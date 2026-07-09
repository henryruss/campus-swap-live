"""Tests for feature_warehouse_rephotography — search-first guided three-shot capture.

Run with: python3 -m pytest test_warehouse_rephotography.py -v

Runs against campusswap_prod (the local prod snapshot with all migrations applied —
set by conftest.py). Deliberately does NOT use the conftest `app` fixture: that
fixture's SQLite override never takes effect (the engine is already bound to
Postgres at import time), so its create_all/drop_all would wipe campusswap_prod.
All data here is unique-tagged instead.

Coverage:
- ItemPhoto model columns (captured_at / sort_order / view) + gallery ordering
- Auth: campus director allowed, approved worker & anonymous blocked
- Synonym-expanded search (couch→sofa, fridge→refrigerator, category-name match)
- sold exclusion, un-reshot-first ordering, ✓ badge rendering
- Stub creation (add path) defaults
- Photo add: view/captured_at/sort_order, cover + ai_generated_at untouched,
  server-side downscale bound, filename convention, validation errors
- Details: category required, three seller modes, proxy at payout_rate=50,
  storage stays NULL, AI enqueue, non-QC guard
- Photo delete: campaign-only guard
- Log Item regression after proxy-helper extraction
"""

import io
import queue
import uuid
from datetime import datetime, timedelta

import pytest
from PIL import Image


def _uid():
    return uuid.uuid4().hex[:8]


def _jpeg_bytes(width=800, height=600, color=(120, 90, 60)):
    img = Image.new('RGB', (width, height), color)
    buf = io.BytesIO()
    img.save(buf, 'JPEG', quality=90)
    buf.seek(0)
    return buf


class StorageStub:
    """Records saves/deletes in memory so tests never touch disk/S3."""

    def __init__(self):
        self.saved = {}
        self.deleted = []

    def save_photo_from_bytes(self, data, key):
        self.saved[key] = data
        return key

    def delete_photo(self, key):
        self.deleted.append(key)
        return True


@pytest.fixture
def client():
    """Fresh test client per test against campusswap_prod (no cookie carry-over).

    Deliberately NOT used as a context manager — preserved request contexts
    leak login state between tests under the patched AppContext.pop."""
    from app import app as _app
    _app.config['TESTING'] = True
    _app.config['WTF_CSRF_ENABLED'] = False
    return _app.test_client()


@pytest.fixture
def db():
    """App-context-wrapped db handle for direct queries in test bodies."""
    from app import app as _app, db as _db
    with _app.app_context():
        yield _db
        _db.session.remove()


@pytest.fixture
def storage_stub(monkeypatch):
    import app as app_module
    stub = StorageStub()
    monkeypatch.setattr(app_module, 'photo_storage', stub)
    return stub


@pytest.fixture
def ai_queue_stub(monkeypatch):
    import app as app_module
    q = queue.Queue()
    monkeypatch.setattr(app_module, '_ai_queue', q)
    return q


@pytest.fixture
def director(db):
    from models import User, TutorialSession
    u = User(
        email=f'cd_{_uid()}@test.com',
        full_name='Rephoto Test Director',
        password_hash='x',
        is_campus_director=True,
    )
    db.session.add(u)
    db.session.flush()
    # Completed tutorial so the CD tutorial_gate doesn't redirect /admin/* requests
    db.session.add(TutorialSession(user_id=u.id, step=9, completed_at=datetime.utcnow()))
    db.session.commit()
    return u


@pytest.fixture
def internal_account(db):
    """The internal Campus Swap account — same .first() the routes use; create if the
    snapshot doesn't have one."""
    from models import User
    existing = User.query.filter_by(is_internal_account=True).first()
    if existing:
        return existing
    u = User(
        email=f'internal_{_uid()}@campusswap.com',
        full_name='Campus Swap',
        password_hash='x',
        is_internal_account=True,
    )
    db.session.add(u)
    db.session.commit()
    return u


def _login(client, user):
    with client.session_transaction() as s:
        s.clear()
        s['_user_id'] = str(user.id)
        s['_fresh'] = True


def _make_item(db, description='Test item', **kwargs):
    from models import InventoryItem
    item = InventoryItem(description=description, price=10, quality=1,
                         status=kwargs.pop('status', 'pending_valuation'), **kwargs)
    db.session.add(item)
    db.session.commit()
    return item


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

class TestItemPhotoModel:
    def test_new_columns_default_like_legacy_rows(self, db):
        from models import ItemPhoto
        item = _make_item(db, description=f'Model probe {_uid()}')
        p = ItemPhoto(item_id=item.id, photo_url='legacy.jpg')
        db.session.add(p)
        db.session.commit()
        assert p.captured_at is None
        assert p.sort_order == 0
        assert p.view is None
        assert p.is_hidden is False

    def test_gallery_orders_by_sort_order_then_id(self, db):
        from models import ItemPhoto, InventoryItem
        item = _make_item(db, description=f'Gallery order probe {_uid()}')
        a = ItemPhoto(item_id=item.id, photo_url='a.jpg', sort_order=2)
        b = ItemPhoto(item_id=item.id, photo_url='b.jpg', sort_order=0)
        c = ItemPhoto(item_id=item.id, photo_url='c.jpg', sort_order=0)
        db.session.add_all([a, b, c])
        db.session.commit()
        db.session.expire(item)
        fresh = db.session.get(InventoryItem, item.id)
        assert [p.photo_url for p in fresh.gallery_photos] == ['b.jpg', 'c.jpg', 'a.jpg']

    def test_legacy_prod_rows_untouched(self, db):
        """No-backfill guarantee: any pre-campaign row still reads as legacy."""
        from models import ItemPhoto
        legacy = ItemPhoto.query.filter(ItemPhoto.photo_url.notlike('rephoto_%')).first()
        if legacy is None:
            pytest.skip('no legacy ItemPhoto rows in this snapshot')
        assert legacy.captured_at is None
        assert legacy.view is None


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

class TestAuth:
    def test_campus_director_can_load_page(self, client, director):
        _login(client, director)
        r = client.get('/admin/warehouse/rephoto')
        assert r.status_code == 200
        assert b'Re-photography campaign' in r.data

    def test_approved_worker_blocked(self, client, db):
        from models import User
        w = User(email=f'w_{_uid()}@test.com', full_name='Rephoto Test Worker',
                 password_hash='x', is_worker=True, worker_status='approved')
        db.session.add(w)
        db.session.commit()
        _login(client, w)
        assert client.get('/admin/warehouse/rephoto').status_code == 403
        assert client.get('/admin/warehouse/rephoto/search?q=couch').status_code == 403

    def test_anonymous_redirected(self, client):
        from app import app as _app
        fresh = _app.test_client()
        r = fresh.get('/admin/warehouse/rephoto')
        assert r.status_code == 302


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

class TestSearch:
    def test_couch_synonym_finds_sofa_and_futon(self, client, db, director):
        _login(client, director)
        tag = _uid()
        sofa = _make_item(db, description=f'Comfy grey sofa {tag}')
        futon = _make_item(db, description=f'Black futon {tag}')
        desk = _make_item(db, description=f'Standing desk {tag}')
        r = client.get('/admin/warehouse/rephoto/search?q=couch')
        assert r.status_code == 200
        assert sofa.description.encode() in r.data
        assert futon.description.encode() in r.data
        assert desk.description.encode() not in r.data

    def test_fridge_synonym_finds_refrigerator(self, client, db, director):
        _login(client, director)
        fridge = _make_item(db, description=f'White refrigerator {_uid()}')
        r = client.get('/admin/warehouse/rephoto/search?q=fridge')
        assert fridge.description.encode() in r.data

    def test_category_name_matches(self, client, db, director):
        from models import InventoryCategory
        cat = InventoryCategory(name=f'Rug Test Cat {_uid()}')
        db.session.add(cat)
        db.session.commit()
        item = _make_item(db, description=f'Nondescript thing {_uid()}', category_id=cat.id)
        _login(client, director)
        r = client.get('/admin/warehouse/rephoto/search?q=rug')
        assert item.description.encode() in r.data

    def test_sold_items_excluded(self, client, db, director):
        _login(client, director)
        tag = _uid()
        sold = _make_item(db, description=f'Sold sofa {tag}', status='sold')
        kept = _make_item(db, description=f'Kept sofa {tag}')
        r = client.get(f'/admin/warehouse/rephoto/search?q={tag}')
        assert kept.description.encode() in r.data
        assert sold.description.encode() not in r.data

    def test_badge_and_ordering(self, client, db, director):
        from models import ItemPhoto
        _login(client, director)
        tag = _uid()
        reshot = _make_item(db, description=f'Reshot loveseat {tag}')
        fresh = _make_item(db, description=f'Fresh loveseat {tag}',
                           date_added=datetime.utcnow() - timedelta(days=3))
        db.session.add(ItemPhoto(item_id=reshot.id, photo_url='x.jpg',
                                 captured_at=datetime.utcnow(), view='front', sort_order=0))
        db.session.commit()
        r = client.get(f'/admin/warehouse/rephoto/search?q={tag}')
        body = r.data.decode()
        assert 'Re-shot today' in body
        # un-reshot item is rendered before the reshot one despite older date_added
        assert body.index(fresh.description) < body.index(reshot.description)

    def test_legacy_only_photos_show_no_badge(self, client, db, director):
        from models import ItemPhoto
        _login(client, director)
        tag = _uid()
        legacy = _make_item(db, description=f'Legacy settee {tag}')
        db.session.add(ItemPhoto(item_id=legacy.id, photo_url='old.jpg'))  # captured_at NULL
        db.session.commit()
        r = client.get(f'/admin/warehouse/rephoto/search?q={tag}')
        assert legacy.description.encode() in r.data
        assert b'Re-shot today' not in r.data

    def test_empty_results_offer_add(self, client, director):
        _login(client, director)
        r = client.get(f'/admin/warehouse/rephoto/search?q=zzzz{_uid()}')
        assert b'Add it' in r.data

    def test_blank_query_returns_nothing(self, client, director):
        _login(client, director)
        r = client.get('/admin/warehouse/rephoto/search?q=')
        assert r.status_code == 200
        assert b'rp-row' not in r.data


# ---------------------------------------------------------------------------
# Stub creation (add path)
# ---------------------------------------------------------------------------

class TestCreateStub:
    def test_stub_defaults(self, client, db, director, internal_account):
        from models import InventoryItem
        _login(client, director)
        r = client.post('/admin/warehouse/rephoto/add-item')
        assert r.status_code == 200
        data = r.get_json()
        assert data['success']
        item = db.session.get(InventoryItem, data['item_id'])
        assert item.status == 'pending_valuation'
        assert item.is_quick_capture is True
        assert item.captured_by_id == director.id
        assert item.seller_id == internal_account.id
        assert item.category_id is None
        assert item.ai_generated_at is None
        assert item.photo_url is None
        assert item.storage_location_id is None


# ---------------------------------------------------------------------------
# Photo add
# ---------------------------------------------------------------------------

class TestAddPhoto:
    def _post_photo(self, client, item_id, view='front', file=None, name='shot.jpg'):
        return client.post(
            f'/admin/warehouse/rephoto/{item_id}/photo',
            data={'view': view, 'photo': (file or _jpeg_bytes(), name)},
            content_type='multipart/form-data',
        )

    def test_photo_created_with_campaign_fields(self, client, db, director, storage_stub):
        from models import ItemPhoto
        _login(client, director)
        item = _make_item(db, description=f'Photo target {_uid()}', photo_url='cover.jpg')
        # pre-existing legacy photo at sort_order 0
        db.session.add(ItemPhoto(item_id=item.id, photo_url='legacy.jpg'))
        db.session.commit()
        before = datetime.utcnow() - timedelta(seconds=5)

        r = self._post_photo(client, item.id, view='front')
        assert r.status_code == 200
        data = r.get_json()
        assert data['success']
        p = db.session.get(ItemPhoto, data['photo_id'])
        assert p.view == 'front'
        assert p.captured_at is not None and p.captured_at >= before
        assert p.is_hidden is False
        assert p.sort_order == 1  # greater than the legacy photo's 0
        assert p.photo_url.startswith(f'rephoto_{item.id}_front_')
        assert data['photo_url'] == f'/uploads/{p.photo_url}'
        assert p.photo_url in storage_stub.saved

    def test_cover_status_and_ai_fields_untouched(self, client, db, director, storage_stub):
        from models import InventoryItem
        _login(client, director)
        gen_at = datetime(2026, 6, 1, 12, 0, 0)
        item = _make_item(db, description=f'Untouched {_uid()}', photo_url='cover.jpg',
                          status='available', ai_generated_at=gen_at)
        r = self._post_photo(client, item.id, view='side')
        assert r.status_code == 200
        db.session.expire_all()
        fresh = db.session.get(InventoryItem, item.id)
        assert fresh.photo_url == 'cover.jpg'
        assert fresh.status == 'available'
        assert fresh.ai_generated_at == gen_at

    def test_consecutive_shots_get_increasing_sort_order(self, client, db, director, storage_stub):
        from models import ItemPhoto
        _login(client, director)
        item = _make_item(db, description=f'Three shots {_uid()}')
        orders = []
        for view in ('front', 'side', 'back'):
            r = self._post_photo(client, item.id, view=view)
            orders.append(db.session.get(ItemPhoto, r.get_json()['photo_id']).sort_order)
        assert orders == [0, 1, 2]

    def test_server_downscale_bounds_oversized_upload(self, client, db, director, storage_stub):
        _login(client, director)
        item = _make_item(db, description=f'Big photo {_uid()}')
        r = self._post_photo(client, item.id, file=_jpeg_bytes(3200, 2400))
        assert r.status_code == 200
        key = r.get_json()['photo_url'].split('/')[-1]
        saved = Image.open(io.BytesIO(storage_stub.saved[key]))
        assert max(saved.size) == 1600
        assert saved.size == (1600, 1200)

    def test_invalid_view_rejected(self, client, db, director, storage_stub):
        _login(client, director)
        item = _make_item(db, description=f'Bad view {_uid()}')
        assert self._post_photo(client, item.id, view='top').status_code == 400
        assert self._post_photo(client, item.id, view='').status_code == 400

    def test_missing_photo_rejected(self, client, db, director):
        _login(client, director)
        item = _make_item(db, description=f'No file {_uid()}')
        r = client.post(f'/admin/warehouse/rephoto/{item.id}/photo', data={'view': 'front'})
        assert r.status_code == 400

    def test_unknown_item_404(self, client, director, storage_stub):
        _login(client, director)
        assert self._post_photo(client, 99999999).status_code == 404


# ---------------------------------------------------------------------------
# Details (add path)
# ---------------------------------------------------------------------------

class TestSetDetails:
    def _stub(self, client, db):
        from models import InventoryItem
        r = client.post('/admin/warehouse/rephoto/add-item')
        return db.session.get(InventoryItem, r.get_json()['item_id'])

    def _cat(self, db):
        from models import InventoryCategory
        return InventoryCategory.query.filter_by(parent_id=None).first()

    def test_category_required(self, client, db, director, internal_account):
        _login(client, director)
        item = self._stub(client, db)
        r = client.post(f'/admin/warehouse/rephoto/{item.id}/details',
                        data={'seller_mode': 'internal'})
        assert r.status_code == 400
        assert 'Category' in r.get_json()['error']

    def test_internal_mode_sets_category_and_enqueues_ai(self, client, db, director,
                                                         internal_account, storage_stub, ai_queue_stub):
        from models import InventoryItem
        _login(client, director)
        item = self._stub(client, db)
        # give it one photo so the AI enqueue fires
        client.post(f'/admin/warehouse/rephoto/{item.id}/photo',
                    data={'view': 'front', 'photo': (_jpeg_bytes(), 'f.jpg')},
                    content_type='multipart/form-data')
        cat = self._cat(db)
        r = client.post(f'/admin/warehouse/rephoto/{item.id}/details',
                        data={'category_id': cat.id, 'seller_mode': 'internal'})
        assert r.status_code == 200 and r.get_json()['success']
        db.session.expire_all()
        fresh = db.session.get(InventoryItem, item.id)
        assert fresh.category_id == cat.id
        assert fresh.seller_id == internal_account.id
        assert fresh.storage_location_id is None
        assert not ai_queue_stub.empty()
        assert ai_queue_stub.get_nowait()[1] == item.id

    def test_details_without_photos_skips_ai_enqueue(self, client, db, director,
                                                     internal_account, ai_queue_stub):
        _login(client, director)
        item = self._stub(client, db)
        cat = self._cat(db)
        r = client.post(f'/admin/warehouse/rephoto/{item.id}/details',
                        data={'category_id': cat.id, 'seller_mode': 'internal'})
        assert r.status_code == 200
        assert ai_queue_stub.empty()

    def test_existing_seller_mode(self, client, db, director, internal_account, ai_queue_stub):
        from models import InventoryItem, User
        _login(client, director)
        seller = User(email=f's_{_uid()}@test.com', full_name='Rephoto Test Seller',
                      password_hash='x', is_seller=True)
        db.session.add(seller)
        db.session.commit()
        item = self._stub(client, db)
        r = client.post(f'/admin/warehouse/rephoto/{item.id}/details',
                        data={'category_id': self._cat(db).id, 'seller_mode': 'existing',
                              'existing_seller_id': seller.id})
        assert r.status_code == 200
        db.session.expire_all()
        assert db.session.get(InventoryItem, item.id).seller_id == seller.id

    def test_new_proxy_seller_at_50(self, client, db, director, internal_account, ai_queue_stub):
        from models import InventoryItem, User
        _login(client, director)
        item = self._stub(client, db)
        email = f'proxy_{_uid()}@test.com'
        r = client.post(f'/admin/warehouse/rephoto/{item.id}/details',
                        data={'category_id': self._cat(db).id, 'seller_mode': 'new',
                              'new_name': 'Word Of Mouth', 'new_email': email})
        assert r.status_code == 200
        proxy = User.query.filter_by(email=email).first()
        assert proxy is not None
        assert proxy.payout_rate == 50
        assert proxy.is_proxy_account is True
        db.session.expire_all()
        assert db.session.get(InventoryItem, item.id).seller_id == proxy.id

    def test_new_proxy_requires_contact(self, client, db, director, internal_account):
        _login(client, director)
        item = self._stub(client, db)
        r = client.post(f'/admin/warehouse/rephoto/{item.id}/details',
                        data={'category_id': self._cat(db).id, 'seller_mode': 'new',
                              'new_name': 'No Contact'})
        assert r.status_code == 400

    def test_unit_and_zone_saved(self, client, db, director, internal_account, ai_queue_stub):
        from models import InventoryItem, StorageLocation
        _login(client, director)
        loc = StorageLocation(name=f'Rephoto Unit {_uid()}', address='x')
        db.session.add(loc)
        db.session.commit()
        item = self._stub(client, db)
        r = client.post(f'/admin/warehouse/rephoto/{item.id}/details',
                        data={'category_id': self._cat(db).id, 'seller_mode': 'internal',
                              'storage_location_id': loc.id, 'storage_row': 'back_left'})
        assert r.status_code == 200
        db.session.expire_all()
        fresh = db.session.get(InventoryItem, item.id)
        assert fresh.storage_location_id == loc.id
        assert fresh.storage_row == 'back_left'

    def test_unit_without_zone_saved(self, client, db, director, internal_account, ai_queue_stub):
        from models import InventoryItem, StorageLocation
        _login(client, director)
        loc = StorageLocation(name=f'Rephoto Unit {_uid()}', address='x')
        db.session.add(loc)
        db.session.commit()
        item = self._stub(client, db)
        r = client.post(f'/admin/warehouse/rephoto/{item.id}/details',
                        data={'category_id': self._cat(db).id, 'seller_mode': 'internal',
                              'storage_location_id': loc.id})
        assert r.status_code == 200
        db.session.expire_all()
        fresh = db.session.get(InventoryItem, item.id)
        assert fresh.storage_location_id == loc.id
        assert fresh.storage_row is None

    def test_invalid_zone_rejected(self, client, db, director, internal_account):
        from models import InventoryItem, StorageLocation
        _login(client, director)
        loc = StorageLocation(name=f'Rephoto Unit {_uid()}', address='x')
        db.session.add(loc)
        db.session.commit()
        item = self._stub(client, db)
        r = client.post(f'/admin/warehouse/rephoto/{item.id}/details',
                        data={'category_id': self._cat(db).id, 'seller_mode': 'internal',
                              'storage_location_id': loc.id, 'storage_row': 'top_shelf'})
        assert r.status_code == 400
        db.session.expire_all()
        assert db.session.get(InventoryItem, item.id).storage_location_id is None

    def test_invalid_unit_rejected(self, client, db, director, internal_account):
        _login(client, director)
        item = self._stub(client, db)
        r = client.post(f'/admin/warehouse/rephoto/{item.id}/details',
                        data={'category_id': self._cat(db).id, 'seller_mode': 'internal',
                              'storage_location_id': '99999999'})
        assert r.status_code == 400

    def test_subcategory_saved_when_child_of_category(self, client, db, director,
                                                      internal_account, ai_queue_stub):
        from models import InventoryItem, InventoryCategory
        _login(client, director)
        parent = InventoryCategory(name=f'Parent Cat {_uid()}')
        db.session.add(parent)
        db.session.flush()
        child_a = InventoryCategory(name=f'Child A {_uid()}', parent_id=parent.id)
        child_b = InventoryCategory(name=f'Child B {_uid()}', parent_id=parent.id)
        db.session.add_all([child_a, child_b])
        db.session.commit()
        item = self._stub(client, db)
        r = client.post(f'/admin/warehouse/rephoto/{item.id}/details',
                        data={'category_id': parent.id, 'seller_mode': 'internal',
                              'subcategory_id': child_a.id})
        assert r.status_code == 200
        db.session.expire_all()
        fresh = db.session.get(InventoryItem, item.id)
        assert fresh.category_id == parent.id
        assert fresh.subcategory_id == child_a.id

    def test_subcategory_ignored_when_wrong_parent(self, client, db, director,
                                                   internal_account, ai_queue_stub):
        from models import InventoryItem, InventoryCategory
        _login(client, director)
        parent = InventoryCategory(name=f'Parent Cat {_uid()}')
        other = InventoryCategory(name=f'Other Cat {_uid()}')
        db.session.add_all([parent, other])
        db.session.flush()
        stray = InventoryCategory(name=f'Stray Child {_uid()}', parent_id=other.id)
        db.session.add(stray)
        db.session.commit()
        item = self._stub(client, db)
        r = client.post(f'/admin/warehouse/rephoto/{item.id}/details',
                        data={'category_id': parent.id, 'seller_mode': 'internal',
                              'subcategory_id': stray.id})
        assert r.status_code == 200
        db.session.expire_all()
        assert db.session.get(InventoryItem, item.id).subcategory_id is None

    def test_non_quick_capture_item_rejected(self, client, db, director, internal_account):
        _login(client, director)
        normal = _make_item(db, description=f'Normal seller item {_uid()}')
        r = client.post(f'/admin/warehouse/rephoto/{normal.id}/details',
                        data={'category_id': self._cat(db).id, 'seller_mode': 'internal'})
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# Photo delete
# ---------------------------------------------------------------------------

class TestDeletePhoto:
    def test_campaign_photo_deleted(self, client, db, director, storage_stub):
        from models import ItemPhoto
        _login(client, director)
        item = _make_item(db, description=f'Delete target {_uid()}')
        key = f'rephoto_{item.id}_front_{_uid()}.jpg'
        p = ItemPhoto(item_id=item.id, photo_url=key,
                      captured_at=datetime.utcnow(), view='front')
        db.session.add(p)
        db.session.commit()
        pid = p.id
        r = client.post(f'/admin/warehouse/rephoto/photo/{pid}/delete')
        assert r.status_code == 200
        assert db.session.get(ItemPhoto, pid) is None
        assert key in storage_stub.deleted

    def test_legacy_photo_protected(self, client, db, director, storage_stub):
        from models import ItemPhoto
        _login(client, director)
        item = _make_item(db, description=f'Legacy keeper {_uid()}')
        p = ItemPhoto(item_id=item.id, photo_url='legacy.jpg')  # captured_at NULL
        db.session.add(p)
        db.session.commit()
        pid = p.id
        r = client.post(f'/admin/warehouse/rephoto/photo/{pid}/delete')
        assert r.status_code == 400
        assert db.session.get(ItemPhoto, pid) is not None
        assert storage_stub.deleted == []


# ---------------------------------------------------------------------------
# Fix: delete_photo keeps admins on the edit page (was bouncing to /admin → ops)
# ---------------------------------------------------------------------------

class TestDeletePhotoRedirect:
    def test_admin_stays_on_edit_page(self, client, db, storage_stub):
        from models import User, ItemPhoto
        admin = User(email=f'adm_{_uid()}@test.com', full_name='Rephoto Test Admin',
                     password_hash='x', is_admin=True)
        db.session.add(admin)
        db.session.commit()
        _login(client, admin)
        item = _make_item(db, description=f'Redirect probe {_uid()}', photo_url='cover.jpg')
        p = ItemPhoto(item_id=item.id, photo_url='gallery.jpg')
        db.session.add(p)
        db.session.commit()
        pid = p.id
        r = client.get(f'/delete_photo/{pid}')
        assert r.status_code == 302
        assert r.headers['Location'].endswith(f'/edit_item/{item.id}')
        assert db.session.get(ItemPhoto, pid) is None

    def test_seller_still_returns_to_edit_page(self, client, db, storage_stub):
        from models import User, ItemPhoto
        seller = User(email=f'sel_{_uid()}@test.com', full_name='Rephoto Test Seller',
                      password_hash='x', is_seller=True)
        db.session.add(seller)
        db.session.commit()
        _login(client, seller)
        item = _make_item(db, description=f'Seller redirect probe {_uid()}',
                          photo_url='cover.jpg', seller_id=seller.id)
        p = ItemPhoto(item_id=item.id, photo_url='gallery.jpg')
        db.session.add(p)
        db.session.commit()
        r = client.get(f'/delete_photo/{p.id}')
        assert r.status_code == 302
        assert r.headers['Location'].endswith(f'/edit_item/{item.id}')


# ---------------------------------------------------------------------------
# Admin seller reassignment from the edit-item page
# ---------------------------------------------------------------------------

class TestAdminSellerReassign:
    def _admin(self, db):
        from models import User
        u = User(email=f'adm_{_uid()}@test.com', full_name='Reassign Test Admin',
                 password_hash='x', is_admin=True)
        db.session.add(u)
        db.session.commit()
        return u

    def _seller(self, db, name='Reassign Target'):
        from models import User
        u = User(email=f'tgt_{_uid()}@test.com', full_name=name, password_hash='x', is_seller=True)
        db.session.add(u)
        db.session.commit()
        return u

    def test_admin_reassigns_seller(self, client, db, internal_account):
        from models import InventoryItem
        admin = self._admin(db)
        target = self._seller(db)
        item = _make_item(db, description=f'QC reassign probe {_uid()}',
                          seller_id=internal_account.id, is_quick_capture=True)
        _login(client, admin)
        r = client.post(f'/edit_item/{item.id}', data={
            'description': item.description,
            'quality': item.quality,
            'new_seller_id': target.id,
        })
        assert r.status_code == 302
        assert r.headers['Location'].endswith('/admin/items')
        db.session.expire_all()
        assert db.session.get(InventoryItem, item.id).seller_id == target.id

    def test_seller_cannot_reassign(self, client, db):
        from models import InventoryItem
        owner = self._seller(db, 'Owner Seller')
        other = self._seller(db, 'Other Seller')
        item = _make_item(db, description=f'No reassign probe {_uid()}', seller_id=owner.id)
        _login(client, owner)
        r = client.post(f'/edit_item/{item.id}', data={
            'description': item.description,
            'quality': item.quality,
            'new_seller_id': other.id,
        })
        assert r.status_code == 302
        db.session.expire_all()
        assert db.session.get(InventoryItem, item.id).seller_id == owner.id

    def test_invalid_seller_id_ignored(self, client, db, internal_account):
        from models import InventoryItem
        admin = self._admin(db)
        item = _make_item(db, description=f'Bad reassign probe {_uid()}',
                          seller_id=internal_account.id)
        _login(client, admin)
        client.post(f'/edit_item/{item.id}', data={
            'description': item.description,
            'quality': item.quality,
            'new_seller_id': '99999999',
        })
        db.session.expire_all()
        assert db.session.get(InventoryItem, item.id).seller_id == internal_account.id


# ---------------------------------------------------------------------------
# Items-tab drawer delete: modal=1 returns JSON (was a 302 the fetch choked on)
# ---------------------------------------------------------------------------

class TestModalDelete:
    def test_modal_delete_returns_json_and_deletes(self, client, db):
        from models import User, InventoryItem
        admin = User(email=f'adm_{_uid()}@test.com', full_name='Modal Delete Admin',
                     password_hash='x', is_admin=True)
        db.session.add(admin)
        db.session.commit()
        item = _make_item(db, description=f'Modal delete probe {_uid()}')
        _login(client, admin)
        r = client.post(f'/admin/item/{item.id}/delete', data={'modal': '1'})
        assert r.status_code == 200
        assert r.get_json() == {'success': True}
        assert db.session.get(InventoryItem, item.id) is None

    def test_non_modal_delete_still_redirects(self, client, db):
        from models import User, InventoryItem
        admin = User(email=f'adm_{_uid()}@test.com', full_name='Redirect Delete Admin',
                     password_hash='x', is_admin=True)
        db.session.add(admin)
        db.session.commit()
        item = _make_item(db, description=f'Redirect delete probe {_uid()}')
        _login(client, admin)
        r = client.post(f'/admin/item/{item.id}/delete')
        assert r.status_code == 302
        assert db.session.get(InventoryItem, item.id) is None


# ---------------------------------------------------------------------------
# Regression: Log Item still works after proxy-helper extraction
# ---------------------------------------------------------------------------

class TestLogItemRegression:
    def test_log_item_new_proxy_seller(self, client, db, director, storage_stub, ai_queue_stub):
        from models import InventoryCategory, InventoryItem, User
        _login(client, director)
        cat = InventoryCategory.query.filter_by(parent_id=None).first()
        email = f'wom_{_uid()}@test.com'
        r = client.post('/admin/warehouse/log-item', data={
            'photo': (_jpeg_bytes(), 'log.jpg'),
            'category_id': cat.id,
            'seller_mode': 'new',
            'new_name': 'Log Item Proxy',
            'new_email': email,
        }, content_type='multipart/form-data')
        assert r.status_code == 200, r.data
        data = r.get_json()
        assert data['success']
        proxy = User.query.filter_by(email=email).first()
        assert proxy.payout_rate == 50 and proxy.is_proxy_account
        assert proxy.proxy_note == 'Word-of-mouth seller — created via warehouse Log Item'
        item = db.session.get(InventoryItem, data['item_id'])
        assert item.seller_id == proxy.id

    def test_log_item_proxy_validation_still_errors(self, client, db, director, storage_stub):
        from models import InventoryCategory
        _login(client, director)
        cat = InventoryCategory.query.filter_by(parent_id=None).first()
        r = client.post('/admin/warehouse/log-item', data={
            'photo': (_jpeg_bytes(), 'log.jpg'),
            'category_id': cat.id,
            'seller_mode': 'new',
            'new_name': '',
        }, content_type='multipart/form-data')
        assert r.status_code == 400
