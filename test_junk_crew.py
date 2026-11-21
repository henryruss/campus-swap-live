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
from junk.models import Job, JobAssignment, JobEvent


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
    uids = created['users']
    if uids:
        job_ids = [j for (j,) in db.session.query(Job.id).filter(Job.created_by_id.in_(uids))]
        db.session.execute(db.delete(JobAssignment).where(
            JobAssignment.job_id.in_(job_ids) | JobAssignment.user_id.in_(uids)))
        db.session.execute(db.delete(JobEvent).where(JobEvent.job_id.in_(job_ids) | JobEvent.user_id.in_(uids)))
        db.session.execute(db.delete(Job).where(Job.id.in_(job_ids)))
    db.session.execute(db.delete(User).where(
        User.id.in_(created['users']) | User.email.in_(new_dev)))
    db.session.commit()


@pytest.fixture
def make_user(tracked):
    def _factory(password=None, **flags):
        flags.setdefault('full_name', 'Test Person')
        u = User(email=f"jr-crew-test-{uuid.uuid4().hex[:10]}@example.com",
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
    assert b'>Calendar<' in mgr_page and b'>My jobs<' in mgr_page   # managers work jobs too (Henry, 2026-11-19)


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


# ── preview tools for super admins (works on the live server) ──

def test_preview_pills_super_admin_only(make_user):
    """Off the dev server: super admins get the pills (view-as forms, not dev sign-in);
    junk managers and crew never do."""
    boss = make_user(is_super_admin=True, is_admin=True)
    page = _login(boss.id).get('/junk/manage').data.decode()
    assert 'jr-devbar' in page
    assert '/junk/dev/view/crew' in page and '/junk/dev/as/' not in page
    mgr = make_user(is_junk_manager=True)
    page = _login(mgr.id).get('/junk/manage').data.decode()
    assert 'jr-devbar' not in page


def test_navy_and_forest_is_locked_in_for_everyone(make_user):
    """One look for everyone (Henry, 2026-11-20); the other themes are shelved, with no switch."""
    for u in (make_user(is_super_admin=True), make_user(is_junk_manager=True), make_user(is_junk_crew=True)):
        g.pop('_login_user', None)
        c = _login(u.id)
        c.set_cookie('jr_theme', 'ledger')   # an old preview cookie changes nothing
        page = c.get('/junk/crew').data.decode()
        assert 'data-jr-theme="navyforest"' in page and 'themes/navyforest.css' in page
        assert 'themes/ledger.css' not in page and 'data-group="theme"' not in page


def test_super_admin_view_as_crew_and_back(make_user):
    boss = make_user(is_super_admin=True)
    c = _login(boss.id)
    assert _path(c.post('/junk/dev/view/crew')) == '/junk/crew'
    assert _path(c.get('/junk/manage')) == '/junk/crew'          # manager pages send them to crew
    assert c.get('/junk/crew').status_code == 200
    assert _path(c.post('/junk/dev/view/manager')) == '/junk/manage'
    assert c.get('/junk/manage').status_code == 200
    db.session.refresh(boss)
    assert not boss.is_junk_crew and not boss.is_junk_manager    # nothing stored on the account


def test_view_as_refused_for_everyone_else(make_user):
    assert _client().post('/junk/dev/view/crew').status_code == 404
    mgr = _login(make_user(is_junk_manager=True).id)
    assert mgr.post('/junk/dev/view/crew').status_code == 404
    assert mgr.get('/junk/manage').status_code == 200
    assert _login(make_user(is_super_admin=True).id).post('/junk/dev/view/admin').status_code == 404


def test_view_as_only_changes_the_viewer(make_user):
    """A super admin previewing as crew still counts as a manager to everyone else's checks."""
    from flask_login import login_user
    from junk.auth import VIEW_AS_KEY, is_junk_manager
    boss = make_user(is_super_admin=True)
    other = make_user(is_super_admin=True)
    with flask_app.test_request_context():
        from flask import session
        login_user(boss)
        session[VIEW_AS_KEY] = 'crew'
        assert is_junk_manager() is False
        assert is_junk_manager(other) is True


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



# ── assigning crew (step 3a) ───────────────────────────────

def _job(mgr, **fields):
    j = Job(created_by_id=mgr.id, **fields)
    db.session.add(j)
    db.session.commit()
    return j


def _crew(c, job, user, action='add'):
    return c.post(f'/junk/manage/job/{job.id}/crew', json={'user_id': user.id, 'action': action})


def _on(job):
    db.session.expire_all()
    return [a.user_id for a in JobAssignment.query.filter_by(job_id=job.id).order_by(JobAssignment.id)]


def test_add_and_remove_crew(make_user):
    mgr = make_user(is_junk_manager=True, full_name='Mia Manager')
    jo = make_user(is_junk_crew=True, full_name='Jordan Lee')
    c = _login(mgr.id)
    job = _job(mgr, customer_name='Smith')
    r = _crew(c, job, jo)
    assert r.status_code == 200 and r.get_json()['ok'] and 'Jordan' in r.get_json()['html']
    assert _on(job) == [jo.id]
    assert _crew(c, job, jo).status_code == 200 and _on(job) == [jo.id]   # adding twice is a no-op
    assert _crew(c, job, mgr).status_code == 200 and _on(job) == [jo.id, mgr.id]  # managers work jobs too
    assert _crew(c, job, jo, 'remove').status_code == 200 and _on(job) == [mgr.id]


def test_only_team_members_can_be_assigned(make_user):
    mgr = make_user(is_junk_manager=True)
    c = _login(mgr.id)
    job = _job(mgr)
    r = _crew(c, job, make_user())   # a plain account, not crew or manager
    assert r.status_code == 400 and r.get_json()['ok'] is False and _on(job) == []
    assert c.post(f'/junk/manage/job/{job.id}/crew', json={'user_id': 'x', 'action': 'add'}).status_code == 400
    assert c.post(f'/junk/manage/job/{job.id}/crew', json={'user_id': mgr.id, 'action': 'nope'}).status_code == 400


def test_crew_cannot_assign(make_user):
    mgr = make_user(is_junk_manager=True)
    crew = make_user(is_junk_crew=True)
    job = _job(mgr)
    assert _crew(_login(crew.id), job, crew).status_code == 403 and _on(job) == []


def test_crew_changes_are_history_and_merge(make_user):
    mgr = make_user(is_junk_manager=True, full_name='Mia Manager')
    a = make_user(is_junk_crew=True, full_name='Ann Able')
    b = make_user(is_junk_crew=True, full_name='Ben Baker')
    c = _login(mgr.id)
    job = _job(mgr)
    _crew(c, job, a)
    _crew(c, job, b)
    ev = JobEvent.query.filter_by(job_id=job.id, action='updated').one()
    assert ev.changes == {'crew': [[], ['Ann Able', 'Ben Baker']]}
    _crew(c, job, a, 'remove')
    _crew(c, job, b, 'remove')
    assert not JobEvent.query.filter_by(job_id=job.id, action='updated').count()  # back where it started


def test_deleting_a_job_deletes_its_assignments(make_user):
    mgr = make_user(is_junk_manager=True)
    crew = make_user(is_junk_crew=True)
    c = _login(mgr.id)
    job = _job(mgr)
    _crew(c, job, crew)
    c.post(f'/junk/manage/job/{job.id}/delete')
    assert not JobAssignment.query.filter_by(user_id=crew.id).count()


def test_cards_and_modal_show_crew(make_user):
    from datetime import date
    mgr = make_user(is_junk_manager=True, full_name='Mia Manager')
    jo = make_user(is_junk_crew=True, full_name='Jordan Lee')
    c = _login(mgr.id)
    job = _job(mgr, customer_name='Smith', scheduled_date=date(2099, 3, 4), queue_position=1)
    _crew(c, job, jo)
    page = c.get('/junk/manage?date=2099-03-04').get_data(as_text=True)
    assert '>JL<' in page and 'Crew: Jordan Lee' in page
    form = c.get(f'/junk/manage/job/form?id={job.id}').get_data(as_text=True)
    assert 'data-crew-remove="%d"' % jo.id in form and 'data-crew-add="%d"' % mgr.id in form   # + Me
    new = c.get('/junk/manage/job/form').get_data(as_text=True)
    assert 'data-crew' not in new   # crew is added once the job exists


def test_add_picker_lists_the_team_by_last_name(make_user):
    from datetime import date
    mgr = make_user(is_junk_manager=True, full_name='Mia Manager')
    zed = make_user(is_junk_crew=True, full_name='Zed Adams')
    amy = make_user(is_junk_manager=True, full_name='Amy Zimmer')
    jo = make_user(is_junk_crew=True, full_name='Jordan Lee')
    c = _login(mgr.id)
    job = _job(mgr, customer_name='Picker', scheduled_date=date(2099, 3, 5), queue_position=1)
    _crew(c, job, jo)
    form = c.get(f'/junk/manage/job/form?id={job.id}').get_data(as_text=True)
    assert '<select' not in form and 'data-pick-q' in form
    opt = lambda u: form.index(f'class="jr-teampick-opt" data-crew-add="{u.id}"')
    assert opt(zed) < opt(amy)                       # by last name, managers included
    assert f'jr-teampick-opt" data-crew-add="{jo.id}"' not in form   # already on the job
    assert f'jr-teampick-opt" data-crew-add="{mgr.id}"' not in form  # you have + Me


def test_move_crew_between_jobs(make_user):
    mgr = make_user(is_junk_manager=True, full_name='Mia Manager')
    jo = make_user(is_junk_crew=True, full_name='Jordan Lee')
    c = _login(mgr.id)
    a, b = _job(mgr, customer_name='A'), _job(mgr, customer_name='B')
    _crew(c, a, jo)
    r = c.post(f'/junk/manage/job/{b.id}/crew', json={'user_id': jo.id, 'action': 'move', 'from_job_id': a.id})
    assert r.status_code == 200 and _on(a) == [] and _on(b) == [jo.id]
    # Each job's history shows its own side of the move.
    assert JobEvent.query.filter_by(job_id=b.id, action='updated').one().changes == {'crew': [[], ['Jordan Lee']]}
    # Moving onto a job they're already on just takes them off the old one; same job is a no-op.
    _crew(c, a, jo)
    c.post(f'/junk/manage/job/{b.id}/crew', json={'user_id': jo.id, 'action': 'move', 'from_job_id': a.id})
    assert _on(a) == [] and _on(b) == [jo.id]
    c.post(f'/junk/manage/job/{b.id}/crew', json={'user_id': jo.id, 'action': 'move', 'from_job_id': b.id})
    assert _on(b) == [jo.id]
    # The job they came from is gone.
    r = c.post(f'/junk/manage/job/{b.id}/crew', json={'user_id': jo.id, 'action': 'move', 'from_job_id': 999999999})
    assert r.status_code == 409


def test_calendar_shows_crew_panel(make_user):
    mgr = make_user(is_junk_manager=True, full_name='Mia Manager')
    jo = make_user(is_junk_crew=True, full_name='Jordan Lee')
    page = _login(mgr.id).get('/junk/manage').get_data(as_text=True)
    assert 'data-crew-panel' in page and f'data-user-id="{jo.id}"' in page
    assert '/junk/manage/job/__ID__/crew' in page
    # You on top; everyone else, managers included, by last name. No stars.
    other = make_user(is_junk_manager=True, full_name='Zed Zimmer')
    abe = make_user(is_junk_crew=True, full_name='Abe Adams')
    page = _login(mgr.id).get('/junk/manage').get_data(as_text=True)
    pos = lambda u: page.index(f'class="jr-crewchip" data-user-id="{u.id}"')
    assert pos(mgr) < pos(abe) < pos(jo) < pos(other)
    assert 'jr-mgr-star' not in page
    assert page.count('jr-crewchip-me') == 1   # only you are marked


# ═══════════════════════════ step 4: My jobs ═══════════════════════════

def test_crew_home_lists_my_jobs_in_calendar_order(make_user, monkeypatch):
    from datetime import date, datetime
    from decimal import Decimal
    import junk.routes as jr
    monkeypatch.setattr(jr, 'today_eastern', lambda: date(2099, 5, 10))
    mgr = make_user(is_junk_manager=True, full_name='Mia Manager')
    me = make_user(is_junk_crew=True, full_name='Jordan Lee')
    sam = make_user(is_junk_crew=True, full_name='Sam Rivera')
    c = _login(mgr.id)
    late = _job(mgr, customer_name='Second Today', scheduled_date=date(2099, 5, 10), queue_position=2, quote_amount=Decimal('300'))
    first = _job(mgr, customer_name='First Today', scheduled_date=date(2099, 5, 10), queue_position=1, quote_amount=Decimal('250'),
                 customer_phone='(919) 555-0142', address='829 Shearer St, Davidson, NC 28036', notes='Couch + 2 chairs')
    soon = _job(mgr, customer_name='Next Week', scheduled_date=date(2099, 5, 16), queue_position=1)
    past = _job(mgr, customer_name='Left Open', scheduled_date=date(2099, 5, 8), queue_position=1, quote_amount=Decimal('100'))
    did = _job(mgr, customer_name='All Done', scheduled_date=date(2099, 5, 1), queue_position=1, quote_amount=Decimal('412.50'),
               completed_at=datetime(2099, 5, 1, 18))
    undated = _job(mgr, customer_name='No Date Yet', quote_amount=Decimal('90'))
    theirs = _job(mgr, customer_name='Not Mine', scheduled_date=date(2099, 5, 10), queue_position=3)
    for j in (late, first, soon, past, did, undated):
        _crew(c, j, me)
    _crew(c, first, sam)
    _crew(c, theirs, sam)
    page = _login(me.id).get('/junk/crew').get_data(as_text=True)
    # Calendar order within today; past-and-open on top; then coming up.
    assert page.index('Left Open') < page.index('First Today') < page.index('Second Today') < page.index('Next Week')
    assert 'Not Mine' not in page and 'No Date Yet' not in page
    # Your cut is 20% of the quote; the quote itself isn't shown.
    assert '$50' in page and '$250' not in page and 'TBD' in page     # Next Week has no quote
    assert 'tel:9195550142' in page and 'sms:9195550142' in page
    assert 'google.com/maps/dir/?api=1&amp;destination=829%20Shearer%20St' in page
    assert '>Address</span>' not in page     # the head's street, the map and Navigate cover it
    # On an iPhone, Navigate opens Apple Maps (Google Maps would send them to the App Store).
    iphone = _login(me.id).get('/junk/crew', headers={'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)'}).get_data(as_text=True)
    assert 'maps.apple.com/?dirflg=d&amp;daddr=829%20Shearer%20St' in iphone and 'google.com/maps/dir' not in iphone
    assert 'You, Sam Rivera' in page and 'Just you' in page
    # Totals count closed jobs only: 20% of $412.50.
    assert '$82.50' in page and '1</strong><span>job done' in page


def test_my_jobs_for_managers_and_viewing_someone_else(make_user, monkeypatch):
    from datetime import date, datetime
    from decimal import Decimal
    import junk.routes as jr
    monkeypatch.setattr(jr, 'today_eastern', lambda: date(2099, 6, 10))
    mgr = make_user(is_junk_manager=True, full_name='Mia Manager')
    jo = make_user(is_junk_crew=True, full_name='Jordan Lee')
    sam = make_user(is_junk_crew=True, full_name='Sam Rivera')
    c = _login(mgr.id)
    j = _job(mgr, customer_name='Jordans Job', scheduled_date=date(2099, 6, 12), queue_position=1, quote_amount=Decimal('500'))
    _crew(c, j, jo)
    for n in range(3):   # three finished; only the latest two show, then "View all"
        d = _job(mgr, customer_name=f'Done {n}', scheduled_date=date(2099, 6, n + 1), queue_position=1,
                 quote_amount=Decimal('100'), completed_at=datetime(2099, 6, n + 1, 18))
        _crew(c, d, jo)
    # Managers have My jobs too.
    mine = c.get('/junk/crew').get_data(as_text=True)
    assert 'My jobs' in mine and 'Jordans Job' not in mine
    # …and can look at anyone's.
    page = c.get(f'/junk/crew?person={jo.id}').get_data(as_text=True)
    assert 'Jordans Job' in page and 'Jordan Lee’s jobs' in page and '$100' in page
    assert 'Done 2' in page and 'Done 1' in page and 'Done 0' not in page
    assert f'/junk/crew/done?person={jo.id}' in page and 'View all 3 finished jobs' in page
    every = c.get(f'/junk/crew/done?person={jo.id}').get_data(as_text=True)
    assert 'Done 0' in every and 'Done 2' in every
    # Crew can't look at each other's.
    g.pop('_login_user', None)
    assert _login(sam.id).get(f'/junk/crew?person={jo.id}').status_code == 403
    g.pop('_login_user', None)
    assert _login(jo.id).get('/junk/crew').get_data(as_text=True).count('jr-cwho') == 0   # no picker for crew
