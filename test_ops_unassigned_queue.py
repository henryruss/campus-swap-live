"""Tests for the admin ops unassigned-pickup queue.

Run with: python3 -m pytest test_ops_unassigned_queue.py -v

Regression context (2026-08-11): the ops panel showed 48+ bogus "re-pickup"
sellers. Two independent causes:

1. _get_re_pickup_seller_ids() flagged any seller with items whose date_added
   was after their completed pickup. Warehouse-side flows (rephotography
   add-path, quick capture) create InventoryItem rows for stock collected
   months earlier, so all of them read as "send another truck".
2. _admin_routes_index_data() did not filter is_tutorial_user, so sandbox
   sellers from the campus-director tutorial leaked into the live panel.
"""

import uuid
from datetime import datetime, timedelta

import pytest


def _uid():
    return uuid.uuid4().hex[:10]


@pytest.fixture(scope='module')
def ops_app():
    from app import app as _app
    _app.config['TESTING'] = True
    _app.config['SERVER_NAME'] = 'localhost'
    return _app


@pytest.fixture
def ops_fixtures(ops_app):
    """Sellers whose post-pickup items are warehouse-side vs genuinely uncollected."""
    from app import db
    from models import (User, InventoryItem, ShiftPickup, Shift, ShiftWeek,
                        StorageLocation)
    tag = _uid()
    completed_at = datetime(2026, 5, 10, 12, 0, 0)
    later = completed_at + timedelta(days=60)

    with ops_app.app_context():
        week = ShiftWeek.query.filter_by(is_tutorial=False).first()
        shift = Shift(week_id=week.id, day_of_week='fri', slot='am', is_active=True)
        db.session.add(shift)

        storage = StorageLocation.query.first()

        def mk_seller(email_prefix, **kw):
            u = User(email=f'{email_prefix}_{tag}@test.com', full_name=f'{email_prefix} {tag}',
                     is_seller=True, **kw)
            u.set_password('testpass123')
            db.session.add(u)
            return u

        # Each of these had a completed pickup, then gained one post-pickup item
        s_storage = mk_seller('ops_storage')      # item already in a storage unit
        s_qc = mk_seller('ops_qc')                # item created at the warehouse
        s_pickedup = mk_seller('ops_pickedup')    # item already collected
        s_rejected = mk_seller('ops_rejected')    # item was rejected
        s_real = mk_seller('ops_real')            # genuinely awaiting collection
        s_tutorial = mk_seller('ops_tutorial', is_tutorial_user=True)
        db.session.flush()

        sellers = [s_storage, s_qc, s_pickedup, s_rejected, s_real, s_tutorial]
        for s in sellers:
            db.session.add(ShiftPickup(shift_id=shift.id, seller_id=s.id, truck_number=1,
                                       status='completed', completed_at=completed_at))

        items = {}
        specs = [
            (s_storage, dict(storage_location_id=storage.id if storage else None)),
            (s_qc, dict(is_quick_capture=True)),
            (s_pickedup, dict(picked_up_at=later)),
            (s_rejected, dict(status='rejected')),
            (s_real, dict()),
            (s_tutorial, dict()),
        ]
        for seller, extra in specs:
            kwargs = dict(seller_id=seller.id, description=f'Ops item {seller.id} {tag}',
                          price=60, status='available', date_added=later)
            kwargs.update(extra)
            it = InventoryItem(**kwargs)
            db.session.add(it)
            items[seller.id] = it
        db.session.commit()

        data = {
            'storage_id': s_storage.id,
            'qc_id': s_qc.id,
            'pickedup_id': s_pickedup.id,
            'rejected_id': s_rejected.id,
            'real_id': s_real.id,
            'tutorial_id': s_tutorial.id,
            'has_storage_location': storage is not None,
            '_cleanup': {
                'seller_ids': [s.id for s in sellers],
                'item_ids': [i.id for i in items.values()],
                'shift_id': shift.id,
            },
        }
        yield data

    with ops_app.app_context():
        from sqlalchemy import delete
        c = data['_cleanup']
        db.session.execute(delete(ShiftPickup).where(ShiftPickup.seller_id.in_(c['seller_ids'])))
        db.session.execute(delete(InventoryItem).where(InventoryItem.id.in_(c['item_ids'])))
        db.session.execute(delete(Shift).where(Shift.id == c['shift_id']))
        db.session.execute(delete(User).where(User.id.in_(c['seller_ids'])))
        db.session.commit()


class TestRePickupDetection:
    def _flagged(self, ops_app):
        import app as app_module
        with ops_app.app_context():
            return app_module._get_re_pickup_seller_ids()

    def test_genuinely_uncollected_item_flags_a_re_pickup(self, ops_app, ops_fixtures):
        assert ops_fixtures['real_id'] in self._flagged(ops_app)

    def test_item_already_in_storage_does_not_flag(self, ops_app, ops_fixtures):
        if not ops_fixtures['has_storage_location']:
            pytest.skip('no StorageLocation rows available in this DB')
        assert ops_fixtures['storage_id'] not in self._flagged(ops_app)

    def test_quick_capture_item_does_not_flag(self, ops_app, ops_fixtures):
        """QC items are created at the warehouse — nothing to collect."""
        assert ops_fixtures['qc_id'] not in self._flagged(ops_app)

    def test_already_picked_up_item_does_not_flag(self, ops_app, ops_fixtures):
        assert ops_fixtures['pickedup_id'] not in self._flagged(ops_app)

    def test_rejected_item_does_not_flag(self, ops_app, ops_fixtures):
        """Never worth sending a truck for something we declined."""
        assert ops_fixtures['rejected_id'] not in self._flagged(ops_app)


class TestNeedsCollectionFilters:
    def test_filters_exclude_all_warehouse_side_signals(self, ops_app, ops_fixtures):
        import app as app_module
        from models import InventoryItem

        with ops_app.app_context():
            q = InventoryItem.query.filter(
                InventoryItem.seller_id.in_(ops_fixtures['_cleanup']['seller_ids']),
                *app_module._needs_collection_filters(),
            ).all()
            seller_ids = {i.seller_id for i in q}

        assert ops_fixtures['real_id'] in seller_ids
        assert ops_fixtures['tutorial_id'] in seller_ids  # filters are about collection, not tutorial
        for key in ('qc_id', 'pickedup_id', 'rejected_id'):
            assert ops_fixtures[key] not in seller_ids, key
        if ops_fixtures['has_storage_location']:
            assert ops_fixtures['storage_id'] not in seller_ids


class TestTutorialSellersExcludedFromOpsPanel:
    def test_tutorial_seller_never_appears_in_unassigned_pool(self, ops_app, ops_fixtures):
        """Sandbox sellers from the campus-director tutorial must not reach live ops."""
        import app as app_module
        from models import User

        with ops_app.test_request_context('/'):
            data = app_module._admin_routes_index_data()
            counts = data['seller_unit_counts']

        assert ops_fixtures['tutorial_id'] not in counts, \
            'tutorial seller leaked into the ops unassigned queue'

        with ops_app.app_context():
            tutorial_ids = {u.id for u in User.query.filter_by(is_tutorial_user=True).all()}
        assert not (tutorial_ids & set(counts)), \
            f'tutorial sellers in unassigned pool: {tutorial_ids & set(counts)}'


# ---------------------------------------------------------------------------
# Crew delivery stop card — the full page and the 30s refresh must not drift
# ---------------------------------------------------------------------------

class TestDeliveryStopCardParity:
    """The auto-refresh partial used to omit Mark Delivered / Flag Issue, so the
    buttons vanished 30s after page load. Both now render one shared macro."""

    MACRO = 'templates/crew/_delivery_stop_card.html'

    def test_only_the_macro_defines_the_action_buttons(self):
        """Guard against a second copy of the card being reintroduced."""
        for path in ('templates/crew/delivery.html',
                     'templates/crew/delivery_stops_partial.html'):
            src = open(path).read()
            assert 'stop_card(' in src, f'{path} should render the shared macro'
            # Match button markup, not the .btn-stop-action CSS rule (which
            # legitimately lives in delivery.html for the macro to use).
            assert 'class="btn-stop-action' not in src, \
                f'{path} has its own copy of the actions — it must use the macro'
            assert 'crew_delivery_stop_update' not in src, \
                f'{path} builds its own status form — it must use the macro'

    def test_macro_gates_actions_on_an_active_run(self):
        src = open(self.MACRO).read()
        assert 'btn-stop-action btn-complete' in src
        assert "delivery_run and delivery_run.status == 'in_progress'" in src

    def test_macro_shows_maps_link_regardless_of_run_state(self):
        """Drivers plan the route before tapping Start Run."""
        src = open(self.MACRO).read()
        maps_at = src.index('fa-map-marked-alt')
        gate_at = src.index("{% if stop.status == 'pending' and delivery_run")
        assert maps_at < gate_at, 'maps link must sit outside the run-gated block'

    def test_directions_start_at_the_warehouse(self, ops_app):
        import app as app_module
        src = open(self.MACRO).read()
        assert 'maps/dir/?api=1&origin=' in src
        assert 'warehouse_address | urlencode' in src
        with ops_app.app_context():
            addr = app_module.get_warehouse_address()
        assert '515 S Greensboro' in addr
        assert 'Carrboro' in addr, \
            'origin must be fully qualified or Google geocodes it ambiguously'


class TestEmailSuppressionInDev:
    """The local DB is a copy of prod, so dev runs must not email real buyers."""

    def test_suppressed_on_a_debug_server(self, monkeypatch, ops_app):
        import app as app_module
        monkeypatch.delenv('SUPPRESS_EMAILS', raising=False)
        monkeypatch.setattr(ops_app, 'debug', True)
        monkeypatch.delenv('FLASK_ENV', raising=False)
        assert app_module._emails_suppressed() is True

    def test_not_suppressed_in_production(self, monkeypatch, ops_app):
        import app as app_module
        monkeypatch.delenv('SUPPRESS_EMAILS', raising=False)
        monkeypatch.setattr(ops_app, 'debug', False)
        assert app_module._emails_suppressed() is False

    def test_env_var_overrides_both_ways(self, monkeypatch, ops_app):
        import app as app_module
        monkeypatch.setattr(ops_app, 'debug', False)
        monkeypatch.setenv('SUPPRESS_EMAILS', '1')
        assert app_module._emails_suppressed() is True
        monkeypatch.setattr(ops_app, 'debug', True)
        monkeypatch.setenv('SUPPRESS_EMAILS', '0')
        assert app_module._emails_suppressed() is False

    def test_send_email_short_circuits_when_suppressed(self, monkeypatch, ops_app):
        import app as app_module
        calls = []
        monkeypatch.setattr(app_module.resend, 'api_key', 'test-key')
        monkeypatch.setattr(app_module, '_resend_send_throttled', lambda d, **kw: calls.append(d))
        monkeypatch.setenv('SUPPRESS_EMAILS', '1')
        with ops_app.test_request_context('/'):
            assert app_module.send_email('real.buyer@gmail.com', 'Delivered!', '<p>x</p>') is True
        assert calls == [], 'no Resend call may be made while suppressed'
