"""Tests for the junk removal manager calendar.

Spec: feature_junk_calendar.md
Run: python3 -m pytest test_junk_calendar.py -q

SAFE against campusswap_prod: requests nothing from either conftest (their `app`/`db`
fixtures drop_all()). Every user and job created here is deleted in teardown.
"""
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app import app as flask_app, db
from models import User
from junk.models import Job, JobEvent
from junk.jobs import week_start


# ═══════════════════════════ fixtures ═══════════════════════════

@pytest.fixture
def app_ctx():
    flask_app.config['TESTING'] = True
    flask_app.config['WTF_CSRF_ENABLED'] = False
    with flask_app.app_context():
        yield flask_app
        db.session.rollback()


@pytest.fixture
def tracked(app_ctx):
    created = {'users': []}
    yield created
    db.session.rollback()
    uids = created['users']
    if uids:
        job_ids = [j for (j,) in db.session.query(Job.id).filter(Job.created_by_id.in_(uids))]
        db.session.execute(db.delete(JobEvent).where(
            JobEvent.job_id.in_(job_ids) | JobEvent.user_id.in_(uids)))
        db.session.execute(db.delete(Job).where(Job.id.in_(job_ids)))
        db.session.execute(db.delete(User).where(User.id.in_(uids)))
    db.session.commit()


@pytest.fixture
def make_user(tracked):
    def _factory(**flags):
        u = User(email=f"jr-test-{uuid.uuid4().hex[:10]}@example.com", full_name='Test Person', **flags)
        db.session.add(u)
        db.session.commit()
        tracked['users'].append(u.id)
        return u
    return _factory


def _login(uid):
    c = flask_app.test_client()
    with c.session_transaction() as s:
        s['_user_id'] = str(uid)
        s['_fresh'] = True
    return c


@pytest.fixture
def manager(make_user):
    return make_user(is_junk_manager=True)


@pytest.fixture
def client(manager):
    return _login(manager.id)


# Far-future dates so tests never collide with real dev data on the same day.
D1 = date(2099, 3, 4)   # a Wednesday
D2 = date(2099, 3, 5)


def _create(client, **fields):
    fields.setdefault('return_to', '/junk/manage')
    r = client.post('/junk/manage/job', data=fields)
    assert r.status_code == 302
    return Job.query.filter_by(created_by_id=_creator(client)).order_by(Job.id.desc()).first()


def _creator(client):
    with client.session_transaction() as s:
        return int(s['_user_id'])


def _line(d):
    """Job ids in a day's line (done included), in queue order."""
    return [j.id for j in Job.query.filter(Job.scheduled_date == d)
            .order_by(Job.queue_position)]


def _positions(d):
    return [j.queue_position for j in Job.query.filter(Job.scheduled_date == d)
            .order_by(Job.queue_position)]


def _move(client, job, d, ordered):
    return client.post('/junk/manage/board/move', json={
        'job_id': job.id, 'date': d.isoformat() if d else None,
        'ordered_ids': [j.id for j in ordered]})


def _fresh(job):
    db.session.expire_all()
    return db.session.get(Job, job.id)


# ═══════════════════════════ access ═══════════════════════════

def test_anonymous_redirected_to_junk_login(app_ctx):
    r = flask_app.test_client().get('/junk/manage')
    assert r.status_code == 302 and '/junk/login' in r.headers['Location']


@pytest.mark.parametrize('flags', [
    {}, {'is_admin': True}, {'is_campus_director': True},
    {'is_worker': True, 'worker_status': 'approved'},
])
def test_non_managers_denied(make_user, flags):
    c = _login(make_user(**flags).id)
    assert c.get('/junk/manage').status_code == 403
    assert c.post('/junk/manage/job', data={'customer_name': 'x'}).status_code == 403
    assert c.post('/junk/manage/board/move', json={}).status_code == 403


def test_manager_and_super_admin_allowed(make_user):
    assert _login(make_user(is_junk_manager=True).id).get('/junk/manage').status_code == 200
    assert _login(make_user(is_admin=True, is_super_admin=True).id).get('/junk/manage').status_code == 200


def test_junk_manager_lands_on_portal(client):
    r = client.get('/dashboard')
    assert r.status_code == 302 and r.headers['Location'].endswith('/junk/manage')


# ═══════════════════════════ create ═══════════════════════════

def test_all_empty_job_is_unscheduled_and_needs_quote(client):
    job = _create(client)
    assert job.state == 'unscheduled' and job.needs_quote and _unscheduled_ids()[-1] == job.id
    assert job.display_name == 'Untitled job'
    body = client.get('/junk/manage').get_data(as_text=True)
    assert f'data-job-id="{job.id}"' in body and 'Untitled job' in body and 'Needs quote' in body


def test_create_with_date_goes_to_end_of_line(client):
    a = _create(client, customer_name='A', scheduled_date=D1.isoformat())
    b = _create(client, customer_name='B', scheduled_date=D1.isoformat(), quote_amount='$1,250')
    assert _line(D1) == [a.id, b.id] and _positions(D1) == [1, 2]
    assert b.quote_amount == Decimal('1250.00') and b.state == 'scheduled'


def test_bad_quote_is_rejected_without_saving(client):
    before = Job.query.count()
    r = client.post('/junk/manage/job', data={'customer_name': 'X', 'quote_amount': 'lots'})
    assert r.status_code == 302 and Job.query.count() == before


def test_week_view_shows_job_on_its_day(client):
    job = _create(client, customer_name='Weekday Person', scheduled_date=D1.isoformat())
    body = client.get(f'/junk/manage?date={D1.isoformat()}').get_data(as_text=True)
    assert f'data-date="{D1.isoformat()}"' in body and 'Weekday Person' in body
    # Sunday job lands in the Mon–Sun week that contains it
    sunday = week_start(D1) + timedelta(days=6)
    _create(client, customer_name='Sunday Person', scheduled_date=sunday.isoformat())
    assert 'Sunday Person' in client.get(f'/junk/manage?date={week_start(D1).isoformat()}').get_data(as_text=True)
    assert 'Sunday Person' not in client.get(
        f'/junk/manage?date={(sunday + timedelta(days=1)).isoformat()}').get_data(as_text=True)


def test_month_view_renders(client):
    _create(client, customer_name='Month Person', scheduled_date=D1.isoformat())
    r = client.get(f'/junk/manage?view=month&date={D1.isoformat()}')
    body = r.get_data(as_text=True)
    assert r.status_code == 200 and 'March 2099' in body and 'Month Person' in body


# ═══════════════════════════ edit ═══════════════════════════

def test_edit_date_moves_to_end_of_new_day_and_renumbers_old(client):
    a = _create(client, customer_name='A', scheduled_date=D1.isoformat())
    b = _create(client, customer_name='B', scheduled_date=D1.isoformat())
    c = _create(client, customer_name='C', scheduled_date=D2.isoformat())
    client.post(f'/junk/manage/job/{a.id}', data={'customer_name': 'A', 'scheduled_date': D2.isoformat()})
    assert _line(D1) == [b.id] and _positions(D1) == [1]
    assert _line(D2) == [c.id, a.id] and _positions(D2) == [1, 2]


def test_clearing_date_unschedules(client):
    a = _create(client, customer_name='A', scheduled_date=D1.isoformat())
    client.post(f'/junk/manage/job/{a.id}', data={'customer_name': 'A', 'scheduled_date': ''})
    a = _fresh(a)
    assert a.state == 'unscheduled' and _unscheduled_ids()[-1] == a.id


def test_edit_records_history_and_no_op_save_records_nothing(client):
    a = _create(client, customer_name='A', quote_amount='250')
    client.post(f'/junk/manage/job/{a.id}', data={'customer_name': 'A', 'quote_amount': '250.00'})
    assert [e.action for e in JobEvent.query.filter_by(job_id=a.id)] == ['created']
    client.post(f'/junk/manage/job/{a.id}', data={'customer_name': 'Alice', 'quote_amount': '300'})
    ev = JobEvent.query.filter_by(job_id=a.id, action='updated').one()
    assert ev.changes == {'customer_name': ['A', 'Alice'], 'quote_amount': ['250.00', '300.00']}
    form = client.get(f'/junk/manage/job/form?id={a.id}').get_data(as_text=True)
    assert 'History' in form and '$250 &rarr; $300' in form


# ═══════════════════════════ drag and drop ═══════════════════════════

def test_reorder_within_a_day(client):
    a, b, c = (_create(client, customer_name=n, scheduled_date=D1.isoformat()) for n in 'ABC')
    assert _move(client, c, D1, [c, a, b]).status_code == 200
    assert _line(D1) == [c.id, a.id, b.id] and _positions(D1) == [1, 2, 3]
    assert not JobEvent.query.filter_by(job_id=c.id, action='updated').count()  # reorders aren't logged


def test_cross_day_move_lands_where_dropped(client):
    a, b = (_create(client, customer_name=n, scheduled_date=D1.isoformat()) for n in 'AB')
    x, y = (_create(client, customer_name=n, scheduled_date=D2.isoformat()) for n in 'XY')
    assert _move(client, a, D2, [x, a, y]).status_code == 200
    assert _line(D2) == [x.id, a.id, y.id] and _positions(D2) == [1, 2, 3]
    assert _line(D1) == [b.id] and _positions(D1) == [1]
    ev = JobEvent.query.filter_by(job_id=a.id, action='updated').one()
    assert ev.changes == {'scheduled_date': [D1.isoformat(), D2.isoformat()]}


def test_unscheduled_to_day_and_back(client):
    u = _create(client, customer_name='U')
    a = _create(client, customer_name='A', scheduled_date=D1.isoformat())
    assert _move(client, u, D1, [u, a]).status_code == 200
    assert _line(D1) == [u.id, a.id]
    assert _move(client, u, None, []).status_code == 200
    u = _fresh(u)
    assert u.state == 'unscheduled' and _unscheduled_ids()[-1] == u.id and _positions(D1) == [1]


def test_stale_move_is_rejected_and_changes_nothing(client):
    a, b = (_create(client, customer_name=n, scheduled_date=D1.isoformat()) for n in 'AB')
    late = _create(client, customer_name='Late', scheduled_date=D1.isoformat())  # client never saw this
    r = _move(client, b, D1, [b, a])
    assert r.status_code == 409 and _line(D1) == [a.id, b.id, late.id]
    assert _move(client, a, D1, [a, a, b, late]).status_code == 409  # duplicates


def test_done_job_can_still_be_dragged_but_not_unscheduled(client):
    a, b = (_create(client, customer_name=n, scheduled_date=D1.isoformat()) for n in 'AB')
    client.post(f'/junk/manage/job/{a.id}/done', data={})
    assert _move(client, a, D1, [b, a]).status_code == 200
    assert _line(D1) == [b.id, a.id]
    assert _move(client, a, None, []).status_code == 409   # a done job keeps a date


# ═══════════════════════════ done ═══════════════════════════

def test_done_and_undo_keep_their_place_in_line(client):
    a, b, c = (_create(client, customer_name=n, scheduled_date=D1.isoformat()) for n in 'ABC')
    client.post(f'/junk/manage/job/{b.id}/done', data={})
    assert _fresh(b).state == 'done'
    assert _line(D1) == [a.id, b.id, c.id] and _positions(D1) == [1, 2, 3]
    body = client.get(f'/junk/manage?date={D1.isoformat()}').get_data(as_text=True)
    assert f'jr-card jr-card--done" data-job-id="{b.id}"' in body
    assert body.index(f'data-job-id="{a.id}"') < body.index(f'data-job-id="{b.id}"') < body.index(f'data-job-id="{c.id}"')
    client.post(f'/junk/manage/job/{b.id}/done', data={'undo': '1'})
    assert _line(D1) == [a.id, b.id, c.id]
    assert [e.action for e in JobEvent.query.filter_by(job_id=b.id).order_by(JobEvent.id)] == \
        ['created', 'done', 'undone']


def test_cannot_mark_unscheduled_job_done(client):
    u = _create(client, customer_name='U')
    client.post(f'/junk/manage/job/{u.id}/done', data={})
    assert _fresh(u).completed_at is None


def test_month_view_has_unscheduled_panel_and_draggable_days(client):
    _create(client, customer_name='Floating')
    a = _create(client, customer_name='A', scheduled_date=D1.isoformat())
    body = client.get(f'/junk/manage?view=month&date={D1.isoformat()}').get_data(as_text=True)
    assert 'jr-list--unscheduled' in body and 'Floating' in body
    assert f'class="jr-list jr-mlist" data-date="{D1.isoformat()}"' in body
    assert f'data-job-id="{a.id}"' in body


def test_today_button_sits_between_arrows(client):
    body = client.get(f'/junk/manage?date={D1.isoformat()}').get_data(as_text=True)
    prev_i = body.index('aria-label="Previous week"')
    today_i = body.index('>Today</a>')
    next_i = body.index('aria-label="Next week"')
    assert prev_i < today_i < next_i


# ═══════════════════════════ delete ═══════════════════════════

def test_delete_is_permanent_and_closes_the_gap(client):
    a, b, c = (_create(client, customer_name=n, scheduled_date=D1.isoformat()) for n in 'ABC')
    client.post(f'/junk/manage/job/{a.id}/done', data={})          # give it some history
    r = client.post(f'/junk/manage/job/{b.id}/delete', data={})
    assert r.status_code == 302
    assert db.session.get(Job, b.id) is None
    assert JobEvent.query.filter_by(job_id=b.id).count() == 0
    assert _line(D1) == [a.id, c.id] and _positions(D1) == [1, 2]


def test_delete_unscheduled_job_closes_queue_gap(client):
    u1, u2, u3 = (_create(client, customer_name=n) for n in ['U1', 'U2', 'U3'])
    client.post(f'/junk/manage/job/{u2.id}/delete', data={})
    q = [j.id for j in Job.query.filter(Job.scheduled_date.is_(None)).order_by(Job.queue_position)]
    assert q.index(u1.id) < q.index(u3.id)
    assert [j.queue_position for j in Job.query.filter(Job.scheduled_date.is_(None))
            .order_by(Job.queue_position)] == list(range(1, len(q) + 1))


def test_removed_pages_are_gone(client):
    a = _create(client, customer_name='A')
    assert client.get('/junk/manage/removed').status_code == 404
    assert client.post(f'/junk/manage/job/{a.id}/restore', data={}).status_code == 404


# ═══════════════════════════ unscheduled queue ═══════════════════════════

def _unscheduled_ids():
    return [j.id for j in Job.query.filter(Job.scheduled_date.is_(None)).order_by(Job.queue_position)]


def test_new_unscheduled_job_joins_bottom(client):
    a = _create(client, customer_name='First')
    b = _create(client, customer_name='Second')
    q = _unscheduled_ids()
    assert q[-2:] == [a.id, b.id]


def test_job_brought_back_joins_bottom_of_unscheduled(client):
    old = _create(client, customer_name='Old scheduled', scheduled_date=D1.isoformat())  # created first
    newer = _create(client, customer_name='Newer unscheduled')
    assert _move(client, old, None, []).status_code == 200
    q = _unscheduled_ids()
    assert q[-1] == old.id and q.index(newer.id) < q.index(old.id)
    # clearing the date in the form does the same
    other = _create(client, customer_name='Other', scheduled_date=D1.isoformat())
    client.post(f'/junk/manage/job/{other.id}', data={'customer_name': 'Other', 'scheduled_date': ''})
    assert _unscheduled_ids()[-1] == other.id


# ═══════════════════════════ safety ═══════════════════════════

def test_return_to_cannot_redirect_off_portal(client):
    r = client.post('/junk/manage/job', data={'customer_name': 'A', 'return_to': 'https://evil.example'})
    assert r.headers['Location'].endswith('/junk/manage')


# ═══════════════════════════ separation from the legacy site ═══════════════════════════

def test_junk_login_page_is_standalone(app_ctx):
    body = flask_app.test_client().get('/junk/login').get_data(as_text=True)
    assert 'Sign in' in body and 'Shop' not in body and 'Become a Seller' not in body


def test_junk_login_with_password(make_user):
    from werkzeug.security import generate_password_hash
    u = make_user(is_junk_manager=True)
    u.password_hash = generate_password_hash('pw-123456')
    db.session.commit()
    bad = flask_app.test_client().post('/junk/login', data={'email': u.email, 'password': 'nope'})
    assert bad.status_code == 200 and "match" in bad.get_data(as_text=True)
    r = flask_app.test_client().post('/junk/login', data={'email': u.email.upper(), 'password': 'pw-123456'})
    assert r.status_code == 302 and r.headers['Location'].endswith('/junk/manage')


def test_non_manager_cannot_sign_in_to_junk(make_user):
    from werkzeug.security import generate_password_hash
    u = make_user()
    u.password_hash = generate_password_hash('pw-123456')
    db.session.commit()
    c = flask_app.test_client()
    body = c.post('/junk/login', data={'email': u.email, 'password': 'pw-123456'}).get_data(as_text=True)
    assert "have access yet" in body
    assert c.get('/junk/manage').status_code == 302


@pytest.mark.parametrize('path', ['/', '/shop', '/dashboard', '/admin/ops', '/crew', '/become-a-seller'])
def test_junk_only_user_never_sees_legacy_site(client, path):
    r = client.get(path)
    assert r.status_code == 302 and r.headers['Location'].endswith('/junk/manage')


def test_legacy_logout_goes_to_junk_login(client):
    r = client.get('/logout')
    assert r.headers['Location'].endswith('/junk/logout')


def test_super_admin_not_confined(make_user):
    c = _login(make_user(is_junk_manager=True, is_admin=True, is_super_admin=True).id)
    r = c.get('/shop')
    assert not (r.status_code == 302 and r.headers.get('Location', '').endswith('/junk/manage'))


def test_today_button_only_off_current_week(client):
    assert '>Today</a>' not in client.get('/junk/manage').get_data(as_text=True)
    assert '>Today</a>' in client.get(f'/junk/manage?date={D1.isoformat()}').get_data(as_text=True)


def test_card_shows_quote(client):
    _create(client, customer_name='Quoted', scheduled_date=D1.isoformat(), quote_amount='1250')
    body = client.get(f'/junk/manage?date={D1.isoformat()}').get_data(as_text=True)
    assert '$1,250' in body
