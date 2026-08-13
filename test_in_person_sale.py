"""Tests for marking items sold in person (cash/Venmo handoff, no Stripe).

Run with: python3 -m pytest test_in_person_sale.py -v

Coverage:
- Payout math reads the collected amount, not the list price
- Mark-sold does every side effect the webhook does (status, sold_at, stock, carts)
- Double-sale protection: item leaves the shop and other shoppers' carts
- Idempotency, validation, and auth (ops access, not just admins)
- Payout queue and CSV export reflect the collected amount
"""

import pytest
from decimal import Decimal
from datetime import datetime
from unittest.mock import patch
import uuid


def _uid():
    return uuid.uuid4().hex[:10]


@pytest.fixture(scope='module')
def ips_client():
    from app import app as _app
    _app.config['TESTING'] = True
    _app.config['WTF_CSRF_ENABLED'] = False
    _app.config['SECRET_KEY'] = 'test-secret-ips'
    _app.config['SERVER_NAME'] = 'localhost'
    with _app.test_client() as client:
        yield client


@pytest.fixture
def ips_data(ips_client):
    """A seller, an admin, a campus director, a plain user, and a $120 item."""
    from app import app as _app, db
    from models import User, InventoryItem, InventoryCategory, TutorialSession
    from datetime import datetime as _dt
    tag = _uid()
    with _app.app_context():
        seller = User(email=f'ips_seller_{tag}@test.com', full_name='IPS Seller', is_seller=True)
        admin = User(email=f'ips_admin_{tag}@test.com', full_name='IPS Admin', is_admin=True)
        admin.set_password('testpass123')
        director = User(email=f'ips_dir_{tag}@test.com', full_name='IPS Director',
                        is_campus_director=True)
        director.set_password('testpass123')
        civilian = User(email=f'ips_civ_{tag}@test.com', full_name='IPS Civilian')
        civilian.set_password('testpass123')
        shopper = User(email=f'ips_shop_{tag}@test.com', full_name='IPS Shopper')
        shopper.set_password('testpass123')
        db.session.add_all([seller, admin, director, civilian, shopper])
        db.session.flush()

        # A campus director is redirected into the onboarding tutorial until it is
        # finished, so mark it complete or every ops route 302s to /admin/tutorial.
        db.session.add(TutorialSession(user_id=director.id, step=7,
                                       completed_at=_dt.utcnow()))
        db.session.flush()

        cat = InventoryCategory(name=f'IPS Cat {tag}', count_in_stock=5)
        db.session.add(cat)
        db.session.flush()

        item = InventoryItem(description=f'IPS Dresser {tag}', price=Decimal('120.00'),
                             status='available', seller_id=seller.id, category_id=cat.id)
        db.session.add(item)
        db.session.commit()
        ctx = {'item_id': item.id, 'cat_id': cat.id, 'seller_id': seller.id,
               'admin_email': admin.email, 'director_email': director.email,
               'civilian_email': civilian.email, 'shopper_email': shopper.email,
               'shopper_id': shopper.id,
               'user_ids': [seller.id, admin.id, director.id, civilian.id, shopper.id]}

    yield ctx

    from sqlalchemy import delete
    from models import Cart, CartItem, TutorialSession, ItemPhoto
    with _app.app_context():
        db.session.execute(delete(ItemPhoto).where(ItemPhoto.item_id == ctx['item_id']))
        db.session.execute(delete(TutorialSession).where(
            TutorialSession.user_id.in_(ctx['user_ids'])))
        db.session.execute(delete(CartItem).where(CartItem.item_id == ctx['item_id']))
        db.session.execute(delete(Cart).where(Cart.user_id.in_(ctx['user_ids'])))
        db.session.execute(delete(InventoryItem).where(InventoryItem.id == ctx['item_id']))
        db.session.execute(delete(InventoryCategory).where(InventoryCategory.id == ctx['cat_id']))
        db.session.execute(delete(User).where(User.id.in_(ctx['user_ids'])))
        db.session.commit()


def _login(client, email, password='testpass123'):
    return client.post('/login', data={'email': email, 'password': password}, follow_redirects=True)


def _logout(client):
    client.get('/logout', follow_redirects=True)


def _mark_sold(client, item_id, amount=None, modal=True):
    data = {'modal': '1'} if modal else {}
    if amount is not None:
        data['amount_collected'] = amount
    return client.post(f'/admin/item/{item_id}/mark-sold', data=data)


# ---------------------------------------------------------------------------
# Payout math
# ---------------------------------------------------------------------------

class TestPayoutMath:

    def test_payout_uses_collected_amount_not_list_price(self, ips_client, ips_data):
        """$120 listed, $100 collected, 50% rate → $50, not $60."""
        from app import app as _app, _get_payout_amount, _get_item_sale_price, db
        from models import InventoryItem
        with _app.app_context():
            item = InventoryItem.query.get(ips_data['item_id'])
            item.sold_in_person = True
            item.amount_collected = Decimal('100.00')
            db.session.commit()

            assert _get_item_sale_price(item) == 100.0
            assert _get_payout_amount(item) == 50.0

    def test_payout_falls_back_to_list_price(self, ips_client, ips_data):
        from app import app as _app, _get_payout_amount, _get_item_sale_price
        from models import InventoryItem
        with _app.app_context():
            item = InventoryItem.query.get(ips_data['item_id'])
            assert _get_item_sale_price(item) == 120.0
            assert _get_payout_amount(item) == 60.0

    def test_zero_collected_is_honoured_not_treated_as_missing(self, ips_client, ips_data):
        """A giveaway must pay $0, not silently fall back to the list price."""
        from app import app as _app, _get_payout_amount, db
        from models import InventoryItem
        with _app.app_context():
            item = InventoryItem.query.get(ips_data['item_id'])
            item.sold_in_person = True
            item.amount_collected = Decimal('0.00')
            db.session.commit()
            assert _get_payout_amount(item) == 0.0


# ---------------------------------------------------------------------------
# The mark-sold action
# ---------------------------------------------------------------------------

class TestMarkSold:

    def test_sets_status_sold_at_and_seller_owed(self, ips_client, ips_data):
        from app import app as _app
        from models import InventoryItem
        _login(ips_client, ips_data['admin_email'])
        resp = _mark_sold(ips_client, ips_data['item_id'], '100')
        _logout(ips_client)

        assert resp.status_code == 200
        assert resp.get_json()['payout_amount'] == 50.0
        with _app.app_context():
            item = InventoryItem.query.get(ips_data['item_id'])
            assert item.status == 'sold'
            assert item.sold_at is not None
            assert item.sold_in_person is True
            assert Decimal(str(item.amount_collected)) == Decimal('100.00')
            assert item.sold_by_id is not None
            assert item.payout_sent is False  # seller still owed

    def test_decrements_category_stock(self, ips_client, ips_data):
        from app import app as _app
        from models import InventoryCategory
        _login(ips_client, ips_data['admin_email'])
        _mark_sold(ips_client, ips_data['item_id'], '120')
        _logout(ips_client)
        with _app.app_context():
            assert InventoryCategory.query.get(ips_data['cat_id']).count_in_stock == 4

    def test_removes_item_from_other_shoppers_carts(self, ips_client, ips_data):
        """The whole point: nobody can check out with an item sold at the door."""
        from app import app as _app, db
        from models import Cart, CartItem

        _login(ips_client, ips_data['shopper_email'])
        ips_client.post(f"/cart/add/{ips_data['item_id']}", data={})
        _logout(ips_client)

        with _app.app_context():
            assert CartItem.query.filter_by(item_id=ips_data['item_id']).count() == 1

        _login(ips_client, ips_data['admin_email'])
        resp = _mark_sold(ips_client, ips_data['item_id'], '120')
        _logout(ips_client)

        assert resp.get_json()['carts_cleared'] == 1
        with _app.app_context():
            assert CartItem.query.filter_by(item_id=ips_data['item_id']).count() == 0

    def test_item_no_longer_addable_to_cart(self, ips_client, ips_data):
        from app import app as _app
        from models import CartItem
        _login(ips_client, ips_data['admin_email'])
        _mark_sold(ips_client, ips_data['item_id'], '120')
        _logout(ips_client)

        _login(ips_client, ips_data['shopper_email'])
        ips_client.post(f"/cart/add/{ips_data['item_id']}", data={})
        _logout(ips_client)
        with _app.app_context():
            assert CartItem.query.filter_by(item_id=ips_data['item_id']).count() == 0

    def test_second_mark_is_rejected(self, ips_client, ips_data):
        """Two workers closing the same deal must not double-decrement stock."""
        from app import app as _app
        from models import InventoryCategory
        _login(ips_client, ips_data['admin_email'])
        first = _mark_sold(ips_client, ips_data['item_id'], '120')
        second = _mark_sold(ips_client, ips_data['item_id'], '120')
        _logout(ips_client)

        assert first.status_code == 200
        assert second.status_code == 409
        assert 'already marked sold' in second.get_json()['error']
        with _app.app_context():
            assert InventoryCategory.query.get(ips_data['cat_id']).count_in_stock == 4

    def test_amount_is_optional(self, ips_client, ips_data):
        from app import app as _app
        from models import InventoryItem
        _login(ips_client, ips_data['admin_email'])
        resp = _mark_sold(ips_client, ips_data['item_id'])
        _logout(ips_client)
        assert resp.status_code == 200
        with _app.app_context():
            item = InventoryItem.query.get(ips_data['item_id'])
            assert item.status == 'sold'
            assert item.sold_in_person is False
            assert item.amount_collected is None

    def test_rejects_garbage_amount(self, ips_client, ips_data):
        from app import app as _app
        from models import InventoryItem
        _login(ips_client, ips_data['admin_email'])
        resp = _mark_sold(ips_client, ips_data['item_id'], 'a hundred bucks')
        _logout(ips_client)
        assert resp.status_code == 400
        with _app.app_context():
            assert InventoryItem.query.get(ips_data['item_id']).status == 'available'

    def test_rejects_negative_amount(self, ips_client, ips_data):
        from app import app as _app
        from models import InventoryItem
        _login(ips_client, ips_data['admin_email'])
        resp = _mark_sold(ips_client, ips_data['item_id'], '-50')
        _logout(ips_client)
        assert resp.status_code == 400
        with _app.app_context():
            assert InventoryItem.query.get(ips_data['item_id']).status == 'available'


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

class TestAuth:

    def test_campus_director_can_mark_sold(self, ips_client, ips_data):
        from app import app as _app
        from models import InventoryItem
        _login(ips_client, ips_data['director_email'])
        resp = _mark_sold(ips_client, ips_data['item_id'], '90')
        _logout(ips_client)
        assert resp.status_code == 200
        with _app.app_context():
            assert InventoryItem.query.get(ips_data['item_id']).status == 'sold'

    def test_plain_user_cannot(self, ips_client, ips_data):
        from app import app as _app
        from models import InventoryItem
        _login(ips_client, ips_data['civilian_email'])
        resp = _mark_sold(ips_client, ips_data['item_id'], '90')
        _logout(ips_client)
        assert resp.status_code == 403
        with _app.app_context():
            assert InventoryItem.query.get(ips_data['item_id']).status == 'available'


# ---------------------------------------------------------------------------
# Downstream: payouts
# ---------------------------------------------------------------------------

class TestPayoutSurfaces:

    def test_unpaid_queue_shows_collected_amount(self, ips_client, ips_data):
        _login(ips_client, ips_data['admin_email'])
        _mark_sold(ips_client, ips_data['item_id'], '100')
        resp = ips_client.get('/admin/payouts')
        _logout(ips_client)

        assert resp.status_code == 200
        body = resp.data.decode()
        assert 'collected $100.00' in body
        assert '$50.00' in body          # payout on the collected amount
        assert 'in person' in body

    def test_csv_export_records_both_prices(self, ips_client, ips_data):
        _login(ips_client, ips_data['admin_email'])
        _mark_sold(ips_client, ips_data['item_id'], '100')
        resp = ips_client.get('/admin/payouts/export')
        _logout(ips_client)

        assert resp.status_code == 200
        text = resp.data.decode()
        header = text.splitlines()[0]
        assert 'list_price' in header and 'sale_price' in header
        assert 'sold_in_person' in header and 'sold_by' in header

        row = [l for l in text.splitlines() if str(ips_data['item_id']) in l][0]
        cells = row.split(',')
        assert '120.0' in cells      # list price retained
        assert '100.0' in cells      # what was actually collected
        assert '50.0' in cells       # payout, computed from the collected amount
        assert 'True' in cells       # sold_in_person

    def test_marking_seller_paid_uses_collected_total(self, ips_client, ips_data):
        from app import app as _app
        from models import InventoryItem
        _login(ips_client, ips_data['admin_email'])
        _mark_sold(ips_client, ips_data['item_id'], '100')
        with patch('app.send_email', return_value=True):
            resp = ips_client.post(
                f"/admin/payouts/seller/{ips_data['seller_id']}/mark_paid",
                follow_redirects=True)
        _logout(ips_client)

        assert resp.status_code == 200
        assert b'$50.00' in resp.data
        with _app.app_context():
            item = InventoryItem.query.get(ips_data['item_id'])
            assert item.payout_sent is True
            assert item.payout_sent_at is not None


# ---------------------------------------------------------------------------
# Downstream: Facebook export
# ---------------------------------------------------------------------------

class TestFbExport:

    def _make_exportable(self, app, item_id):
        """Satisfy every clause in _shop_eligible_clauses().

        Shop-ready means: AI approved + priced + storage assigned + re-photographed
        (an ItemPhoto with captured_at set) + matched to a non-internal seller.
        """
        from app import db
        from datetime import datetime as _dt
        from models import InventoryItem, StorageLocation, ItemPhoto
        with app.app_context():
            loc = StorageLocation.query.first()
            if not loc:
                return False
            item = InventoryItem.query.get(item_id)
            item.ai_approved = True
            item.needs_new_photo = False
            item.storage_location_id = loc.id
            item.rephoto_disposition = None
            db.session.add(ItemPhoto(item_id=item.id, photo_url='ips_test.jpg',
                                     captured_at=_dt.utcnow(), sort_order=0))
            db.session.commit()
            return True

    def test_sold_item_drops_out_of_fb_export(self, ips_client, ips_data):
        """An item sold at the door must not still be listable on Facebook."""
        from app import app as _app, _fb_export_query
        if not self._make_exportable(_app, ips_data['item_id']):
            pytest.skip('no StorageLocation available in this database')

        with _app.app_context():
            before = {i.id for i in _fb_export_query(unposted_only=False).all()}

        _login(ips_client, ips_data['admin_email'])
        _mark_sold(ips_client, ips_data['item_id'], '100')
        _logout(ips_client)

        with _app.app_context():
            after = {i.id for i in _fb_export_query(unposted_only=False).all()}

        assert ips_data['item_id'] in before, 'fixture item was not exportable to begin with'
        assert ips_data['item_id'] not in after

    def test_eligible_count_drops_by_exactly_one(self, ips_client, ips_data):
        """No sibling unit silently takes its place in the poster's queue."""
        from app import app as _app, _fb_export_query
        if not self._make_exportable(_app, ips_data['item_id']):
            pytest.skip('no StorageLocation available in this database')

        with _app.app_context():
            before = _fb_export_query(unposted_only=False).count()

        _login(ips_client, ips_data['admin_email'])
        _mark_sold(ips_client, ips_data['item_id'], '100')
        _logout(ips_client)

        with _app.app_context():
            assert _fb_export_query(unposted_only=False).count() == before - 1


# ---------------------------------------------------------------------------
# The legacy /admin page button shares the same logic
# ---------------------------------------------------------------------------

class TestLegacyMarkSold:

    def test_legacy_button_also_clears_carts(self, ips_client, ips_data):
        """The old dashboard's Sold button must not leave the item in carts either."""
        from app import app as _app
        from models import CartItem, InventoryItem

        _login(ips_client, ips_data['shopper_email'])
        ips_client.post(f"/cart/add/{ips_data['item_id']}", data={})
        _logout(ips_client)
        with _app.app_context():
            assert CartItem.query.filter_by(item_id=ips_data['item_id']).count() == 1

        _login(ips_client, ips_data['admin_email'])
        with patch('app.send_email', return_value=True):
            ips_client.post('/admin', data={'mark_sold': str(ips_data['item_id'])},
                            follow_redirects=True)
        _logout(ips_client)

        with _app.app_context():
            item = InventoryItem.query.get(ips_data['item_id'])
            assert item.status == 'sold'
            assert item.sold_at is not None
            assert CartItem.query.filter_by(item_id=ips_data['item_id']).count() == 0
