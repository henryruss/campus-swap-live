"""Integration tests for the Warehouse Floor addendum:
Unit Efficiency, Cost Tracking & Consolidation.

Run: python -m pytest test_warehouse_cost_addendum.py -v
"""
import pytest
from app import app as _app, db
from models import User, StorageLocation, InventoryItem, InventoryCategory
from werkzeug.security import generate_password_hash


# Reuse the conftest fixtures (client, test_admin_user, admin_client)
from tests.conftest import client, test_admin_user, admin_client  # noqa: F401


@pytest.fixture
def director_client(client):
    """A non-super admin (ops access, NOT super admin) — must never see $.
    Uses is_admin (not is_campus_director) to avoid the CD tutorial redirect
    gate; the cost-visibility check keys on current_user.is_super_admin, which
    is False for both."""
    with client.application.app_context():
        cd = User(
            email='admin2@test.com', full_name='Dir', password_hash=generate_password_hash('x'),
            is_admin=True, is_super_admin=False,
        )
        db.session.add(cd)
        db.session.commit()
        cid = cd.id
    with client.session_transaction() as sess:
        sess['_user_id'] = str(cid)
        sess['_fresh'] = True
    return client


def _mk_units():
    """Create 3 rankable units (distinct cost/sqft) + 1 unranked. Returns ids."""
    u1 = StorageLocation(name='Unit A', size_sqft=300.0, monthly_cost=120, is_active=True)  # 0.40
    u2 = StorageLocation(name='Unit B', size_sqft=250.0, monthly_cost=150, is_active=True)  # 0.60
    u3 = StorageLocation(name='Unit C', size_sqft=200.0, monthly_cost=180, is_active=True)  # 0.90
    u4 = StorageLocation(name='Unit D', is_active=True)                                      # unranked
    db.session.add_all([u1, u2, u3, u4])
    db.session.commit()
    return u1.id, u2.id, u3.id, u4.id


# ── Model properties ──

def test_cost_per_sqft_and_size_display(client):
    with client.application.app_context():
        loc = StorageLocation(name='X', size_sqft=300.0, monthly_cost=180)
        assert abs(loc.cost_per_sqft - 0.6) < 1e-9
        assert loc.size_display == '300 sq ft'
        # Missing either field => None
        loc2 = StorageLocation(name='Y', size_sqft=300.0, monthly_cost=None)
        assert loc2.cost_per_sqft is None
        loc3 = StorageLocation(name='Z', size_sqft=None, monthly_cost=180)
        assert loc3.cost_per_sqft is None
        assert loc3.size_display is None


# ── Warehouse page: cost visibility gated by super admin ──

def test_super_admin_sees_dollars_on_cards(admin_client):
    with admin_client.application.app_context():
        _mk_units()
    r = admin_client.get('/admin/warehouse')
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert '/sqft' in body and '/mo' in body
    assert 'Best Value' in body
    assert 'Expensive' in body


def test_director_never_sees_dollars(director_client):
    with director_client.application.app_context():
        _mk_units()
    r = director_client.get('/admin/warehouse')
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert '/sqft' not in body
    assert '/mo' not in body
    # Priority badges ARE visible to all users
    assert 'Best Value' in body


def test_unit_partial_hides_cost_from_director(director_client):
    with director_client.application.app_context():
        ids = _mk_units()
    r = director_client.get(f'/admin/warehouse/unit/{ids[0]}')
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    # No rendered cost UI: the summary line + editable inputs are super-admin only.
    # ('/sqft' appears in the shared saveUnitCost JS string, so check the real
    # leak vectors instead — the cost summary div and the editable input fields.)
    assert 'id="whu-cost-summary-' not in body   # rendered cost line (super-admin only)
    assert 'class="whu-cost-fields"' not in body  # editable inputs block
    assert 'id="whu-size-' not in body
    assert 'No cost data set' not in body
    # but size label + priority ARE shown to all users
    assert 'sq ft' in body


def test_unit_partial_shows_editable_cost_to_super_admin(admin_client):
    with admin_client.application.app_context():
        ids = _mk_units()
    r = admin_client.get(f'/admin/warehouse/unit/{ids[0]}')
    body = r.get_data(as_text=True)
    assert 'id="whu-size-' in body and 'id="whu-cost-' in body  # rendered editable inputs
    assert 'class="whu-cost-fields"' in body
    assert '/sqft' in body


# ── Inline cost edit via storage edit route (ajax) ──

def test_storage_edit_ajax_updates_cost(admin_client):
    with admin_client.application.app_context():
        ids = _mk_units()
        target = ids[3]  # Unit D, no cost
    r = admin_client.post(f'/admin/storage/{target}/edit',
                          data={'ajax': '1', 'size_sqft': '10x20', 'monthly_cost': '200'})
    assert r.status_code == 200
    j = r.get_json()
    assert j['success'] is True
    assert j['size_sqft'] == 200.0
    assert j['monthly_cost'] == 200.0
    assert abs(j['cost_per_sqft'] - 1.0) < 1e-9
    with admin_client.application.app_context():
        loc = StorageLocation.query.get(target)
        assert loc.size_sqft == 200.0
        assert float(loc.monthly_cost) == 200.0


def test_storage_edit_zero_cost_becomes_null(admin_client):
    with admin_client.application.app_context():
        ids = _mk_units()
        target = ids[0]
    r = admin_client.post(f'/admin/storage/{target}/edit',
                          data={'ajax': '1', 'monthly_cost': '0'})
    j = r.get_json()
    assert j['monthly_cost'] is None  # 0 treated as null
    with admin_client.application.app_context():
        assert StorageLocation.query.get(target).monthly_cost is None


def test_storage_edit_partial_does_not_wipe_other_field(admin_client):
    """Editing only monthly_cost must not clear size_sqft (field absent)."""
    with admin_client.application.app_context():
        ids = _mk_units()
        target = ids[0]
    admin_client.post(f'/admin/storage/{target}/edit',
                      data={'ajax': '1', 'monthly_cost': '99'})
    with admin_client.application.app_context():
        loc = StorageLocation.query.get(target)
        assert loc.size_sqft == 300.0  # untouched
        assert float(loc.monthly_cost) == 99.0


# ── Bulk move ──

def test_bulk_move_moves_and_clears_row(admin_client):
    with admin_client.application.app_context():
        ids = _mk_units()
        src, dest = ids[0], ids[1]
        cat = InventoryCategory(name='Cat')
        db.session.add(cat); db.session.commit()
        i1 = InventoryItem(description='a', price=0, status='pending_valuation',
                           storage_location_id=src, storage_row='back_left')
        i2 = InventoryItem(description='b', price=0, status='available',
                           storage_location_id=src, storage_row='front_right')
        db.session.add_all([i1, i2]); db.session.commit()
        i1id, i2id = i1.id, i2.id

    r = admin_client.post('/admin/warehouse/bulk-move',
                          data={'destination_unit_id': dest, 'item_ids[]': [i1id, i2id]})
    assert r.status_code == 200
    j = r.get_json()
    assert j['success'] is True and j['moved_count'] == 2
    with admin_client.application.app_context():
        for iid in (i1id, i2id):
            it = InventoryItem.query.get(iid)
            assert it.storage_location_id == dest
            assert it.storage_row is None  # cleared


def test_bulk_move_empty_selection_400(admin_client):
    with admin_client.application.app_context():
        ids = _mk_units()
    r = admin_client.post('/admin/warehouse/bulk-move',
                          data={'destination_unit_id': ids[1]})
    assert r.status_code == 400


def test_bulk_move_skips_unknown_ids(admin_client):
    with admin_client.application.app_context():
        ids = _mk_units()
        dest = ids[1]
        i1 = InventoryItem(description='a', price=0, status='pending_valuation',
                           storage_location_id=ids[0])
        db.session.add(i1); db.session.commit()
        i1id = i1.id
    r = admin_client.post('/admin/warehouse/bulk-move',
                          data={'destination_unit_id': dest, 'item_ids[]': [i1id, 999999]})
    j = r.get_json()
    assert j['moved_count'] == 1  # unknown id skipped silently


# ── Import parsing ──

def test_import_template_has_monthly_rate(admin_client):
    r = admin_client.get('/admin/storage/template')
    assert r.status_code == 200
    assert 'Monthly Rate' in r.get_data(as_text=True)


def test_import_parses_size_and_cost(admin_client):
    import io
    csv_content = "Unit #,Location,Size,Monthly Rate\n900,Loc,10x30,180\n901,Loc,bad,\n"
    data = {'file': (io.BytesIO(csv_content.encode()), 'units.csv')}
    r = admin_client.post('/admin/storage/import', data=data,
                          content_type='multipart/form-data', follow_redirects=False)
    assert r.status_code in (302, 200)
    with admin_client.application.app_context():
        u900 = StorageLocation.query.filter_by(name='Unit 900').first()
        assert u900 is not None
        assert u900.size_sqft == 300.0
        assert float(u900.monthly_cost) == 180.0
        u901 = StorageLocation.query.filter_by(name='Unit 901').first()
        assert u901 is not None
        assert u901.size_sqft is None      # malformed size
        assert u901.monthly_cost is None   # blank rate


def test_import_updates_existing_without_wiping(admin_client):
    import io
    with admin_client.application.app_context():
        existing = StorageLocation(name='Unit 950', size_sqft=300.0, monthly_cost=120, is_active=True)
        db.session.add(existing); db.session.commit()
    # Sheet has only Size (no Monthly Rate column) — cost must be preserved
    csv_content = "Unit #,Location,Size\n950,Loc,10x40\n"
    data = {'file': (io.BytesIO(csv_content.encode()), 'units.csv')}
    admin_client.post('/admin/storage/import', data=data, content_type='multipart/form-data')
    with admin_client.application.app_context():
        u = StorageLocation.query.filter_by(name='Unit 950').first()
        assert u.size_sqft == 400.0           # updated
        assert float(u.monthly_cost) == 120.0  # NOT wiped (column absent)
