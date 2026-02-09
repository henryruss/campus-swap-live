"""
Integration tests for authentication routes.

These test the full login/registration flow.
Run: pytest tests/test_auth.py -v
"""
import pytest


@pytest.mark.integration
class TestRegistration:
    """Test user registration flow"""
    
    def test_register_page_loads(self, client):
        """Test that registration page is accessible"""
        response = client.get('/register')
        assert response.status_code == 200
        # Check page contains registration form
        assert b'register' in response.data.lower() or b'create account' in response.data.lower()
    
    def test_register_new_user_success(self, client):
        """
        Test successful user registration.
        
        This simulates a user filling out the registration form.
        """
        response = client.post('/register', data={
            'email': 'newuser@example.com',
            'password': 'password123',
            'full_name': 'New User'
        }, follow_redirects=True)
        
        assert response.status_code == 200
        
        # Check user was created in database
        from app import User
        with client.application.app_context():
            user = User.query.filter_by(email='newuser@example.com').first()
            assert user is not None
            assert user.full_name == 'New User'
            assert user.password_hash is not None  # Password should be hashed
    
    def test_register_duplicate_email(self, client, test_user):
        """
        Test that registering with existing email shows error.
        
        Users shouldn't be able to create multiple accounts with same email.
        """
        response = client.post('/register', data={
            'email': test_user.email,  # Use existing user's email
            'password': 'password123',
            'full_name': 'Duplicate User'
        }, follow_redirects=True)
        
        assert response.status_code == 200
        # Should show error or redirect to login
        assert b'already exists' in response.data.lower() or b'login' in response.data.lower()
    
    def test_register_invalid_email(self, client):
        """Test that invalid email addresses are rejected"""
        response = client.post('/register', data={
            'email': 'invalid-email-format',
            'password': 'password123',
            'full_name': 'Test User'
        })
        
        assert response.status_code == 200
        assert b'valid email' in response.data.lower() or b'invalid' in response.data.lower()
    
    def test_register_short_password(self, client):
        """Test that passwords shorter than 6 characters are rejected"""
        response = client.post('/register', data={
            'email': 'test@example.com',
            'password': '12345',  # Only 5 characters
            'full_name': 'Test User'
        })
        
        assert response.status_code == 200
        assert b'6 characters' in response.data.lower() or b'password' in response.data.lower()


@pytest.mark.integration
class TestLogin:
    """Test login functionality"""
    
    def test_login_page_loads(self, client):
        """Test that login page is accessible"""
        response = client.get('/login')
        assert response.status_code == 200
    
    def test_login_success(self, client, test_user):
        """
        Test successful login.
        
        This simulates a user logging in with correct credentials.
        """
        response = client.post('/login', data={
            'email': test_user.email,
            'password': 'testpass123',  # Password from conftest.py fixture
            'form_type': 'login'
        }, follow_redirects=True)
        
        assert response.status_code == 200
        # Should redirect to dashboard after successful login
        # Check for dashboard content or redirect location
        assert (b'dashboard' in response.data.lower() or 
                '/dashboard' in response.request.path or
                response.request.path == '/dashboard')
    
    def test_login_wrong_password(self, client, test_user):
        """Test that wrong password shows error"""
        response = client.post('/login', data={
            'email': test_user.email,
            'password': 'wrongpassword',
            'form_type': 'login'
        })
        
        assert response.status_code == 200
        assert b'invalid' in response.data.lower() or b'incorrect' in response.data.lower() or b'wrong' in response.data.lower()
    
    def test_login_nonexistent_user(self, client):
        """Test that logging in with non-existent email shows error"""
        response = client.post('/login', data={
            'email': 'nonexistent@example.com',
            'password': 'password123',
            'form_type': 'login'
        })
        
        assert response.status_code == 200
        assert b'not found' in response.data.lower() or b'create' in response.data.lower()
    
    def test_login_invalid_email_format(self, client):
        """Test that invalid email format is rejected"""
        response = client.post('/login', data={
            'email': 'not-an-email',
            'password': 'password123',
            'form_type': 'login'
        })
        
        assert response.status_code == 200
        assert b'valid email' in response.data.lower()


@pytest.mark.integration
class TestLogout:
    """Test logout functionality"""
    
    def test_logout_requires_login(self, client):
        """
        Test that logout requires authentication.
        
        If not logged in, should redirect to login.
        """
        response = client.get('/logout', follow_redirects=True)
        assert response.status_code == 200
        # Should redirect to login or index
        assert b'login' in response.data.lower() or response.request.path == '/'
    
    def test_logout_success(self, authenticated_client):
        """
        Test successful logout.
        
        After logout, user should be redirected and session cleared.
        """
        response = authenticated_client.get('/logout', follow_redirects=True)
        assert response.status_code == 200
        # Should redirect to index/homepage
        assert b'campus swap' in response.data.lower() or response.request.path == '/'


@pytest.mark.integration
class TestProtectedRoutes:
    """Test that protected routes require authentication"""
    
    def test_dashboard_requires_login(self, client):
        """Test that dashboard requires login"""
        response = client.get('/dashboard', follow_redirects=True)
        assert response.status_code == 200
        # Should redirect to login
        assert b'login' in response.data.lower() or '/login' in response.request.path
    
    def test_dashboard_accessible_when_logged_in(self, authenticated_client):
        """Test that dashboard is accessible when logged in"""
        response = authenticated_client.get('/dashboard')
        assert response.status_code == 200
        assert b'dashboard' in response.data.lower()
    
    def test_add_item_requires_login(self, client):
        """Test that add_item route requires login"""
        response = client.get('/add_item', follow_redirects=True)
        assert response.status_code == 200
        assert b'login' in response.data.lower()
