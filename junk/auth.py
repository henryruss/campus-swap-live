"""Access guards for the junk removal portal."""
from functools import wraps

from flask import abort, jsonify, redirect, request, url_for
from flask_login import current_user


def is_junk_manager(user=None):
    """Junk managers and super admins. Everyone who passes has the same permissions."""
    user = user or current_user
    return bool(user and user.is_authenticated and (
        getattr(user, 'is_junk_manager', False) or getattr(user, 'is_super_admin', False)
    ))


def is_junk_only(user=None):
    """A junk manager with no legacy role. Confined to /junk — never sees the old site."""
    user = user or current_user
    return bool(user and user.is_authenticated
                and getattr(user, 'is_junk_manager', False)
                and not getattr(user, 'is_admin', False)
                and not getattr(user, 'is_super_admin', False)
                and not getattr(user, 'is_campus_director', False))


def junk_manager_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            if request.is_json:
                return jsonify(ok=False, error='login'), 401
            return redirect(url_for('junk.login', next=request.full_path.rstrip('?')))
        if not is_junk_manager():
            abort(403)
        return view(*args, **kwargs)
    return wrapped
