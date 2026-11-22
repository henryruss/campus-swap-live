"""Job logic: queue ordering, form parsing, and change history.

Kept separate from routes so the rules are testable on their own. Nothing in junk/ imports
from app.py (helpers.py already has a circular import with it).
"""
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from models import db
from junk.models import Job, JobAssignment, JobEvent, person_name

EASTERN = ZoneInfo('America/New_York')

# Field order here is the order the form and history show them in.
JOB_FIELDS = ('customer_name', 'customer_phone', 'address', 'quote_amount', 'scheduled_date', 'notes')
FIELD_LABELS = {
    'customer_name': 'Name',
    'customer_phone': 'Phone',
    'address': 'Address',
    'quote_amount': 'Quote',
    'scheduled_date': 'Date',
    'notes': 'Notes',
}
_MAX_LEN = {'customer_name': 120, 'customer_phone': 30, 'address': 255}


class JobFormError(ValueError):
    pass


# ─── time ────────────────────────────────────────────────────────────────

def today_eastern():
    return datetime.now(EASTERN).date()


def to_eastern(dt_utc):
    """Naive UTC datetime → aware Eastern datetime, for display."""
    if dt_utc is None:
        return None
    return dt_utc.replace(tzinfo=ZoneInfo('UTC')).astimezone(EASTERN)


def week_start(d):
    """Monday of the week containing d."""
    return d - timedelta(days=d.weekday())


def parse_date(raw):
    """'YYYY-MM-DD' → date; blank → None. Raises JobFormError on garbage."""
    raw = (raw or '').strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise JobFormError("That date doesn't look right.")


def parse_quote(raw):
    """'$1,250' / '250' / '' → Decimal or None. Raises JobFormError on garbage."""
    raw = (raw or '').strip().replace('$', '').replace(',', '')
    if not raw:
        return None
    try:
        value = Decimal(raw).quantize(Decimal('0.01'))
    except InvalidOperation:
        raise JobFormError("Quote should be a dollar amount, like 250.")
    if value < 0 or value >= Decimal('100000000'):
        raise JobFormError("Quote should be a dollar amount, like 250.")
    return value


def parse_job_form(form):
    """Request form → {field: value} for every JOB_FIELD. All fields optional."""
    values = {}
    for field in ('customer_name', 'customer_phone', 'address'):
        v = (form.get(field) or '').strip()
        values[field] = v[:_MAX_LEN[field]] or None
    values['notes'] = (form.get('notes') or '').strip() or None
    values['quote_amount'] = parse_quote(form.get('quote_amount'))
    values['scheduled_date'] = parse_date(form.get('scheduled_date'))
    return values


def parse_location(form, address):
    """(lat, lng) from the hidden fields the Places picker fills, or (None, None). Coordinates
    without an address, or out of range, are dropped rather than rejected."""
    if not address:
        return None, None
    try:
        lat = float(form.get('address_lat') or '')
        lng = float(form.get('address_lng') or '')
    except ValueError:
        return None, None
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None, None
    return lat, lng


def _set_location(job, location):
    """Location isn't a history field: it follows the address, which is."""
    if location is None:
        return False
    lat, lng = location
    if (job.address_lat, job.address_lng) == (lat, lng):
        return False
    job.address_lat, job.address_lng = lat, lng
    return True


# ─── the day's line ──────────────────────────────────────────────────────

def day_line_query(d):
    """A line of jobs, in order. For a date: that day's jobs, done or not (done is just a
    state; a done job keeps its place). For d=None: the Unscheduled queue, where a job
    joins at the bottom whenever it lands there."""
    q = Job.query.filter(Job.scheduled_date.is_(None) if d is None else Job.scheduled_date == d)
    return q.order_by(Job.queue_position.asc().nullslast(), Job.id.asc())


def unscheduled_query():
    return day_line_query(None)


def renumber_day(d):
    """Renumber a line (a day, or the Unscheduled queue for d=None) 1..n, closing gaps."""
    for i, job in enumerate(day_line_query(d).all(), start=1):
        if job.queue_position != i:
            job.queue_position = i


def place_job(job):
    """Put a job at the bottom of the line its date says it belongs in (a day, or the
    Unscheduled queue). Call after changing scheduled_date. Does not renumber the line the
    job came from — callers do that."""
    job.queue_position = day_line_query(job.scheduled_date).filter(Job.id != job.id).count() + 1


# ─── history ─────────────────────────────────────────────────────────────

def _jsonable(v):
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return str(v)
    return v


def _normalize(field, v):
    """Compare quote values as Decimals so 250 vs 250.00 isn't a change."""
    if field == 'quote_amount' and v is not None:
        return Decimal(v).quantize(Decimal('0.01'))
    return v


def diff_fields(job, values):
    """{field: [old, new]} for fields in values that differ from the job's current values."""
    changes = {}
    for field, new in values.items():
        old = getattr(job, field)
        if _normalize(field, old) != _normalize(field, new):
            changes[field] = [_jsonable(old), _jsonable(new)]
    return changes


def log_event(job, user, action, changes=None):
    db.session.add(JobEvent(job_id=job.id, user_id=getattr(user, 'id', None),
                            action=action, changes=changes or {}))


# The modal autosaves as you type, so one sitting of edits by one person becomes one entry.
EDIT_MERGE_WINDOW = timedelta(minutes=10)


def log_edit(job, user, changes):
    uid = getattr(user, 'id', None)
    last = job.events.first()  # newest
    if not (last and last.action == 'updated' and last.user_id == uid
            and datetime.utcnow() - last.created_at < EDIT_MERGE_WINDOW):
        log_event(job, user, 'updated', changes)
        return
    merged = dict(last.changes or {})
    for field, (old, new) in changes.items():
        if field in merged:
            old = merged[field][0]   # keep the value from before the sitting started
        if _normalize(field, old) == _normalize(field, new):
            merged.pop(field, None)  # edited and then put back
        else:
            merged[field] = [old, new]
    if merged:
        last.changes = merged        # a new dict, so SQLAlchemy sees the JSON change
        last.created_at = datetime.utcnow()
    else:
        db.session.delete(last)


# ─── operations (each commits) ───────────────────────────────────────────

def create_job(values, user, location=None):
    job = Job(created_by_id=getattr(user, 'id', None), **values)
    _set_location(job, location)
    db.session.add(job)
    db.session.flush()
    place_job(job)
    log_event(job, user, 'created',
              {f: [None, _jsonable(v)] for f, v in values.items() if v is not None})
    db.session.commit()
    return job


def update_job(job, values, user, location=None):
    """Apply edited fields. A date change sends the job to the end of the new day's line."""
    changes = diff_fields(job, values)
    moved_pin = _set_location(job, location)
    if not changes:
        if moved_pin:
            db.session.commit()
        return job
    old_date = job.scheduled_date
    for field, v in values.items():
        setattr(job, field, v)
    if 'scheduled_date' in changes:
        db.session.flush()
        place_job(job)
        renumber_day(old_date)
    log_edit(job, user, changes)
    db.session.commit()
    return job


def set_crew(job, person, actor, on):
    """Put a person on a job (on=True) or take them off. Returns False if nothing changed.
    Anyone with junk access can work a job, managers included."""
    from junk.auth import has_junk_access
    current = {a.user_id: a for a in job.assignments}
    if on == (person.id in current):
        return False
    if on and not has_junk_access(person):
        raise JobFormError(f"{person_name(person)} isn't on the team.")
    before = [person_name(u) for u in job.crew]
    if on:
        job.assignments.append(JobAssignment(user=person, created_by_id=getattr(actor, 'id', None)))
    else:
        job.assignments.remove(current[person.id])
    db.session.flush()
    log_edit(job, actor, {'crew': [before, [person_name(u) for u in job.crew]]})
    db.session.commit()
    return True


def mark_done(job, user):
    """Done keeps the job's place in its day's line."""
    if job.completed_at:
        return job
    if not job.scheduled_date:
        raise JobFormError("Give the job a date before marking it done.")
    job.completed_at = datetime.utcnow()
    job.completed_by_id = getattr(user, 'id', None)
    log_event(job, user, 'done')
    db.session.commit()
    return job


def undo_done(job, user):
    if not job.completed_at:
        return job
    job.completed_at = None
    job.completed_by_id = None
    log_event(job, user, 'undone')
    db.session.commit()
    return job


def delete_job(job):
    """Permanently delete a job and its history. Closes the gap in the line it was in."""
    line = job.scheduled_date
    keys = [p.key for p in job.photos]        # checklist photos go too
    db.session.execute(db.delete(JobEvent).where(JobEvent.job_id == job.id))
    db.session.delete(job)
    db.session.flush()
    renumber_day(line)
    db.session.commit()
    if keys:
        from storage import get_storage_instance
        for key in keys:
            try:
                get_storage_instance().delete_photo(key)
            except Exception:
                pass


class StaleBoard(Exception):
    """The client's view of the day no longer matches the DB (someone else edited it)."""


def move_job(job, target_date, ordered_ids, user):
    """Drag-and-drop save.

    target_date=None → unschedule: the job joins the bottom of the Unscheduled queue
    (ordered_ids ignored). Otherwise ordered_ids must be exactly the target day's line plus
    this one, in their new order. Anything else means the client is stale → StaleBoard,
    nothing changed.
    """
    old_date = job.scheduled_date

    if target_date is None:
        if old_date is None:
            return job
        if job.completed_at:
            raise StaleBoard()  # a done job must keep a date
        job.scheduled_date = None
        db.session.flush()
        place_job(job)
        renumber_day(old_date)
        log_event(job, user, 'updated', {'scheduled_date': [_jsonable(old_date), None]})
        db.session.commit()
        return job

    try:
        ordered_ids = [int(i) for i in ordered_ids]
    except (TypeError, ValueError):
        raise StaleBoard()
    current = {j.id for j in day_line_query(target_date).filter(Job.id != job.id)}
    expected = current | {job.id}
    if len(ordered_ids) != len(set(ordered_ids)) or set(ordered_ids) != expected:
        raise StaleBoard()

    job.scheduled_date = target_date
    by_id = {j.id: j for j in Job.query.filter(Job.id.in_(expected))}
    for pos, jid in enumerate(ordered_ids, start=1):
        by_id[jid].queue_position = pos
    db.session.flush()
    if old_date != target_date:
        renumber_day(old_date)
        log_event(job, user, 'updated',
                  {'scheduled_date': [_jsonable(old_date), _jsonable(target_date)]})
    db.session.commit()
    return job


# ─── display ─────────────────────────────────────────────────────────────

def format_value(field, raw):
    """History display for a stored JSON value."""
    if raw in (None, ''):
        return '—'
    if field == 'scheduled_date':
        try:
            return date.fromisoformat(raw).strftime('%a, %b %-d')
        except (TypeError, ValueError):
            return str(raw)
    if field == 'quote_amount':
        try:
            return format_money(Decimal(raw))
        except InvalidOperation:
            return str(raw)
    if field == 'notes' and len(str(raw)) > 60:
        return str(raw)[:57] + '…'
    return str(raw)


CREW_PAY_DEFAULT = 20   # percent of the quote, per person on the job (Henry, 2026-11-18)


def crew_pay_pct():
    """Each person's share of a job, in percent. AppSetting junk_crew_pay_pct, default 20."""
    from models import AppSetting
    try:
        pct = Decimal(str(AppSetting.get('junk_crew_pay_pct', CREW_PAY_DEFAULT)))
    except (InvalidOperation, ValueError):
        return Decimal(CREW_PAY_DEFAULT)
    return pct if 0 <= pct <= 100 else Decimal(CREW_PAY_DEFAULT)


def crew_cut(job, pct=None):
    """What one person on this job makes: pct × quote, to the cent. None while there's no quote."""
    if job.quote_amount is None:
        return None
    pct = crew_pay_pct() if pct is None else pct
    return (job.quote_amount * pct / 100).quantize(Decimal('0.01'))


def format_money(v):
    if v is None:
        return ''
    v = Decimal(v)
    return f"${v:,.0f}" if v == v.to_integral_value() else f"${v:,.2f}"
