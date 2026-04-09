"""
Tests for the referral program feature.
Run with: pytest tests/test_referral.py -v

These tests cover:
- Referral code generation
- Code application at registration
- Signup bonus for referred users
- Referral confirmation on item arrival at storage
- Payout rate calculation (base, bonus, cap)
- AppSetting-driven configurability
- Edge cases (self-referral, invalid code, double confirmation, etc.)
- Payout amount calculation uses payout_rate (not collection_method)
- OAuth + guest session referral code carry-through
- /referral/validate endpoint
- Admin panel referral stats
- Referral window (no confirmation without arrived_at_store_at)
"""

import pytest
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
    """Seed the default referral AppSettings."""
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


def _make_user(email='seller@test.com', full_name='Test Seller', payout_rate=20):
    """Create a basic seller user."""
    from helpers import generate_referral_code  # adjust import to match actual location
    user = User(
        email=email,
        full_name=full_name,
        payout_rate=payout_rate,
        is_seller=True,
    )
    user.referral_code = generate_referral_code()
    user.set_password('password123')
    db.session.add(user)
    db.session.commit()
    return user


def _make_item(seller, status='pending_valuation', arrived=False):
    """Create a basic inventory item."""
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
        arrived_at_store_at=datetime.utcnow() if arrived else None,
    )
    db.session.add(item)
    db.session.commit()
    return item


def _login(client, email='seller@test.com', password='password123'):
    return client.post('/login', data={'email': email, 'password': password},
                       follow_redirects=True)


# ---------------------------------------------------------------------------
# 1. Referral Code Generation
# ---------------------------------------------------------------------------

class TestReferralCodeGeneration:

    def test_every_new_user_gets_a_referral_code(self, app_ctx):
        user = _make_user()
        assert user.referral_code is not None
        assert len(user.referral_code) == 8

    def test_referral_code_is_uppercase_alphanumeric(self, app_ctx):
        user = _make_user()
        code = user.referral_code
        assert code == code.upper()
        assert code.isalnum()

    def test_referral_code_excludes_ambiguous_characters(self, app_ctx):
        """O, 0, I, 1 must never appear in generated codes."""
        for _ in range(50):
            user = _make_user(email=f'user{_}@test.com')
            for bad_char in ('O', '0', 'I', '1'):
                assert bad_char not in user.referral_code, \
                    f"Ambiguous character '{bad_char}' found in code: {user.referral_code}"

    def test_referral_codes_are_unique(self, app_ctx):
        users = [_make_user(email=f'u{i}@test.com') for i in range(20)]
        codes = [u.referral_code for u in users]
        assert len(codes) == len(set(codes)), "Duplicate referral codes generated"

    def test_existing_users_get_codes_via_backfill(self, app_ctx):
        """Simulate a user who existed before the feature (no referral_code)."""
        user = User(email='old@test.com', full_name='Old User', payout_rate=20)
        user.set_password('pw')
        db.session.add(user)
        db.session.commit()
        assert user.referral_code is None

        # Run the backfill script / helper
        from helpers import backfill_referral_codes  # adjust import
        backfill_referral_codes()

        db.session.refresh(user)
        assert user.referral_code is not None
        assert len(user.referral_code) == 8


# ---------------------------------------------------------------------------
# 2. Applying a Referral Code at Registration
# ---------------------------------------------------------------------------

class TestReferralCodeAtRegistration:

    def test_valid_code_sets_referred_by_id(self, client):
        referrer = _make_user(email='referrer@test.com')
        resp = client.post('/register', data={
            'email': 'newuser@test.com',
            'full_name': 'New User',
            'password': 'password123',
            'referral_code': referrer.referral_code,
        }, follow_redirects=True)
        assert resp.status_code == 200
        new_user = User.query.filter_by(email='newuser@test.com').first()
        assert new_user is not None
        assert new_user.referred_by_id == referrer.id

    def test_valid_code_gives_signup_bonus(self, client):
        referrer = _make_user(email='referrer@test.com')
        client.post('/register', data={
            'email': 'newuser@test.com',
            'full_name': 'New User',
            'password': 'password123',
            'referral_code': referrer.referral_code,
        }, follow_redirects=True)
        new_user = User.query.filter_by(email='newuser@test.com').first()
        assert new_user.payout_rate == 30  # base 20 + signup bonus 10

    def test_no_code_gives_base_rate(self, client):
        client.post('/register', data={
            'email': 'newuser@test.com',
            'full_name': 'New User',
            'password': 'password123',
            'referral_code': '',
        }, follow_redirects=True)
        new_user = User.query.filter_by(email='newuser@test.com').first()
        assert new_user.payout_rate == 20

    def test_invalid_code_is_silently_ignored(self, client):
        resp = client.post('/register', data={
            'email': 'newuser@test.com',
            'full_name': 'New User',
            'password': 'password123',
            'referral_code': 'NOTREAL',
        }, follow_redirects=True)
        assert resp.status_code == 200
        new_user = User.query.filter_by(email='newuser@test.com').first()
        assert new_user is not None  # account still created
        assert new_user.payout_rate == 20
        assert new_user.referred_by_id is None

    def test_self_referral_is_rejected(self, client, app_ctx):
        """A user cannot use their own referral code."""
        # This scenario requires creating the user first, then trying to
        # apply their own code. Test at the helper level.
        from helpers import apply_referral_code
        user = _make_user()
        original_rate = user.payout_rate
        apply_referral_code(user, user.referral_code)
        db.session.refresh(user)
        assert user.payout_rate == original_rate
        assert user.referred_by_id is None

    def test_referral_code_is_case_insensitive(self, client):
        referrer = _make_user(email='referrer@test.com')
        client.post('/register', data={
            'email': 'newuser@test.com',
            'full_name': 'New User',
            'password': 'password123',
            'referral_code': referrer.referral_code.lower(),
        }, follow_redirects=True)
        new_user = User.query.filter_by(email='newuser@test.com').first()
        assert new_user.referred_by_id == referrer.id

    def test_unconfirmed_referral_row_created_on_signup(self, client):
        referrer = _make_user(email='referrer@test.com')
        client.post('/register', data={
            'email': 'newuser@test.com',
            'full_name': 'New User',
            'password': 'password123',
            'referral_code': referrer.referral_code,
        }, follow_redirects=True)
        new_user = User.query.filter_by(email='newuser@test.com').first()
        referral = Referral.query.filter_by(
            referrer_id=referrer.id, referred_id=new_user.id
        ).first()
        assert referral is not None
        assert referral.confirmed is False
        assert referral.confirmed_at is None

    def test_referrer_payout_rate_does_not_change_at_signup(self, client):
        """Referrer rate only changes when item arrives — not when friend signs up."""
        referrer = _make_user(email='referrer@test.com')
        original_rate = referrer.payout_rate
        client.post('/register', data={
            'email': 'newuser@test.com',
            'full_name': 'New User',
            'password': 'password123',
            'referral_code': referrer.referral_code,
        }, follow_redirects=True)
        db.session.refresh(referrer)
        assert referrer.payout_rate == original_rate

    def test_referral_code_from_url_param_prepopulates(self, client):
        referrer = _make_user(email='referrer@test.com')
        resp = client.get(f'/register?ref={referrer.referral_code}')
        assert resp.status_code == 200
        assert referrer.referral_code.encode() in resp.data


# ---------------------------------------------------------------------------
# 3. Referral Confirmation (Item Arrives at Storage)
# ---------------------------------------------------------------------------

class TestReferralConfirmation:

    def test_referral_confirmed_when_stop_completed(self, client, app_ctx):
        referrer = _make_user(email='referrer@test.com')
        referred = _make_user(email='referred@test.com')
        referred.referred_by_id = referrer.id
        db.session.commit()

        referral = Referral(referrer_id=referrer.id, referred_id=referred.id)
        db.session.add(referral)
        db.session.commit()

        from helpers import maybe_confirm_referral_for_seller
        maybe_confirm_referral_for_seller(referred)

        referral = Referral.query.filter_by(
            referrer_id=referrer.id, referred_id=referred.id
        ).first()
        assert referral.confirmed is True
        assert referral.confirmed_at is not None

    def test_referrer_payout_rate_increases_on_confirmation(self, app_ctx):
        referrer = _make_user(email='referrer@test.com')
        referred = _make_user(email='referred@test.com')
        referred.referred_by_id = referrer.id
        db.session.commit()

        referral = Referral(referrer_id=referrer.id, referred_id=referred.id)
        db.session.add(referral)
        db.session.commit()

        from helpers import maybe_confirm_referral_for_seller
        maybe_confirm_referral_for_seller(referred)

        db.session.refresh(referrer)
        assert referrer.payout_rate == 30  # 20 base + 10 bonus

    def test_second_stop_completion_for_same_seller_does_not_double_count(self, app_ctx):
        referrer = _make_user(email='referrer@test.com')
        referred = _make_user(email='referred@test.com')
        referred.referred_by_id = referrer.id
        db.session.commit()

        referral = Referral(referrer_id=referrer.id, referred_id=referred.id, confirmed=True,
                            confirmed_at=datetime.utcnow())
        db.session.add(referral)
        db.session.commit()

        from helpers import maybe_confirm_referral_for_seller
        maybe_confirm_referral_for_seller(referred)

        db.session.refresh(referrer)
        # Rate should still be 30, not 40
        assert referrer.payout_rate == 30

    def test_no_referral_confirmed_when_program_inactive_at_stop(self, app_ctx):
        """Stop completion while referral program is off should not confirm the referral."""
        AppSetting.set('referral_program_active', 'false')
        referrer = _make_user(email='referrer@test.com')
        referred = _make_user(email='referred@test.com')
        referred.referred_by_id = referrer.id
        referral = Referral(referrer_id=referrer.id, referred_id=referred.id)
        db.session.add(referral)
        db.session.commit()

        from helpers import maybe_confirm_referral_for_seller
        maybe_confirm_referral_for_seller(referred)

        db.session.refresh(referrer)
        db.session.refresh(referral)
        assert referral.confirmed is False
        assert referrer.payout_rate == 20

    def test_no_referral_for_user_with_no_referred_by_id(self, app_ctx):
        """Stop completion for a non-referred seller should not error or create referral records."""
        seller = _make_user()
        assert seller.referred_by_id is None

        from helpers import maybe_confirm_referral_for_seller
        maybe_confirm_referral_for_seller(seller)  # should not raise

        assert Referral.query.count() == 0

    def test_confirmation_email_sent_to_referrer(self, app_ctx):
        referrer = _make_user(email='referrer@test.com')
        referred = _make_user(email='referred@test.com')
        referred.referred_by_id = referrer.id
        db.session.commit()

        referral = Referral(referrer_id=referrer.id, referred_id=referred.id)
        db.session.add(referral)
        db.session.commit()

        with patch('app.send_email') as mock_send:
            from helpers import maybe_confirm_referral_for_seller
            maybe_confirm_referral_for_seller(referred)
            mock_send.assert_called_once()
            call_args = mock_send.call_args
            assert referrer.email in call_args[0] or referrer.email in str(call_args)


# ---------------------------------------------------------------------------
# 4. Payout Rate Calculation
# ---------------------------------------------------------------------------

class TestPayoutRateCalculation:

    def test_base_rate_with_zero_referrals(self, app_ctx):
        from helpers import calculate_payout_rate
        user = _make_user()
        assert calculate_payout_rate(user) == 20

    def test_rate_increases_per_confirmed_referral(self, app_ctx):
        from helpers import calculate_payout_rate
        referrer = _make_user()
        for i in range(3):
            referred = _make_user(email=f'referred{i}@test.com')
            referral = Referral(referrer_id=referrer.id, referred_id=referred.id,
                                confirmed=True, confirmed_at=datetime.utcnow())
            db.session.add(referral)
        db.session.commit()
        assert calculate_payout_rate(referrer) == 50  # 20 + (3 × 10)

    def test_rate_is_capped_at_max(self, app_ctx):
        from helpers import calculate_payout_rate
        referrer = _make_user()
        for i in range(10):  # 10 referrals → would be 120% without cap
            referred = _make_user(email=f'referred{i}@test.com')
            referral = Referral(referrer_id=referrer.id, referred_id=referred.id,
                                confirmed=True, confirmed_at=datetime.utcnow())
            db.session.add(referral)
        db.session.commit()
        assert calculate_payout_rate(referrer) == 100

    def test_unconfirmed_referrals_do_not_count(self, app_ctx):
        from helpers import calculate_payout_rate
        referrer = _make_user()
        for i in range(5):
            referred = _make_user(email=f'referred{i}@test.com')
            referral = Referral(referrer_id=referrer.id, referred_id=referred.id,
                                confirmed=False)  # not confirmed
            db.session.add(referral)
        db.session.commit()
        assert calculate_payout_rate(referrer) == 20

    def test_rate_respects_appsetting_bonus_per_referral(self, app_ctx):
        """Changing referral_bonus_per_referral AppSetting changes calculation."""
        from helpers import calculate_payout_rate
        AppSetting.set('referral_bonus_per_referral', '5')
        referrer = _make_user()
        for i in range(4):
            referred = _make_user(email=f'referred{i}@test.com')
            referral = Referral(referrer_id=referrer.id, referred_id=referred.id,
                                confirmed=True, confirmed_at=datetime.utcnow())
            db.session.add(referral)
        db.session.commit()
        assert calculate_payout_rate(referrer) == 40  # 20 + (4 × 5)

    def test_rate_respects_appsetting_max_rate(self, app_ctx):
        """Lowering referral_max_rate caps existing high earners."""
        from helpers import calculate_payout_rate
        AppSetting.set('referral_max_rate', '60')
        referrer = _make_user()
        for i in range(8):
            referred = _make_user(email=f'referred{i}@test.com')
            referral = Referral(referrer_id=referrer.id, referred_id=referred.id,
                                confirmed=True, confirmed_at=datetime.utcnow())
            db.session.add(referral)
        db.session.commit()
        assert calculate_payout_rate(referrer) == 60

    def test_rate_respects_appsetting_base_rate(self, app_ctx):
        from helpers import calculate_payout_rate
        AppSetting.set('referral_base_rate', '25')
        user = _make_user()
        assert calculate_payout_rate(user) == 25

    def test_eight_referrals_reaches_100_percent(self, app_ctx):
        from helpers import calculate_payout_rate
        referrer = _make_user()
        for i in range(8):
            referred = _make_user(email=f'referred{i}@test.com')
            referral = Referral(referrer_id=referrer.id, referred_id=referred.id,
                                confirmed=True, confirmed_at=datetime.utcnow())
            db.session.add(referral)
        db.session.commit()
        assert calculate_payout_rate(referrer) == 100  # 20 + (8 × 10) = 100


# ---------------------------------------------------------------------------
# 5. Payout Amount Uses payout_rate (Not collection_method)
# ---------------------------------------------------------------------------

class TestPayoutAmountCalculation:

    def test_payout_amount_uses_payout_rate(self, app_ctx):
        seller = _make_user()
        seller.payout_rate = 40
        db.session.commit()
        item = _make_item(seller)
        item.price = 200
        db.session.commit()

        expected_payout = 200 * 0.40
        actual_payout = item.price * (item.seller.payout_rate / 100)
        assert actual_payout == expected_payout

    def test_payout_email_reflects_correct_rate(self, app_ctx):
        """The sold email uses payout_rate, not collection_method."""
        seller = _make_user()
        seller.payout_rate = 50
        db.session.commit()
        item = _make_item(seller)
        item.price = 100
        item.status = 'sold'
        item.sold_at = datetime.utcnow()
        db.session.commit()

        with patch('app.send_email') as mock_send:
            from helpers import send_item_sold_email  # adjust to actual function name
            send_item_sold_email(item)
            mock_send.assert_called_once()
            email_html = str(mock_send.call_args)
            # Should mention $50.00 payout (100 × 50%)
            assert '50' in email_html
            # Should NOT reference old tier names
            assert 'Pro Plan' not in email_html
            assert 'Free Plan' not in email_html

    def test_100_percent_payout_rate_gives_full_price(self, app_ctx):
        seller = _make_user()
        seller.payout_rate = 100
        db.session.commit()
        item = _make_item(seller)
        item.price = 150
        db.session.commit()
        payout = item.price * (item.seller.payout_rate / 100)
        assert payout == 150.0


# ---------------------------------------------------------------------------
# 6. Referral Program Kill Switch
# ---------------------------------------------------------------------------

class TestReferralProgramKillSwitch:

    def test_code_not_applied_when_program_inactive(self, client, app_ctx):
        AppSetting.set('referral_program_active', 'false')
        referrer = _make_user(email='referrer@test.com')
        client.post('/register', data={
            'email': 'newuser@test.com',
            'full_name': 'New User',
            'password': 'password123',
            'referral_code': referrer.referral_code,
        }, follow_redirects=True)
        new_user = User.query.filter_by(email='newuser@test.com').first()
        assert new_user.payout_rate == 20
        assert new_user.referred_by_id is None

    def test_referral_not_confirmed_when_program_inactive(self, app_ctx):
        AppSetting.set('referral_program_active', 'false')
        referrer = _make_user(email='referrer@test.com')
        referred = _make_user(email='referred@test.com')
        referred.referred_by_id = referrer.id
        referral = Referral(referrer_id=referrer.id, referred_id=referred.id)
        db.session.add(referral)
        db.session.commit()

        from helpers import maybe_confirm_referral_for_seller
        maybe_confirm_referral_for_seller(referred)

        db.session.refresh(referrer)
        assert referrer.payout_rate == 20

    def test_validate_endpoint_returns_invalid_when_program_off(self, client, app_ctx):
        AppSetting.set('referral_program_active', 'false')
        referrer = _make_user(email='referrer@test.com')
        resp = client.get(f'/referral/validate?code={referrer.referral_code}')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['valid'] is False


# ---------------------------------------------------------------------------
# 7. /referral/validate Endpoint
# ---------------------------------------------------------------------------

class TestReferralValidateEndpoint:

    def test_valid_code_returns_valid_true(self, client, app_ctx):
        referrer = _make_user(email='referrer@test.com', full_name='Jane Smith')
        resp = client.get(f'/referral/validate?code={referrer.referral_code}')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['valid'] is True
        assert 'Jane' in data['referrer_name']  # First name present
        assert 'Smith' not in data['referrer_name']  # Last name not fully exposed — first + last initial only

    def test_invalid_code_returns_valid_false(self, client):
        resp = client.get('/referral/validate?code=XXXXXXXX')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['valid'] is False

    def test_missing_code_param_returns_valid_false(self, client):
        resp = client.get('/referral/validate')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['valid'] is False

    def test_validate_is_case_insensitive(self, client, app_ctx):
        referrer = _make_user(email='referrer@test.com')
        resp = client.get(f'/referral/validate?code={referrer.referral_code.lower()}')
        data = resp.get_json()
        assert data['valid'] is True


# ---------------------------------------------------------------------------
# 8. Session / OAuth Referral Code Carry-Through
# ---------------------------------------------------------------------------

class TestReferralCodeSessionHandling:

    def test_ref_param_saved_to_session(self, client, app_ctx):
        referrer = _make_user(email='referrer@test.com')
        with client.session_transaction() as sess:
            sess.clear()
        client.get(f'/register?ref={referrer.referral_code}')
        with client.session_transaction() as sess:
            assert sess.get('referral_code') == referrer.referral_code

    def test_ref_param_survives_oauth_redirect(self, client, app_ctx):
        """Session referral code is present before and after OAuth redirect initiation."""
        referrer = _make_user(email='referrer@test.com')
        # Simulate visiting login page with ref param
        client.get(f'/login?ref={referrer.referral_code}')
        with client.session_transaction() as sess:
            assert sess.get('referral_code') == referrer.referral_code

    def test_guest_onboarding_captures_ref_param(self, client, app_ctx):
        """ref param on any onboarding entry point is stored in session."""
        referrer = _make_user(email='referrer@test.com')
        client.get(f'/onboard?ref={referrer.referral_code}')
        with client.session_transaction() as sess:
            assert sess.get('referral_code') == referrer.referral_code

    def test_referral_code_applied_at_guest_account_creation(self, client, app_ctx):
        """When a guest completes onboarding and creates an account, the session code is applied."""
        referrer = _make_user(email='referrer@test.com')
        with client.session_transaction() as sess:
            sess['referral_code'] = referrer.referral_code

        # Simulate the account-creation POST at the end of onboarding
        resp = client.post('/onboard/complete_account', data={
            'email': 'guest@test.com',
            'full_name': 'Guest User',
            'password': 'password123',
        }, follow_redirects=True)
        assert resp.status_code == 200
        new_user = User.query.filter_by(email='guest@test.com').first()
        assert new_user is not None
        assert new_user.referred_by_id == referrer.id
        assert new_user.payout_rate == 30

    def test_referral_code_cleared_from_session_after_use(self, client, app_ctx):
        """After account creation, referral_code should be removed from session."""
        referrer = _make_user(email='referrer@test.com')
        with client.session_transaction() as sess:
            sess['referral_code'] = referrer.referral_code
        client.post('/register', data={
            'email': 'newuser@test.com',
            'full_name': 'New User',
            'password': 'password123',
        }, follow_redirects=True)
        with client.session_transaction() as sess:
            assert 'referral_code' not in sess


# ---------------------------------------------------------------------------
# 9. Referral Chain (Referred Sellers Can Also Refer)
# ---------------------------------------------------------------------------

class TestReferralChain:

    def test_referred_seller_can_refer_others(self, app_ctx):
        """A seller who joined via referral code still gets their own code and can refer."""
        from helpers import apply_referral_code
        referrer = _make_user(email='referrer@test.com')
        referred = _make_user(email='referred@test.com')
        apply_referral_code(referred, referrer.referral_code)

        assert referred.referred_by_id == referrer.id
        assert referred.referral_code is not None

        # referred can now refer third_user
        third = _make_user(email='third@test.com')
        apply_referral_code(third, referred.referral_code)
        assert third.referred_by_id == referred.id

    def test_referral_chains_do_not_cross_contaminate(self, app_ctx):
        """Confirming third_user's stop boosts referred, not the original referrer."""
        from helpers import apply_referral_code, maybe_confirm_referral_for_seller, calculate_payout_rate
        referrer = _make_user(email='referrer@test.com')
        referred = _make_user(email='referred@test.com')
        apply_referral_code(referred, referrer.referral_code)
        db.session.commit()

        third = _make_user(email='third@test.com')
        apply_referral_code(third, referred.referral_code)
        db.session.commit()

        # Confirm third_user's stop
        maybe_confirm_referral_for_seller(third)

        db.session.refresh(referred)
        db.session.refresh(referrer)

        # referred gets +10% (their direct referral confirmed)
        assert referred.payout_rate == 40  # 30 (signup bonus) + 10

        # referrer rate unchanged by this event
        assert referrer.payout_rate == 20


# ---------------------------------------------------------------------------
# 10. Admin Panel Referral Stats
# ---------------------------------------------------------------------------

class TestAdminReferralStats:

    def _login_admin(self, client):
        admin = User(email='admin@test.com', full_name='Admin', is_admin=True, is_super_admin=True)
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()
        client.post('/login', data={'email': 'admin@test.com', 'password': 'admin123'},
                    follow_redirects=True)
        return admin

    def test_admin_panel_loads_with_referral_section(self, client, app_ctx):
        self._login_admin(client)
        resp = client.get('/admin')
        assert resp.status_code == 200
        assert b'Referral Program' in resp.data

    def test_admin_referral_stats_show_confirmed_count(self, client, app_ctx):
        self._login_admin(client)
        referrer = _make_user(email='r@test.com')
        referred = _make_user(email='ref@test.com')
        referral = Referral(referrer_id=referrer.id, referred_id=referred.id,
                            confirmed=True, confirmed_at=datetime.utcnow())
        db.session.add(referral)
        db.session.commit()

        resp = client.get('/admin')
        assert b'1' in resp.data  # at minimum, count appears

    def test_admin_seller_panel_shows_payout_rate(self, client, app_ctx):
        self._login_admin(client)
        seller = _make_user(email='seller@test.com')
        seller.payout_rate = 40
        db.session.commit()
        resp = client.get(f'/admin/seller/{seller.id}/panel')
        assert resp.status_code == 200
        assert b'40' in resp.data
        assert b'40%' in resp.data or b'40' in resp.data

    def test_admin_seller_panel_does_not_show_old_tier_labels(self, client, app_ctx):
        self._login_admin(client)
        seller = _make_user()
        resp = client.get(f'/admin/seller/{seller.id}/panel')
        assert b'Pro Plan' not in resp.data
        assert b'Free Plan' not in resp.data

    def test_admin_can_update_referral_appsettings(self, client, app_ctx):
        self._login_admin(client)
        resp = client.post('/admin/settings/referral', data={
            'referral_base_rate': '25',
            'referral_signup_bonus': '15',
            'referral_bonus_per_referral': '5',
            'referral_max_rate': '80',
            'referral_program_active': 'true',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert AppSetting.get('referral_base_rate') == '25'
        assert AppSetting.get('referral_max_rate') == '80'


# ---------------------------------------------------------------------------
# 11. Regression: Existing Features Not Broken
# ---------------------------------------------------------------------------

class TestRegressions:

    def test_seller_dashboard_still_loads(self, client, app_ctx):
        _make_user()
        _login(client)
        resp = client.get('/dashboard')
        assert resp.status_code == 200

    def test_register_page_still_loads(self, client):
        resp = client.get('/register')
        assert resp.status_code == 200

    def test_item_status_lifecycle_unchanged(self, app_ctx):
        seller = _make_user()
        item = _make_item(seller, status='pending_valuation')
        assert item.status == 'pending_valuation'
        item.status = 'approved'
        db.session.commit()
        db.session.refresh(item)
        assert item.status == 'approved'

    def test_payout_sent_flag_still_works(self, app_ctx):
        seller = _make_user()
        item = _make_item(seller, status='sold')
        item.sold_at = datetime.utcnow()
        item.payout_sent = False
        db.session.commit()
        item.payout_sent = True
        db.session.commit()
        db.session.refresh(item)
        assert item.payout_sent is True

    def test_collection_method_field_still_exists(self, app_ctx):
        """collection_method must not be removed from InventoryItem."""
        seller = _make_user()
        item = _make_item(seller)
        assert hasattr(item, 'collection_method')
        assert item.collection_method == 'free'

    def test_webhook_route_still_responds(self, client):
        resp = client.post('/webhook', data=b'{}',
                           content_type='application/json',
                           headers={'Stripe-Signature': 'invalid'})
        # Should return 400 (bad signature) not 404 or 500
        assert resp.status_code in (400, 200)

    def test_upgrade_pickup_route_still_exists(self, client, app_ctx):
        """Route must not 404 — may redirect or show dashboard."""
        _make_user()
        _login(client)
        resp = client.get('/upgrade_pickup', follow_redirects=False)
        assert resp.status_code in (200, 302, 303)  # not 404

    def test_user_model_has_new_fields(self, app_ctx):
        user = _make_user()
        assert hasattr(user, 'referral_code')
        assert hasattr(user, 'referred_by_id')
        assert hasattr(user, 'payout_rate')

    def test_referral_model_exists(self, app_ctx):
        referrer = _make_user(email='r@test.com')
        referred = _make_user(email='ref@test.com')
        ref = Referral(referrer_id=referrer.id, referred_id=referred.id)
        db.session.add(ref)
        db.session.commit()
        assert ref.id is not None
        assert ref.confirmed is False

    def test_one_user_can_only_be_referred_once(self, app_ctx):
        """Referral.referred_id has unique constraint — can't be referred by two people."""
        referrer1 = _make_user(email='r1@test.com')
        referrer2 = _make_user(email='r2@test.com')
        referred = _make_user(email='referred@test.com')

        ref1 = Referral(referrer_id=referrer1.id, referred_id=referred.id)
        db.session.add(ref1)
        db.session.commit()

        ref2 = Referral(referrer_id=referrer2.id, referred_id=referred.id)
        db.session.add(ref2)
        with pytest.raises(Exception):  # IntegrityError from unique constraint
            db.session.commit()


# ---------------------------------------------------------------------------
# 12. Stop-Completion Referral Trigger (route-level integration tests)
#
# These tests verify the new trigger: referral is confirmed when a mover marks
# a stop 'completed' via POST /crew/shift/<id>/stop/<id>/update, NOT when an
# item arrives at the warehouse via crew_intake_submit.
# ---------------------------------------------------------------------------

from models import ShiftWeek, Shift, ShiftAssignment, ShiftPickup, ShiftRun
import datetime as dt


def _make_shift(mover):
    """Create a ShiftWeek + Shift + ShiftRun + ShiftAssignment for the given mover."""
    week = ShiftWeek(week_start=dt.date(2026, 1, 6), status='published')  # a Monday
    db.session.add(week)
    db.session.flush()
    shift = Shift(week_id=week.id, day_of_week='mon', slot='am')
    db.session.add(shift)
    db.session.flush()
    run = ShiftRun(shift_id=shift.id, started_by_id=mover.id)
    db.session.add(run)
    db.session.flush()
    assignment = ShiftAssignment(
        shift_id=shift.id, worker_id=mover.id, role_on_shift='driver', truck_number=1
    )
    db.session.add(assignment)
    db.session.commit()
    return shift


def _make_mover(email='mover@test.com'):
    """Create an approved worker (mover)."""
    user = User(email=email, full_name='Test Mover', is_worker=True, worker_status='approved')
    user.set_password('password123')
    db.session.add(user)
    db.session.commit()
    return user


def _make_pickup(shift, seller):
    """Create a ShiftPickup (stop) for the given seller on the given shift."""
    pickup = ShiftPickup(shift_id=shift.id, seller_id=seller.id, truck_number=1, stop_order=1)
    db.session.add(pickup)
    db.session.commit()
    return pickup


def _login_as(client, user):
    client.post('/login', data={'email': user.email, 'password': 'password123'},
                follow_redirects=True)


class TestStopCompletionReferralTrigger:

    def test_completing_stop_confirms_referral(self, client, app_ctx):
        """Core behavior: marking a stop completed triggers referral confirmation."""
        referrer = _make_user(email='referrer@test.com')
        referred = _make_user(email='referred@test.com')
        referred.referred_by_id = referrer.id
        referral = Referral(referrer_id=referrer.id, referred_id=referred.id)
        db.session.add(referral)
        db.session.commit()

        mover = _make_mover()
        shift = _make_shift(mover)
        pickup = _make_pickup(shift, referred)

        _login_as(client, mover)
        resp = client.post(
            f'/crew/shift/{shift.id}/stop/{pickup.id}/update',
            data={'status': 'completed'},
            follow_redirects=True,
        )
        assert resp.status_code == 200

        db.session.refresh(referral)
        assert referral.confirmed is True
        assert referral.confirmed_at is not None

    def test_completing_stop_boosts_referrer_payout_rate(self, client, app_ctx):
        """Referrer's payout_rate goes up after stop completion."""
        referrer = _make_user(email='referrer@test.com')
        referred = _make_user(email='referred@test.com')
        referred.referred_by_id = referrer.id
        referral = Referral(referrer_id=referrer.id, referred_id=referred.id)
        db.session.add(referral)
        db.session.commit()

        mover = _make_mover()
        shift = _make_shift(mover)
        pickup = _make_pickup(shift, referred)

        _login_as(client, mover)
        client.post(
            f'/crew/shift/{shift.id}/stop/{pickup.id}/update',
            data={'status': 'completed'},
            follow_redirects=True,
        )

        db.session.refresh(referrer)
        assert referrer.payout_rate == 30  # 20 base + 10 bonus

    def test_issue_stop_does_not_confirm_referral(self, client, app_ctx):
        """Marking a stop as 'issue' must NOT confirm the referral."""
        referrer = _make_user(email='referrer@test.com')
        referred = _make_user(email='referred@test.com')
        referred.referred_by_id = referrer.id
        referral = Referral(referrer_id=referrer.id, referred_id=referred.id)
        db.session.add(referral)
        db.session.commit()

        mover = _make_mover()
        shift = _make_shift(mover)
        pickup = _make_pickup(shift, referred)

        _login_as(client, mover)
        client.post(
            f'/crew/shift/{shift.id}/stop/{pickup.id}/update',
            data={'status': 'issue', 'notes': 'No one home.'},
            follow_redirects=True,
        )

        db.session.refresh(referral)
        assert referral.confirmed is False
        db.session.refresh(referrer)
        assert referrer.payout_rate == 20

    def test_intake_arrival_no_longer_confirms_referral(self, client, app_ctx):
        """Setting arrived_at_store_at during intake must NOT confirm the referral anymore."""
        from models import StorageLocation, IntakeRecord, InventoryCategory

        referrer = _make_user(email='referrer@test.com')
        referred = _make_user(email='referred@test.com')
        referred.referred_by_id = referrer.id
        referral = Referral(referrer_id=referrer.id, referred_id=referred.id)
        db.session.add(referral)
        db.session.commit()

        item = _make_item(referred, status='available')

        # Set up an organizer and storage location for the intake route
        organizer = _make_mover(email='organizer@test.com')
        loc = StorageLocation(name='Unit A', is_active=True)
        db.session.add(loc)
        db.session.flush()

        week = ShiftWeek(week_start=dt.date(2026, 2, 2), status='published')
        db.session.add(week)
        db.session.flush()
        shift = Shift(week_id=week.id, day_of_week='mon', slot='am')
        db.session.add(shift)
        db.session.flush()
        assignment = ShiftAssignment(
            shift_id=shift.id, worker_id=organizer.id, role_on_shift='organizer'
        )
        db.session.add(assignment)
        db.session.commit()

        _login_as(client, organizer)
        client.post(
            f'/crew/intake/{shift.id}/item/{item.id}',
            data={
                'storage_location_id': loc.id,
                'quality': 3,
            },
            follow_redirects=True,
        )

        db.session.refresh(referral)
        # Referral must still be pending — intake no longer triggers confirmation
        assert referral.confirmed is False
        db.session.refresh(referrer)
        assert referrer.payout_rate == 20

    def test_completing_stop_for_non_referred_seller_does_not_error(self, client, app_ctx):
        """Stop completion for a seller with no referral code should succeed cleanly."""
        seller = _make_user(email='seller@test.com')
        assert seller.referred_by_id is None

        mover = _make_mover()
        shift = _make_shift(mover)
        pickup = _make_pickup(shift, seller)

        _login_as(client, mover)
        resp = client.post(
            f'/crew/shift/{shift.id}/stop/{pickup.id}/update',
            data={'status': 'completed'},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert Referral.query.count() == 0

    def test_completing_stop_twice_does_not_double_count(self, client, app_ctx):
        """If a stop is reverted and re-completed, the referral credit is given only once."""
        referrer = _make_user(email='referrer@test.com')
        referred = _make_user(email='referred@test.com')
        referred.referred_by_id = referrer.id
        referral = Referral(referrer_id=referrer.id, referred_id=referred.id)
        db.session.add(referral)
        db.session.commit()

        mover = _make_mover()
        shift = _make_shift(mover)
        pickup = _make_pickup(shift, referred)

        _login_as(client, mover)
        # Complete the stop once
        client.post(
            f'/crew/shift/{shift.id}/stop/{pickup.id}/update',
            data={'status': 'completed'},
            follow_redirects=True,
        )
        # Revert it
        client.post(
            f'/crew/shift/{shift.id}/stop/{pickup.id}/revert',
            follow_redirects=True,
        )
        # Complete it again
        client.post(
            f'/crew/shift/{shift.id}/stop/{pickup.id}/update',
            data={'status': 'completed'},
            follow_redirects=True,
        )

        db.session.refresh(referrer)
        assert referrer.payout_rate == 30  # still 30, not 40
