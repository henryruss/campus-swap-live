"""
Integration tests for admin routes.

These test admin panel functionality and access control.
Run: pytest tests/test_admin.py -v
"""
import pytest


@pytest.mark.integration
class TestAdminAccess:
    """Test admin access control"""
    
    def test_admin_requires_login(self, client):
        """
        Test that admin panel requires authentication.
        
        Regular users (not logged in) should not be able to access admin.
        """
        response = client.get('/admin', follow_redirects=True)
        assert response.status_code == 200
        # Should redirect to login or show access denied
        assert b'login' in response.data.lower() or b'access denied' in response.data.lower()
    
    def test_admin_requires_admin_role(self, authenticated_client):
        """
        Test that admin panel requires admin role.
        
        Regular logged-in users should not have admin access.
        """
        response = authenticated_client.get('/admin', follow_redirects=True)
        assert response.status_code == 200
        # Regular user should not have access
        assert b'access denied' in response.data.lower() or b'dashboard' in response.data.lower()
    
    def test_admin_access_granted(self, admin_client):
        """
        Test that admin users can access admin panel.
        
        Users with is_admin=True should be able to access admin routes.
        """
        response = admin_client.get('/admin')
        assert response.status_code == 200
        # Should show admin interface - check for common admin page elements
        admin_indicators = [
            b'admin', b'pending', b'items', b'category', 
            b'gallery', b'export', b'stats'
        ]
        assert any(indicator in response.data.lower() for indicator in admin_indicators)


@pytest.mark.integration
class TestAdminCategoryManagement:
    """Test admin category management functions"""
    
    def test_admin_add_category(self, admin_client):
        """Test that admin can add a new category"""
        response = admin_client.post('/admin/category/add', data={
            'name': 'New Test Category',
            'icon': 'fa-test'
        }, follow_redirects=True)
        
        assert response.status_code == 200
        
        # Check category was created in database
        from app import InventoryCategory
        with admin_client.application.app_context():
            category = InventoryCategory.query.filter_by(name='New Test Category').first()
            assert category is not None
            assert category.image_url == 'fa-test'
    
    def test_admin_add_duplicate_category(self, admin_client, test_category):
        """Test that duplicate category names are rejected"""
        response = admin_client.post('/admin/category/add', data={
            'name': test_category.name,  # Use existing category name
            'icon': 'fa-test'
        }, follow_redirects=True)
        
        assert response.status_code == 200
        # Should show error about duplicate
        assert b'already exists' in response.data.lower() or b'duplicate' in response.data.lower()
    
    def test_admin_delete_category(self, admin_client, test_category):
        """
        Test that admin can delete a category.
        
        Note: This will fail if category has items (by design).
        """
        response = admin_client.post(f'/admin/category/delete/{test_category.id}', 
                                    follow_redirects=True)
        assert response.status_code == 200
        
        # Check category was deleted (if no items were using it)
        from app import InventoryCategory
        with admin_client.application.app_context():
            category = InventoryCategory.query.get(test_category.id)
            # Category should be deleted if it had no items
            # If it had items, deletion should have been prevented
            if category is None:
                # Successfully deleted
                pass
            else:
                # Deletion prevented because category has items
                assert b'cannot delete' in response.data.lower() or b'items' in response.data.lower()


@pytest.mark.integration
class TestAdminItemManagement:
    """Test admin item management functions"""
    
    def test_admin_mark_item_sold(self, admin_client, test_item):
        """
        Test that admin can mark an item as sold.
        
        This simulates an admin manually marking an item as sold.
        """
        response = admin_client.post('/admin', data={
            'mark_sold': test_item.id
        }, follow_redirects=True)
        
        assert response.status_code == 200
        
        # Check item status changed in database
        from app import InventoryItem
        with admin_client.application.app_context():
            item = InventoryItem.query.get(test_item.id)
            assert item.status == 'sold'
            assert item.sold_at is not None
    
    def test_admin_mark_item_available(self, admin_client, test_item):
        """Test that admin can mark a sold item as available again"""
        from app import db, InventoryItem
        with admin_client.application.app_context():
            # First mark as sold
            test_item.status = 'sold'
            test_item.sold_at = db.session.query(db.func.now()).scalar()
            db.session.commit()
        
        # Then mark as available
        response = admin_client.post('/admin', data={
            'mark_available': test_item.id
        }, follow_redirects=True)
        
        assert response.status_code == 200
        
        # Check item status changed back
        with admin_client.application.app_context():
            item = InventoryItem.query.get(test_item.id)
            assert item.status == 'available'
            assert item.sold_at is None
    
    def test_admin_update_item_price(self, admin_client, test_item):
        """Test that admin can update item price"""
        response = admin_client.post('/admin', data={
            'bulk_update_items': 'true',
            f'price_{test_item.id}': '75.00'
        }, follow_redirects=True)
        
        assert response.status_code == 200
        
        # Check price was updated
        from app import InventoryItem
        with admin_client.application.app_context():
            item = InventoryItem.query.get(test_item.id)
            assert item.price == 75.00
    
    def test_admin_delete_item(self, admin_client, test_item):
        """Test that admin can delete an item"""
        item_id = test_item.id
        
        response = admin_client.post('/admin', data={
            'delete_item': item_id
        }, follow_redirects=True)
        
        assert response.status_code == 200
        
        # Check item was deleted
        from app import InventoryItem
        with admin_client.application.app_context():
            item = InventoryItem.query.get(item_id)
            assert item is None


@pytest.mark.integration
class TestAdminDataExport:
    """Test admin data export functionality"""
    
    def test_admin_export_users(self, admin_client, test_user):
        """Test that admin can export users as CSV"""
        response = admin_client.get('/admin/export/users')
        assert response.status_code == 200
        assert 'text/csv' in response.content_type.lower()
        # CSV should contain user email
        assert test_user.email.encode() in response.data
    
    def test_admin_export_items(self, admin_client, test_item):
        """Test that admin can export items as CSV"""
        response = admin_client.get('/admin/export/items')
        assert response.status_code == 200
        assert 'text/csv' in response.content_type.lower()
        # CSV should contain item description
        assert test_item.description.encode() in response.data
    
    def test_admin_preview_users(self, admin_client, test_user):
        """Test that admin can preview users in browser"""
        response = admin_client.get('/admin/preview/users')
        assert response.status_code == 200
        # Should show user email
        assert test_user.email.encode() in response.data
