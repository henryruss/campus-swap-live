"""Tests for Spec #D2: delivery route optimization.

Run with: python3 -m pytest test_delivery_route_optimize.py -v

Coverage:
- Waypoint grouping (same address collapses to one waypoint)
- Nearest-neighbour + 2-opt correctness on a known layout
- Google Routes parsing: success, bad permutation, HTTP error, no key → fallback
- optimize_delivery_route(): stop_order writes, completed stops frozen,
  anchor selection, ungeocoded stops parked at the end
- Plan caching: unchanged route re-serves without calling Google
- Route guards + end-to-end POST from ops and crew
"""

import pytest
from decimal import Decimal
from datetime import datetime, timedelta, date
from unittest.mock import patch, MagicMock
import uuid


def _uid():
    return uuid.uuid4().hex[:10]


# Chapel Hill-ish coordinates. Warehouse is the Carrboro default.
WAREHOUSE = (35.9030324, -79.0709049)


@pytest.fixture(scope='module')
def route_client():
    from app import app as _app, db
    from models import AppSetting

    _app.config['TESTING'] = True
    _app.config['WTF_CSRF_ENABLED'] = False
    _app.config['SECRET_KEY'] = 'test-secret-route'
    _app.config['SERVER_NAME'] = 'localhost'

    with _app.test_client() as client:
        with _app.app_context():
            AppSetting.set('warehouse_lat', str(WAREHOUSE[0]))
            AppSetting.set('warehouse_lng', str(WAREHOUSE[1]))
            db.session.commit()
            yield client


@pytest.fixture
def delivery_shift(route_client):
    """A delivery shift with 4 stops on truck 1, at known coordinates.

    Returns dict with shift_id, stop_ids (in creation order), worker_id, admin_id.
    """
    from app import app as _app, db
    from models import (User, InventoryItem, BuyerOrder, Order, Shift, ShiftWeek,
                        ShiftAssignment, DeliveryStop)
    tag = _uid()
    with _app.app_context():
        seller = User(email=f'rt_seller_{tag}@test.com', full_name='Route Seller', is_seller=True)
        buyer = User(email=f'rt_buyer_{tag}@test.com', full_name='Route Buyer')
        worker = User(email=f'rt_worker_{tag}@test.com', full_name='Route Driver', is_worker=True)
        worker.set_password('testpass123')
        admin = User(email=f'rt_admin_{tag}@test.com', full_name='Route Admin', is_admin=True)
        admin.set_password('testpass123')
        db.session.add_all([seller, buyer, worker, admin])
        db.session.flush()

        # week_start is unique per (week_start, is_tutorial) — reuse across tests
        # rather than colliding on the second fixture build.
        week = ShiftWeek.query.filter_by(week_start=date(2026, 8, 17), is_tutorial=False).first()
        if not week:
            week = ShiftWeek(week_start=date(2026, 8, 17), status='published')
            db.session.add(week)
            db.session.flush()
        shift = Shift(week_id=week.id, day_of_week='mon', slot='am', trucks=1)
        db.session.add(shift)
        db.session.flush()
        db.session.add(ShiftAssignment(shift_id=shift.id, worker_id=worker.id,
                                       role_on_shift='driver', truck_number=1))

        # Deliberately created in a bad geographic order so a correct optimizer
        # must reorder them. Roughly: far NE, near W, mid N, far NE again (same
        # address as the first, to exercise grouping).
        specs = [
            ('900 MLK Jr Blvd, Chapel Hill, NC 27514', 35.9450, -79.0550),
            ('12 Cameron Ave, Chapel Hill, NC 27599', 35.9100, -79.0550),
            ('55 Rosemary St, Chapel Hill, NC 27514', 35.9160, -79.0620),
            ('900 MLK Jr Blvd, Chapel Hill, NC 27514', 35.9450, -79.0550),
        ]
        stop_ids = []
        order = Order(buyer_id=buyer.id, buyer_email=buyer.email, status='paid')
        db.session.add(order)
        db.session.flush()
        for i, (addr, lat, lng) in enumerate(specs):
            item = InventoryItem(description=f'Route Item {i}', price=Decimal('40.00'),
                                 status='sold', seller_id=seller.id)
            db.session.add(item)
            db.session.flush()
            bo = BuyerOrder(item_id=item.id, order_id=order.id, buyer_email=buyer.email,
                            delivery_address=addr, delivery_lat=lat, delivery_lng=lng)
            db.session.add(bo)
            db.session.flush()
            stop = DeliveryStop(shift_id=shift.id, buyer_order_id=bo.id, truck_number=1,
                                stop_order=i + 1, status='pending')
            db.session.add(stop)
            db.session.flush()
            stop_ids.append(stop.id)
        db.session.commit()
        ctx = {'shift_id': shift.id, 'stop_ids': stop_ids,
               'worker_id': worker.id, 'admin_id': admin.id,
               'worker_email': worker.email, 'admin_email': admin.email,
               'order_id': order.id,
               'item_ids': [bo.item_id for bo in BuyerOrder.query.filter_by(order_id=order.id)],
               'user_ids': [seller.id, buyer.id, worker.id, admin.id]}

    yield ctx

    # Teardown — 30 tests' worth of fixture rows would otherwise pile up in the
    # shared snapshot DB. Delete in FK dependency order; the ShiftWeek is shared
    # across tests so it stays.
    from sqlalchemy import delete
    from models import DeliveryRoutePlan
    with _app.app_context():
        db.session.execute(delete(DeliveryRoutePlan).where(
            DeliveryRoutePlan.shift_id == ctx['shift_id']))
        db.session.execute(delete(DeliveryStop).where(
            DeliveryStop.shift_id == ctx['shift_id']))
        db.session.execute(delete(BuyerOrder).where(BuyerOrder.order_id == ctx['order_id']))
        db.session.execute(delete(Order).where(Order.id == ctx['order_id']))
        db.session.execute(delete(InventoryItem).where(InventoryItem.id.in_(ctx['item_ids'])))
        db.session.execute(delete(ShiftAssignment).where(
            ShiftAssignment.shift_id == ctx['shift_id']))
        db.session.execute(delete(Shift).where(Shift.id == ctx['shift_id']))
        db.session.execute(delete(User).where(User.id.in_(ctx['user_ids'])))
        db.session.commit()


def _login(client, email, password='testpass123'):
    return client.post('/login', data={'email': email, 'password': password}, follow_redirects=True)


def _logout(client):
    client.get('/logout', follow_redirects=True)


def _stop_orders(app, stop_ids):
    from models import DeliveryStop
    with app.app_context():
        return [DeliveryStop.query.get(sid).stop_order for sid in stop_ids]


# ---------------------------------------------------------------------------
# Waypoint grouping
# ---------------------------------------------------------------------------

class TestWaypointGrouping:

    def test_same_address_collapses_to_one_waypoint(self, route_client, delivery_shift):
        """Stops 0 and 3 share an address → 3 waypoints for 4 stops."""
        from app import app as _app, _group_delivery_waypoints
        from models import DeliveryStop
        with _app.app_context():
            stops = DeliveryStop.query.filter_by(shift_id=delivery_shift['shift_id']).all()
            groups, ungeocoded = _group_delivery_waypoints(stops)
            assert len(groups) == 3
            assert not ungeocoded
            sizes = sorted(len(g['stops']) for g in groups)
            assert sizes == [1, 1, 2]

    def test_ungeocoded_stops_separated(self, route_client, delivery_shift):
        from app import app as _app, _group_delivery_waypoints, db
        from models import DeliveryStop
        with _app.app_context():
            stops = DeliveryStop.query.filter_by(shift_id=delivery_shift['shift_id']).all()
            stops[0].buyer_order.delivery_lat = None
            stops[0].buyer_order.delivery_lng = None
            db.session.commit()
            groups, ungeocoded = _group_delivery_waypoints(stops)
            assert len(ungeocoded) == 1
            assert sum(len(g['stops']) for g in groups) == 3


# ---------------------------------------------------------------------------
# Nearest-neighbour + 2-opt
# ---------------------------------------------------------------------------

class TestNearestNeighbour:

    def test_orders_points_along_a_line(self, route_client):
        """Points strung out along a line get visited in order, not zig-zag."""
        from app import _optimize_order_nearest_neighbour
        origin = (35.90, -79.07)
        # Shuffled input; correct answer walks north.
        pts = [(35.94, -79.07), (35.91, -79.07), (35.93, -79.07), (35.92, -79.07)]
        order = _optimize_order_nearest_neighbour(origin, pts, origin)
        assert [pts[i][0] for i in order] == [35.91, 35.92, 35.93, 35.94]

    def test_two_opt_beats_plain_nearest_neighbour(self, route_client):
        """2-opt must never return a longer path than the NN seed."""
        from app import _optimize_order_nearest_neighbour, _path_length_miles, haversine_miles
        origin = WAREHOUSE
        pts = [(35.9450, -79.0550), (35.9100, -79.0550), (35.9160, -79.0620),
               (35.9500, -79.1000), (35.8900, -79.0300)]

        # Plain NN, no refinement
        unvisited, cur, nn_order = set(range(len(pts))), origin, []
        while unvisited:
            nxt = min(unvisited, key=lambda i: haversine_miles(cur[0], cur[1], pts[i][0], pts[i][1]))
            nn_order.append(nxt)
            cur = pts[nxt]
            unvisited.discard(nxt)
        nn_len = _path_length_miles(origin, [pts[i] for i in nn_order], origin)

        order = _optimize_order_nearest_neighbour(origin, pts, origin)
        assert sorted(order) == list(range(len(pts)))  # a real permutation
        assert _path_length_miles(origin, [pts[i] for i in order], origin) <= nn_len + 1e-9

    def test_handles_empty_and_single(self, route_client):
        from app import _optimize_order_nearest_neighbour
        assert _optimize_order_nearest_neighbour(WAREHOUSE, [], WAREHOUSE) == []
        assert _optimize_order_nearest_neighbour(WAREHOUSE, [(35.9, -79.0)], WAREHOUSE) == [0]


# ---------------------------------------------------------------------------
# Google Routes API adapter
# ---------------------------------------------------------------------------

def _routes_response(order, distance=12345, duration='1830s'):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {'routes': [{
        'optimizedIntermediateWaypointIndex': order,
        'distanceMeters': distance,
        'duration': duration,
    }]}
    return resp


class TestGoogleAdapter:

    def test_parses_successful_response(self, route_client):
        from app import app as _app, _optimize_order_google
        pts = [(35.94, -79.05), (35.91, -79.05), (35.92, -79.06)]
        with _app.app_context(), \
             patch.dict('os.environ', {'GOOGLE_MAPS_API_KEY': 'test-key', 'GOOGLE_ROUTES_API_KEY': ''}), \
             patch('requests.post', return_value=_routes_response([2, 1, 0])) as mock_post:
            result = _optimize_order_google(WAREHOUSE, pts, WAREHOUSE)

        assert result == ([2, 1, 0], 12345, 1830)
        body = mock_post.call_args.kwargs['json']
        assert body['optimizeWaypointOrder'] is True
        assert len(body['intermediates']) == 3
        assert body['origin']['location']['latLng']['latitude'] == WAREHOUSE[0]

    def test_rejects_incomplete_permutation(self, route_client):
        """A short/duplicated index list would silently drop stops — must fall back."""
        from app import app as _app, _optimize_order_google
        pts = [(35.94, -79.05), (35.91, -79.05), (35.92, -79.06)]
        with _app.app_context(), \
             patch.dict('os.environ', {'GOOGLE_MAPS_API_KEY': 'test-key', 'GOOGLE_ROUTES_API_KEY': ''}), \
             patch('requests.post', return_value=_routes_response([0, 1])):
            assert _optimize_order_google(WAREHOUSE, pts, WAREHOUSE) is None

    def test_http_error_returns_none(self, route_client):
        from app import app as _app, _optimize_order_google
        bad = MagicMock()
        bad.status_code = 403
        bad.text = 'PERMISSION_DENIED'
        with _app.app_context(), \
             patch.dict('os.environ', {'GOOGLE_MAPS_API_KEY': 'test-key', 'GOOGLE_ROUTES_API_KEY': ''}), \
             patch('requests.post', return_value=bad):
            assert _optimize_order_google(WAREHOUSE, [(35.9, -79.0)], WAREHOUSE) is None

    def test_network_exception_returns_none(self, route_client):
        from app import app as _app, _optimize_order_google
        with _app.app_context(), \
             patch.dict('os.environ', {'GOOGLE_MAPS_API_KEY': 'test-key', 'GOOGLE_ROUTES_API_KEY': ''}), \
             patch('requests.post', side_effect=OSError('connection reset')):
            assert _optimize_order_google(WAREHOUSE, [(35.9, -79.0)], WAREHOUSE) is None

    def test_no_key_returns_none(self, route_client):
        from app import app as _app, _optimize_order_google
        with _app.app_context(), patch.dict('os.environ', {'GOOGLE_MAPS_API_KEY': '', 'GOOGLE_ROUTES_API_KEY': ''}):
            assert _optimize_order_google(WAREHOUSE, [(35.9, -79.0)], WAREHOUSE) is None

    def test_over_waypoint_cap_skips_api(self, route_client):
        from app import app as _app, _optimize_order_google, ROUTES_MAX_WAYPOINTS
        pts = [(35.9 + i * 0.001, -79.0) for i in range(ROUTES_MAX_WAYPOINTS + 1)]
        with _app.app_context(), \
             patch.dict('os.environ', {'GOOGLE_MAPS_API_KEY': 'test-key', 'GOOGLE_ROUTES_API_KEY': ''}), \
             patch('requests.post') as mock_post:
            assert _optimize_order_google(WAREHOUSE, pts, WAREHOUSE) is None
            mock_post.assert_not_called()


# ---------------------------------------------------------------------------
# optimize_delivery_route()
# ---------------------------------------------------------------------------

class TestOptimizeDeliveryRoute:

    def test_writes_contiguous_stop_order(self, route_client, delivery_shift):
        from app import app as _app, optimize_delivery_route
        from models import Shift, DeliveryStop
        with _app.app_context(), patch.dict('os.environ', {'GOOGLE_MAPS_API_KEY': '', 'GOOGLE_ROUTES_API_KEY': ''}):
            shift = Shift.query.get(delivery_shift['shift_id'])
            result = optimize_delivery_route(shift, 1)
            assert result['ok']
            assert result['method'] == 'nearest_neighbor'

            stops = DeliveryStop.query.filter_by(shift_id=shift.id).all()
            orders = sorted(s.stop_order for s in stops)
            assert orders == [1, 2, 3, 4]

    def test_same_address_stops_stay_adjacent(self, route_client, delivery_shift):
        """The two stops at 900 MLK must be consecutive — one doorstep, one visit."""
        from app import app as _app, optimize_delivery_route
        from models import Shift, DeliveryStop
        with _app.app_context(), patch.dict('os.environ', {'GOOGLE_MAPS_API_KEY': '', 'GOOGLE_ROUTES_API_KEY': ''}):
            shift = Shift.query.get(delivery_shift['shift_id'])
            optimize_delivery_route(shift, 1)
            mlk = [s.stop_order for s in DeliveryStop.query.filter_by(shift_id=shift.id).all()
                   if '900 MLK' in s.buyer_order.delivery_address]
            assert abs(mlk[0] - mlk[1]) == 1

    def test_message_reports_stops_and_addresses_separately(self, route_client, delivery_shift):
        """4 stops at 3 addresses — the summary must not read '3 stops ordered'."""
        from app import app as _app, optimize_delivery_route
        from models import Shift
        with _app.app_context(), \
             patch.dict('os.environ', {'GOOGLE_MAPS_API_KEY': '', 'GOOGLE_ROUTES_API_KEY': ''}):
            shift = Shift.query.get(delivery_shift['shift_id'])
            result = optimize_delivery_route(shift, 1)
            assert '4 stops at 3 addresses' in result['message']

    def test_message_says_stops_ordered_when_one_per_address(self, route_client, delivery_shift):
        from app import app as _app, optimize_delivery_route, db
        from models import Shift, DeliveryStop
        with _app.app_context(), \
             patch.dict('os.environ', {'GOOGLE_MAPS_API_KEY': '', 'GOOGLE_ROUTES_API_KEY': ''}):
            # Remove the duplicate-address stop so stops == addresses
            dup = DeliveryStop.query.get(delivery_shift['stop_ids'][3])
            db.session.delete(dup)
            db.session.commit()
            shift = Shift.query.get(delivery_shift['shift_id'])
            result = optimize_delivery_route(shift, 1)
            assert '3 stops ordered' in result['message']

    def test_completed_stops_are_frozen_at_the_front(self, route_client, delivery_shift):
        """A delivered stop keeps position 1 and is never reshuffled."""
        from app import app as _app, optimize_delivery_route, db
        from models import Shift, DeliveryStop
        first_id = delivery_shift['stop_ids'][1]  # 12 Cameron Ave
        with _app.app_context(), patch.dict('os.environ', {'GOOGLE_MAPS_API_KEY': '', 'GOOGLE_ROUTES_API_KEY': ''}):
            done = DeliveryStop.query.get(first_id)
            done.status = 'completed'
            done.completed_at = datetime.utcnow()
            db.session.commit()

            shift = Shift.query.get(delivery_shift['shift_id'])
            result = optimize_delivery_route(shift, 1)
            assert result['ok']
            assert DeliveryStop.query.get(first_id).stop_order == 1
            pending_orders = sorted(
                s.stop_order for s in DeliveryStop.query.filter_by(shift_id=shift.id).all()
                if s.status == 'pending'
            )
            assert pending_orders == [2, 3, 4]

    def test_anchor_is_last_completed_stop(self, route_client, delivery_shift):
        """With a stop delivered, the optimizer routes from there, not the warehouse."""
        from app import app as _app, optimize_delivery_route, db
        from models import Shift, DeliveryStop, DeliveryRoutePlan
        done_id = delivery_shift['stop_ids'][1]
        with _app.app_context(), patch.dict('os.environ', {'GOOGLE_MAPS_API_KEY': '', 'GOOGLE_ROUTES_API_KEY': ''}):
            done = DeliveryStop.query.get(done_id)
            done.status = 'completed'
            db.session.commit()

            shift = Shift.query.get(delivery_shift['shift_id'])
            optimize_delivery_route(shift, 1)
            plan = DeliveryRoutePlan.query.filter_by(shift_id=shift.id, truck_number=1).first()
            assert plan.anchor_label == '12 Cameron Ave'

    def test_from_warehouse_ignores_completed_anchor(self, route_client, delivery_shift):
        """Ops plans the shift, so the loop always starts and ends at the warehouse."""
        from app import app as _app, optimize_delivery_route, db, get_warehouse_address
        from models import Shift, DeliveryStop, DeliveryRoutePlan
        from urllib.parse import parse_qs, urlparse
        with _app.app_context(), \
             patch.dict('os.environ', {'GOOGLE_MAPS_API_KEY': '', 'GOOGLE_ROUTES_API_KEY': ''}):
            done = DeliveryStop.query.get(delivery_shift['stop_ids'][1])
            done.status = 'completed'
            db.session.commit()

            shift = Shift.query.get(delivery_shift['shift_id'])
            optimize_delivery_route(shift, 1, from_warehouse=True)
            plan = DeliveryRoutePlan.query.filter_by(shift_id=shift.id, truck_number=1).first()

            assert plan.anchor_label == 'Warehouse'
            qs = parse_qs(urlparse(plan.maps_url).query)
            assert qs['origin'][0] == get_warehouse_address()
            assert qs['destination'][0] == get_warehouse_address()

    def test_ops_and_crew_plans_do_not_reuse_each_other(self, route_client, delivery_shift):
        """Different questions about the same truck must not share a cached answer."""
        from app import app as _app, optimize_delivery_route, db
        from models import Shift, DeliveryStop
        with _app.app_context(), \
             patch.dict('os.environ', {'GOOGLE_MAPS_API_KEY': '', 'GOOGLE_ROUTES_API_KEY': ''}):
            done = DeliveryStop.query.get(delivery_shift['stop_ids'][1])
            done.status = 'completed'
            db.session.commit()

            shift = Shift.query.get(delivery_shift['shift_id'])
            optimize_delivery_route(shift, 1, from_warehouse=True)
            crew = optimize_delivery_route(shift, 1, from_warehouse=False)
            assert crew['reused'] is False
            ops = optimize_delivery_route(shift, 1, from_warehouse=True)
            assert ops['reused'] is False

    def test_anchor_is_warehouse_when_nothing_delivered(self, route_client, delivery_shift):
        from app import app as _app, optimize_delivery_route
        from models import Shift, DeliveryRoutePlan
        with _app.app_context(), patch.dict('os.environ', {'GOOGLE_MAPS_API_KEY': '', 'GOOGLE_ROUTES_API_KEY': ''}):
            shift = Shift.query.get(delivery_shift['shift_id'])
            optimize_delivery_route(shift, 1)
            plan = DeliveryRoutePlan.query.filter_by(shift_id=shift.id, truck_number=1).first()
            assert plan.anchor_label == 'Warehouse'

    def test_ungeocoded_stops_parked_at_end(self, route_client, delivery_shift):
        from app import app as _app, optimize_delivery_route, db
        from models import Shift, DeliveryStop
        orphan_id = delivery_shift['stop_ids'][2]
        with _app.app_context(), patch.dict('os.environ', {'GOOGLE_MAPS_API_KEY': '', 'GOOGLE_ROUTES_API_KEY': ''}):
            orphan = DeliveryStop.query.get(orphan_id)
            orphan.buyer_order.delivery_lat = None
            orphan.buyer_order.delivery_lng = None
            db.session.commit()

            shift = Shift.query.get(delivery_shift['shift_id'])
            result = optimize_delivery_route(shift, 1)
            assert result['ungeocoded'] == 1
            assert DeliveryStop.query.get(orphan_id).stop_order == 4
            assert 'without an address on file' in result['message']

    def test_uses_google_order_when_available(self, route_client, delivery_shift):
        from app import app as _app, optimize_delivery_route
        from models import Shift, DeliveryStop, DeliveryRoutePlan
        with _app.app_context(), \
             patch.dict('os.environ', {'GOOGLE_MAPS_API_KEY': 'test-key', 'GOOGLE_ROUTES_API_KEY': ''}), \
             patch('requests.post', return_value=_routes_response([2, 0, 1])):
            shift = Shift.query.get(delivery_shift['shift_id'])
            result = optimize_delivery_route(shift, 1)
            assert result['method'] == 'google'
            plan = DeliveryRoutePlan.query.filter_by(shift_id=shift.id, truck_number=1).first()
            assert plan.distance_meters == 12345
            assert plan.duration_seconds == 1830
            assert plan.distance_miles == 7.7
            assert plan.duration_display == '30 min'
            # Group index 2 (55 Rosemary) was placed first by the mocked response
            first = [s for s in DeliveryStop.query.filter_by(shift_id=shift.id).all()
                     if s.stop_order == 1][0]
            assert '55 Rosemary' in first.buyer_order.delivery_address

    def test_falls_back_when_google_fails(self, route_client, delivery_shift):
        from app import app as _app, optimize_delivery_route
        from models import Shift
        bad = MagicMock()
        bad.status_code = 500
        bad.text = 'boom'
        with _app.app_context(), \
             patch.dict('os.environ', {'GOOGLE_MAPS_API_KEY': 'test-key', 'GOOGLE_ROUTES_API_KEY': ''}), \
             patch('requests.post', return_value=bad):
            shift = Shift.query.get(delivery_shift['shift_id'])
            result = optimize_delivery_route(shift, 1)
            assert result['ok']
            assert result['method'] == 'nearest_neighbor'
            assert 'maps unavailable' in result['message']

    def test_maps_url_is_a_loop_back_to_warehouse(self, route_client, delivery_shift):
        from app import app as _app, optimize_delivery_route, get_warehouse_address
        from models import Shift, DeliveryRoutePlan
        from urllib.parse import parse_qs, urlparse
        with _app.app_context(), patch.dict('os.environ', {'GOOGLE_MAPS_API_KEY': '', 'GOOGLE_ROUTES_API_KEY': ''}):
            shift = Shift.query.get(delivery_shift['shift_id'])
            optimize_delivery_route(shift, 1)
            plan = DeliveryRoutePlan.query.filter_by(shift_id=shift.id, truck_number=1).first()
            qs = parse_qs(urlparse(plan.maps_url).query)
            assert qs['destination'][0] == get_warehouse_address()
            assert qs['origin'][0] == get_warehouse_address()
            assert len(qs['waypoints'][0].split('|')) == 3

    def test_maps_url_uses_coordinates_not_address_text(self, route_client, delivery_shift):
        """Waypoints must be lat,lng — address text is ambiguous without city/state."""
        from app import app as _app, optimize_delivery_route
        from models import Shift, DeliveryRoutePlan
        from urllib.parse import parse_qs, urlparse
        with _app.app_context(), \
             patch.dict('os.environ', {'GOOGLE_MAPS_API_KEY': '', 'GOOGLE_ROUTES_API_KEY': ''}):
            shift = Shift.query.get(delivery_shift['shift_id'])
            optimize_delivery_route(shift, 1)
            plan = DeliveryRoutePlan.query.filter_by(shift_id=shift.id, truck_number=1).first()
            qs = parse_qs(urlparse(plan.maps_url).query)
            for wp in qs['waypoints'][0].split('|'):
                lat, lng = wp.split(',')
                assert 35.0 < float(lat) < 36.5
                assert -80.0 < float(lng) < -78.5

    def test_mid_run_maps_origin_is_never_a_bare_street(self, route_client, delivery_shift):
        """Regression: anchor_label is display-only. Using it as the Maps origin sent a
        Chapel Hill route to a same-named street in Louisiana."""
        from app import app as _app, optimize_delivery_route, db
        from models import Shift, DeliveryStop, DeliveryRoutePlan
        from urllib.parse import parse_qs, urlparse
        with _app.app_context(), \
             patch.dict('os.environ', {'GOOGLE_MAPS_API_KEY': '', 'GOOGLE_ROUTES_API_KEY': ''}):
            done = DeliveryStop.query.get(delivery_shift['stop_ids'][1])
            done.status = 'completed'
            db.session.commit()

            shift = Shift.query.get(delivery_shift['shift_id'])
            optimize_delivery_route(shift, 1)
            plan = DeliveryRoutePlan.query.filter_by(shift_id=shift.id, truck_number=1).first()

            # Display label stays human-readable...
            assert plan.anchor_label == '12 Cameron Ave'
            # ...but the link must carry coordinates, not that city-less string.
            origin = parse_qs(urlparse(plan.maps_url).query)['origin'][0]
            assert origin != '12 Cameron Ave'
            lat, lng = origin.split(',')
            assert round(float(lat), 4) == 35.9100
            assert round(float(lng), 4) == -79.0550

    def test_no_stops_returns_not_ok(self, route_client, delivery_shift):
        from app import app as _app, optimize_delivery_route
        from models import Shift
        with _app.app_context():
            shift = Shift.query.get(delivery_shift['shift_id'])
            result = optimize_delivery_route(shift, 99)
            assert not result['ok']
            assert 'No delivery stops' in result['message']

    def test_all_resolved_returns_not_ok(self, route_client, delivery_shift):
        from app import app as _app, optimize_delivery_route, db
        from models import Shift, DeliveryStop
        with _app.app_context():
            for s in DeliveryStop.query.filter_by(shift_id=delivery_shift['shift_id']).all():
                s.status = 'completed'
            db.session.commit()
            shift = Shift.query.get(delivery_shift['shift_id'])
            result = optimize_delivery_route(shift, 1)
            assert not result['ok']
            assert 'already resolved' in result['message']


# ---------------------------------------------------------------------------
# Plan caching
# ---------------------------------------------------------------------------

class TestPlanCaching:

    def test_second_click_skips_the_api(self, route_client, delivery_shift):
        """Unchanged route → no second billable call."""
        from app import app as _app, optimize_delivery_route
        from models import Shift
        with _app.app_context(), \
             patch.dict('os.environ', {'GOOGLE_MAPS_API_KEY': 'test-key', 'GOOGLE_ROUTES_API_KEY': ''}), \
             patch('requests.post', return_value=_routes_response([0, 1, 2])) as mock_post:
            shift = Shift.query.get(delivery_shift['shift_id'])
            optimize_delivery_route(shift, 1)
            assert mock_post.call_count == 1

            second = optimize_delivery_route(shift, 1)
            assert mock_post.call_count == 1  # not called again
            assert second['reused'] is True
            assert 'already optimized' in second['message']

    def test_removing_a_stop_invalidates_the_plan(self, route_client, delivery_shift):
        from app import app as _app, optimize_delivery_route, db
        from models import Shift, DeliveryStop
        with _app.app_context(), \
             patch.dict('os.environ', {'GOOGLE_MAPS_API_KEY': 'test-key', 'GOOGLE_ROUTES_API_KEY': ''}), \
             patch('requests.post', return_value=_routes_response([0, 1, 2])) as mock_post:
            shift = Shift.query.get(delivery_shift['shift_id'])
            optimize_delivery_route(shift, 1)
            assert mock_post.call_count == 1

            # Drop one waypoint → hash changes → recompute
            doomed = DeliveryStop.query.get(delivery_shift['stop_ids'][1])
            db.session.delete(doomed)
            db.session.commit()

            mock_post.return_value = _routes_response([0, 1])
            result = optimize_delivery_route(shift, 1)
            assert mock_post.call_count == 2
            assert result['reused'] is False

    def test_version_bump_invalidates_stored_plans(self, route_client, delivery_shift):
        """A stored plan whose URL format is now wrong must recompute, not be reused."""
        from app import app as _app, optimize_delivery_route, db
        from models import Shift, DeliveryRoutePlan
        with _app.app_context(), \
             patch.dict('os.environ', {'GOOGLE_MAPS_API_KEY': '', 'GOOGLE_ROUTES_API_KEY': ''}):
            shift = Shift.query.get(delivery_shift['shift_id'])
            optimize_delivery_route(shift, 1)
            plan = DeliveryRoutePlan.query.filter_by(shift_id=shift.id, truck_number=1).first()

            # Simulate a plan stored by the previous version
            plan.plan_hash = plan.plan_hash.replace(plan.plan_hash[:4], 'old0')
            db.session.commit()

            result = optimize_delivery_route(shift, 1)
            assert result['reused'] is False

    def test_completing_a_stop_invalidates_the_plan(self, route_client, delivery_shift):
        """Anchor moves as the driver progresses, so the cache must miss."""
        from app import app as _app, optimize_delivery_route, db
        from models import Shift, DeliveryStop
        with _app.app_context(), patch.dict('os.environ', {'GOOGLE_MAPS_API_KEY': '', 'GOOGLE_ROUTES_API_KEY': ''}):
            shift = Shift.query.get(delivery_shift['shift_id'])
            optimize_delivery_route(shift, 1)

            first = [s for s in DeliveryStop.query.filter_by(shift_id=shift.id).all()
                     if s.stop_order == 1][0]
            first.status = 'completed'
            db.session.commit()

            result = optimize_delivery_route(shift, 1)
            assert result['reused'] is False


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

class TestRoutes:

    def test_ops_route_requires_ops_access(self, route_client, delivery_shift):
        from app import app as _app, db
        from models import User
        tag = _uid()
        with _app.app_context():
            nobody = User(email=f'rt_nobody_{tag}@test.com', full_name='Nobody')
            nobody.set_password('testpass123')
            db.session.add(nobody)
            db.session.commit()

        _login(route_client, f'rt_nobody_{tag}@test.com')
        resp = route_client.post(
            f"/admin/ops/delivery/{delivery_shift['shift_id']}/truck/1/optimize")
        _logout(route_client)
        with _app.app_context():
            User.query.filter_by(email=f'rt_nobody_{tag}@test.com').delete()
            db.session.commit()
        assert resp.status_code == 403

    def test_ops_route_optimizes(self, route_client, delivery_shift):
        from app import app as _app
        from models import DeliveryRoutePlan
        _login(route_client, delivery_shift['admin_email'])
        with patch.dict('os.environ', {'GOOGLE_MAPS_API_KEY': '', 'GOOGLE_ROUTES_API_KEY': ''}):
            resp = route_client.post(
                f"/admin/ops/delivery/{delivery_shift['shift_id']}/truck/1/optimize")
        _logout(route_client)

        assert resp.status_code == 302
        with _app.app_context():
            plan = DeliveryRoutePlan.query.filter_by(
                shift_id=delivery_shift['shift_id'], truck_number=1).first()
            assert plan is not None
            assert plan.stop_count == 4

    def test_crew_route_optimizes_own_truck(self, route_client, delivery_shift):
        from app import app as _app
        from models import DeliveryRoutePlan
        _login(route_client, delivery_shift['worker_email'])
        with patch.dict('os.environ', {'GOOGLE_MAPS_API_KEY': '', 'GOOGLE_ROUTES_API_KEY': ''}):
            resp = route_client.post(f"/crew/delivery/{delivery_shift['shift_id']}/optimize")
        _logout(route_client)

        assert resp.status_code == 302
        with _app.app_context():
            plan = DeliveryRoutePlan.query.filter_by(
                shift_id=delivery_shift['shift_id'], truck_number=1).first()
            assert plan is not None

    def test_crew_route_rejects_non_worker(self, route_client, delivery_shift):
        from app import app as _app, db
        from models import User
        tag = _uid()
        with _app.app_context():
            civilian = User(email=f'rt_civ_{tag}@test.com', full_name='Civilian')
            civilian.set_password('testpass123')
            db.session.add(civilian)
            db.session.commit()

        _login(route_client, f'rt_civ_{tag}@test.com')
        resp = route_client.post(f"/crew/delivery/{delivery_shift['shift_id']}/optimize")
        _logout(route_client)
        with _app.app_context():
            User.query.filter_by(email=f'rt_civ_{tag}@test.com').delete()
            db.session.commit()
        assert resp.status_code == 403

    def test_crew_delivery_page_renders_optimize_button(self, route_client, delivery_shift):
        _login(route_client, delivery_shift['worker_email'])
        resp = route_client.get(f"/crew/delivery/{delivery_shift['shift_id']}")
        _logout(route_client)
        assert resp.status_code == 200
        assert b'Optimize route' in resp.data
        assert b'Full loop from the warehouse and back' in resp.data
