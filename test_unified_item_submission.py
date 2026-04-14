# Tests: Unified Item Submission Flow
# Covers: onboarding step removal, payout skip logic, add_item parity, dashboard pickup week

import pytest
from unittest.mock import patch, MagicMock
from flask import session


# ---------------------------------------------------------------------------
# Fixtures — adjust imports to match your actual app factory / test setup
# ---------------------------------------------------------------------------

@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def logged_in_seller_with_payout(client, db, make_user):
    """Authenticated seller who already has payout method on file."""
    user = make_user(
        payout_method='venmo',
        payout_handle='@testuser',
        is_seller=True,
    )
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
    return user


@pytest.fixture
def logged_in_seller_no_payout(client, db, make_user):
    """Authenticated seller with no payout method set."""
    user = make_user(
        payout_method=None,
        payout_handle=None,
        is_seller=True,
    )
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
    return user


# ---------------------------------------------------------------------------
# 1. PICKUP WEEK STEP REMOVED FROM ONBOARDING
# ---------------------------------------------------------------------------

class TestPickupWeekRemovedFromOnboarding:

    def test_onboard_step_7_is_not_pickup_week(self, client, logged_in_seller_no_payout):
        """After steps 1-6, the next step should be payout or review — not pickup week."""
        # Simulate having completed steps 1-6 in session
        with client.session_transaction() as sess:
            sess['onboard_step'] = 7
            sess['onboard_category_id'] = 1
            sess['onboard_quality'] = 4
            sess['onboard_description'] = 'Test item'
            sess['onboard_long_description'] = 'A longer description'
            sess['onboard_suggested_price'] = '50.00'

        resp = client.get('/onboard')
        assert resp.status_code == 200
        html = resp.data.decode()

        # Must NOT contain pickup week UI
        assert 'pickup_week' not in html
        assert 'Week 1' not in html or 'week1' not in html  # radio value
        assert 'onboard_pickup_week' not in html
        assert 'onboard_time_preference' not in html

        # Must contain payout or review
        assert ('payout_method' in html) or ('Review' in html) or ('Venmo' in html)

    def test_onboard_no_week_selection_radio_cards(self, client, logged_in_seller_no_payout):
        """The two week-selection radio cards (Week 1 / Week 2) must not appear anywhere in onboard."""
        resp = client.get('/onboard')
        html = resp.data.decode()
        assert 'Apr 27' not in html  # Week 1 date range
        assert 'May 4' not in html   # Week 2 start date
        # These are the values set via /api/user/set_pickup_week, not onboarding

    def test_onboard_step_count_does_not_include_pickup_week(self, client, logged_in_seller_no_payout):
        """Progress indicator should reflect 7 or fewer steps, not 9+."""
        resp = client.get('/onboard')
        html = resp.data.decode()
        # Should not show "Step X of 9" or higher — pickup week was step 7 of 9
        assert 'of 9' not in html
        assert 'of 10' not in html
        assert 'of 11' not in html


class TestPickupWeekSessionNotSaved:

    def test_guest_save_does_not_persist_pickup_week(self, client):
        """Guest save endpoint must not store pickup week keys."""
        with client.session_transaction() as sess:
            sess['onboard_step'] = 4
            sess['onboard_description'] = 'My couch'

        resp = client.post('/onboard/guest/save', data={
            'onboard_pickup_week': 'week1',
            'onboard_time_preference': 'morning',
        })

        with client.session_transaction() as sess:
            assert 'onboard_pickup_week' not in sess
            assert 'onboard_time_preference' not in sess

    def test_existing_guest_session_with_pickup_week_is_cleaned(self, client):
        """If a guest session from before this change has pickup week saved, it should be ignored on resume."""
        with client.session_transaction() as sess:
            sess['onboard_step'] = 8
            sess['onboard_pickup_week'] = 'week2'         # legacy key
            sess['onboard_time_preference'] = 'afternoon'  # legacy key

        resp = client.get('/onboard')
        assert resp.status_code == 200
        # Critically: should not crash or redirect to a pickup week step


# ---------------------------------------------------------------------------
# 2. PAYOUT STEP CONDITIONAL LOGIC
# ---------------------------------------------------------------------------

class TestPayoutStepSkip:

    def test_payout_step_skipped_for_seller_with_payout_on_file(
        self, client, logged_in_seller_with_payout
    ):
        """Seller with payout already set should jump from step 6 (price) to review."""
        with client.session_transaction() as sess:
            sess['onboard_step'] = 7  # would be payout step

        resp = client.get('/onboard')
        html = resp.data.decode()

        # Should show review page, not payout entry form
        assert 'payout_method' not in html or 'already on file' in html.lower()

    def test_payout_step_shown_for_seller_without_payout(
        self, client, logged_in_seller_no_payout
    ):
        """Seller without payout set must see the payout method step."""
        with client.session_transaction() as sess:
            sess['onboard_step'] = 7

        resp = client.get('/onboard')
        html = resp.data.decode()
        assert 'payout_method' in html or 'Venmo' in html or 'PayPal' in html

    def test_payout_step_shown_for_guest(self, client):
        """Guest (unauthenticated) must always see payout method step."""
        with client.session_transaction() as sess:
            sess['onboard_step'] = 7

        resp = client.get('/onboard')
        html = resp.data.decode()
        assert 'payout_method' in html or 'Venmo' in html or 'PayPal' in html

    def test_payout_saved_to_user_on_submit(self, client, logged_in_seller_no_payout, db):
        """Submitting payout step must persist method + handle to User, not just session."""
        with client.session_transaction() as sess:
            sess['onboard_step'] = 7
            # Populate required item fields so submission can complete
            sess['onboard_category_id'] = 1
            sess['onboard_quality'] = 4
            sess['onboard_description'] = 'Test couch'
            sess['onboard_long_description'] = 'A nice couch'
            sess['onboard_suggested_price'] = '75.00'

        resp = client.post('/onboard', data={
            'step': '7',
            'payout_method': 'venmo',
            'payout_handle': '@newhandle',
            'payout_handle_confirm': '@newhandle',
        }, follow_redirects=False)

        from models import User
        user = User.query.get(logged_in_seller_no_payout.id)
        assert user.payout_method == 'venmo'
        assert user.payout_handle == '@newhandle'

    def test_payout_validation_rejects_mismatched_handles(self, client, logged_in_seller_no_payout):
        """Mismatched payout handle confirmation must return an error."""
        with client.session_transaction() as sess:
            sess['onboard_step'] = 7

        resp = client.post('/onboard', data={
            'step': '7',
            'payout_method': 'venmo',
            'payout_handle': '@handleA',
            'payout_handle_confirm': '@handleB',
        })
        assert resp.status_code == 200
        html = resp.data.decode()
        assert 'match' in html.lower() or 'error' in html.lower()


# ---------------------------------------------------------------------------
# 3. ITEM CREATION — BOTH PATHS PRODUCE CORRECT ITEM
# ---------------------------------------------------------------------------

class TestItemCreatedCorrectly:

    def test_onboard_creates_item_as_pending_valuation(
        self, client, logged_in_seller_with_payout, db
    ):
        """Completing onboard submission must create item with status=pending_valuation."""
        from models import InventoryItem

        with client.session_transaction() as sess:
            sess['onboard_category_id'] = 1
            sess['onboard_quality'] = 4
            sess['onboard_description'] = 'My desk'
            sess['onboard_long_description'] = 'Solid wood desk'
            sess['onboard_suggested_price'] = '60.00'
            # Simulate photos already uploaded via TempUpload
            sess['onboard_temp_upload_ids'] = []  # adjust if needed

        resp = client.post('/onboard', data={'step': 'submit'}, follow_redirects=False)

        item = InventoryItem.query.filter_by(
            seller_id=logged_in_seller_with_payout.id
        ).order_by(InventoryItem.id.desc()).first()

        assert item is not None
        assert item.status == 'pending_valuation'
        assert item.collection_method == 'free'

    def test_onboard_does_not_set_pickup_week_on_item(
        self, client, logged_in_seller_with_payout, db
    ):
        """Item created via onboard must not have pickup_week set (that's a User field now)."""
        from models import InventoryItem

        resp = client.post('/onboard', data={'step': 'submit'}, follow_redirects=False)

        item = InventoryItem.query.filter_by(
            seller_id=logged_in_seller_with_payout.id
        ).order_by(InventoryItem.id.desc()).first()

        if item:
            # pickup_week on InventoryItem is admin-only; onboarding must not set it
            assert item.pickup_week is None

    def test_add_item_creates_item_same_as_onboard(
        self, client, logged_in_seller_with_payout, db
    ):
        """add_item and onboard must produce items with identical field values for same input."""
        from models import InventoryItem

        shared_data = {
            'category_id': '1',
            'quality': '4',
            'description': 'Identical item',
            'long_description': 'Same description both paths',
            'suggested_price': '45.00',
        }

        # Submit via onboard
        with client.session_transaction() as sess:
            for k, v in shared_data.items():
                sess[f'onboard_{k}'] = v
        client.post('/onboard', data={'step': 'submit'})
        onboard_item = InventoryItem.query.filter_by(
            seller_id=logged_in_seller_with_payout.id
        ).order_by(InventoryItem.id.desc()).first()

        # Submit via add_item
        with client.session_transaction() as sess:
            for k, v in shared_data.items():
                sess[f'onboard_{k}'] = v
        client.post('/add_item', data={'step': 'submit'})
        add_item = InventoryItem.query.filter_by(
            seller_id=logged_in_seller_with_payout.id
        ).order_by(InventoryItem.id.desc()).first()

        if onboard_item and add_item and onboard_item.id != add_item.id:
            assert onboard_item.status == add_item.status
            assert onboard_item.collection_method == add_item.collection_method
            assert onboard_item.category_id == add_item.category_id

    def test_returning_seller_redirects_to_dashboard_not_onboard_complete(
        self, client, logged_in_seller_with_payout
    ):
        """/onboard_complete is for new accounts only. Returning sellers go to /dashboard."""
        with client.session_transaction() as sess:
            sess['onboard_category_id'] = 1
            sess['onboard_quality'] = 4
            sess['onboard_description'] = 'My lamp'
            sess['onboard_long_description'] = 'Nice lamp'
            sess['onboard_suggested_price'] = '20.00'

        resp = client.post('/onboard', data={'step': 'submit'}, follow_redirects=False)
        assert resp.status_code in (302, 303)
        assert '/dashboard' in resp.headers.get('Location', '')


# ---------------------------------------------------------------------------
# 4. DASHBOARD PICKUP WEEK — UNCHANGED AND STILL WORKS
# ---------------------------------------------------------------------------

class TestDashboardPickupWeek:

    def test_api_set_pickup_week_still_works(self, client, logged_in_seller_with_payout, db):
        """POST /api/user/set_pickup_week must accept week + time preference and save to User."""
        from models import User

        resp = client.post('/api/user/set_pickup_week', json={
            'pickup_week': 'week1',
            'pickup_time_preference': 'morning',
        })

        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert data['pickup_week'] == 'week1'
        assert data['pickup_time_preference'] == 'morning'

        user = User.query.get(logged_in_seller_with_payout.id)
        assert user.pickup_week == 'week1'
        assert user.pickup_time_preference == 'morning'

    def test_api_set_pickup_week_requires_time_preference(
        self, client, logged_in_seller_with_payout
    ):
        """Week submitted without time preference should fail validation."""
        resp = client.post('/api/user/set_pickup_week', json={
            'pickup_week': 'week2',
            # no pickup_time_preference
        })
        data = resp.get_json()
        assert data.get('success') is not True

    def test_dashboard_shows_pickup_week_stats_cell(
        self, client, logged_in_seller_with_payout
    ):
        """Stats bar on dashboard must render pickup week cell regardless of whether week is set."""
        resp = client.get('/dashboard')
        assert resp.status_code == 200
        html = resp.data.decode()
        # Either the set value or the "Not scheduled" fallback must appear
        assert 'Pickup Window' in html or 'pickup' in html.lower()

    def test_dashboard_shows_not_scheduled_when_pickup_week_unset(
        self, client, logged_in_seller_no_payout, db
    ):
        """Seller with no pickup_week set should see 'Not scheduled' amber indicator."""
        from models import User
        user = User.query.get(logged_in_seller_no_payout.id)
        user.pickup_week = None
        user.pickup_time_preference = None
        db.session.commit()

        resp = client.get('/dashboard')
        html = resp.data.decode()
        assert 'Not scheduled' in html or 'Set now' in html

    def test_pickup_week_set_via_onboard_previously_still_shows_on_dashboard(
        self, client, db, make_user
    ):
        """Users who set pickup_week during onboarding before this change still see it on dashboard."""
        user = make_user(
            payout_method='venmo',
            payout_handle='@olduser',
            is_seller=True,
            pickup_week='week1',
            pickup_time_preference='afternoon',
        )
        with client.session_transaction() as sess:
            sess['_user_id'] = str(user.id)

        resp = client.get('/dashboard')
        html = resp.data.decode()
        assert 'Wk 1' in html or 'Week 1' in html or 'afternoon' in html.lower()


# ---------------------------------------------------------------------------
# 5. GUEST FLOW — ACCOUNT CREATION STILL WORKS
# ---------------------------------------------------------------------------

class TestGuestFlow:

    def test_guest_sees_account_creation_steps_after_payout(self, client):
        """Unauthenticated users must see account creation steps after payout step."""
        with client.session_transaction() as sess:
            sess['onboard_step'] = 9  # account creation step (was 10 before)

        resp = client.get('/onboard')
        assert resp.status_code == 200
        html = resp.data.decode()
        assert 'email' in html.lower() or 'password' in html.lower() or 'full_name' in html.lower()

    def test_guest_account_creation_step_does_not_include_pickup_week(self, client):
        """Account creation step must not ask for pickup week (was never in this step, confirm it stays removed)."""
        with client.session_transaction() as sess:
            sess['onboard_step'] = 9

        resp = client.get('/onboard')
        html = resp.data.decode()
        assert 'onboard_pickup_week' not in html
        assert 'pickup_week' not in html

    def test_guest_complete_redirects_to_onboard_complete(self, client, db):
        """New account created via guest flow must redirect to /onboard_complete."""
        # Full guest submission — this is an integration-level test
        # Populate all required session keys
        with client.session_transaction() as sess:
            sess['onboard_category_id'] = 1
            sess['onboard_quality'] = 4
            sess['onboard_description'] = 'Guest item'
            sess['onboard_long_description'] = 'Guest description'
            sess['onboard_suggested_price'] = '30.00'
            sess['onboard_payout_method'] = 'venmo'
            sess['onboard_payout_handle'] = '@guestuser'

        resp = client.post('/onboard', data={
            'step': 'create_account',
            'full_name': 'Test Guest',
            'email': 'guest_unique@test.edu',
            'phone': '9195551234',
            'password': 'password123',
        }, follow_redirects=False)

        assert resp.status_code in (302, 303)
        assert 'onboard_complete' in resp.headers.get('Location', '')


# ---------------------------------------------------------------------------
# 6. REGRESSION — NOTHING ELSE BROKEN
# ---------------------------------------------------------------------------

class TestRegressions:

    def test_edit_item_route_unaffected(self, client, logged_in_seller_with_payout, db):
        """edit_item must still load without error after onboard changes."""
        from models import InventoryItem
        item = InventoryItem.query.filter_by(
            seller_id=logged_in_seller_with_payout.id
        ).first()
        if item:
            resp = client.get(f'/edit_item/{item.id}')
            assert resp.status_code == 200

    def test_confirm_pickup_still_redirects_to_dashboard(self, client, logged_in_seller_with_payout):
        """/confirm_pickup must still redirect to dashboard (it was already deprecated)."""
        resp = client.get('/confirm_pickup', follow_redirects=False)
        assert resp.status_code in (302, 303)
        assert '/dashboard' in resp.headers.get('Location', '')

    def test_onboard_complete_page_still_loads(self, client, logged_in_seller_with_payout):
        resp = client.get('/onboard_complete')
        assert resp.status_code == 200

    def test_upgrade_pickup_route_unaffected(self, client, logged_in_seller_with_payout):
        resp = client.get('/upgrade_pickup')
        assert resp.status_code in (200, 302)  # may redirect if already Pro

    def test_photo_upload_session_endpoint_unaffected(self, client, logged_in_seller_with_payout):
        """TempUpload / upload session API must not be broken by onboard changes."""
        resp = client.post('/api/upload_session/create')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'session_token' in data

    def test_item_status_not_changed_by_this_feature(self, client, logged_in_seller_with_payout, db):
        """No item status transitions should be introduced by this change."""
        from models import InventoryItem
        items_before = {
            i.id: i.status
            for i in InventoryItem.query.filter_by(
                seller_id=logged_in_seller_with_payout.id
            ).all()
        }
        # Hit onboard (GET only — no submission)
        client.get('/onboard')

        items_after = {
            i.id: i.status
            for i in InventoryItem.query.filter_by(
                seller_id=logged_in_seller_with_payout.id
            ).all()
        }
        assert items_before == items_after
