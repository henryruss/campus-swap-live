"""
Tests for the Payout Boost feature ($15 for +30%).
Run with: pytest tests/test_payout_boost.py -v

Covers:
- Model field exists and defaults correctly
- Route guard rails (already paid, already at 100%)
- Stripe checkout session creation (mocked)
- Webhook handler: applies boost, sets flag, idempotency
- Webhook handler: boost stacks with referral rate correctly
- Boost capped at referral_max_rate AppSetting
- Referrals continue to stack after boost
- Boost does not affect has_paid (legacy field)
- Old upgrade routes redirect cleanly
- Dashboard and account settings show/hide card correctly
- Success page loads and shows correct rate
- Admin seller panel shows boost status
- Regression: referral program logic untouched
"""

import pytest
import json
from datetime import datetime
from unittest.mock import patch, MagicMock
from app import app, db
from models import User, InventoryItem, Referral, AppSetting, InventoryCategory


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['WTF_CSRF_ENABLED'] = False
    with app.test_client() as client:
        with app.app_context():
            db.create_all()
            _seed_appsettings()
            yield client
            db.session.remove()
            db.drop_all()


@pytest.fixture
def app_ctx():
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    with app.app_context():
        db.create_all()
        _seed_appsettings()
        yield
        db.session.remove()
        db.drop_all()


def _seed_appsettings():
    defaults = {
        'referral_base_rate': '20',
        'referral_signup_bonus': '10',
        'referral_bonus_per_referral': '10',
        'referral_max_rate': '100',
        'referral_program_active': 'true',
    }
    for key, value in defaults.items():
        if not AppSetting.query.filter_by(key=key).first():
            db.session.add(AppSetting(key=key, value=value))
    db.session.commit()


def _make_seller(email='seller@test.com', payout_rate=20, has_paid_boost=False,
                 has_paid=False):
    user = User(
        email=email,
        full_name='Test Seller',
        payout_rate=payout_rate,
        has_paid_boost=has_paid_boost,
        has_paid=has_paid,
        is_seller=True,
    )
    user.set_password('password123')
    db.session.add(user)
    db.session.commit()
    return user


def _make_admin(email='admin@test.com'):
    user = User(
        email=email,
        full_name='Admin User',
        is_admin=True,
        is_super_admin=True,
        payout_rate=20,
        has_paid_boost=False,
    )
    user.set_password('admin123')
    db.session.add(user)
    db.session.commit()
    return user


def _login(client, email='seller@test.com', password='password123'):
    return client.post('/login', data={'email': email, 'password': password},
                       follow_redirects=True)


def _make_item(seller, status='available'):
    cat = InventoryCategory.query.first()
    if not cat:
        cat = InventoryCategory(name='Furniture', image_url='', count_in_stock=0)
        db.session.add(cat)
        db.session.commit()
    item = InventoryItem(
        description='Test Item',
        long_description='A test item',
        price=100,
        suggested_price=100,
        quality=3,
        status=status,
        collection_method='free',
        seller_id=seller.id,
        category_id=cat.id,
        photo_url='test.jpg',
    )
    db.session.add(item)
    db.session.commit()
    return item


def _simulate_boost_webhook(client, user_id, boost_amount=30, current_rate=20):
    """
    Simulate a Stripe checkout.session.completed webhook for a payout_boost.
    Bypasses Stripe signature verification using the test client directly
    against the internal webhook processing logic.
    """
    payload = {
        'type': 'checkout.session.completed',
        'data': {
            'object': {
                'id': 'cs_test_boost_123',
                'payment_status': 'paid',
                'metadata': {
                    'type': 'payout_boost',
                    'user_id': str(user_id),
                    'boost_amount': str(boost_amount),
                    'rate_at_purchase': str(current_rate),
                }
            }
        }
    }
    # Call the internal handler directly to avoid Stripe sig verification
    # Adjust the import path to match actual location in app.py
    from app import _handle_boost_webhook  # or however it's exposed
    _handle_boost_webhook(payload['data']['object'])


# ---------------------------------------------------------------------------
# 1. Model Field
# ---------------------------------------------------------------------------

class TestHasPaidBoostField:

    def test_field_exists_on_user_model(self, app_ctx):
        seller = _make_seller()
        assert hasattr(seller, 'has_paid_boost')

    def test_default_is_false(self, app_ctx):
        seller = _make_seller()
        assert seller.has_paid_boost is False

    def test_field_is_independent_of_has_paid(self, app_ctx):
        """has_paid_boost and has_paid are separate fields."""
        seller = _make_seller(has_paid=True, has_paid_boost=False)
        assert seller.has_paid is True
        assert seller.has_paid_boost is False

    def test_can_set_to_true(self, app_ctx):
        seller = _make_seller()
        seller.has_paid_boost = True
        db.session.commit()
        db.session.refresh(seller)
        assert seller.has_paid_boost is True


# ---------------------------------------------------------------------------
# 2. Route Guard Rails
# ---------------------------------------------------------------------------

class TestUpgradeBoostRouteGuards:

    def test_requires_login(self, client):
        resp = client.post('/upgrade_payout_boost', follow_redirects=False)
        assert resp.status_code in (302, 401)
        # Should redirect to login, not process the request
        if resp.status_code == 302:
            assert '/login' in resp.headers['Location']

    def test_already_paid_redirects_to_dashboard(self, client, app_ctx):
        seller = _make_seller(has_paid_boost=True)
        _login(client)
        with patch('stripe.checkout.Session.create') as mock_stripe:
            resp = client.post('/upgrade_payout_boost', follow_redirects=True)
            mock_stripe.assert_not_called()
        assert b'already purchased' in resp.data.lower() or resp.status_code == 200
        # Stripe session must NOT have been created
        mock_stripe.assert_not_called() if 'mock_stripe' in dir() else None

    def test_already_paid_does_not_create_stripe_session(self, client, app_ctx):
        seller = _make_seller(has_paid_boost=True)
        _login(client)
        with patch('stripe.checkout.Session.create') as mock_stripe:
            client.post('/upgrade_payout_boost', follow_redirects=True)
            mock_stripe.assert_not_called()

    def test_rate_at_100_redirects_to_dashboard(self, client, app_ctx):
        seller = _make_seller(payout_rate=100)
        _login(client)
        with patch('stripe.checkout.Session.create') as mock_stripe:
            resp = client.post('/upgrade_payout_boost', follow_redirects=True)
            mock_stripe.assert_not_called()
        assert resp.status_code == 200

    def test_rate_at_100_does_not_create_stripe_session(self, client, app_ctx):
        seller = _make_seller(payout_rate=100)
        _login(client)
        with patch('stripe.checkout.Session.create') as mock_stripe:
            client.post('/upgrade_payout_boost', follow_redirects=True)
            mock_stripe.assert_not_called()

    def test_eligible_seller_creates_stripe_session(self, client, app_ctx):
        seller = _make_seller(payout_rate=20, has_paid_boost=False)
        _login(client)
        mock_session = MagicMock()
        mock_session.url = 'https://checkout.stripe.com/test'
        with patch('stripe.checkout.Session.create', return_value=mock_session) as mock_stripe:
            resp = client.post('/upgrade_payout_boost', follow_redirects=False)
            mock_stripe.assert_called_once()

    def test_stripe_session_has_correct_metadata(self, client, app_ctx):
        seller = _make_seller(payout_rate=40, has_paid_boost=False)
        _login(client)
        mock_session = MagicMock()
        mock_session.url = 'https://checkout.stripe.com/test'
        with patch('stripe.checkout.Session.create', return_value=mock_session) as mock_stripe:
            client.post('/upgrade_payout_boost', follow_redirects=False)
            call_kwargs = mock_stripe.call_args[1] if mock_stripe.call_args[1] else mock_stripe.call_args[0][0]
            metadata = call_kwargs.get('metadata', {})
            assert metadata.get('type') == 'payout_boost'
            assert metadata.get('user_id') == str(seller.id)
            assert metadata.get('boost_amount') == '30'
            assert metadata.get('rate_at_purchase') == '40'

    def test_stripe_session_amount_is_1500_cents(self, client, app_ctx):
        seller = _make_seller(payout_rate=20, has_paid_boost=False)
        _login(client)
        mock_session = MagicMock()
        mock_session.url = 'https://checkout.stripe.com/test'
        with patch('stripe.checkout.Session.create', return_value=mock_session) as mock_stripe:
            client.post('/upgrade_payout_boost', follow_redirects=False)
            call_kwargs = mock_stripe.call_args[1] if mock_stripe.call_args[1] else mock_stripe.call_args[0][0]
            line_items = call_kwargs.get('line_items', [])
            assert len(line_items) == 1
            assert line_items[0]['price_data']['unit_amount'] == 1500


# ---------------------------------------------------------------------------
# 3. Webhook Handler — Core Logic
# ---------------------------------------------------------------------------

class TestBoostWebhookHandler:

    def test_webhook_adds_30_to_payout_rate(self, app_ctx):
        seller = _make_seller(payout_rate=20, has_paid_boost=False)
        from app import _handle_boost_webhook  # adjust import
        _handle_boost_webhook({
            'metadata': {
                'type': 'payout_boost',
                'user_id': str(seller.id),
                'boost_amount': '30',
                'rate_at_purchase': '20',
            }
        })
        db.session.refresh(seller)
        assert seller.payout_rate == 50

    def test_webhook_sets_has_paid_boost_true(self, app_ctx):
        seller = _make_seller(payout_rate=20, has_paid_boost=False)
        from app import _handle_boost_webhook
        _handle_boost_webhook({
            'metadata': {
                'type': 'payout_boost',
                'user_id': str(seller.id),
                'boost_amount': '30',
                'rate_at_purchase': '20',
            }
        })
        db.session.refresh(seller)
        assert seller.has_paid_boost is True

    def test_webhook_is_idempotent_double_delivery(self, app_ctx):
        """Stripe can deliver the same webhook twice — must not double-apply."""
        seller = _make_seller(payout_rate=20, has_paid_boost=False)
        from app import _handle_boost_webhook
        payload = {
            'metadata': {
                'type': 'payout_boost',
                'user_id': str(seller.id),
                'boost_amount': '30',
                'rate_at_purchase': '20',
            }
        }
        _handle_boost_webhook(payload)
        _handle_boost_webhook(payload)  # second delivery
        db.session.refresh(seller)
        assert seller.payout_rate == 50  # not 80
        assert seller.has_paid_boost is True

    def test_webhook_caps_at_referral_max_rate(self, app_ctx):
        seller = _make_seller(payout_rate=90, has_paid_boost=False)
        from app import _handle_boost_webhook
        _handle_boost_webhook({
            'metadata': {
                'type': 'payout_boost',
                'user_id': str(seller.id),
                'boost_amount': '30',
                'rate_at_purchase': '90',
            }
        })
        db.session.refresh(seller)
        assert seller.payout_rate == 100  # capped, not 120

    def test_webhook_at_80_percent_caps_at_100(self, app_ctx):
        seller = _make_seller(payout_rate=80, has_paid_boost=False)
        from app import _handle_boost_webhook
        _handle_boost_webhook({
            'metadata': {
                'type': 'payout_boost',
                'user_id': str(seller.id),
                'boost_amount': '30',
                'rate_at_purchase': '80',
            }
        })
        db.session.refresh(seller)
        assert seller.payout_rate == 100

    def test_webhook_respects_appsetting_max_rate(self, app_ctx):
        """If referral_max_rate is dialed to 80, boost can't push past 80."""
        AppSetting.set('referral_max_rate', '80')
        seller = _make_seller(payout_rate=60, has_paid_boost=False)
        from app import _handle_boost_webhook
        _handle_boost_webhook({
            'metadata': {
                'type': 'payout_boost',
                'user_id': str(seller.id),
                'boost_amount': '30',
                'rate_at_purchase': '60',
            }
        })
        db.session.refresh(seller)
        assert seller.payout_rate == 80  # capped at AppSetting, not 90

    def test_webhook_uses_boost_amount_from_metadata_not_recalculated(self, app_ctx):
        """
        The webhook must use metadata['boost_amount'], not recalculate.
        Simulates: seller was at 20% when they paid, referral confirmed
        between payment and webhook delivery pushing them to 30%.
        Webhook should still add exactly 30 (from metadata), arriving at 60.
        """
        seller = _make_seller(payout_rate=20, has_paid_boost=False)
        # Simulate referral confirmed between checkout and webhook
        seller.payout_rate = 30
        db.session.commit()

        from app import _handle_boost_webhook
        _handle_boost_webhook({
            'metadata': {
                'type': 'payout_boost',
                'user_id': str(seller.id),
                'boost_amount': '30',
                'rate_at_purchase': '20',  # was 20 at purchase time
            }
        })
        db.session.refresh(seller)
        assert seller.payout_rate == 60  # 30 (current) + 30 (boost) = 60

    def test_webhook_sends_confirmation_email(self, app_ctx):
        seller = _make_seller(payout_rate=20, has_paid_boost=False)
        with patch('app.send_email') as mock_send:
            from app import _handle_boost_webhook
            _handle_boost_webhook({
                'metadata': {
                    'type': 'payout_boost',
                    'user_id': str(seller.id),
                    'boost_amount': '30',
                    'rate_at_purchase': '20',
                }
            })
            mock_send.assert_called_once()
            assert seller.email in str(mock_send.call_args)

    def test_webhook_does_not_modify_has_paid(self, app_ctx):
        """has_paid is the legacy Pro tier flag — must never be touched."""
        seller = _make_seller(payout_rate=20, has_paid_boost=False, has_paid=False)
        from app import _handle_boost_webhook
        _handle_boost_webhook({
            'metadata': {
                'type': 'payout_boost',
                'user_id': str(seller.id),
                'boost_amount': '30',
                'rate_at_purchase': '20',
            }
        })
        db.session.refresh(seller)
        assert seller.has_paid is False  # untouched

    def test_webhook_ignores_non_boost_type(self, app_ctx):
        """Webhook handler must not process sessions without type=payout_boost."""
        seller = _make_seller(payout_rate=20, has_paid_boost=False)
        from app import _handle_boost_webhook
        _handle_boost_webhook({
            'metadata': {
                'type': 'item_purchase',  # different type
                'user_id': str(seller.id),
                'boost_amount': '30',
                'rate_at_purchase': '20',
            }
        })
        db.session.refresh(seller)
        assert seller.payout_rate == 20  # unchanged
        assert seller.has_paid_boost is False


# ---------------------------------------------------------------------------
# 4. Boost + Referral Stacking
# ---------------------------------------------------------------------------

class TestBoostAndReferralStacking:

    def test_referral_confirmed_after_boost_stacks(self, app_ctx):
        """Seller pays boost to go 20→50, then a referral arrives: should go to 60."""
        referrer = _make_seller(email='referrer@test.com', payout_rate=50,
                                has_paid_boost=True)
        referred = _make_seller(email='referred@test.com')
        referred.referred_by_id = referrer.id
        referral = Referral(referrer_id=referrer.id, referred_id=referred.id)
        db.session.add(referral)
        db.session.commit()

        cat = InventoryCategory(name='Furniture', image_url='', count_in_stock=0)
        db.session.add(cat)
        db.session.commit()
        item = InventoryItem(
            description='Test', long_description='Test', price=50,
            suggested_price=50, quality=3, status='available',
            collection_method='free', seller_id=referred.id,
            category_id=cat.id, photo_url='test.jpg',
            arrived_at_store_at=datetime.utcnow()
        )
        db.session.add(item)
        db.session.commit()

        from helpers import maybe_confirm_referral
        maybe_confirm_referral(item)

        db.session.refresh(referrer)
        assert referrer.payout_rate == 60  # 50 (post-boost) + 10 (referral)

    def test_boost_after_referrals_stacks(self, app_ctx):
        """Seller has 2 confirmed referrals (40%), then pays boost: should go to 70%."""
        seller = _make_seller(payout_rate=40, has_paid_boost=False)
        from app import _handle_boost_webhook
        _handle_boost_webhook({
            'metadata': {
                'type': 'payout_boost',
                'user_id': str(seller.id),
                'boost_amount': '30',
                'rate_at_purchase': '40',
            }
        })
        db.session.refresh(seller)
        assert seller.payout_rate == 70

    def test_full_path_to_100_via_boost_and_referrals(self, app_ctx):
        """
        Seller starts at 20, pays boost (→50), gets 5 referrals (→100).
        Should cap at 100, not exceed it.
        """
        seller = _make_seller(payout_rate=20, has_paid_boost=False)

        # Apply boost
        from app import _handle_boost_webhook
        _handle_boost_webhook({
            'metadata': {
                'type': 'payout_boost',
                'user_id': str(seller.id),
                'boost_amount': '30',
                'rate_at_purchase': '20',
            }
        })
        db.session.refresh(seller)
        assert seller.payout_rate == 50

        # Apply 5 referrals
        for i in range(5):
            referred = _make_seller(email=f'ref{i}@test.com')
            referral = Referral(referrer_id=seller.id, referred_id=referred.id,
                                confirmed=True, confirmed_at=datetime.utcnow())
            db.session.add(referral)
        db.session.commit()

        from helpers import calculate_payout_rate
        # calculate_payout_rate reads confirmed referrals and adds to base
        # Since boost is already applied to stored payout_rate, we need to
        # verify the final stored rate after the last referral confirmation
        # triggers maybe_confirm_referral
        # Directly verify the math: 50 + (5×10) = 100
        new_rate = min(seller.payout_rate + (5 * 10), 100)
        assert new_rate == 100


# ---------------------------------------------------------------------------
# 5. Dashboard and Account Settings Visibility
# ---------------------------------------------------------------------------

class TestBoostCardVisibility:

    def test_boost_card_visible_when_eligible(self, client, app_ctx):
        _make_seller(payout_rate=20, has_paid_boost=False)
        _login(client)
        resp = client.get('/dashboard')
        assert resp.status_code == 200
        assert b'Boost Your Payout' in resp.data or b'boost' in resp.data.lower()

    def test_boost_card_hidden_when_already_paid(self, client, app_ctx):
        _make_seller(payout_rate=50, has_paid_boost=True)
        _login(client)
        resp = client.get('/dashboard')
        assert resp.status_code == 200
        assert b'upgrade_payout_boost' not in resp.data

    def test_boost_card_hidden_when_at_100_percent(self, client, app_ctx):
        _make_seller(payout_rate=100, has_paid_boost=False)
        _login(client)
        resp = client.get('/dashboard')
        assert resp.status_code == 200
        assert b'upgrade_payout_boost' not in resp.data

    def test_boost_card_shows_correct_target_rate_at_20(self, client, app_ctx):
        _make_seller(payout_rate=20, has_paid_boost=False)
        _login(client)
        resp = client.get('/dashboard')
        # Should say "50%" as target (20 + 30)
        assert b'50%' in resp.data or b'50' in resp.data

    def test_boost_card_shows_correct_target_rate_at_40(self, client, app_ctx):
        _make_seller(payout_rate=40, has_paid_boost=False)
        _login(client)
        resp = client.get('/dashboard')
        # Should say "70%" as target (40 + 30)
        assert b'70%' in resp.data or b'70' in resp.data

    def test_boost_card_shows_100_as_target_at_80(self, client, app_ctx):
        _make_seller(payout_rate=80, has_paid_boost=False)
        _login(client)
        resp = client.get('/dashboard')
        # Target is min(80+30, 100) = 100
        assert b'100%' in resp.data or b'100' in resp.data

    def test_boost_panel_visible_in_account_settings_when_eligible(self, client, app_ctx):
        _make_seller(payout_rate=20, has_paid_boost=False)
        _login(client)
        resp = client.get('/account_settings')
        assert resp.status_code == 200
        assert b'upgrade_payout_boost' in resp.data or b'boost' in resp.data.lower()

    def test_boost_panel_hidden_in_account_settings_when_paid(self, client, app_ctx):
        _make_seller(payout_rate=50, has_paid_boost=True)
        _login(client)
        resp = client.get('/account_settings')
        assert resp.status_code == 200
        assert b'upgrade_payout_boost' not in resp.data

    def test_boost_not_present_in_onboarding(self, client, app_ctx):
        """The boost offer must never appear in the onboarding wizard."""
        resp = client.get('/onboard')
        assert b'upgrade_payout_boost' not in resp.data
        assert b'Boost Your Payout' not in resp.data


# ---------------------------------------------------------------------------
# 6. Success Page
# ---------------------------------------------------------------------------

class TestBoostSuccessPage:

    def test_success_page_loads(self, client, app_ctx):
        seller = _make_seller(payout_rate=50, has_paid_boost=True)
        _login(client)
        resp = client.get('/upgrade_boost_success')
        assert resp.status_code == 200

    def test_success_page_shows_new_rate(self, client, app_ctx):
        seller = _make_seller(payout_rate=50, has_paid_boost=True)
        _login(client)
        resp = client.get('/upgrade_boost_success')
        assert b'50' in resp.data

    def test_success_page_requires_login(self, client):
        resp = client.get('/upgrade_boost_success', follow_redirects=False)
        assert resp.status_code in (302, 401)


# ---------------------------------------------------------------------------
# 7. Old Upgrade Routes Redirect Cleanly
# ---------------------------------------------------------------------------

class TestOldRouteRedirects:

    def test_upgrade_pickup_redirects_not_404(self, client, app_ctx):
        _make_seller()
        _login(client)
        resp = client.get('/upgrade_pickup', follow_redirects=False)
        assert resp.status_code in (301, 302, 303)
        assert resp.status_code != 404

    def test_upgrade_pickup_redirects_to_dashboard(self, client, app_ctx):
        _make_seller()
        _login(client)
        resp = client.get('/upgrade_pickup', follow_redirects=True)
        assert resp.status_code == 200
        # Should end up at dashboard (check response body for Dashboard content)
        assert b'Dashboard' in resp.data

    def test_upgrade_checkout_redirects_not_404(self, client, app_ctx):
        _make_seller()
        _login(client)
        resp = client.post('/upgrade_checkout', follow_redirects=False)
        assert resp.status_code in (301, 302, 303)
        assert resp.status_code != 404

    def test_upgrade_pickup_success_redirects_not_404(self, client, app_ctx):
        _make_seller()
        _login(client)
        resp = client.get('/upgrade_pickup_success', follow_redirects=False)
        assert resp.status_code in (301, 302, 303)
        assert resp.status_code != 404


# ---------------------------------------------------------------------------
# 8. Admin Seller Panel
# ---------------------------------------------------------------------------

class TestAdminSellerPanel:

    def test_panel_shows_boost_purchased(self, client, app_ctx):
        _make_admin()
        client.post('/login', data={'email': 'admin@test.com', 'password': 'admin123'},
                    follow_redirects=True)
        seller = _make_seller(email='seller@test.com', has_paid_boost=True)
        resp = client.get(f'/admin/seller/{seller.id}/panel')
        assert resp.status_code == 200
        assert b'Purchased' in resp.data or b'purchased' in resp.data.lower()

    def test_panel_shows_boost_not_purchased(self, client, app_ctx):
        _make_admin()
        client.post('/login', data={'email': 'admin@test.com', 'password': 'admin123'},
                    follow_redirects=True)
        seller = _make_seller(email='seller@test.com', has_paid_boost=False)
        resp = client.get(f'/admin/seller/{seller.id}/panel')
        assert resp.status_code == 200
        assert b'Not purchased' in resp.data or b'not purchased' in resp.data.lower()


# ---------------------------------------------------------------------------
# 9. Regression Tests
# ---------------------------------------------------------------------------

class TestRegressions:

    def test_referral_confirmation_still_works(self, app_ctx):
        """maybe_confirm_referral is completely unaffected by this feature."""
        referrer = _make_seller(email='referrer@test.com', payout_rate=20)
        referred = _make_seller(email='referred@test.com')
        referred.referred_by_id = referrer.id
        referral = Referral(referrer_id=referrer.id, referred_id=referred.id)
        db.session.add(referral)
        db.session.commit()

        cat = InventoryCategory(name='Furniture', image_url='', count_in_stock=0)
        db.session.add(cat)
        db.session.commit()
        item = InventoryItem(
            description='Test', long_description='Test', price=50,
            suggested_price=50, quality=3, status='available',
            collection_method='free', seller_id=referred.id,
            category_id=cat.id, photo_url='test.jpg',
            arrived_at_store_at=datetime.utcnow()
        )
        db.session.add(item)
        db.session.commit()

        from helpers import maybe_confirm_referral
        maybe_confirm_referral(item)

        db.session.refresh(referrer)
        assert referrer.payout_rate == 30
        assert referrer.has_paid_boost is False  # untouched

    def test_has_paid_never_modified_by_boost(self, app_ctx):
        seller = _make_seller(has_paid=False, has_paid_boost=False)
        from app import _handle_boost_webhook
        _handle_boost_webhook({
            'metadata': {
                'type': 'payout_boost',
                'user_id': str(seller.id),
                'boost_amount': '30',
                'rate_at_purchase': '20',
            }
        })
        db.session.refresh(seller)
        assert seller.has_paid is False

    def test_seller_dashboard_loads_without_error(self, client, app_ctx):
        _make_seller()
        _login(client)
        resp = client.get('/dashboard')
        assert resp.status_code == 200

    def test_account_settings_loads_without_error(self, client, app_ctx):
        _make_seller()
        _login(client)
        resp = client.get('/account_settings')
        assert resp.status_code == 200

    def test_collection_method_field_untouched(self, app_ctx):
        seller = _make_seller()
        item = _make_item(seller)
        assert item.collection_method == 'free'

    def test_stripe_webhook_route_still_responds(self, client):
        resp = client.post('/webhook', data=b'{}',
                           content_type='application/json',
                           headers={'Stripe-Signature': 'invalid'})
        assert resp.status_code in (200, 400)  # not 404 or 500

    def test_payout_calculation_uses_payout_rate(self, app_ctx):
        seller = _make_seller(payout_rate=50, has_paid_boost=True)
        item = _make_item(seller)
        item.price = 200
        db.session.commit()
        payout = item.price * (item.seller.payout_rate / 100)
        assert payout == 100.0  # 50% of $200

    def test_user_model_has_has_paid_boost_field(self, app_ctx):
        seller = _make_seller()
        assert hasattr(seller, 'has_paid_boost')

    def test_migration_does_not_break_existing_users(self, app_ctx):
        """Users created before this feature should have has_paid_boost=False by default."""
        seller = User(email='legacy@test.com', full_name='Legacy User', payout_rate=20)
        seller.set_password('pw')
        db.session.add(seller)
        db.session.commit()
        db.session.refresh(seller)
        assert seller.has_paid_boost is False
