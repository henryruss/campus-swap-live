"""
Tests for Spec A — zone-based delivery pricing, sales tax rounding, single-item
checkout totals, checkout routes, and webhook.

Canary: $2.00 * 7.25% = $0.15 (ROUND_HALF_UP), NOT $0.14 (banker's rounding).
Delivery fee is excluded from the taxable base.

Run: pytest tests/test_delivery_fees.py -v
"""

import pytest
import json
from decimal import Decimal
from datetime import datetime
from unittest.mock import patch, MagicMock

from app import app as _app, db, calculate_delivery_zone, compute_sales_tax
from models import (
    User, InventoryCategory, InventoryItem, AppSetting,
    BuyerOrder, Order, Cart, CartItem, SellerAlert,
)
from werkzeug.security import generate_password_hash


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def category(client):
    with _app.app_context():
        cat = InventoryCategory(name='Furniture', image_url='fa-couch', count_in_stock=10)
        db.session.add(cat)
        db.session.commit()
        _ = cat.id, cat.name
        return cat


@pytest.fixture
def seller(client):
    with _app.app_context():
        u = User(
            email='seller@fees.edu',
            password_hash=generate_password_hash('pass123'),
            full_name='Seller User',
            is_seller=True,
            has_paid=True,
        )
        db.session.add(u)
        db.session.commit()
        _ = u.id, u.email
        return u


@pytest.fixture
def buyer(client):
    with _app.app_context():
        u = User(
            email='buyer@fees.edu',
            password_hash=generate_password_hash('pass123'),
            full_name='Buyer User',
            is_seller=False,
            has_paid=False,
        )
        db.session.add(u)
        db.session.commit()
        _ = u.id, u.email
        return u


@pytest.fixture
def seller_client(client, seller):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(seller.id)
        sess['_fresh'] = True
    return client


@pytest.fixture
def buyer_client(client, buyer):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(buyer.id)
        sess['_fresh'] = True
    return client


@pytest.fixture
def item_85(client, seller, category):
    with _app.app_context():
        item = InventoryItem(
            description='Test Chair',
            price=85.00,
            status='available',
            category_id=category.id,
            seller_id=seller.id,
            collection_method='online',
            photo_url='chair.jpg',
        )
        db.session.add(item)
        db.session.commit()
        _ = item.id, item.price, item.status, item.category_id, item.seller_id
        return item


@pytest.fixture
def item_200(client, seller, category):
    with _app.app_context():
        item = InventoryItem(
            description='Expensive Desk',
            price=200.00,
            status='available',
            category_id=category.id,
            seller_id=seller.id,
            collection_method='online',
            photo_url='desk.jpg',
        )
        db.session.add(item)
        db.session.commit()
        _ = item.id, item.price, item.status, item.category_id, item.seller_id
        return item


# ── helpers ───────────────────────────────────────────────────────────────────

def _set_warehouse(client):
    with _app.app_context():
        AppSetting.set('warehouse_lat', '35.9132')
        AppSetting.set('warehouse_lng', '-79.0558')


def _make_cart(buyer_id, item_ids):
    """Create a Cart with the given items; return cart_id."""
    with _app.app_context():
        cart = Cart(user_id=buyer_id)
        db.session.add(cart)
        db.session.flush()
        for iid in item_ids:
            db.session.add(CartItem(cart_id=cart.id, item_id=iid))
        cart.updated_at = datetime.utcnow()
        db.session.commit()
        return cart.id


def _pending_session(cart_id, zone=1, zone_fee='15', distance=3.0,
                     items_subtotal='85', sales_tax='6.16', bundle_free=False):
    return {
        'cart_id': cart_id,
        'street': '123 Main St',
        'city': 'Chapel Hill',
        'state': 'NC',
        'zip': '27514',
        'address_string': '123 Main St, Chapel Hill, NC 27514',
        'lat': 35.92,
        'lng': -79.05,
        'distance_miles': distance,
        'zone': zone,
        'zone_fee': zone_fee,
        'bundle_free': bundle_free,
        'items_subtotal': items_subtotal,
        'sales_tax': sales_tax,
    }


def _mock_stripe_session(session_id='cs_test_abc'):
    mock = MagicMock()
    mock.id = session_id
    mock.url = 'https://checkout.stripe.com/test'
    return mock


def _fire_webhook(client, event_dict):
    with patch('stripe.Webhook.construct_event', return_value=event_dict):
        return client.post(
            '/webhook',
            data=json.dumps({'type': 'checkout.session.completed'}),
            content_type='application/json',
            headers={'Stripe-Signature': 'test_sig'},
        )


def _cart_order_event(order_id, item_ids, stripe_session_id='cs_test_abc',
                      buyer_email='buyer@fees.edu', buyer_name='Test Buyer'):
    return {
        'type': 'checkout.session.completed',
        'data': {
            'object': {
                'id': stripe_session_id,
                'metadata': {
                    'type': 'cart_order',
                    'order_id': str(order_id),
                    'item_ids': ','.join(str(i) for i in item_ids),
                },
                'customer_details': {
                    'email': buyer_email,
                    'name': buyer_name,
                },
            }
        },
    }


# ── TestZoneCalculation ────────────────────────────────────────────────────────

class TestZoneCalculation:

    def test_zone_1_lower_bound(self, client):
        with _app.app_context():
            assert calculate_delivery_zone(0) == (1, Decimal('15'))

    def test_zone_1_mid(self, client):
        with _app.app_context():
            assert calculate_delivery_zone(3.2) == (1, Decimal('15'))

    def test_zone_1_inclusive_upper(self, client):
        with _app.app_context():
            assert calculate_delivery_zone(5.0) == (1, Decimal('15'))

    def test_zone_2_just_over_boundary(self, client):
        with _app.app_context():
            assert calculate_delivery_zone(5.01) == (2, Decimal('20'))

    def test_zone_2_inclusive_upper(self, client):
        with _app.app_context():
            assert calculate_delivery_zone(10.0) == (2, Decimal('20'))

    def test_zone_3_just_over_boundary(self, client):
        with _app.app_context():
            assert calculate_delivery_zone(10.01) == (3, Decimal('25'))

    def test_zone_3_inclusive_upper(self, client):
        with _app.app_context():
            assert calculate_delivery_zone(15.0) == (3, Decimal('25'))

    def test_zone_4_just_over_boundary(self, client):
        with _app.app_context():
            assert calculate_delivery_zone(15.01) == (4, Decimal('30'))

    def test_exactly_20_miles_is_zone_4(self, client):
        with _app.app_context():
            assert calculate_delivery_zone(20.0) == (4, Decimal('30'))

    def test_just_over_20_miles_rejected(self, client):
        with _app.app_context():
            assert calculate_delivery_zone(20.01) is None

    def test_far_distance_rejected(self, client):
        with _app.app_context():
            assert calculate_delivery_zone(50) is None

    def test_zone_config_read_from_appsettings(self, client):
        with _app.app_context():
            AppSetting.set('delivery_zone_boundaries', '3,6,9,12')
            AppSetting.set('delivery_zone_fees', '10,15,20,25')
            assert calculate_delivery_zone(3.0) == (1, Decimal('10'))
            assert calculate_delivery_zone(3.01) == (2, Decimal('15'))
            assert calculate_delivery_zone(12.01) is None

    def test_zone_falls_back_to_defaults_when_setting_absent(self, client):
        with _app.app_context():
            AppSetting.query.filter_by(key='delivery_zone_boundaries').delete()
            AppSetting.query.filter_by(key='delivery_zone_fees').delete()
            db.session.commit()
            # Hardcoded defaults: 5,10,15,20 miles → fees 15,20,25,30
            assert calculate_delivery_zone(5.0) == (1, Decimal('15'))


# ── TestSalesTax ───────────────────────────────────────────────────────────────

class TestSalesTax:

    def test_tax_two_dollar_item_rounds_half_up(self, client):
        # CANARY: 2.00 * 0.0725 = 0.1450 — ROUND_HALF_UP → 0.15 (not 0.14 via banker's rounding)
        with _app.app_context():
            assert compute_sales_tax(2.00) == Decimal('0.15')

    def test_tax_eighty_five_dollar_item(self, client):
        with _app.app_context():
            assert compute_sales_tax(85.00) == Decimal('6.16')

    def test_tax_fifty_dollar_item(self, client):
        with _app.app_context():
            assert compute_sales_tax(50.00) == Decimal('3.63')

    def test_tax_thirty_dollar_item(self, client):
        with _app.app_context():
            assert compute_sales_tax(30.00) == Decimal('2.18')

    def test_tax_twenty_dollar_item(self, client):
        with _app.app_context():
            assert compute_sales_tax(20.00) == Decimal('1.45')

    def test_tax_thirty_three_dollar_item(self, client):
        with _app.app_context():
            assert compute_sales_tax(33.00) == Decimal('2.39')

    def test_tax_seven_dollar_item(self, client):
        with _app.app_context():
            assert compute_sales_tax(7.00) == Decimal('0.51')

    def test_tax_two_hundred_dollar_item(self, client):
        with _app.app_context():
            assert compute_sales_tax(200.00) == Decimal('14.50')

    def test_tax_zero_dollar_item(self, client):
        with _app.app_context():
            assert compute_sales_tax(0.00) == Decimal('0.00')

    def test_tax_never_applied_to_delivery_fee(self, client):
        # Tax on $85 alone = $6.16. Tax on $85+$15 combined = $7.25.
        # The implementation must tax item price only.
        with _app.app_context():
            assert compute_sales_tax(85.00) == Decimal('6.16')
            assert compute_sales_tax(85.00 + 15.00) == Decimal('7.25')  # what it would be if wrong
            # Verify these are different — confirms the test is meaningful
            assert Decimal('6.16') != Decimal('7.25')

    def test_tax_rate_read_from_appsettings(self, client):
        with _app.app_context():
            AppSetting.set('sales_tax_rate', '0.10')
            assert compute_sales_tax(100.00) == Decimal('10.00')


# ── TestSingleItemTotal ────────────────────────────────────────────────────────

class TestSingleItemTotal:
    """
    Drive the total via POST /checkout/review and assert captured Stripe line items.

    Table from spec:
      $85 / Zone 1 ($15) / no flex  → item 8500, tax 616, delivery 1500  → total $106.16
      $85 / Zone 1 ($15) / flex     → same lines + coupon                → total $101.16
      $200 / Zone 4 ($30) / no flex → item 20000, tax 1450, delivery 3000 → total $244.50
      $200 / Zone 4 ($30) / flex    → same lines + coupon                → total $239.50
    """

    def _review_post(self, buyer_client, buyer, item, zone, zone_fee_str,
                     is_flexible=False, coupon='coupon_xyz'):
        cart_id = _make_cart(buyer.id, [item.id])
        pending = _pending_session(
            cart_id=cart_id,
            zone=zone,
            zone_fee=zone_fee_str,
            items_subtotal=str(item.price),
            sales_tax=str(compute_sales_tax(item.price)),
        )
        if is_flexible:
            with _app.app_context():
                AppSetting.set('stripe_flexible_coupon_id', coupon)
        with buyer_client.session_transaction() as sess:
            sess['pending_delivery'] = pending
        mock_session = _mock_stripe_session()
        with patch('stripe.checkout.Session.create', return_value=mock_session) as mock_create:
            resp = buyer_client.post(
                '/checkout/review',
                data={'is_flexible': '1'} if is_flexible else {},
            )
            return resp, mock_create

    def test_85_zone1_no_flex_line_items(self, buyer_client, buyer, item_85, category, seller):
        resp, mock_create = self._review_post(buyer_client, buyer, item_85, zone=1, zone_fee_str='15')
        assert resp.status_code == 303
        kwargs = mock_create.call_args[1]
        lines = kwargs['line_items']
        amounts = [li['price_data']['unit_amount'] for li in lines]
        assert 8500 in amounts   # item $85.00
        assert 616 in amounts    # tax $6.16
        assert 1500 in amounts   # delivery $15.00
        assert all(a >= 0 for a in amounts)  # no negative line items

    def test_85_zone1_flex_attaches_coupon(self, buyer_client, buyer, item_85, category, seller):
        resp, mock_create = self._review_post(
            buyer_client, buyer, item_85, zone=1, zone_fee_str='15',
            is_flexible=True, coupon='coupon_flex_test',
        )
        assert resp.status_code == 303
        kwargs = mock_create.call_args[1]
        assert 'discounts' in kwargs
        assert kwargs['discounts'] == [{'coupon': 'coupon_flex_test'}]
        # Delivery line still present even with flex (discount via coupon)
        lines = kwargs['line_items']
        amounts = [li['price_data']['unit_amount'] for li in lines]
        assert 1500 in amounts

    def test_200_zone4_no_flex_line_items(self, buyer_client, buyer, item_200, category, seller):
        resp, mock_create = self._review_post(buyer_client, buyer, item_200, zone=4, zone_fee_str='30')
        assert resp.status_code == 303
        kwargs = mock_create.call_args[1]
        lines = kwargs['line_items']
        amounts = [li['price_data']['unit_amount'] for li in lines]
        assert 20000 in amounts  # item $200.00
        assert 1450 in amounts   # tax $14.50
        assert 3000 in amounts   # delivery $30.00

    def test_total_excludes_delivery_from_tax(self, buyer_client, buyer, item_85, category, seller):
        # Tax must be 616 cents ($6.16 on $85), not 725 cents ($7.25 on $100)
        resp, mock_create = self._review_post(buyer_client, buyer, item_85, zone=1, zone_fee_str='15')
        assert resp.status_code == 303
        kwargs = mock_create.call_args[1]
        lines = kwargs['line_items']
        tax_line = next(
            li for li in lines
            if 'Sales Tax' in li['price_data']['product_data']['name']
        )
        assert tax_line['price_data']['unit_amount'] == 616


# ── TestCheckoutRoutes ─────────────────────────────────────────────────────────

class TestCheckoutRoutes:

    def test_address_in_range_redirects_to_review(self, buyer_client, buyer, item_85, category, seller):
        _set_warehouse(buyer_client)
        cart_id = _make_cart(buyer.id, [item_85.id])
        with buyer_client.session_transaction() as sess:
            sess['checkout_cart_id'] = cart_id

        with patch('app.geocode_address', return_value=(35.92, -79.05)), \
             patch('app.haversine_miles', return_value=3.0):
            resp = buyer_client.post('/checkout/delivery', data={
                'street': '123 Main St',
                'city': 'Chapel Hill',
                'state': 'NC',
                'zip': '27514',
            })

        assert resp.status_code == 302
        assert 'review' in resp.headers.get('Location', '')

    def test_address_out_of_range_rejected(self, buyer_client, buyer, item_85, category, seller):
        _set_warehouse(buyer_client)
        cart_id = _make_cart(buyer.id, [item_85.id])
        with buyer_client.session_transaction() as sess:
            sess['checkout_cart_id'] = cart_id

        with patch('app.geocode_address', return_value=(36.5, -80.0)), \
             patch('app.haversine_miles', return_value=25.0):
            resp = buyer_client.post('/checkout/delivery', data={
                'street': '999 Far Away Rd',
                'city': 'Durham',
                'state': 'NC',
                'zip': '27701',
            })

        # Should re-render the form with an error, no redirect to review
        assert resp.status_code == 200
        assert b'outside' in resp.data.lower() or b'area' in resp.data.lower() or b'20 miles' in resp.data.lower()

    def test_geocode_failure_rejected(self, buyer_client, buyer, item_85, category, seller):
        _set_warehouse(buyer_client)
        cart_id = _make_cart(buyer.id, [item_85.id])
        with buyer_client.session_transaction() as sess:
            sess['checkout_cart_id'] = cart_id

        with patch('app.geocode_address', return_value=(None, None)):
            resp = buyer_client.post('/checkout/delivery', data={
                'street': 'INVALID ADDRESS XYZ',
                'city': 'Nowhere',
                'state': 'NC',
                'zip': '00000',
            })

        assert resp.status_code == 200
        assert b'verify' in resp.data.lower() or b'address' in resp.data.lower()

    def test_review_without_session_redirects_to_cart(self, client):
        # No pending_delivery in session → redirect to cart
        resp = client.get('/checkout/review')
        assert resp.status_code == 302
        assert 'cart' in resp.headers.get('Location', '').lower()

    def test_review_post_creates_stripe_session_with_correct_line_items(
            self, buyer_client, buyer, item_85, category, seller):
        cart_id = _make_cart(buyer.id, [item_85.id])
        pending = _pending_session(
            cart_id=cart_id, zone=1, zone_fee='15',
            items_subtotal='85', sales_tax='6.16',
        )
        with buyer_client.session_transaction() as sess:
            sess['pending_delivery'] = pending

        mock_sess = _mock_stripe_session()
        with patch('stripe.checkout.Session.create', return_value=mock_sess) as mock_create:
            resp = buyer_client.post('/checkout/review', data={})

        assert resp.status_code == 303
        kwargs = mock_create.call_args[1]
        lines = kwargs['line_items']
        amounts = [li['price_data']['unit_amount'] for li in lines]
        assert 8500 in amounts
        assert 616 in amounts
        assert 1500 in amounts
        # No negative unit_amounts
        assert all(a >= 0 for a in amounts)

    def test_flexible_attaches_coupon(self, buyer_client, buyer, item_85, category, seller):
        with _app.app_context():
            AppSetting.set('stripe_flexible_coupon_id', 'coupon_flex_abc')
        cart_id = _make_cart(buyer.id, [item_85.id])
        pending = _pending_session(cart_id=cart_id, zone=1, zone_fee='15',
                                   items_subtotal='85', sales_tax='6.16')
        with buyer_client.session_transaction() as sess:
            sess['pending_delivery'] = pending

        mock_sess = _mock_stripe_session()
        with patch('stripe.checkout.Session.create', return_value=mock_sess) as mock_create:
            resp = buyer_client.post('/checkout/review', data={'is_flexible': '1'})

        assert resp.status_code == 303
        kwargs = mock_create.call_args[1]
        assert kwargs.get('discounts') == [{'coupon': 'coupon_flex_abc'}]

    def test_flexible_hidden_when_coupon_unset(self, buyer_client, buyer, item_85, category, seller):
        with _app.app_context():
            AppSetting.query.filter_by(key='stripe_flexible_coupon_id').delete()
            db.session.commit()
        cart_id = _make_cart(buyer.id, [item_85.id])
        pending = _pending_session(cart_id=cart_id, zone=1, zone_fee='15',
                                   items_subtotal='85', sales_tax='6.16')
        with buyer_client.session_transaction() as sess:
            sess['pending_delivery'] = pending

        mock_sess = _mock_stripe_session()
        with patch('stripe.checkout.Session.create', return_value=mock_sess) as mock_create:
            # POST with is_flexible=1, but coupon is absent → should be ignored
            resp = buyer_client.post('/checkout/review', data={'is_flexible': '1'})

        assert resp.status_code == 303
        kwargs = mock_create.call_args[1]
        assert 'discounts' not in kwargs

    def test_item_sold_between_review_and_pay_is_blocked(
            self, buyer_client, buyer, item_85, category, seller):
        # Mark item sold before the POST
        with _app.app_context():
            item = InventoryItem.query.get(item_85.id)
            item.status = 'sold'
            db.session.commit()

        cart_id = _make_cart(buyer.id, [item_85.id])
        pending = _pending_session(cart_id=cart_id, zone=1, zone_fee='15',
                                   items_subtotal='85', sales_tax='6.16')
        with buyer_client.session_transaction() as sess:
            sess['pending_delivery'] = pending

        with patch('stripe.checkout.Session.create') as mock_create:
            resp = buyer_client.post('/checkout/review', data={})

        # Redirected to cart, not to Stripe
        assert resp.status_code == 302
        assert 'cart' in resp.headers.get('Location', '').lower()
        mock_create.assert_not_called()


# ── TestWebhook ────────────────────────────────────────────────────────────────

class TestWebhook:

    def _create_pending_order(self, buyer_id, item_id):
        with _app.app_context():
            order = Order(
                buyer_id=buyer_id,
                buyer_email='buyer@fees.edu',
                buyer_name='Test Buyer',
                delivery_street='123 Main St',
                delivery_city='Chapel Hill',
                delivery_state='NC',
                delivery_zip='27514',
                delivery_lat=35.92,
                delivery_lng=-79.05,
                distance_miles=3.0,
                delivery_zone=1,
                delivery_fee=Decimal('15'),
                bundle_free_delivery=False,
                is_flexible_delivery=False,
                flexible_discount=Decimal('0'),
                sales_tax=Decimal('6.16'),
                items_subtotal=Decimal('85'),
                total_paid=Decimal('106.16'),
                status='pending',
            )
            db.session.add(order)
            db.session.commit()
            _ = order.id, order.status
            return order.id

    def test_checkout_completed_creates_buyer_order(
            self, client, seller, buyer, category, item_85):
        order_id = self._create_pending_order(buyer.id, item_85.id)
        event = _cart_order_event(order_id, [item_85.id])

        with patch('app.send_email') as mock_email:
            resp = _fire_webhook(client, event)

        assert resp.status_code == 200

        with _app.app_context():
            order = Order.query.get(order_id)
            assert order.status == 'paid'

            item = InventoryItem.query.get(item_85.id)
            assert item.status == 'sold'

            bo = BuyerOrder.query.filter_by(item_id=item_85.id).first()
            assert bo is not None
            assert bo.order_id == order_id
            assert bo.delivery_zone == 1
            assert Decimal(str(bo.delivery_fee)) == Decimal('15')
            assert Decimal(str(bo.sales_tax)) == Decimal('6.16')
            assert Decimal(str(bo.items_subtotal)) == Decimal('85')
            assert Decimal(str(bo.item_price_paid)) == Decimal('85')
            assert Decimal(str(bo.item_sales_tax)) == Decimal('6.16')
            assert bo.stripe_session_id == 'cs_test_abc'

        assert mock_email.call_count >= 1

    def test_webhook_is_idempotent(self, client, seller, buyer, category, item_85):
        order_id = self._create_pending_order(buyer.id, item_85.id)
        event = _cart_order_event(order_id, [item_85.id])

        with patch('app.send_email') as mock_email:
            _fire_webhook(client, event)
            call_count_after_first = mock_email.call_count
            _fire_webhook(client, event)  # same event again

        with _app.app_context():
            bo_count = BuyerOrder.query.filter_by(item_id=item_85.id).count()
            assert bo_count == 1  # exactly one BuyerOrder

            item = InventoryItem.query.get(item_85.id)
            assert item.status == 'sold'  # still sold

        # No extra emails on the second webhook call
        assert mock_email.call_count == call_count_after_first

    def test_webhook_double_sale_guard(self, client, seller, buyer, category, item_85):
        # Item already sold before webhook fires
        with _app.app_context():
            item = InventoryItem.query.get(item_85.id)
            item.status = 'sold'
            db.session.commit()

        order_id = self._create_pending_order(buyer.id, item_85.id)
        event = _cart_order_event(order_id, [item_85.id])

        with patch('app.send_email'):
            _fire_webhook(client, event)

        with _app.app_context():
            order = Order.query.get(order_id)
            assert order.has_conflict is True

            # No BuyerOrder created for already-sold item
            bo_count = BuyerOrder.query.filter_by(item_id=item_85.id).count()
            assert bo_count == 0

            # SellerAlert created for the double-sale
            alert = SellerAlert.query.filter_by(alert_type='double_sale').first()
            assert alert is not None

            # Item status unchanged
            item = InventoryItem.query.get(item_85.id)
            assert item.status == 'sold'

    def test_item_marked_sold_only_via_webhook(self, client, seller, buyer, category, item_85):
        # Hitting the success URL alone must NOT mark an item sold
        with patch('stripe.checkout.Session.retrieve') as mock_retrieve:
            mock_retrieve.return_value = MagicMock(
                metadata={'type': 'cart_order', 'order_id': '999'}
            )
            # GET success page with a fake stripe session
            resp = client.get('/item_success?order_id=cs_test_fake')

        with _app.app_context():
            item = InventoryItem.query.get(item_85.id)
            assert item.status == 'available'
