"""Tests for junk crew access and the dev-only account switch.

Run: python3 -m pytest test_junk_crew.py -q

SAFE against campusswap_prod: requests nothing from either conftest (their `app`/`db`
fixtures drop_all()). Every user created here is deleted in teardown, including the dev
accounts if (and only if) a test created them.
"""
import uuid

import pytest
from flask import g
from flask.testing import FlaskClient
from werkzeug.security import generate_password_hash

from app import app as flask_app, db
from models import User
from junk.routes import DEV_ACCOUNTS


@pytest.fixture
def app_ctx():
    flask_app.config['TESTING'] = True
    flask_app.config['WTF_CSRF_ENABLED'] = False
    with flask_app.app_context():
        yield flask_app
        db.session.rollback()
    flask_app.config.pop('JUNK_DEV_SWITCH', None)
    flask_app.config.pop('SITE_LOCKED_TO_JUNK', None)


@pytest.fixture
def tracked(app_ctx):
    dev_emails = [e for e, _, _ in DEV_ACCOUNTS.values()]
    existed = {e for (e,) in db.session.query(User.email).filter(User.email.in_(dev_emails))}
    created = {'users': []}
    yield created
    db.session.rollback()
    new_dev = [e for e in dev_emails if e not in existed]
    db.session.execute(db.delete(User).where(
        User.id.in_(created['users']) | User.email.in_(new_dev)))
    db.session.commit()


@pytest.fixture
def make_user(tracked):
    def _factory(password=None, **flags):
        u = User(email=f"jr-crew-test-{uuid.uuid4().hex[:10]}@example.com", full_name='Test Person',
                 password_hash=generate_password_hash(password) if password else None, **flags)
        db.session.add(u)
        db.session.commit()
        tracked['users'].append(u.id)
        return u
    return _factory


class _Client(FlaskClient):
    """The fixtures hold one app context across requests, so Flask-Login's per-request user
    cache (g._login_user) would leak between users within a test. Clear it per request."""
    def open(self, *args, **kwargs):
        g.pop('_login_user', None)
        return super().open(*args, **kwargs)


def _client():
    return _Client(flask_app, flask_app.response_class, use_cookies=True)


def _login(uid):
    c = _client()
    with c.session_transaction() as s:
        s['_user_id'] = str(uid)
        s['_fresh'] = True
    return c


def _path(resp):
    return resp.headers.get('Location', '').split('?')[0]


# ── crew access ────────────────────────────────────────────

def test_crew_home_guard(make_user):
    assert _path(_client().get('/junk/crew')) == '/junk/login'
    assert _login(make_user(is_junk_crew=True).id).get('/junk/crew').status_code == 200
    assert _login(make_user(is_junk_manager=True).id).get('/junk/crew').status_code == 200
    assert _login(make_user(is_worker=True, worker_status='approved').id).get('/junk/crew').status_code == 403


def test_crew_sent_home_from_manager_pages(make_user):
    c = _login(make_user(is_junk_crew=True).id)
    assert _path(c.get('/junk/manage')) == '/junk/crew'
    assert c.post('/junk/manage/job', data={}).status_code == 403
    assert c.post('/junk/manage/board/move', json={}).status_code == 403


def test_landing_by_role(make_user):
    assert _path(_login(make_user(is_junk_crew=True).id).get('/junk/')) == '/junk/crew'
    assert _path(_login(make_user(is_junk_manager=True).id).get('/junk/')) == '/junk/manage'
    both = _login(make_user(is_junk_manager=True, is_junk_crew=True).id)
    assert _path(both.get('/junk/')) == '/junk/manage'
    assert both.get('/junk/crew').status_code == 200


def test_crew_confined_to_junk(make_user):
    c = _login(make_user(is_junk_crew=True).id)
    assert _path(c.get('/dashboard')) == '/junk/crew'
    assert _path(c.get('/logout')) == '/junk/logout'


def test_crew_password_sign_in(make_user):
    u = make_user(password='crewpass123', is_junk_crew=True)
    r = _client().post('/junk/login', data={'email': u.email, 'password': 'crewpass123'})
    assert _path(r) == '/junk/crew'
    nobody = make_user(password='crewpass123')
    r = _client().post('/junk/login', data={'email': nobody.email, 'password': 'crewpass123'})
    assert r.status_code == 200 and b"have access yet" in r.data


def test_tabs_by_role(make_user):
    crew_page = _login(make_user(is_junk_crew=True).id).get('/junk/crew').data
    assert b'My jobs' in crew_page and b'>Calendar<' not in crew_page
    mgr_page = _login(make_user(is_junk_manager=True).id).get('/junk/manage').data
    assert b'>Calendar<' in mgr_page and b'My jobs' not in mgr_page


def test_site_lock_sends_crew_home(app_ctx, make_user):
    flask_app.config['SITE_LOCKED_TO_JUNK'] = True
    u = make_user(is_junk_crew=True, is_admin=False)
    assert _path(_login(u.id).get('/')) == '/junk/crew'


# ── dev switch ─────────────────────────────────────────────

def test_dev_switch_off_by_default_under_tests(tracked):
    c = _client()
    assert c.post('/junk/dev/as/crew').status_code == 404
    assert b'jr-dev' not in c.get('/junk/login').data


def test_dev_switch_off_on_render(app_ctx, tracked, monkeypatch):
    flask_app.config['TESTING'] = False
    monkeypatch.setenv('RENDER', 'true')
    try:
        with flask_app.test_request_context():
            from junk.routes import dev_switch_enabled
            flask_app.debug = True
            assert dev_switch_enabled() is False
    finally:
        flask_app.debug = False
        flask_app.config['TESTING'] = True


def test_dev_switch_both_ways(app_ctx, tracked):
    flask_app.config['JUNK_DEV_SWITCH'] = True
    c = _client()
    assert b'jr-dev' in c.get('/junk/login').data
    assert _path(c.post('/junk/dev/as/manager')) == '/junk/manage'
    assert c.get('/junk/manage').status_code == 200
    assert _path(c.post('/junk/dev/as/crew')) == '/junk/crew'
    assert _path(c.get('/junk/manage')) == '/junk/crew'
    assert c.post('/junk/dev/as/admin').status_code == 404
    crew = User.query.filter_by(email=DEV_ACCOUNTS['crew'][0]).one()
    assert crew.is_junk_crew and not crew.is_junk_manager and not crew.is_admin


# ── team page ──────────────────────────────────────────────

def test_team_page_guard(make_user):
    assert _login(make_user(is_junk_manager=True).id).get('/junk/manage/team').status_code == 200
    assert _path(_login(make_user(is_junk_crew=True).id).get('/junk/manage/team')) == '/junk/crew'
    crew = make_user(is_junk_crew=True)
    assert _login(crew.id).post('/junk/manage/team/add', data={'email': 'x@example.com'}).status_code == 403
    assert _login(crew.id).post(f'/junk/manage/team/{crew.id}/remove').status_code == 403


def test_team_lists_managers_and_crew(make_user):
    mgr = make_user(is_junk_manager=True)
    crew = make_user(is_junk_crew=True, phone='9195550142')
    seller = make_user()
    page = _login(mgr.id).get('/junk/manage/team').data.decode()
    assert crew.email in page and '(919) 555-0142' in page
    assert seller.email not in page


def test_add_new_crew_creates_account_without_password(tracked, make_user):
    c = _login(make_user(is_junk_manager=True).id)
    email = f"jr-crew-test-{uuid.uuid4().hex[:10]}@example.com"
    r = c.post('/junk/manage/team/add', data={'email': email, 'name': 'Jo Crew', 'phone': '919 555 0100'})
    assert _path(r) == '/junk/manage/team'
    u = User.query.filter_by(email=email).one()
    tracked['users'].append(u.id)
    assert u.is_junk_crew and not u.is_junk_manager and not u.is_admin
    assert u.password_hash is None and u.full_name == 'Jo Crew' and u.phone == '919 555 0100'


def test_add_existing_account_keeps_its_details(make_user):
    c = _login(make_user(is_junk_manager=True).id)
    u = make_user(phone='1112223333')
    c.post('/junk/manage/team/add', data={'email': u.email.upper(), 'name': 'Other Name', 'phone': '999'})
    db.session.refresh(u)
    assert u.is_junk_crew and u.full_name == 'Test Person' and u.phone == '1112223333'


def test_add_rejects_bad_and_duplicate(make_user):
    c = _login(make_user(is_junk_manager=True).id)
    before = User.query.count()
    r = c.post('/junk/manage/team/add', data={'email': 'not an email'})
    assert 'add=1' in r.headers['Location'] and User.query.count() == before
    crew = make_user(is_junk_crew=True)
    r = c.post('/junk/manage/team/add', data={'email': crew.email})
    assert 'add=1' in r.headers['Location']


def test_remove_clears_flag_never_deletes(make_user):
    c = _login(make_user(is_junk_manager=True).id)
    crew = make_user(is_junk_crew=True)
    assert _path(c.post(f'/junk/manage/team/{crew.id}/remove')) == '/junk/manage/team'
    db.session.refresh(crew)
    assert crew.is_junk_crew is False and db.session.get(User, crew.id) is not None
    # Removed crew lose access.
    assert _login(crew.id).get('/junk/crew').status_code == 403
    # Not crew (already removed, or a manager) → 404.
    assert c.post(f'/junk/manage/team/{crew.id}/remove').status_code == 404
