"""
Pytest configuration and fixtures for Campus Swap tests.

Fixtures are reusable test data/objects that tests can use.
Think of them as "test helpers" that set up common scenarios.
"""
import pytest
import os
import tempfile
from app import app, db
from models import User, InventoryCategory, InventoryItem, AppSetting
from werkzeug.security import generate_password_hash


@pytest.fixture(scope='function')
def client():
    """
    Create a test client for the application.
    
    This fixture:
    - Creates a temporary in-memory database (SQLite)
    - Sets up test configuration
    - Creates all database tables
    - Yields a test client you can use to make requests
    - Cleans up after the test
    
    Use this in any test that needs to make HTTP requests.
    """
    # Create a temporary database file
    db_fd, db_path = tempfile.mkstemp()
    
    # Configure app for testing
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False  # Disable CSRF for easier testing
    app.config['SECRET_KEY'] = 'test-secret-key'
    app.config['SERVER_NAME'] = 'localhost'  # Needed for URL building in tests
    
    # Disable rate limiting for tests (if Flask-Limiter is installed)
    # Flask-Limiter decorators are applied at import time, so we need to patch the instance
    if hasattr(app, 'limiter') and app.limiter:
        # Completely disable the limiter
        app.limiter.enabled = False
        
        # Clear all rate limit storage
        try:
            if hasattr(app.limiter, '_storage') and app.limiter._storage:
                if hasattr(app.limiter._storage, 'reset'):
                    app.limiter._storage.reset()
                if hasattr(app.limiter._storage, 'clear'):
                    app.limiter._storage.clear()
                # Try to clear all keys in memory storage
                if hasattr(app.limiter._storage, 'storage'):
                    app.limiter._storage.storage.clear()
        except:
            pass
        
        # Override the limit decorator to be a no-op
        original_limit = app.limiter.limit
        def noop_limit(*args, **kwargs):
            # If called as @limiter.limit("3 per hour"), args[0] is the limit string
            # If called as @limiter.limit(), no args
            def decorator(f):
                return f
            # Handle @limiter.limit() without args (returns decorator)
            # Handle @limiter.limit("3 per hour") with args (returns decorator)
            if not args:
                return decorator
            if len(args) == 1 and callable(args[0]):
                # Called as @limiter.limit without parentheses on a function
                return args[0]
            return decorator
        
        app.limiter.limit = noop_limit
        
        # Override check to always allow
        app.limiter.check = lambda *args, **kwargs: True
        
        # Also set default_limits to empty
        app.limiter.default_limits = []
    
    # Create test client and set up database
    with app.test_client() as client:
        with app.app_context():
            # Create all tables
            db.create_all()
            # Yield the client to the test
            yield client
            # Clean up after test
            db.session.remove()
            db.drop_all()
    
    # Clean up temporary database file
    os.close(db_fd)
    os.unlink(db_path)


@pytest.fixture
def test_user(client):
    """
    Create a test user in the database.
    
    This creates a regular user (not admin) that you can use in tests.
    Email: test@example.com
    Password: testpass123
    """
    with app.app_context():
        user = User(
            email='test@example.com',
            password_hash=generate_password_hash('testpass123'),
            full_name='Test User',
            is_seller=True,
            has_paid=True
        )
        db.session.add(user)
        db.session.commit()
        # Access attributes to ensure they're loaded before session closes
        # This prevents DetachedInstanceError when accessing these later
        _ = user.id, user.email, user.full_name, user.is_admin, user.is_seller, user.has_paid
        return user


@pytest.fixture
def test_admin_user(client):
    """
    Create a test admin user in the database.
    
    This creates an admin user that you can use to test admin routes.
    Email: admin@example.com
    Password: adminpass123
    """
    with app.app_context():
        admin = User(
            email='admin@example.com',
            password_hash=generate_password_hash('adminpass123'),
            full_name='Admin User',
            is_admin=True,
            is_super_admin=True,
            is_seller=True,
            has_paid=True
        )
        db.session.add(admin)
        db.session.commit()
        # Access attributes to ensure they're loaded before session closes
        # This prevents DetachedInstanceError when accessing these later
        _ = admin.id, admin.email, admin.full_name, admin.is_admin, admin.is_seller, admin.has_paid
        return admin


@pytest.fixture
def test_category(client):
    """
    Create a test category in the database.
    
    This creates a category that you can use for testing items.
    """
    with app.app_context():
        category = InventoryCategory(
            name='Test Category',
            image_url='fa-box',
            count_in_stock=0
        )
        db.session.add(category)
        db.session.commit()
        # Access attributes to ensure they're loaded before session closes
        # This prevents DetachedInstanceError when accessing these later
        _ = category.id, category.name, category.image_url, category.count_in_stock
        return category


@pytest.fixture
def test_item(client, test_user, test_category):
    """
    Create a test item in the database.
    
    This creates an available item that you can use in tests.
    Requires: test_user and test_category fixtures
    """
    with app.app_context():
        item = InventoryItem(
            description='Test Item',
            long_description='This is a test item description',
            price=50.00,
            quality=4,
            status='available',
            category_id=test_category.id,
            seller_id=test_user.id,
            collection_method='online',
            photo_url='test.jpg'
        )
        db.session.add(item)
        db.session.commit()
        # Access attributes to ensure they're loaded before session closes
        # This prevents DetachedInstanceError when accessing these later
        _ = item.id, item.category_id, item.seller_id, item.status, item.price
        return item


@pytest.fixture
def authenticated_client(client, test_user):
    """
    Create an authenticated test client.
    
    This simulates a logged-in user session.
    Use this when testing routes that require login.
    """
    # Use Flask-Login's test client login method
    from flask_login import login_user
    
    # Need to be in both app context and request context for login_user
    with client.application.app_context():
        # Get fresh user from DB for login_user (needs to be in session)
        user = User.query.get(test_user.id)
        if not user:
            user = test_user
    
    # Set session using session_transaction (creates request context)
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
    
    return client


@pytest.fixture
def admin_client(client, test_admin_user):
    """
    Create an authenticated admin test client.
    
    This simulates a logged-in admin user session.
    Use this when testing admin routes.
    """
    # Use Flask-Login's test client login method
    from flask_login import login_user
    
    # Need to be in both app context and request context for login_user
    with client.application.app_context():
        # Get fresh user from DB for login_user (needs to be in session)
        user = User.query.get(test_admin_user.id)
        if not user:
            user = test_admin_user
    
    # Set session using session_transaction (creates request context)
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
    
    return client
