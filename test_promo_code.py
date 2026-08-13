"""Tests for the checkout promo code (free-delivery code, default "pickup").

Run with: python3 -m pytest test_promo_code.py -v

Coverage:
- _validate_promo_code() normalization + rejection
- Promo input rendered on the review page; hidden when the code is blanked out
- Applying a valid code zeroes the delivery fee and total; invalid code does not
- Promo survives an address edit
- Remove clears it
- Order row records promo_code and delivery_fee=0 at Stripe-session creation
"""

import pytest
from decimal import Decimal
from unittest.mock import patch, MagicMock
import uuid


def _uid():
    return uuid.uuid4().hex[:10]


@pytest.fixture(scope='module')
def promo_client():
    from app import app as _app, db
    from models import AppSetting

    _app.config['TESTING'] = True
    _app.config['WTF_CSRF_ENABLED'] = False
    _app.config['SECRET_KEY'] = 'test-secret-promo'
    _app.config['SERVER_NAME'] = 'localhost'

    with _app.test_client() as client:
        with _app.app_context():
            for key, val in [
                ('store_open_date', '2020-01-01'),
                ('warehouse_lat', '35.9132'),
                ('warehouse_lng', '-79.0558'),
                ('delivery_zone_boundaries', '5,10,15,20'),
                ('delivery_zone_fees', '15,20,25,30'),
                ('sales_tax_rate', '0.0725'),
                ('flexible_delivery_discount', '5'),
                ('cart_hold_minutes', '30'),
                ('bundle_min_items', '2'),
                ('promo_free_delivery_code', 'pickup'),
            ]:
                AppSetting.set(key, val)
            db.session.commit()
            yield client


@pytest.fixture(scope='module')
def promo_users(promo_client):
    from app import app as _app, db
    from models import User
    tag = _uid()
    with _app.app_context():
        seller = User(email=f'promo_seller_{tag}@test.com', full_name='Promo Seller', is_seller=True)
        seller.set_password('testpass123')
        buyer = User(email=f'promo_buyer_{tag}@test.com', full_name='Promo Buyer')
        buyer.set_password('testpass123')
        db.session.add_all([seller, buyer])
        db.session.commit()
        return seller.id, buyer.id


@pytest.fixture
def promo_item(promo_client, promo_users):
    """A single fresh available item (single item = delivery fee applies, no bundle)."""
    from app import app as _app, db
    from models import InventoryItem
    seller_id, _ = promo_users
    with _app.app_context():
        item = InventoryItem(description=f'Promo Item {_uid()}', price=Decimal('100.00'),
                             status='available', seller_id=seller_id)
        db.session.add(item)
        db.session.commit()
        return item.id


def _login(client, email, password='testpass123'):
    return client.post('/login', data={'email': email, 'password': password}, follow_redirects=True)


def _logout(client):
    client.get('/logout', follow_redirects=True)


def _start_checkout(client, buyer_email, item_ids, app):
    """Log in, clear carts, add items, run /cart/checkout, submit the address."""
    from app import db
    from models import User, Cart, CartItem

    _login(client, buyer_email)
    with app.app_context():
        buyer = User.query.filter_by(email=buyer_email).first()
        for cart in Cart.query.filter_by(user_id=buyer.id).all():
            CartItem.query.filter_by(cart_id=cart.id).delete()
        Cart.query.filter_by(user_id=buyer.id).delete()
        db.session.commit()

    for iid in item_ids:
        client.post(f'/cart/add/{iid}', data={})
    client.post('/cart/checkout', follow_redirects=False)

    with patch('app.geocode_address', return_value=(35.97, -79.06)), \
         patch('app.haversine_miles', return_value=3.0):
        client.post('/checkout/delivery', data={
            'street': '100 Main St', 'city': 'Chapel Hill', 'state': 'NC', 'zip': '27514',
        }, follow_redirects=False)


# ---------------------------------------------------------------------------
# Unit: _validate_promo_code
# ---------------------------------------------------------------------------

class TestValidatePromoCode:

    def test_exact_match(self, promo_client):
        from app import app as _app, _validate_promo_code
        with _app.app_context():
            assert _validate_promo_code('pickup') == 'pickup'

    def test_case_and_whitespace_insensitive(self, promo_client):
        from app import app as _app, _validate_promo_code
        with _app.app_context():
            assert _validate_promo_code('  PickUp  ') == 'pickup'

    def test_wrong_code_rejected(self, promo_client):
        from app import app as _app, _validate_promo_code
        with _app.app_context():
            assert _validate_promo_code('freeship') is None

    def test_empty_rejected(self, promo_client):
        from app import app as _app, _validate_promo_code
        with _app.app_context():
            assert _validate_promo_code('') is None
            assert _validate_promo_code(None) is None

    def test_blank_setting_disables_promos(self, promo_client):
        """Clearing the AppSetting turns the feature off — nothing validates."""
        from app import app as _app, _validate_promo_code, db
        from models import AppSetting
        with _app.app_context():
            AppSetting.set('promo_free_delivery_code', '')
            db.session.commit()
            try:
                assert _validate_promo_code('pickup') is None
            finally:
                AppSetting.set('promo_free_delivery_code', 'pickup')
                db.session.commit()


# ---------------------------------------------------------------------------
# Review page rendering
# ---------------------------------------------------------------------------

class TestReviewPagePromoUI:

    def test_promo_input_shown(self, promo_client, promo_users, promo_item):
        from app import app as _app
        from models import User
        _, buyer_id = promo_users
        with _app.app_context():
            buyer = User.query.get(buyer_id)

        _start_checkout(promo_client, buyer.email, [promo_item], _app)
        resp = promo_client.get('/checkout/review')
        _logout(promo_client)

        assert resp.status_code == 200
        assert b'name="promo_code"' in resp.data
        assert b'Promo code' in resp.data

    def test_promo_input_hidden_when_disabled(self, promo_client, promo_users, promo_item):
        from app import app as _app, db
        from models import User, AppSetting
        _, buyer_id = promo_users
        with _app.app_context():
            buyer = User.query.get(buyer_id)
            AppSetting.set('promo_free_delivery_code', '')
            db.session.commit()

        try:
            _start_checkout(promo_client, buyer.email, [promo_item], _app)
            resp = promo_client.get('/checkout/review')
            _logout(promo_client)
            assert resp.status_code == 200
            assert b'name="promo_code"' not in resp.data
        finally:
            with _app.app_context():
                AppSetting.set('promo_free_delivery_code', 'pickup')
                db.session.commit()


# ---------------------------------------------------------------------------
# Applying the code
# ---------------------------------------------------------------------------

class TestApplyPromo:

    def test_valid_code_waives_delivery_fee(self, promo_client, promo_users, promo_item):
        """$100 item, zone 1 ($15) → total drops to 100 + 7.25 tax = $107.25."""
        from app import app as _app
        from models import User
        _, buyer_id = promo_users
        with _app.app_context():
            buyer = User.query.get(buyer_id)

        _start_checkout(promo_client, buyer.email, [promo_item], _app)
        before = promo_client.get('/checkout/review')
        assert b'$122.25' in before.data  # 100 + 7.25 + 15

        promo_client.post('/checkout/promo', data={'promo_code': 'PICKUP'})
        after = promo_client.get('/checkout/review')
        _logout(promo_client)

        assert after.status_code == 200
        assert b'PICKUP' in after.data
        assert b'$107.25' in after.data
        assert b'$122.25' not in after.data

    def test_invalid_code_leaves_fee_in_place(self, promo_client, promo_users, promo_item):
        from app import app as _app
        from models import User
        _, buyer_id = promo_users
        with _app.app_context():
            buyer = User.query.get(buyer_id)

        _start_checkout(promo_client, buyer.email, [promo_item], _app)
        promo_client.post('/checkout/promo', data={'promo_code': 'nope'})
        resp = promo_client.get('/checkout/review')
        _logout(promo_client)

        assert b'$122.25' in resp.data
        assert b'name="promo_code"' in resp.data  # input still offered

    def test_remove_restores_fee(self, promo_client, promo_users, promo_item):
        from app import app as _app
        from models import User
        _, buyer_id = promo_users
        with _app.app_context():
            buyer = User.query.get(buyer_id)

        _start_checkout(promo_client, buyer.email, [promo_item], _app)
        promo_client.post('/checkout/promo', data={'promo_code': 'pickup'})
        promo_client.post('/checkout/promo', data={'remove': '1'})
        resp = promo_client.get('/checkout/review')
        _logout(promo_client)

        assert b'$122.25' in resp.data

    def test_promo_survives_address_change(self, promo_client, promo_users, promo_item):
        from app import app as _app
        from models import User
        _, buyer_id = promo_users
        with _app.app_context():
            buyer = User.query.get(buyer_id)

        _start_checkout(promo_client, buyer.email, [promo_item], _app)
        promo_client.post('/checkout/promo', data={'promo_code': 'pickup'})

        with patch('app.geocode_address', return_value=(35.97, -79.06)), \
             patch('app.haversine_miles', return_value=3.0):
            promo_client.post('/checkout/delivery', data={
                'street': '200 Franklin St', 'city': 'Chapel Hill', 'state': 'NC', 'zip': '27514',
            }, follow_redirects=False)

        resp = promo_client.get('/checkout/review')
        _logout(promo_client)
        assert b'$107.25' in resp.data

    def test_promo_route_without_pending_order_redirects_to_cart(self, promo_client):
        with promo_client.session_transaction() as sess:
            sess.pop('pending_delivery', None)
        resp = promo_client.post('/checkout/promo', data={'promo_code': 'pickup'})
        assert resp.status_code == 302
        assert '/cart' in resp.headers['Location']


# ---------------------------------------------------------------------------
# Order record
# ---------------------------------------------------------------------------

class TestPromoOnOrder:

    def test_order_records_promo_and_zero_fee(self, promo_client, promo_users, promo_item):
        from app import app as _app
        from models import User, Order
        _, buyer_id = promo_users
        with _app.app_context():
            buyer = User.query.get(buyer_id)

        _start_checkout(promo_client, buyer.email, [promo_item], _app)
        promo_client.post('/checkout/promo', data={'promo_code': 'pickup'})

        fake_session = MagicMock()
        fake_session.id = f'cs_test_{_uid()}'
        fake_session.url = 'https://stripe.test/checkout'
        with patch('stripe.checkout.Session.create', return_value=fake_session) as mock_create:
            resp = promo_client.post('/checkout/review', data={'is_flexible': '0'})
        _logout(promo_client)

        assert resp.status_code == 303
        with _app.app_context():
            order = Order.query.filter_by(stripe_checkout_session_id=fake_session.id).first()
            assert order is not None
            assert order.promo_code == 'pickup'
            assert Decimal(str(order.delivery_fee)) == Decimal('0')
            assert Decimal(str(order.total_paid)) == Decimal('107.25')

        # No delivery-fee line item sent to Stripe
        line_names = [li['price_data']['product_data']['name']
                      for li in mock_create.call_args.kwargs['line_items']]
        assert not any('Delivery Fee' in n for n in line_names)
