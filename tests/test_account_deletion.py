"""
Tests for account and item deletion flows.

Covers:
  - Admin deletes another user's item via /admin/item/<id>/delete
  - Admin deletes a user account via /admin/user/delete/<id>
  - User self-deletes via POST /account/delete
  - Authorization guards on all three paths

Run: pytest tests/test_account_deletion.py -v
"""
import pytest
from app import app as _app, db
from models import User, InventoryItem, InventoryCategory, AppSetting, UploadSession
from werkzeug.security import generate_password_hash


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def category(client):
    with _app.app_context():
        cat = InventoryCategory(name='Electronics', image_url='fa-laptop', count_in_stock=2)
        db.session.add(cat)
        db.session.commit()
        _ = cat.id, cat.name, cat.count_in_stock
        return cat


@pytest.fixture
def seller(client):
    with _app.app_context():
        u = User(
            email='seller@test.edu',
            password_hash=generate_password_hash('pass123'),
            full_name='Seller User',
            is_seller=True,
            has_paid=True,
        )
        db.session.add(u)
        db.session.commit()
        _ = u.id, u.email, u.full_name
        return u


@pytest.fixture
def seller_item(client, seller, category):
    with _app.app_context():
        item = InventoryItem(
            description='Old Laptop',
            price=200.0,
            status='available',
            category_id=category.id,
            seller_id=seller.id,
            collection_method='online',
            photo_url=None,
        )
        db.session.add(item)
        # Sync count_in_stock
        cat = InventoryCategory.query.get(category.id)
        cat.count_in_stock = 1
        db.session.commit()
        _ = item.id, item.status, item.category_id
        return item


@pytest.fixture
def super_admin(client):
    with _app.app_context():
        u = User(
            email='superadmin@test.edu',
            password_hash=generate_password_hash('adminpass'),
            full_name='Super Admin',
            is_admin=True,
            is_super_admin=True,
            is_seller=True,
            has_paid=True,
        )
        db.session.add(u)
        db.session.commit()
        _ = u.id, u.email, u.is_admin, u.is_super_admin
        return u


@pytest.fixture
def admin_client(client, super_admin):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(super_admin.id)
        sess['_fresh'] = True
    return client


@pytest.fixture
def seller_client(client, seller):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(seller.id)
        sess['_fresh'] = True
    return client


# ── admin item deletion ───────────────────────────────────────────────────────

class TestAdminDeleteItem:

    def test_admin_can_delete_item(self, admin_client, seller_item, category):
        item_id = seller_item.id
        cat_id = category.id

        resp = admin_client.post(f'/admin/item/{item_id}/delete')
        assert resp.status_code in (302, 200)

        with _app.app_context():
            assert InventoryItem.query.get(item_id) is None
            # count_in_stock should have decremented
            cat = InventoryCategory.query.get(cat_id)
            assert cat.count_in_stock == 0

    def test_admin_delete_item_not_found_redirects(self, admin_client):
        resp = admin_client.post('/admin/item/99999/delete')
        assert resp.status_code in (302, 404)

    def test_non_admin_cannot_delete_item(self, seller_client, seller_item):
        item_id = seller_item.id
        resp = seller_client.post(f'/admin/item/{item_id}/delete', follow_redirects=True)
        assert resp.status_code == 200
        # Item should still exist
        with _app.app_context():
            assert InventoryItem.query.get(item_id) is not None

    def test_unauthenticated_cannot_delete_item(self, client, seller_item):
        item_id = seller_item.id
        resp = client.post(f'/admin/item/{item_id}/delete', follow_redirects=True)
        assert resp.status_code == 200
        with _app.app_context():
            assert InventoryItem.query.get(item_id) is not None

    def test_delete_item_flashes_success(self, admin_client, seller_item):
        resp = admin_client.post(
            f'/admin/item/{seller_item.id}/delete',
            follow_redirects=True
        )
        assert b'deleted' in resp.data.lower()


# ── admin user deletion ───────────────────────────────────────────────────────

class TestAdminDeleteUser:

    def test_admin_can_delete_seller(self, admin_client, seller, seller_item):
        user_id = seller.id
        item_id = seller_item.id

        resp = admin_client.post(f'/admin/user/delete/{user_id}')
        assert resp.status_code in (302, 200)

        with _app.app_context():
            assert User.query.get(user_id) is None
            assert InventoryItem.query.get(item_id) is None

    def test_admin_cannot_delete_self(self, admin_client, super_admin):
        admin_id = super_admin.id
        resp = admin_client.post(f'/admin/user/delete/{admin_id}', follow_redirects=True)
        assert resp.status_code == 200
        assert b'cannot delete your own' in resp.data.lower()
        with _app.app_context():
            assert User.query.get(admin_id) is not None

    def test_admin_cannot_delete_last_admin(self, admin_client, super_admin):
        """Deleting the only admin account should be blocked."""
        admin_id = super_admin.id
        resp = admin_client.post(f'/admin/user/delete/{admin_id}', follow_redirects=True)
        assert resp.status_code == 200
        with _app.app_context():
            assert User.query.get(admin_id) is not None

    def test_non_admin_cannot_delete_user(self, seller_client, seller):
        user_id = seller.id
        resp = seller_client.post(f'/admin/user/delete/{user_id}', follow_redirects=True)
        assert resp.status_code in (200, 403)
        with _app.app_context():
            assert User.query.get(user_id) is not None

    def test_delete_nonexistent_user_redirects(self, admin_client):
        resp = admin_client.post('/admin/user/delete/99999')
        assert resp.status_code in (302, 404)

    def test_admin_delete_user_removes_upload_sessions(self, admin_client, seller):
        user_id = seller.id
        with _app.app_context():
            sess = UploadSession(session_token='test-token-abc', user_id=user_id)
            db.session.add(sess)
            db.session.commit()

        admin_client.post(f'/admin/user/delete/{user_id}')

        with _app.app_context():
            assert UploadSession.query.filter_by(user_id=user_id).count() == 0

    def test_admin_delete_user_flashes_success(self, admin_client, seller):
        resp = admin_client.post(
            f'/admin/user/delete/{seller.id}',
            follow_redirects=True
        )
        assert b'deleted' in resp.data.lower()


# ── user self-deletion ────────────────────────────────────────────────────────

class TestSelfDeleteAccount:

    def test_seller_can_delete_own_account(self, seller_client, seller):
        user_id = seller.id
        resp = seller_client.post('/account/delete')
        assert resp.status_code in (302, 200)
        with _app.app_context():
            assert User.query.get(user_id) is None

    def test_self_delete_removes_items(self, seller_client, seller, seller_item):
        user_id = seller.id
        item_id = seller_item.id
        seller_client.post('/account/delete')
        with _app.app_context():
            assert User.query.get(user_id) is None
            assert InventoryItem.query.get(item_id) is None

    def test_self_delete_logs_user_out(self, seller_client, seller):
        seller_client.post('/account/delete')
        # After deletion, accessing a protected page should redirect to login
        resp = seller_client.get('/dashboard', follow_redirects=True)
        assert b'login' in resp.data.lower() or resp.request.path == '/login'

    def test_self_delete_redirects_to_index(self, seller_client, seller):
        resp = seller_client.post('/account/delete', follow_redirects=False)
        assert resp.status_code == 302
        assert '/' in resp.headers.get('Location', '')

    def test_unauthenticated_cannot_self_delete(self, client):
        resp = client.post('/account/delete', follow_redirects=True)
        assert resp.status_code == 200
        assert b'login' in resp.data.lower()

    def test_admin_self_delete_blocked(self, admin_client, super_admin):
        admin_id = super_admin.id
        resp = admin_client.post('/account/delete', follow_redirects=True)
        assert resp.status_code == 200
        assert b'admin' in resp.data.lower()
        with _app.app_context():
            assert User.query.get(admin_id) is not None

    def test_self_delete_decrements_stock_count(self, seller_client, seller, seller_item, category):
        cat_id = category.id
        seller_client.post('/account/delete')
        with _app.app_context():
            cat = InventoryCategory.query.get(cat_id)
            assert cat.count_in_stock == 0

    def test_self_delete_flashes_success(self, seller_client, seller):
        resp = seller_client.post('/account/delete', follow_redirects=True)
        assert b'deleted' in resp.data.lower()
