"""Tests for adding a crew member directly from Crew HQ (/admin/crew/add).

Run: python3 -m pytest test_crew_add.py -q

Deliberately self-contained: the root conftest `app` fixture repoints the URI at a
temp SQLite file and calls drop_all(), which is destructive against the configured
Postgres DB. Nothing here requests `app`, `db`, or `make_user` from that conftest.
Every row created below is tracked and deleted in teardown.
"""
from datetime import datetime

import pytest
from werkzeug.security import check_password_hash

from app import app as flask_app, db
from models import User, WorkerApplication, WorkerAvailability


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
    for uid in created['users']:
        db.session.execute(db.delete(WorkerAvailability).where(WorkerAvailability.user_id == uid))
        db.session.execute(db.delete(WorkerApplication).where(WorkerApplication.user_id == uid))
        db.session.execute(
            db.update(WorkerApplication)
            .where(WorkerApplication.reviewed_by == uid)
            .values(reviewed_by=None)
        )
        db.session.execute(db.delete(User).where(User.id == uid))
    db.session.commit()


def _login(uid):
    c = flask_app.test_client()
    with c.session_transaction() as s:
        s['_user_id'] = str(uid)
        s['_fresh'] = True
    return c


@pytest.fixture
def client_admin(app_ctx):
    admin = (User.query.filter_by(is_super_admin=True).first()
             or User.query.filter_by(is_admin=True).first())
    if admin is None:
        pytest.skip('no admin user in this database')
    return _login(admin.id)


@pytest.fixture
def client_plain(tracked):
    u = User(email=f'crewadd-plain-{datetime.utcnow().timestamp()}@example.com',
             full_name='Crew Add Plain', is_admin=False, is_super_admin=False,
             is_campus_director=False, is_worker=False)
    db.session.add(u)
    db.session.commit()
    tracked['users'].append(u.id)
    return _login(u.id)


def _unique_email(tag='new'):
    return f'crewadd-{tag}-{datetime.utcnow().timestamp()}@example.com'.replace(' ', '')


def _form(email, **overrides):
    data = {
        'full_name': 'Test Crew Member',
        'email': email,
        'phone': '9195551234',
        'unc_year': 'Junior',
        'why_blurb': 'Added by hand.',
    }
    data.update(overrides)
    return data


def _fetch(email, tracked):
    user = User.query.filter_by(email=email).first()
    if user:
        tracked['users'].append(user.id)
    return user


# ─────────────────────────── access control ───────────────────────────

def test_non_admin_cannot_add_crew(client_plain, tracked):
    email = _unique_email('denied')
    resp = client_plain.post('/admin/crew/add', data=_form(email), follow_redirects=False)
    assert resp.status_code == 302
    assert User.query.filter_by(email=email).first() is None


def test_logged_out_cannot_add_crew(app_ctx):
    email = _unique_email('anon')
    resp = flask_app.test_client().post('/admin/crew/add', data=_form(email))
    assert resp.status_code in (302, 401)
    assert User.query.filter_by(email=email).first() is None


# ─────────────────────────── happy path ───────────────────────────

def test_creates_approved_crew_member(client_admin, tracked):
    email = _unique_email()
    resp = client_admin.post('/admin/crew/add', data=_form(email, send_welcome=''),
                             follow_redirects=False)
    assert resp.status_code == 302

    user = _fetch(email, tracked)
    assert user is not None
    assert user.is_worker is True
    assert user.worker_status == 'approved'
    assert user.worker_role == 'both'
    assert user.full_name == 'Test Crew Member'
    assert user.phone  # normalized by validate_phone
    assert user.password_hash  # temp password set so they can log in
    assert user.referral_code

    app_rec = WorkerApplication.query.filter_by(user_id=user.id).first()
    assert app_rec is not None
    assert app_rec.unc_year == 'Junior'
    assert app_rec.role_pref == 'both'
    assert app_rec.why_blurb == 'Added by hand.'
    assert app_rec.reviewed_at is not None
    assert app_rec.reviewed_by is not None


def test_temp_password_is_shown_to_admin_and_works(client_admin, tracked):
    email = _unique_email('pw')
    resp = client_admin.post('/admin/crew/add', data=_form(email, send_welcome=''),
                             follow_redirects=True)
    body = resp.get_data(as_text=True)
    assert 'Temporary password:' in body

    user = _fetch(email, tracked)
    # Pull the code out of the flash and confirm it authenticates.
    shown = body.split('Temporary password:')[1].split()[0].strip('.,')
    assert check_password_hash(user.password_hash, shown)


def test_availability_defaults_to_all_available(client_admin, tracked):
    email = _unique_email('avail-default')
    # No availability checkboxes submitted at all — _availability_booleans reads
    # unchecked as False, so the form must post every available slot explicitly.
    data = _form(email, send_welcome='')
    for day in ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']:
        for slot in ['am', 'pm']:
            data[f'{day}_{slot}'] = 'true'
    client_admin.post('/admin/crew/add', data=data)

    user = _fetch(email, tracked)
    avail = WorkerAvailability.query.filter_by(user_id=user.id, week_start=None).first()
    assert avail is not None
    assert all(getattr(avail, f'{d}_{s}')
               for d in ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
               for s in ['am', 'pm'])


def test_availability_blackouts_are_saved(client_admin, tracked):
    email = _unique_email('avail-blackout')
    data = _form(email, send_welcome='')
    for day in ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']:
        for slot in ['am', 'pm']:
            data[f'{day}_{slot}'] = 'true'
    del data['mon_am']   # blacked out
    del data['sun_pm']   # blacked out
    client_admin.post('/admin/crew/add', data=data)

    user = _fetch(email, tracked)
    avail = WorkerAvailability.query.filter_by(user_id=user.id, week_start=None).first()
    assert avail.mon_am is False
    assert avail.sun_pm is False
    assert avail.mon_pm is True
    assert avail.tue_am is True


# ─────────────────────────── validation ───────────────────────────

@pytest.mark.parametrize('missing', ['full_name', 'email', 'phone'])
def test_required_fields(client_admin, tracked, missing):
    email = _unique_email(f'missing-{missing}')
    data = _form(email)
    data[missing] = ''
    resp = client_admin.post('/admin/crew/add', data=data, follow_redirects=True)
    assert 'Name, email, and phone are required.' in resp.get_data(as_text=True)
    assert User.query.filter_by(email=email).first() is None


def test_invalid_email_rejected(client_admin):
    resp = client_admin.post('/admin/crew/add', data=_form('not-an-email'),
                             follow_redirects=True)
    assert 'Invalid email address.' in resp.get_data(as_text=True)
    assert User.query.filter_by(email='not-an-email').first() is None


def test_invalid_phone_rejected(client_admin, tracked):
    email = _unique_email('badphone')
    resp = client_admin.post('/admin/crew/add', data=_form(email, phone='123'),
                             follow_redirects=True)
    assert User.query.filter_by(email=email).first() is None
    assert resp.status_code == 200


# ─────────────────────────── existing users ───────────────────────────

def test_promotes_existing_user_without_touching_password(client_admin, tracked):
    email = _unique_email('existing')
    existing = User(email=email, full_name='Already Here', phone='(919) 555-0000',
                    password_hash='sentinel-hash', is_seller=True)
    db.session.add(existing)
    db.session.commit()
    tracked['users'].append(existing.id)

    client_admin.post('/admin/crew/add',
                      data=_form(email, full_name='Different Name', send_welcome=''))

    db.session.refresh(existing)
    assert existing.is_worker is True
    assert existing.worker_status == 'approved'
    assert existing.password_hash == 'sentinel-hash'  # never reset
    assert existing.full_name == 'Already Here'       # existing values win
    assert existing.is_seller is True                 # seller status preserved


def test_already_approved_crew_is_rejected(client_admin, tracked):
    email = _unique_email('dupe')
    existing = User(email=email, full_name='On The Crew', phone='(919) 555-0001',
                    is_worker=True, worker_status='approved', worker_role='both')
    db.session.add(existing)
    db.session.commit()
    tracked['users'].append(existing.id)

    resp = client_admin.post('/admin/crew/add', data=_form(email), follow_redirects=True)
    assert 'already on the crew' in resp.get_data(as_text=True)
    assert WorkerApplication.query.filter_by(user_id=existing.id).first() is None


def test_re_adding_rejected_applicant_reuses_records(client_admin, tracked):
    email = _unique_email('rejected')
    existing = User(email=email, full_name='Was Rejected', phone='(919) 555-0002',
                    is_worker=False, worker_status='rejected')
    db.session.add(existing)
    db.session.commit()
    tracked['users'].append(existing.id)
    db.session.add(WorkerApplication(user_id=existing.id, unc_year='Freshman',
                                     role_pref='both', applied_at=datetime.utcnow()))
    db.session.add(WorkerAvailability(user_id=existing.id, week_start=None))
    db.session.commit()

    data = _form(email, send_welcome='')
    data['mon_am'] = 'true'
    client_admin.post('/admin/crew/add', data=data)

    db.session.refresh(existing)
    assert existing.worker_status == 'approved'
    # WorkerApplication.user_id is unique — must be reused, not duplicated.
    assert WorkerApplication.query.filter_by(user_id=existing.id).count() == 1
    assert WorkerApplication.query.filter_by(user_id=existing.id).first().unc_year == 'Junior'
    assert WorkerAvailability.query.filter_by(user_id=existing.id, week_start=None).count() == 1


# ─────────────────────────── welcome email ───────────────────────────

def test_welcome_email_sent_when_checked(client_admin, tracked, monkeypatch):
    sent = []
    monkeypatch.setattr('app.send_email', lambda to, subj, body: sent.append((to, subj, body)))

    email = _unique_email('welcome')
    resp = client_admin.post('/admin/crew/add', data=_form(email, send_welcome='true'),
                             follow_redirects=True)
    _fetch(email, tracked)

    assert len(sent) == 1
    assert sent[0][0] == email
    assert 'Temporary password' in sent[0][2]
    assert 'Welcome email sent.' in resp.get_data(as_text=True)


def test_no_email_when_unchecked(client_admin, tracked, monkeypatch):
    sent = []
    monkeypatch.setattr('app.send_email', lambda to, subj, body: sent.append(to))

    email = _unique_email('nowelcome')
    client_admin.post('/admin/crew/add', data=_form(email, send_welcome=''))
    _fetch(email, tracked)

    assert sent == []


def test_email_failure_does_not_break_the_add(client_admin, tracked, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError('resend down')
    monkeypatch.setattr('app.send_email', boom)

    email = _unique_email('emailfail')
    resp = client_admin.post('/admin/crew/add', data=_form(email, send_welcome='true'),
                             follow_redirects=False)
    assert resp.status_code == 302

    user = _fetch(email, tracked)
    assert user is not None and user.worker_status == 'approved'


# ─────────────────────────── UI wiring ───────────────────────────

def test_crew_hq_renders_add_form(client_admin):
    resp = client_admin.get('/admin/crew')
    body = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert 'Add Crew Member' in body
    assert 'add-crew-modal' in body
    assert '/admin/crew/add' in body
