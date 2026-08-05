"""Tests for the Facebook Marketplace export tool.

Spec: feature_fb_marketplace_export.md
Run: python3 -m pytest test_fb_export.py -q
"""
import io
import re
import zipfile
from datetime import datetime

import pytest

from app import (
    app as flask_app, db,
    _fb_price, _fb_category, _fb_description, _fb_condition,
    _fb_photo_buckets, _fb_export_query, _fb_slug, _fb_zip_entries,
    _fb_export_category_options, _fb_export_filter_label,
    _shop_eligible_clauses, _stock_group_collapse_clause,
    _has_marketplace_access,
)
from models import User, InventoryItem, ItemPhoto, InventoryCategory, AppSetting
from constants import FB_CONDITION_DEFAULT, FB_PRICE_MARKUP_DEFAULT, FB_CTA_VARIANTS


class FakeItem:
    """Minimal stand-in for price math — _fb_price only reads .price."""
    def __init__(self, price):
        self.price = price


# ═══════════════════════════ fixtures ═══════════════════════════
# Deliberately self-contained: the root conftest `app` fixture repoints the URI at a
# temp SQLite file and calls drop_all(), which is destructive against the configured
# Postgres DB. Nothing here requests `app`, `db`, or `make_user` from that conftest.
# Every row created below is tracked and deleted in teardown.

@pytest.fixture
def app_ctx():
    flask_app.config['TESTING'] = True
    flask_app.config['WTF_CSRF_ENABLED'] = False
    with flask_app.app_context():
        yield flask_app
        db.session.rollback()


@pytest.fixture
def tracked(app_ctx):
    """Collects rows to delete after the test, children before parents."""
    created = {'photos': [], 'items': [], 'categories': [], 'users': []}
    yield created
    for p in created['photos']:
        db.session.execute(db.delete(ItemPhoto).where(ItemPhoto.id == p))
    # Clear the self-FK before deleting, or the parent delete violates it.
    for i in created['items']:
        db.session.execute(
            db.update(InventoryItem)
            .where(InventoryItem.replaced_by_item_id == i)
            .values(replaced_by_item_id=None)
        )
    for i in created['items']:
        db.session.execute(db.delete(InventoryItem).where(InventoryItem.id == i))
    # Reverse order: children (subcategories) were appended after their parents, and
    # inventory_category has a self-FK, so parents must go last.
    for c in reversed(created['categories']):
        db.session.execute(db.delete(InventoryCategory).where(InventoryCategory.id == c))
    for u in created['users']:
        db.session.execute(db.delete(User).where(User.id == u))
    db.session.commit()


@pytest.fixture
def make_item(tracked):
    def _factory(**kwargs):
        kwargs.setdefault('description', 'Test item')
        kwargs.setdefault('quality', 1)
        # status stays at the model default so factory rows never enter the export set
        # and cannot perturb the eligibility-parity test.
        item = InventoryItem(**kwargs)
        db.session.add(item)
        db.session.commit()
        tracked['items'].append(item.id)
        return item
    return _factory


@pytest.fixture
def make_category(tracked):
    def _factory(parent_name, sub_name):
        parent = InventoryCategory(name=parent_name)
        db.session.add(parent)
        db.session.commit()
        tracked['categories'].append(parent.id)
        sub = None
        if sub_name:
            sub = InventoryCategory(name=sub_name, parent_id=parent.id)
            db.session.add(sub)
            db.session.commit()
            tracked['categories'].append(sub.id)
        return parent, sub
    return _factory


@pytest.fixture
def add_photo(tracked):
    def _factory(item, photo_url, is_hidden=False, view=None, sort_order=None):
        if sort_order is None:
            sort_order = len(item.gallery_photos)
        p = ItemPhoto(item_id=item.id, photo_url=photo_url, is_hidden=is_hidden,
                      view=view, sort_order=sort_order, captured_at=datetime.utcnow())
        db.session.add(p)
        db.session.commit()
        tracked['photos'].append(p.id)
        db.session.refresh(item)
        return p
    return _factory


@pytest.fixture
def fake_storage(monkeypatch):
    """Swap the storage backend so `originals` derivation is deterministic and offline."""
    class _FakeStorage:
        def __init__(self):
            self.present = set()

        def exists(self, key):
            return key in self.present

        def get_photo_bytes(self, key):
            return b'\xff\xd8\xff\xd9' if key in self.present else None

    fake = _FakeStorage()
    monkeypatch.setattr('app.photo_storage', fake)
    return fake


def _login(uid):
    c = flask_app.test_client()
    with c.session_transaction() as s:
        s['_user_id'] = str(uid)
        s['_fresh'] = True
    return c


@pytest.fixture
def setting():
    """Temporarily override an AppSetting, restoring the ORIGINAL value afterward.

    These tests share a real database, so blanking a setting in teardown would leak
    state into later tests (and later runs) instead of undoing the change.
    """
    saved = {}

    def _set(key, value):
        if key not in saved:
            saved[key] = AppSetting.get(key, None)
        AppSetting.set(key, value)

    yield _set

    for key, original in saved.items():
        AppSetting.set(key, original if original is not None else '')


@pytest.fixture
def eligible_item(tracked, make_item, add_photo):
    """A fully shop-eligible item, so route tests don't depend on what the DB
    happens to contain. Mirrors _fb_export_query's filters exactly."""
    from models import StorageLocation
    loc = StorageLocation.query.first()
    if loc is None:
        pytest.skip('no StorageLocation in this database')
    item = make_item(
        description='Test eligible dresser',
        long_description='A test dresser used by the FB export route tests.',
        price=100.0,
        status='available',
        ai_approved=True,
        needs_new_photo=False,
        storage_location_id=loc.id,
        rephoto_disposition='kept',   # satisfies _matched_or_kept_clause without a seller
    )
    # captured_at is what _rephotographed_clause() keys on.
    add_photo(item, f'fbtest_{item.id}_front_nobg.jpg', view='front')
    db.session.commit()
    return item



@pytest.fixture
def categorized_items(tracked, make_item, add_photo, make_category):
    """A parent category + subcategory with 2 fully-eligible items in it.

    The category-filter tests must not depend on the DB happening to contain
    categorized eligible inventory — campusswap_prod has none, which silently
    turned these into skips.
    """
    from models import StorageLocation
    loc = StorageLocation.query.first()
    if loc is None:
        pytest.skip('no StorageLocation in this database')
    parent, sub = make_category('FBTest Furniture', 'FBTest Couch')
    items = []
    for n in range(2):
        it = make_item(
            description=f'FBTest couch {n}',
            long_description='Test couch for category filter tests.',
            price=200.0,
            status='available',
            ai_approved=True,
            needs_new_photo=False,
            storage_location_id=loc.id,
            rephoto_disposition='kept',
            category_id=parent.id,
            subcategory_id=sub.id,
        )
        add_photo(it, f'fbtest_cat_{it.id}_front_nobg.jpg', view='front')
        items.append(it)
    db.session.commit()
    return parent, sub, items


@pytest.fixture
def client_admin(app_ctx):
    admin = (User.query.filter_by(is_super_admin=True).first()
             or User.query.filter_by(is_admin=True).first())
    if admin is None:
        pytest.skip('no admin user in this database')
    return _login(admin.id)


@pytest.fixture
def poster_user(tracked):
    """A marketplace poster: NOT crew, NOT admin, NOT campus director."""
    u = User(email=f'fbtest-poster-{datetime.utcnow().timestamp()}@example.com',
             full_name='FB Test Poster', is_marketplace_poster=True,
             is_worker=False, worker_status=None,
             is_admin=False, is_super_admin=False, is_campus_director=False)
    db.session.add(u)
    db.session.commit()
    tracked['users'].append(u.id)
    return u


@pytest.fixture
def client_poster(poster_user):
    return _login(poster_user.id)


@pytest.fixture
def client_plain(tracked):
    u = User(email=f'fbtest-plain-{datetime.utcnow().timestamp()}@example.com',
             full_name='FB Test Plain', is_marketplace_poster=False,
             is_worker=False, is_admin=False, is_super_admin=False,
             is_campus_director=False)
    db.session.add(u)
    db.session.commit()
    tracked['users'].append(u.id)
    return _login(u.id)


# ─────────────────────────── pricing ───────────────────────────

@pytest.mark.parametrize('price,expected', [
    (10,     17),    # (10+5)*1.1  = 16.5   -> 17
    (16,     24),    # (16+5)*1.1  = 23.1   -> 24
    (35,     44),    # (35+5)*1.1  = 44.0   -> 44 (exact, no round-up)
    (49,     60),    # last cent of the <50 tier
    (49.99,  61),
    (50,     66),    # first of the 50-99 tier: (50+10)*1.1 = 66.0
    (79,     98),
    (99,    120),
    (99.99, 121),
    (100,   127),    # first of the 100+ tier: (100+15)*1.1 = 126.5 -> 127
    (108,   136),
    (200,   237),
    (287,   333),
])
def test_fb_price_tiers(app_ctx, price, expected):
    assert _fb_price(FakeItem(price)) == expected


def test_fb_price_rounds_up_not_nearest(app_ctx):
    # (100+15)*1.1 = 126.5 — banker's/nearest rounding would give 126.
    assert _fb_price(FakeItem(100)) == 127


def test_fb_price_none_when_no_price(app_ctx):
    assert _fb_price(FakeItem(None)) is None
    assert _fb_price(FakeItem(0)) is None


def test_fb_price_markup_setting_overrides_default(app_ctx, setting):
    setting('fb_price_markup', '2.0')
    assert _fb_price(FakeItem(35)) == 80   # (35+5)*2.0


def test_fb_price_bad_markup_setting_falls_back(app_ctx, setting):
    setting('fb_price_markup', 'not-a-number')
    assert _fb_price(FakeItem(35)) == 44   # falls back to 1.1


# ─────────────────────────── condition ───────────────────────────

def test_condition_is_single_fixed_value(app_ctx):
    assert _fb_condition() == FB_CONDITION_DEFAULT == 'Used - Good'


def test_condition_ignores_item_quality(app_ctx, make_item):
    """Every item lists as the same condition regardless of quality, because
    quality==1 is the unset default on the large majority of inventory."""
    labels = set()
    for q in (1, 2, 3, 4, 5):
        make_item(quality=q)
        labels.add(_fb_condition())
    assert labels == {'Used - Good'}


# ─────────────────────────── description ───────────────────────────

def test_description_has_cta_and_url(app_ctx, make_item):
    """Assert only what every CTA variant shares — the block rotates by item id."""
    item = make_item(long_description='A sturdy oak desk.')
    out = _fb_description(item)
    assert 'A sturdy oak desk.' in out
    assert 'https://usecampusswap.com/shop' in out
    assert '30 mile' in out.lower()


def test_cta_variants_all_carry_the_required_facts(app_ctx):
    """Rotating the prose must never drop the radius, the URL, or emoji-freeness."""
    for i, v in enumerate(FB_CTA_VARIANTS):
        assert 'usecampusswap.com/shop' in v, f'variant {i} missing URL'
        assert '30 mile' in v.lower(), f'variant {i} missing radius'
        assert all(ord(ch) < 0x2190 for ch in v), f'variant {i} has an emoji/symbol'


def test_cta_variants_are_distinct(app_ctx):
    """Identical variants would defeat the whole point."""
    assert len(set(FB_CTA_VARIANTS)) == len(FB_CTA_VARIANTS)
    assert len(FB_CTA_VARIANTS) >= 3


def test_cta_variant_is_deterministic_for_an_item(app_ctx, make_item):
    """Keyed on id, not random — the same item must render identically every time,
    or the worker sees the text change between page load and re-download."""
    item = make_item(long_description='Desk.')
    assert _fb_description(item) == _fb_description(item)


def test_cta_variant_selected_by_item_id(app_ctx, make_item):
    item = make_item(long_description='Desk.')
    expected = FB_CTA_VARIANTS[item.id % len(FB_CTA_VARIANTS)]
    assert expected in _fb_description(item)


def test_cta_rotates_across_consecutive_ids(app_ctx, make_item):
    """Adjacent items must not share a closing block."""
    items = [make_item(long_description=f'Item {n}.') for n in range(len(FB_CTA_VARIANTS))]
    blocks = [_fb_description(i).split('\n\n')[-1] for i in items]
    assert len(set(blocks)) == len(FB_CTA_VARIANTS)


def test_description_has_no_emoji(app_ctx, make_item):
    out = _fb_description(make_item(long_description='Desk.'))
    assert all(ord(ch) < 0x2190 for ch in out), 'description must stay emoji-free'


def test_description_includes_dimensions_when_present(app_ctx, make_item):
    item = make_item(long_description='Desk.', width_in=30, length_in=18, height_in=34)
    out = _fb_description(item)
    assert 'Dimensions: 30"W x 18"D x 34"H' in out


def test_description_omits_dimension_line_when_absent(app_ctx, make_item):
    out = _fb_description(make_item(long_description='Desk.'))
    assert 'Dimensions:' not in out


def test_description_includes_mattress_size(app_ctx, make_item):
    out = _fb_description(make_item(long_description='Mattress.', mattress_size='queen'))
    assert 'Size: Queen' in out


def test_description_falls_back_to_short_description(app_ctx, make_item):
    item = make_item(description='Blue chair', long_description=None)
    assert 'Blue chair' in _fb_description(item)


def test_description_cta_setting_overrides(app_ctx, make_item, setting):
    setting('fb_cta_text', 'CUSTOM CTA LINE')
    out = _fb_description(make_item(long_description='Desk.'))
    assert 'CUSTOM CTA LINE' in out
    assert 'usecampusswap.com' not in out


# ─────────────────────────── categories ───────────────────────────

def test_category_maps_known_subcategory(app_ctx, make_item, make_category):
    parent, sub = make_category('Furniture', 'Dresser')
    item = make_item(category_id=parent.id, subcategory_id=sub.id)
    fb, cs = _fb_category(item)
    assert fb == 'Dressers & Armoires'
    assert cs == 'Furniture > Dresser'


def test_category_keyword_fallback_for_other_bucket(app_ctx, make_item, make_category):
    """NULL subcategory ('Other' bucket) still resolves via a title keyword."""
    parent, _ = make_category('Other', None)
    item = make_item(description='Black LED desk lamp', category_id=parent.id, subcategory_id=None)
    fb, _cs = _fb_category(item)
    assert fb == 'Lamps'


def test_category_returns_none_when_unmappable(app_ctx, make_item, make_category):
    """No mapping and no keyword hit -> None, so the UI prompts instead of
    offering a misleading value to paste."""
    parent, _ = make_category('Other', None)
    item = make_item(description='Light blue changing pad',
                     category_id=parent.id, subcategory_id=None)
    fb, cs = _fb_category(item)
    assert fb is None
    assert cs == 'Other'


# ─────────────────────────── photo buckets ───────────────────────────

def test_ai_enhanced_photos_excluded(app_ctx, make_item, add_photo):
    item = make_item()
    add_photo(item, 'ai_enhanced_abc.jpg')
    add_photo(item, 'shot_nobg.jpg')
    listing, _originals, _src = _fb_photo_buckets(item)
    assert 'ai_enhanced_abc.jpg' not in listing
    assert 'shot_nobg.jpg' in listing


def test_hidden_photos_excluded(app_ctx, make_item, add_photo):
    item = make_item()
    add_photo(item, 'visible_nobg.jpg')
    add_photo(item, 'hidden_nobg.jpg', is_hidden=True)
    listing, _o, _s = _fb_photo_buckets(item)
    assert listing == ['visible_nobg.jpg']


def test_originals_come_from_matched_seller_listing(app_ctx, make_item, add_photo):
    """replaced_by_item_id lives on the ORIGINAL and points at the shop item."""
    shop = make_item(description='Rephotographed dresser')
    add_photo(shop, 'wh_front_nobg.jpg')
    original = make_item(description='Seller dresser', photo_url='seller_cover.jpg')
    add_photo(original, 'seller_extra.jpg')
    original.replaced_by_item_id = shop.id
    db.session.commit()

    listing, originals, src = _fb_photo_buckets(shop)
    assert src == 'seller'
    assert listing == ['wh_front_nobg.jpg']
    assert 'seller_cover.jpg' in originals
    assert 'seller_extra.jpg' in originals


def test_matched_original_with_null_cover(app_ctx, make_item, add_photo):
    """Confirmed in production: a matched original can have NULL photo_url
    but a populated gallery. Must not crash or emit a None entry."""
    shop = make_item()
    add_photo(shop, 'wh_nobg.jpg')
    original = make_item(photo_url=None)
    add_photo(original, 'seller_gallery.jpg')
    original.replaced_by_item_id = shop.id
    db.session.commit()

    _l, originals, src = _fb_photo_buckets(shop)
    assert src == 'seller'
    assert None not in originals
    assert originals == ['seller_gallery.jpg']


def test_originals_derived_from_nobg_when_no_match(app_ctx, make_item, add_photo, fake_storage):
    """No matched original -> derive the pre-bg-removal raw by dropping '_nobg'."""
    item = make_item()
    add_photo(item, 'capture_a_nobg.jpg')
    fake_storage.present.add('capture_a.jpg')
    _l, originals, src = _fb_photo_buckets(item)
    assert src == 'warehouse'
    assert originals == ['capture_a.jpg']


def test_derived_original_skipped_when_missing_in_storage(app_ctx, make_item, add_photo, fake_storage):
    """Derived names are not DB rows, so a miss must be skipped silently."""
    item = make_item()
    add_photo(item, 'capture_b_nobg.jpg')
    # fake_storage.present intentionally left empty
    _l, originals, src = _fb_photo_buckets(item)
    assert src == 'warehouse'
    assert originals == []


def test_legacy_photo_without_nobg_has_no_original(app_ctx, make_item, add_photo, fake_storage):
    item = make_item()
    add_photo(item, 'legacy_photo.jpg')
    _l, originals, _s = _fb_photo_buckets(item)
    assert originals == []


def test_cover_used_as_listing_when_gallery_empty(app_ctx, make_item):
    item = make_item(photo_url='only_cover.jpg')
    listing, _o, _s = _fb_photo_buckets(item)
    assert listing == ['only_cover.jpg']


# ─────────────────────────── zip structure ───────────────────────────

def test_slug_is_ascii_and_bounded(app_ctx, make_item):
    item = make_item(description='Café Dresser — 6 Drawers!! (white)')
    slug = _fb_slug(item)
    assert slug.startswith(f'item-{item.id}-')
    assert slug.isascii()
    assert '/' not in slug and ' ' not in slug


def test_zip_is_one_flat_folder_per_item(app_ctx, make_item, add_photo, fake_storage):
    """No listing/ + originals/ split — one folder, one continuous sequence."""
    item = make_item()
    add_photo(item, 'a_nobg.jpg', view='front')
    add_photo(item, 'b_nobg.jpg', view='side')
    fake_storage.present.update({'a.jpg', 'b.jpg'})
    entries = [arc for arc, _key in _fb_zip_entries(item)]
    slug = _fb_slug(item)
    assert entries == [
        f'{slug}/01-front.jpg',
        f'{slug}/02-side.jpg',
        f'{slug}/03-extra.jpg',
        f'{slug}/04-extra.jpg',
    ]
    assert all(a.count('/') == 1 for a in entries), 'must be flat'


def test_zip_numbering_sorts_into_upload_order(app_ctx, make_item, add_photo, fake_storage):
    """Ascending filename sort must equal intended upload order, so select-all-and-drag
    puts the cover photo first instead of the back shot — which is what happened when the
    two subfolders each restarted numbering at 01."""
    item = make_item()
    for key, view in [('a_nobg.jpg', 'front'), ('b_nobg.jpg', 'side'), ('c_nobg.jpg', 'back')]:
        add_photo(item, key, view=view)
    fake_storage.present.update({'a.jpg', 'b.jpg', 'c.jpg'})
    names = [arc.split('/')[-1] for arc, _k in _fb_zip_entries(item)]
    assert names == sorted(names), 'name-sort order must match generated order'
    assert names[0].startswith('01-front'), 'cover photo must sort first'
    assert len(set(names)) == len(names), 'no filename collisions'


# ─────────────────────────── eligibility ───────────────────────────

def test_export_set_matches_shop_visibility(app_ctx):
    """The export must never drift from what buyers see on /shop.

    Calls the SHARED helpers rather than re-listing the conditions. The previous version
    hand-copied the filter clauses and omitted the stock-group collapse, so it compared
    the export against its own incomplete copy of /shop and passed while the real sets
    differed by 72 items (287 vs 215). A test that duplicates the logic it checks will
    always agree with itself.
    """
    shop_count = InventoryItem.query.filter(
        *_shop_eligible_clauses(), _stock_group_collapse_clause()
    ).count()
    assert _fb_export_query(unposted_only=False).count() == shop_count


def _make_stock_group(make_item, add_photo, tag, n=3, price=80.0):
    """n eligible items sharing one stock_group_id. Returns the created items."""
    from models import StorageLocation
    loc = StorageLocation.query.first()
    if loc is None:
        pytest.skip('no StorageLocation in this database')
    group = f'fbtest-{tag}-{datetime.utcnow().timestamp()}'
    units = []
    for i in range(n):
        it = make_item(
            description=f'FBTest {tag} unit {i}', price=price, status='available',
            ai_approved=True, needs_new_photo=False, storage_location_id=loc.id,
            rephoto_disposition='kept', stock_group_id=group,
        )
        add_photo(it, f'fbtest_{tag}_{it.id}_front_nobg.jpg', view='front')
        units.append(it)
    db.session.commit()
    return group, units


def test_multi_unit_stock_collapses_to_one_listing(app_ctx, tracked, make_item, add_photo):
    """37 identical mattresses are ONE Facebook listing, not 37.

    This is the behavioural assertion the parity test cannot make on its own — parity
    would still hold if /shop and the export were both changed the wrong way together.
    """
    _group, units = _make_stock_group(make_item, add_photo, 'collapse')
    ids = {i.id for i in _fb_export_query(unposted_only=False).all()}
    present = ids & {u.id for u in units}
    assert len(present) == 1, f'expected 1 of 3 grouped units, got {len(present)}'
    assert present == {min(u.id for u in units)}, 'should keep the lowest-id unit'


def test_stock_count_surfaced_for_grouped_item(app_ctx, tracked, make_item, add_photo):
    """The poster must be told there are N units, or they list 1 of 37 unknowingly."""
    group, _units = _make_stock_group(make_item, add_photo, 'count')
    kept = next(i for i in _fb_export_query(unposted_only=False).all()
                if i.stock_group_id == group)
    assert kept.stock_available_count == 3


def test_grouped_page_shows_quantity(client_admin, app_ctx, tracked, make_item, add_photo):
    group, _units = _make_stock_group(make_item, add_photo, 'qty')
    items = _fb_export_query(unposted_only=False).all()
    pos = next(n for n, i in enumerate(items, start=1) if i.stock_group_id == group)
    body = client_admin.get(f'/admin/fb-export?unposted=0&i={pos}').get_data(as_text=True)
    assert '3 identical units' in body


def test_unposted_filter_reflects_posted_flag(app_ctx, eligible_item):
    before = _fb_export_query(unposted_only=True).count()
    item = eligible_item
    item.fb_posted_at = datetime.utcnow()
    db.session.commit()
    try:
        assert _fb_export_query(unposted_only=True).count() == before - 1
        assert _fb_export_query(unposted_only=False).count() >= before
    finally:
        item.fb_posted_at = None
        db.session.commit()


# ─────────────────────────── routes & auth ───────────────────────────

def test_page_renders_for_admin(client_admin, eligible_item):
    r = client_admin.get('/admin/fb-export')
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert 'Used - Good' in body
    assert 'usecampusswap.com/shop' in body
    assert 'Item 1 of' in body


def test_eligible_item_appears_in_export_set(app_ctx, eligible_item):
    ids = [i.id for i in _fb_export_query(unposted_only=True).all()]
    assert eligible_item.id in ids


def test_out_of_range_index_clamps(client_admin, eligible_item):
    assert client_admin.get('/admin/fb-export?i=999999').status_code == 200
    assert client_admin.get('/admin/fb-export?i=-5').status_code == 200


def test_poster_can_access(client_poster, eligible_item):
    assert client_poster.get('/admin/fb-export').status_code == 200


def test_plain_user_forbidden(client_plain):
    assert client_plain.get('/admin/fb-export').status_code == 403


def test_anonymous_redirected(app_ctx):
    with flask_app.test_client() as c:
        r = c.get('/admin/fb-export')
        assert r.status_code in (301, 302, 401)


@pytest.mark.parametrize('path', [
    '/admin/settings', '/admin/items', '/admin/ops', '/admin/schedule', '/admin/warehouse',
])
def test_poster_cannot_reach_ops_routes(client_poster, path):
    """The whole point of the dedicated flag: no ops surface."""
    assert client_poster.get(path).status_code != 200


def test_poster_is_not_crew(app_ctx, poster_user):
    """Must stay out of the staffing pool — this is why require_crew() was rejected."""
    assert poster_user.is_worker is False
    assert poster_user.worker_status is None


def test_mark_posted_sets_and_clears(client_admin, app_ctx, eligible_item):
    iid = eligible_item.id

    r = client_admin.post(f'/admin/fb-export/{iid}/posted',
                          json={'posted': True, 'fb_listing_url': 'https://fb.com/x'})
    assert r.status_code == 200 and r.get_json()['success'] is True
    refreshed = db.session.get(InventoryItem, iid)
    assert refreshed.fb_posted_at is not None
    assert refreshed.fb_listing_url == 'https://fb.com/x'

    r = client_admin.post(f'/admin/fb-export/{iid}/posted', json={'posted': False})
    assert r.status_code == 200
    refreshed = db.session.get(InventoryItem, iid)
    assert refreshed.fb_posted_at is None
    assert refreshed.fb_listing_url is None


def test_mark_posted_forbidden_for_plain_user(client_plain, app_ctx, eligible_item):
    item = eligible_item
    r = client_plain.post(f'/admin/fb-export/{item.id}/posted', json={'posted': True})
    assert r.status_code == 403
    assert db.session.get(InventoryItem, item.id).fb_posted_at is None


def test_item_zip_is_valid_archive(client_admin, app_ctx, eligible_item):
    item = eligible_item
    r = client_admin.get(f'/admin/fb-export/{item.id}/photos.zip')
    assert r.status_code == 200
    z = zipfile.ZipFile(io.BytesIO(r.data))
    assert z.testzip() is None
    assert all(n.startswith(_fb_slug(item) + '/') for n in z.namelist())


def test_bulk_zip_respects_limit(client_admin, app_ctx, eligible_item):
    r = client_admin.get('/admin/fb-export/photos.zip?limit=2')
    assert r.status_code == 200
    z = zipfile.ZipFile(io.BytesIO(r.data))
    assert z.testzip() is None
    folders = {n.split('/')[0] for n in z.namelist()}
    assert len(folders) <= 2


def test_bulk_zip_404_when_offset_past_end(client_admin):
    r = client_admin.get('/admin/fb-export/photos.zip?offset=999999')
    assert r.status_code == 404


def test_zip_missing_file_does_not_500(client_admin, app_ctx, make_item, add_photo):
    """A photo row pointing at a key absent from storage must be skipped, not fatal."""
    item = make_item()
    add_photo(item, 'definitely-not-in-storage-xyz.jpg')
    r = client_admin.get(f'/admin/fb-export/{item.id}/photos.zip')
    assert r.status_code == 200
    assert zipfile.ZipFile(io.BytesIO(r.data)).testzip() is None


# ─────────────────────────── category filter ───────────────────────────

def test_category_options_counts_match_filtered_queries(app_ctx, categorized_items):
    """Every count in the picker must equal what selecting it actually returns,
    or the poster is told 12 couches and shown a different number."""
    opts = _fb_export_category_options(unposted_only=True)
    for p in opts:
        assert p['count'] == _fb_export_query(
            unposted_only=True, category_id=p['parent_id']).count()
        for sub in p['subs']:
            assert sub['count'] == _fb_export_query(
                unposted_only=True, subcategory_id=sub['id']).count()


def test_category_options_sum_to_total(app_ctx, categorized_items):
    """No eligible item may be unreachable through the picker."""
    opts = _fb_export_category_options(unposted_only=True)
    assert sum(p['count'] for p in opts) == _fb_export_query(unposted_only=True).count()


def test_category_options_only_include_nonempty(app_ctx, categorized_items):
    for p in _fb_export_category_options(unposted_only=True):
        assert p['count'] > 0
        for sub in p['subs']:
            assert sub['count'] > 0


def test_subcategory_filter_narrows_to_that_subcategory(app_ctx, categorized_items):
    _parent, sub, created = categorized_items
    items = _fb_export_query(unposted_only=False, subcategory_id=sub.id).all()
    assert {i.id for i in items} == {i.id for i in created}
    assert all(i.subcategory_id == sub.id for i in items)


def test_subcategory_wins_over_category_when_both_given(app_ctx, categorized_items):
    """Documented precedence: sub is strictly narrower, so it takes priority."""
    parent, sub, _created = categorized_items
    both = _fb_export_query(unposted_only=False,
                            category_id=parent.id, subcategory_id=sub.id).count()
    assert both == _fb_export_query(unposted_only=False, subcategory_id=sub.id).count()
    # A mismatched pair still honours sub, rather than intersecting to zero.
    assert _fb_export_query(unposted_only=False,
                            category_id=999999, subcategory_id=sub.id).count() == both


def test_unknown_category_id_returns_empty_not_error(app_ctx):
    assert _fb_export_query(unposted_only=False, subcategory_id=999999).count() == 0
    assert _fb_export_query(unposted_only=False, category_id=999999).count() == 0


def test_filter_label_none_when_unfiltered(app_ctx):
    assert _fb_export_filter_label(None, None) is None
    assert _fb_export_filter_label(999999, None) is None


def test_filtered_page_renders_and_scopes_count(client_admin, app_ctx, categorized_items):
    _parent, sub, created = categorized_items
    r = client_admin.get(f'/admin/fb-export?sub={sub.id}')
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert f'Item 1 of {len(created)}' in body
    assert sub.name in body
    assert f'posted in {sub.name}' in body


def test_filter_preserved_in_navigation_links(client_admin, app_ctx, categorized_items):
    """Losing cat/sub on Next would silently dump the poster back into the full catalog."""
    _parent, sub, _created = categorized_items
    body = client_admin.get(f'/admin/fb-export?sub={sub.id}').get_data(as_text=True)
    assert re.search(r'href="[^"]*sub=%d[^"]*"[^>]*>\s*Next' % sub.id, body)
    # and on the unposted/all toggle
    assert re.search(r'href="[^"]*sub=%d[^"]*"[^>]*>\s*show all' % sub.id, body)


def test_unknown_filter_renders_empty_state_not_500(client_admin):
    r = client_admin.get('/admin/fb-export?sub=999999')
    assert r.status_code == 200
    assert 'Nothing left to post' in r.get_data(as_text=True)


def test_bulk_zip_respects_category_filter(client_admin, app_ctx, categorized_items):
    """'Download the couches' must not hand over the first N of the whole catalog."""
    _parent, sub, created = categorized_items
    expected = {_fb_slug(i) for i in created}
    r = client_admin.get(f'/admin/fb-export/photos.zip?sub={sub.id}&limit=50&unposted=0')
    assert r.status_code == 200
    folders = {n.split('/')[0] for n in zipfile.ZipFile(io.BytesIO(r.data)).namelist()}
    assert folders <= expected, 'bulk zip leaked items outside the filter'


def test_bulk_zip_filename_names_the_filter(client_admin, app_ctx, categorized_items):
    _parent, sub, _created = categorized_items
    r = client_admin.get(f'/admin/fb-export/photos.zip?sub={sub.id}&limit=1&unposted=0')
    assert r.status_code == 200
    disp = r.headers.get('Content-Disposition', '')
    assert 'fbtest-couch' in disp, disp


def test_bulk_zip_filename_says_all_when_unfiltered(client_admin, eligible_item):
    r = client_admin.get('/admin/fb-export/photos.zip?limit=1&unposted=0')
    assert r.status_code == 200
    assert 'campusswap-fb-all-' in r.headers.get('Content-Disposition', '')
