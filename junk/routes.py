"""Junk removal routes: sign-in, calendar, job modal, drag-and-drop saves."""
import calendar as _calendar
import os
from collections import defaultdict
from datetime import timedelta

from flask import (abort, current_app, flash, get_flashed_messages, jsonify, redirect,
                   render_template, request, session, url_for)
from flask_login import current_user, login_user, logout_user
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.security import check_password_hash, generate_password_hash

from junk import junk_bp
from junk.auth import (has_junk_access, is_junk_crew, is_junk_manager, is_junk_only,
                       junk_crew_required, junk_home, junk_manager_required)
from junk.jobs import (
    JobFormError, StaleBoard,
    create_job, delete_job, format_money, mark_done, move_job, set_crew,
    parse_date, parse_job_form, parse_location, to_eastern, today_eastern, undo_done,
    unscheduled_query, update_job, week_start,
)
from junk.models import Job, JobAssignment, initials, person_name
from sqlalchemy.orm import joinedload, selectinload
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


@junk_bp.app_template_filter('jr_phone')
def _jr_phone(v):
    """(919) 555-0142 for a US number; anything else exactly as typed."""
    digits = ''.join(ch for ch in (v or '') if ch.isdigit())
    if len(digits) == 11 and digits[0] == '1':
        digits = digits[1:]
    if len(digits) == 10:
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    return v or ''


@junk_bp.app_template_filter('jr_initials')
def _jr_initials(user):
    return initials(user)


@junk_bp.app_template_filter('jr_person')
def _jr_person(user):
    return person_name(user)


@junk_bp.app_template_filter('jr_eastern')
def _jr_eastern(dt):
    local = to_eastern(dt)
    return local.strftime('%b %-d, %-I:%M %p') if local else ''


@junk_bp.context_processor
def _junk_context():
    return {'google_maps_key': os.environ.get('GOOGLE_MAPS_API_KEY', ''), 'jr_asset': _jr_asset,
            'jr_is_manager': is_junk_manager(), 'jr_is_crew': is_junk_crew(),
            'jr_dev_switch': dev_switch_enabled(), 'jr_dev_role': _dev_role()}


def _jr_asset(filename):
    """Static URL stamped with the file's mtime, so a deploy never runs against cached CSS/JS."""
    try:
        v = int(os.path.getmtime(os.path.join(junk_bp.static_folder, filename)))
    except OSError:
        v = 0
    return url_for('junk.static', filename=filename, v=v)


# ─── separation from the legacy site ─────────────────────────────────────

_JUNK_ONLY_ALLOWED = ('/junk', '/static/', '/favicon')

# While the site is locked, these stay reachable. Machines call them, not people: payment and
# SMS webhooks, Render cron jobs, photo URLs inside old emails, unsubscribe links, health checks.
_LOCK_OPEN = (
    '/junk', '/static/', '/uploads/', '/favicon', '/health',
    '/webhook', '/sms/webhook', '/admin/cron/', '/admin/digest/trigger', '/unsubscribe/',
)


def site_locked():
    """The legacy Campus Swap site is closed: every page sends people to the junk sign-in.
    On by default; SITE_LOCKED_TO_JUNK=0 reopens it. Nothing is deleted, only gated.
    Off under TESTING (legacy suites exercise those pages) unless a test turns it on."""
    if current_app.config.get('TESTING'):
        return bool(current_app.config.get('SITE_LOCKED_TO_JUNK'))
    return os.environ.get('SITE_LOCKED_TO_JUNK', '1').strip().lower() not in ('0', 'false', 'no')


def _is_legacy_admin(user):
    return bool(getattr(user, 'is_admin', False) or getattr(user, 'is_super_admin', False))


@junk_bp.before_app_request
def _gate_legacy_site():
    path = request.path

    # A junk-only account never sees the legacy site, locked or not.
    if current_user.is_authenticated and is_junk_only(current_user):
        if path == '/logout':
            return redirect(url_for('junk.logout'))
        if path.startswith(_JUNK_ONLY_ALLOWED):
            return None
        return redirect(junk_home())

    if not site_locked():
        return None
    if path == '/robots.txt':
        return current_app.response_class('User-agent: *\nDisallow: /\n', mimetype='text/plain')
    if path.startswith(_LOCK_OPEN):
        return None
    # Google sign-in only when it started on /junk/login; otherwise it would run the old
    # seller sign-up and create accounts.
    if path.startswith('/auth/google') and session.get(JUNK_OAUTH_FLAG):
        return None
    # Admins (Henry, Ben) keep the old site for wrap-up work: payouts, records.
    if current_user.is_authenticated and _is_legacy_admin(current_user):
        return None
    if path == '/logout':
        return redirect(url_for('junk.logout'))
    if has_junk_access():
        return redirect(junk_home())
    return redirect(url_for('junk.login'))


# ─── sign in / out ───────────────────────────────────────────────────────

def _safe_next(target):
    if target and target.startswith('/junk') and not target.startswith('//'):
        return target
    return junk_home()


@junk_bp.route('/')
def index():
    return redirect(junk_home() if has_junk_access() else url_for('junk.login'))


def _google_enabled():
    return bool(os.environ.get('GOOGLE_CLIENT_ID') and os.environ.get('GOOGLE_CLIENT_SECRET'))


def _find_user(email):
    email = (email or '').strip()
    return User.query.filter(db.func.lower(User.email) == email.lower()).first() if email else None


LAST_SIGNIN_COOKIE = 'jr_last_signin'


def _remember_method(response, method):
    """Which way this browser last got in, so the login page can say 'Last used'."""
    response.set_cookie(LAST_SIGNIN_COOKIE, method, max_age=60 * 60 * 24 * 365,
                        httponly=True, samesite='Lax', secure=request.is_secure)
    return response


def _render_login(email='', error=None, notice=None, status=200, no_password=False):
    # Messages handed over a redirect (from the Google callback or a reset link) arrive as flashes.
    for category, msg in get_flashed_messages(with_categories=True):
        if category == 'junk_error':
            error = error or msg
        elif category == 'junk_notice':
            notice = notice or msg
    last_used = request.cookies.get(LAST_SIGNIN_COOKIE)
    return render_template('junk/login.html', email=email, error=error, notice=notice,
                           google_enabled=_google_enabled(), no_password=no_password,
                           google_client_id=os.environ.get('GOOGLE_CLIENT_ID', '').strip(),
                           last_used=last_used if last_used in ('google', 'password') else None,
                           next_url=request.args.get('next', '')), status


@junk_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Two ways in, and both work for every manager: Google, or email + password. An account
    that has only ever used Google can set a password through the emailed link."""
    if has_junk_access():
        return redirect(junk_home())
    if request.method == 'GET':
        return _render_login()
    email = (request.form.get('email') or '').strip()
    password = request.form.get('password') or ''
    user = _find_user(email)
    if user and not user.password_hash:
        return _render_login(email, no_password=True, error=(
            "This account was set up with Google, so it doesn't have a password yet."))
    if not user or not check_password_hash(user.password_hash, password):
        return _render_login(email, error="That email and password don't match.")
    if not has_junk_access(user):
        return _render_login(email, error="This account doesn't have access yet.")
    login_user(user, remember=True)
    return _remember_method(redirect(_safe_next(request.args.get('next'))), 'password')


# ─── Google ──────────────────────────────────────────────────────────────
# Reuses the site's one Google OAuth client (/auth/google), so no new redirect URI is needed
# in Google Cloud. The flag in the session tells the shared callback to hand the result back
# here via finish_google_login() instead of running the seller sign-up flow.

JUNK_OAUTH_FLAG = 'junk_oauth_next'


@junk_bp.route('/login/google')
def login_google():
    if not _google_enabled():
        flash("Google sign-in isn't set up here. Use your email and password.", 'junk_error')
        return redirect(url_for('junk.login'))
    session[JUNK_OAUTH_FLAG] = _safe_next(request.args.get('next'))
    return redirect(url_for('auth_google'))


def _google_user(userinfo):
    """(user, None) for a manager or crew member Google vouches for, else (None, error message).
    Never creates an account: Google only gets you into an account that already has access."""
    email = (userinfo.get('email') or '').strip()
    if not email or userinfo.get('email_verified') is False:
        return None, "Google didn't confirm an email for that account."
    user = _find_user(email)
    if not user or not has_junk_access(user):
        return None, f"{email} doesn't have access yet."
    if not user.oauth_provider or not user.oauth_id:
        user.oauth_provider = 'google'
        user.oauth_id = userinfo.get('sub')
        db.session.commit()
    return user, None


def finish_google_login(userinfo, next_url):
    """Full-page fallback: called by app.auth_google_callback when the sign-in started on
    /junk/login (used if the popup can't run, e.g. Google's script didn't load)."""
    user, error = _google_user(userinfo)
    if error:
        flash(error, 'junk_error')
        return redirect(url_for('junk.login'))
    login_user(user, remember=True)
    return _remember_method(redirect(_safe_next(next_url)), 'google')


# Popup sign-in (the normal path): Google's script opens a small window over the login page and
# hands the page a one-time code; we trade it for the user's profile here. 'postmessage' is
# the redirect_uri Google requires for codes obtained this way. Needs this site listed under
# "Authorized JavaScript origins" on the OAuth client in Google Cloud.
_GOOGLE_TOKEN_URL = 'https://oauth2.googleapis.com/token'
_GOOGLE_USERINFO_URL = 'https://openidconnect.googleapis.com/v1/userinfo'


def _google_userinfo_from_code(code):
    import requests
    tok = requests.post(_GOOGLE_TOKEN_URL, timeout=10, data={
        'code': code,
        'client_id': os.environ.get('GOOGLE_CLIENT_ID', '').strip(),
        'client_secret': os.environ.get('GOOGLE_CLIENT_SECRET', '').strip(),
        'redirect_uri': 'postmessage',
        'grant_type': 'authorization_code',
    })
    tok.raise_for_status()
    access_token = tok.json()['access_token']
    info = requests.get(_GOOGLE_USERINFO_URL, timeout=10,
                        headers={'Authorization': f'Bearer {access_token}'})
    info.raise_for_status()
    return info.json()


@junk_bp.route('/login/google/code', methods=['POST'])
def login_google_code():
    if not _google_enabled():
        return jsonify(ok=False, error="Google sign-in isn't set up here."), 400
    data = request.get_json(silent=True) or {}
    code = data.get('code')
    if not code or not isinstance(code, str):
        return jsonify(ok=False, error="Google sign-in didn't go through. Try again."), 400
    try:
        userinfo = _google_userinfo_from_code(code)
    except Exception:
        current_app.logger.exception('junk: Google code exchange failed')
        return jsonify(ok=False, error="Google sign-in didn't go through. Try again, or use your password."), 502
    user, error = _google_user(userinfo)
    if error:
        return jsonify(ok=False, error=error), 403
    login_user(user, remember=True)
    return _remember_method(jsonify(ok=True, redirect=_safe_next(data.get('next'))), 'google')


# ─── set a password by email link ────────────────────────────────────────
# One link covers "forgot my password" and "I've only ever used Google". It expires after an
# hour and stops working once used: it's signed over the current password hash, so setting a
# password invalidates it.

_LINK_MAX_AGE = 60 * 60
_MIN_PASSWORD = 8


def _link_serializer():
    return URLSafeTimedSerializer(current_app.secret_key, salt='junk-set-password')


def _hash_tag(user):
    return (user.password_hash or '')[-16:]


def make_password_link(user):
    token = _link_serializer().dumps({'u': user.id, 'h': _hash_tag(user)})
    return url_for('junk.password_set', token=token, _external=True)


def _user_from_link(token):
    try:
        data = _link_serializer().loads(token, max_age=_LINK_MAX_AGE)
    except (SignatureExpired, BadSignature):
        return None
    user = db.session.get(User, data.get('u')) if isinstance(data, dict) else None
    if not user or data.get('h') != _hash_tag(user) or not has_junk_access(user):
        return None
    return user


@junk_bp.route('/login/password', methods=['GET', 'POST'])
def password_request():
    """Ask for a set-password link. Same answer whether or not the email has an account."""
    email = (request.args.get('email') or '').strip()
    if request.method == 'POST':
        email = (request.form.get('email') or '').strip()
        user = _find_user(email)
        if user and has_junk_access(user):
            link = make_password_link(user)
            if current_app.debug:  # dev mail is suppressed (logged, not sent): print the link
                current_app.logger.warning('junk: set-password link for %s: %s', user.email, link)
            send = current_app.extensions.get('junk_send_email')
            name = (user.full_name or '').split(' ')[0] or 'there'
            html = render_template('junk/email_password_link.html', name=name, link=link)
            sent = False
            try:
                sent = bool(send and send(user.email, 'Set your password', html))
            except Exception:
                current_app.logger.exception('junk: password link email failed for user %s', user.id)
            if not sent:
                current_app.logger.warning('junk: password link not sent for user %s', user.id)
        return render_template('junk/password_request.html', email=email, sent=True)
    return render_template('junk/password_request.html', email=email, sent=False)


@junk_bp.route('/login/password/<token>', methods=['GET', 'POST'])
def password_set(token):
    user = _user_from_link(token)
    if not user:
        flash("That link has expired or was already used. Send yourself a new one.", 'junk_error')
        return redirect(url_for('junk.password_request'))
    error = None
    if request.method == 'POST':
        password = request.form.get('password') or ''
        if len(password) < _MIN_PASSWORD:
            error = f"Use at least {_MIN_PASSWORD} characters."
        elif password != (request.form.get('confirm') or ''):
            error = "Those passwords don't match."
        else:
            user.password_hash = generate_password_hash(password)
            db.session.commit()
            login_user(user, remember=True)
            return _remember_method(redirect(junk_home(user)), 'password')
    return render_template('junk/password_set.html', user=user, error=error)


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


def _week_label_short(start):
    """Phone toolbar: Nov 16–22 / Nov 30–Dec 6."""
    end = start + timedelta(days=6)
    tail = str(end.day) if start.month == end.month else end.strftime('%b %-d')
    return f"{start.strftime('%b %-d')}\u2013{tail}"


# Cards show their crew's initials: load assignments + people in one go, not one query per card.
_WITH_CREW = selectinload(Job.assignments).joinedload(JobAssignment.user)


def _jobs_by_day(first, last):
    """{date: [jobs in line order]}. Done jobs keep their place."""
    rows = (Job.query.options(_WITH_CREW)
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

    unscheduled = unscheduled_query().options(_WITH_CREW).all()

    ctx = dict(view=view, today=today, anchor=anchor, unscheduled=unscheduled,
               return_to=_calendar_url(view, anchor))

    if view == 'week':
        start = week_start(anchor)
        days = [start + timedelta(days=i) for i in range(7)]
        ctx.update(
            days=days,
            jobs=_jobs_by_day(days[0], days[-1]),
            label=_week_label(start),
            label_short=_week_label_short(start),
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
            label_short=first.strftime('%b %Y'),
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
        'junk/_job_form.html', job=job, prefill_date=prefill_date, team=_team(),
        return_to=request.args.get('return_to') or url_for('junk.manage'),
    )


@junk_bp.route('/manage/job', methods=['POST'])
@junk_manager_required
def job_create():
    try:
        values = parse_job_form(request.form)
    except JobFormError as e:
        flash(str(e), 'error')
        return redirect(_safe_return())
    job = create_job(values, current_user, parse_location(request.form, values['address']))
    flash(f"{job.display_name} added.", 'success')
    return redirect(_safe_return())


@junk_bp.route('/manage/job/<int:job_id>', methods=['POST'])
@junk_manager_required
def job_update(job_id):
    """The modal autosaves here (X-Autosave: 1 → JSON). A plain form post redirects back."""
    job = _get_job(job_id)
    autosave = request.headers.get('X-Autosave') == '1'
    try:
        values = parse_job_form(request.form)
    except JobFormError as e:
        if autosave:
            return jsonify(ok=False, error=str(e)), 400
        flash(str(e), 'error')
        return redirect(_safe_return())
    update_job(job, values, current_user, parse_location(request.form, values['address']))
    if autosave:
        return jsonify(ok=True)
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


@junk_bp.route('/manage/job/<int:job_id>/crew', methods=['POST'])
@junk_manager_required
def job_crew(job_id):
    """Add or remove one person: JSON {user_id, action: 'add' | 'remove'}. Answers with the
    modal's crew section, re-rendered, so the modal and the drag code share one route."""
    job = _get_job(job_id)
    data = request.get_json(silent=True) or {}
    try:
        person = db.session.get(User, int(data.get('user_id')))
    except (TypeError, ValueError):
        person = None
    action = data.get('action')
    if person is None or action not in ('add', 'remove'):
        return jsonify(ok=False, error="That didn't work. Refresh and try again."), 400
    try:
        set_crew(job, person, current_user, on=(action == 'add'))
    except JobFormError as e:
        return jsonify(ok=False, error=str(e)), 400
    return jsonify(ok=True, html=render_template('junk/_job_crew.html', job=job, team=_team()))


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


# ─── team ────────────────────────────────────────────────────────────────

def _team():
    """Everyone with junk access: managers first, then crew, each by name."""
    people = (User.query
              .filter(db.or_(User.is_junk_manager.is_(True), User.is_junk_crew.is_(True),
                             User.is_super_admin.is_(True)))
              .all())
    return sorted(people, key=lambda u: (not is_junk_manager(u),
                                         (u.full_name or u.email or '').lower()))


@junk_bp.route('/manage/team')
@junk_manager_required
def team():
    return render_template('junk/manage_team.html', people=_team(),
                           adding=request.args.get('add') == '1')


@junk_bp.route('/manage/team/add', methods=['POST'])
@junk_manager_required
def team_add():
    """Give an email crew access. Creates the account (no password) if there isn't one.
    Nothing is sent: they sign in with Google, or set a password from the sign-in page."""
    email = (request.form.get('email') or '').strip()
    name = (request.form.get('name') or '').strip()[:100]
    phone = (request.form.get('phone') or '').strip()[:20]
    if '@' not in email or ' ' in email or len(email) > 120:
        flash("Enter an email address.", 'error')
        return redirect(url_for('junk.team', add=1))
    user = _find_user(email)
    if user and user.is_junk_crew:
        flash(f"{user.full_name or user.email} is already crew.", 'error')
        return redirect(url_for('junk.team', add=1))
    if user is None:
        user = User(email=email.lower())
        db.session.add(user)
    user.is_junk_crew = True
    if name and not user.full_name:
        user.full_name = name
    if phone and not user.phone:
        user.phone = phone
    db.session.commit()
    flash(f"{user.full_name or user.email} added to crew.", 'success')
    return redirect(url_for('junk.team'))


@junk_bp.route('/manage/team/<int:user_id>/remove', methods=['POST'])
@junk_manager_required
def team_remove(user_id):
    """Takes away crew access. Never deletes the account."""
    user = db.session.get(User, user_id)
    if user is None or not user.is_junk_crew:
        abort(404)
    user.is_junk_crew = False
    db.session.commit()
    flash(f"{user.full_name or user.email} removed from crew.", 'success')
    return redirect(url_for('junk.team'))


# ─── crew ────────────────────────────────────────────────────────────────

@junk_bp.route('/crew')
@junk_crew_required
def crew_home():
    """The crew side of the portal. Empty until jobs can be assigned to crew."""
    return render_template('junk/crew_home.html')


# ─── dev-only role switch ────────────────────────────────────────────────
# One click to become the dev manager or the dev crew member, so both sides can be checked
# side by side. Only on a local debug server: never on Render, never under tests unless a test
# turns it on. The two accounts are created on first use, in the local database only.

DEV_ACCOUNTS = {
    'manager': ('junk-dev@example.com', 'Manager (dev)', {'is_junk_manager': True}),
    'crew': ('junk-crew-dev@example.com', 'Crew (dev)', {'is_junk_crew': True}),
}
DEV_PASSWORD = 'junkdev123'


def dev_switch_enabled():
    if 'JUNK_DEV_SWITCH' in current_app.config:
        return bool(current_app.config['JUNK_DEV_SWITCH'])
    if current_app.config.get('TESTING') or os.environ.get('RENDER'):
        return False
    return bool(current_app.debug)


def _dev_role():
    """'manager' / 'crew' when signed in as one of the dev accounts, else None."""
    if not current_user.is_authenticated:
        return None
    email = (current_user.email or '').lower()
    return next((role for role, (e, _, _) in DEV_ACCOUNTS.items() if e == email), None)


def _dev_account(role):
    email, name, flags = DEV_ACCOUNTS[role]
    user = _find_user(email)
    if user is None:
        user = User(email=email, full_name=name, password_hash=generate_password_hash(DEV_PASSWORD))
        db.session.add(user)
    user.full_name = name  # the top bar shows the first word: "Manager" / "Crew"
    for flag, value in flags.items():
        setattr(user, flag, value)
    db.session.commit()
    return user


@junk_bp.route('/dev/as/<role>', methods=['POST'])
def dev_switch(role):
    if not dev_switch_enabled() or role not in DEV_ACCOUNTS:
        abort(404)
    user = _dev_account(role)
    logout_user()
    login_user(user, remember=True)
    return redirect(junk_home(user))
