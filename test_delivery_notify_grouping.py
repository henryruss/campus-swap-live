"""Tests that delivery notification counts buyers, not stops.

Run with: python3 -m pytest test_delivery_notify_grouping.py -v

One buyer purchasing three items produces three DeliveryStop rows. Sending was
already grouped per buyer order, but the ops badge and confirmation dialog counted
stops, so notifying one person announced "3 buyers".
"""

import pytest
from decimal import Decimal
from datetime import date
from unittest.mock import patch
import uuid


def _uid():
    return uuid.uuid4().hex[:10]


@pytest.fixture(scope='module')
def notify_client():
    from app import app as _app
    _app.config['TESTING'] = True
    _app.config['WTF_CSRF_ENABLED'] = False
    _app.config['SECRET_KEY'] = 'test-secret-notify'
    _app.config['SERVER_NAME'] = 'localhost'
    with _app.test_client() as client:
        yield client


@pytest.fixture
def multi_item_order(notify_client):
    """One buyer, one Order, three items → three stops. Plus a second solo buyer."""
    from app import app as _app, db
    from models import (User, InventoryItem, BuyerOrder, Order, Shift, ShiftWeek,
                        ShiftAssignment, DeliveryStop)
    tag = _uid()
    with _app.app_context():
        seller = User(email=f'ng_seller_{tag}@test.com', full_name='NG Seller', is_seller=True)
        buyer = User(email=f'ng_buyer_{tag}@test.com', full_name='Three Item Buyer')
        buyer2 = User(email=f'ng_buyer2_{tag}@test.com', full_name='Solo Buyer')
        admin = User(email=f'ng_admin_{tag}@test.com', full_name='NG Admin', is_admin=True)
        admin.set_password('testpass123')
        db.session.add_all([seller, buyer, buyer2, admin])
        db.session.flush()

        week = ShiftWeek.query.filter_by(week_start=date(2026, 9, 7), is_tutorial=False).first()
        if not week:
            week = ShiftWeek(week_start=date(2026, 9, 7), status='published')
            db.session.add(week)
            db.session.flush()
        shift = Shift(week_id=week.id, day_of_week='tue', slot='pm', trucks=1)
        db.session.add(shift)
        db.session.flush()

        stop_ids = []
        # Buyer 1: one Order, three items
        order = Order(buyer_id=buyer.id, buyer_email=buyer.email,
                      buyer_name='Three Item Buyer', status='paid')
        db.session.add(order)
        db.session.flush()
        for i in range(3):
            item = InventoryItem(description=f'NG Item {i}', price=Decimal('50.00'),
                                 status='sold', seller_id=seller.id)
            db.session.add(item)
            db.session.flush()
            bo = BuyerOrder(item_id=item.id, order_id=order.id, buyer_email=buyer.email,
                            delivery_address='400 Hillsborough St, Chapel Hill, NC 27514',
                            delivery_lat=35.9210, delivery_lng=-79.0600)
            db.session.add(bo)
            db.session.flush()
            s = DeliveryStop(shift_id=shift.id, buyer_order_id=bo.id, truck_number=1,
                             status='pending')
            db.session.add(s)
            db.session.flush()
            stop_ids.append(s.id)

        # Buyer 2: a separate single-item order
        order2 = Order(buyer_id=buyer2.id, buyer_email=buyer2.email,
                       buyer_name='Solo Buyer', status='paid')
        db.session.add(order2)
        db.session.flush()
        item2 = InventoryItem(description='NG Solo Item', price=Decimal('75.00'),
                              status='sold', seller_id=seller.id)
        db.session.add(item2)
        db.session.flush()
        bo2 = BuyerOrder(item_id=item2.id, order_id=order2.id, buyer_email=buyer2.email,
                         delivery_address='9 Ransom St, Chapel Hill, NC 27516',
                         delivery_lat=35.9150, delivery_lng=-79.0570)
        db.session.add(bo2)
        db.session.flush()
        s2 = DeliveryStop(shift_id=shift.id, buyer_order_id=bo2.id, truck_number=1,
                          status='pending')
        db.session.add(s2)
        db.session.flush()
        stop_ids.append(s2.id)
        db.session.commit()

        ctx = {'shift_id': shift.id, 'stop_ids': stop_ids,
               'admin_email': admin.email,
               'order_ids': [order.id, order2.id],
               'item_ids': [bo.item_id for bo in BuyerOrder.query.filter(
                   BuyerOrder.order_id.in_([order.id, order2.id]))],
               'user_ids': [seller.id, buyer.id, buyer2.id, admin.id]}

    yield ctx

    from sqlalchemy import delete
    from models import DeliveryRoutePlan
    with _app.app_context():
        db.session.execute(delete(DeliveryRoutePlan).where(
            DeliveryRoutePlan.shift_id == ctx['shift_id']))
        db.session.execute(delete(DeliveryStop).where(
            DeliveryStop.shift_id == ctx['shift_id']))
        db.session.execute(delete(BuyerOrder).where(
            BuyerOrder.order_id.in_(ctx['order_ids'])))
        db.session.execute(delete(Order).where(Order.id.in_(ctx['order_ids'])))
        db.session.execute(delete(InventoryItem).where(
            InventoryItem.id.in_(ctx['item_ids'])))
        db.session.execute(delete(ShiftAssignment).where(
            ShiftAssignment.shift_id == ctx['shift_id']))
        db.session.execute(delete(Shift).where(Shift.id == ctx['shift_id']))
        db.session.execute(delete(User).where(User.id.in_(ctx['user_ids'])))
        db.session.commit()


def _login(client, email, password='testpass123'):
    return client.post('/login', data={'email': email, 'password': password}, follow_redirects=True)


def _logout(client):
    client.get('/logout', follow_redirects=True)


class TestGrouping:

    def test_four_stops_group_into_two_buyers(self, notify_client, multi_item_order):
        from app import app as _app, _group_stops_by_buyer_order
        from models import DeliveryStop
        with _app.app_context():
            stops = DeliveryStop.query.filter_by(shift_id=multi_item_order['shift_id']).all()
            assert len(stops) == 4
            assert len(_group_stops_by_buyer_order(stops)) == 2


class TestOpsBadge:

    def test_badge_counts_buyers_not_stops(self, notify_client, multi_item_order):
        """Regression: this said 4 (stops) when only 2 emails would go out."""
        _login(notify_client, multi_item_order['admin_email'])
        resp = notify_client.get(f"/admin/ops?shift_id={multi_item_order['shift_id']}")
        _logout(notify_client)

        assert resp.status_code == 200
        assert b'data-unnotified="2"' in resp.data
        assert b'data-unnotified="4"' not in resp.data


class TestSending:

    def test_one_email_per_buyer(self, notify_client, multi_item_order):
        from app import app as _app
        from models import DeliveryStop

        _login(notify_client, multi_item_order['admin_email'])
        with patch('app.send_email', return_value=True) as mock_send:
            resp = notify_client.post(
                f"/admin/crew/shift/{multi_item_order['shift_id']}/notify-buyers",
                follow_redirects=False)
        _logout(notify_client)

        assert resp.status_code == 302
        assert mock_send.call_count == 2  # two buyers, not four stops

        with _app.app_context():
            stops = DeliveryStop.query.filter_by(shift_id=multi_item_order['shift_id']).all()
            # every stop marked, including the two that shared an email
            assert all(s.notified_at is not None for s in stops)

    def test_multi_item_email_names_all_items(self, notify_client, multi_item_order):
        from app import app as _app
        from models import DeliveryStop

        _login(notify_client, multi_item_order['admin_email'])
        with patch('app.send_email', return_value=True) as mock_send:
            notify_client.post(
                f"/admin/crew/shift/{multi_item_order['shift_id']}/notify-buyers")
        _logout(notify_client)

        bodies = [c.args[2] if len(c.args) > 2 else c.kwargs.get('html', '')
                  for c in mock_send.call_args_list]
        multi = [b for b in bodies if 'all 3 of your items' in b]
        assert len(multi) == 1
        for i in range(3):
            assert f'NG Item {i}' in multi[0]

    def test_badge_clears_after_notifying(self, notify_client, multi_item_order):
        _login(notify_client, multi_item_order['admin_email'])
        with patch('app.send_email', return_value=True):
            notify_client.post(
                f"/admin/crew/shift/{multi_item_order['shift_id']}/notify-buyers")
        resp = notify_client.get(f"/admin/ops?shift_id={multi_item_order['shift_id']}")
        _logout(notify_client)
        assert b'data-unnotified="0"' in resp.data
