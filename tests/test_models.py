"""
Unit tests for database models.

These test that the database models work correctly.
Run: pytest tests/test_models.py -v
"""
import pytest
from datetime import datetime
from app import db
from models import User, InventoryCategory, InventoryItem, AppSetting


@pytest.mark.unit
class TestUserModel:
    """Test User model"""
    
    def test_create_user(self, client):
        """Test creating a user in the database"""
        with client.application.app_context():
            user = User(
                email='test@example.com',
                password_hash='hashed_password',
                full_name='Test User'
            )
            db.session.add(user)
            db.session.commit()
            
            # Check user was created with correct values
            assert user.id is not None
            assert user.email == 'test@example.com'
            assert user.full_name == 'Test User'
            # Check defaults
            assert user.is_admin == False
            assert user.is_seller == False
            assert user.has_paid == False
            assert user.date_joined is not None
    
    def test_user_email_unique(self, client, test_user):
        """Test that email addresses must be unique"""
        with client.application.app_context():
            duplicate = User(
                email=test_user.email,  # Same email
                password_hash='hash'
            )
            db.session.add(duplicate)
            
            # Should raise an error when committing
            import pytest
            from sqlalchemy.exc import IntegrityError
            with pytest.raises(IntegrityError):
                db.session.commit()
    
    def test_user_relationships(self, client, test_user, test_item):
        """Test that user-item relationship works"""
        with client.application.app_context():
            from models import User, InventoryItem
            # Refresh objects in session to access relationships
            user = User.query.get(test_user.id)
            item = InventoryItem.query.get(test_item.id)
            # User should have items
            assert len(user.items) > 0
            assert user.items[0].id == item.id
            # Item should have seller
            assert item.seller.id == user.id


@pytest.mark.unit
class TestInventoryCategoryModel:
    """Test InventoryCategory model"""
    
    def test_create_category(self, client):
        """Test creating a category"""
        with client.application.app_context():
            category = InventoryCategory(
                name='Test Category',
                image_url='fa-box',
                count_in_stock=0
            )
            db.session.add(category)
            db.session.commit()
            
            assert category.id is not None
            assert category.name == 'Test Category'
            assert category.image_url == 'fa-box'
            assert category.count_in_stock == 0
    
    def test_category_defaults(self, client):
        """Test category default values"""
        with client.application.app_context():
            category = InventoryCategory(name='Test')
            db.session.add(category)
            db.session.commit()
            
            assert category.count_in_stock == 0


@pytest.mark.unit
class TestInventoryItemModel:
    """Test InventoryItem model"""
    
    def test_create_item(self, client, test_user, test_category):
        """Test creating an item"""
        with client.application.app_context():
            item = InventoryItem(
                description='Test Item',
                price=50.00,
                quality=4,
                status='available',
                category_id=test_category.id,
                seller_id=test_user.id
            )
            db.session.add(item)
            db.session.commit()
            
            assert item.id is not None
            assert item.description == 'Test Item'
            assert item.price == 50.00
            assert item.quality == 4
            assert item.status == 'available'
            assert item.date_added is not None
    
    def test_item_defaults(self, client, test_category):
        """Test item default values"""
        with client.application.app_context():
            item = InventoryItem(
                description='Test',
                quality=3,
                category_id=test_category.id
            )
            db.session.add(item)
            db.session.commit()
            
            # Check defaults
            assert item.status == 'pending_valuation'
            assert item.collection_method == 'online'
            assert item.payout_sent == False
            assert item.sold_at is None
    
    def test_item_relationships(self, client, test_item, test_user, test_category):
        """Test item relationships to user and category"""
        with client.application.app_context():
            from models import User, InventoryItem, InventoryCategory
            # Refresh objects in session to access relationships
            item = InventoryItem.query.get(test_item.id)
            user = User.query.get(test_user.id)
            category = InventoryCategory.query.get(test_category.id)
            # Item should have seller
            assert item.seller.id == user.id
            # Item should have category
            assert item.category.id == category.id
            # User should have item
            assert item in user.items
            # Category should have item - use refreshed category object
            assert item in category.items


@pytest.mark.unit
class TestAppSettingModel:
    """Test AppSetting model (key-value store)"""
    
    def test_app_setting_get_set(self, client):
        """Test AppSetting get/set methods"""
        with client.application.app_context():
            # Set a value
            AppSetting.set('test_key', 'test_value')
            
            # Get the value
            value = AppSetting.get('test_key')
            assert value == 'test_value'
            
            # Get non-existent key with default
            default = AppSetting.get('nonexistent', 'default_value')
            assert default == 'default_value'
            
            # Get non-existent key without default
            none_value = AppSetting.get('nonexistent')
            assert none_value is None
    
    def test_app_setting_update(self, client):
        """Test updating an existing AppSetting"""
        with client.application.app_context():
            # Set initial value
            AppSetting.set('test_key', 'value1')
            assert AppSetting.get('test_key') == 'value1'
            
            # Update the value
            AppSetting.set('test_key', 'value2')
            assert AppSetting.get('test_key') == 'value2'
            
            # Should only be one record
            settings = AppSetting.query.filter_by(key='test_key').all()
            assert len(settings) == 1
    
    def test_app_setting_string_conversion(self, client):
        """Test that AppSetting converts values to strings"""
        with client.application.app_context():
            # Set numeric value
            AppSetting.set('numeric_key', 123)
            value = AppSetting.get('numeric_key')
            assert value == '123'  # Should be string
            assert isinstance(value, str)
            
            # Set boolean value
            AppSetting.set('bool_key', True)
            value = AppSetting.get('bool_key')
            assert value == 'True'  # Should be string
