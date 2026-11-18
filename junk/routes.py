"""Junk removal routes: sign-in, calendar, job modal, drag-and-drop saves."""
import calendar as _calendar
import os
from collections import defaultdict
from datetime import timedelta

from flask import abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_user, logout_user
from werkzeug.security import check_password_hash

from junk import junk_bp
from junk.auth import is_junk_manager, is_junk_only, junk_manager_required
from junk.jobs import (
    FIELD_LABELS, JOB_FIELDS, JobFormError, StaleBoard,
    create_job, delete_job, format_money, format_value, mark_done, move_job,
    parse_date, parse_job_form, to_eastern, today_eastern, undo_done,
    unscheduled_query, update_job, week_start,
)
from junk.models import Job
from models import db, User


@junk_bp.app_template_filter('jr_money')
def _jr_money(v):
    return format_money(v)


@junk_bp.app_template_filter('jr_plain')
def _jr_plain(v):
    """Quote for an input box: 250 / 250.50, no $ or commas."""
    if v is None:
        return ''
    return str(int(v)) if v == v.to_integral_value() else f"{v:.2f}"


@junk_bp.app_template_filter('jr_eastern')
def _jr_eastern(dt):
    local = to_eastern(dt)
    return local.strftime('%b %-d, %-I:%M %p') if local else ''


@junk_bp.context_processor
def _junk_context():
    return {'google_maps_key': os.environ.get('GOOGLE_MAPS_API_KEY', '')}


# ─── separation from the legacy site ─────────────────────────────────────

_JUNK_ONLY_ALLOWED = ('/junk', '/static/', '/favicon')


@junk_bp.before_app_request
def _confine_junk_only_users():
    """A junk-only account never sees the legacy Campus Swap site. Anything outside /junk
    sends them back to their calendar."""
    if not current_user.is_authenticated or not is_junk_only(current_user):
        return None
    path = request.path
    if path == '/logout':
        return redirect(url_for('junk.logout'))
    if path.startswith(_JUNK_ONLY_ALLOWED):
        return None
    return redirect(url_for('junk.manage'))


# ─── sign in / out ───────────────────────────────────────────────────────

def _safe_next(target):
    if target and target.startswith('/junk') and not target.startswith('//'):
        return target
    return url_for('junk.manage')


@junk_bp.route('/')
def index():
    return redirect(url_for('junk.manage'))


@junk_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated and is_junk_manager():
        return redirect(url_for('junk.manage'))
    email = ''
    error = None
    if request.method == 'POST':
        email = (request.form.get('email') or '').strip()
        password = request.form.get('password') or ''
        user = User.query.filter(db.func.lower(User.email) == email.lower()).first() if email else None
        if not user or not user.password_hash or not check_password_hash(user.password_hash, password):
            error = "That email and password don't match."
        elif not is_junk_manager(user):
            error = "This account doesn't have access yet."
        else:
            login_user(user, remember=True)
            return redirect(_safe_next(request.args.get('next')))
    return render_template('junk/login.html', email=email, error=error)


@junk_bp.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('junk.login'))


# ─── helpers ─────────────────────────────────────────────────────────────

def _calendar_url(view, d):
    args = {'date': d.isoformat()}
    if view == 'month':
        args['view'] = 'month'
    return url_for('junk.manage', **args)


def _safe_return(default=None):
    """Only ever redirect back inside the manager portal."""
    target = request.form.get('return_to') or ''
    if target.startswith('/junk/manage') and not target.startswith('//'):
        return target
    return default or url_for('junk.manage')


def _get_job(job_id):
    job = db.session.get(Job, job_id)
    if job is None:
        abort(404)
    return job


def _week_label(start):
    end = start + timedelta(days=6)
    if start.month == end.month:
        return f"{start.strftime('%b %-d')} – {end.day}"
    if start.year == end.year:
        return f"{start.strftime('%b %-d')} – {end.strftime('%b %-d')}"
    return f"{start.strftime('%b %-d, %Y')} – {end.strftime('%b %-d, %Y')}"


def _jobs_by_day(first, last):
    """{date: [jobs in line order]}. Done jobs keep their place."""
    rows = (Job.query
            .filter(Job.scheduled_date >= first, Job.scheduled_date <= last)
            .order_by(Job.scheduled_date, Job.queue_position.asc().nullslast(), Job.id.asc())
            .all())
    days = defaultdict(list)
    for job in rows:
        days[job.scheduled_date].append(job)
    return days


# ─── calendar ────────────────────────────────────────────────────────────

@junk_bp.route('/manage')
@junk_manager_required
def manage():
    view = 'month' if request.args.get('view') == 'month' else 'week'
    today = today_eastern()
    try:
        anchor = parse_date(request.args.get('date')) or today
    except JobFormError:
        anchor = today

    unscheduled = unscheduled_query().all()

    ctx = dict(view=view, today=today, anchor=anchor, unscheduled=unscheduled,
               return_to=_calendar_url(view, anchor))

    if view == 'week':
        start = week_start(anchor)
        days = [start + timedelta(days=i) for i in range(7)]
        ctx.update(
            days=days,
            jobs=_jobs_by_day(days[0], days[-1]),
            label=_week_label(start),
            showing_today=(start == week_start(today)),
            prev_url=_calendar_url('week', start - timedelta(days=7)),
            next_url=_calendar_url('week', start + timedelta(days=7)),
            today_url=_calendar_url('week', today),
            week_url=_calendar_url('week', anchor),
            month_url=_calendar_url('month', anchor),
        )
    else:
        first = anchor.replace(day=1)
        last = first.replace(day=_calendar.monthrange(first.year, first.month)[1])
        grid_start = week_start(first)
        grid_end = week_start(last) + timedelta(days=6)
        n_days = (grid_end - grid_start).days + 1
        prev_month = (first - timedelta(days=1)).replace(day=1)
        next_month = last + timedelta(days=1)
        ctx.update(
            weeks=[[grid_start + timedelta(days=w * 7 + i) for i in range(7)]
                   for w in range(n_days // 7)],
            jobs=_jobs_by_day(grid_start, grid_end),
            month=first.month,
            label=first.strftime('%B %Y'),
            showing_today=(first.year, first.month) == (today.year, today.month),
            prev_url=_calendar_url('month', prev_month),
            next_url=_calendar_url('month', next_month),
            today_url=_calendar_url('month', today),
            week_url=_calendar_url('week', anchor if anchor.month == first.month else first),
            month_url=_calendar_url('month', anchor),
        )
    return render_template('junk/manage_calendar.html', **ctx)


# ─── job modal ───────────────────────────────────────────────────────────

@junk_bp.route('/manage/job/form')
@junk_manager_required
def job_form():
    """Modal contents (HTML fragment). ?id= edits a job; ?date= prefills a new one."""
    job = None
    prefill_date = None
    if request.args.get('id'):
        try:
            job = _get_job(int(request.args['id']))
        except ValueError:
            abort(404)
    else:
        try:
            prefill_date = parse_date(request.args.get('date'))
        except JobFormError:
            prefill_date = None
    return render_template(
        'junk/_job_form.html', job=job, prefill_date=prefill_date,
        return_to=request.args.get('return_to') or url_for('junk.manage'),
        field_labels=FIELD_LABELS, field_order=JOB_FIELDS, format_value=format_value,
    )


@junk_bp.route('/manage/job', methods=['POST'])
@junk_manager_required
def job_create():
    try:
        values = parse_job_form(request.form)
    except JobFormError as e:
        flash(str(e), 'error')
        return redirect(_safe_return())
    job = create_job(values, current_user)
    flash(f"{job.display_name} added.", 'success')
    return redirect(_safe_return())


@junk_bp.route('/manage/job/<int:job_id>', methods=['POST'])
@junk_manager_required
def job_update(job_id):
    job = _get_job(job_id)
    try:
        values = parse_job_form(request.form)
    except JobFormError as e:
        flash(str(e), 'error')
        return redirect(_safe_return())
    update_job(job, values, current_user)
    return redirect(_safe_return())


@junk_bp.route('/manage/job/<int:job_id>/done', methods=['POST'])
@junk_manager_required
def job_done(job_id):
    job = _get_job(job_id)
    try:
        if request.form.get('undo') == '1':
            undo_done(job, current_user)
        else:
            mark_done(job, current_user)
    except JobFormError as e:
        flash(str(e), 'error')
    return redirect(_safe_return())


@junk_bp.route('/manage/job/<int:job_id>/delete', methods=['POST'])
@junk_manager_required
def job_delete(job_id):
    """Permanent. The modal asks for confirmation first."""
    job = _get_job(job_id)
    name = job.display_name
    delete_job(job)
    flash(f"{name} deleted.", 'success')
    return redirect(_safe_return())


# ─── drag and drop ───────────────────────────────────────────────────────

@junk_bp.route('/manage/board/move', methods=['POST'])
@junk_manager_required
def board_move():
    data = request.get_json(silent=True) or {}
    try:
        job = db.session.get(Job, int(data.get('job_id')))
    except (TypeError, ValueError):
        job = None
    if job is None:
        return jsonify(ok=False, error='stale'), 409
    try:
        target = parse_date(data.get('date'))
        move_job(job, target, data.get('ordered_ids') or [], current_user)
    except (JobFormError, StaleBoard):
        return jsonify(ok=False, error='stale'), 409
    return jsonify(ok=True)
