"""Tests for the job-site checklist (feature_junk_jobsite.md, Slice 3a).

Run: python3 -m pytest test_junk_checklist.py -q

SAFE against campusswap_prod: requests nothing from either conftest (their `app`/`db`
fixtures drop_all()). Photos go to a temp folder, never static/uploads or S3. Every user and
job created here is deleted in teardown (photos and answers go with their job).
"""
import os
import uuid
from datetime import date
from io import BytesIO

import pytest
from flask import g
from flask.testing import FlaskClient
from PIL import Image

import storage
from app import app as flask_app, db
from models import User
from junk.checklist import MAX_PHOTOS
from junk.jobs import delete_job
from junk.models import Job, JobAssignment, JobCheck, JobEvent, JobPhoto


@pytest.fixture
def app_ctx(tmp_path, monkeypatch):
    flask_app.config['TESTING'] = True
    flask_app.config['WTF_CSRF_ENABLED'] = False
    monkeypatch.setattr(storage, '_storage', storage.LocalStorage(str(tmp_path)))
    with flask_app.app_context():
        yield flask_app
        db.session.rollback()


@pytest.fixture
def made(app_ctx):
    created = {'users': [], 'jobs': []}
    yield created
    db.session.rollback()
    jobs, uids = created['jobs'], created['users']
    if jobs:
        db.session.execute(db.delete(JobEvent).where(JobEvent.job_id.in_(jobs)))
        db.session.execute(db.delete(Job).where(Job.id.in_(jobs)))   # photos, answers, crew cascade
    if uids:
        db.session.execute(db.delete(User).where(User.id.in_(uids)))
    db.session.commit()


@pytest.fixture
def people(made):
    def user(name, **flags):
        u = User(email=f'jr-ck-test-{uuid.uuid4().hex[:10]}@example.com', full_name=name, **flags)
        db.session.add(u)
        db.session.commit()
        made['users'].append(u.id)
        return u
    mgr = user('Mia Manager', is_junk_manager=True)
    me = user('Cal Crew', is_junk_crew=True)
    pal = user('Pat Partner', is_junk_crew=True)
    other = user('Oscar Other', is_junk_crew=True)
    job = Job(created_by_id=mgr.id, customer_name='Checklist Job', address='829 Shearer St, Davidson, NC',
              scheduled_date=date(2099, 5, 4), queue_position=1)
    job.assignments.append(JobAssignment(user_id=me.id))
    db.session.add(job)
    db.session.commit()
    made['jobs'].append(job.id)
    return {'mgr': mgr, 'me': me, 'pal': pal, 'other': other, 'job': job}


class _Client(FlaskClient):
    def open(self, *args, **kwargs):
        g.pop('_login_user', None)   # one app context across requests (see test_junk_crew.py)
        return super().open(*args, **kwargs)


def _login(user):
    c = _Client(flask_app, flask_app.response_class, use_cookies=True)
    with c.session_transaction() as s:
        s['_user_id'] = str(user.id)
        s['_fresh'] = True
    return c


def _jpeg(color='white'):
    buf = BytesIO()
    Image.new('RGB', (40, 30), color).save(buf, 'JPEG')
    buf.seek(0)
    return buf


def _upload(c, job, kind='cleared', f=None):
    return c.post(f'/junk/job/{job.id}/photo', data={'kind': kind, 'photo': (f or _jpeg(), 'p.jpg')},
                  content_type='multipart/form-data')


def _check(c, job, **body):
    return c.post(f'/junk/job/{job.id}/check', json=body)


def _fresh(job):
    db.session.expire_all()
    return db.session.get(Job, job.id)


# ── photos ──────────────────────────────────────────────────

def test_crew_on_the_job_adds_a_photo(people):
    job, c = people['job'], _login(people['me'])
    r = _upload(c, job)
    assert r.status_code == 200 and r.json['ok']
    assert '1 of 3' in r.json['html']
    [photo] = _fresh(job).photos
    assert photo.kind == 'cleared' and photo.uploaded_by_id == people['me'].id
    assert os.path.exists(os.path.join(storage._storage.upload_folder, photo.key))
    img = c.get(f'/junk/job/photo/{photo.id}')
    assert img.status_code == 200 and img.mimetype == 'image/jpeg'
    assert img.headers['Cache-Control'].startswith('private')
    assert JobEvent.query.filter_by(job_id=job.id, action='checklist').count() == 1


def test_only_the_jobs_crew_and_managers(people):
    job = people['job']
    assert _upload(_login(people['me']), job).status_code == 200
    photo = _fresh(job).photos[0]
    outsider = _login(people['other'])
    assert _upload(outsider, job).status_code == 403
    assert outsider.get(f'/junk/job/photo/{photo.id}').status_code == 403
    assert _check(outsider, job, item='truck', answer='returned').status_code == 403
    assert outsider.post(f'/junk/job/photo/{photo.id}/remove').status_code == 403
    mgr = _login(people['mgr'])          # managers can fill in and see any job
    assert mgr.get(f'/junk/job/photo/{photo.id}').status_code == 200
    assert _upload(mgr, job, 'dump').status_code == 200
    anon = _Client(flask_app, flask_app.response_class, use_cookies=True)
    assert anon.get(f'/junk/job/photo/{photo.id}').status_code == 302   # to sign-in


def test_not_a_photo(people):
    r = _upload(_login(people['me']), people['job'], f=BytesIO(b'%PDF-1.4 not an image'))
    assert r.status_code == 400 and not r.json['ok'] and "isn't a photo" in r.json['error']
    assert _fresh(people['job']).photos == []


def test_bad_kind_and_photo_limit(people):
    c, job = _login(people['me']), people['job']
    assert _upload(c, job, kind='selfie').status_code == 400
    for _ in range(MAX_PHOTOS):
        assert _upload(c, job).status_code == 200
    r = _upload(c, job)
    assert r.status_code == 400 and 'most photos' in r.json['error']
    assert _upload(c, job, 'dump').status_code == 200        # the limit is per item


def test_remove_a_photo(people):
    c, job = _login(people['me']), people['job']
    _upload(c, job)
    photo = _fresh(job).photos[0]
    path = os.path.join(storage._storage.upload_folder, photo.key)
    r = c.post(f'/junk/job/photo/{photo.id}/remove')
    assert r.status_code == 200 and '0 of 3' in r.json['html']
    assert _fresh(job).photos == [] and not os.path.exists(path)


def test_deleting_a_job_deletes_its_photos(people):
    job = people['job']
    _upload(_login(people['me']), job)
    path = os.path.join(storage._storage.upload_folder, _fresh(job).photos[0].key)
    delete_job(_fresh(job))
    assert not os.path.exists(path)
    assert JobPhoto.query.filter_by(job_id=job.id).count() == 0


# ── answers ─────────────────────────────────────────────────

def test_dump_is_a_receipt_or_another_jobs_load(people):
    c, job = _login(people['me']), people['job']
    _check(c, job, item='dump', answer='shared')
    r = _upload(c, job, 'dump')
    assert r.status_code == 400 and 'Undo that first' in r.json['error']
    _check(c, job, item='dump', answer='')
    assert _upload(c, job, 'dump').status_code == 200
    r = _check(c, job, item='dump', answer='shared')
    assert r.status_code == 400 and 'Remove it first' in r.json['error']
    assert 'data-answer="shared"' not in r.json['html'] and 'data-photo-add="dump"' not in r.json['html']


def test_dumped_with_another_job_toggles(people):
    c, job = _login(people['me']), people['job']
    r = _check(c, job, item='dump', answer='shared')
    assert r.status_code == 200 and '1 of 3' in r.json['html'] and 'aria-pressed="true"' in r.json['html']
    assert _check(c, job, item='dump', answer='').status_code == 200   # tap again: undone
    assert _fresh(job).checks == []
    assert _check(c, job, item='dump', answer='returned').status_code == 400


def test_truck_answers(people):
    c, job = _login(people['me']), people['job']
    r = _check(c, job, item='truck', answer='handed')          # just a tap, no person to pick
    assert r.status_code == 200 and 'aria-pressed="true"' in r.json['html']
    t = _fresh(job).checks[0]
    assert (t.item, t.answer, t.handed_to_id, t.answered_by_id) == ('truck', 'handed', None, people['me'].id)
    _check(c, job, item='truck', answer='returned')
    assert _fresh(job).checks[0].answer == 'returned'
    assert _check(c, job, item='truck', answer='kept').status_code == 400   # "still have it" is gone
    _check(c, job, item='truck', answer='')                    # tap the chosen one again: undone
    assert _fresh(job).checks == []
    events = JobEvent.query.filter_by(job_id=job.id, action='checklist').order_by(JobEvent.id).all()
    assert [e.changes['truck'] for e in events] == [[None, 'handed'], ['handed', 'returned'], ['returned', None]]


def test_complete_checklist_waits_for_manager_review(people):
    c, job = _login(people['me']), people['job']
    _upload(c, job)
    _check(c, job, item='dump', answer='shared')
    r = _check(c, job, item='truck', answer='returned')
    assert r.json['complete'] and '3 of 3' in r.json['html']
    assert 'waiting on manager review' in r.json['status']
    assert _fresh(job).completed_at is None      # a manager's Mark done closes it
    page = c.get('/junk/crew').get_data(as_text=True)
    assert page.index('Waiting on review') < page.index('Checklist Job')


def test_closed_jobs_are_read_only_for_crew(people):
    c, job, mgr = _login(people['me']), people['job'], _login(people['mgr'])
    _upload(c, job)
    photo = _fresh(job).photos[0]
    mgr.post(f'/junk/manage/job/{job.id}/done', data={})
    assert _fresh(job).completed_at is not None
    r = _upload(c, job)
    assert r.status_code == 403 and 'closed this job' in r.json['error']
    assert _check(c, job, item='truck', answer='returned').status_code == 403
    assert c.post(f'/junk/job/photo/{photo.id}/remove').status_code == 403
    assert c.get(f'/junk/job/photo/{photo.id}').status_code == 200        # still visible
    page = c.get(f'/junk/crew/done?job={job.id}').get_data(as_text=True)
    assert 'A manager has closed this job' in page and 'data-photo-add' not in page
    assert _upload(mgr, job).status_code == 200                            # managers still can


def test_my_jobs_shows_the_checklist(people):
    c = _login(people['me'])
    _check(c, people['job'], item='truck', answer='returned')
    page = c.get('/junk/crew').get_data(as_text=True)
    assert 'data-checklist' in page and '1 of 3' in page
    assert 'data-answer="handed"' in page and 'data-hand-to' not in page


# ── photos from a phone (QR on a computer) ──────────────────

def test_qr_link_adds_photos_from_a_phone_without_signing_in(people):
    c, job = _login(people['me']), people['job']
    r = c.get(f'/junk/job/{job.id}/snap?kind=cleared')
    assert r.status_code == 200 and r.json['ok'] and '<svg' in r.json['svg']
    path = '/junk/snap/' + r.json['url'].split('/junk/snap/')[1]
    phone = _Client(flask_app, flask_app.response_class, use_cookies=True)   # not signed in
    page = phone.get(path)
    assert page.status_code == 200 and 'Cleared out' in page.get_data(as_text=True)
    up = phone.post(path + '/photo', data={'photo': (_jpeg(), 'p.jpg')}, content_type='multipart/form-data')
    assert up.status_code == 200 and up.json['ok'] and '1 photo on the job' in up.json['html']
    [photo] = _fresh(job).photos
    assert (photo.kind, photo.uploaded_by_id) == ('cleared', people['me'].id)    # it's theirs
    assert phone.get(f'{path}/photo/{photo.id}').status_code == 200
    # The computer's card picks it up.
    assert '1 of 3' in c.get(f'/junk/job/{job.id}/checklist').json['html']


def test_qr_links_are_guarded(people, monkeypatch):
    c, job = _login(people['me']), people['job']
    assert _login(people['other']).get(f'/junk/job/{job.id}/snap?kind=cleared').status_code == 403
    assert c.get(f'/junk/job/{job.id}/snap?kind=selfie').status_code == 400
    phone = _Client(flask_app, flask_app.response_class, use_cookies=True)
    assert phone.get('/junk/snap/not-a-real-token').status_code == 404
    assert phone.post('/junk/snap/not-a-real-token/photo', data={}).status_code == 403
    path = '/junk/snap/' + c.get(f'/junk/job/{job.id}/snap?kind=dump').json['url'].split('/junk/snap/')[1]
    import junk.routes as jr
    monkeypatch.setattr(jr, 'SNAP_MAX_AGE', -1)                                # expired
    assert phone.get(path).status_code == 410
    monkeypatch.setattr(jr, 'SNAP_MAX_AGE', 1800)
    _login(people['mgr']).post(f'/junk/manage/job/{job.id}/done', data={})   # closed by a manager
    r = phone.post(path + '/photo', data={'photo': (_jpeg(), 'p.jpg')}, content_type='multipart/form-data')
    assert r.status_code == 403 and 'closed' in r.json['error']
    assert c.get(f'/junk/job/{job.id}/snap?kind=cleared').status_code == 403


# ── the manager side ────────────────────────────────────────

def _other_job(people, **fields):
    j = Job(created_by_id=people['mgr'].id, customer_name='Other Job', scheduled_date=date(2099, 5, 6), queue_position=1, **fields)
    db.session.add(j)
    db.session.commit()
    return j


def test_job_modal_shows_the_checklist_with_who_and_when(people, made):
    c, job, mgr = _login(people['me']), people['job'], _login(people['mgr'])
    _upload(c, job)
    _check(c, job, item='dump', answer='shared')
    form = mgr.get(f'/junk/manage/job/form?id={job.id}').get_data(as_text=True)
    assert 'data-checklist' in form and '2 of 3' in form
    assert 'Cal · ' in form                                  # who answered (first name) and when
    assert 'data-move=' in form                              # managers can move photos
    assert 'jr-btn--quiet">Mark done' in form                # not complete yet: Mark done stays quiet
    _check(c, job, item='truck', answer='returned')
    form = mgr.get(f'/junk/manage/job/form?id={job.id}').get_data(as_text=True)
    assert 'jr-btn--primary">Mark done' in form              # complete: ready for review
    crew_page = c.get('/junk/crew').get_data(as_text=True)
    assert 'data-move=' not in crew_page and 'Cal · ' not in crew_page   # crew don't get either


def test_calendar_cards_show_checklist_dots(people):
    c, job, mgr = _login(people['me']), people['job'], _login(people['mgr'])
    page = mgr.get('/junk/manage?date=2099-05-04').get_data(as_text=True)
    assert 'jr-card-ck' not in page                          # nothing answered yet: no dots
    _check(c, job, item='truck', answer='returned')
    page = mgr.get('/junk/manage?date=2099-05-04').get_data(as_text=True)
    assert 'Checklist 1 of 3' in page and page.count('class="on"') >= 1


def test_manager_moves_a_photo_to_the_right_job(people, made):
    c, job, mgr = _login(people['me']), people['job'], _login(people['mgr'])
    other = _other_job(people)
    made['jobs'].append(other.id)
    _check(c, job, item='dump', answer='')
    _upload(c, job, 'dump')
    photo = _fresh(job).photos[0]
    targets = mgr.get(f'/junk/manage/photo/{photo.id}/targets').json['jobs']
    assert other.id in [t['id'] for t in targets] and job.id not in [t['id'] for t in targets]
    other_check = JobCheck(job_id=other.id, item='dump', answer='shared')   # the other job said "shared"
    db.session.add(other_check)
    db.session.commit()
    r = mgr.post(f'/junk/manage/photo/{photo.id}/move', json={'job_id': other.id})
    assert r.status_code == 200 and '0 of 3' in r.json['html']              # the old job's checklist
    db.session.expire_all()
    moved = db.session.get(JobPhoto, photo.id)
    assert moved.job_id == other.id and moved.key == photo.key             # same file, new job
    assert JobCheck.query.filter_by(job_id=other.id, item='dump').count() == 0   # the receipt wins
    assert JobEvent.query.filter_by(job_id=other.id, action='checklist').count() == 1
    assert _login(people['me']).post(f'/junk/manage/photo/{photo.id}/move', json={'job_id': job.id}).status_code == 403


def test_job_modal_checklist_is_to_look_at_with_an_edit_button(people):
    c, job, mgr = _login(people['me']), people['job'], _login(people['mgr'])
    form = mgr.get(f'/junk/manage/job/form?id={job.id}').get_data(as_text=True)
    assert 'data-ck-review' in form and 'data-ck-edit' in form
    assert form.index('id="jr-job-form"') < form.index('data-ck-review')      # untouched: below the details
    _check(c, job, item='truck', answer='handed')
    form = mgr.get(f'/junk/manage/job/form?id={job.id}').get_data(as_text=True)
    assert form.index('data-ck-review') < form.index('id="jr-job-form"')      # started: on top
    assert 'Handed off' in form and 'No photos yet' in form
    r = _check(mgr, job, item='truck', answer='returned')                     # a manager edits
    assert 'Returned it' in r.json['review']                                  # the look updates too
    assert _check(c, job, item='truck', answer='handed').json['review'] is None   # crew don't get it
