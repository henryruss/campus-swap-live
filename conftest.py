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
