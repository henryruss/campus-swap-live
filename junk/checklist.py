"""The job-site checklist (feature_junk_jobsite.md, Slice 3a).

Crew prove a job from afar: photos of the cleared-out space, the dump receipt (or "dumped with
another job"), and where the truck went. Nothing is gated: any item, any job, any order, any
date, and every answer can be changed. Mix-ups are fixed afterward by a manager.

Payment is the fourth item; it arrives with Stripe (3b). A job whose checklist is complete waits
for a manager's review (Mark done). Until then crew can change anything; once a manager has
marked it done, only managers can.
"""
import secrets
from datetime import datetime

from models import db
from junk.jobs import JobFormError, log_event
from junk.models import JobCheck, JobPhoto

ITEMS = ('cleared', 'dump', 'truck')      # 'payment' joins with Stripe
MAX_PHOTOS = 12                            # per kind, per job
TRUCK_LABELS = {'returned': 'Returned it', 'handed': 'Handed off'}


def _storage():
    from storage import get_storage_instance
    return get_storage_instance()


class Checklist:
    """A job's answers, read once for a template."""

    def __init__(self, job):
        self.job = job
        self.cleared = [p for p in job.photos if p.kind == 'cleared']
        self.receipts = [p for p in job.photos if p.kind == 'dump']
        checks = {c.item: c for c in job.checks}
        self.dump_shared = 'dump' in checks and checks['dump'].answer == 'shared'
        self.truck = checks.get('truck')

    def answered(self, item):
        if item == 'cleared':
            return bool(self.cleared)
        if item == 'dump':
            return bool(self.receipts) or self.dump_shared
        if item == 'truck':
            return self.truck is not None
        return False

    @property
    def done(self):
        return sum(self.answered(i) for i in ITEMS)

    @property
    def total(self):
        return len(ITEMS)

    @property
    def complete(self):
        """Everything answered: the job waits on a manager's review."""
        return self.done == self.total


def add_photo(job, kind, file_obj, user):
    """Save one photo (resized, as JPEG) to the site's photo storage and attach it."""
    if kind not in JobPhoto.KINDS:
        raise JobFormError("That didn't work. Refresh and try again.")
    if sum(p.kind == kind for p in job.photos) >= MAX_PHOTOS:
        raise JobFormError(f"That's the most photos ({MAX_PHOTOS}) for one item.")
    if kind == 'dump' and any(c.item == 'dump' and c.answer == 'shared' for c in job.checks):
        raise JobFormError("This job says it was dumped with another job. Undo that first.")
    key = f'junk_{job.id}_{kind}_{secrets.token_hex(12)}.jpg'
    try:
        _storage().save_photo(file_obj, key)
    except Exception:
        raise JobFormError("That file isn't a photo we can read. Try another.")
    photo = JobPhoto(kind=kind, key=key, uploaded_by_id=getattr(user, 'id', None))
    job.photos.append(photo)
    db.session.flush()
    log_event(job, user, 'checklist', {'photo': [None, kind]})
    db.session.commit()
    return photo


def remove_photo(photo, user):
    job = photo.job
    kind = photo.kind
    job.photos.remove(photo)
    db.session.flush()
    log_event(job, user, 'checklist', {'photo': [kind, None]})
    db.session.commit()
    try:
        _storage().delete_photo(photo.key)
    except Exception:
        pass   # the row is gone; an orphaned file is harmless


def set_check(job, item, answer, user):
    """Answer (or, with answer='' / None, clear) the dump or truck item."""
    if item not in JobCheck.ANSWERS:
        raise JobFormError("That didn't work. Refresh and try again.")
    answer = answer or None
    if answer and answer not in JobCheck.ANSWERS[item]:
        raise JobFormError("That didn't work. Refresh and try again.")
    if item == 'dump' and answer and any(p.kind == 'dump' for p in job.photos):
        raise JobFormError("There's already a receipt photo. Remove it first.")
    handed_to = None   # "Handed off" is just a tap for now (feature_junk_jobsite.md); the column waits
    current = next((c for c in job.checks if c.item == item), None)

    def describe(c):
        return c.answer if c is not None else None

    before = describe(current)
    if answer is None:
        if current is not None:
            job.checks.remove(current)
    else:
        if current is None:
            current = JobCheck(item=item, answer=answer)
            job.checks.append(current)
        current.answer = answer
        current.handed_to = handed_to
        current.handed_to_id = getattr(handed_to, 'id', None)
        current.answered_by_id = getattr(user, 'id', None)
        current.answered_at = datetime.utcnow()
    db.session.flush()
    after = describe(current) if answer else None
    if before != after:
        log_event(job, user, 'checklist', {item: [before, after]})
    db.session.commit()
