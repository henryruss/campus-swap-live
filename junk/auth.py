"""Access guards for the junk removal portal.

Two roles, both User flags, and a user can hold both:
- manager (is_junk_manager, or super admin): the calendar at /junk/manage
- crew (is_junk_crew): the crew home at /junk/crew
"""
from functools import wraps

from flask import abort, jsonify, redirect, request, url_for
from flask_login import current_user


def _user(user):
    user = user or current_user
    return user if (user and user.is_authenticated) else None


def is_junk_manager(user=None):
    """Junk managers and super admins. Everyone who passes has the same permissions."""
    user = _user(user)
    return bool(user and (getattr(user, 'is_junk_manager', False)
                          or getattr(user, 'is_super_admin', False)))


def is_junk_crew(user=None):
    user = _user(user)
    return bool(user and getattr(user, 'is_junk_crew', False))


def has_junk_access(user=None):
    return is_junk_manager(user) or is_junk_crew(user)


def is_junk_only(user=None):
    """A junk manager or crew member with no legacy role. Confined to /junk — never sees the old site."""
    user = _user(user)
    return bool(user
                and (getattr(user, 'is_junk_manager', False) or getattr(user, 'is_junk_crew', False))
                and not getattr(user, 'is_admin', False)
                and not getattr(user, 'is_super_admin', False)
                and not getattr(user, 'is_campus_director', False))


def junk_home(user=None):
    """Where this user lands: managers on the calendar, crew on the crew home."""
    return url_for('junk.manage') if is_junk_manager(user) else url_for('junk.crew_home')


def _guard(allowed):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                if request.is_json:
                    return jsonify(ok=False, error='login'), 401
                return redirect(url_for('junk.login', next=request.full_path.rstrip('?')))
            if not allowed():
                # Signed in to the other side of the portal: send them home rather than a 403.
                if has_junk_access() and not request.is_json and request.method == 'GET':
                    return redirect(junk_home())
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator


junk_manager_required = _guard(is_junk_manager)
# Managers pass too, so they can see what crew see.
junk_crew_required = _guard(has_junk_access)
