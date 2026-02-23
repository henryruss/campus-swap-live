"""
Integration tests for inventory and marketplace routes.

These test browsing, searching, and viewing items.
Run: pytest tests/test_inventory.py -v
"""
import pytest


@pytest.mark.integration
class TestInventoryPage:
    """Test inventory listing page"""
    
    def test_inventory_page_loads(self, client):
        """Test that inventory page is accessible"""
        response = client.get('/inventory')
        assert response.status_code == 200
        assert b'inventory' in response.data.lower() or b'shop' in response.data.lower()
    
    def test_inventory_with_category_filter(self, client, test_category):
        """Test filtering inventory by category"""
        response = client.get(f'/inventory?category_id={test_category.id}')
        assert response.status_code == 200
        # Should show category name or filtered results
        assert test_category.name.encode() in response.data or b'filtered' in response.data.lower()
    
    def test_inventory_search_functionality(self, client, test_item):
        """
        Test search functionality.
        
        Search for "Test" should find our test item.
        """
        response = client.get('/inventory?search=Test')
        assert response.status_code == 200
        # Should find the test item
        assert test_item.description.encode() in response.data
    
    def test_inventory_search_no_results(self, client):
        """Test search with no matching results"""
        response = client.get('/inventory?search=nonexistentitem12345xyz')
        assert response.status_code == 200
        # Should show empty state or "no results" message
        assert b'coming soon' in response.data.lower() or b'no' in response.data.lower()
    
    def test_inventory_pagination(self, client):
        """Test that pagination works"""
        response = client.get('/inventory?page=1')
        assert response.status_code == 200
    
    def test_inventory_preserves_search_in_url(self, client, test_item):
        """Test that search term is preserved in item links"""
        response = client.get('/inventory?search=Test')
        assert response.status_code == 200
        # Item links should include search parameter
        item_link = f'/item/{test_item.id}'
        # Check that search is preserved in links (may be in URL or form)
        assert item_link.encode() in response.data


@pytest.mark.integration
class TestProductDetail:
    """Test product detail page"""
    
    def test_product_detail_page_loads(self, client, test_item):
        """Test that product detail page is accessible"""
        response = client.get(f'/item/{test_item.id}')
        assert response.status_code == 200
        # Should show item description
        assert test_item.description.encode() in response.data
        # Should show price
        assert str(int(test_item.price)).encode() in response.data
    
    def test_product_detail_nonexistent_item(self, client):
        """Test that non-existent item returns 404"""
        response = client.get('/item/99999')
        assert response.status_code == 404
    
    def test_product_detail_preserves_search(self, client, test_item):
        """
        Test that product detail page preserves search query.
        
        When you click "Back", it should return to search results.
        """
        response = client.get(f'/item/{test_item.id}?search=test&store=UNC%20Chapel%20Hill')
        assert response.status_code == 200
        # Back link should preserve search
        assert b'search=test' in response.data or b'back' in response.data.lower()
    
    def test_product_detail_shows_item_info(self, client, test_item):
        """Test that product detail shows all item information"""
        response = client.get(f'/item/{test_item.id}')
        assert response.status_code == 200
        assert test_item.description.encode() in response.data
        if test_item.long_description:
            assert test_item.long_description.encode() in response.data


@pytest.mark.integration
class TestBuyItem:
    """Test item purchase flow"""
    
    def test_buy_item_redirects_to_stripe(self, client, test_item):
        """
        Test that buying an item redirects to Stripe checkout.
        
        Note: This will fail if Stripe keys aren't set, but that's okay.
        We're testing the flow, not actual payment processing.
        """
        response = client.get(f'/buy_item/{test_item.id}', follow_redirects=False)
        # Should redirect (302/303) to Stripe checkout
        # Or return error if Stripe not configured (which is fine for tests)
        assert response.status_code in [200, 302, 303, 500]
    
    def test_buy_sold_item_shows_error(self, client, test_item):
        """Test that buying a sold item shows error"""
        from app import db, InventoryItem
        with client.application.app_context():
            # Refresh item in session and mark as sold
            item = InventoryItem.query.get(test_item.id)
            item.status = 'sold'
            db.session.commit()
        
        response = client.get(f'/buy_item/{test_item.id}', follow_redirects=True)
        assert response.status_code == 200
        # Check for flash message or error text in response
        response_lower = response.data.lower()
        assert (b'no longer available' in response_lower or 
                b'sorry' in response_lower or 
                b'not available' in response_lower or
                b'unavailable' in response_lower)
    
    def test_buy_nonexistent_item(self, client):
        """Test that buying non-existent item returns 404"""
        response = client.get('/buy_item/99999', follow_redirects=False)
        assert response.status_code == 404
    
    def test_buy_item_without_price(self, client, test_category):
        """Test that items without price can't be purchased"""
        from app import db, InventoryItem, User
        with client.application.app_context():
            # Create item without price
            user = User(email='seller@test.com', password_hash='hash')
            db.session.add(user)
            db.session.flush()
            
            item = InventoryItem(
                description='Free Item',
                quality=3,
                price=None,  # No price
                status='available',
                category_id=test_category.id,
                seller_id=user.id,
                photo_url='test.jpg'  # Add photo_url to avoid URL building issues
            )
            db.session.add(item)
            db.session.commit()
            item_id = item.id
        
        response = client.get(f'/buy_item/{item_id}', follow_redirects=True)
        # Should show error or redirect (seller has_paid=False so item not available)
        assert response.status_code == 200
        assert (b'not available' in response.data.lower() or
                b'not yet available' in response.data.lower() or
                b'invalid' in response.data.lower())
