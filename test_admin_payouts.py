"""Tests for the admin payouts page and payout marking.

Run with: python3 -m pytest test_admin_payouts.py -v

Regression context (2026-08-11): /admin/payouts returned 500 for every request.
The route put the seller's payout lines under a dict key named 'items', and
`group.items` in Jinja resolves to dict.items — the bound method — not the key,
so the template raised "builtin_function_or_method object has no element 0".
The key is now 'lines'.
"""

import uuid

import pytest


def _uid():
    return uuid.uuid4().hex[:10]


@pytest.fixture(scope='module')
def payout_app():
    from app import app as _app
    _app.config['TESTING'] = True
    _app.config['WTF_CSRF_ENABLED'] = False
    _app.config['SERVER_NAME'] = 'localhost'
    return _app


@pytest.fixture
def payout_fixtures(payout_app):
    """A seller with 3 sold-unpaid items, and one with no payout handle."""
    from app import db
    from models import User, InventoryItem
    tag = _uid()

    with payout_app.app_context():
        seller = User(email=f'payout_seller_{tag}@test.com', full_name='Payout Seller',
                      is_seller=True, payout_method='Venmo', payout_handle=f'@handle{tag}')
        nohandle = User(email=f'payout_nohandle_{tag}@test.com', full_name='No Handle',
                        is_seller=True)
        for u in (seller, nohandle):
            u.set_password('testpass123')
        db.session.add_all([seller, nohandle])
        db.session.flush()

        items = []
        for i, price in enumerate([100, 50, 25]):
            it = InventoryItem(seller_id=seller.id, description=f'Payout item {i} {tag}',
                               price=price, status='sold', payout_sent=False)
            db.session.add(it)
            items.append(it)
        orphan = InventoryItem(seller_id=nohandle.id, description=f'No handle item {tag}',
                               price=40, status='sold', payout_sent=False)
        db.session.add(orphan)
        db.session.commit()

        data = {
            'seller_id': seller.id,
            'seller_email': seller.email,
            'handle': seller.payout_handle,
            'nohandle_id': nohandle.id,
            'item_ids': [i.id for i in items],
            'orphan_id': orphan.id,
            'expected_total': 87.50,   # 50% of 100 + 50 + 25
        }
        yield data

    with payout_app.app_context():
        from sqlalchemy import delete
        db.session.execute(delete(InventoryItem).where(
            InventoryItem.id.in_(data['item_ids'] + [data['orphan_id']])))
        db.session.execute(delete(User).where(
            User.id.in_([data['seller_id'], data['nohandle_id']])))
        db.session.commit()


def _admin_client(payout_app):
    from models import User
    c = payout_app.test_client()
    with payout_app.app_context():
        aid = User.query.filter_by(is_super_admin=True).first().id
    with c.session_transaction() as sess:
        sess['_user_id'] = str(aid)
        sess['_fresh'] = True
    return c


class TestPayoutsPageLoads:
    def test_unpaid_tab_renders(self, payout_app, payout_fixtures):
        """This is the regression: the page 500'd on every load."""
        r = _admin_client(payout_app).get('/admin/payouts')
        assert r.status_code == 200

    def test_paid_tab_renders(self, payout_app, payout_fixtures):
        r = _admin_client(payout_app).get('/admin/payouts?tab=paid')
        assert r.status_code == 200

    def test_csv_export_still_works(self, payout_app, payout_fixtures):
        r = _admin_client(payout_app).get('/admin/payouts/export')
        assert r.status_code == 200

    def test_template_never_uses_the_colliding_key(self):
        """`group.items` silently resolves to dict.items() in Jinja."""
        src = open('templates/admin/payouts.html').read()
        assert 'group.items' not in src, \
            "group.items resolves to dict.items (a method), not the payout lines"
        assert 'group.lines' in src

    def test_route_exposes_lines_not_items(self):
        src = open('app.py').read()
        assert "'lines': []," in src
        assert "seller_groups[sid]['lines'].append" in src


class TestPayoutCardContent:
    def test_card_shows_handle_and_total(self, payout_app, payout_fixtures):
        body = _admin_client(payout_app).get('/admin/payouts').get_data(as_text=True)
        assert payout_fixtures['handle'] in body, 'the handle is what gets pasted into Venmo'
        assert f"{payout_fixtures['expected_total']:.2f}" in body
        assert 'Payout Seller' in body

    def test_missing_handle_is_called_out(self, payout_app, payout_fixtures):
        body = _admin_client(payout_app).get('/admin/payouts').get_data(as_text=True)
        assert 'No payout handle on file' in body, \
            'paying a seller with no handle must be blocked visibly'

    def test_every_item_is_listed_with_its_payout(self, payout_app, payout_fixtures):
        body = _admin_client(payout_app).get('/admin/payouts').get_data(as_text=True)
        for item_id in payout_fixtures['item_ids']:
            assert f'#{item_id}' in body
        for amt in ('50.00', '25.00', '12.50'):   # 50% of 100 / 50 / 25
            assert amt in body


class TestMarkSellerPaid:
    def test_marks_every_item_and_sends_one_email(self, payout_app, monkeypatch,
                                                  payout_fixtures):
        import app as app_module
        from app import db
        from models import InventoryItem

        sent = []
        monkeypatch.setattr(app_module, 'send_email',
                            lambda to, subject, html, **kw: sent.append((to, subject, html)))

        c = _admin_client(payout_app)
        r = c.post(f"/admin/payouts/seller/{payout_fixtures['seller_id']}/mark_paid",
                   follow_redirects=True)
        assert r.status_code == 200

        with payout_app.app_context():
            db.session.expire_all()
            items = InventoryItem.query.filter(
                InventoryItem.id.in_(payout_fixtures['item_ids'])).all()
            assert all(i.payout_sent for i in items)
            assert all(i.payout_sent_at is not None for i in items)

        assert len(sent) == 1, f'one grouped email expected, got {len(sent)}'
        to, subject, html = sent[0]
        assert to == payout_fixtures['seller_email']
        assert 'items' in subject
        assert '87.50' in html, 'grouped email should show the total sent'
        assert payout_fixtures['handle'] in html

    def test_is_idempotent(self, payout_app, monkeypatch, payout_fixtures):
        import app as app_module
        sent = []
        monkeypatch.setattr(app_module, 'send_email',
                            lambda to, subject, html, **kw: sent.append(to))
        c = _admin_client(payout_app)
        url = f"/admin/payouts/seller/{payout_fixtures['seller_id']}/mark_paid"
        c.post(url)
        r2 = c.post(url, follow_redirects=True)
        assert 'Nothing unpaid' in r2.get_data(as_text=True)
        assert len(sent) == 1, 'second call must not re-send'

    def test_single_item_email_keeps_singular_copy(self, payout_app, monkeypatch,
                                                  payout_fixtures):
        import app as app_module
        sent = []
        monkeypatch.setattr(app_module, 'send_email',
                            lambda to, subject, html, **kw: sent.append((subject, html)))
        c = _admin_client(payout_app)
        c.post(f"/admin/payouts/seller/{payout_fixtures['nohandle_id']}/mark_paid")
        subject, html = sent[0]
        assert subject.endswith('item!'), subject
        assert 'Sale price:' in html

    def test_requires_admin(self, payout_app, payout_fixtures):
        with payout_app.test_client() as c:
            with c.session_transaction() as sess:
                sess.clear()
            r = c.post(f"/admin/payouts/seller/{payout_fixtures['seller_id']}/mark_paid")
        assert r.status_code in (302, 401, 403)


class TestPayoutEmailBuilder:
    def test_grouped_email_lists_each_item_and_total(self, payout_app, payout_fixtures):
        import app as app_module
        from models import InventoryItem, User

        with payout_app.test_request_context('/'):
            items = InventoryItem.query.filter(
                InventoryItem.id.in_(payout_fixtures['item_ids'])).all()
            seller = User.query.get(payout_fixtures['seller_id'])
            html = app_module._payout_sent_email_html(items, seller)

        assert '3 items' in html
        for amt in ('50.00', '25.00', '12.50', '87.50'):
            assert amt in html
        assert 'Total sent' in html

    def test_subject_switches_on_count(self):
        from app import _payout_sent_subject
        assert _payout_sent_subject(1).endswith('item!')
        assert _payout_sent_subject(4).endswith('items!')
