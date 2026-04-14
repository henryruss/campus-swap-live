"""
Tests for Spec #7 — Seller Progress Tracker

Covers:
- _compute_seller_tracker() stage logic (all 6 stages, active/completed/upcoming states)
- Interrupt detection (needs_info item, pickup issue)
- Edge cases: only rejected items, all items needs_info, pickup issue vs. completed
- One ShiftPickup query per call (not per item)
- setup_complete computation in dashboard route (requires payout_handle)
- tracker=None when setup incomplete
- Dashboard route passes setup_complete and tracker to template
- Setup strip and tracker are mutually exclusive (never both rendered)
- Regression: dashboard still loads; existing seller data unaffected
"""

import pytest
from datetime import datetime


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def seller(app, db):
    """A fully-configured seller (setup_complete=True)."""
    from models import User
    u = User(
        email='seller@test.com',
        full_name='Test Seller',
        is_seller=True,
        phone='9195551234',
        pickup_week='week1',
        pickup_location_type='on_campus',
        pickup_dorm='Morrison',
        pickup_room='101',
        pickup_access_type='elevator',
        pickup_floor=1,
        payout_method='venmo',
        payout_handle='@testseller',
    )
    u.set_password('password')
    db.session.add(u)
    db.session.commit()
    return u


@pytest.fixture
def seller_client(client, seller):
    client.post('/login', data={'email': seller.email, 'password': 'password'})
    return client


@pytest.fixture
def category(app, db):
    from models import InventoryCategory
    cat = InventoryCategory(name='Chair', default_unit_size=1.0)
    db.session.add(cat)
    db.session.commit()
    return cat


def make_item(db, seller, status='available', picked_up_at=None,
              arrived_at_store_at=None, category=None):
    from models import InventoryItem
    item = InventoryItem(
        description='Test Item',
        price=50.0,
        quality=3,
        status=status,
        collection_method='online',
        seller_id=seller.id,
        category_id=category.id if category else None,
        picked_up_at=picked_up_at,
        arrived_at_store_at=arrived_at_store_at,
    )
    db.session.add(item)
    db.session.commit()
    return item


def make_shift_pickup(db, app, seller, status='pending'):
    from models import ShiftWeek, Shift, ShiftPickup, User
    # Minimal admin user for created_by_id
    admin = db.session.query(User).filter_by(email='admin_fixture@test.com').first()
    if not admin:
        admin = User(email='admin_fixture@test.com', full_name='Admin', is_admin=True)
        admin.set_password('pw')
        db.session.add(admin)
        db.session.commit()

    from datetime import date
    week = ShiftWeek(week_start=date(2026, 4, 27), status='published',
                     created_by_id=admin.id)
    db.session.add(week)
    db.session.commit()

    shift = Shift(week_id=week.id, day_of_week='mon', slot='am', trucks=1)
    db.session.add(shift)
    db.session.commit()

    pickup = ShiftPickup(
        shift_id=shift.id,
        seller_id=seller.id,
        truck_number=1,
        status=status,
        created_by_id=admin.id,
    )
    db.session.add(pickup)
    db.session.commit()
    return pickup


# ---------------------------------------------------------------------------
# _compute_seller_tracker — Stage logic
# ---------------------------------------------------------------------------

class TestComputeSellerTracker:

    def test_no_items_stage1_active(self, app, db, seller):
        """No items at all → Stage 1 (Submitted) is active."""
        from app import _compute_seller_tracker
        with app.app_context():
            result = _compute_seller_tracker(seller, [])
        stages = {s['key']: s['state'] for s in result['stages']}
        assert stages['submitted'] == 'active'
        assert stages['approved'] == 'upcoming'
        assert stages['scheduled'] == 'upcoming'

    def test_only_rejected_items_stage1_active(self, app, db, seller, category):
        """Only rejected items → active_items empty → Stage 1 active."""
        from app import _compute_seller_tracker
        item = make_item(db, seller, status='rejected', category=category)
        with app.app_context():
            result = _compute_seller_tracker(seller, [item])
        stages = {s['key']: s['state'] for s in result['stages']}
        assert stages['submitted'] == 'active'

    def test_pending_valuation_item_stage2_active(self, app, db, seller, category):
        """Item in pending_valuation → Stage 1 complete, Stage 2 active."""
        from app import _compute_seller_tracker
        item = make_item(db, seller, status='pending_valuation', category=category)
        with app.app_context():
            result = _compute_seller_tracker(seller, [item])
        stages = {s['key']: s['state'] for s in result['stages']}
        assert stages['submitted'] == 'completed'
        assert stages['approved'] == 'active'

    def test_approved_item_no_pickup_stage3_active(self, app, db, seller, category):
        """Approved item, no ShiftPickup → Stage 3 (Scheduled) active."""
        from app import _compute_seller_tracker
        item = make_item(db, seller, status='available', category=category)
        with app.app_context():
            result = _compute_seller_tracker(seller, [item])
        stages = {s['key']: s['state'] for s in result['stages']}
        assert stages['submitted'] == 'completed'
        assert stages['approved'] == 'completed'
        assert stages['scheduled'] == 'active'

    def test_scheduled_no_pickup_at_stage4_active(self, app, db, seller, category):
        """ShiftPickup exists → Stage 3 complete; no picked_up_at → Stage 4 active."""
        from app import _compute_seller_tracker
        item = make_item(db, seller, status='available', category=category)
        make_shift_pickup(db, app, seller, status='pending')
        with app.app_context():
            result = _compute_seller_tracker(seller, [item])
        stages = {s['key']: s['state'] for s in result['stages']}
        assert stages['scheduled'] == 'completed'
        assert stages['picked_up'] == 'active'

    def test_picked_up_no_arrived_stage5_active(self, app, db, seller, category):
        """picked_up_at set → Stage 4 complete; no arrived_at_store_at → Stage 5 active."""
        from app import _compute_seller_tracker
        item = make_item(db, seller, status='available',
                         picked_up_at=datetime.utcnow(), category=category)
        make_shift_pickup(db, app, seller, status='completed')
        with app.app_context():
            result = _compute_seller_tracker(seller, [item])
        stages = {s['key']: s['state'] for s in result['stages']}
        assert stages['picked_up'] == 'completed'
        assert stages['at_campus_swap'] == 'active'

    def test_arrived_teaser_mode_stage6_active(self, app, db, seller, category):
        """arrived_at_store_at set + shop_teaser_mode=true → Stage 5 complete, Stage 6 active."""
        from app import _compute_seller_tracker
        from models import AppSetting
        AppSetting.set('shop_teaser_mode', 'true')
        item = make_item(db, seller, status='available',
                         picked_up_at=datetime.utcnow(),
                         arrived_at_store_at=datetime.utcnow(),
                         category=category)
        make_shift_pickup(db, app, seller, status='completed')
        with app.app_context():
            result = _compute_seller_tracker(seller, [item])
        stages = {s['key']: s['state'] for s in result['stages']}
        assert stages['at_campus_swap'] == 'completed'
        assert stages['in_the_shop'] == 'active'
        AppSetting.set('shop_teaser_mode', 'false')

    def test_all_complete_no_active_stage(self, app, db, seller, category):
        """All conditions met → no active stage, all completed."""
        from app import _compute_seller_tracker
        from models import AppSetting
        AppSetting.set('shop_teaser_mode', 'false')
        item = make_item(db, seller, status='available',
                         picked_up_at=datetime.utcnow(),
                         arrived_at_store_at=datetime.utcnow(),
                         category=category)
        make_shift_pickup(db, app, seller, status='completed')
        with app.app_context():
            result = _compute_seller_tracker(seller, [item])
        stages = {s['key']: s['state'] for s in result['stages']}
        assert all(s == 'completed' for s in stages.values())
        active_stages = [s for s in result['stages'] if s['state'] == 'active']
        assert active_stages == []

    def test_all_complete_terminal_message(self, app, db, seller, category):
        """All stages complete → terminal 'Good luck!' message."""
        from app import _compute_seller_tracker
        from models import AppSetting
        AppSetting.set('shop_teaser_mode', 'false')
        item = make_item(db, seller, status='available',
                         picked_up_at=datetime.utcnow(),
                         arrived_at_store_at=datetime.utcnow(),
                         category=category)
        make_shift_pickup(db, app, seller, status='completed')
        with app.app_context():
            result = _compute_seller_tracker(seller, [item])
        assert 'Good luck' in result['active_message']

    def test_sold_item_counts_for_stage6(self, app, db, seller, category):
        """sold item satisfies Stage 6 (available OR sold)."""
        from app import _compute_seller_tracker
        from models import AppSetting
        AppSetting.set('shop_teaser_mode', 'false')
        item = make_item(db, seller, status='sold',
                         picked_up_at=datetime.utcnow(),
                         arrived_at_store_at=datetime.utcnow(),
                         category=category)
        make_shift_pickup(db, app, seller, status='completed')
        with app.app_context():
            result = _compute_seller_tracker(seller, [item])
        stages = {s['key']: s['state'] for s in result['stages']}
        assert stages['in_the_shop'] == 'completed'

    def test_stage6_absent_appsetting_treats_as_false(self, app, db, seller, category):
        """Missing shop_teaser_mode key → defaults 'false' → Stage 6 evaluates normally."""
        from app import _compute_seller_tracker
        from models import AppSetting
        # Remove the key if present
        from app import db as _db
        existing = AppSetting.query.filter_by(key='shop_teaser_mode').first()
        if existing:
            _db.session.delete(existing)
            _db.session.commit()
        item = make_item(db, seller, status='available',
                         picked_up_at=datetime.utcnow(),
                         arrived_at_store_at=datetime.utcnow(),
                         category=category)
        make_shift_pickup(db, app, seller, status='completed')
        with app.app_context():
            result = _compute_seller_tracker(seller, [item])
        stages = {s['key']: s['state'] for s in result['stages']}
        assert stages['in_the_shop'] == 'completed'


# ---------------------------------------------------------------------------
# _compute_seller_tracker — Upcoming states
# ---------------------------------------------------------------------------

class TestUpcomingStates:

    def test_stages_after_active_are_upcoming(self, app, db, seller, category):
        """All stages after the active one are 'upcoming', not 'completed'."""
        from app import _compute_seller_tracker
        item = make_item(db, seller, status='pending_valuation', category=category)
        with app.app_context():
            result = _compute_seller_tracker(seller, [item])
        states = [s['state'] for s in result['stages']]
        # pending_valuation → submitted=completed, approved=active, rest=upcoming
        assert states == ['completed', 'active', 'upcoming', 'upcoming', 'upcoming', 'upcoming']

    def test_active_stage_message_is_correct(self, app, db, seller, category):
        """Active stage message for 'scheduled' stage (available item, no ShiftPickup)."""
        from app import _compute_seller_tracker
        item = make_item(db, seller, status='available', category=category)
        # 'available' satisfies submitted+approved; no ShiftPickup → scheduled is active
        with app.app_context():
            result = _compute_seller_tracker(seller, [item])
        # active_key = 'scheduled' → "Pickup scheduled. We'll text you..."
        assert 'text' in result['active_message'].lower() or 'driver' in result['active_message'].lower()


# ---------------------------------------------------------------------------
# _compute_seller_tracker — ShiftPickup issue
# ---------------------------------------------------------------------------

class TestPickupIssue:

    def test_pickup_issue_keeps_stage3_active(self, app, db, seller, category):
        """ShiftPickup with status='issue' → Stage 3 condition False → Stage 3 stays active."""
        from app import _compute_seller_tracker
        item = make_item(db, seller, status='available', category=category)
        make_shift_pickup(db, app, seller, status='issue')
        with app.app_context():
            result = _compute_seller_tracker(seller, [item])
        stages = {s['key']: s['state'] for s in result['stages']}
        assert stages['scheduled'] == 'active'

    def test_pickup_issue_fires_interrupt(self, app, db, seller, category):
        """ShiftPickup status='issue' fires interrupt with correct message and no link."""
        from app import _compute_seller_tracker
        item = make_item(db, seller, status='available', category=category)
        make_shift_pickup(db, app, seller, status='issue')
        with app.app_context():
            result = _compute_seller_tracker(seller, [item])
        assert result['interrupt'] is not None
        assert 'issue' in result['interrupt']['message'].lower()
        assert result['interrupt']['link'] is None

    def test_pickup_completed_clears_interrupt(self, app, db, seller, category):
        """ShiftPickup status='completed' → no interrupt."""
        from app import _compute_seller_tracker
        item = make_item(db, seller, status='available',
                         picked_up_at=datetime.utcnow(), category=category)
        make_shift_pickup(db, app, seller, status='completed')
        with app.app_context():
            result = _compute_seller_tracker(seller, [item])
        assert result['interrupt'] is None


# ---------------------------------------------------------------------------
# _compute_seller_tracker — needs_info interrupt
# ---------------------------------------------------------------------------

class TestNeedsInfoInterrupt:

    def test_needs_info_item_fires_interrupt_with_link(self, app, db, seller, category):
        """needs_info item fires interrupt with edit link."""
        from app import _compute_seller_tracker
        item = make_item(db, seller, status='needs_info', category=category)
        with app.app_context():
            result = _compute_seller_tracker(seller, [item])
        assert result['interrupt'] is not None
        assert 'attention' in result['interrupt']['message'].lower()
        assert result['interrupt']['link'] == f'/edit_item/{item.id}'

    def test_needs_info_takes_priority_over_pickup_issue(self, app, db, seller, category):
        """needs_info interrupt takes priority over pickup issue interrupt."""
        from app import _compute_seller_tracker
        item = make_item(db, seller, status='needs_info', category=category)
        make_shift_pickup(db, app, seller, status='issue')
        with app.app_context():
            result = _compute_seller_tracker(seller, [item])
        assert 'attention' in result['interrupt']['message'].lower()
        assert result['interrupt']['link'] is not None  # has link, not the no-link issue

    def test_all_items_needs_info_stage2_active(self, app, db, seller, category):
        """All items needs_info → approved condition False → Stage 2 active, interrupt fires."""
        from app import _compute_seller_tracker
        item = make_item(db, seller, status='needs_info', category=category)
        with app.app_context():
            result = _compute_seller_tracker(seller, [item])
        stages = {s['key']: s['state'] for s in result['stages']}
        # submitted=completed (has active items), approved=active (needs_info excluded), rest=upcoming
        assert stages['submitted'] == 'completed'
        assert stages['approved'] == 'active'
        assert stages['scheduled'] == 'upcoming'
        assert result['interrupt'] is not None

    def test_no_interrupt_when_no_issues(self, app, db, seller, category):
        """Clean state → interrupt is None."""
        from app import _compute_seller_tracker
        item = make_item(db, seller, status='available', category=category)
        with app.app_context():
            result = _compute_seller_tracker(seller, [item])
        assert result['interrupt'] is None


# ---------------------------------------------------------------------------
# _compute_seller_tracker — One query guarantee
# ---------------------------------------------------------------------------

class TestOneQuery:

    def test_single_shiftpickup_query_not_per_item(self, app, db, seller, category):
        """_compute_seller_tracker issues one ShiftPickup query regardless of item count."""
        from app import _compute_seller_tracker
        # Create multiple items
        items = [make_item(db, seller, status='available', category=category) for _ in range(5)]
        make_shift_pickup(db, app, seller, status='pending')
        query_count = []

        from unittest.mock import patch
        original_filter = type(
            __import__('models').ShiftPickup.query.filter_by()
        )

        # Count via SQLAlchemy event
        from sqlalchemy import event
        from app import db as _db
        counts = []

        def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
            if 'shift_pickup' in statement.lower():
                counts.append(1)

        with app.app_context():
            engine = _db.engine
            event.listen(engine, 'before_cursor_execute', before_cursor_execute)
            try:
                _compute_seller_tracker(seller, items)
            finally:
                event.remove(engine, 'before_cursor_execute', before_cursor_execute)

        assert len(counts) == 1, f"Expected 1 ShiftPickup query, got {len(counts)}"


# ---------------------------------------------------------------------------
# Dashboard route — setup_complete computation
# ---------------------------------------------------------------------------

class TestSetupComplete:

    def test_setup_complete_requires_payout_handle(self, app, db, seller):
        """setup_complete is False if payout_handle is missing."""
        seller.payout_handle = None
        db.session.commit()
        with app.test_client() as c:
            c.post('/login', data={'email': seller.email, 'password': 'password'})
            from flask import template_rendered
            captured = []
            def on_template(sender, template, context, **extra):
                captured.append(context)
            template_rendered.connect(on_template, app)
            try:
                c.get('/dashboard')
            finally:
                template_rendered.disconnect(on_template, app)
        assert len(captured) > 0
        ctx = captured[-1]
        assert ctx.get('setup_complete') is False

    def test_setup_complete_true_when_all_fields_set(self, app, db, seller):
        """setup_complete=True when phone, pickup_week, pickup_location, payout_method, payout_handle all set."""
        with app.test_client() as c:
            c.post('/login', data={'email': seller.email, 'password': 'password'})
            from flask import template_rendered
            captured = []
            def on_template(sender, template, context, **extra):
                captured.append(context)
            template_rendered.connect(on_template, app)
            try:
                c.get('/dashboard')
            finally:
                template_rendered.disconnect(on_template, app)
        ctx = captured[-1]
        assert ctx.get('setup_complete') is True

    def test_tracker_none_when_setup_incomplete(self, app, db, seller):
        """tracker=None in template context when setup_complete=False."""
        seller.payout_handle = None
        db.session.commit()
        with app.test_client() as c:
            c.post('/login', data={'email': seller.email, 'password': 'password'})
            from flask import template_rendered
            captured = []
            def on_template(sender, template, context, **extra):
                captured.append(context)
            template_rendered.connect(on_template, app)
            try:
                c.get('/dashboard')
            finally:
                template_rendered.disconnect(on_template, app)
        ctx = captured[-1]
        assert ctx.get('tracker') is None

    def test_tracker_present_when_setup_complete(self, app, db, seller):
        """tracker dict present in template context when setup_complete=True."""
        with app.test_client() as c:
            c.post('/login', data={'email': seller.email, 'password': 'password'})
            from flask import template_rendered
            captured = []
            def on_template(sender, template, context, **extra):
                captured.append(context)
            template_rendered.connect(on_template, app)
            try:
                c.get('/dashboard')
            finally:
                template_rendered.disconnect(on_template, app)
        ctx = captured[-1]
        assert ctx.get('tracker') is not None
        assert 'stages' in ctx['tracker']
        assert len(ctx['tracker']['stages']) == 6

    def test_setup_complete_false_missing_phone(self, app, db, seller):
        """setup_complete=False when phone is missing."""
        seller.phone = None
        db.session.commit()
        with app.test_client() as c:
            c.post('/login', data={'email': seller.email, 'password': 'password'})
            from flask import template_rendered
            captured = []
            def on_template(sender, template, context, **extra):
                captured.append(context)
            template_rendered.connect(on_template, app)
            try:
                c.get('/dashboard')
            finally:
                template_rendered.disconnect(on_template, app)
        ctx = captured[-1]
        assert ctx.get('setup_complete') is False

    def test_setup_complete_false_missing_pickup_week(self, app, db, seller):
        """setup_complete=False when pickup_week is missing."""
        seller.pickup_week = None
        db.session.commit()
        with app.test_client() as c:
            c.post('/login', data={'email': seller.email, 'password': 'password'})
            from flask import template_rendered
            captured = []
            def on_template(sender, template, context, **extra):
                captured.append(context)
            template_rendered.connect(on_template, app)
            try:
                c.get('/dashboard')
            finally:
                template_rendered.disconnect(on_template, app)
        ctx = captured[-1]
        assert ctx.get('setup_complete') is False


# ---------------------------------------------------------------------------
# Dashboard route — HTML output (strip vs. tracker mutual exclusivity)
# ---------------------------------------------------------------------------

class TestDashboardHTML:

    def test_setup_strip_visible_when_incomplete(self, app, db, seller):
        """setup-strip present in HTML when setup is incomplete."""
        seller.payout_handle = None
        db.session.commit()
        with app.test_client() as c:
            c.post('/login', data={'email': seller.email, 'password': 'password'})
            rv = c.get('/dashboard')
        assert b'setup-strip' in rv.data

    def test_tracker_not_in_html_when_setup_incomplete(self, app, db, seller):
        """seller-tracker class absent from HTML when setup incomplete."""
        seller.payout_handle = None
        db.session.commit()
        with app.test_client() as c:
            c.post('/login', data={'email': seller.email, 'password': 'password'})
            rv = c.get('/dashboard')
        assert b'seller-tracker' not in rv.data

    def test_tracker_in_html_when_setup_complete(self, app, db, seller):
        """seller-tracker present in HTML when setup complete."""
        with app.test_client() as c:
            c.post('/login', data={'email': seller.email, 'password': 'password'})
            rv = c.get('/dashboard')
        assert b'seller-tracker' in rv.data

    def test_setup_strip_absent_when_tracker_shown(self, app, db, seller):
        """setup-strip absent from HTML when tracker is shown."""
        with app.test_client() as c:
            c.post('/login', data={'email': seller.email, 'password': 'password'})
            rv = c.get('/dashboard')
        assert b'setup-strip' not in rv.data

    def test_item_tile_checklist_removed(self, app, db, seller, category):
        """dashboard-item-checklist class is gone from dashboard HTML."""
        make_item(db, seller, status='available', category=category)
        with app.test_client() as c:
            c.post('/login', data={'email': seller.email, 'password': 'password'})
            rv = c.get('/dashboard')
        assert b'dashboard-item-checklist' not in rv.data

    def test_stage_labels_present_in_tracker_html(self, app, db, seller):
        """Stage labels rendered in tracker HTML."""
        with app.test_client() as c:
            c.post('/login', data={'email': seller.email, 'password': 'password'})
            rv = c.get('/dashboard')
        assert b'Submitted' in rv.data
        assert b'Approved' in rv.data
        assert b'Scheduled' in rv.data

    def test_interrupt_html_shown_for_needs_info(self, app, db, seller, category):
        """Interrupt callout HTML rendered when item needs attention."""
        make_item(db, seller, status='needs_info', category=category)
        with app.test_client() as c:
            c.post('/login', data={'email': seller.email, 'password': 'password'})
            rv = c.get('/dashboard')
        assert b'seller-tracker__interrupt' in rv.data
        assert b'attention' in rv.data

    def test_no_interrupt_html_for_clean_state(self, app, db, seller, category):
        """No interrupt callout when no issues."""
        make_item(db, seller, status='available', category=category)
        with app.test_client() as c:
            c.post('/login', data={'email': seller.email, 'password': 'password'})
            rv = c.get('/dashboard')
        assert b'seller-tracker__interrupt' not in rv.data


# ---------------------------------------------------------------------------
# Regression
# ---------------------------------------------------------------------------

class TestRegression:

    def test_dashboard_still_loads_for_seller(self, app, db, seller):
        """Dashboard loads with 200 for a valid seller."""
        with app.test_client() as c:
            c.post('/login', data={'email': seller.email, 'password': 'password'})
            rv = c.get('/dashboard')
        assert rv.status_code == 200

    def test_dashboard_loads_without_items(self, app, db):
        """Dashboard loads for seller with no items (is_seller=True path)."""
        from models import User
        u = User(
            email='noitems@test.com',
            full_name='No Items',
            is_seller=True,
            phone='9195550000',
            pickup_week='week1',
            pickup_location_type='on_campus',
            pickup_dorm='Morrison',
            pickup_room='200',
            pickup_access_type='elevator',
            pickup_floor=1,
            payout_method='venmo',
            payout_handle='@noitems',
        )
        u.set_password('pw')
        db.session.add(u)
        db.session.commit()
        with app.test_client() as c:
            c.post('/login', data={'email': u.email, 'password': 'pw'})
            rv = c.get('/dashboard')
        # No items + is_seller=True → dashboard renders (not redirected to onboard)
        assert rv.status_code == 200

    def test_picked_up_at_not_modified_by_tracker(self, app, db, seller, category):
        """_compute_seller_tracker reads picked_up_at but does not write it."""
        from app import _compute_seller_tracker
        ts = datetime(2026, 4, 28, 10, 0, 0)
        item = make_item(db, seller, status='available', picked_up_at=ts, category=category)
        with app.app_context():
            _compute_seller_tracker(seller, [item])
        db.session.refresh(item)
        assert item.picked_up_at == ts

    def test_arrived_at_store_not_modified_by_tracker(self, app, db, seller, category):
        """_compute_seller_tracker reads arrived_at_store_at but does not write it."""
        from app import _compute_seller_tracker
        ts = datetime(2026, 4, 29, 14, 0, 0)
        item = make_item(db, seller, status='available',
                         picked_up_at=ts, arrived_at_store_at=ts, category=category)
        with app.app_context():
            _compute_seller_tracker(seller, [item])
        db.session.refresh(item)
        assert item.arrived_at_store_at == ts
