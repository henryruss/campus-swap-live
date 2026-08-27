"""Tests for the crew delivery loading checklist and proof of delivery.

Run with: python3 -m pytest test_delivery_loading.py -v

Driver feedback, three asks:
  - group the delivery list by storage unit so a unit can be cleared in one pass
  - mark each item "Loaded" as it goes on the truck
  - photograph the drop-off, and show the buyer the photo and the time

Coverage:
- _group_stops_by_storage_unit(): unit grouping, row ordering, unlocated bucket
- POST /crew/delivery/stop/<id>/loaded: toggle, idempotency, auth, JSON counts
- Loading state is independent of delivery status and of stop_order
- Crew page renders the checklist and the on-truck badge
- Proof of delivery: photo stored + stamped, required-unless-explained, non-image
  rejected, issue flags exempt
- The delivered email carries every stop's photo and the delivery time

SAFE SUITE: defines its own fixtures, never touches the root conftest `app`/`db`
fixtures, and deletes its own rows in teardown. Do not add `app` or `db` as a
fixture parameter here — that repoints the URI and drop_all()s campusswap_prod.
"""

import pytest
from decimal import Decimal
from datetime import date, datetime, timedelta
import uuid


def _uid():
    return uuid.uuid4().hex[:10]


@pytest.fixture(autouse=True)
def _never_send_real_email():
    """Hard block on outbound mail for every test in this module.

    Not optional. The local .env carries a live RESEND_API_KEY, and these routes
    now email real super admins on an issue flag — a test that resolves a stop
    outside its own patch() block sends Henry an actual email. That happened.
    Tests that need to inspect the calls still nest their own patch() inside this
    one; the inner mock wins for the duration of its block.
    """
    from unittest.mock import patch
    with patch('app.send_email', return_value=True) as m:
        yield m


@pytest.fixture(scope='module')
def load_client():
    from app import app as _app

    _app.config['TESTING'] = True
    _app.config['WTF_CSRF_ENABLED'] = False
    _app.config['SECRET_KEY'] = 'test-secret-loading'
    _app.config['SERVER_NAME'] = 'localhost'
    with _app.test_client() as client:
        yield client


@pytest.fixture
def loading_shift(load_client):
    """A delivery shift whose 5 stops span two storage units plus one unlocated item.

    Rows are deliberately assigned out of walking order so the grouping has something
    to sort. Returns a dict of ids keyed for readability.
    """
    from app import app as _app, db
    from models import (User, InventoryItem, BuyerOrder, Order, Shift, ShiftWeek,
                        ShiftAssignment, DeliveryStop, StorageLocation)
    tag = _uid()
    with _app.app_context():
        seller = User(email=f'ld_seller_{tag}@test.com', full_name='Load Seller', is_seller=True)
        buyer = User(email=f'ld_buyer_{tag}@test.com', full_name='Load Buyer')
        worker = User(email=f'ld_worker_{tag}@test.com', full_name='Load Driver', is_worker=True)
        worker.set_password('testpass123')
        admin = User(email=f'ld_admin_{tag}@test.com', full_name='Load Admin', is_admin=True)
        admin.set_password('testpass123')
        db.session.add_all([seller, buyer, worker, admin])
        db.session.flush()

        unit_a = StorageLocation(name=f'Unit A {tag}', address='515 S Greensboro St')
        unit_b = StorageLocation(name=f'Unit B {tag}', address='9 Elsewhere Rd')
        db.session.add_all([unit_a, unit_b])
        db.session.flush()

        # Anchored to the current week, not a fixed date. The loading checklist is
        # hidden on a past shift (`is_past`), so a hardcoded date silently stops
        # exercising it the day it rolls into the past.
        from app import _today_eastern
        _today = _today_eastern()
        _week_start = _today - timedelta(days=_today.weekday())
        _dow = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'][_today.weekday()]

        week = ShiftWeek.query.filter_by(week_start=_week_start, is_tutorial=False).first()
        if not week:
            week = ShiftWeek(week_start=_week_start, status='published')
            db.session.add(week)
            db.session.flush()
        shift = Shift(week_id=week.id, day_of_week=_dow, slot='am', trucks=1)
        db.session.add(shift)
        db.session.flush()
        db.session.add(ShiftAssignment(shift_id=shift.id, worker_id=worker.id,
                                       role_on_shift='driver', truck_number=1))

        # (storage unit, row). back_left before front_left on purpose — the grouping
        # must reorder them front-to-back, which is not the enum's alpha order.
        specs = [
            (unit_a, 'back_left'),
            (unit_b, 'middle_right'),
            (unit_a, 'front_left'),
            (None,   None),            # never assigned a unit
            (unit_a, 'front_left'),
        ]
        stop_ids = []
        order = Order(buyer_id=buyer.id, buyer_email=buyer.email, status='paid')
        db.session.add(order)
        db.session.flush()
        for i, (loc, row) in enumerate(specs):
            item = InventoryItem(description=f'Load Item {i}', price=Decimal('40.00'),
                                 status='sold', seller_id=seller.id,
                                 storage_location_id=(loc.id if loc else None),
                                 storage_row=row)
            db.session.add(item)
            db.session.flush()
            bo = BuyerOrder(item_id=item.id, order_id=order.id, buyer_email=buyer.email,
                            delivery_address=f'{100 + i} Test St, Chapel Hill, NC 27514',
                            delivery_lat=35.91 + i / 1000, delivery_lng=-79.05)
            db.session.add(bo)
            db.session.flush()
            stop = DeliveryStop(shift_id=shift.id, buyer_order_id=bo.id, truck_number=1,
                                stop_order=i + 1, status='pending')
            db.session.add(stop)
            db.session.flush()
            stop_ids.append(stop.id)
        db.session.commit()

        ctx = {'shift_id': shift.id, 'stop_ids': stop_ids, 'order_id': order.id,
               'unit_a_id': unit_a.id, 'unit_b_id': unit_b.id,
               'unit_a_name': unit_a.name, 'unit_b_name': unit_b.name,
               'worker_email': worker.email, 'worker_id': worker.id,
               'admin_email': admin.email,
               'item_ids': [bo.item_id for bo in BuyerOrder.query.filter_by(order_id=order.id)],
               'user_ids': [seller.id, buyer.id, worker.id, admin.id]}

    yield ctx

    from sqlalchemy import delete
    from models import DeliveryRoutePlan, DeliveryRun
    with _app.app_context():
        db.session.execute(delete(DeliveryRoutePlan).where(
            DeliveryRoutePlan.shift_id == ctx['shift_id']))
        db.session.execute(delete(DeliveryRun).where(DeliveryRun.shift_id == ctx['shift_id']))
        db.session.execute(delete(DeliveryStop).where(
            DeliveryStop.shift_id == ctx['shift_id']))
        db.session.execute(delete(BuyerOrder).where(BuyerOrder.order_id == ctx['order_id']))
        db.session.execute(delete(Order).where(Order.id == ctx['order_id']))
        db.session.execute(delete(InventoryItem).where(InventoryItem.id.in_(ctx['item_ids'])))
        db.session.execute(delete(ShiftAssignment).where(
            ShiftAssignment.shift_id == ctx['shift_id']))
        db.session.execute(delete(Shift).where(Shift.id == ctx['shift_id']))
        db.session.execute(delete(StorageLocation).where(
            StorageLocation.id.in_([ctx['unit_a_id'], ctx['unit_b_id']])))
        db.session.execute(delete(User).where(User.id.in_(ctx['user_ids'])))
        db.session.commit()


def _login(client, email, password='testpass123'):
    return client.post('/login', data={'email': email, 'password': password},
                       follow_redirects=True)


def _logout(client):
    client.get('/logout', follow_redirects=True)


def _groups(app, shift_id):
    from app import _group_stops_by_storage_unit
    from models import DeliveryStop
    stops = (DeliveryStop.query.filter_by(shift_id=shift_id)
             .order_by(DeliveryStop.stop_order.asc()).all())
    return _group_stops_by_storage_unit(stops)


# ---------------------------------------------------------------------------
# Grouping
# ---------------------------------------------------------------------------

class TestStorageGrouping:

    def test_one_group_per_unit(self, load_client, loading_shift):
        from app import app as _app
        with _app.app_context():
            groups = _groups(_app, loading_shift['shift_id'])
            assert len(groups) == 3          # Unit A, Unit B, unlocated
            assert sum(len(g['stops']) for g in groups) == 5

    def test_units_are_alphabetical_and_unlocated_is_last(self, load_client, loading_shift):
        """Unlocated items are an exception list, not a unit to work through."""
        from app import app as _app
        with _app.app_context():
            groups = _groups(_app, loading_shift['shift_id'])
            assert groups[0]['name'] == loading_shift['unit_a_name']
            assert groups[1]['name'] == loading_shift['unit_b_name']
            assert groups[-1]['location'] is None
            assert groups[-1]['name'] == 'No storage unit assigned'

    def test_unlocated_items_collapse_into_one_group(self, load_client, loading_shift):
        """Regression guard: keying the bucket on the location object rather than its
        id would give every unlocated item a group of its own."""
        from app import app as _app, db
        from models import DeliveryStop, InventoryItem
        with _app.app_context():
            stop = DeliveryStop.query.get(loading_shift['stop_ids'][0])
            item = InventoryItem.query.get(stop.buyer_order.item_id)
            item.storage_location_id = None
            db.session.commit()

            groups = _groups(_app, loading_shift['shift_id'])
            unlocated = [g for g in groups if g['location'] is None]
            assert len(unlocated) == 1
            assert len(unlocated[0]['stops']) == 2

    def test_rows_sort_front_to_back_not_alphabetically(self, load_client, loading_shift):
        """The crew walks a unit front to back; 'back_left' sorts first in the enum."""
        from app import app as _app
        with _app.app_context():
            unit_a = _groups(_app, loading_shift['shift_id'])[0]
            assert [r['key'] for r in unit_a['rows']] == ['front_left', 'back_left']
            assert [r['label'] for r in unit_a['rows']] == ['Front Left', 'Back Left']

    def test_items_in_the_same_row_stay_together(self, load_client, loading_shift):
        from app import app as _app
        with _app.app_context():
            unit_a = _groups(_app, loading_shift['shift_id'])[0]
            front = [r for r in unit_a['rows'] if r['key'] == 'front_left'][0]
            assert len(front['stops']) == 2

    def test_missing_row_is_labelled_not_dropped(self, load_client, loading_shift):
        from app import app as _app
        with _app.app_context():
            groups = _groups(_app, loading_shift['shift_id'])
            unlocated = groups[-1]
            assert [r['label'] for r in unlocated['rows']] == ['Row not set']
            assert len(unlocated['rows'][0]['stops']) == 1

    def test_loaded_count_is_per_unit(self, load_client, loading_shift):
        from app import app as _app, db
        from models import DeliveryStop
        with _app.app_context():
            stop = DeliveryStop.query.get(loading_shift['stop_ids'][0])   # Unit A
            stop.loaded_at = datetime.utcnow()
            db.session.commit()

            groups = _groups(_app, loading_shift['shift_id'])
            by_name = {g['name']: g for g in groups}
            assert by_name[loading_shift['unit_a_name']]['loaded_count'] == 1
            assert by_name[loading_shift['unit_b_name']]['loaded_count'] == 0

    def test_grouping_does_not_disturb_stop_order(self, load_client, loading_shift):
        """The route order is the whole point of the list below — grouping is a
        separate view over the same stops, never a re-sort of them."""
        from app import app as _app
        from models import DeliveryStop
        with _app.app_context():
            _groups(_app, loading_shift['shift_id'])
            orders = sorted(s.stop_order for s in
                            DeliveryStop.query.filter_by(shift_id=loading_shift['shift_id']))
            assert orders == [1, 2, 3, 4, 5]


# ---------------------------------------------------------------------------
# Marking loaded
# ---------------------------------------------------------------------------

class TestMarkLoaded:

    def test_marks_loaded_with_timestamp_and_worker(self, load_client, loading_shift):
        from app import app as _app
        from models import DeliveryStop
        stop_id = loading_shift['stop_ids'][0]
        _login(load_client, loading_shift['worker_email'])
        resp = load_client.post(f'/crew/delivery/stop/{stop_id}/loaded', data={'loaded': '1'})
        _logout(load_client)

        assert resp.status_code == 200
        body = resp.get_json()
        assert body['ok'] is True and body['loaded'] is True
        assert body['loaded_count'] == 1 and body['total'] == 5
        with _app.app_context():
            stop = DeliveryStop.query.get(stop_id)
            assert stop.loaded_at is not None
            assert stop.loaded_by_id == loading_shift['worker_id']

    def test_unloading_clears_the_record(self, load_client, loading_shift):
        """Un-checking is a correction, not history — the next load must record
        whoever actually did it."""
        from app import app as _app
        from models import DeliveryStop
        stop_id = loading_shift['stop_ids'][0]
        _login(load_client, loading_shift['worker_email'])
        load_client.post(f'/crew/delivery/stop/{stop_id}/loaded', data={'loaded': '1'})
        resp = load_client.post(f'/crew/delivery/stop/{stop_id}/loaded', data={'loaded': '0'})
        _logout(load_client)

        assert resp.get_json()['loaded'] is False
        with _app.app_context():
            stop = DeliveryStop.query.get(stop_id)
            assert stop.loaded_at is None and stop.loaded_by_id is None

    def test_double_tap_keeps_the_first_timestamp(self, load_client, loading_shift):
        """A retry on flaky warehouse signal must not rewrite when it was loaded."""
        from app import app as _app
        from models import DeliveryStop
        stop_id = loading_shift['stop_ids'][0]
        _login(load_client, loading_shift['worker_email'])
        load_client.post(f'/crew/delivery/stop/{stop_id}/loaded', data={'loaded': '1'})
        with _app.app_context():
            first = DeliveryStop.query.get(stop_id).loaded_at
        load_client.post(f'/crew/delivery/stop/{stop_id}/loaded', data={'loaded': '1'})
        _logout(load_client)

        with _app.app_context():
            assert DeliveryStop.query.get(stop_id).loaded_at == first

    def test_counts_climb_across_stops(self, load_client, loading_shift):
        _login(load_client, loading_shift['worker_email'])
        counts = []
        for stop_id in loading_shift['stop_ids'][:3]:
            resp = load_client.post(f'/crew/delivery/stop/{stop_id}/loaded',
                                    data={'loaded': '1'})
            counts.append(resp.get_json()['loaded_count'])
        _logout(load_client)
        assert counts == [1, 2, 3]

    def test_loading_does_not_touch_delivery_status(self, load_client, loading_shift):
        """Loaded and delivered are different axes — an item on the truck is still
        pending until it is at the buyer's door."""
        from app import app as _app
        from models import DeliveryStop
        stop_id = loading_shift['stop_ids'][0]
        _login(load_client, loading_shift['worker_email'])
        load_client.post(f'/crew/delivery/stop/{stop_id}/loaded', data={'loaded': '1'})
        _logout(load_client)
        with _app.app_context():
            stop = DeliveryStop.query.get(stop_id)
            assert stop.status == 'pending'
            assert stop.completed_at is None

    def test_admin_can_mark_without_an_assignment(self, load_client, loading_shift):
        from app import app as _app
        from models import DeliveryStop
        stop_id = loading_shift['stop_ids'][1]
        _login(load_client, loading_shift['admin_email'])
        resp = load_client.post(f'/crew/delivery/stop/{stop_id}/loaded', data={'loaded': '1'})
        _logout(load_client)
        assert resp.status_code == 200
        with _app.app_context():
            assert DeliveryStop.query.get(stop_id).loaded_at is not None

    def test_rejects_a_non_worker(self, load_client, loading_shift):
        from app import app as _app, db
        from models import User
        tag = _uid()
        with _app.app_context():
            civilian = User(email=f'ld_civ_{tag}@test.com', full_name='Civilian')
            civilian.set_password('testpass123')
            db.session.add(civilian)
            db.session.commit()

        _login(load_client, f'ld_civ_{tag}@test.com')
        resp = load_client.post(
            f"/crew/delivery/stop/{loading_shift['stop_ids'][0]}/loaded", data={'loaded': '1'})
        _logout(load_client)
        with _app.app_context():
            User.query.filter_by(email=f'ld_civ_{tag}@test.com').delete()
            db.session.commit()
        assert resp.status_code == 403

    def test_rejects_a_worker_from_another_shift(self, load_client, loading_shift):
        """is_worker alone is not authorisation — the crew member must be on this shift."""
        from app import app as _app, db
        from models import User
        tag = _uid()
        with _app.app_context():
            stranger = User(email=f'ld_other_{tag}@test.com', full_name='Other Crew',
                            is_worker=True)
            stranger.set_password('testpass123')
            db.session.add(stranger)
            db.session.commit()

        _login(load_client, f'ld_other_{tag}@test.com')
        resp = load_client.post(
            f"/crew/delivery/stop/{loading_shift['stop_ids'][0]}/loaded", data={'loaded': '1'})
        _logout(load_client)
        with _app.app_context():
            User.query.filter_by(email=f'ld_other_{tag}@test.com').delete()
            db.session.commit()
        assert resp.status_code == 403

    def test_anonymous_is_redirected_to_login(self, load_client, loading_shift):
        resp = load_client.post(
            f"/crew/delivery/stop/{loading_shift['stop_ids'][0]}/loaded", data={'loaded': '1'})
        assert resp.status_code in (301, 302)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

class TestCrewPageRendering:

    def test_checklist_lists_every_unit(self, load_client, loading_shift):
        _login(load_client, loading_shift['worker_email'])
        resp = load_client.get(f"/crew/delivery/{loading_shift['shift_id']}")
        _logout(load_client)

        assert resp.status_code == 200
        html = resp.data.decode()
        assert 'Load the truck' in html
        assert '<span id="loaded-count">0</span> / 5 loaded' in html
        assert loading_shift['unit_a_name'] in html
        assert loading_shift['unit_b_name'] in html
        assert 'No storage unit assigned' in html
        assert 'Front Left' in html and 'Back Left' in html

    def test_stop_card_shows_on_truck_once_loaded(self, load_client, loading_shift):
        """The driver at the door should not have to scroll back to the checklist."""
        from app import app as _app, db
        from models import DeliveryStop
        with _app.app_context():
            stop = DeliveryStop.query.get(loading_shift['stop_ids'][0])
            stop.loaded_at = datetime.utcnow()
            db.session.commit()

        _login(load_client, loading_shift['worker_email'])
        resp = load_client.get(f"/crew/delivery/{loading_shift['shift_id']}")
        _logout(load_client)

        html = resp.data.decode()
        assert 'On truck' in html
        assert 'Not loaded' in html      # the other four

    def test_checklist_hidden_on_a_past_shift(self, load_client, loading_shift):
        """Nothing left to load on a delivery that already happened.

        Moves the shift onto a throwaway past week rather than rewriting the
        week_start of the shared current week — that week may hold real shifts, and
        a failure between the mutation and the restore would leave them misdated.
        """
        from app import app as _app, db
        from models import Shift, ShiftWeek
        with _app.app_context():
            shift = Shift.query.get(loading_shift['shift_id'])
            original_week_id = shift.week_id
            past_week = ShiftWeek.query.filter_by(week_start=date(2020, 1, 6),
                                                  is_tutorial=False).first()
            temp_week_created = past_week is None
            if temp_week_created:
                past_week = ShiftWeek(week_start=date(2020, 1, 6), status='published')
                db.session.add(past_week)
                db.session.flush()
            past_week_id = past_week.id
            shift.week_id = past_week_id
            db.session.commit()

        try:
            _login(load_client, loading_shift['worker_email'])
            resp = load_client.get(f"/crew/delivery/{loading_shift['shift_id']}")
            _logout(load_client)
        finally:
            with _app.app_context():
                Shift.query.get(loading_shift['shift_id']).week_id = original_week_id
                db.session.commit()
                if temp_week_created:
                    db.session.delete(ShiftWeek.query.get(past_week_id))
                    db.session.commit()

        assert b'Load the truck' not in resp.data


# ---------------------------------------------------------------------------
# Proof of delivery
#
# The photo and its timestamp are written in the same request, so a delivery
# record can never carry a photo from one moment and a time from another.
# ---------------------------------------------------------------------------

def _jpeg_bytes(size=(120, 90), colour=(30, 120, 90)):
    """A real JPEG — validate_file_upload sniffs the MIME type, and _downscale_image
    actually decodes it, so a stub of random bytes will not do."""
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', size, colour).save(buf, format='JPEG')
    buf.seek(0)
    return buf


def _start_run(app, shift_id, worker_id):
    from models import DeliveryRun
    from datetime import datetime as _dt
    with app.app_context():
        from app import db
        if not DeliveryRun.query.filter_by(shift_id=shift_id).first():
            db.session.add(DeliveryRun(shift_id=shift_id, started_at=_dt.utcnow(),
                                       started_by_id=worker_id))
            db.session.commit()


class TestProofOfDelivery:

    def test_photo_is_stored_and_stamped(self, load_client, loading_shift):
        from app import app as _app, photo_storage
        from models import DeliveryStop
        stop_id = loading_shift['stop_ids'][0]
        _start_run(_app, loading_shift['shift_id'], loading_shift['worker_id'])

        _login(load_client, loading_shift['worker_email'])
        resp = load_client.post(
            f'/crew/delivery/stop/{stop_id}/update',
            data={'status': 'completed', 'notes': '',
                  'pod_photo': (_jpeg_bytes(), 'porch.jpg')},
            content_type='multipart/form-data')
        _logout(load_client)

        assert resp.status_code == 302
        with _app.app_context():
            stop = DeliveryStop.query.get(stop_id)
            assert stop.status == 'completed'
            assert stop.pod_photo_url is not None
            assert stop.pod_photo_url.startswith(f'pod_{stop_id}_')
            assert stop.pod_photo_url.endswith('.jpg')
            # The timestamp is the delivery time, written alongside the photo
            assert stop.completed_at is not None
            assert stop.buyer_order.delivered_at == stop.completed_at
            assert photo_storage.exists(stop.pod_photo_url)
            photo_storage.delete_photo(stop.pod_photo_url)

    def test_completing_without_a_photo_or_reason_is_refused(self, load_client, loading_shift):
        """Proof of delivery is the point — an empty confirm must not silently pass."""
        from app import app as _app
        from models import DeliveryStop
        stop_id = loading_shift['stop_ids'][1]
        _start_run(_app, loading_shift['shift_id'], loading_shift['worker_id'])

        _login(load_client, loading_shift['worker_email'])
        resp = load_client.post(f'/crew/delivery/stop/{stop_id}/update',
                                data={'status': 'completed', 'notes': ''})
        _logout(load_client)

        assert resp.status_code == 302          # redirected back with a flash
        with _app.app_context():
            stop = DeliveryStop.query.get(stop_id)
            assert stop.status == 'pending'     # unchanged
            assert stop.completed_at is None

    def test_a_written_reason_lets_a_photoless_delivery_through(self, load_client, loading_shift):
        """A dead camera must never make a run impossible to close."""
        from app import app as _app
        from models import DeliveryStop
        stop_id = loading_shift['stop_ids'][2]
        _start_run(_app, loading_shift['shift_id'], loading_shift['worker_id'])

        _login(load_client, loading_shift['worker_email'])
        resp = load_client.post(
            f'/crew/delivery/stop/{stop_id}/update',
            data={'status': 'completed', 'notes': 'Phone camera died — buyer signed for it'})
        _logout(load_client)

        assert resp.status_code == 302
        with _app.app_context():
            stop = DeliveryStop.query.get(stop_id)
            assert stop.status == 'completed'
            assert stop.pod_photo_url is None
            assert 'camera died' in stop.notes

    def test_flagging_an_issue_never_requires_a_photo(self, load_client, loading_shift):
        from app import app as _app
        from models import DeliveryStop
        stop_id = loading_shift['stop_ids'][3]
        _start_run(_app, loading_shift['shift_id'], loading_shift['worker_id'])

        _login(load_client, loading_shift['worker_email'])
        resp = load_client.post(f'/crew/delivery/stop/{stop_id}/update',
                                data={'status': 'issue', 'notes': 'Nobody home'})
        _logout(load_client)

        assert resp.status_code == 302
        with _app.app_context():
            stop = DeliveryStop.query.get(stop_id)
            assert stop.status == 'issue'
            assert stop.pod_photo_url is None

    def test_a_non_image_upload_is_rejected_and_the_stop_untouched(self, load_client, loading_shift):
        import io
        from app import app as _app
        from models import DeliveryStop
        stop_id = loading_shift['stop_ids'][4]
        _start_run(_app, loading_shift['shift_id'], loading_shift['worker_id'])

        _login(load_client, loading_shift['worker_email'])
        resp = load_client.post(
            f'/crew/delivery/stop/{stop_id}/update',
            data={'status': 'completed', 'notes': '',
                  'pod_photo': (io.BytesIO(b'#!/bin/sh\nrm -rf /'), 'payload.sh')},
            content_type='multipart/form-data')
        _logout(load_client)

        assert resp.status_code == 302
        with _app.app_context():
            stop = DeliveryStop.query.get(stop_id)
            assert stop.status == 'pending'
            assert stop.pod_photo_url is None

    def test_photo_appears_on_the_stop_card(self, load_client, loading_shift):
        from app import app as _app, db
        from models import DeliveryStop
        with _app.app_context():
            stop = DeliveryStop.query.get(loading_shift['stop_ids'][0])
            stop.status = 'completed'
            stop.completed_at = datetime.utcnow()
            stop.pod_photo_url = 'pod_fake_abc123.jpg'
            db.session.commit()

        _login(load_client, loading_shift['worker_email'])
        resp = load_client.get(f"/crew/delivery/{loading_shift['shift_id']}")
        _logout(load_client)
        assert b'pod_fake_abc123.jpg' in resp.data

    def test_card_says_so_when_no_photo_was_taken(self, load_client, loading_shift):
        from app import app as _app, db
        from models import DeliveryStop
        with _app.app_context():
            # The whole visit has to be resolved — a card with anything still pending
            # is showing action buttons, not an outcome.
            for stop_id in loading_shift['stop_ids']:
                stop = DeliveryStop.query.get(stop_id)
                stop.status = 'completed'
                stop.completed_at = datetime.utcnow()
                stop.pod_photo_url = None
            db.session.commit()

        _login(load_client, loading_shift['worker_email'])
        resp = load_client.get(f"/crew/delivery/{loading_shift['shift_id']}")
        _logout(load_client)
        assert b'No delivery photo taken' in resp.data


class TestDeliveredEmail:
    """The buyer-facing half: the photo and the time land in the 'Delivered!' email."""

    def _send(self, app, shift_id, pod_urls):
        """Mark every stop delivered with the given photo urls, capturing the email."""
        from unittest.mock import patch
        from app import db, _send_delivery_completed_email
        from models import DeliveryStop
        with app.app_context():
            stops = (DeliveryStop.query.filter_by(shift_id=shift_id)
                     .order_by(DeliveryStop.stop_order).all())
            for stop, url in zip(stops, pod_urls):
                stop.status = 'completed'
                stop.completed_at = datetime(2026, 8, 19, 14, 35)
                stop.pod_photo_url = url
            db.session.commit()
            with patch('app.send_email') as mock_send:
                _send_delivery_completed_email(stops[:len(pod_urls)])
            assert mock_send.called, 'no email was sent'
            return mock_send.call_args[0][2]      # html body

    def test_photo_and_time_are_in_the_email(self, load_client, loading_shift):
        from app import app as _app
        html = self._send(_app, loading_shift['shift_id'], ['pod_1_aaa.jpg'])
        assert 'pod_1_aaa.jpg' in html
        assert 'Where we left it' in html
        assert 'Delivered at' in html
        assert '2:35 PM' in html

    def test_every_stop_photo_is_included_for_a_multi_item_order(self, load_client, loading_shift):
        from app import app as _app
        html = self._send(_app, loading_shift['shift_id'],
                          ['pod_1_aaa.jpg', 'pod_2_bbb.jpg', 'pod_3_ccc.jpg'])
        for name in ('pod_1_aaa.jpg', 'pod_2_bbb.jpg', 'pod_3_ccc.jpg'):
            assert name in html

    def test_email_still_sends_when_the_photo_was_skipped(self, load_client, loading_shift):
        """No photo is not an error — the buyer still gets told it arrived."""
        from app import app as _app
        html = self._send(_app, loading_shift['shift_id'], [None])
        assert 'Delivered!' in html
        assert 'Where we left it' not in html
        assert 'Delivered at' in html


# ---------------------------------------------------------------------------
# When the buyer hears from us
#
# One stop per item, marked individually, so a multi-item order is only settled
# once every one of its stops is resolved. The email fires on stop update — never
# on End Run — so a crew member who forgets to close the run cannot mute a buyer.
# ---------------------------------------------------------------------------

class TestWhenTheBuyerIsEmailed:
    """All five fixture stops are one buyer on one truck — i.e. a single visit.

    So a default (visit-scoped) completion settles the whole order in one post, which
    is the point of the visit model: the crew cannot leave two of three items silently
    unresolved. Tests that need per-item behaviour pass scope='item' explicitly.
    """

    def _resolve(self, client, stop_id, status, notes='ok', scope=None):
        data = {'status': status, 'notes': notes}
        if scope:
            data['scope'] = scope
        return client.post(f'/crew/delivery/stop/{stop_id}/update', data=data)

    @pytest.fixture
    def run(self, load_client, loading_shift):
        _start_run(__import__('app').app, loading_shift['shift_id'],
                   loading_shift['worker_id'])
        _login(load_client, loading_shift['worker_email'])
        yield
        _logout(load_client)

    def test_one_post_settles_the_whole_visit_and_emails_once(self, load_client, loading_shift, run):
        """One knock, one photo, one email — no leftover pending siblings to forget."""
        from unittest.mock import patch
        from app import app as _app
        from models import DeliveryStop
        with patch('app.send_email') as mock:
            self._resolve(load_client, loading_shift['stop_ids'][0], 'completed')

        with _app.app_context():
            statuses = [DeliveryStop.query.get(i).status for i in loading_shift['stop_ids']]
        assert statuses == ['completed'] * 5

        delivered = [c[0][1] for c in mock.call_args_list if 'has been delivered' in c[0][1]]
        assert delivered == ['Your Campus Swap order has been delivered']

    def test_one_photo_covers_every_item_in_the_visit(self, load_client, loading_shift, run):
        """The driver photographs the pile once, not once per item."""
        from app import app as _app, photo_storage
        from models import DeliveryStop
        resp = load_client.post(
            f"/crew/delivery/stop/{loading_shift['stop_ids'][0]}/update",
            data={'status': 'completed', 'notes': '',
                  'pod_photo': (_jpeg_bytes(), 'porch.jpg')},
            content_type='multipart/form-data')
        assert resp.status_code == 302

        with _app.app_context():
            urls = {DeliveryStop.query.get(i).pod_photo_url
                    for i in loading_shift['stop_ids']}
            assert len(urls) == 1                  # one file, shared by all five
            filename = urls.pop()
            assert filename is not None
            photo_storage.delete_photo(filename)

    def test_the_email_shows_the_shared_photo_once(self, load_client, loading_shift, run):
        """De-duplicated by filename, captioned with everything it shows."""
        from unittest.mock import patch
        with patch('app.send_email') as mock:
            load_client.post(
                f"/crew/delivery/stop/{loading_shift['stop_ids'][0]}/update",
                data={'status': 'completed', 'notes': '',
                      'pod_photo': (_jpeg_bytes(), 'porch.jpg')},
                content_type='multipart/form-data')
        body = next(c[0][2] for c in mock.call_args_list
                    if 'has been delivered' in c[0][1])
        assert body.count('alt="Photo taken at delivery"') == 1
        # ...but every item it covers is named under it
        for i in range(5):
            assert f'Load Item {i}' in body

    def test_end_run_is_not_what_sends_it(self, load_client, loading_shift, run):
        """A driver who never taps End Run must not leave the buyer uninformed."""
        from unittest.mock import patch
        from app import app as _app
        from models import DeliveryRun
        self._resolve(load_client, loading_shift['stop_ids'][0], 'completed')
        with _app.app_context():
            assert DeliveryRun.query.filter_by(
                shift_id=loading_shift['shift_id']).first().ended_at is None
        with patch('app.send_email') as mock:
            load_client.post(f"/crew/delivery/{loading_shift['shift_id']}/end")
        assert [c for c in mock.call_args_list if 'delivered' in c[0][1].lower()] == []

    def test_no_email_while_an_item_is_still_pending(self, load_client, loading_shift, run):
        """Item-scoped completion leaves siblings pending, so nothing sends yet."""
        from unittest.mock import patch
        with patch('app.send_email') as mock:
            for stop_id in loading_shift['stop_ids'][:4]:
                self._resolve(load_client, stop_id, 'completed', scope='item')
        assert [c for c in mock.call_args_list if 'delivered' in c[0][1].lower()] == []

    def test_a_flagged_item_no_longer_buries_the_whole_order(self, load_client, loading_shift, run):
        """Regression: any 'issue' used to mean the email never sent at all, so a
        buyer was never told about the items that did arrive."""
        from unittest.mock import patch
        ids = loading_shift['stop_ids']
        with patch('app.send_email') as mock:
            for stop_id in ids[:4]:
                self._resolve(load_client, stop_id, 'completed', scope='item')
            self._resolve(load_client, ids[4], 'issue', notes='Sofa would not fit',
                          scope='item')
        subjects = [c[0][1] for c in mock.call_args_list]
        assert subjects.count('Part of your Campus Swap order has been delivered') == 1

    def test_partial_email_names_what_did_not_arrive(self, load_client, loading_shift, run):
        from unittest.mock import patch
        from app import app as _app
        from models import DeliveryStop
        ids = loading_shift['stop_ids']
        with _app.app_context():
            missing = DeliveryStop.query.get(ids[4]).buyer_order.item.description
        with patch('app.send_email') as mock:
            for stop_id in ids[:4]:
                self._resolve(load_client, stop_id, 'completed', scope='item')
            self._resolve(load_client, ids[4], 'issue', notes='Sofa would not fit',
                          scope='item')

        body = next(c[0][2] for c in mock.call_args_list
                    if c[0][1].startswith('Part of your'))
        assert 'Still to come' in body
        assert missing in body
        assert 'be in touch to rearrange' in body
        # The crew's internal shorthand must not leak to the buyer
        assert 'Sofa would not fit' not in body
        # And it must not claim the whole order landed
        assert 'All 4 of your items' not in body

    def test_flagging_the_visit_flags_every_pending_item(self, load_client, loading_shift, run):
        """Nobody home applies to the whole doorstep, not one box on it."""
        from unittest.mock import patch
        from app import app as _app
        from models import DeliveryStop
        with patch('app.send_email'):
            self._resolve(load_client, loading_shift['stop_ids'][0], 'issue',
                          notes='Nobody home', scope='visit')
        with _app.app_context():
            statuses = [DeliveryStop.query.get(i).status for i in loading_shift['stop_ids']]
        assert statuses == ['issue'] * 5

    def test_every_item_flagged_means_no_delivered_email(self, load_client, loading_shift, run):
        """Nothing arrived, so there is nothing to congratulate them on."""
        from unittest.mock import patch
        with patch('app.send_email') as mock:
            self._resolve(load_client, loading_shift['stop_ids'][0], 'issue',
                          notes='Access denied', scope='visit')
        subjects = [c[0][1] for c in mock.call_args_list]
        assert [s for s in subjects if 'delivered' in s.lower()] == []

    def test_a_later_re_attempt_sends_its_own_email(self, load_client, loading_shift, run):
        """After a partial email, resolving the flagged item must still tell the buyer.

        This is why completed_email_sent_at is stamped only on the stops an email
        actually covered — stamping the whole group would mute the follow-up.
        """
        from unittest.mock import patch
        ids = loading_shift['stop_ids']
        with patch('app.send_email'):
            for stop_id in ids[:4]:
                self._resolve(load_client, stop_id, 'completed', scope='item')
            self._resolve(load_client, ids[4], 'issue', notes='Nobody home', scope='item')

        with patch('app.send_email') as mock:
            self._resolve(load_client, ids[4], 'completed', notes='Re-attempted',
                          scope='item')
        subjects = [c[0][1] for c in mock.call_args_list]
        assert 'Your Campus Swap order has been delivered' in subjects

    def test_re_marking_a_delivered_visit_does_not_re_email(self, load_client, loading_shift, run):
        from unittest.mock import patch
        self._resolve(load_client, loading_shift['stop_ids'][0], 'completed')
        with patch('app.send_email') as mock:
            self._resolve(load_client, loading_shift['stop_ids'][0], 'completed')
        assert [c for c in mock.call_args_list if 'delivered' in c[0][1].lower()] == []


class TestVisitGrouping:
    """One card per drop-off, and the server derives the group — never the form."""

    def test_one_visit_for_one_buyers_items(self, load_client, loading_shift):
        from app import app as _app, _group_stops_into_visits
        from models import DeliveryStop
        with _app.app_context():
            stops = (DeliveryStop.query.filter_by(shift_id=loading_shift['shift_id'])
                     .order_by(DeliveryStop.stop_order).all())
            visits = _group_stops_into_visits(stops)
        assert len(visits) == 1
        assert len(visits[0]['stops']) == 5
        assert visits[0]['status'] == 'pending'

    def test_visit_status_rolls_up(self, load_client, loading_shift):
        from app import app as _app, db, _group_stops_into_visits
        from models import DeliveryStop
        ids = loading_shift['stop_ids']
        with _app.app_context():
            DeliveryStop.query.get(ids[0]).status = 'completed'
            DeliveryStop.query.get(ids[1]).status = 'issue'
            for i in ids[2:]:
                DeliveryStop.query.get(i).status = 'completed'
            db.session.commit()
            stops = DeliveryStop.query.filter_by(shift_id=loading_shift['shift_id']).all()
            assert _group_stops_into_visits(stops)[0]['status'] == 'partial'

    def test_items_split_across_trucks_are_separate_visits(self, load_client, loading_shift):
        """Two trucks means two doorsteps' worth of work and two photos."""
        from app import app as _app, db, _group_stops_into_visits
        from models import DeliveryStop
        with _app.app_context():
            DeliveryStop.query.get(loading_shift['stop_ids'][0]).truck_number = 2
            db.session.commit()
            stops = DeliveryStop.query.filter_by(shift_id=loading_shift['shift_id']).all()
            visits = _group_stops_into_visits(stops)
            assert len(visits) == 2
            assert sorted(len(v['stops']) for v in visits) == [1, 4]

    def test_visits_keep_the_optimized_route_order(self, load_client, loading_shift):
        """A visit sits where its earliest stop sits — grouping must not scramble
        the ordering the route optimizer solved."""
        from app import app as _app, db, _group_stops_into_visits
        from models import DeliveryStop
        with _app.app_context():
            # Put one item on truck 2 with an early stop_order, so if grouping
            # ignored stop_order the two visits would come back the other way round.
            first = DeliveryStop.query.get(loading_shift['stop_ids'][4])
            first.truck_number = 2
            first.stop_order = 0
            db.session.commit()
            stops = DeliveryStop.query.filter_by(shift_id=loading_shift['shift_id']).all()
            visits = _group_stops_into_visits(stops)
            assert visits[0]['stops'][0].id == loading_shift['stop_ids'][4]

    def test_the_group_is_derived_server_side_not_posted(self, load_client, loading_shift):
        """The form sends one stop id; a tampered scope cannot reach other buyers.

        Posting against a stop on truck 2 must settle only truck 2's stop, even
        though the same Order owns four more stops on truck 1.
        """
        from app import app as _app, db
        from models import DeliveryStop
        ids = loading_shift['stop_ids']
        _start_run(_app, loading_shift['shift_id'], loading_shift['worker_id'])
        with _app.app_context():
            DeliveryStop.query.get(ids[0]).truck_number = 2
            db.session.commit()

        _login(load_client, loading_shift['worker_email'])
        load_client.post(f'/crew/delivery/stop/{ids[0]}/update',
                         data={'status': 'completed', 'notes': 'left it', 'scope': 'visit'})
        _logout(load_client)

        with _app.app_context():
            assert DeliveryStop.query.get(ids[0]).status == 'completed'
            assert [DeliveryStop.query.get(i).status for i in ids[1:]] == ['pending'] * 4



class TestAdminIssueAlert:

    @pytest.fixture
    def super_admin(self, loading_shift):
        from app import app as _app, db
        from models import User
        tag = _uid()
        with _app.app_context():
            sa = User(email=f'ld_super_{tag}@test.com', full_name='Super Admin',
                      is_admin=True, is_super_admin=True)
            sa.set_password('testpass123')
            db.session.add(sa)
            db.session.commit()
            sa_id, sa_email = sa.id, sa.email
        yield sa_email
        with _app.app_context():
            db.session.execute(__import__('sqlalchemy').delete(User).where(User.id == sa_id))
            db.session.commit()

    def test_flagging_a_stop_emails_the_super_admin(self, load_client, loading_shift, super_admin):
        from unittest.mock import patch
        from app import app as _app
        _start_run(_app, loading_shift['shift_id'], loading_shift['worker_id'])
        _login(load_client, loading_shift['worker_email'])
        with patch('app.send_email') as mock:
            load_client.post(
                f"/crew/delivery/stop/{loading_shift['stop_ids'][0]}/update",
                data={'status': 'issue', 'notes': 'Truck could not fit down the street'})
        _logout(load_client)

        alerts = [c for c in mock.call_args_list if c[0][1].startswith('Delivery issue:')]
        # Every super admin gets it, and each gets it exactly once. The snapshot DB
        # already holds real super admins, so don't assume this fixture is the only one.
        with _app.app_context():
            from models import User
            expected = {u.email for u in User.query.filter(
                User.is_super_admin == True, User.unsubscribed == False).all()}
        recipients = [c[0][0] for c in alerts]
        assert super_admin in recipients
        assert sorted(recipients) == sorted(expected)
        body = alerts[0][0][2]
        # The crew's reason is exactly what the admin needs, unlike the buyer
        assert 'Truck could not fit down the street' in body
        assert 'Load Driver' in body           # who flagged it

    def test_completing_a_stop_does_not_alert(self, load_client, loading_shift, super_admin):
        from unittest.mock import patch
        from app import app as _app
        _start_run(_app, loading_shift['shift_id'], loading_shift['worker_id'])
        _login(load_client, loading_shift['worker_email'])
        with patch('app.send_email') as mock:
            load_client.post(f"/crew/delivery/stop/{loading_shift['stop_ids'][0]}/update",
                             data={'status': 'completed', 'notes': 'Left on porch'})
        _logout(load_client)
        assert [c for c in mock.call_args_list if c[0][1].startswith('Delivery issue:')] == []

    def test_a_failing_alert_does_not_break_the_stop_update(self, load_client, loading_shift, super_admin):
        """The crew's work must survive a broken mail provider."""
        from unittest.mock import patch
        from app import app as _app
        from models import DeliveryStop
        stop_id = loading_shift['stop_ids'][0]
        _start_run(_app, loading_shift['shift_id'], loading_shift['worker_id'])
        _login(load_client, loading_shift['worker_email'])
        with patch('app.send_email', side_effect=RuntimeError('resend is down')):
            resp = load_client.post(f'/crew/delivery/stop/{stop_id}/update',
                                    data={'status': 'issue', 'notes': 'Nobody home'})
        _logout(load_client)

        assert resp.status_code == 302
        with _app.app_context():
            assert DeliveryStop.query.get(stop_id).status == 'issue'
