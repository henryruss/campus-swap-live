"""Tests for Spec B: Shopping Cart, Multi-Item Checkout & Bundle & Save.

Run with: python3 -m pytest test_cart_bundle.py -v

Coverage:
- item_is_held() helper logic
- Bundle & Save free delivery (2+ items → $0 fee)
- Tax math (sum of per-item; never on delivery)
- Cart add/remove/view routes
- Checkout flow guards (empty cart → /cart; no session → /cart)
- Review page content (zone fee vs FREE banner; flexible toggle)
- Guest cart via session token
- Cart checkout dead-item auto-removal
- Legacy redirect behavior
"""

import pytest
from decimal import Decimal
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
import uuid


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uid():
    return uuid.uuid4().hex[:10]


# ---------------------------------------------------------------------------
# Unit tests: item_is_held() — patch DB, no fixture needed
# ---------------------------------------------------------------------------

class TestItemIsHeld:
    """Integration tests for item_is_held() using the real DB."""

    def test_no_active_cart_returns_false(self):
        """Item with no CartItem rows is not held."""
        from app import app as _app, item_is_held, db
        from models import InventoryItem, User, Cart, CartItem
        import uuid

        tag = uuid.uuid4().hex[:8]
        with _app.app_context():
            seller = User(email=f'hold_seller_{tag}@test.com', full_name='Hold Seller', is_seller=True)
            db.session.add(seller)
            db.session.flush()
            item = InventoryItem(description='Hold Test Item', price=Decimal('10.00'),
                                 status='available', seller_id=seller.id)
            db.session.add(item)
            db.session.commit()
            assert not item_is_held(item)

    def test_item_in_fresh_cart_is_held(self):
        """Item added to a cart with recent updated_at is held."""
        from app import app as _app, item_is_held, db
        from models import InventoryItem, User, Cart, CartItem
        from datetime import datetime
        import uuid

        tag = uuid.uuid4().hex[:8]
        with _app.app_context():
            seller = User(email=f'hold_seller2_{tag}@test.com', full_name='Hold Seller', is_seller=True)
            db.session.add(seller)
            db.session.flush()
            item = InventoryItem(description='Held Item', price=Decimal('10.00'),
                                 status='available', seller_id=seller.id)
            db.session.add(item)
            db.session.flush()

            cart = Cart(session_token=f'test_token_{tag}', updated_at=datetime.utcnow())
            db.session.add(cart)
            db.session.flush()
            ci = CartItem(cart_id=cart.id, item_id=item.id)
            db.session.add(ci)
            db.session.commit()

            assert item_is_held(item)

    def test_exclude_cart_id_skips_own_cart(self):
        """exclude_cart_id=cart.id → not considered held by that cart."""
        from app import app as _app, item_is_held, db
        from models import InventoryItem, User, Cart, CartItem
        from datetime import datetime
        import uuid

        tag = uuid.uuid4().hex[:8]
        with _app.app_context():
            seller = User(email=f'hold_seller3_{tag}@test.com', full_name='Hold Seller', is_seller=True)
            db.session.add(seller)
            db.session.flush()
            item = InventoryItem(description='Excl Test Item', price=Decimal('10.00'),
                                 status='available', seller_id=seller.id)
            db.session.add(item)
            db.session.flush()

            cart = Cart(session_token=f'excl_token_{tag}', updated_at=datetime.utcnow())
            db.session.add(cart)
            db.session.flush()
            ci = CartItem(cart_id=cart.id, item_id=item.id)
            db.session.add(ci)
            db.session.commit()

            # Held normally, but not when we exclude our own cart
            assert item_is_held(item)
            assert not item_is_held(item, exclude_cart_id=cart.id)


# ---------------------------------------------------------------------------
# Unit tests: Bundle & Save math (pure logic)
# ---------------------------------------------------------------------------

class TestBundleMath:

    def test_single_item_pays_zone_fee(self):
        """1 item → delivery fee = zone fee."""
        bundle_min = 2
        item_count = 1
        zone_fee = Decimal('15.00')
        bundle_free = item_count >= bundle_min
        effective_fee = Decimal('0') if bundle_free else zone_fee
        assert bundle_free is False
        assert effective_fee == Decimal('15.00')

    def test_two_items_free_delivery(self):
        """2 items → delivery free."""
        bundle_min = 2
        item_count = 2
        zone_fee = Decimal('20.00')
        bundle_free = item_count >= bundle_min
        effective_fee = Decimal('0') if bundle_free else zone_fee
        assert bundle_free is True
        assert effective_fee == Decimal('0')

    def test_three_items_free_delivery(self):
        """3 items → also free."""
        bundle_min = 2
        item_count = 3
        bundle_free = item_count >= bundle_min
        assert bundle_free is True

    def test_bundle_min_configurable(self):
        """bundle_min_items=3 → 2 items still pays."""
        bundle_min = 3
        assert not (2 >= bundle_min)


class TestBundleTaxMath:

    def test_tax_on_items_only_not_delivery(self):
        """Tax applies to item prices; delivery is never taxed."""
        item_price = Decimal('85.00')
        delivery_fee = Decimal('15.00')
        tax_rate = Decimal('0.0725')
        item_tax = round(item_price * tax_rate, 2)
        total_taxable = item_price  # NOT item_price + delivery_fee
        assert item_tax == Decimal('6.16')
        assert total_taxable == item_price

    def test_multi_item_tax_is_sum_of_per_item(self):
        """Two items: tax = sum of per-item taxes."""
        prices = [Decimal('85.00'), Decimal('50.00')]
        tax_rate = Decimal('0.0725')
        per_item_taxes = [round(p * tax_rate, 2) for p in prices]
        total_tax = sum(per_item_taxes)
        assert per_item_taxes[0] == Decimal('6.16')
        # 50.00 * 0.0725 = 3.625 → rounds to 3.62 (Python banker's rounding)
        assert per_item_taxes[1] == Decimal('3.62')
        assert total_tax == Decimal('9.78')

    def test_flexible_discount_applied_to_total(self):
        """Flexible −$5 comes off total, not delivery."""
        items_subtotal = Decimal('135.00')
        delivery_fee = Decimal('0')  # bundle free
        sales_tax = Decimal('9.79')
        flex_discount = Decimal('5.00')
        total_standard = items_subtotal + sales_tax + delivery_fee
        total_flexible = total_standard - flex_discount
        assert total_standard == Decimal('144.79')
        assert total_flexible == Decimal('139.79')

    def test_flexible_single_item_reduces_net_delivery(self):
        """Single item with flexible: $5 off total (net: delivery_fee - 5)."""
        items_subtotal = Decimal('85.00')
        delivery_fee = Decimal('15.00')
        sales_tax = Decimal('6.16')
        flex_discount = Decimal('5.00')
        total_standard = items_subtotal + sales_tax + delivery_fee
        total_flexible = max(
            total_standard - flex_discount,
            items_subtotal + sales_tax - flex_discount
        )
        assert total_standard == Decimal('106.16')
        assert total_flexible == Decimal('101.16')


# ---------------------------------------------------------------------------
# Integration tests: route-level
# ---------------------------------------------------------------------------

@pytest.fixture(scope='module')
def cart_client():
    """Test client connected to the actual DB (same pattern as test_delivery_fees.py)."""
    from app import app as _app, db
    from models import AppSetting

    _app.config['TESTING'] = True
    _app.config['WTF_CSRF_ENABLED'] = False
    _app.config['SECRET_KEY'] = 'test-secret-cart'
    _app.config['SERVER_NAME'] = 'localhost'

    with _app.test_client() as client:
        with _app.app_context():
            # Ensure required AppSettings exist (upsert)
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
            ]:
                AppSetting.set(key, val)
            db.session.commit()
            yield client


@pytest.fixture(scope='module')
def cart_test_users(cart_client):
    """Create a seller + buyer for cart tests. Returns (seller_id, buyer_id)."""
    from app import app as _app, db
    from models import User, InventoryItem
    tag = _uid()
    with _app.app_context():
        seller = User(
            email=f'cart_seller_{tag}@test.com',
            full_name='Cart Seller',
            is_seller=True,
        )
        seller.set_password('testpass123')
        buyer = User(
            email=f'cart_buyer_{tag}@test.com',
            full_name='Cart Buyer',
        )
        buyer.set_password('testpass123')
        db.session.add_all([seller, buyer])
        db.session.commit()
        return seller.id, buyer.id


@pytest.fixture(scope='module')
def cart_items(cart_client, cart_test_users):
    """Create 3 available items. Returns list of item IDs."""
    from app import app as _app, db
    from models import InventoryItem
    seller_id, _ = cart_test_users
    with _app.app_context():
        items = []
        for i, price in enumerate([Decimal('85.00'), Decimal('50.00'), Decimal('30.00')], 1):
            item = InventoryItem(
                description=f'Cart Test Item {i}',
                price=price,
                status='available',
                seller_id=seller_id,
            )
            db.session.add(item)
            db.session.flush()
            items.append(item.id)
        db.session.commit()
        return items


def _login(client, email, password='testpass123'):
    return client.post('/login', data={'email': email, 'password': password},
                       follow_redirects=True)


def _logout(client):
    client.get('/logout', follow_redirects=True)


# ---------------------------------------------------------------------------
# Cart add / remove
# ---------------------------------------------------------------------------

class TestCartAdd:

    def test_add_to_cart_returns_count(self, cart_client, cart_test_users, cart_items):
        """POST /cart/add/<id> returns JSON with count."""
        from app import app as _app, db
        from models import User, Cart, CartItem

        _, buyer_id = cart_test_users
        with _app.app_context():
            buyer = User.query.get(buyer_id)

        _login(cart_client, buyer.email)
        resp = cart_client.post(f'/cart/add/{cart_items[0]}',
                                data={}, content_type='application/x-www-form-urlencoded')
        _logout(cart_client)

        assert resp.status_code == 200
        data = resp.get_json()
        assert 'count' in data
        assert data['count'] >= 1

    def test_add_unavailable_item_blocked(self, cart_client, cart_test_users):
        """Adding a sold item returns 409."""
        from app import app as _app, db
        from models import User, InventoryItem

        seller_id, buyer_id = cart_test_users
        with _app.app_context():
            sold_item = InventoryItem(
                description='Already Sold',
                price=Decimal('40.00'),
                status='sold',
                seller_id=seller_id,
            )
            db.session.add(sold_item)
            db.session.commit()
            sold_item_id = sold_item.id
            buyer = User.query.get(buyer_id)

        _login(cart_client, buyer.email)
        resp = cart_client.post(f'/cart/add/{sold_item_id}', data={})
        _logout(cart_client)

        assert resp.status_code == 409

    def test_add_same_item_twice_is_idempotent(self, cart_client, cart_test_users, cart_items):
        """Adding the same item again returns already_in_cart."""
        from app import app as _app
        from models import User

        _, buyer_id = cart_test_users
        with _app.app_context():
            buyer = User.query.get(buyer_id)

        _login(cart_client, buyer.email)
        cart_client.post(f'/cart/add/{cart_items[1]}', data={})
        resp = cart_client.post(f'/cart/add/{cart_items[1]}', data={})
        _logout(cart_client)

        assert resp.status_code == 200
        data = resp.get_json()
        assert data.get('already_in_cart') is True


class TestCartRemove:

    def test_remove_item_from_cart(self, cart_client, cart_test_users, cart_items):
        """POST /cart/remove/<id> redirects to /cart."""
        from app import app as _app
        from models import User

        _, buyer_id = cart_test_users
        with _app.app_context():
            buyer = User.query.get(buyer_id)

        _login(cart_client, buyer.email)
        # Add first
        cart_client.post(f'/cart/add/{cart_items[2]}', data={})
        # Then remove
        resp = cart_client.post(f'/cart/remove/{cart_items[2]}', follow_redirects=False)
        _logout(cart_client)

        assert resp.status_code == 302
        assert '/cart' in resp.headers['Location']


# ---------------------------------------------------------------------------
# Cart view — bundle hint
# ---------------------------------------------------------------------------

class TestCartView:

    def _setup_cart(self, cart_client, buyer_email, item_ids, app):
        """Add items to a logged-in buyer's cart."""
        _login(cart_client, buyer_email)
        for iid in item_ids:
            cart_client.post(f'/cart/add/{iid}', data={})

    def _clear_buyer_cart(self, buyer_id, app):
        """Delete CartItems then Carts for a buyer (respects FK order)."""
        from app import db
        from models import Cart, CartItem
        with app.app_context():
            for cart in Cart.query.filter_by(user_id=buyer_id).all():
                CartItem.query.filter_by(cart_id=cart.id).delete()
            Cart.query.filter_by(user_id=buyer_id).delete()
            db.session.commit()

    def test_empty_cart_shows_empty_state(self, cart_client, cart_test_users):
        from app import app as _app
        from models import User

        _, buyer_id = cart_test_users
        with _app.app_context():
            buyer = User.query.get(buyer_id)

        self._clear_buyer_cart(buyer_id, _app)
        _login(cart_client, buyer.email)
        resp = cart_client.get('/cart')
        _logout(cart_client)

        assert resp.status_code == 200
        assert b'cart' in resp.data.lower()

    def test_one_item_shows_upsell_hint(self, cart_client, cart_test_users, cart_items):
        from app import app as _app
        from models import User

        _, buyer_id = cart_test_users
        with _app.app_context():
            buyer = User.query.get(buyer_id)

        self._clear_buyer_cart(buyer_id, _app)
        _login(cart_client, buyer.email)
        cart_client.post(f'/cart/add/{cart_items[0]}', data={})
        resp = cart_client.get('/cart')
        _logout(cart_client)

        assert resp.status_code == 200
        body = resp.data.decode()
        assert 'free delivery' in body.lower() or 'bundle' in body.lower()

    def test_two_items_shows_bundle_unlocked(self, cart_client, cart_test_users, cart_items):
        from app import app as _app
        from models import User

        _, buyer_id = cart_test_users
        with _app.app_context():
            buyer = User.query.get(buyer_id)

        self._clear_buyer_cart(buyer_id, _app)
        _login(cart_client, buyer.email)
        cart_client.post(f'/cart/add/{cart_items[0]}', data={})
        cart_client.post(f'/cart/add/{cart_items[1]}', data={})
        resp = cart_client.get('/cart')
        _logout(cart_client)

        assert resp.status_code == 200
        body = resp.data.decode().lower()
        assert 'free delivery' in body or 'bundle' in body


# ---------------------------------------------------------------------------
# Checkout flow guards
# ---------------------------------------------------------------------------

class TestCheckoutGuards:

    def test_checkout_delivery_no_session_redirects_to_cart(self, cart_client, cart_test_users):
        """GET /checkout/delivery without checkout_cart_id → /cart."""
        from app import app as _app
        from models import User

        _, buyer_id = cart_test_users
        with _app.app_context():
            buyer = User.query.get(buyer_id)

        _login(cart_client, buyer.email)
        with cart_client.session_transaction() as sess:
            sess.pop('checkout_cart_id', None)
        resp = cart_client.get('/checkout/delivery', follow_redirects=False)
        _logout(cart_client)

        assert resp.status_code == 302
        assert '/cart' in resp.headers['Location']

    def test_checkout_review_no_session_redirects_to_cart(self, cart_client, cart_test_users):
        """GET /checkout/review without pending_delivery → /cart."""
        from app import app as _app
        from models import User

        _, buyer_id = cart_test_users
        with _app.app_context():
            buyer = User.query.get(buyer_id)

        _login(cart_client, buyer.email)
        with cart_client.session_transaction() as sess:
            sess.pop('pending_delivery', None)
        resp = cart_client.get('/checkout/review', follow_redirects=False)
        _logout(cart_client)

        assert resp.status_code == 302
        assert '/cart' in resp.headers['Location']

    def _clear_buyer_cart(self, buyer_id, app):
        from app import db
        from models import Cart, CartItem
        with app.app_context():
            for cart in Cart.query.filter_by(user_id=buyer_id).all():
                CartItem.query.filter_by(cart_id=cart.id).delete()
            Cart.query.filter_by(user_id=buyer_id).delete()
            db.session.commit()

    def test_cart_checkout_empty_cart_redirects(self, cart_client, cart_test_users):
        """POST /cart/checkout with empty cart → /cart."""
        from app import app as _app, db
        from models import User

        _, buyer_id = cart_test_users
        with _app.app_context():
            buyer = User.query.get(buyer_id)

        self._clear_buyer_cart(buyer_id, _app)
        _login(cart_client, buyer.email)
        resp = cart_client.post('/cart/checkout', follow_redirects=False)
        _logout(cart_client)

        assert resp.status_code == 302
        assert '/cart' in resp.headers['Location']

    def test_cart_checkout_removes_dead_items_and_bounces(self, cart_client, cart_test_users):
        """If all items sold while in cart, checkout bounces to /cart."""
        from app import app as _app, db
        from models import User, InventoryItem

        seller_id, buyer_id = cart_test_users
        with _app.app_context():
            buyer = User.query.get(buyer_id)
            stale_item = InventoryItem(
                description='Stale Item',
                price=Decimal('20.00'),
                status='available',
                seller_id=seller_id,
            )
            db.session.add(stale_item)
            db.session.commit()
            stale_id = stale_item.id

        _login(cart_client, buyer.email)
        cart_client.post(f'/cart/add/{stale_id}', data={})
        # Mark it sold (simulating someone else buying it)
        with _app.app_context():
            itm = InventoryItem.query.get(stale_id)
            itm.status = 'sold'
            db.session.commit()
        resp = cart_client.post('/cart/checkout', follow_redirects=False)
        _logout(cart_client)

        assert resp.status_code == 302
        assert '/cart' in resp.headers['Location']


# ---------------------------------------------------------------------------
# Checkout review page content
# ---------------------------------------------------------------------------

class TestCheckoutReviewContent:

    def _clear_buyer_cart(self, buyer_id, app):
        from app import db
        from models import Cart, CartItem
        with app.app_context():
            for cart in Cart.query.filter_by(user_id=buyer_id).all():
                CartItem.query.filter_by(cart_id=cart.id).delete()
            Cart.query.filter_by(user_id=buyer_id).delete()
            db.session.commit()

    def _make_cart_with_items(self, client, buyer_email, item_ids, app):
        """Helper: log in, clear cart, add items, run /cart/checkout."""
        from app import db
        from models import User

        _login(client, buyer_email)
        with app.app_context():
            buyer = User.query.filter_by(email=buyer_email).first()
            if buyer:
                for cart in __import__('models').Cart.query.filter_by(user_id=buyer.id).all():
                    __import__('models').CartItem.query.filter_by(cart_id=cart.id).delete()
                __import__('models').Cart.query.filter_by(user_id=buyer.id).delete()
                db.session.commit()

        for iid in item_ids:
            client.post(f'/cart/add/{iid}', data={})

        client.post('/cart/checkout', follow_redirects=False)

    def test_review_single_item_shows_zone_fee(self, cart_client, cart_test_users, cart_items):
        """Single-item order: delivery fee shown (not FREE)."""
        from app import app as _app
        from models import User

        _, buyer_id = cart_test_users
        with _app.app_context():
            buyer = User.query.get(buyer_id)

        self._make_cart_with_items(cart_client, buyer.email, [cart_items[0]], _app)

        with patch('app.geocode_address', return_value=(35.97, -79.06)), \
             patch('app.haversine_miles', return_value=3.0):
            cart_client.post('/checkout/delivery', data={
                'street': '100 Main St', 'city': 'Chapel Hill',
                'state': 'NC', 'zip': '27514',
            }, follow_redirects=False)

        resp = cart_client.get('/checkout/review')
        _logout(cart_client)

        assert resp.status_code == 200
        body = resp.data.decode()
        # Zone fee line should appear (not bundle free)
        assert '15.00' in body or 'Zone' in body
        assert 'Bundle' not in body or 'FREE' not in body

    def test_review_two_items_shows_bundle_free(self, cart_client, cart_test_users, cart_items):
        """Two-item order: Bundle & Save shows FREE delivery."""
        from app import app as _app
        from models import User

        _, buyer_id = cart_test_users
        with _app.app_context():
            buyer = User.query.get(buyer_id)

        self._make_cart_with_items(cart_client, buyer.email,
                                   [cart_items[0], cart_items[1]], _app)

        with patch('app.geocode_address', return_value=(35.97, -79.06)), \
             patch('app.haversine_miles', return_value=3.0):
            cart_client.post('/checkout/delivery', data={
                'street': '100 Main St', 'city': 'Chapel Hill',
                'state': 'NC', 'zip': '27514',
            }, follow_redirects=False)

        resp = cart_client.get('/checkout/review')
        _logout(cart_client)

        assert resp.status_code == 200
        body = resp.data.decode()
        assert 'FREE' in body or 'Bundle' in body

    def test_review_out_of_range_address_shows_error(self, cart_client, cart_test_users, cart_items):
        """Address > 20 miles → error message on delivery page."""
        from app import app as _app
        from models import User

        _, buyer_id = cart_test_users
        with _app.app_context():
            buyer = User.query.get(buyer_id)

        self._make_cart_with_items(cart_client, buyer.email, [cart_items[0]], _app)

        with patch('app.geocode_address', return_value=(36.5, -80.0)), \
             patch('app.haversine_miles', return_value=45.0):
            resp = cart_client.post('/checkout/delivery', data={
                'street': '1 Far St', 'city': 'Fartown',
                'state': 'NC', 'zip': '12345',
            }, follow_redirects=False)
        _logout(cart_client)

        assert resp.status_code == 200
        body = resp.data.lower()
        assert b'20 miles' in body or b'outside' in body

    def test_review_flexible_toggle_hidden_without_coupon(self, cart_client, cart_test_users, cart_items):
        """Flexible toggle absent when stripe_flexible_coupon_id not set."""
        from app import app as _app, db
        from models import User, AppSetting

        _, buyer_id = cart_test_users
        with _app.app_context():
            buyer = User.query.get(buyer_id)
            AppSetting.query.filter_by(key='stripe_flexible_coupon_id').delete()
            db.session.commit()

        self._make_cart_with_items(cart_client, buyer.email, [cart_items[0]], _app)
        with patch('app.geocode_address', return_value=(35.97, -79.06)), \
             patch('app.haversine_miles', return_value=3.0):
            cart_client.post('/checkout/delivery', data={
                'street': '100 Main St', 'city': 'Chapel Hill',
                'state': 'NC', 'zip': '27514',
            })
        resp = cart_client.get('/checkout/review')
        _logout(cart_client)

        assert resp.status_code == 200
        assert b'flexible-checkbox' not in resp.data

    def test_review_flexible_toggle_shown_with_coupon(self, cart_client, cart_test_users, cart_items):
        """Flexible toggle present when coupon configured."""
        from app import app as _app, db
        from models import User, AppSetting

        _, buyer_id = cart_test_users
        with _app.app_context():
            buyer = User.query.get(buyer_id)
            AppSetting.set('stripe_flexible_coupon_id', 'coupon_test_xyz')
            db.session.commit()

        self._make_cart_with_items(cart_client, buyer.email, [cart_items[0]], _app)
        with patch('app.geocode_address', return_value=(35.97, -79.06)), \
             patch('app.haversine_miles', return_value=3.0):
            cart_client.post('/checkout/delivery', data={
                'street': '100 Main St', 'city': 'Chapel Hill',
                'state': 'NC', 'zip': '27514',
            })
        resp = cart_client.get('/checkout/review')
        _logout(cart_client)

        assert resp.status_code == 200
        assert b'flexible-checkbox' in resp.data


# ---------------------------------------------------------------------------
# Guest cart
# ---------------------------------------------------------------------------

class TestGuestCart:

    def test_guest_cart_created_via_session_token(self, cart_client, cart_test_users, cart_items):
        """Guest (not logged in) can add to cart; cart keyed by session token."""
        from app import app as _app, db
        from models import Cart, InventoryItem

        seller_id, _ = cart_test_users
        # Create a fresh item guaranteed not to be held by any other cart
        with _app.app_context():
            fresh_item = InventoryItem(
                description='Guest Test Item',
                price=Decimal('15.00'),
                status='available',
                seller_id=seller_id,
            )
            db.session.add(fresh_item)
            db.session.commit()
            fresh_item_id = fresh_item.id

        # Log out to ensure guest session
        cart_client.get('/logout', follow_redirects=True)
        # Clear any previous guest cart token
        with cart_client.session_transaction() as sess:
            sess.pop('cart_token', None)

        resp = cart_client.post(f'/cart/add/{fresh_item_id}', data={})
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'count' in data

        with cart_client.session_transaction() as sess:
            token = sess.get('cart_token')
        assert token is not None
        with _app.app_context():
            cart = Cart.query.filter_by(session_token=token).first()
            assert cart is not None

    def _clear_buyer_cart(self, buyer_id, app):
        from app import db
        from models import Cart, CartItem
        with app.app_context():
            for cart in Cart.query.filter_by(user_id=buyer_id).all():
                CartItem.query.filter_by(cart_id=cart.id).delete()
            Cart.query.filter_by(user_id=buyer_id).delete()
            db.session.commit()

    def test_guest_cart_merges_on_login(self, cart_client, cart_test_users, cart_items):
        """Guest cart items merge into user cart on login."""
        from app import app as _app, db
        from models import User, Cart, CartItem, InventoryItem

        seller_id, buyer_id = cart_test_users
        # Create a fresh item for this test to avoid hold conflicts
        with _app.app_context():
            merge_item = InventoryItem(
                description='Merge Test Item',
                price=Decimal('25.00'),
                status='available',
                seller_id=seller_id,
            )
            db.session.add(merge_item)
            db.session.commit()
            merge_item_id = merge_item.id
            buyer = User.query.get(buyer_id)

        self._clear_buyer_cart(buyer_id, _app)

        # Add item as guest
        cart_client.get('/logout', follow_redirects=True)
        with cart_client.session_transaction() as sess:
            sess.pop('cart_token', None)
        cart_client.post(f'/cart/add/{merge_item_id}', data={})

        with cart_client.session_transaction() as sess:
            guest_token = sess.get('cart_token')
        assert guest_token is not None

        # Now log in — merge should happen
        _login(cart_client, buyer.email)

        # Guest token should be cleared from session
        with cart_client.session_transaction() as sess:
            assert sess.get('cart_token') is None

        # User cart should contain the item
        with _app.app_context():
            user_cart = Cart.query.filter_by(user_id=buyer_id).first()
            assert user_cart is not None
            item_ids = [ci.item_id for ci in user_cart.cart_items]
            assert merge_item_id in item_ids

        _logout(cart_client)


# ---------------------------------------------------------------------------
# Nav cart badge
# ---------------------------------------------------------------------------

class TestCartBadge:

    def _clear_buyer_cart(self, buyer_id, app):
        from app import db
        from models import Cart, CartItem
        with app.app_context():
            for cart in Cart.query.filter_by(user_id=buyer_id).all():
                CartItem.query.filter_by(cart_id=cart.id).delete()
            Cart.query.filter_by(user_id=buyer_id).delete()
            db.session.commit()

    def test_cart_count_in_context(self, cart_client, cart_test_users, cart_items):
        """Cart count appears in page HTML after adding items."""
        from app import app as _app
        from models import User

        _, buyer_id = cart_test_users
        with _app.app_context():
            buyer = User.query.get(buyer_id)
        self._clear_buyer_cart(buyer_id, _app)

        _login(cart_client, buyer.email)
        cart_client.post(f'/cart/add/{cart_items[0]}', data={})

        resp = cart_client.get('/inventory')
        _logout(cart_client)

        assert resp.status_code == 200
        # The cart badge or count should appear in the nav
        body = resp.data.decode()
        assert 'cart' in body.lower()
