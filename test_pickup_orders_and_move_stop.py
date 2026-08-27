"""Tests for buyer-pickup orders and moving a failed delivery stop to a new route.

Run with: python3 -m pytest test_pickup_orders_and_move_stop.py -v

Coverage:
- Pickup classification: promo-code orders and hand-marked sales, delivery orders are not
- Pickup orders are kept out of the delivery queue (they never go on a truck)
- Mark picked up / undo, idempotency, and auth
- Moving an `issue` stop: state reset, notes history, guards (status, mixed truck, no-op)
"""

import pytest
import uuid
from decimal import Decimal
from datetime import datetime, date


def _uid():
    return uuid.uuid4().hex[:10]


@pytest.fixture(scope='module')
def pk_client():
    from app import app as _app
    _app.config['TESTING'] = True
    _app.config['WTF_CSRF_ENABLED'] = False
    _app.config['SECRET_KEY'] = 'test-secret-pickup'
    _app.config['SERVER_NAME'] = 'localhost'
    with _app.test_client() as client:
        yield client


@pytest.fixture
def pk_data(pk_client):
    """Admin + civilian, one category, and four sold items:

      delivery_item — a normal cart order, no promo   → delivery queue
      promo_item    — same shape but promo_code set   → pickup queue
      manual_item   — sold by hand, no BuyerOrder      → pickup queue
      routed_item   — a delivery order already on a failed (`issue`) stop
    """
    from app import app as _app, db
    from models import (User, InventoryItem, InventoryCategory, Order, BuyerOrder,
                        Shift, ShiftWeek, DeliveryStop)
    tag = _uid()
    with _app.app_context():
        admin = User(email=f'pk_admin_{tag}@test.com', full_name='PK Admin', is_admin=True)
        admin.set_password('testpass123')
        civilian = User(email=f'pk_civ_{tag}@test.com', full_name='PK Civilian')
        civilian.set_password('testpass123')
        seller = User(email=f'pk_seller_{tag}@test.com', full_name='PK Seller', is_seller=True)
        db.session.add_all([admin, civilian, seller])
        db.session.flush()

        cat = InventoryCategory(name=f'PK Cat {tag}', count_in_stock=10, default_unit_size=1.0)
        db.session.add(cat)
        db.session.flush()

        def _item(label):
            it = InventoryItem(description=f'PK {label} {tag}', price=Decimal('100.00'),
                               status='sold', sold_at=datetime.utcnow(),
                               seller_id=seller.id, category_id=cat.id)
            db.session.add(it)
            return it

        delivery_item = _item('Delivery')
        promo_item = _item('Promo')
        manual_item = _item('Manual')
        routed_item = _item('Routed')
        db.session.flush()

        def _order(promo=None):
            o = Order(buyer_email=f'buyer_{tag}@test.com', buyer_name='PK Buyer',
                      delivery_street='101 Main St', delivery_city='Chapel Hill',
                      delivery_state='NC', delivery_zip='27514',
                      promo_code=promo, status='paid')
            db.session.add(o)
            db.session.flush()
            return o

        def _line(order, item):
            bo = BuyerOrder(item_id=item.id, buyer_email=order.buyer_email,
                            delivery_address='101 Main St, Chapel Hill, NC 27514',
                            order_id=order.id)
            db.session.add(bo)
            db.session.flush()
            return bo

        delivery_order = _order()
        delivery_bo = _line(delivery_order, delivery_item)
        promo_order = _order(promo='pickup')
        promo_bo = _line(promo_order, promo_item)
        routed_order = _order()
        routed_bo = _line(routed_order, routed_item)
        # manual_item deliberately gets no BuyerOrder — that is what makes it a hand sale.
        manual_item.sold_in_person = True
        manual_item.amount_collected = Decimal('80.00')

        # A week far in the future so the (week_start, is_tutorial) unique constraint
        # never collides with real or other-suite data. Shift dates are derived from
        # week_start + day_of_week by _ops_shift_date, not stored.
        week = ShiftWeek(week_start=date(2030, 1, 7), status='published', is_tutorial=False)
        db.session.add(week)
        db.session.flush()
        old_shift = Shift(week_id=week.id, day_of_week='mon',
                          slot='am', trucks=2, is_active=True)
        new_shift = Shift(week_id=week.id, day_of_week='thu',
                          slot='pm', trucks=2, is_active=True)
        db.session.add_all([old_shift, new_shift])
        db.session.flush()

        stop = DeliveryStop(shift_id=old_shift.id, buyer_order_id=routed_bo.id,
                            truck_number=1, stop_order=3, status='issue',
                            notes='Buyer not home', completed_at=datetime.utcnow(),
                            notified_at=datetime.utcnow(), loaded_at=datetime.utcnow(),
                            pod_photo_url='pod_test.jpg')
        db.session.add(stop)
        db.session.commit()

        ctx = {
            'admin_email': admin.email, 'civilian_email': civilian.email,
            'cat_id': cat.id,
            'delivery_item_id': delivery_item.id, 'promo_item_id': promo_item.id,
            'manual_item_id': manual_item.id, 'routed_item_id': routed_item.id,
            'delivery_bo_id': delivery_bo.id, 'promo_bo_id': promo_bo.id,
            'routed_bo_id': routed_bo.id,
            'order_ids': [delivery_order.id, promo_order.id, routed_order.id],
            'bo_ids': [delivery_bo.id, promo_bo.id, routed_bo.id],
            'item_ids': [delivery_item.id, promo_item.id, manual_item.id, routed_item.id],
            'stop_id': stop.id,
            'old_shift_id': old_shift.id, 'new_shift_id': new_shift.id,
            'week_id': week.id,
            'user_ids': [admin.id, civilian.id, seller.id],
        }

    yield ctx

    from sqlalchemy import delete
    from models import (ItemPhoto, CartItem, Cart, ShiftPickup, DeliveryStop as DS,
                        DeliveryRoutePlan)
    with _app.app_context():
        db.session.execute(delete(DeliveryRoutePlan).where(
            DeliveryRoutePlan.shift_id.in_([ctx['old_shift_id'], ctx['new_shift_id']])))
        db.session.execute(delete(DS).where(DS.buyer_order_id.in_(ctx['bo_ids'])))
        db.session.execute(delete(ShiftPickup).where(
            ShiftPickup.shift_id.in_([ctx['old_shift_id'], ctx['new_shift_id']])))
        db.session.execute(delete(Shift).where(
            Shift.id.in_([ctx['old_shift_id'], ctx['new_shift_id']])))
        db.session.execute(delete(ShiftWeek).where(ShiftWeek.id == ctx['week_id']))
        db.session.execute(delete(BuyerOrder).where(BuyerOrder.id.in_(ctx['bo_ids'])))
        db.session.execute(delete(Order).where(Order.id.in_(ctx['order_ids'])))
        db.session.execute(delete(ItemPhoto).where(ItemPhoto.item_id.in_(ctx['item_ids'])))
        db.session.execute(delete(CartItem).where(CartItem.item_id.in_(ctx['item_ids'])))
        db.session.execute(delete(Cart).where(Cart.user_id.in_(ctx['user_ids'])))
        db.session.execute(delete(InventoryItem).where(InventoryItem.id.in_(ctx['item_ids'])))
        db.session.execute(delete(InventoryCategory).where(InventoryCategory.id == ctx['cat_id']))
        db.session.execute(delete(User).where(User.id.in_(ctx['user_ids'])))
        db.session.commit()


def _login(client, email, password='testpass123'):
    return client.post('/login', data={'email': email, 'password': password},
                       follow_redirects=True)


def _logout(client):
    client.get('/logout', follow_redirects=True)


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

class TestPickupClassification:

    def test_promo_order_is_a_pickup(self, pk_client, pk_data):
        from app import app as _app, _order_is_pickup
        from models import BuyerOrder
        with _app.app_context():
            bo = BuyerOrder.query.get(pk_data['promo_bo_id'])
            assert _order_is_pickup(bo) is True

    def test_plain_order_is_a_delivery(self, pk_client, pk_data):
        from app import app as _app, _order_is_pickup
        from models import BuyerOrder
        with _app.app_context():
            bo = BuyerOrder.query.get(pk_data['delivery_bo_id'])
            assert _order_is_pickup(bo) is False

    def test_hand_marked_sale_has_no_buyer_order_and_is_a_pickup(self, pk_client, pk_data):
        from app import app as _app, _order_is_pickup
        from models import InventoryItem
        with _app.app_context():
            item = InventoryItem.query.get(pk_data['manual_item_id'])
            assert item.buyer_order is None
            assert _order_is_pickup(None) is True


class TestQueueSeparation:

    def test_pickup_queue_holds_promo_and_manual_only(self, pk_client, pk_data):
        from app import app as _app, _build_pickup_queue
        with _app.app_context():
            ids = {i for g in _build_pickup_queue() for i in g['item_ids']}
        assert pk_data['promo_item_id'] in ids
        assert pk_data['manual_item_id'] in ids
        assert pk_data['delivery_item_id'] not in ids

    def test_delivery_queue_excludes_pickup_orders(self, pk_client, pk_data):
        from app import app as _app, _build_delivery_queue
        with _app.app_context():
            bo_ids = {i for g in _build_delivery_queue() for i in g['buyer_order_ids']}
        assert pk_data['delivery_bo_id'] in bo_ids
        assert pk_data['promo_bo_id'] not in bo_ids

    def test_pickup_group_carries_source_and_promo_code(self, pk_client, pk_data):
        from app import app as _app, _build_pickup_queue
        with _app.app_context():
            groups = {g['item_ids'][0]: g for g in _build_pickup_queue()}
        promo = groups[pk_data['promo_item_id']]
        manual = groups[pk_data['manual_item_id']]
        assert promo['source'] == 'promo'
        assert promo['promo_code'] == 'pickup'
        assert promo['buyer_email']
        assert manual['source'] == 'manual'
        assert manual['buyer_email'] is None

    def test_partial_renders_both_sources(self, pk_client, pk_data):
        _login(pk_client, pk_data['admin_email'])
        resp = pk_client.get('/admin/ops/pickup-queue')
        assert resp.status_code == 200
        body = resp.data.decode()
        assert 'Promo PICKUP' in body
        assert 'Sold by hand' in body
        _logout(pk_client)


# ---------------------------------------------------------------------------
# Mark picked up
# ---------------------------------------------------------------------------

class TestMarkPickedUp:

    def test_mark_stamps_and_drops_out_of_queue(self, pk_client, pk_data):
        from app import app as _app, _build_pickup_queue
        from models import InventoryItem
        _login(pk_client, pk_data['admin_email'])
        resp = pk_client.post('/admin/pickup/mark-picked-up',
                              data={'item_ids': str(pk_data['promo_item_id']), 'ajax': '1'})
        assert resp.status_code == 200
        assert resp.get_json()['marked'] == 1
        with _app.app_context():
            item = InventoryItem.query.get(pk_data['promo_item_id'])
            assert item.picked_up_by_buyer_at is not None
            assert item.picked_up_by_buyer_by_id is not None
            ids = {i for g in _build_pickup_queue() for i in g['item_ids']}
        assert pk_data['promo_item_id'] not in ids
        _logout(pk_client)

    def test_mark_is_idempotent(self, pk_client, pk_data):
        """A second click must not restamp — two people can be looking at the same queue."""
        from app import app as _app
        from models import InventoryItem
        _login(pk_client, pk_data['admin_email'])
        pk_client.post('/admin/pickup/mark-picked-up',
                       data={'item_ids': str(pk_data['manual_item_id']), 'ajax': '1'})
        with _app.app_context():
            first = InventoryItem.query.get(pk_data['manual_item_id']).picked_up_by_buyer_at
        resp = pk_client.post('/admin/pickup/mark-picked-up',
                              data={'item_ids': str(pk_data['manual_item_id']), 'ajax': '1'})
        assert resp.get_json()['marked'] == 0
        with _app.app_context():
            assert InventoryItem.query.get(pk_data['manual_item_id']).picked_up_by_buyer_at == first
        _logout(pk_client)

    def test_undo_puts_it_back(self, pk_client, pk_data):
        from app import app as _app, _build_pickup_queue
        _login(pk_client, pk_data['admin_email'])
        pk_client.post('/admin/pickup/mark-picked-up',
                       data={'item_ids': str(pk_data['promo_item_id']), 'ajax': '1'})
        pk_client.post('/admin/pickup/undo-picked-up',
                       data={'item_ids': str(pk_data['promo_item_id']), 'ajax': '1'})
        with _app.app_context():
            ids = {i for g in _build_pickup_queue() for i in g['item_ids']}
        assert pk_data['promo_item_id'] in ids
        _logout(pk_client)

    def test_marking_does_not_change_sale_state(self, pk_client, pk_data):
        """Pickup is a handoff record, not a sale record — status and payout basis hold."""
        from app import app as _app, _get_item_sale_price
        from models import InventoryItem
        _login(pk_client, pk_data['admin_email'])
        pk_client.post('/admin/pickup/mark-picked-up',
                       data={'item_ids': str(pk_data['manual_item_id']), 'ajax': '1'})
        with _app.app_context():
            item = InventoryItem.query.get(pk_data['manual_item_id'])
            assert item.status == 'sold'
            assert _get_item_sale_price(item) == 80.0
        _logout(pk_client)

    def test_requires_ops_access(self, pk_client, pk_data):
        _login(pk_client, pk_data['civilian_email'])
        resp = pk_client.post('/admin/pickup/mark-picked-up',
                              data={'item_ids': str(pk_data['promo_item_id']), 'ajax': '1'})
        assert resp.status_code == 403
        resp = pk_client.get('/admin/ops/pickup-queue')
        assert resp.status_code == 403
        _logout(pk_client)


# ---------------------------------------------------------------------------
# Move a failed stop to another route
# ---------------------------------------------------------------------------

class TestMoveStop:

    def _move(self, client, stop_id, shift_id, truck):
        return client.post(f'/admin/delivery/stop/{stop_id}/move',
                           data={'shift_truck': f'{shift_id}_{truck}', 'ajax': '1'})

    def test_move_resets_stop_onto_new_route(self, pk_client, pk_data):
        from app import app as _app
        from models import DeliveryStop
        _login(pk_client, pk_data['admin_email'])
        resp = self._move(pk_client, pk_data['stop_id'], pk_data['new_shift_id'], 2)
        assert resp.status_code == 200, resp.data
        with _app.app_context():
            stop = DeliveryStop.query.get(pk_data['stop_id'])
            assert stop.shift_id == pk_data['new_shift_id']
            assert stop.truck_number == 2
            assert stop.status == 'pending'
            assert stop.completed_at is None
            assert stop.pod_photo_url is None
            assert stop.notified_at is None
            assert stop.completed_email_sent_at is None
            assert stop.loaded_at is None
            assert stop.buyer_order.delivered_at is None
        _logout(pk_client)

    def test_failed_attempt_survives_in_notes(self, pk_client, pk_data):
        from app import app as _app
        from models import DeliveryStop
        _login(pk_client, pk_data['admin_email'])
        self._move(pk_client, pk_data['stop_id'], pk_data['new_shift_id'], 2)
        with _app.app_context():
            notes = DeliveryStop.query.get(pk_data['stop_id']).notes
        assert 'Buyer not home' in notes
        assert 'attempt' in notes
        _logout(pk_client)

    def test_moved_stop_gets_a_fresh_stop_order(self, pk_client, pk_data):
        from app import app as _app, db
        from models import DeliveryStop
        _login(pk_client, pk_data['admin_email'])
        self._move(pk_client, pk_data['stop_id'], pk_data['new_shift_id'], 2)
        with _app.app_context():
            stop = DeliveryStop.query.get(pk_data['stop_id'])
            others = db.session.query(db.func.max(DeliveryStop.stop_order)).filter(
                DeliveryStop.shift_id == pk_data['new_shift_id'],
                DeliveryStop.id != stop.id,
            ).scalar() or 0
            assert stop.stop_order == others + 1
        _logout(pk_client)

    def test_pending_stop_cannot_be_moved(self, pk_client, pk_data):
        """Only a failed attempt moves; a pending stop is removed and re-assigned."""
        from app import app as _app, db
        from models import DeliveryStop
        with _app.app_context():
            DeliveryStop.query.get(pk_data['stop_id']).status = 'pending'
            db.session.commit()
        _login(pk_client, pk_data['admin_email'])
        resp = self._move(pk_client, pk_data['stop_id'], pk_data['new_shift_id'], 2)
        assert resp.status_code == 409
        assert 'issue' in resp.get_json()['error']
        _logout(pk_client)

    def test_completed_stop_cannot_be_moved(self, pk_client, pk_data):
        from app import app as _app, db
        from models import DeliveryStop
        with _app.app_context():
            DeliveryStop.query.get(pk_data['stop_id']).status = 'completed'
            db.session.commit()
        _login(pk_client, pk_data['admin_email'])
        resp = self._move(pk_client, pk_data['stop_id'], pk_data['new_shift_id'], 2)
        assert resp.status_code == 409
        _logout(pk_client)

    def test_move_to_same_shift_and_truck_is_rejected(self, pk_client, pk_data):
        _login(pk_client, pk_data['admin_email'])
        resp = self._move(pk_client, pk_data['stop_id'], pk_data['old_shift_id'], 1)
        assert resp.status_code == 409
        _logout(pk_client)

    def test_move_to_a_pickup_truck_is_blocked(self, pk_client, pk_data):
        """A truck is pickup or delivery, never both — same rule as add-stop."""
        from app import app as _app, db
        from models import ShiftPickup
        with _app.app_context():
            db.session.add(ShiftPickup(shift_id=pk_data['new_shift_id'],
                                       seller_id=pk_data['user_ids'][2],
                                       truck_number=2, stop_order=1))
            db.session.commit()
        _login(pk_client, pk_data['admin_email'])
        resp = self._move(pk_client, pk_data['stop_id'], pk_data['new_shift_id'], 2)
        assert resp.status_code == 409
        assert 'pickup stops' in resp.get_json()['error']
        _logout(pk_client)

    def test_bad_target_is_rejected(self, pk_client, pk_data):
        _login(pk_client, pk_data['admin_email'])
        resp = pk_client.post(f"/admin/delivery/stop/{pk_data['stop_id']}/move",
                              data={'shift_truck': 'garbage', 'ajax': '1'})
        assert resp.status_code == 400
        _logout(pk_client)

    def test_requires_ops_access(self, pk_client, pk_data):
        _login(pk_client, pk_data['civilian_email'])
        resp = self._move(pk_client, pk_data['stop_id'], pk_data['new_shift_id'], 2)
        assert resp.status_code == 403
        _logout(pk_client)

    def test_moved_stop_reappears_on_the_new_truck_detail(self, pk_client, pk_data):
        _login(pk_client, pk_data['admin_email'])
        self._move(pk_client, pk_data['stop_id'], pk_data['new_shift_id'], 2)
        resp = pk_client.get(
            f"/admin/ops/truck-detail?shift_id={pk_data['new_shift_id']}&truck=2")
        assert resp.status_code == 200
        assert f"#{pk_data['routed_item_id']}" in resp.data.decode()
        _logout(pk_client)
