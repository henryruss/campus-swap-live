"""
Tests for the AI Autofill revamp (2026-07-17).

Runs against campusswap_prod (the local prod snapshot with all migrations
applied — set by conftest.py). Deliberately does NOT use the conftest `app`
fixture: that fixture's SQLite override never takes effect (the engine is bound
to Postgres at import time), so its create_all/drop_all would wipe the snapshot.
All data here is unique-tagged and cleaned up per test.

Covers:
- Eligibility: only rephotographed items without AI autofill set are eligible
  (rephoto items keep photo_url NULL, so eligibility must not require a cover).
- Baseline pricing lookup: subcategory -> category -> global default.
- Full pipeline: title, short description, baseline x multiplier pricing
  (clamp + $5 rounding), remove.bg photo processing (replace in place, _nobg
  naming, cover set to processed front photo), and AI staging fields.

remove.bg and Anthropic are mocked — no network calls, no credits spent.
"""

import uuid
from datetime import datetime
from decimal import Decimal

import pytest


def _uid():
    return uuid.uuid4().hex[:8]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db():
    """App-context-wrapped db handle for direct queries in test bodies."""
    from app import app as _app, db as _db
    with _app.app_context():
        yield _db
        _db.session.remove()


@pytest.fixture
def factory(db):
    """Creates categories/items tagged with a unique run id and tears them down.

    Cleanup deletes ItemPhoto -> InventoryItem -> InventoryCategory in FK order.
    """
    from models import InventoryItem, ItemPhoto, InventoryCategory
    created_items = []
    created_categories = []

    def make_category(name, baseline=None, parent=None):
        cat = InventoryCategory(
            name=f'{name} {_uid()}',
            baseline_price=Decimal(str(baseline)) if baseline is not None else None,
            parent_id=parent.id if parent else None,
        )
        db.session.add(cat)
        db.session.commit()
        created_categories.append(cat.id)
        return cat

    def make_item(category=None, subcategory=None, rephotographed=True,
                  ai_generated_at=None, status='pending_valuation',
                  views=('front', 'side', 'back')):
        item = InventoryItem(
            description='Seller Title Desk',
            seller_description='Seller Title Desk',
            status=status,
            category_id=category.id if category else None,
            subcategory_id=subcategory.id if subcategory else None,
            ai_generated_at=ai_generated_at,
        )
        db.session.add(item)
        db.session.flush()
        for i, view in enumerate(views):
            db.session.add(ItemPhoto(
                item_id=item.id,
                photo_url=f'rephoto_{item.id}_{view}_{_uid()}.jpg',
                captured_at=datetime.utcnow() if rephotographed else None,
                view=view,
                sort_order=i,
            ))
        db.session.commit()
        created_items.append(item.id)
        return item

    yield type('F', (), {'make_category': staticmethod(make_category),
                         'make_item': staticmethod(make_item)})

    for item_id in created_items:
        ItemPhoto.query.filter_by(item_id=item_id).delete()
        InventoryItem.query.filter_by(id=item_id).delete()
    # Reverse order so child (sub)categories are removed before their parents.
    for cat_id in reversed(created_categories):
        InventoryCategory.query.filter_by(id=cat_id).delete()
    db.session.commit()


@pytest.fixture
def cats(factory):
    """Furniture (baseline 75) with Desk (75), Couch (325), and a no-baseline sub."""
    furniture = factory.make_category('Furniture Test', baseline=75)
    return {
        'furniture': furniture,
        'desk': factory.make_category('Desk Test', baseline=75, parent=furniture),
        'couch': factory.make_category('Couch Test', baseline=325, parent=furniture),
        'nobaseline': factory.make_category('NoBaseline Test', parent=furniture),
    }


# ---------------------------------------------------------------------------
# Eligibility
# ---------------------------------------------------------------------------

def test_rephotographed_item_is_eligible(db, factory, cats):
    from app import _ai_autofill_eligible_query
    item = factory.make_item(category=cats['furniture'], subcategory=cats['desk'])
    ids = [i.id for i in _ai_autofill_eligible_query().all()]
    assert item.id in ids


def test_non_rephotographed_item_excluded(db, factory, cats):
    from app import _ai_autofill_eligible_query
    item = factory.make_item(category=cats['furniture'], rephotographed=False)
    ids = [i.id for i in _ai_autofill_eligible_query().all()]
    assert item.id not in ids


def test_already_ai_filled_item_excluded(db, factory, cats):
    from app import _ai_autofill_eligible_query
    item = factory.make_item(category=cats['furniture'], ai_generated_at=datetime.utcnow())
    ids = [i.id for i in _ai_autofill_eligible_query().all()]
    assert item.id not in ids


@pytest.mark.parametrize('status', ['rejected', 'sold'])
def test_rejected_and_sold_excluded(db, factory, cats, status):
    from app import _ai_autofill_eligible_query
    item = factory.make_item(category=cats['furniture'], status=status)
    ids = [i.id for i in _ai_autofill_eligible_query().all()]
    assert item.id not in ids


def test_eligible_with_null_cover(db, factory, cats):
    """Rephoto items keep photo_url NULL — they must still be eligible."""
    from app import _ai_autofill_eligible_query
    item = factory.make_item(category=cats['furniture'], subcategory=cats['desk'])
    assert item.photo_url is None
    ids = [i.id for i in _ai_autofill_eligible_query().all()]
    assert item.id in ids


# ---------------------------------------------------------------------------
# Baseline lookup
# ---------------------------------------------------------------------------

def test_baseline_prefers_subcategory(db, factory, cats):
    from app import _ai_baseline_price
    item = factory.make_item(category=cats['furniture'], subcategory=cats['couch'])
    baseline, source = _ai_baseline_price(item)
    assert baseline == 325.0
    assert source.startswith('subcategory')


def test_baseline_falls_back_to_category(db, factory, cats):
    from app import _ai_baseline_price
    item = factory.make_item(category=cats['furniture'], subcategory=cats['nobaseline'])
    baseline, source = _ai_baseline_price(item)
    assert baseline == 75.0
    assert source.startswith('category')


def test_baseline_falls_back_to_global_default(db, factory, cats):
    from app import _ai_baseline_price
    item = factory.make_item(category=None, subcategory=None)
    baseline, source = _ai_baseline_price(item)
    assert baseline == 40.0
    assert source == 'global-default'


# ---------------------------------------------------------------------------
# Full pipeline (mocked remove.bg + Anthropic)
# ---------------------------------------------------------------------------

class _FakeStorage:
    def get_photo_bytes(self, key):
        return b'\xff\xd8\xff\xe0fakejpegbytes'

    def save_photo_from_bytes(self, data, key):
        return key


def _fake_anthropic_factory(text):
    class _Msgs:
        def create(self, **kw):
            resp = type('R', (), {})()
            content = type('C', (), {})()
            content.text = text
            resp.content = [content]
            return resp

    class _Client:
        def __init__(self, *a, **k):
            self.messages = _Msgs()

    return _Client


def _patch_pipeline(monkeypatch, ai_text):
    import app as app_module
    import storage as storage_module
    import anthropic
    monkeypatch.setenv('REMOVEBG_API_KEY', 'test-key')
    monkeypatch.setattr(app_module, '_removebg_cutout', lambda b, size='full': b'PNGCUTOUT')
    monkeypatch.setattr(app_module, '_composite_on_background', lambda b, **k: b'JPGGRAY')
    monkeypatch.setattr(app_module, 'photo_storage', _FakeStorage())
    monkeypatch.setattr(storage_module, 'get_storage_instance', lambda: _FakeStorage())
    monkeypatch.setattr(anthropic, 'Anthropic', _fake_anthropic_factory(ai_text))


def _ai_text(multiplier, title='Modern Desk', desc='A sturdy wooden desk in good condition.', retail='150'):
    return (f"TITLE: {title}\n"
            f"DESCRIPTION: {desc}\n"
            f"PRICE_MULTIPLIER: {multiplier}\n"
            f"RETAIL: {retail}")


def test_pipeline_pricing_and_photos(db, factory, cats, monkeypatch):
    from app import app as _app, _process_single_item_ai
    from models import InventoryItem
    _patch_pipeline(monkeypatch, _ai_text('1.0'))
    item = factory.make_item(category=cats['furniture'], subcategory=cats['desk'])
    item_id = item.id
    ok = _process_single_item_ai(_app, item)
    assert ok is True
    refreshed = InventoryItem.query.get(item_id)
    assert float(refreshed.ai_price) == 75.0          # baseline 75 x 1.0
    assert refreshed.ai_description == 'Modern Desk'   # title staged
    assert 'sturdy wooden desk' in refreshed.ai_long_description
    assert refreshed.ai_generated_at is not None
    assert refreshed.ai_review_pending is True
    assert refreshed.ai_photo_enhanced is True
    # Cover set to processed FRONT photo (_nobg)
    assert refreshed.photo_url is not None
    assert refreshed.photo_url.endswith('_nobg.jpg')
    assert '_front_' in refreshed.photo_url
    # Every carousel photo replaced in place with a _nobg version
    for p in refreshed.gallery_photos:
        assert p.photo_url.endswith('_nobg.jpg')


def test_pipeline_multiplier_clamped_high(db, factory, cats, monkeypatch):
    from app import app as _app, _process_single_item_ai
    from models import InventoryItem
    _patch_pipeline(monkeypatch, _ai_text('3.0'))  # clamp to 1.6
    item = factory.make_item(category=cats['furniture'], subcategory=cats['couch'])
    item_id = item.id
    _process_single_item_ai(_app, item)
    refreshed = InventoryItem.query.get(item_id)
    assert float(refreshed.ai_price) == 520.0  # 325 x 1.6


def test_pipeline_multiplier_clamped_low(db, factory, cats, monkeypatch):
    from app import app as _app, _process_single_item_ai
    from models import InventoryItem
    _patch_pipeline(monkeypatch, _ai_text('0.1'))  # clamp to 0.6
    item = factory.make_item(category=cats['furniture'], subcategory=cats['couch'])
    item_id = item.id
    _process_single_item_ai(_app, item)
    refreshed = InventoryItem.query.get(item_id)
    assert float(refreshed.ai_price) == 195.0  # 325 x 0.6


def test_pipeline_price_rounded_to_five(db, factory, cats, monkeypatch):
    from app import app as _app, _process_single_item_ai
    from models import InventoryItem
    _patch_pipeline(monkeypatch, _ai_text('0.77'))  # 75 x 0.77 = 57.75 -> 60
    item = factory.make_item(category=cats['furniture'], subcategory=cats['desk'])
    item_id = item.id
    _process_single_item_ai(_app, item)
    refreshed = InventoryItem.query.get(item_id)
    assert float(refreshed.ai_price) % 5 == 0
    assert float(refreshed.ai_price) == 60.0


@pytest.mark.parametrize('setting,expected', [
    (None, 'full'),          # unset -> full (production default)
    ('full', 'full'),
    ('preview', 'preview'),
    ('bogus', 'full'),        # invalid -> full
])
def test_removebg_size_from_appsetting(db, factory, cats, monkeypatch, setting, expected):
    from app import app as _app, _process_single_item_ai
    from models import AppSetting
    captured = {}

    import app as app_module
    import storage as storage_module
    import anthropic
    monkeypatch.setenv('REMOVEBG_API_KEY', 'test-key')
    monkeypatch.setattr(app_module, '_composite_on_background', lambda b, **k: b'JPGGRAY')
    monkeypatch.setattr(app_module, 'photo_storage', _FakeStorage())
    monkeypatch.setattr(storage_module, 'get_storage_instance', lambda: _FakeStorage())
    monkeypatch.setattr(anthropic, 'Anthropic', _fake_anthropic_factory(_ai_text('1.0')))

    def _spy(b, size='full'):
        captured['size'] = size
        return b'PNGCUTOUT'
    monkeypatch.setattr(app_module, '_removebg_cutout', _spy)

    AppSetting.set('ai_removebg_size', setting) if setting is not None else \
        AppSetting.query.filter_by(key='ai_removebg_size').delete()
    db.session.commit()

    item = factory.make_item(category=cats['furniture'], subcategory=cats['desk'], views=('front',))
    _process_single_item_ai(_app, item)
    assert captured['size'] == expected

    # Don't leave a stray global setting in the snapshot.
    AppSetting.query.filter_by(key='ai_removebg_size').delete()
    db.session.commit()


def test_bg_review_includes_rephoto_pending(db, factory, cats):
    from app import _background_removal_review_query
    from models import InventoryItem
    item = factory.make_item(category=cats['furniture'], subcategory=cats['desk'])
    item.ai_review_pending = True
    db.session.commit()
    ids = [i.id for i in _background_removal_review_query().all()]
    assert item.id in ids


def test_bg_review_excludes_legacy_openai_enhanced(db, factory, cats):
    """Regression: legacy OpenAI items set ai_photo_enhanced=True but are NOT
    rephotographed — they must not appear in Background Removal Review."""
    from app import _background_removal_review_query
    from models import InventoryItem
    item = factory.make_item(category=cats['furniture'], rephotographed=False)
    item.ai_review_pending = True
    item.ai_photo_enhanced = True  # mimics old OpenAI flow
    db.session.commit()
    ids = [i.id for i in _background_removal_review_query().all()]
    assert item.id not in ids


def test_bg_review_excludes_not_pending(db, factory, cats):
    from app import _background_removal_review_query
    item = factory.make_item(category=cats['furniture'], subcategory=cats['desk'])
    # rephotographed but not pending review
    ids = [i.id for i in _background_removal_review_query().all()]
    assert item.id not in ids


def test_worker_does_not_skip_null_cover_rephoto_item(db, factory, cats, monkeypatch):
    """Regression: _run_ai_generation_single must NOT skip rephoto items just
    because photo_url (cover) is NULL — they have gallery photos."""
    import app as app_module
    from app import app as _app, _run_ai_generation_single
    called = {}
    monkeypatch.setattr(app_module, '_process_single_item_ai',
                        lambda a, item, **k: called.__setitem__('id', item.id) or True)
    item = factory.make_item(category=cats['furniture'], subcategory=cats['desk'])
    assert item.photo_url is None
    _run_ai_generation_single(_app, item.id)
    assert called.get('id') == item.id  # pipeline actually ran


def test_worker_skips_item_with_no_photos_at_all(db, factory, cats, monkeypatch):
    import app as app_module
    from app import app as _app, _run_ai_generation_single
    called = {}
    monkeypatch.setattr(app_module, '_process_single_item_ai',
                        lambda a, item, **k: called.__setitem__('id', item.id) or True)
    # No photos at all (no gallery, no cover)
    item = factory.make_item(category=cats['furniture'], subcategory=cats['desk'], views=())
    _run_ai_generation_single(_app, item.id)
    assert 'id' not in called  # pipeline skipped


def test_photo_step_skipped_for_non_rephoto_item(db, factory, cats, monkeypatch):
    """remove.bg must NOT run for non-rephotographed items (no captured_at photos)
    — protects the auto-on-submission flow from silently burning credits."""
    from app import app as _app, _process_single_item_ai
    from models import InventoryItem
    import app as app_module
    import storage as storage_module
    import anthropic
    called = {'removebg': 0}
    monkeypatch.setenv('REMOVEBG_API_KEY', 'test-key')
    monkeypatch.setattr(app_module, '_composite_on_background', lambda b, **k: b'JPGGRAY')
    monkeypatch.setattr(app_module, 'photo_storage', _FakeStorage())
    monkeypatch.setattr(storage_module, 'get_storage_instance', lambda: _FakeStorage())
    monkeypatch.setattr(anthropic, 'Anthropic', _fake_anthropic_factory(_ai_text('1.0')))
    monkeypatch.setattr(app_module, '_removebg_cutout',
                        lambda b, size='full': called.__setitem__('removebg', called['removebg'] + 1) or b'X')
    item = factory.make_item(category=cats['furniture'], subcategory=cats['desk'], rephotographed=False)
    item_id = item.id
    _process_single_item_ai(_app, item)
    assert called['removebg'] == 0            # no paid calls
    refreshed = InventoryItem.query.get(item_id)
    assert refreshed.ai_photo_enhanced is False
    assert refreshed.ai_description == 'Modern Desk'  # text still generated


def test_pipeline_originals_recoverable_naming(db, factory, cats, monkeypatch):
    """The _nobg filename is the original stem + _nobg, so the raw file is
    recoverable by dropping the suffix."""
    from app import app as _app, _process_single_item_ai
    from models import InventoryItem
    _patch_pipeline(monkeypatch, _ai_text('1.0'))
    item = factory.make_item(category=cats['furniture'], subcategory=cats['desk'], views=('front',))
    original_stem = item.gallery_photos[0].photo_url.rsplit('.', 1)[0]
    item_id = item.id
    _process_single_item_ai(_app, item)
    refreshed = InventoryItem.query.get(item_id)
    assert refreshed.gallery_photos[0].photo_url == f'{original_stem}_nobg.jpg'


# ---------------------------------------------------------------------------
# Publish (rephoto item → shop) — order-independent go-live
# ---------------------------------------------------------------------------

def _make_publishable(db, factory, cats):
    """A rephoto item detached from the session with every shop-ready field set.
    Detached (expunged) so we can assign placeholder FK ids without autoflush
    tripping FK constraints during teardown."""
    item = factory.make_item(category=cats['furniture'], subcategory=cats['desk'])
    db.session.expunge(item)
    item.status = 'pending_valuation'
    item.ai_approved = True
    item.seller_id = 999001
    item.storage_location_id = 888001
    item.price = 40
    item.photo_url = 'rephoto_front_nobg.jpg'
    item.needs_new_photo = False
    return item


def test_publish_when_all_ready(db, factory, cats):
    from app import _publish_rephoto_if_ready
    item = _make_publishable(db, factory, cats)
    assert _publish_rephoto_if_ready(item) is True
    assert item.status == 'available'


def test_no_publish_without_storage(db, factory, cats):
    from app import _publish_rephoto_if_ready
    item = _make_publishable(db, factory, cats)
    item.storage_location_id = None
    assert _publish_rephoto_if_ready(item) is False
    assert item.status == 'pending_valuation'


def test_no_publish_without_seller(db, factory, cats):
    from app import _publish_rephoto_if_ready
    item = _make_publishable(db, factory, cats)
    item.seller_id = None
    assert _publish_rephoto_if_ready(item) is False


def test_no_publish_when_not_ai_approved(db, factory, cats):
    from app import _publish_rephoto_if_ready
    item = _make_publishable(db, factory, cats)
    item.ai_approved = False
    assert _publish_rephoto_if_ready(item) is False


def test_no_publish_without_price(db, factory, cats):
    from app import _publish_rephoto_if_ready
    item = _make_publishable(db, factory, cats)
    item.price = 0
    assert _publish_rephoto_if_ready(item) is False


def test_no_publish_when_needs_new_photo(db, factory, cats):
    from app import _publish_rephoto_if_ready
    item = _make_publishable(db, factory, cats)
    item.needs_new_photo = True
    assert _publish_rephoto_if_ready(item) is False


def test_no_publish_when_already_sold(db, factory, cats):
    from app import _publish_rephoto_if_ready
    item = _make_publishable(db, factory, cats)
    item.status = 'sold'
    assert _publish_rephoto_if_ready(item) is False
    assert item.status == 'sold'  # untouched
