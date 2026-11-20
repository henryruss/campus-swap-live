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
from flask import g

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
    assert f'data-job-id="{job.id}"' in body and 'Untitled job' in body
    assert 'Needs quote' not in body   # the quote lives in the modal, not on cards


def test_card_shows_street_line_only(client):
    job = _create(client, customer_name='Street Test', address='829 Shearer St, Davidson, NC 28036')
    body = client.get('/junk/manage').get_data(as_text=True)
    assert 'title="829 Shearer St, Davidson, NC 28036">829 Shearer St</div>' in body


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
    # History is still recorded, but no longer shown in the modal.
    form = client.get(f'/junk/manage/job/form?id={a.id}').get_data(as_text=True)
    assert 'History' not in form


# ═══════════════════════════ autosave (modal) ═══════════════════════════

AUTOSAVE = {'X-Autosave': '1', 'Accept': 'application/json'}


def test_autosave_answers_json(client):
    a = _create(client, customer_name='A', quote_amount='250')
    r = client.post(f'/junk/manage/job/{a.id}', data={'customer_name': 'Alicia'}, headers=AUTOSAVE)
    assert r.status_code == 200 and r.get_json() == {'ok': True}
    db.session.refresh(a)
    assert a.customer_name == 'Alicia'


def test_autosave_bad_value_is_a_json_error_and_changes_nothing(client):
    a = _create(client, customer_name='A', quote_amount='250')
    r = client.post(f'/junk/manage/job/{a.id}', data={'customer_name': 'B', 'quote_amount': 'abc'},
                    headers=AUTOSAVE)
    assert r.status_code == 400 and r.get_json()['ok'] is False and r.get_json()['error']
    db.session.refresh(a)
    assert a.customer_name == 'A' and a.quote_amount == Decimal('250')


def test_a_burst_of_autosaves_is_one_history_entry(client):
    a = _create(client, customer_name='A', quote_amount='250')
    for name in ('Al', 'Ali', 'Alice'):
        client.post(f'/junk/manage/job/{a.id}', data={'customer_name': name, 'quote_amount': '250'},
                    headers=AUTOSAVE)
    client.post(f'/junk/manage/job/{a.id}', data={'customer_name': 'Alice', 'quote_amount': '300'},
                headers=AUTOSAVE)
    ev = JobEvent.query.filter_by(job_id=a.id, action='updated').one()
    assert ev.changes == {'customer_name': ['A', 'Alice'], 'quote_amount': ['250.00', '300.00']}


def test_edit_then_put_back_leaves_no_history(client):
    a = _create(client, customer_name='A')
    client.post(f'/junk/manage/job/{a.id}', data={'customer_name': 'B'}, headers=AUTOSAVE)
    client.post(f'/junk/manage/job/{a.id}', data={'customer_name': 'A'}, headers=AUTOSAVE)
    assert not JobEvent.query.filter_by(job_id=a.id, action='updated').count()


def test_edits_by_someone_else_or_later_are_separate_entries(client, make_user):
    a = _create(client, customer_name='A')
    client.post(f'/junk/manage/job/{a.id}', data={'customer_name': 'B'}, headers=AUTOSAVE)
    other = _login(make_user(is_junk_manager=True).id)
    g.pop('_login_user', None)  # the fixture's shared app context caches the signed-in user
    other.post(f'/junk/manage/job/{a.id}', data={'customer_name': 'C'}, headers=AUTOSAVE)
    assert JobEvent.query.filter_by(job_id=a.id, action='updated').count() == 2
    # An hour later, the same person's edit starts a new entry.
    last = JobEvent.query.filter_by(job_id=a.id, action='updated').order_by(JobEvent.id.desc()).first()
    last.created_at -= timedelta(hours=1)
    db.session.commit()
    other.post(f'/junk/manage/job/{a.id}', data={'customer_name': 'D'}, headers=AUTOSAVE)
    assert JobEvent.query.filter_by(job_id=a.id, action='updated').count() == 3


def test_modal_footer(client):
    a = _create(client, customer_name='A', scheduled_date=D1.isoformat())
    form = client.get(f'/junk/manage/job/form?id={a.id}').get_data(as_text=True)
    assert 'data-autosave' in form and 'Mark done' in form and 'data-delete' in form
    assert '>Save<' not in form and '>Cancel<' not in form
    new = client.get('/junk/manage/job/form').get_data(as_text=True)
    assert 'data-autosave' not in new and 'Add job' in new and 'data-delete' not in new


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


def test_quote_is_in_modal_not_on_card(client):
    job = _create(client, customer_name='Quoted', scheduled_date=D1.isoformat(), quote_amount='1250')
    body = client.get(f'/junk/manage?date={D1.isoformat()}').get_data(as_text=True)
    assert '$1,250' not in body
    form = client.get(f'/junk/manage/job/form?id={job.id}').get_data(as_text=True)
    assert 'value="1250' in form


# ═══════════════════════════ address location (Places pick) ═══════════════════════════

def test_picked_address_saves_location(client):
    job = _create(client, address='123 Main St, Pineville, NC', address_lat='35.08', address_lng='-80.88')
    assert (job.address_lat, job.address_lng) == (35.08, -80.88)
    assert 'address_lat' not in job.events.first().changes  # location isn't a history field


def test_typed_address_has_no_location(client):
    job = _create(client, address='Behind the gym', address_lat='', address_lng='')
    assert job.address_lat is None and job.address_lng is None


def test_location_dropped_without_address_or_out_of_range(client):
    assert _create(client, address='', address_lat='35', address_lng='-80').address_lat is None
    assert _create(client, address='x', address_lat='135', address_lng='-80').address_lat is None


def test_editing_address_by_hand_clears_location(client):
    job = _create(client, address='123 Main St', address_lat='35.08', address_lng='-80.88')
    client.post(f'/junk/manage/job/{job.id}', data={'address': '125 Main St', 'return_to': '/junk/manage'})
    db.session.refresh(job)
    assert job.address == '125 Main St' and job.address_lat is None


def test_edit_form_prefills_location(client):
    job = _create(client, address='123 Main St', address_lat='35.08', address_lng='-80.88')
    body = client.get(f'/junk/manage/job/form?id={job.id}').get_data(as_text=True)
    assert 'value="35.08"' in body and 'data-addr-map' in body


# ═══════════════════════════ sign in: Google and password both work ═══════════════════════════

def test_google_only_account_gets_pointed_to_both_ways_in(make_user):
    u = make_user(is_junk_manager=True, oauth_provider='google', oauth_id='g-1')
    body = flask_app.test_client().post('/junk/login', data={'email': u.email, 'password': 'whatever'}).get_data(as_text=True)
    assert "doesn&#39;t have a password yet" in body and 'Continue with Google' in body
    assert 'Email me a link to set one' in body  # the fix is one click from the error


def test_login_remembers_last_method(make_user, monkeypatch):
    from werkzeug.security import generate_password_hash
    monkeypatch.setenv('GOOGLE_CLIENT_ID', 'x')
    monkeypatch.setenv('GOOGLE_CLIENT_SECRET', 'y')
    u = make_user(is_junk_manager=True)
    u.password_hash = generate_password_hash('pw-123456')
    db.session.commit()
    c = flask_app.test_client()
    assert 'Last used' not in c.get('/junk/login').get_data(as_text=True)
    r = c.post('/junk/login', data={'email': u.email, 'password': 'pw-123456'})
    assert 'jr_last_signin=password' in r.headers.get('Set-Cookie', '')
    c.get('/junk/logout')
    c.set_cookie('jr_last_signin', 'google')
    body = c.get('/junk/login').get_data(as_text=True)
    assert 'is-last' in body and 'Last used' in body


def test_google_login_sets_last_used_cookie(make_user):
    from junk.routes import finish_google_login
    u = make_user(is_junk_manager=True)
    with flask_app.test_request_context():
        r = finish_google_login({'email': u.email, 'sub': 'g', 'email_verified': True}, '/junk/manage')
    assert 'jr_last_signin=google' in r.headers.get('Set-Cookie', '')


def test_assets_are_cache_busted(client):
    body = client.get('/junk/manage').get_data(as_text=True)
    assert 'manage.css?v=' in body and 'manage.js?v=' in body


def test_google_button_starts_shared_oauth_with_junk_flag(app_ctx, monkeypatch):
    monkeypatch.setenv('GOOGLE_CLIENT_ID', 'x')
    monkeypatch.setenv('GOOGLE_CLIENT_SECRET', 'y')
    c = flask_app.test_client()
    r = c.get('/junk/login/google?next=/junk/manage?view=month')
    assert r.headers['Location'].endswith('/auth/google')
    with c.session_transaction() as s:
        assert s['junk_oauth_next'] == '/junk/manage?view=month'


def test_finish_google_login_signs_in_manager_and_links_google(make_user):
    from junk.routes import finish_google_login
    u = make_user(is_junk_manager=True)
    with flask_app.test_request_context():
        r = finish_google_login({'email': u.email.upper(), 'sub': 'g-42', 'email_verified': True}, '/junk/manage')
        from flask_login import current_user
        assert r.headers['Location'] == '/junk/manage' and current_user.id == u.id
    db.session.refresh(u)
    assert (u.oauth_provider, u.oauth_id) == ('google', 'g-42')


def test_finish_google_login_never_creates_accounts(app_ctx, make_user):
    from junk.routes import finish_google_login
    outsider = make_user()
    for email in (f"nobody-{uuid.uuid4().hex[:8]}@example.com", outsider.email):
        with flask_app.test_request_context():
            r = finish_google_login({'email': email, 'sub': 'g-1', 'email_verified': True}, '/junk/manage')
            assert r.headers['Location'].endswith('/junk/login')
    assert User.query.filter(User.email.like('nobody-%@example.com')).count() == 0


def test_finish_google_login_rejects_unverified_email(make_user):
    from junk.routes import finish_google_login
    u = make_user(is_junk_manager=True)
    with flask_app.test_request_context():
        r = finish_google_login({'email': u.email, 'sub': 'g', 'email_verified': False}, '/junk/manage')
        assert r.headers['Location'].endswith('/junk/login')


def test_password_link_request_never_reveals_accounts(make_user, monkeypatch):
    sent = []
    monkeypatch.setitem(flask_app.extensions, 'junk_send_email', lambda to, subj, html: sent.append((to, html)) or True)
    u = make_user(is_junk_manager=True, oauth_provider='google', oauth_id='g')
    outsider = make_user()
    bodies = [flask_app.test_client().post('/junk/login/password', data={'email': e}).get_data(as_text=True)
              for e in (u.email, outsider.email, 'nobody@example.com')]
    assert all('a link is on its way' in b for b in bodies)
    assert [to for to, _ in sent] == [u.email]
    assert '/junk/login/password/' in sent[0][1]


def test_password_link_sets_password_once(make_user):
    from junk.routes import make_password_link
    u = make_user(is_junk_manager=True, oauth_provider='google', oauth_id='g')
    with flask_app.test_request_context():
        path = '/' + make_password_link(u).split('/', 3)[3]
    c = flask_app.test_client()
    assert 'For ' + u.email in c.get(path).get_data(as_text=True)
    assert 'match' in c.post(path, data={'password': 'longenough1', 'confirm': 'different1'}).get_data(as_text=True)
    assert 'at least 8' in c.post(path, data={'password': 'short', 'confirm': 'short'}).get_data(as_text=True)
    r = c.post(path, data={'password': 'longenough1', 'confirm': 'longenough1'})
    assert r.headers['Location'].endswith('/junk/manage')
    # Both routes now work, and the link is spent.
    r2 = flask_app.test_client().post('/junk/login', data={'email': u.email, 'password': 'longenough1'})
    assert r2.headers['Location'].endswith('/junk/manage')
    assert flask_app.test_client().get(path).headers['Location'].endswith('/junk/login/password')


def test_password_link_rejects_tampering(app_ctx):
    assert flask_app.test_client().get('/junk/login/password/not-a-token').status_code == 302


# ═══════════════════════════ Google popup (code flow) ═══════════════════════════

@pytest.fixture
def google_env(monkeypatch):
    monkeypatch.setenv('GOOGLE_CLIENT_ID', 'cid-123')
    monkeypatch.setenv('GOOGLE_CLIENT_SECRET', 'secret')


def test_login_page_wires_google_popup(app_ctx, google_env):
    body = flask_app.test_client().get('/junk/login').get_data(as_text=True)
    assert 'data-google-popup' in body and 'data-client-id="cid-123"' in body
    assert 'accounts.google.com/gsi/client' in body and 'login.js?v=' in body


def test_google_code_signs_in_manager(make_user, google_env, monkeypatch):
    import junk.routes as jr
    u = make_user(is_junk_manager=True)
    seen = []
    monkeypatch.setattr(jr, '_google_userinfo_from_code',
                        lambda code: seen.append(code) or {'email': u.email, 'sub': 'g-9', 'email_verified': True})
    c = flask_app.test_client()
    r = c.post('/junk/login/google/code', json={'code': 'abc', 'next': '/junk/manage?view=month'})
    assert r.status_code == 200 and r.get_json() == {'ok': True, 'redirect': '/junk/manage?view=month'}
    assert seen == ['abc'] and 'jr_last_signin=google' in r.headers.get('Set-Cookie', '')
    assert c.get('/junk/manage').status_code == 200


def test_google_code_rejects_non_manager_and_bad_input(make_user, google_env, monkeypatch):
    import junk.routes as jr
    outsider = make_user()
    monkeypatch.setattr(jr, '_google_userinfo_from_code',
                        lambda code: {'email': outsider.email, 'sub': 'g', 'email_verified': True})
    c = flask_app.test_client()
    r = c.post('/junk/login/google/code', json={'code': 'abc', 'next': 'https://evil.example'})
    assert r.status_code == 403 and 'have access yet' in r.get_json()['error']
    assert c.post('/junk/login/google/code', json={}).status_code == 400
    assert c.get('/junk/manage').status_code == 302


def test_google_code_exchange_failure_is_graceful(app_ctx, google_env, monkeypatch):
    import junk.routes as jr
    def boom(code):
        raise RuntimeError('google down')
    monkeypatch.setattr(jr, '_google_userinfo_from_code', boom)
    r = flask_app.test_client().post('/junk/login/google/code', json={'code': 'abc'})
    assert r.status_code == 502 and 'password' in r.get_json()['error']


# ═══════════════════════════ site locked to junk ═══════════════════════════

@pytest.fixture
def locked(app_ctx):
    flask_app.config['SITE_LOCKED_TO_JUNK'] = True
    yield
    flask_app.config.pop('SITE_LOCKED_TO_JUNK', None)


@pytest.mark.parametrize('path', ['/', '/shop', '/login', '/register', '/dashboard', '/admin',
                                  '/become-a-seller', '/item/1', '/sitemap.xml', '/crew'])
def test_locked_site_sends_visitors_to_junk_login(locked, path):
    r = flask_app.test_client().get(path)
    assert r.status_code == 302 and r.headers['Location'].endswith('/junk/login')


@pytest.mark.parametrize('path', ['/junk/login', '/health', '/static/style.css', '/favicon.ico'])
def test_locked_site_keeps_machine_and_junk_paths_open(locked, path):
    r = flask_app.test_client().get(path)
    assert not (r.status_code == 302 and r.headers.get('Location', '').endswith('/junk/login'))


def test_locked_site_keeps_webhooks_and_crons_reachable(locked):
    c = flask_app.test_client()
    for path in ('/webhook', '/sms/webhook', '/admin/cron/send-scheduled-mass-emails', '/admin/digest/trigger'):
        r = c.post(path)
        assert not r.headers.get('Location', '').endswith('/junk/login'), path


def test_locked_robots_disallows_everything(locked):
    assert 'Disallow: /\n' in flask_app.test_client().get('/robots.txt').get_data(as_text=True)


def test_locked_google_auth_only_from_junk_login(locked):
    c = flask_app.test_client()
    assert c.get('/auth/google').headers['Location'].endswith('/junk/login')
    with c.session_transaction() as s:
        s['junk_oauth_next'] = '/junk/manage'
    assert not c.get('/auth/google').headers.get('Location', '').endswith('/junk/login')


def test_locked_site_lets_admins_through(locked, make_user):
    c = _login(make_user(is_admin=True, is_super_admin=True).id)
    r = c.get('/shop')
    assert not (r.status_code == 302 and r.headers.get('Location', '').endswith('/junk/login'))


def test_locked_site_sends_signed_in_manager_to_calendar(locked, client):
    assert client.get('/shop').headers['Location'].endswith('/junk/manage')


def test_locked_site_sends_plain_seller_to_junk_login(locked, make_user):
    r = _login(make_user().id).get('/dashboard')
    assert r.headers['Location'].endswith('/junk/login')


def test_lock_on_by_default_and_env_can_reopen(app_ctx, monkeypatch):
    from junk.routes import site_locked
    flask_app.config['TESTING'] = False
    try:
        with flask_app.test_request_context():
            monkeypatch.delenv('SITE_LOCKED_TO_JUNK', raising=False)
            assert site_locked()
            monkeypatch.setenv('SITE_LOCKED_TO_JUNK', '0')
            assert not site_locked()
    finally:
        flask_app.config['TESTING'] = True
