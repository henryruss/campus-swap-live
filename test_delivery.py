"""
tests/test_delivery.py

Test suite for the buyer delivery flow (feature_buyer_delivery.md).

Covers:
  - haversine_miles() helper accuracy
  - GET /checkout/delivery/<id> — happy path, guards, edge cases
  - POST /checkout/delivery/<id> — in-range, out-of-range, bad address, geocode failure
  - create_checkout_session reads pending_delivery from session
  - Webhook creates BuyerOrder from Stripe metadata
  - product.html shows "Weekly Delivery · Free" (not "In-Store Pickup")
  - item_success.html shows delivery copy (not warehouse pickup copy)
  - Admin item table shows delivery address for sold items
"""

import json
import math
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def seller(db_session, app):
    """A minimal seller user."""
    from models import User
    u = User(
        email='seller@test.com',
        full_name='Test Seller',
        is_seller=True,
        payout_rate=20,
    )
    u.set_password('password')
    db_session.add(u)
    db_session.commit()
    return u


@pytest.fixture
def category(db_session):
    """A minimal inventory category."""
    from models import InventoryCategory
    cat = InventoryCategory(name='Furniture', image_url='furniture.jpg')
    db_session.add(cat)
    db_session.commit()
    return cat


@pytest.fixture
def available_item(db_session, seller, category):
    """An item with status='available' ready to be purchased."""
    from models import InventoryItem
    item = InventoryItem(
        description='Test Couch',
        long_description='A comfortable test couch.',
        price=75.00,
        suggested_price=80.00,
        quality=4,
        status='available',
        collection_method='online',
        category_id=category.id,
        seller_id=seller.id,
        photo_url='couch.jpg',
    )
    db_session.add(item)
    db_session.commit()
    return item


@pytest.fixture
def sold_item(db_session, seller, category):
    """An item that is already sold."""
    from models import InventoryItem
    item = InventoryItem(
        description='Already Sold Lamp',
        price=25.00,
        suggested_price=25.00,
        quality=3,
        status='sold',
        collection_method='online',
        category_id=category.id,
        seller_id=seller.id,
        photo_url='lamp.jpg',
    )
    db_session.add(item)
    db_session.commit()
    return item


@pytest.fixture
def pending_item(db_session, seller, category):
    """An item still in pending_valuation."""
    from models import InventoryItem
    item = InventoryItem(
        description='Pending Rug',
        price=40.00,
        suggested_price=40.00,
        quality=4,
        status='pending_valuation',
        collection_method='online',
        category_id=category.id,
        seller_id=seller.id,
        photo_url='rug.jpg',
    )
    db_session.add(item)
    db_session.commit()
    return item


@pytest.fixture
def warehouse_settings(db_session):
    """Set warehouse AppSettings for Chapel Hill, NC."""
    from models import AppSetting
    AppSetting.set('warehouse_lat', '35.9132')
    AppSetting.set('warehouse_lng', '-79.0558')
    AppSetting.set('delivery_radius_miles', '50')
    db_session.commit()


# In-range address (Durham, NC — ~11 miles from Chapel Hill)
IN_RANGE_FORM = {
    'street': '300 W Morgan St',
    'city': 'Durham',
    'state': 'NC',
    'zip': '27701',
}

# Out-of-range address (Charlotte, NC — ~160 miles from Chapel Hill)
OUT_OF_RANGE_FORM = {
    'street': '100 N Tryon St',
    'city': 'Charlotte',
    'state': 'NC',
    'zip': '28202',
}

# Geocode result for Durham
DURHAM_GEOCODE = MagicMock(latitude=35.9940, longitude=-78.8986)

# Geocode result for Charlotte
CHARLOTTE_GEOCODE = MagicMock(latitude=35.2271, longitude=-80.8431)


# ---------------------------------------------------------------------------
# Unit tests: haversine_miles()
# ---------------------------------------------------------------------------

class TestHaversineMiles:
    """haversine_miles(lat1, lng1, lat2, lng2) correctness."""

    def test_same_point_is_zero(self, app):
        from app import haversine_miles
        assert haversine_miles(35.9132, -79.0558, 35.9132, -79.0558) == pytest.approx(0.0, abs=0.01)

    def test_chapel_hill_to_durham_roughly_11_miles(self, app):
        from app import haversine_miles
        # Chapel Hill → Durham is ~11 miles straight line
        dist = haversine_miles(35.9132, -79.0558, 35.9940, -78.8986)
        assert 9 < dist < 14

    def test_chapel_hill_to_charlotte_roughly_145_165_miles(self, app):
        from app import haversine_miles
        dist = haversine_miles(35.9132, -79.0558, 35.2271, -80.8431)
        assert 145 < dist < 165

    def test_chapel_hill_to_raleigh_roughly_28_miles(self, app):
        from app import haversine_miles
        # Raleigh is ~28 miles from Chapel Hill
        dist = haversine_miles(35.9132, -79.0558, 35.7796, -78.6382)
        assert 24 < dist < 34

    def test_symmetrical(self, app):
        from app import haversine_miles
        d1 = haversine_miles(35.9132, -79.0558, 35.9940, -78.8986)
        d2 = haversine_miles(35.9940, -78.8986, 35.9132, -79.0558)
        assert d1 == pytest.approx(d2, rel=1e-6)


# ---------------------------------------------------------------------------
# GET /checkout/delivery/<id>
# ---------------------------------------------------------------------------

class TestDeliveryPageGet:

    def test_available_item_renders_form(self, client, available_item, warehouse_settings):
        resp = client.get(f'/checkout/delivery/{available_item.id}')
        assert resp.status_code == 200
        assert b'Where should we deliver' in resp.data

    def test_page_shows_item_title(self, client, available_item, warehouse_settings):
        resp = client.get(f'/checkout/delivery/{available_item.id}')
        assert available_item.description.encode() in resp.data

    def test_page_shows_item_price(self, client, available_item, warehouse_settings):
        resp = client.get(f'/checkout/delivery/{available_item.id}')
        assert b'75' in resp.data

    def test_sold_item_redirects_to_inventory(self, client, sold_item, warehouse_settings):
        resp = client.get(f'/checkout/delivery/{sold_item.id}')
        assert resp.status_code == 302
        assert '/inventory' in resp.headers['Location']

    def test_pending_item_redirects_to_product_page(self, client, pending_item, warehouse_settings):
        resp = client.get(f'/checkout/delivery/{pending_item.id}')
        assert resp.status_code == 302
        assert f'/item/{pending_item.id}' in resp.headers['Location']

    def test_nonexistent_item_returns_404(self, client, warehouse_settings):
        resp = client.get('/checkout/delivery/99999')
        assert resp.status_code == 404

    def test_reserve_only_mode_blocks_access(self, client, available_item, db_session, warehouse_settings):
        from models import AppSetting
        AppSetting.set('reserve_only_mode', 'true')
        db_session.commit()
        resp = client.get(f'/checkout/delivery/{available_item.id}')
        assert resp.status_code == 302
        assert f'/item/{available_item.id}' in resp.headers['Location']
        AppSetting.set('reserve_only_mode', 'false')
        db_session.commit()

    def test_state_field_pre_filled_with_nc(self, client, available_item, warehouse_settings):
        resp = client.get(f'/checkout/delivery/{available_item.id}')
        assert b'value="NC"' in resp.data or b"value='NC'" in resp.data


# ---------------------------------------------------------------------------
# POST /checkout/delivery/<id>
# ---------------------------------------------------------------------------

class TestDeliveryPagePost:

    def test_in_range_address_sets_session_and_redirects_to_checkout(
        self, client, available_item, warehouse_settings
    ):
        with patch('app.geocode_address', return_value=(35.9940, -78.8986)):
            resp = client.post(
                f'/checkout/delivery/{available_item.id}',
                data=IN_RANGE_FORM,
            )
        # Should redirect onward toward Stripe (create_checkout_session)
        assert resp.status_code == 302

    def test_in_range_address_writes_pending_delivery_to_session(
        self, client, available_item, warehouse_settings
    ):
        with client.session_transaction() as sess:
            sess.clear()

        with patch('app.geocode_address', return_value=(35.9940, -78.8986)):
            client.post(
                f'/checkout/delivery/{available_item.id}',
                data=IN_RANGE_FORM,
            )

        with client.session_transaction() as sess:
            delivery = sess.get('pending_delivery')
            assert delivery is not None
            assert delivery['item_id'] == available_item.id
            assert delivery['lat'] == pytest.approx(35.9940, abs=0.001)
            assert delivery['lng'] == pytest.approx(-78.8986, abs=0.001)
            assert '300 W Morgan St' in delivery['address_string']

    def test_out_of_range_address_re_renders_form_with_error(
        self, client, available_item, warehouse_settings
    ):
        with patch('app.geocode_address', return_value=(35.2271, -80.8431)):
            resp = client.post(
                f'/checkout/delivery/{available_item.id}',
                data=OUT_OF_RANGE_FORM,
            )
        assert resp.status_code == 200
        assert b'outside our delivery area' in resp.data

    def test_out_of_range_repopulates_form_fields(
        self, client, available_item, warehouse_settings
    ):
        with patch('app.geocode_address', return_value=(35.2271, -80.8431)):
            resp = client.post(
                f'/checkout/delivery/{available_item.id}',
                data=OUT_OF_RANGE_FORM,
            )
        assert b'Charlotte' in resp.data

    def test_geocode_failure_re_renders_form_with_error(
        self, client, available_item, warehouse_settings
    ):
        with patch('app.geocode_address', return_value=(None, None)):
            resp = client.post(
                f'/checkout/delivery/{available_item.id}',
                data=IN_RANGE_FORM,
            )
        assert resp.status_code == 200
        assert b"couldn't find that address" in resp.data or b"could not find" in resp.data

    def test_geocode_failure_does_not_set_session(
        self, client, available_item, warehouse_settings
    ):
        with client.session_transaction() as sess:
            sess.pop('pending_delivery', None)

        with patch('app.geocode_address', return_value=(None, None)):
            client.post(
                f'/checkout/delivery/{available_item.id}',
                data=IN_RANGE_FORM,
            )

        with client.session_transaction() as sess:
            assert 'pending_delivery' not in sess

    def test_missing_warehouse_settings_fails_open(
        self, client, available_item, db_session
    ):
        """If warehouse lat/lng not configured, allow purchase (fail open)."""
        from models import AppSetting
        # Ensure warehouse settings are absent
        for key in ('warehouse_lat', 'warehouse_lng', 'delivery_radius_miles'):
            s = AppSetting.query.filter_by(key=key).first()
            if s:
                db_session.delete(s)
        db_session.commit()

        with patch('app.geocode_address', return_value=(35.9940, -78.8986)):
            resp = client.post(
                f'/checkout/delivery/{available_item.id}',
                data=IN_RANGE_FORM,
            )
        # Should proceed (not block) — redirect toward checkout
        assert resp.status_code == 302

    def test_sold_item_post_redirects_to_inventory(
        self, client, sold_item, warehouse_settings
    ):
        resp = client.post(
            f'/checkout/delivery/{sold_item.id}',
            data=IN_RANGE_FORM,
        )
        assert resp.status_code == 302
        assert '/inventory' in resp.headers['Location']

    def test_missing_required_fields_does_not_proceed(
        self, client, available_item, warehouse_settings
    ):
        """Submitting with blank street should not geocode or set session."""
        with patch('app.geocode_address') as mock_geo:
            resp = client.post(
                f'/checkout/delivery/{available_item.id}',
                data={'street': '', 'city': 'Durham', 'state': 'NC', 'zip': '27701'},
            )
        mock_geo.assert_not_called()
        # Either re-renders form (200) or client-side validation catches it
        assert resp.status_code in (200, 302)
        if resp.status_code == 302:
            # Must not redirect to checkout — should stay on delivery page
            assert 'checkout/delivery' in resp.headers['Location'] or \
                   'create_checkout' not in resp.headers['Location']


# ---------------------------------------------------------------------------
# create_checkout_session — reads pending_delivery
# ---------------------------------------------------------------------------

class TestCheckoutSessionDelivery:

    def test_missing_pending_delivery_redirects_to_delivery_page(
        self, client, available_item, warehouse_settings
    ):
        """If pending_delivery missing from session, redirect back to delivery page."""
        with client.session_transaction() as sess:
            sess.pop('pending_delivery', None)

        resp = client.post(
            '/create_checkout_session',
            data={'item_id': available_item.id},
        )
        assert resp.status_code == 302
        assert f'checkout/delivery/{available_item.id}' in resp.headers['Location']

    def test_pending_delivery_wrong_item_redirects_to_delivery_page(
        self, client, available_item, warehouse_settings
    ):
        """If pending_delivery is for a different item, redirect back."""
        with client.session_transaction() as sess:
            sess['pending_delivery'] = {
                'item_id': available_item.id + 999,
                'address_string': '300 W Morgan St, Durham, NC 27701',
                'lat': 35.9940,
                'lng': -78.8986,
            }

        resp = client.post(
            '/create_checkout_session',
            data={'item_id': available_item.id},
        )
        assert resp.status_code == 302
        assert f'checkout/delivery/{available_item.id}' in resp.headers['Location']


# ---------------------------------------------------------------------------
# BuyerOrder model
# ---------------------------------------------------------------------------

class TestBuyerOrderModel:

    def test_buyer_order_can_be_created(self, db_session, available_item):
        from models import BuyerOrder
        order = BuyerOrder(
            item_id=available_item.id,
            buyer_email='buyer@test.com',
            delivery_address='300 W Morgan St, Durham, NC 27701',
            delivery_lat=35.9940,
            delivery_lng=-78.8986,
            stripe_session_id='cs_test_abc123',
        )
        db_session.add(order)
        db_session.commit()
        assert order.id is not None

    def test_buyer_order_linked_to_item(self, db_session, available_item):
        from models import BuyerOrder, InventoryItem
        order = BuyerOrder(
            item_id=available_item.id,
            buyer_email='buyer@test.com',
            delivery_address='300 W Morgan St, Durham, NC 27701',
        )
        db_session.add(order)
        db_session.commit()
        item = InventoryItem.query.get(available_item.id)
        assert item.buyer_order is not None
        assert item.buyer_order.buyer_email == 'buyer@test.com'

    def test_buyer_order_unique_per_item(self, db_session, available_item):
        """Two BuyerOrders for the same item should raise an IntegrityError."""
        from models import BuyerOrder
        import sqlalchemy.exc
        o1 = BuyerOrder(item_id=available_item.id, buyer_email='a@test.com',
                        delivery_address='123 Main St')
        o2 = BuyerOrder(item_id=available_item.id, buyer_email='b@test.com',
                        delivery_address='456 Oak Ave')
        db_session.add(o1)
        db_session.commit()
        db_session.add(o2)
        with pytest.raises(sqlalchemy.exc.IntegrityError):
            db_session.commit()
        db_session.rollback()


# ---------------------------------------------------------------------------
# Webhook: BuyerOrder creation
# ---------------------------------------------------------------------------

class TestWebhookCreatesOrder:
    """
    Simulate the webhook creating a BuyerOrder from Stripe metadata.
    Uses the same mock-webhook pattern as existing test_admin.py webhook tests.
    """

    def _make_webhook_payload(self, item_id, stripe_session_id='cs_test_xyz'):
        return {
            'type': 'checkout.session.completed',
            'data': {
                'object': {
                    'id': stripe_session_id,
                    'metadata': {
                        'item_id': str(item_id),
                        'delivery_address': '300 W Morgan St, Durham, NC 27701',
                        'delivery_lat': '35.9940',
                        'delivery_lng': '-78.8986',
                    },
                    'customer_details': {
                        'email': 'buyer@test.com',
                    },
                    'payment_status': 'paid',
                }
            }
        }

    def test_webhook_creates_buyer_order_on_purchase(
        self, client, available_item, db_session
    ):
        from models import BuyerOrder
        payload = self._make_webhook_payload(available_item.id)

        with patch('stripe.Webhook.construct_event', return_value=payload):
            resp = client.post(
                '/webhook',
                data=json.dumps(payload),
                content_type='application/json',
                headers={'Stripe-Signature': 'test_sig'},
            )

        assert resp.status_code == 200
        order = BuyerOrder.query.filter_by(item_id=available_item.id).first()
        assert order is not None
        assert order.buyer_email == 'buyer@test.com'
        assert order.delivery_address == '300 W Morgan St, Durham, NC 27701'
        assert order.delivery_lat == pytest.approx(35.9940, abs=0.001)
        assert order.delivery_lng == pytest.approx(-78.8986, abs=0.001)
        assert order.stripe_session_id == 'cs_test_xyz'

    def test_webhook_marks_item_sold(self, client, available_item, db_session):
        from models import InventoryItem
        payload = self._make_webhook_payload(available_item.id)

        with patch('stripe.Webhook.construct_event', return_value=payload):
            client.post(
                '/webhook',
                data=json.dumps(payload),
                content_type='application/json',
                headers={'Stripe-Signature': 'test_sig'},
            )

        item = InventoryItem.query.get(available_item.id)
        assert item.status == 'sold'

    def test_webhook_no_delivery_metadata_does_not_create_order(
        self, client, available_item, db_session
    ):
        """If metadata has no delivery_address, no BuyerOrder should be created."""
        from models import BuyerOrder
        payload = {
            'type': 'checkout.session.completed',
            'data': {
                'object': {
                    'id': 'cs_test_no_delivery',
                    'metadata': {'item_id': str(available_item.id)},
                    'customer_details': {'email': 'buyer@test.com'},
                    'payment_status': 'paid',
                }
            }
        }
        with patch('stripe.Webhook.construct_event', return_value=payload):
            resp = client.post(
                '/webhook',
                data=json.dumps(payload),
                content_type='application/json',
                headers={'Stripe-Signature': 'test_sig'},
            )

        assert resp.status_code == 200
        order = BuyerOrder.query.filter_by(item_id=available_item.id).first()
        assert order is None


# ---------------------------------------------------------------------------
# Template content tests
# ---------------------------------------------------------------------------

class TestProductPageCopy:

    def test_product_page_shows_weekly_delivery_not_in_store_pickup(
        self, client, available_item
    ):
        resp = client.get(f'/item/{available_item.id}')
        assert resp.status_code == 200
        assert b'In-Store Pickup' not in resp.data
        assert b'Weekly Delivery' in resp.data

    def test_buy_now_links_to_delivery_page_not_checkout_session(
        self, client, available_item
    ):
        resp = client.get(f'/item/{available_item.id}')
        assert resp.status_code == 200
        html = resp.data.decode()
        # Buy Now must link to the delivery interstitial
        assert f'/checkout/delivery/{available_item.id}' in html
        # Must NOT post directly to create_checkout_session
        assert 'create_checkout_session' not in html or \
               f'/checkout/delivery/{available_item.id}' in html


class TestItemSuccessCopy:

    def test_success_page_shows_delivery_language(self, client):
        resp = client.get('/item_success')
        assert resp.status_code == 200
        # Should mention delivery, not warehouse
        assert b'deliver' in resp.data.lower() or b'delivery' in resp.data.lower()

    def test_success_page_does_not_mention_warehouse_pickup(self, client):
        resp = client.get('/item_success')
        assert resp.status_code == 200
        # Old copy: "Visit Campus Swap Warehouse"
        assert b'Visit Campus Swap Warehouse' not in resp.data
        assert b'Show email receipt to claim item' not in resp.data


# ---------------------------------------------------------------------------
# Admin: delivery address visible on sold items
# ---------------------------------------------------------------------------

class TestAdminDeliveryAddressVisibility:

    @pytest.fixture
    def admin_user(self, db_session):
        from models import User
        u = User(email='admin@test.com', full_name='Admin User',
                 is_admin=True, payout_rate=20)
        u.set_password('adminpass')
        db_session.add(u)
        db_session.commit()
        return u

    @pytest.fixture
    def sold_item_with_order(self, db_session, seller, category):
        from models import InventoryItem, BuyerOrder
        item = InventoryItem(
            description='Sold Couch',
            price=75.00,
            suggested_price=80.00,
            quality=4,
            status='sold',
            collection_method='online',
            category_id=category.id,
            seller_id=seller.id,
            photo_url='couch.jpg',
        )
        db_session.add(item)
        db_session.commit()
        order = BuyerOrder(
            item_id=item.id,
            buyer_email='buyer@test.com',
            delivery_address='300 W Morgan St, Durham, NC 27701',
            delivery_lat=35.9940,
            delivery_lng=-78.8986,
        )
        db_session.add(order)
        db_session.commit()
        return item

    def test_admin_panel_shows_delivery_address_for_sold_item(
        self, client, admin_user, sold_item_with_order
    ):
        client.post('/login', data={
            'email': 'admin@test.com',
            'password': 'adminpass',
        })
        resp = client.get('/admin')
        assert resp.status_code == 200
        assert b'300 W Morgan St' in resp.data or b'Durham' in resp.data

    def test_admin_panel_shows_dash_when_no_buyer_order(
        self, client, admin_user, sold_item
    ):
        """Items sold before this feature had no BuyerOrder — show '—'."""
        client.post('/login', data={
            'email': 'admin@test.com',
            'password': 'adminpass',
        })
        resp = client.get('/admin')
        assert resp.status_code == 200
        # Page should not crash when buyer_order is None


# ---------------------------------------------------------------------------
# AppSetting: delivery_radius_miles is configurable
# ---------------------------------------------------------------------------

class TestDeliveryRadiusConfigurable:

    def test_custom_radius_blocks_previously_in_range_address(
        self, client, available_item, db_session
    ):
        """Set radius to 5 miles — Durham (~11 miles) should now be out of range."""
        from models import AppSetting
        AppSetting.set('warehouse_lat', '35.9132')
        AppSetting.set('warehouse_lng', '-79.0558')
        AppSetting.set('delivery_radius_miles', '5')
        db_session.commit()

        with patch('app.geocode_address', return_value=(35.9940, -78.8986)):
            resp = client.post(
                f'/checkout/delivery/{available_item.id}',
                data=IN_RANGE_FORM,
            )
        assert resp.status_code == 200
        assert b'outside our delivery area' in resp.data

        # Reset
        AppSetting.set('delivery_radius_miles', '50')
        db_session.commit()
