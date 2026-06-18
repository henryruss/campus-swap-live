"""
Tests for Spec B — cart operations, item holds, bundle pricing, multi-line Stripe
sessions, multi-item webhook, and Order backfill migration.

Canary: $50 + $30 per-item tax = 3.63 + 2.18 = $5.81 (NOT $5.80 from taxing $80 subtotal).

Run: pytest tests/test_cart_bundle.py -v
"""

import pytest
import json
from decimal import Decimal
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from app import app as _app, db, compute_sales_tax, backfill_orders_from_buyer_orders
from models import (
    User, InventoryCategory, InventoryItem, AppSetting,
    BuyerOrder, Order, Cart, CartItem, SellerAlert,
)
from werkzeug.security import generate_password_hash


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def category(client):
    with _app.app_context():
        cat = InventoryCategory(name='Furniture', image_url='fa-couch', count_in_stock=20)
        db.session.add(cat)
        db.session.commit()
        _ = cat.id, cat.name
        return cat


@pytest.fixture
def seller(client):
    with _app.app_context():
        u = User(
            email='seller@bundle.edu',
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
            email='buyer@bundle.edu',
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
def buyer2(client):
    with _app.app_context():
        u = User(
            email='buyer2@bundle.edu',
            password_hash=generate_password_hash('pass123'),
            full_name='Buyer Two',
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
def item_50(client, seller, category):
    with _app.app_context():
        item = InventoryItem(
            description='Bookshelf',
            price=50.00,
            status='available',
            category_id=category.id,
            seller_id=seller.id,
            collection_method='online',
            photo_url='shelf.jpg',
        )
        db.session.add(item)
        db.session.commit()
        _ = item.id, item.price, item.status, item.category_id, item.seller_id
        return item


@pytest.fixture
def item_30(client, seller, category):
    with _app.app_context():
        item = InventoryItem(
            description='Desk Chair',
            price=30.00,
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
def item_20(client, seller, category):
    with _app.app_context():
        item = InventoryItem(
            description='Lamp',
            price=20.00,
            status='available',
            category_id=category.id,
            seller_id=seller.id,
            collection_method='online',
            photo_url='lamp.jpg',
        )
        db.session.add(item)
        db.session.commit()
        _ = item.id, item.price, item.status, item.category_id, item.seller_id
        return item


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_cart(user_id, item_ids, updated_at=None):
    with _app.app_context():
        cart = Cart(user_id=user_id)
        cart.updated_at = updated_at or datetime.utcnow()
        db.session.add(cart)
        db.session.flush()
        for iid in item_ids:
            db.session.add(CartItem(cart_id=cart.id, item_id=iid))
        db.session.commit()
        return cart.id


def _make_pending_delivery(cart_id, zone=2, zone_fee='20', distance=7.0,
                            items_subtotal='50', sales_tax='3.63', bundle_free=False):
    return {
        'cart_id': cart_id,
        'street': '456 Campus Dr',
        'city': 'Chapel Hill',
        'state': 'NC',
        'zip': '27514',
        'address_string': '456 Campus Dr, Chapel Hill, NC 27514',
        'lat': 35.91,
        'lng': -79.05,
        'distance_miles': distance,
        'zone': zone,
        'zone_fee': zone_fee,
        'bundle_free': bundle_free,
        'items_subtotal': items_subtotal,
        'sales_tax': sales_tax,
    }


def _mock_stripe_session(session_id='cs_bundle_test'):
    mock = MagicMock()
    mock.id = session_id
    mock.url = 'https://checkout.stripe.com/bundle'
    return mock


def _fire_webhook(client, event_dict):
    with patch('stripe.Webhook.construct_event', return_value=event_dict):
        return client.post(
            '/webhook',
            data=json.dumps({'type': 'checkout.session.completed'}),
            content_type='application/json',
            headers={'Stripe-Signature': 'test_sig'},
        )


def _cart_order_event(order_id, item_ids, stripe_session_id='cs_bundle_test',
                      buyer_email='buyer@bundle.edu', buyer_name='Bundle Buyer'):
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


def _make_pending_order(buyer_id, item_ids, delivery_fee=20, bundle_free=False,
                        is_flexible=False, flexible_discount=0,
                        stripe_session_id='cs_bundle_test'):
    with _app.app_context():
        subtotal = sum(
            Decimal(str(InventoryItem.query.get(iid).price))
            for iid in item_ids
        )
        tax = sum(
            compute_sales_tax(InventoryItem.query.get(iid).price)
            for iid in item_ids
        )
        fee = Decimal('0') if bundle_free else Decimal(str(delivery_fee))
        disc = Decimal(str(flexible_discount)) if is_flexible else Decimal('0')
        total = subtotal + tax + fee - disc
        order = Order(
            buyer_id=buyer_id,
            buyer_email='buyer@bundle.edu',
            buyer_name='Bundle Buyer',
            delivery_street='456 Campus Dr',
            delivery_city='Chapel Hill',
            delivery_state='NC',
            delivery_zip='27514',
            delivery_lat=35.91,
            delivery_lng=-79.05,
            distance_miles=7.0,
            delivery_zone=None if bundle_free else 2,
            delivery_fee=fee,
            bundle_free_delivery=bundle_free,
            is_flexible_delivery=is_flexible,
            flexible_discount=disc,
            sales_tax=tax,
            items_subtotal=subtotal,
            total_paid=total,
            stripe_checkout_session_id=stripe_session_id,
            status='pending',
        )
        db.session.add(order)
        db.session.commit()
        _ = order.id, order.status
        return order.id


def _make_legacy_buyer_order(item_id, buyer_email='legacy@test.com',
                              delivery_fee=None, sales_tax=None,
                              is_flexible=False, flexible_discount=None,
                              stripe_session_id=None):
    with _app.app_context():
        item = InventoryItem.query.get(item_id)
        item.status = 'sold'
        price = Decimal(str(item.price))
        fee = Decimal(str(delivery_fee)) if delivery_fee is not None else Decimal('0')
        tax = Decimal(str(sales_tax)) if sales_tax is not None else Decimal('0')
        disc = Decimal(str(flexible_discount)) if flexible_discount is not None else Decimal('0')
        subtotal = price
        total = subtotal + tax + fee - disc
        bo = BuyerOrder(
            item_id=item_id,
            buyer_email=buyer_email,
            delivery_address='789 Old St, Chapel Hill, NC 27514',
            delivery_lat=35.91,
            delivery_lng=-79.05,
            delivery_zone=1 if fee > 0 else None,
            delivery_fee=fee,
            is_flexible_delivery=is_flexible,
            flexible_discount=disc,
            sales_tax=tax,
            distance_miles=3.0,
            items_subtotal=subtotal,
            total_paid=total,
            stripe_checkout_session_id=stripe_session_id,
            # order_id left NULL — this is a legacy record
        )
        db.session.add(bo)
        db.session.commit()
        _ = bo.id
        return bo.id


# ── TestCartOperations ─────────────────────────────────────────────────────────

class TestCartOperations:

    def test_add_item_creates_cart_and_holds_item(self, buyer_client, buyer, item_50, category, seller):
        resp = buyer_client.post(f'/cart/add/{item_50.id}')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['count'] == 1

        with _app.app_context():
            cart = Cart.query.filter_by(user_id=buyer.id).first()
            assert cart is not None
            ci = CartItem.query.filter_by(cart_id=cart.id, item_id=item_50.id).first()
            assert ci is not None
            assert cart.updated_at is not None

    def test_add_same_item_twice_is_noop(self, buyer_client, buyer, item_50, category, seller):
        buyer_client.post(f'/cart/add/{item_50.id}')
        resp = buyer_client.post(f'/cart/add/{item_50.id}')  # second add
        assert resp.status_code == 200
        data = resp.get_json()
        assert data.get('already_in_cart') is True

        with _app.app_context():
            cart = Cart.query.filter_by(user_id=buyer.id).first()
            count = CartItem.query.filter_by(cart_id=cart.id, item_id=item_50.id).count()
            assert count == 1

    def test_remove_item_releases_hold(self, buyer_client, buyer, item_50, category, seller):
        buyer_client.post(f'/cart/add/{item_50.id}')
        resp = buyer_client.post(f'/cart/remove/{item_50.id}')
        assert resp.status_code == 302  # redirect after remove

        with _app.app_context():
            cart = Cart.query.filter_by(user_id=buyer.id).first()
            if cart:
                count = CartItem.query.filter_by(cart_id=cart.id, item_id=item_50.id).count()
                assert count == 0

    def test_cart_badge_count_reflects_items(self, buyer_client, buyer, item_50, item_30, category, seller):
        resp1 = buyer_client.post(f'/cart/add/{item_50.id}')
        assert resp1.get_json()['count'] == 1
        resp2 = buyer_client.post(f'/cart/add/{item_30.id}')
        assert resp2.get_json()['count'] == 2

    def test_guest_cart_persists_then_merges_on_login(
            self, client, buyer, item_50, category, seller):
        # Add item as guest (no login)
        resp = client.post(f'/cart/add/{item_50.id}')
        assert resp.status_code == 200
        assert resp.get_json()['count'] == 1

        # Log in — _merge_guest_cart_into_user should fire
        with patch('app.send_email'):  # suppress any login-triggered emails
            client.post('/login', data={
                'email': buyer.email,
                'password': 'pass123',
                'form_type': 'login',
            })

        with _app.app_context():
            cart = Cart.query.filter_by(user_id=buyer.id).first()
            assert cart is not None
            ci = CartItem.query.filter_by(item_id=item_50.id).first()
            assert ci is not None
            assert ci.cart_id == cart.id


# ── TestItemHolds ──────────────────────────────────────────────────────────────

class TestItemHolds:

    def test_held_item_cannot_be_added_by_another_cart(
            self, client, buyer, buyer2, item_50, category, seller):
        # Buyer holds item in cart A
        with _app.app_context():
            cart_a = Cart(user_id=buyer.id)
            cart_a.updated_at = datetime.utcnow()
            db.session.add(cart_a)
            db.session.flush()
            db.session.add(CartItem(cart_id=cart_a.id, item_id=item_50.id))
            db.session.commit()

        # Buyer2 tries to add the same item
        with client.session_transaction() as sess:
            sess['_user_id'] = str(buyer2.id)
            sess['_fresh'] = True

        resp = client.post(f'/cart/add/{item_50.id}')
        assert resp.status_code == 409
        data = resp.get_json()
        assert 'error' in data

    def test_hold_expires_after_window(self, client, buyer, buyer2, item_50, category, seller):
        # Buyer holds item but with updated_at far in the past (beyond hold window)
        with _app.app_context():
            old_time = datetime.utcnow() - timedelta(hours=2)
            cart_a = Cart(user_id=buyer.id)
            cart_a.created_at = old_time
            cart_a.updated_at = old_time
            db.session.add(cart_a)
            db.session.flush()
            db.session.add(CartItem(cart_id=cart_a.id, item_id=item_50.id))
            db.session.commit()

        # Buyer2 can now add (hold expired)
        with client.session_transaction() as sess:
            sess['_user_id'] = str(buyer2.id)
            sess['_fresh'] = True

        resp = client.post(f'/cart/add/{item_50.id}')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'count' in data

    def test_sold_item_removed_from_other_carts(
            self, client, buyer, buyer2, item_50, category, seller):
        # Buyer2's cart holds item_50
        cart_a_id = _make_cart(buyer2.id, [item_50.id])

        # Buyer purchases item via webhook
        order_id = _make_pending_order(buyer.id, [item_50.id],
                                        delivery_fee=20, bundle_free=False)
        event = _cart_order_event(order_id, [item_50.id])

        with patch('app.send_email'):
            _fire_webhook(client, event)

        # Buyer2's CartItem should be deleted
        with _app.app_context():
            remaining = CartItem.query.filter_by(
                cart_id=cart_a_id, item_id=item_50.id
            ).count()
            assert remaining == 0


# ── TestBundleAndTotals ────────────────────────────────────────────────────────

class TestBundleAndTotals:
    """
    Verify bundle/total math through POST /checkout/review with mocked Stripe.

    Spec table (Zone 2 = $20 fee, bundle_min=2):
      1 × $50          | Zone 2 / no bundle → $73.63
      1 × $50 / flex   | Zone 2 / no bundle → $68.63
      $50 + $30        | bundle → free delivery → $85.81  ← tax canary
      $50 + $30 / flex | bundle → $80.81
      $50 + $30 + $20  | bundle → $107.26
    """

    def _review_post(self, buyer_client, buyer, item_ids, bundle_free=False,
                     zone=2, zone_fee='20', is_flexible=False):
        cart_id = _make_cart(buyer.id, item_ids)
        pending = _make_pending_delivery(
            cart_id=cart_id,
            zone=zone,
            zone_fee=zone_fee,
            bundle_free=bundle_free,
        )
        if is_flexible:
            with _app.app_context():
                AppSetting.set('stripe_flexible_coupon_id', 'coupon_bundle_test')
        with buyer_client.session_transaction() as sess:
            sess['pending_delivery'] = pending
        mock_sess = _mock_stripe_session()
        with patch('stripe.checkout.Session.create', return_value=mock_sess) as mock_create:
            resp = buyer_client.post(
                '/checkout/review',
                data={'is_flexible': '1'} if is_flexible else {},
            )
        return resp, mock_create

    def test_single_item_pays_zone_delivery(self, buyer_client, buyer, item_50, category, seller):
        resp, mock_create = self._review_post(buyer_client, buyer, [item_50.id])
        assert resp.status_code == 303
        lines = mock_create.call_args[1]['line_items']
        amounts = [li['price_data']['unit_amount'] for li in lines]
        assert 5000 in amounts   # $50.00
        assert 363 in amounts    # $3.63 tax
        assert 2000 in amounts   # $20.00 delivery

    def test_two_items_get_free_delivery(self, buyer_client, buyer, item_50, item_30, category, seller):
        resp, mock_create = self._review_post(buyer_client, buyer,
                                               [item_50.id, item_30.id], bundle_free=True)
        assert resp.status_code == 303
        lines = mock_create.call_args[1]['line_items']
        amounts = [li['price_data']['unit_amount'] for li in lines]
        # No delivery line
        assert 2000 not in amounts
        # Both item lines
        assert 5000 in amounts
        assert 3000 in amounts

    def test_three_items_still_free_delivery(
            self, buyer_client, buyer, item_50, item_30, item_20, category, seller):
        resp, mock_create = self._review_post(
            buyer_client, buyer, [item_50.id, item_30.id, item_20.id], bundle_free=True)
        assert resp.status_code == 303
        lines = mock_create.call_args[1]['line_items']
        # No delivery fee line (bundle overrides to $0)
        delivery_lines = [
            li for li in lines
            if 'Delivery' in li['price_data']['product_data']['name']
        ]
        assert len(delivery_lines) == 0
        # All 3 item lines present
        amounts = [li['price_data']['unit_amount'] for li in lines]
        assert 5000 in amounts
        assert 3000 in amounts
        assert 2000 in amounts  # the $20 item, not a delivery fee

    def test_multi_item_tax_is_per_item_then_summed(
            self, buyer_client, buyer, item_50, item_30, category, seller):
        # CANARY: per-item tax 3.63 + 2.18 = 5.81, NOT 5.80 (from taxing $80 subtotal)
        resp, mock_create = self._review_post(buyer_client, buyer,
                                               [item_50.id, item_30.id], bundle_free=True)
        assert resp.status_code == 303
        lines = mock_create.call_args[1]['line_items']
        tax_line = next(
            li for li in lines
            if 'Sales Tax' in li['price_data']['product_data']['name']
        )
        assert tax_line['price_data']['unit_amount'] == 581   # $5.81
        assert tax_line['price_data']['unit_amount'] != 580   # NOT $5.80

    def test_flexible_discount_comes_off_delivery_for_single_item(
            self, buyer_client, buyer, item_50, category, seller):
        # Single item: delivery $20, flexible $5 off → total $68.63
        resp, mock_create = self._review_post(buyer_client, buyer, [item_50.id],
                                               is_flexible=True)
        assert resp.status_code == 303
        kwargs = mock_create.call_args[1]
        assert 'discounts' in kwargs
        assert kwargs['discounts'][0]['coupon'] == 'coupon_bundle_test'

    def test_flexible_discount_comes_off_total_for_bundle(
            self, buyer_client, buyer, item_50, item_30, category, seller):
        # Bundle: delivery $0, flexible $5 off → total $80.81
        resp, mock_create = self._review_post(buyer_client, buyer,
                                               [item_50.id, item_30.id],
                                               bundle_free=True, is_flexible=True)
        assert resp.status_code == 303
        kwargs = mock_create.call_args[1]
        assert 'discounts' in kwargs
        # No delivery line (bundle is free)
        lines = kwargs['line_items']
        delivery_lines = [
            li for li in lines
            if 'Delivery' in li['price_data']['product_data']['name']
        ]
        assert len(delivery_lines) == 0

    def test_removing_item_from_bundle_restores_delivery_fee(
            self, buyer_client, buyer, item_50, item_30, category, seller):
        # Start with 2-item bundle → add to cart, then remove one → 1 item pays delivery

        # Set up 2-item cart
        buyer_client.post(f'/cart/add/{item_50.id}')
        buyer_client.post(f'/cart/add/{item_30.id}')

        # Remove one item
        buyer_client.post(f'/cart/remove/{item_30.id}')

        # Now cart has 1 item — post to checkout/review
        with _app.app_context():
            cart = Cart.query.filter_by(user_id=buyer.id).first()
            cart_id = cart.id

        pending = _make_pending_delivery(cart_id=cart_id, zone=2, zone_fee='20',
                                          items_subtotal='50', sales_tax='3.63',
                                          bundle_free=False)
        with buyer_client.session_transaction() as sess:
            sess['pending_delivery'] = pending

        mock_sess = _mock_stripe_session()
        with patch('stripe.checkout.Session.create', return_value=mock_sess) as mock_create:
            resp = buyer_client.post('/checkout/review', data={})

        assert resp.status_code == 303
        lines = mock_create.call_args[1]['line_items']
        amounts = [li['price_data']['unit_amount'] for li in lines]
        assert 2000 in amounts  # delivery fee restored


# ── TestMultiLineStripeSession ─────────────────────────────────────────────────

class TestMultiLineStripeSession:

    def _post_review(self, buyer_client, buyer, item_ids, bundle_free=False,
                     zone=2, zone_fee='20', is_flexible=False, coupon='coupon_ms_test'):
        cart_id = _make_cart(buyer.id, item_ids)
        pending = _make_pending_delivery(
            cart_id=cart_id, zone=zone, zone_fee=zone_fee, bundle_free=bundle_free,
        )
        if is_flexible:
            with _app.app_context():
                AppSetting.set('stripe_flexible_coupon_id', coupon)
        with buyer_client.session_transaction() as sess:
            sess['pending_delivery'] = pending
        mock_sess = _mock_stripe_session()
        with patch('stripe.checkout.Session.create', return_value=mock_sess) as mock_create:
            resp = buyer_client.post(
                '/checkout/review',
                data={'is_flexible': '1'} if is_flexible else {},
            )
        return resp, mock_create.call_args[1] if mock_create.called else None

    def test_one_line_item_per_cart_item(self, buyer_client, buyer, item_50, item_30, category, seller):
        resp, kwargs = self._post_review(buyer_client, buyer, [item_50.id, item_30.id],
                                          bundle_free=True)
        assert resp.status_code == 303
        item_lines = [
            li for li in kwargs['line_items']
            if 'Sales Tax' not in li['price_data']['product_data']['name']
            and 'Delivery' not in li['price_data']['product_data']['name']
        ]
        assert len(item_lines) == 2

    def test_tax_line_present(self, buyer_client, buyer, item_50, category, seller):
        resp, kwargs = self._post_review(buyer_client, buyer, [item_50.id])
        assert resp.status_code == 303
        tax_lines = [
            li for li in kwargs['line_items']
            if 'Sales Tax' in li['price_data']['product_data']['name']
        ]
        assert len(tax_lines) == 1

    def test_delivery_line_present_for_single_item(self, buyer_client, buyer, item_50, category, seller):
        resp, kwargs = self._post_review(buyer_client, buyer, [item_50.id])
        assert resp.status_code == 303
        delivery_lines = [
            li for li in kwargs['line_items']
            if 'Delivery' in li['price_data']['product_data']['name']
        ]
        assert len(delivery_lines) == 1
        assert delivery_lines[0]['price_data']['unit_amount'] == 2000

    def test_delivery_line_omitted_for_bundle(self, buyer_client, buyer, item_50, item_30, category, seller):
        resp, kwargs = self._post_review(buyer_client, buyer, [item_50.id, item_30.id],
                                          bundle_free=True)
        assert resp.status_code == 303
        delivery_lines = [
            li for li in kwargs['line_items']
            if 'Delivery' in li['price_data']['product_data']['name']
        ]
        assert len(delivery_lines) == 0

    def test_coupon_attached_when_flexible(self, buyer_client, buyer, item_50, category, seller):
        resp, kwargs = self._post_review(buyer_client, buyer, [item_50.id],
                                          is_flexible=True, coupon='coupon_flex_ms')
        assert resp.status_code == 303
        assert kwargs.get('discounts') == [{'coupon': 'coupon_flex_ms'}]

    def test_no_negative_line_items(self, buyer_client, buyer, item_50, item_30, item_20, category, seller):
        # Test all scenarios produce non-negative line items
        for item_ids, bundle in [
            ([item_50.id], False),
            ([item_50.id, item_30.id], True),
            ([item_50.id, item_30.id, item_20.id], True),
        ]:
            cart_id = _make_cart(buyer.id, item_ids)
            pending = _make_pending_delivery(cart_id=cart_id, bundle_free=bundle)
            with buyer_client.session_transaction() as sess:
                sess['pending_delivery'] = pending
            mock_sess = _mock_stripe_session()
            with patch('stripe.checkout.Session.create', return_value=mock_sess) as mock_create:
                buyer_client.post('/checkout/review', data={})
            if mock_create.called:
                for li in mock_create.call_args[1]['line_items']:
                    assert li['price_data']['unit_amount'] >= 0

    def test_line_items_plus_discount_equal_total_paid(
            self, buyer_client, buyer, item_50, category, seller):
        # No flex: sum of line items equals Order.total_paid
        cart_id = _make_cart(buyer.id, [item_50.id])
        pending = _make_pending_delivery(cart_id=cart_id, zone=2, zone_fee='20')
        with buyer_client.session_transaction() as sess:
            sess['pending_delivery'] = pending
        mock_sess = _mock_stripe_session()
        with patch('stripe.checkout.Session.create', return_value=mock_sess) as mock_create:
            buyer_client.post('/checkout/review', data={})

        lines = mock_create.call_args[1]['line_items']
        line_total_cents = sum(li['price_data']['unit_amount'] for li in lines)

        with _app.app_context():
            order = Order.query.filter_by(buyer_id=buyer.id).order_by(Order.id.desc()).first()
            assert order is not None
            total_paid_cents = int(Decimal(str(order.total_paid)) * 100)
            assert line_total_cents == total_paid_cents

    def test_pending_order_created_before_redirect(
            self, buyer_client, buyer, item_50, category, seller):
        cart_id = _make_cart(buyer.id, [item_50.id])
        pending = _make_pending_delivery(cart_id=cart_id)
        with buyer_client.session_transaction() as sess:
            sess['pending_delivery'] = pending
        mock_sess = _mock_stripe_session()
        with patch('stripe.checkout.Session.create', return_value=mock_sess):
            resp = buyer_client.post('/checkout/review', data={})

        assert resp.status_code == 303
        with _app.app_context():
            # Order created before redirect — may be 'pending' or 'paid' (if webhook fired),
            # but must exist with the correct stripe session ID
            order = Order.query.filter_by(buyer_id=buyer.id).order_by(Order.id.desc()).first()
            assert order is not None
            # Was pending at creation; webhook hasn't fired in this test
            assert order.status == 'pending'


# ── TestMultiItemWebhook ───────────────────────────────────────────────────────

class TestMultiItemWebhook:

    def test_order_marked_paid_and_lines_created(
            self, client, seller, buyer, item_50, item_30, category):
        order_id = _make_pending_order(buyer.id, [item_50.id, item_30.id],
                                        bundle_free=True)
        event = _cart_order_event(order_id, [item_50.id, item_30.id])

        with patch('app.send_email') as mock_email:
            resp = _fire_webhook(client, event)

        assert resp.status_code == 200

        with _app.app_context():
            order = Order.query.get(order_id)
            assert order.status == 'paid'

            # One BuyerOrder per item
            bo_50 = BuyerOrder.query.filter_by(item_id=item_50.id).first()
            bo_30 = BuyerOrder.query.filter_by(item_id=item_30.id).first()
            assert bo_50 is not None
            assert bo_30 is not None
            assert bo_50.order_id == order_id
            assert bo_30.order_id == order_id

            # Correct per-item taxes
            assert Decimal(str(bo_50.item_sales_tax)) == Decimal('3.63')
            assert Decimal(str(bo_30.item_sales_tax)) == Decimal('2.18')

            # Both items sold
            item50 = InventoryItem.query.get(item_50.id)
            item30 = InventoryItem.query.get(item_30.id)
            assert item50.status == 'sold'
            assert item30.status == 'sold'

            # Cart items cleared
            remaining = CartItem.query.filter(
                CartItem.item_id.in_([item_50.id, item_30.id])
            ).count()
            assert remaining == 0

        # At least one email sent (buyer confirmation + seller notification)
        assert mock_email.call_count >= 1

    def test_webhook_idempotent_for_multi_item(
            self, client, seller, buyer, item_50, item_30, category):
        order_id = _make_pending_order(buyer.id, [item_50.id, item_30.id], bundle_free=True)
        event = _cart_order_event(order_id, [item_50.id, item_30.id])

        with patch('app.send_email') as mock_email:
            _fire_webhook(client, event)
            count_after_first = mock_email.call_count
            _fire_webhook(client, event)  # same event again

        with _app.app_context():
            bo_count = BuyerOrder.query.filter(
                BuyerOrder.item_id.in_([item_50.id, item_30.id])
            ).count()
            assert bo_count == 2  # exactly one per item

        # Second webhook is a no-op for emails too
        assert mock_email.call_count == count_after_first

    def test_partial_double_sale_guard(
            self, client, seller, buyer, item_50, item_30, category):
        # item_30 is already sold before webhook fires
        with _app.app_context():
            item30 = InventoryItem.query.get(item_30.id)
            item30.status = 'sold'
            db.session.commit()

        order_id = _make_pending_order(buyer.id, [item_50.id, item_30.id], bundle_free=True)
        event = _cart_order_event(order_id, [item_50.id, item_30.id])

        with patch('app.send_email'):
            _fire_webhook(client, event)

        with _app.app_context():
            order = Order.query.get(order_id)
            assert order.status == 'paid'
            assert order.has_conflict is True

            # item_50 was available → sold and BuyerOrder created
            item50 = InventoryItem.query.get(item_50.id)
            assert item50.status == 'sold'
            bo_50 = BuyerOrder.query.filter_by(item_id=item_50.id).first()
            assert bo_50 is not None

            # item_30 was already sold → no new BuyerOrder, SellerAlert created
            bo_30 = BuyerOrder.query.filter_by(item_id=item_30.id).first()
            assert bo_30 is None
            alert = SellerAlert.query.filter_by(alert_type='double_sale').first()
            assert alert is not None

    def test_empty_cart_never_creates_session(self, buyer_client, buyer, category, seller):
        # Cart checkout with an empty cart → no Stripe session, redirected to cart
        with _app.app_context():
            cart = Cart(user_id=buyer.id)
            cart.updated_at = datetime.utcnow()
            db.session.add(cart)
            db.session.commit()

        with buyer_client.session_transaction() as sess:
            sess['checkout_cart_id'] = None  # no cart_id set

        with patch('stripe.checkout.Session.create') as mock_create:
            resp = buyer_client.post('/cart/checkout')

        # Redirected away — no Stripe call
        assert resp.status_code == 302
        mock_create.assert_not_called()


# ── TestBackfillMigration ──────────────────────────────────────────────────────

class TestBackfillMigration:
    """
    Test the backfill_orders_from_buyer_orders() callable in isolation.

    The migration calls the same logic via raw SQL; this suite tests the ORM
    callable that the migration delegates to (or a parallel ORM implementation).
    """

    def test_one_order_created_per_legacy_buyer_order(
            self, client, seller, category, item_50, item_30, item_20):
        bo_ids = [
            _make_legacy_buyer_order(item_50.id),
            _make_legacy_buyer_order(item_30.id),
            _make_legacy_buyer_order(item_20.id),
        ]

        with _app.app_context():
            found, created, linked = backfill_orders_from_buyer_orders()

        assert found == 3
        assert created == 3

        with _app.app_context():
            for bo_id in bo_ids:
                bo = BuyerOrder.query.get(bo_id)
                assert bo.order_id is not None
                order = Order.query.get(bo.order_id)
                assert order is not None

    def test_counts_match_before_and_after(self, client, seller, category, item_50, item_30):
        _make_legacy_buyer_order(item_50.id)
        _make_legacy_buyer_order(item_30.id)

        with _app.app_context():
            bo_count_before = BuyerOrder.query.count()
            order_count_before = Order.query.count()
            assert bo_count_before == 2
            assert order_count_before == 0

            backfill_orders_from_buyer_orders()

            bo_count_after = BuyerOrder.query.count()
            order_count_after = Order.query.count()
            assert bo_count_after == 2   # unchanged
            assert order_count_after == 2

    def test_legacy_free_delivery_orders_backfill_with_zero_fee_and_tax(
            self, client, seller, category, item_50):
        _make_legacy_buyer_order(item_50.id, delivery_fee=0, sales_tax=0)

        with _app.app_context():
            backfill_orders_from_buyer_orders()
            bo = BuyerOrder.query.filter_by(item_id=item_50.id).first()
            order = Order.query.get(bo.order_id)
            assert Decimal(str(order.delivery_fee)) == Decimal('0')
            assert Decimal(str(order.sales_tax)) == Decimal('0')

    def test_spec_a_orders_promote_fields_to_order(
            self, client, seller, category, item_50):
        _make_legacy_buyer_order(
            item_50.id,
            delivery_fee=20,
            sales_tax=3.63,
            is_flexible=True,
            flexible_discount=5,
        )

        with _app.app_context():
            backfill_orders_from_buyer_orders()
            bo = BuyerOrder.query.filter_by(item_id=item_50.id).first()
            order = Order.query.get(bo.order_id)
            assert Decimal(str(order.delivery_fee)) == Decimal('20')
            assert Decimal(str(order.sales_tax)).quantize(Decimal('0.01')) == Decimal('3.63')
            assert order.is_flexible_delivery is True
            assert Decimal(str(order.flexible_discount)) == Decimal('5')
            assert order.status == 'paid'

    def test_backfill_is_idempotent(self, client, seller, category, item_50, item_30):
        _make_legacy_buyer_order(item_50.id)
        _make_legacy_buyer_order(item_30.id)

        with _app.app_context():
            backfill_orders_from_buyer_orders()
            order_count_after_first = Order.query.count()

            # Second run: all BuyerOrders already have order_id → nothing to process
            found2, created2, _ = backfill_orders_from_buyer_orders()
            order_count_after_second = Order.query.count()

        assert found2 == 0
        assert created2 == 0
        assert order_count_after_second == order_count_after_first
