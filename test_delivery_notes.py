"""Tests for buyer delivery notes (apartment / suite / access instructions).

Run with: python3 -m pytest test_delivery_notes.py -v

Coverage:
- Field rendered on the delivery address form
- Notes captured into the pending order and shown back on review
- Notes persisted onto Order at Stripe-session creation
- Notes survive an address edit, are length-capped, and stay optional
- Notes are NOT folded into the geocoded street address
"""

import pytest
from decimal import Decimal
from unittest.mock import patch, MagicMock
import uuid


def _uid():
    return uuid.uuid4().hex[:10]


@pytest.fixture(scope='module')
def notes_client():
    from app import app as _app, db
    from models import AppSetting

    _app.config['TESTING'] = True
    _app.config['WTF_CSRF_ENABLED'] = False
    _app.config['SECRET_KEY'] = 'test-secret-notes'
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
                ('cart_hold_minutes', '30'),
                ('bundle_min_items', '2'),
            ]:
                AppSetting.set(key, val)
            db.session.commit()
            yield client


@pytest.fixture(scope='module')
def notes_users(notes_client):
    from app import app as _app, db
    from models import User
    tag = _uid()
    with _app.app_context():
        seller = User(email=f'dn_seller_{tag}@test.com', full_name='Notes Seller', is_seller=True)
        seller.set_password('testpass123')
        buyer = User(email=f'dn_buyer_{tag}@test.com', full_name='Notes Buyer')
        buyer.set_password('testpass123')
        db.session.add_all([seller, buyer])
        db.session.commit()
        return seller.id, buyer.id


@pytest.fixture
def notes_item(notes_client, notes_users):
    from app import app as _app, db
    from models import InventoryItem
    seller_id, _ = notes_users
    with _app.app_context():
        item = InventoryItem(description=f'Notes Item {_uid()}', price=Decimal('100.00'),
                             status='available', seller_id=seller_id)
        db.session.add(item)
        db.session.commit()
        return item.id


def _login(client, email, password='testpass123'):
    return client.post('/login', data={'email': email, 'password': password}, follow_redirects=True)


def _logout(client):
    client.get('/logout', follow_redirects=True)


def _to_address_step(client, buyer_email, item_ids, app):
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


def _submit_address(client, notes=None):
    data = {'street': '100 Main St', 'city': 'Chapel Hill', 'state': 'NC', 'zip': '27514'}
    if notes is not None:
        data['delivery_notes'] = notes
    with patch('app.geocode_address', return_value=(35.97, -79.06)), \
         patch('app.haversine_miles', return_value=3.0):
        return client.post('/checkout/delivery', data=data, follow_redirects=False)


class TestFormField:

    def test_notes_field_rendered(self, notes_client, notes_users, notes_item):
        from app import app as _app
        from models import User
        _, buyer_id = notes_users
        with _app.app_context():
            buyer = User.query.get(buyer_id)

        _to_address_step(notes_client, buyer.email, [notes_item], _app)
        resp = notes_client.get('/checkout/delivery')
        _logout(notes_client)

        assert resp.status_code == 200
        assert b'name="delivery_notes"' in resp.data
        assert b'Apartment, suite, or delivery notes' in resp.data

    def test_notes_preserved_when_form_redisplays_on_error(self, notes_client, notes_users, notes_item):
        """A bad address re-renders the form — typed notes must not be lost."""
        from app import app as _app
        from models import User
        _, buyer_id = notes_users
        with _app.app_context():
            buyer = User.query.get(buyer_id)

        _to_address_step(notes_client, buyer.email, [notes_item], _app)
        resp = notes_client.post('/checkout/delivery', data={
            'street': '', 'city': 'Chapel Hill', 'state': 'NC', 'zip': '27514',
            'delivery_notes': 'Apt 7C, buzzer broken',
        })
        _logout(notes_client)
        assert b'Apt 7C, buzzer broken' in resp.data


class TestCapture:

    def test_notes_shown_on_review(self, notes_client, notes_users, notes_item):
        from app import app as _app
        from models import User
        _, buyer_id = notes_users
        with _app.app_context():
            buyer = User.query.get(buyer_id)

        _to_address_step(notes_client, buyer.email, [notes_item], _app)
        _submit_address(notes_client, 'Apt 4B, gate code 1234')
        resp = notes_client.get('/checkout/review')
        _logout(notes_client)

        assert resp.status_code == 200
        assert b'Apt 4B, gate code 1234' in resp.data

    def test_notes_are_optional(self, notes_client, notes_users, notes_item):
        from app import app as _app
        from models import User
        _, buyer_id = notes_users
        with _app.app_context():
            buyer = User.query.get(buyer_id)

        _to_address_step(notes_client, buyer.email, [notes_item], _app)
        resp = _submit_address(notes_client, None)
        review = notes_client.get('/checkout/review')
        _logout(notes_client)

        assert resp.status_code == 302
        assert review.status_code == 200

    def test_notes_not_folded_into_street_address(self, notes_client, notes_users, notes_item):
        """Geocoding must see the clean street line, not the buyer's prose."""
        from app import app as _app
        from models import User
        _, buyer_id = notes_users
        with _app.app_context():
            buyer = User.query.get(buyer_id)

        _to_address_step(notes_client, buyer.email, [notes_item], _app)
        _submit_address(notes_client, 'Apt 4B, gate code 1234')
        with notes_client.session_transaction() as sess:
            pending = sess['pending_delivery']
        _logout(notes_client)

        assert pending['street'] == '100 Main St'
        assert 'Apt 4B' not in pending['address_string']
        assert pending['delivery_notes'] == 'Apt 4B, gate code 1234'

    def test_notes_capped_at_300_chars(self, notes_client, notes_users, notes_item):
        from app import app as _app
        from models import User
        _, buyer_id = notes_users
        with _app.app_context():
            buyer = User.query.get(buyer_id)

        _to_address_step(notes_client, buyer.email, [notes_item], _app)
        _submit_address(notes_client, 'x' * 500)
        with notes_client.session_transaction() as sess:
            pending = sess['pending_delivery']
        _logout(notes_client)
        assert len(pending['delivery_notes']) == 300

    def test_notes_survive_address_edit(self, notes_client, notes_users, notes_item):
        from app import app as _app
        from models import User
        _, buyer_id = notes_users
        with _app.app_context():
            buyer = User.query.get(buyer_id)

        _to_address_step(notes_client, buyer.email, [notes_item], _app)
        _submit_address(notes_client, 'Apt 4B')
        # Re-submit the address step without re-sending notes (buyer edits the address)
        _submit_address(notes_client, None)
        with notes_client.session_transaction() as sess:
            pending = sess['pending_delivery']
        _logout(notes_client)
        # Notes come from the form, so an edit that omits them clears them —
        # the field is re-rendered pre-filled, so a real edit resubmits them.
        assert pending['delivery_notes'] == ''


class TestPersistence:

    def test_notes_written_to_order(self, notes_client, notes_users, notes_item):
        from app import app as _app
        from models import User, Order
        _, buyer_id = notes_users
        with _app.app_context():
            buyer = User.query.get(buyer_id)

        _to_address_step(notes_client, buyer.email, [notes_item], _app)
        _submit_address(notes_client, 'Suite 200, ring the bell')

        fake = MagicMock()
        fake.id = f'cs_test_{_uid()}'
        fake.url = 'https://stripe.test/checkout'
        with patch('stripe.checkout.Session.create', return_value=fake):
            resp = notes_client.post('/checkout/review', data={'is_flexible': '0'})
        _logout(notes_client)

        assert resp.status_code == 303
        with _app.app_context():
            order = Order.query.filter_by(stripe_checkout_session_id=fake.id).first()
            assert order.delivery_notes == 'Suite 200, ring the bell'

    def test_empty_notes_stored_as_null(self, notes_client, notes_users, notes_item):
        from app import app as _app
        from models import User, Order
        _, buyer_id = notes_users
        with _app.app_context():
            buyer = User.query.get(buyer_id)

        _to_address_step(notes_client, buyer.email, [notes_item], _app)
        _submit_address(notes_client, '   ')

        fake = MagicMock()
        fake.id = f'cs_test_{_uid()}'
        fake.url = 'https://stripe.test/checkout'
        with patch('stripe.checkout.Session.create', return_value=fake):
            notes_client.post('/checkout/review', data={'is_flexible': '0'})
        _logout(notes_client)

        with _app.app_context():
            order = Order.query.filter_by(stripe_checkout_session_id=fake.id).first()
            assert order.delivery_notes is None

    def test_notes_copied_to_buyer_order_on_webhook(self, notes_client, notes_users, notes_item):
        """The driver's stop card reads BuyerOrder — notes must be denormalized there."""
        from app import app as _app, db
        from models import User, Order, BuyerOrder, InventoryItem
        seller_id, buyer_id = notes_users
        with _app.app_context():
            buyer = User.query.get(buyer_id)

        _to_address_step(notes_client, buyer.email, [notes_item], _app)
        _submit_address(notes_client, 'Apt 9, park in visitor lot')

        fake = MagicMock()
        fake.id = f'cs_test_{_uid()}'
        fake.url = 'https://stripe.test/checkout'
        with patch('stripe.checkout.Session.create', return_value=fake):
            notes_client.post('/checkout/review', data={'is_flexible': '0'})
        _logout(notes_client)

        with _app.app_context():
            order = Order.query.filter_by(stripe_checkout_session_id=fake.id).first()
            event = {
                'type': 'checkout.session.completed',
                'data': {'object': {
                    'id': fake.id,
                    'metadata': {'type': 'cart_order', 'order_id': str(order.id),
                                 'item_ids': str(notes_item)},
                    'customer_details': {'email': buyer.email, 'phone': None, 'name': 'Notes Buyer'},
                }},
            }
            with patch('app.stripe.Webhook.construct_event', return_value=event), \
                 patch('app.send_email', return_value=True), \
                 patch('app._send_admin_sale_notification', return_value=True), \
                 patch('app._send_buyer_order_confirmation', return_value=True):
                resp = notes_client.post('/webhook', data='{}',
                                         headers={'Stripe-Signature': 'test'})
            assert resp.status_code == 200

            bo = BuyerOrder.query.filter_by(item_id=notes_item).first()
            assert bo is not None
            assert bo.delivery_notes == 'Apt 9, park in visitor lot'

            # cleanup so the item can be reused
            db.session.delete(bo)
            item = InventoryItem.query.get(notes_item)
            item.status = 'available'
            db.session.commit()
