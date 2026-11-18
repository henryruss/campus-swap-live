"""Junk removal — internal tools.

A self-contained Flask Blueprint mounted at /junk. Reuses only shared infrastructure
(db, User, Flask-Login, CSRF). Nothing here imports from app.py.

Spec: feature_junk_calendar.md
"""
from flask import Blueprint

junk_bp = Blueprint(
    'junk', __name__,
    url_prefix='/junk',
    template_folder='templates',
    static_folder='static',
    static_url_path='/static',
)

from junk import models  # noqa: E402,F401  (register tables with SQLAlchemy / Alembic)
from junk import routes  # noqa: E402,F401
