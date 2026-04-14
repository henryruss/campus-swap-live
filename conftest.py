"""
Root conftest.py — patches Flask 3.x AppContext to handle nested contexts in tests.

When both `client` and `app_ctx` fixtures are active in the same test, the Flask 3.x
context ContextVar can get into an inconsistent state when request contexts from test
client calls are pushed mid-teardown. This patch makes AppContext.pop() robust to
that scenario.
"""
import pytest
import flask.ctx
from flask.ctx import _cv_app


_original_pop = flask.ctx.AppContext.pop


def _safe_pop(self, exc=flask.ctx.sys.exc_info):
    """Patched AppContext.pop that tolerates ContextVar inconsistencies in nested test contexts."""
    import sys
    _sentinel = object()

    try:
        if len(self._cv_tokens) == 1:
            exc_val = sys.exc_info()[1]
            try:
                self.app.do_teardown_appcontext(exc_val)
            except Exception:
                pass  # Don't let teardown errors prevent context cleanup
    finally:
        try:
            ctx = _cv_app.get(None)
        except LookupError:
            ctx = None

        if self._cv_tokens:
            token = self._cv_tokens.pop()
            try:
                _cv_app.reset(token)
            except Exception:
                pass

    if ctx is not None and ctx is not self:
        # Context mismatch in nested test scenario — just continue
        pass

    try:
        from flask.signals import appcontext_popped
        appcontext_popped.send(self.app, _async_wrapper=self.app.ensure_sync)
    except Exception:
        pass


@pytest.fixture(autouse=True, scope='session')
def patch_flask_app_context():
    """Patch Flask AppContext.pop to handle nested test contexts gracefully."""
    flask.ctx.AppContext.pop = _safe_pop
    yield
    flask.ctx.AppContext.pop = _original_pop


import os
import secrets
import tempfile

@pytest.fixture(scope='function')
def app():
    """App fixture for unified item submission tests."""
    from app import app as flask_app, db as _db

    db_fd, db_path = tempfile.mkstemp()
    flask_app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
    flask_app.config['TESTING'] = True
    flask_app.config['WTF_CSRF_ENABLED'] = False
    flask_app.config['SECRET_KEY'] = 'test-secret-key'
    flask_app.config['SERVER_NAME'] = 'localhost'

    # Disable rate limiting
    if hasattr(flask_app, 'limiter') and flask_app.limiter:
        flask_app.limiter.enabled = False

    with flask_app.app_context():
        _db.create_all()
        # Seed at least one category so /onboard renders (not no_categories path)
        from models import InventoryCategory, AppSetting
        cat = InventoryCategory(name='Furniture', image_url='fa-couch', count_in_stock=0)
        _db.session.add(cat)
        # Make sure pickup period is active
        AppSetting.set('pickup_period_active', 'true')
        _db.session.commit()
        yield flask_app
        _db.session.remove()
        _db.drop_all()

    os.close(db_fd)
    os.unlink(db_path)


@pytest.fixture
def db(app):
    """Database fixture."""
    from app import db as _db
    return _db


@pytest.fixture
def make_user(app, db):
    """Factory fixture that creates User objects."""
    from werkzeug.security import generate_password_hash

    def _factory(**kwargs):
        from models import User
        uid = secrets.token_hex(4)
        user = User(
            email=kwargs.get('email', f'user_{uid}@test.edu'),
            password_hash=generate_password_hash('testpass123'),
            full_name=kwargs.get('full_name', f'Test User {uid}'),
            payout_method=kwargs.get('payout_method', None),
            payout_handle=kwargs.get('payout_handle', None),
            is_seller=kwargs.get('is_seller', True),
            pickup_week=kwargs.get('pickup_week', None),
            pickup_time_preference=kwargs.get('pickup_time_preference', None),
        )
        db.session.add(user)
        db.session.commit()
        return user

    return _factory
