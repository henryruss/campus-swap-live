"""Tests for the Shop Drop waitlist (ShopNotifySignup).

Run with: python3 -m pytest test_shop_notify_signup.py -v

Regression context (2026-08-11): the model and both routes existed but no
migration ever created the `shop_notify_signup` table. The admin CSV export
500'd, and POST /shop/notify would have 500'd as soon as shop_teaser_mode was
switched on for a pre-launch. Migration 982051a9ce5d creates the table; these
tests fail loudly if it ever goes missing again.
"""

import uuid

import pytest


def _uid():
    return uuid.uuid4().hex[:10]


@pytest.fixture(scope='module')
def notify_client():
    from app import app as _app
    _app.config['TESTING'] = True
    _app.config['WTF_CSRF_ENABLED'] = False
    _app.config['SERVER_NAME'] = 'localhost'
    with _app.test_client() as client:
        yield client


@pytest.fixture
def clean_signups(notify_client):
    """Track emails created by a test and delete them afterwards."""
    from app import app as _app, db
    from models import ShopNotifySignup
    from sqlalchemy import delete

    created = []
    yield created

    if created:
        with _app.app_context():
            db.session.execute(
                delete(ShopNotifySignup).where(ShopNotifySignup.email.in_(created))
            )
            db.session.commit()


class TestSignupCapture:
    def test_table_exists(self):
        """Guards against the model existing with no migration behind it."""
        from app import app as _app
        from models import ShopNotifySignup
        with _app.app_context():
            ShopNotifySignup.query.count()  # raises ProgrammingError if table is missing

    def test_post_creates_a_row(self, notify_client, clean_signups):
        from app import app as _app
        from models import ShopNotifySignup

        email = f'waitlist_{_uid()}@example.com'
        clean_signups.append(email)

        r = notify_client.post('/shop/notify', data={'email': email})
        assert r.status_code == 302

        with _app.app_context():
            row = ShopNotifySignup.query.filter_by(email=email).first()
            assert row is not None
            assert row.created_at is not None
            assert row.ip_address  # captured for spam review

    def test_email_is_lowercased_and_trimmed(self, notify_client, clean_signups):
        from app import app as _app
        from models import ShopNotifySignup

        tag = _uid()
        email = f'Waitlist_{tag}@Example.COM'
        clean_signups.append(email.strip().lower())

        notify_client.post('/shop/notify', data={'email': f'  {email}  '})
        with _app.app_context():
            assert ShopNotifySignup.query.filter_by(email=email.lower()).first() is not None

    def test_empty_email_creates_no_row(self, notify_client):
        from app import app as _app
        from models import ShopNotifySignup

        with _app.app_context():
            before = ShopNotifySignup.query.count()
        r = notify_client.post('/shop/notify', data={'email': '   '})
        assert r.status_code == 302
        with _app.app_context():
            assert ShopNotifySignup.query.count() == before

    def test_duplicates_are_allowed(self, notify_client, clean_signups):
        """No unique constraint by design — a repeat signup must not 500."""
        from app import app as _app
        from models import ShopNotifySignup

        email = f'waitlist_dup_{_uid()}@example.com'
        clean_signups.append(email)

        for _ in range(2):
            assert notify_client.post('/shop/notify', data={'email': email}).status_code == 302
        with _app.app_context():
            assert ShopNotifySignup.query.filter_by(email=email).count() == 2


class TestAdminExport:
    def _login_super_admin(self, notify_client):
        from app import app as _app
        from models import User
        with _app.app_context():
            admin = User.query.filter_by(is_super_admin=True).first()
            assert admin is not None, 'no super admin in DB to test with'
            aid = admin.id
        with notify_client.session_transaction() as sess:
            sess['_user_id'] = str(aid)
            sess['_fresh'] = True

    def test_export_returns_csv(self, notify_client, clean_signups):
        email = f'waitlist_csv_{_uid()}@example.com'
        clean_signups.append(email)
        notify_client.post('/shop/notify', data={'email': email})

        self._login_super_admin(notify_client)
        r = notify_client.get('/admin/export/notify-signups')

        assert r.status_code == 200
        assert 'csv' in r.headers.get('Content-Type', '')
        body = r.get_data(as_text=True)
        assert body.splitlines()[0] == 'Email,Signed Up At,IP Address'
        assert email in body

    def test_export_requires_login(self, notify_client):
        with notify_client.session_transaction() as sess:
            sess.clear()
        r = notify_client.get('/admin/export/notify-signups')
        assert r.status_code in (302, 401), 'anonymous users must not reach the export'
