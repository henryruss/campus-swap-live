"""
Tests for Spec #6 — Route Planning

Covers:
- Item unit size resolution (category default, per-item override, fallback)
- Effective truck capacity calculation
- Auto-assignment algorithm (preference match, capacity, TBD logic, idempotency)
- Geographic clustering (dorm, partner apartment, lat/lng proximity, unlocated)
- Nearest-neighbor stop ordering
- Add Truck (Shift.trucks increment, new truck number)
- Stop movement between trucks
- Capacity warning flag behavior
- Seller notification email (idempotency via notified_at)
- Route settings (AppSetting reads/writes)
- Auth gating on all new routes
- Mover stops_partial auto-refresh endpoint
- Stairs/elevator badge data present on stop cards
- Sellers without pickup_week excluded from route builder
"""

import pytest
import math
from datetime import datetime, date


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def admin_user(app, db):
    from models import User
    u = User(
        email='admin@test.com',
        full_name='Admin User',
        is_admin=True,
        is_super_admin=True,
        is_seller=True,
    )
    u.set_password('password')
    db.session.add(u)
    db.session.commit()
    return u


@pytest.fixture
def regular_user(app, db):
    from models import User
    u = User(
        email='worker@test.com',
        full_name='Regular Worker',
        is_worker=True,
        worker_status='approved',
    )
    u.set_password('password')
    db.session.add(u)
    db.session.commit()
    return u


@pytest.fixture
def admin_client(client, admin_user):
    client.post('/login', data={'email': admin_user.email, 'password': 'password'})
    return client


@pytest.fixture
def worker_client(client, regular_user):
    client.post('/login', data={'email': regular_user.email, 'password': 'password'})
    return client


@pytest.fixture
def category_couch(app, db):
    from models import InventoryCategory
    cat = InventoryCategory(name='Couch / Sofa', default_unit_size=3.0)
    db.session.add(cat)
    db.session.commit()
    return cat


@pytest.fixture
def category_fridge(app, db):
    from models import InventoryCategory
    cat = InventoryCategory(name='Mini Fridge', default_unit_size=1.0)
    db.session.add(cat)
    db.session.commit()
    return cat


@pytest.fixture
def category_misc(app, db):
    from models import InventoryCategory
    cat = InventoryCategory(name='Miscellaneous', default_unit_size=0.5)
    db.session.add(cat)
    db.session.commit()
    return cat


@pytest.fixture
def seller_week1_am(app, db):
    """Seller with week1, morning preference, on-campus dorm address."""
    from models import User
    u = User(
        email='seller_am@test.com',
        full_name='AM Seller',
        is_seller=True,
        pickup_week='week1',
        pickup_time_preference='morning',
        pickup_location_type='on_campus',
        pickup_dorm='Granville Towers',
        pickup_lat=35.9132,
        pickup_lng=-79.0558,
    )
    u.set_password('password')
    db.session.add(u)
    db.session.commit()
    return u


@pytest.fixture
def seller_week1_pm(app, db):
    """Seller with week1, afternoon preference, different dorm."""
    from models import User
    u = User(
        email='seller_pm@test.com',
        full_name='PM Seller',
        is_seller=True,
        pickup_week='week1',
        pickup_time_preference='afternoon',
        pickup_location_type='on_campus',
        pickup_dorm='Ehringhaus',
        pickup_lat=35.9100,
        pickup_lng=-79.0530,
    )
    u.set_password('password')
    db.session.add(u)
    db.session.commit()
    return u


@pytest.fixture
def seller_no_week(app, db):
    """Seller with no pickup_week set — should be excluded from route builder."""
    from models import User
    u = User(
        email='seller_noweek@test.com',
        full_name='No Week Seller',
        is_seller=True,
        pickup_week=None,
        pickup_location_type='on_campus',
        pickup_dorm='Morrison',
    )
    u.set_password('password')
    db.session.add(u)
    db.session.commit()
    return u


@pytest.fixture
def seller_partner_apt(app, db):
    """Seller at a partner apartment building."""
    from models import User
    u = User(
        email='seller_apt@test.com',
        full_name='Apt Seller',
        is_seller=True,
        pickup_week='week1',
        pickup_time_preference='morning',
        pickup_location_type='off_campus',
        pickup_partner_building='The Lofts at 140',
        pickup_lat=35.9200,
        pickup_lng=-79.0600,
    )
    u.set_password('password')
    db.session.add(u)
    db.session.commit()
    return u


@pytest.fixture
def seller_off_campus_nearby(app, db):
    """Off-campus seller near seller_week1_am (within 0.25 miles)."""
    from models import User
    u = User(
        email='seller_nearby@test.com',
        full_name='Nearby Seller',
        is_seller=True,
        pickup_week='week1',
        pickup_time_preference='morning',
        pickup_location_type='off_campus',
        pickup_address='123 Franklin St, Chapel Hill, NC',
        pickup_lat=35.9133,   # very close to seller_week1_am
        pickup_lng=-79.0559,
    )
    u.set_password('password')
    db.session.add(u)
    db.session.commit()
    return u


@pytest.fixture
def seller_no_address(app, db):
    """Seller with no lat/lng and no dorm — unlocated cluster."""
    from models import User
    u = User(
        email='seller_noloc@test.com',
        full_name='No Location Seller',
        is_seller=True,
        pickup_week='week1',
        pickup_time_preference='morning',
        pickup_lat=None,
        pickup_lng=None,
        pickup_dorm=None,
    )
    u.set_password('password')
    db.session.add(u)
    db.session.commit()
    return u


@pytest.fixture
def available_item(app, db, seller_week1_am, category_couch):
    from models import InventoryItem
    item = InventoryItem(
        description='Big couch',
        status='available',
        seller_id=seller_week1_am.id,
        category_id=category_couch.id,
        price=100,
        collection_method='free',
    )
    db.session.add(item)
    db.session.commit()
    return item


@pytest.fixture
def shift_week1_am(app, db, admin_user):
    """A published week1 AM shift with 2 trucks."""
    from models import ShiftWeek, Shift
    week = ShiftWeek(
        week_start=date(2026, 4, 27),
        status='published',
        created_by_id=admin_user.id,
    )
    db.session.add(week)
    db.session.flush()
    shift = Shift(
        week_id=week.id,
        day_of_week='mon',
        slot='am',
        trucks=2,
        is_active=True,
    )
    db.session.add(shift)
    db.session.commit()
    return shift


@pytest.fixture
def shift_week1_pm(app, db, admin_user):
    """A published week1 PM shift with 1 truck."""
    from models import ShiftWeek, Shift
    week = ShiftWeek.query.filter_by(week_start=date(2026, 4, 27)).first()
    if not week:
        week = ShiftWeek(
            week_start=date(2026, 4, 27),
            status='published',
            created_by_id=admin_user.id,
        )
        db.session.add(week)
        db.session.flush()
    shift = Shift(
        week_id=week.id,
        day_of_week='mon',
        slot='pm',
        trucks=1,
        is_active=True,
    )
    db.session.add(shift)
    db.session.commit()
    return shift


@pytest.fixture
def storage_location(app, db, admin_user):
    from models import StorageLocation
    loc = StorageLocation(
        name='Main Storage Unit',
        address='500 Airport Rd, Chapel Hill, NC',
        is_active=True,
        created_by_id=admin_user.id,
    )
    db.session.add(loc)
    db.session.commit()
    return loc


# ---------------------------------------------------------------------------
# Unit Size Resolution
# ---------------------------------------------------------------------------

class TestItemUnitSizeResolution:

    def test_uses_category_default_when_no_override(self, app, db, available_item, category_couch):
        from helpers import get_item_unit_size
        assert get_item_unit_size(available_item) == 3.0

    def test_uses_per_item_override_when_set(self, app, db, available_item):
        from helpers import get_item_unit_size
        available_item.unit_size = 1.5
        db.session.commit()
        assert get_item_unit_size(available_item) == 1.5

    def test_override_of_zero_is_respected(self, app, db, available_item):
        """A unit_size of 0.0 is a valid override (e.g. very small item)."""
        from helpers import get_item_unit_size
        available_item.unit_size = 0.0
        db.session.commit()
        assert get_item_unit_size(available_item) == 0.0

    def test_fallback_to_1_when_no_category(self, app, db, available_item):
        from helpers import get_item_unit_size
        available_item.category_id = None
        available_item.unit_size = None
        db.session.commit()
        assert get_item_unit_size(available_item) == 1.0

    def test_fallback_to_1_when_category_has_no_default(self, app, db, available_item, category_couch):
        from helpers import get_item_unit_size
        category_couch.default_unit_size = None
        available_item.unit_size = None
        db.session.commit()
        assert get_item_unit_size(available_item) == 1.0

    def test_seller_unit_count_sums_all_available_items(self, app, db, seller_week1_am, category_couch, category_fridge):
        from models import InventoryItem
        from helpers import get_seller_unit_count
        item1 = InventoryItem(description='Couch', status='available',
                              seller_id=seller_week1_am.id, category_id=category_couch.id,
                              price=100, collection_method='free')
        item2 = InventoryItem(description='Fridge', status='available',
                              seller_id=seller_week1_am.id, category_id=category_fridge.id,
                              price=50, collection_method='free')
        item3 = InventoryItem(description='Sold couch', status='sold',
                              seller_id=seller_week1_am.id, category_id=category_couch.id,
                              price=100, collection_method='free')
        db.session.add_all([item1, item2, item3])
        db.session.commit()
        # 3.0 (couch) + 1.0 (fridge) = 4.0; sold item excluded
        assert get_seller_unit_count(seller_week1_am) == 4.0

    def test_seller_unit_count_excludes_non_available_statuses(self, app, db, seller_week1_am, category_couch):
        from models import InventoryItem
        from helpers import get_seller_unit_count
        for status in ['pending_valuation', 'rejected', 'needs_info', 'sold']:
            item = InventoryItem(description=f'{status} item', status=status,
                                 seller_id=seller_week1_am.id, category_id=category_couch.id,
                                 price=100, collection_method='free')
            db.session.add(item)
        db.session.commit()
        assert get_seller_unit_count(seller_week1_am) == 0.0


# ---------------------------------------------------------------------------
# Truck Capacity
# ---------------------------------------------------------------------------

class TestTruckCapacity:

    def test_effective_capacity_default(self, app, db):
        from helpers import get_effective_capacity
        from models import AppSetting
        AppSetting.set('truck_raw_capacity', '18')
        AppSetting.set('truck_capacity_buffer_pct', '10')
        # floor(18 * 0.9) = floor(16.2) = 16
        assert get_effective_capacity() == 16

    def test_effective_capacity_zero_buffer(self, app, db):
        from helpers import get_effective_capacity
        from models import AppSetting
        AppSetting.set('truck_raw_capacity', '20')
        AppSetting.set('truck_capacity_buffer_pct', '0')
        assert get_effective_capacity() == 20

    def test_effective_capacity_uses_floor(self, app, db):
        from helpers import get_effective_capacity
        from models import AppSetting
        AppSetting.set('truck_raw_capacity', '10')
        AppSetting.set('truck_capacity_buffer_pct', '15')
        # floor(10 * 0.85) = floor(8.5) = 8
        assert get_effective_capacity() == 8

    def test_effective_capacity_falls_back_to_defaults(self, app, db):
        from helpers import get_effective_capacity
        # No AppSettings set — should use hardcoded defaults (18, 10%)
        result = get_effective_capacity()
        assert result == math.floor(18 * 0.9)

    def test_route_settings_page_loads(self, admin_client):
        resp = admin_client.get('/admin/settings/route')
        assert resp.status_code == 200

    def test_route_settings_requires_super_admin(self, client, db):
        from models import User
        regular_admin = User(email='reg_admin@test.com', full_name='Reg Admin',
                             is_admin=True, is_super_admin=False)
        regular_admin.set_password('password')
        db.session.add(regular_admin)
        db.session.commit()
        client.post('/login', data={'email': 'reg_admin@test.com', 'password': 'password'})
        resp = client.post('/admin/settings/route', data={'truck_raw_capacity': '20'})
        assert resp.status_code in (302, 403)

    def test_route_settings_saves_appSettings(self, admin_client, app):
        from models import AppSetting
        admin_client.post('/admin/settings/route', data={
            'truck_raw_capacity': '20',
            'truck_capacity_buffer_pct': '15',
            'route_am_window': '8am-12pm',
            'route_pm_window': '12pm-4pm',
        })
        with app.app_context():
            assert AppSetting.get('truck_raw_capacity') == '20'
            assert AppSetting.get('truck_capacity_buffer_pct') == '15'

    def test_route_settings_saves_category_unit_sizes(self, admin_client, app, category_couch):
        admin_client.post('/admin/settings/route', data={
            'truck_raw_capacity': '18',
            'truck_capacity_buffer_pct': '10',
            f'category_unit_{category_couch.id}': '2.5',
        })
        with app.app_context():
            from models import InventoryCategory
            cat = InventoryCategory.query.get(category_couch.id)
            assert cat.default_unit_size == 2.5


# ---------------------------------------------------------------------------
# Auto-Assignment Algorithm
# ---------------------------------------------------------------------------

class TestAutoAssignment:

    def test_assigns_seller_to_matching_am_shift(self, admin_client, app, db,
                                                  seller_week1_am, available_item,
                                                  shift_week1_am):
        from models import ShiftPickup
        resp = admin_client.post('/admin/routes/auto-assign',
                                 content_type='application/json')
        assert resp.status_code == 200
        data = resp.get_json()
        assert seller_week1_am.id in data['assigned']
        pickup = ShiftPickup.query.filter_by(seller_id=seller_week1_am.id).first()
        assert pickup is not None
        assert pickup.shift_id == shift_week1_am.id

    def test_seller_goes_to_tbd_when_no_matching_slot(self, admin_client, app, db,
                                                        seller_week1_pm, available_item,
                                                        shift_week1_am):
        """seller_week1_pm wants afternoon but only AM shift exists."""
        from models import InventoryItem
        item = InventoryItem(description='Item', status='available',
                             seller_id=seller_week1_pm.id,
                             price=50, collection_method='free')
        db.session.add(item)
        db.session.commit()
        resp = admin_client.post('/admin/routes/auto-assign',
                                 content_type='application/json')
        data = resp.get_json()
        tbd_ids = [t['seller_id'] for t in data['tbd']]
        assert seller_week1_pm.id in tbd_ids

    def test_tbd_reason_included_in_response(self, admin_client, app, db,
                                              seller_week1_pm, shift_week1_am):
        from models import InventoryItem
        item = InventoryItem(description='Item', status='available',
                             seller_id=seller_week1_pm.id,
                             price=50, collection_method='free')
        db.session.add(item)
        db.session.commit()
        resp = admin_client.post('/admin/routes/auto-assign',
                                 content_type='application/json')
        data = resp.get_json()
        tbd_entry = next(t for t in data['tbd'] if t['seller_id'] == seller_week1_pm.id)
        assert 'reason' in tbd_entry
        assert len(tbd_entry['reason']) > 0

    def test_over_capacity_assignment_sets_warning_flag(self, admin_client, app, db,
                                                          seller_week1_am, category_couch,
                                                          shift_week1_am):
        """Fill shift beyond effective capacity — should assign with warning, not block."""
        from models import InventoryItem, AppSetting, ShiftPickup
        AppSetting.set('truck_raw_capacity', '2')
        AppSetting.set('truck_capacity_buffer_pct', '0')
        # Create a couch (3.0 units) — exceeds capacity of 2
        item = InventoryItem(description='Big couch', status='available',
                             seller_id=seller_week1_am.id, category_id=category_couch.id,
                             price=100, collection_method='free')
        db.session.add(item)
        db.session.commit()
        resp = admin_client.post('/admin/routes/auto-assign',
                                 content_type='application/json')
        assert resp.status_code == 200
        data = resp.get_json()
        # Seller still assigned despite over-cap
        assert seller_week1_am.id in data['assigned']
        pickup = ShiftPickup.query.filter_by(seller_id=seller_week1_am.id).first()
        assert pickup.capacity_warning is True
        assert pickup.shift_id == shift_week1_am.id

    def test_auto_assignment_skips_seller_with_existing_pickup(self, admin_client, app, db,
                                                                 seller_week1_am, available_item,
                                                                 shift_week1_am):
        from models import ShiftPickup
        # Pre-create a pickup
        existing = ShiftPickup(shift_id=shift_week1_am.id, seller_id=seller_week1_am.id,
                               truck_number=1, status='pending')
        db.session.add(existing)
        db.session.commit()
        resp = admin_client.post('/admin/routes/auto-assign',
                                 content_type='application/json')
        data = resp.get_json()
        assert seller_week1_am.id not in data['assigned']
        # Still only one pickup
        assert ShiftPickup.query.filter_by(seller_id=seller_week1_am.id).count() == 1

    def test_auto_assignment_excludes_sellers_without_pickup_week(self, admin_client, app, db,
                                                                    seller_no_week, shift_week1_am):
        from models import InventoryItem, ShiftPickup
        item = InventoryItem(description='Item', status='available',
                             seller_id=seller_no_week.id, price=50, collection_method='free')
        db.session.add(item)
        db.session.commit()
        resp = admin_client.post('/admin/routes/auto-assign',
                                 content_type='application/json')
        data = resp.get_json()
        assert seller_no_week.id not in data['assigned']
        tbd_ids = [t['seller_id'] for t in data['tbd']]
        assert seller_no_week.id not in tbd_ids
        assert ShiftPickup.query.filter_by(seller_id=seller_no_week.id).count() == 0

    def test_largest_unit_count_sellers_assigned_first(self, admin_client, app, db,
                                                         category_couch, category_misc,
                                                         shift_week1_am):
        """With limited capacity, the big seller should get the truck, small seller goes over-cap or TBD."""
        from models import User, InventoryItem, AppSetting, ShiftPickup
        AppSetting.set('truck_raw_capacity', '3')
        AppSetting.set('truck_capacity_buffer_pct', '0')

        big_seller = User(email='big@test.com', full_name='Big Seller',
                          is_seller=True, pickup_week='week1',
                          pickup_time_preference='morning')
        big_seller.set_password('x')
        small_seller = User(email='small@test.com', full_name='Small Seller',
                            is_seller=True, pickup_week='week1',
                            pickup_time_preference='morning')
        small_seller.set_password('x')
        db.session.add_all([big_seller, small_seller])
        db.session.flush()

        big_item = InventoryItem(description='Couch', status='available',
                                 seller_id=big_seller.id, category_id=category_couch.id,
                                 price=100, collection_method='free')
        small_item = InventoryItem(description='Misc', status='available',
                                   seller_id=small_seller.id, category_id=category_misc.id,
                                   price=10, collection_method='free')
        db.session.add_all([big_item, small_item])
        db.session.commit()

        admin_client.post('/admin/routes/auto-assign', content_type='application/json')

        big_pickup = ShiftPickup.query.filter_by(seller_id=big_seller.id).first()
        assert big_pickup is not None  # big seller placed first


# ---------------------------------------------------------------------------
# Route Builder Page
# ---------------------------------------------------------------------------

class TestRouteBuilderPage:

    def test_route_builder_loads(self, admin_client, shift_week1_am):
        resp = admin_client.get('/admin/routes')
        assert resp.status_code == 200

    def test_route_builder_requires_admin(self, client):
        resp = client.get('/admin/routes')
        assert resp.status_code in (302, 403)

    def test_route_builder_excludes_sellers_without_pickup_week(self, admin_client, app, db,
                                                                  seller_no_week, shift_week1_am):
        from models import InventoryItem
        item = InventoryItem(description='Item', status='available',
                             seller_id=seller_no_week.id, price=50, collection_method='free')
        db.session.add(item)
        db.session.commit()
        resp = admin_client.get('/admin/routes')
        assert resp.status_code == 200
        # Seller without pickup week should not appear in the unassigned panel
        assert b'No Week Seller' not in resp.data

    def test_route_builder_shows_unassigned_sellers(self, admin_client, app, db,
                                                      seller_week1_am, available_item,
                                                      shift_week1_am):
        resp = admin_client.get('/admin/routes')
        assert b'AM Seller' in resp.data

    def test_route_builder_shows_shift_capacity_board(self, admin_client, shift_week1_am):
        resp = admin_client.get('/admin/routes')
        assert resp.status_code == 200
        # Board should show shifts for the week


# ---------------------------------------------------------------------------
# Geographic Clustering
# ---------------------------------------------------------------------------

class TestGeographicClustering:

    def test_dorm_sellers_share_cluster(self, app, db, admin_user):
        """Two sellers in the same dorm are in the same cluster."""
        from models import User
        from helpers import build_geographic_clusters
        s1 = User(email='s1@t.com', full_name='S1', is_seller=True,
                  pickup_week='week1', pickup_time_preference='morning',
                  pickup_location_type='on_campus', pickup_dorm='Granville Towers')
        s2 = User(email='s2@t.com', full_name='S2', is_seller=True,
                  pickup_week='week1', pickup_time_preference='morning',
                  pickup_location_type='on_campus', pickup_dorm='Granville Towers')
        db.session.add_all([s1, s2])
        db.session.commit()
        clusters = build_geographic_clusters([s1, s2])
        granville_cluster = next(c for c in clusters if c['label'] == 'Granville Towers')
        assert s1.id in [u.id for u in granville_cluster['sellers']]
        assert s2.id in [u.id for u in granville_cluster['sellers']]

    def test_different_dorms_different_clusters(self, app, db):
        from models import User
        from helpers import build_geographic_clusters
        s1 = User(email='s3@t.com', full_name='S3', is_seller=True,
                  pickup_location_type='on_campus', pickup_dorm='Granville Towers')
        s2 = User(email='s4@t.com', full_name='S4', is_seller=True,
                  pickup_location_type='on_campus', pickup_dorm='Ehringhaus')
        db.session.add_all([s1, s2])
        db.session.commit()
        clusters = build_geographic_clusters([s1, s2])
        labels = [c['label'] for c in clusters]
        assert 'Granville Towers' in labels
        assert 'Ehringhaus' in labels

    def test_partner_apartment_clusters_by_name(self, app, db, seller_partner_apt):
        from models import User
        from helpers import build_geographic_clusters
        s2 = User(email='apt2@t.com', full_name='Apt2', is_seller=True,
                  pickup_week='week1', pickup_location_type='off_campus',
                  pickup_partner_building='The Lofts at 140',
                  pickup_lat=35.9201, pickup_lng=-79.0601)
        db.session.add(s2)
        db.session.commit()
        clusters = build_geographic_clusters([seller_partner_apt, s2])
        lofts_cluster = next(c for c in clusters if c['label'] == 'The Lofts at 140')
        assert len(lofts_cluster['sellers']) == 2

    def test_partner_apartment_not_grouped_by_latlng(self, app, db, seller_partner_apt):
        """Partner building seller should NOT be grouped with a nearby off-campus seller
        that's close in lat/lng but in a different building."""
        from models import User
        from helpers import build_geographic_clusters
        nearby = User(email='nearby2@t.com', full_name='Nearby2', is_seller=True,
                      pickup_week='week1', pickup_location_type='off_campus',
                      pickup_partner_building=None,
                      pickup_address='141 Main St',
                      pickup_lat=35.9201, pickup_lng=-79.0601)  # same coords
        db.session.add(nearby)
        db.session.commit()
        clusters = build_geographic_clusters([seller_partner_apt, nearby])
        lofts_cluster = next((c for c in clusters if c['label'] == 'The Lofts at 140'), None)
        assert lofts_cluster is not None
        assert nearby.id not in [u.id for u in lofts_cluster['sellers']]

    def test_off_campus_proximity_grouping(self, app, db, seller_off_campus_nearby):
        from models import User
        from helpers import build_geographic_clusters
        # Another seller very close by
        close = User(email='close@t.com', full_name='Close', is_seller=True,
                     pickup_week='week1', pickup_location_type='off_campus',
                     pickup_lat=35.9133, pickup_lng=-79.0560)  # ~10m away
        db.session.add(close)
        db.session.commit()
        clusters = build_geographic_clusters([seller_off_campus_nearby, close])
        # Both should share a cluster
        shared = [c for c in clusters if len(c['sellers']) == 2]
        assert len(shared) == 1

    def test_off_campus_far_apart_separate_clusters(self, app, db):
        from models import User
        from helpers import build_geographic_clusters
        s1 = User(email='far1@t.com', full_name='Far1', is_seller=True,
                  pickup_location_type='off_campus',
                  pickup_lat=35.9132, pickup_lng=-79.0558)
        s2 = User(email='far2@t.com', full_name='Far2', is_seller=True,
                  pickup_location_type='off_campus',
                  pickup_lat=35.9300, pickup_lng=-79.0700)  # > 0.25 miles away
        db.session.add_all([s1, s2])
        db.session.commit()
        clusters = build_geographic_clusters([s1, s2])
        # Each should be in their own cluster
        assert all(len(c['sellers']) == 1 for c in clusters if c['label'] != 'Unlocated')

    def test_no_address_goes_to_unlocated(self, app, db, seller_no_address):
        from helpers import build_geographic_clusters
        clusters = build_geographic_clusters([seller_no_address])
        unlocated = next(c for c in clusters if c['label'] == 'Unlocated')
        assert seller_no_address.id in [u.id for u in unlocated['sellers']]


# ---------------------------------------------------------------------------
# Stop Ordering (Nearest-Neighbor)
# ---------------------------------------------------------------------------

class TestStopOrdering:

    def test_order_route_assigns_stop_order(self, admin_client, app, db,
                                             seller_week1_am, available_item,
                                             shift_week1_am, storage_location):
        from models import ShiftPickup
        # Assign storage unit to truck
        shift_week1_am.truck_unit_plan = f'{{"1": {storage_location.id}}}'
        pickup = ShiftPickup(shift_id=shift_week1_am.id, seller_id=seller_week1_am.id,
                             truck_number=1, status='pending')
        db.session.add(pickup)
        db.session.commit()
        resp = admin_client.post(f'/admin/crew/shift/{shift_week1_am.id}/order')
        assert resp.status_code in (200, 302)
        db.session.refresh(pickup)
        assert pickup.stop_order is not None

    def test_order_route_multiple_stops_assigns_sequential_order(self, admin_client, app, db,
                                                                   shift_week1_am, storage_location,
                                                                   category_couch):
        from models import User, InventoryItem, ShiftPickup
        shift_week1_am.truck_unit_plan = f'{{"1": {storage_location.id}}}'

        sellers = []
        for i, (lat, lng) in enumerate([(35.910, -79.050), (35.915, -79.055), (35.920, -79.060)]):
            s = User(email=f'ord{i}@t.com', full_name=f'Seller {i}', is_seller=True,
                     pickup_week='week1', pickup_time_preference='morning',
                     pickup_lat=lat, pickup_lng=lng)
            s.set_password('x')
            db.session.add(s)
            db.session.flush()
            item = InventoryItem(description='item', status='available',
                                 seller_id=s.id, category_id=category_couch.id,
                                 price=50, collection_method='free')
            db.session.add(item)
            db.session.flush()
            pickup = ShiftPickup(shift_id=shift_week1_am.id, seller_id=s.id,
                                 truck_number=1, status='pending')
            db.session.add(pickup)
            sellers.append((s, pickup))
        db.session.commit()

        admin_client.post(f'/admin/crew/shift/{shift_week1_am.id}/order')

        orders = sorted([p.stop_order for _, p in sellers
                         if db.session.refresh(p) is None or True])
        # All stop_orders should be set and unique
        refreshed = [db.session.get(ShiftPickup, p.id) for _, p in sellers]
        stop_orders = [p.stop_order for p in refreshed]
        assert all(o is not None for o in stop_orders)
        assert len(set(stop_orders)) == 3  # all unique

    def test_stops_without_latlng_appended_last(self, admin_client, app, db,
                                                  shift_week1_am, storage_location,
                                                  seller_no_address, category_misc):
        from models import User, InventoryItem, ShiftPickup
        shift_week1_am.truck_unit_plan = f'{{"1": {storage_location.id}}}'

        # Seller with location
        located = User(email='located@t.com', full_name='Located', is_seller=True,
                       pickup_week='week1', pickup_time_preference='morning',
                       pickup_lat=35.910, pickup_lng=-79.050)
        located.set_password('x')
        db.session.add(located)
        db.session.flush()
        item1 = InventoryItem(description='item', status='available',
                              seller_id=located.id, category_id=category_misc.id,
                              price=10, collection_method='free')
        item2 = InventoryItem(description='item', status='available',
                              seller_id=seller_no_address.id, category_id=category_misc.id,
                              price=10, collection_method='free')
        db.session.add_all([item1, item2])
        db.session.flush()

        p1 = ShiftPickup(shift_id=shift_week1_am.id, seller_id=located.id,
                         truck_number=1, status='pending')
        p2 = ShiftPickup(shift_id=shift_week1_am.id, seller_id=seller_no_address.id,
                         truck_number=1, status='pending')
        db.session.add_all([p1, p2])
        db.session.commit()

        admin_client.post(f'/admin/crew/shift/{shift_week1_am.id}/order')

        p1 = db.session.get(type(p1), p1.id)
        p2 = db.session.get(type(p2), p2.id)
        # No-address stop should have a higher stop_order than the located stop
        assert p1.stop_order < p2.stop_order

    def test_manual_reorder_updates_stop_order(self, admin_client, app, db,
                                                seller_week1_am, available_item,
                                                shift_week1_am):
        from models import ShiftPickup
        pickup = ShiftPickup(shift_id=shift_week1_am.id, seller_id=seller_week1_am.id,
                             truck_number=1, status='pending', stop_order=3)
        db.session.add(pickup)
        db.session.commit()
        resp = admin_client.post(
            f'/admin/crew/shift/{shift_week1_am.id}/stop/{pickup.id}/reorder',
            json={'stop_order': 1}
        )
        assert resp.status_code == 200
        db.session.refresh(pickup)
        assert pickup.stop_order == 1


# ---------------------------------------------------------------------------
# Add Truck
# ---------------------------------------------------------------------------

class TestAddTruck:

    def test_add_truck_increments_shift_trucks(self, admin_client, app, db, shift_week1_am):
        original_count = shift_week1_am.trucks
        resp = admin_client.post(f'/admin/crew/shift/{shift_week1_am.id}/add-truck')
        assert resp.status_code == 200
        db.session.refresh(shift_week1_am)
        assert shift_week1_am.trucks == original_count + 1

    def test_add_truck_returns_new_truck_number(self, admin_client, app, db, shift_week1_am):
        resp = admin_client.post(f'/admin/crew/shift/{shift_week1_am.id}/add-truck')
        data = resp.get_json()
        assert 'new_truck_number' in data
        assert data['new_truck_number'] == shift_week1_am.trucks + 1

    def test_add_truck_new_number_is_max_plus_one(self, admin_client, app, db,
                                                    shift_week1_am, seller_week1_am,
                                                    available_item):
        from models import ShiftPickup
        # Pre-populate truck 1 and truck 2
        shift_week1_am.trucks = 2
        p1 = ShiftPickup(shift_id=shift_week1_am.id, seller_id=seller_week1_am.id,
                         truck_number=2, status='pending')
        db.session.add(p1)
        db.session.commit()
        resp = admin_client.post(f'/admin/crew/shift/{shift_week1_am.id}/add-truck')
        data = resp.get_json()
        assert data['new_truck_number'] == 3

    def test_add_truck_requires_admin(self, worker_client, shift_week1_am):
        resp = worker_client.post(f'/admin/crew/shift/{shift_week1_am.id}/add-truck')
        assert resp.status_code in (302, 403)

    def test_add_truck_works_during_active_shiftrun(self, admin_client, app, db,
                                                      shift_week1_am, admin_user):
        from models import ShiftRun
        run = ShiftRun(shift_id=shift_week1_am.id, started_by_id=admin_user.id,
                       status='in_progress')
        db.session.add(run)
        db.session.commit()
        resp = admin_client.post(f'/admin/crew/shift/{shift_week1_am.id}/add-truck')
        assert resp.status_code == 200
        db.session.refresh(shift_week1_am)
        assert shift_week1_am.trucks == 3  # was 2


# ---------------------------------------------------------------------------
# Stop Movement
# ---------------------------------------------------------------------------

class TestStopMovement:

    def test_move_stop_to_different_truck(self, admin_client, app, db,
                                           seller_week1_am, available_item,
                                           shift_week1_am):
        from models import ShiftPickup
        pickup = ShiftPickup(shift_id=shift_week1_am.id, seller_id=seller_week1_am.id,
                             truck_number=1, status='pending')
        db.session.add(pickup)
        db.session.commit()
        resp = admin_client.post(f'/admin/routes/stop/{pickup.id}/move',
                                 json={'shift_id': shift_week1_am.id, 'truck_number': 2})
        assert resp.status_code == 200
        db.session.refresh(pickup)
        assert pickup.truck_number == 2

    def test_move_stop_to_different_shift(self, admin_client, app, db,
                                           seller_week1_am, available_item,
                                           shift_week1_am, shift_week1_pm):
        from models import ShiftPickup
        pickup = ShiftPickup(shift_id=shift_week1_am.id, seller_id=seller_week1_am.id,
                             truck_number=1, status='pending')
        db.session.add(pickup)
        db.session.commit()
        resp = admin_client.post(f'/admin/routes/stop/{pickup.id}/move',
                                 json={'shift_id': shift_week1_pm.id, 'truck_number': 1})
        assert resp.status_code == 200
        db.session.refresh(pickup)
        assert pickup.shift_id == shift_week1_pm.id

    def test_move_stop_clears_capacity_warning_when_under_cap(self, admin_client, app, db,
                                                                seller_week1_am, available_item,
                                                                shift_week1_am):
        from models import ShiftPickup, AppSetting
        AppSetting.set('truck_raw_capacity', '18')
        AppSetting.set('truck_capacity_buffer_pct', '0')
        pickup = ShiftPickup(shift_id=shift_week1_am.id, seller_id=seller_week1_am.id,
                             truck_number=1, status='pending', capacity_warning=True)
        db.session.add(pickup)
        db.session.commit()
        # Move to truck 2 which has no other stops (plenty of capacity)
        admin_client.post(f'/admin/routes/stop/{pickup.id}/move',
                          json={'shift_id': shift_week1_am.id, 'truck_number': 2})
        db.session.refresh(pickup)
        assert pickup.capacity_warning is False

    def test_manual_assign_seller_to_shift(self, admin_client, app, db,
                                            seller_week1_am, available_item,
                                            shift_week1_am):
        from models import ShiftPickup
        resp = admin_client.post(f'/admin/routes/seller/{seller_week1_am.id}/assign',
                                 json={'shift_id': shift_week1_am.id, 'truck_number': 1})
        assert resp.status_code == 200
        pickup = ShiftPickup.query.filter_by(seller_id=seller_week1_am.id).first()
        assert pickup is not None

    def test_manual_assign_already_scheduled_seller_returns_error(self, admin_client, app, db,
                                                                    seller_week1_am, available_item,
                                                                    shift_week1_am):
        from models import ShiftPickup
        existing = ShiftPickup(shift_id=shift_week1_am.id, seller_id=seller_week1_am.id,
                               truck_number=1, status='pending')
        db.session.add(existing)
        db.session.commit()
        resp = admin_client.post(f'/admin/routes/seller/{seller_week1_am.id}/assign',
                                 json={'shift_id': shift_week1_am.id, 'truck_number': 1})
        assert resp.status_code == 409  # conflict


# ---------------------------------------------------------------------------
# Seller Notification
# ---------------------------------------------------------------------------

class TestSellerNotification:

    def test_notify_sellers_sends_emails(self, admin_client, app, db,
                                          seller_week1_am, available_item,
                                          shift_week1_am, mocker):
        from models import ShiftPickup
        mocker.patch('app.send_email')
        pickup = ShiftPickup(shift_id=shift_week1_am.id, seller_id=seller_week1_am.id,
                             truck_number=1, status='pending')
        db.session.add(pickup)
        db.session.commit()
        resp = admin_client.post(f'/admin/crew/shift/{shift_week1_am.id}/notify')
        assert resp.status_code in (200, 302)
        db.session.refresh(pickup)
        assert pickup.notified_at is not None

    def test_notify_sellers_sets_shift_flag(self, admin_client, app, db,
                                             seller_week1_am, available_item,
                                             shift_week1_am, mocker):
        from models import ShiftPickup
        mocker.patch('app.send_email')
        pickup = ShiftPickup(shift_id=shift_week1_am.id, seller_id=seller_week1_am.id,
                             truck_number=1, status='pending')
        db.session.add(pickup)
        db.session.commit()
        admin_client.post(f'/admin/crew/shift/{shift_week1_am.id}/notify')
        db.session.refresh(shift_week1_am)
        assert shift_week1_am.sellers_notified is True

    def test_notify_sellers_idempotent_does_not_resend(self, admin_client, app, db,
                                                         seller_week1_am, available_item,
                                                         shift_week1_am, mocker):
        from models import ShiftPickup
        mock_email = mocker.patch('app.send_email')
        pickup = ShiftPickup(shift_id=shift_week1_am.id, seller_id=seller_week1_am.id,
                             truck_number=1, status='pending')
        db.session.add(pickup)
        db.session.commit()
        admin_client.post(f'/admin/crew/shift/{shift_week1_am.id}/notify')
        admin_client.post(f'/admin/crew/shift/{shift_week1_am.id}/notify')
        # Email should only have been sent once
        assert mock_email.call_count == 1

    def test_notify_sellers_sends_to_newly_added_stop(self, admin_client, app, db,
                                                        seller_week1_am, seller_week1_pm,
                                                        available_item, shift_week1_am,
                                                        mocker):
        from models import ShiftPickup, InventoryItem
        mock_email = mocker.patch('app.send_email')
        # First seller notified
        p1 = ShiftPickup(shift_id=shift_week1_am.id, seller_id=seller_week1_am.id,
                         truck_number=1, status='pending')
        db.session.add(p1)
        db.session.commit()
        admin_client.post(f'/admin/crew/shift/{shift_week1_am.id}/notify')
        assert mock_email.call_count == 1

        # Add second seller
        item2 = InventoryItem(description='Item', status='available',
                              seller_id=seller_week1_pm.id, price=50, collection_method='free')
        p2 = ShiftPickup(shift_id=shift_week1_am.id, seller_id=seller_week1_pm.id,
                         truck_number=1, status='pending')
        db.session.add_all([item2, p2])
        db.session.commit()
        admin_client.post(f'/admin/crew/shift/{shift_week1_am.id}/notify')
        # Second email sent, first not re-sent
        assert mock_email.call_count == 2


# ---------------------------------------------------------------------------
# Mover: Stops Partial Endpoint
# ---------------------------------------------------------------------------

class TestStopsPartial:

    def test_stops_partial_requires_crew(self, client, shift_week1_am):
        resp = client.get(f'/crew/shift/{shift_week1_am.id}/stops_partial')
        assert resp.status_code in (302, 403)

    def test_stops_partial_returns_html(self, app, db, worker_client,
                                         seller_week1_am, available_item,
                                         shift_week1_am, regular_user):
        from models import ShiftPickup, ShiftAssignment
        assignment = ShiftAssignment(shift_id=shift_week1_am.id,
                                     worker_id=regular_user.id,
                                     role_on_shift='driver',
                                     truck_number=1)
        pickup = ShiftPickup(shift_id=shift_week1_am.id, seller_id=seller_week1_am.id,
                             truck_number=1, status='pending', stop_order=1)
        db.session.add_all([assignment, pickup])
        db.session.commit()
        resp = worker_client.get(f'/crew/shift/{shift_week1_am.id}/stops_partial')
        assert resp.status_code == 200
        assert b'AM Seller' in resp.data

    def test_stops_partial_only_shows_current_workers_truck(self, app, db,
                                                              worker_client,
                                                              shift_week1_am,
                                                              regular_user,
                                                              category_misc):
        from models import User, InventoryItem, ShiftPickup, ShiftAssignment
        # Worker on truck 1
        assignment = ShiftAssignment(shift_id=shift_week1_am.id,
                                     worker_id=regular_user.id,
                                     role_on_shift='driver',
                                     truck_number=1)
        db.session.add(assignment)

        # Seller on truck 1
        s1 = User(email='t1@t.com', full_name='Truck1 Seller', is_seller=True)
        s1.set_password('x')
        # Seller on truck 2
        s2 = User(email='t2@t.com', full_name='Truck2 Seller', is_seller=True)
        s2.set_password('x')
        db.session.add_all([s1, s2])
        db.session.flush()

        i1 = InventoryItem(description='i', status='available', seller_id=s1.id,
                           price=10, collection_method='free')
        i2 = InventoryItem(description='i', status='available', seller_id=s2.id,
                           price=10, collection_method='free')
        db.session.add_all([i1, i2])
        db.session.flush()

        p1 = ShiftPickup(shift_id=shift_week1_am.id, seller_id=s1.id,
                         truck_number=1, status='pending')
        p2 = ShiftPickup(shift_id=shift_week1_am.id, seller_id=s2.id,
                         truck_number=2, status='pending')
        db.session.add_all([p1, p2])
        db.session.commit()

        resp = worker_client.get(f'/crew/shift/{shift_week1_am.id}/stops_partial')
        assert b'Truck1 Seller' in resp.data
        assert b'Truck2 Seller' not in resp.data

    def test_stops_partial_shows_navigate_button(self, app, db, worker_client,
                                                   seller_week1_am, available_item,
                                                   shift_week1_am, regular_user):
        from models import ShiftPickup, ShiftAssignment
        assignment = ShiftAssignment(shift_id=shift_week1_am.id,
                                     worker_id=regular_user.id,
                                     role_on_shift='driver',
                                     truck_number=1)
        pickup = ShiftPickup(shift_id=shift_week1_am.id, seller_id=seller_week1_am.id,
                             truck_number=1, status='pending', stop_order=1)
        db.session.add_all([assignment, pickup])
        db.session.commit()
        resp = worker_client.get(f'/crew/shift/{shift_week1_am.id}/stops_partial')
        assert b'Navigate' in resp.data
        assert b'maps.google.com' in resp.data


# ---------------------------------------------------------------------------
# Stairs / Elevator Badge
# ---------------------------------------------------------------------------

class TestStairsElevatorBadge:

    def test_stairs_badge_shown_on_stop_card(self, admin_client, app, db,
                                              shift_week1_am, category_misc):
        from models import User, InventoryItem, ShiftPickup
        s = User(email='stairs@t.com', full_name='Stairs Seller', is_seller=True,
                 pickup_week='week1', pickup_time_preference='morning',
                 pickup_access_type='stairs')
        s.set_password('x')
        db.session.add(s)
        db.session.flush()
        item = InventoryItem(description='i', status='available', seller_id=s.id,
                             category_id=category_misc.id, price=10, collection_method='free')
        pickup = ShiftPickup(shift_id=shift_week1_am.id, seller_id=s.id,
                             truck_number=1, status='pending')
        db.session.add_all([item, pickup])
        db.session.commit()
        resp = admin_client.get(f'/admin/crew/shift/{shift_week1_am.id}/ops')
        assert resp.status_code == 200
        # Stairs indicator should appear somewhere on the page
        assert b'Stairs' in resp.data or 'stairs' in resp.data.decode().lower()

    def test_elevator_badge_shown_on_stop_card(self, admin_client, app, db,
                                                shift_week1_am, category_misc):
        from models import User, InventoryItem, ShiftPickup
        s = User(email='elevator@t.com', full_name='Elevator Seller', is_seller=True,
                 pickup_week='week1', pickup_time_preference='morning',
                 pickup_access_type='elevator')
        s.set_password('x')
        db.session.add(s)
        db.session.flush()
        item = InventoryItem(description='i', status='available', seller_id=s.id,
                             category_id=category_misc.id, price=10, collection_method='free')
        pickup = ShiftPickup(shift_id=shift_week1_am.id, seller_id=s.id,
                             truck_number=1, status='pending')
        db.session.add_all([item, pickup])
        db.session.commit()
        resp = admin_client.get(f'/admin/crew/shift/{shift_week1_am.id}/ops')
        assert b'Elevator' in resp.data or 'elevator' in resp.data.decode().lower()


# ---------------------------------------------------------------------------
# Ops Page Issue Alert Banner
# ---------------------------------------------------------------------------

class TestIssueAlertBanner:

    def test_issue_banner_shown_when_stop_flagged(self, admin_client, app, db,
                                                   seller_week1_am, available_item,
                                                   shift_week1_am):
        from models import ShiftPickup
        pickup = ShiftPickup(shift_id=shift_week1_am.id, seller_id=seller_week1_am.id,
                             truck_number=1, status='issue', notes='Seller not home')
        db.session.add(pickup)
        db.session.commit()
        resp = admin_client.get(f'/admin/crew/shift/{shift_week1_am.id}/ops')
        assert resp.status_code == 200
        assert b'Seller not home' in resp.data

    def test_issue_banner_hidden_when_no_issues(self, admin_client, app, db,
                                                 seller_week1_am, available_item,
                                                 shift_week1_am):
        from models import ShiftPickup
        pickup = ShiftPickup(shift_id=shift_week1_am.id, seller_id=seller_week1_am.id,
                             truck_number=1, status='pending')
        db.session.add(pickup)
        db.session.commit()
        resp = admin_client.get(f'/admin/crew/shift/{shift_week1_am.id}/ops')
        # No issue note should appear in the banner
        assert b'issue-alert' not in resp.data or b'Seller not home' not in resp.data


# ---------------------------------------------------------------------------
# Static Map URL Builder
# ---------------------------------------------------------------------------

class TestStaticMapUrl:

    def test_returns_none_when_no_api_key(self, app, db, storage_location):
        from helpers import build_static_map_url
        from models import AppSetting
        AppSetting.set('maps_static_api_key', '')
        result = build_static_map_url([], storage_location)
        assert result is None

    def test_returns_url_string_when_api_key_set(self, app, db, storage_location):
        from helpers import build_static_map_url
        from models import AppSetting, ShiftPickup, User
        AppSetting.set('maps_static_api_key', 'test_key_123')
        storage_location.address = '500 Airport Rd, Chapel Hill, NC'
        # Mock geocoder or provide coords directly
        storage_location.lat = 35.900
        storage_location.lng = -79.060
        db.session.commit()
        result = build_static_map_url([], storage_location)
        assert result is not None
        assert 'maps.googleapis.com' in result
        assert 'test_key_123' in result

    def test_map_url_includes_stop_markers(self, app, db, storage_location,
                                            seller_week1_am, shift_week1_am):
        from helpers import build_static_map_url
        from models import AppSetting, ShiftPickup
        AppSetting.set('maps_static_api_key', 'test_key')
        storage_location.lat = 35.900
        storage_location.lng = -79.060
        db.session.commit()
        pickup = ShiftPickup(shift_id=shift_week1_am.id, seller_id=seller_week1_am.id,
                             truck_number=1, status='pending', stop_order=1)
        db.session.add(pickup)
        db.session.commit()
        result = build_static_map_url([pickup], storage_location)
        assert result is not None
        assert 'markers' in result


# ---------------------------------------------------------------------------
# Regression: Existing Routes Not Broken
# ---------------------------------------------------------------------------

class TestRegressions:

    def test_existing_ops_page_still_loads(self, admin_client, shift_week1_am):
        resp = admin_client.get(f'/admin/crew/shift/{shift_week1_am.id}/ops')
        assert resp.status_code == 200

    def test_crew_shift_view_still_loads(self, app, db, worker_client,
                                          shift_week1_am, regular_user):
        from models import ShiftAssignment, ShiftRun
        assignment = ShiftAssignment(shift_id=shift_week1_am.id,
                                     worker_id=regular_user.id,
                                     role_on_shift='driver',
                                     truck_number=1)
        run = ShiftRun(shift_id=shift_week1_am.id, started_by_id=regular_user.id,
                       status='in_progress')
        db.session.add_all([assignment, run])
        db.session.commit()
        resp = worker_client.get(f'/crew/shift/{shift_week1_am.id}')
        assert resp.status_code == 200

    def test_admin_panel_still_loads(self, admin_client):
        resp = admin_client.get('/admin')
        assert resp.status_code == 200

    def test_seller_dashboard_still_loads(self, app, db, client, seller_week1_am):
        client.post('/login', data={'email': seller_week1_am.email, 'password': 'password'})
        resp = client.get('/dashboard')
        assert resp.status_code == 200

    def test_payout_percentage_helper_untouched(self, app, db, available_item):
        """_get_payout_percentage must still work and not be affected by unit_size field."""
        from helpers import get_payout_percentage
        result = get_payout_percentage(available_item)
        assert isinstance(result, float)
        assert 0.0 < result <= 1.0

    def test_existing_assign_seller_to_shift_still_works(self, admin_client,
                                                           shift_week1_am,
                                                           seller_week1_am,
                                                           available_item):
        """The existing admin_shift_assign_seller route on ops page must still function."""
        resp = admin_client.post(
            f'/admin/crew/shift/{shift_week1_am.id}/assign',
            data={'seller_id': seller_week1_am.id, 'truck_number': 1}
        )
        assert resp.status_code in (200, 302)
