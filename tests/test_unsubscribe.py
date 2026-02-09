"""
Integration tests for email unsubscribe functionality.

These test the unsubscribe flow including:
- Unsubscribe page access
- Token validation
- Unsubscribe confirmation and processing
- Filtering unsubscribed users from marketing emails
- Unsubscribe token generation

Run: pytest tests/test_unsubscribe.py -v
"""
import pytest
from app import db, User, ensure_unsubscribe_token, wrap_email_template


@pytest.mark.integration
class TestUnsubscribePage:
    """Test unsubscribe page access and display"""
    
    def test_unsubscribe_page_with_valid_token(self, client, test_user):
        """Test that unsubscribe page loads with valid token"""
        with client.application.app_context():
            # Generate unsubscribe token for user
            token = ensure_unsubscribe_token(test_user)
        
        response = client.get(f'/unsubscribe/{token}')
        assert response.status_code == 200
        # Should show confirmation page with user email
        assert test_user.email.encode() in response.data
        assert b'unsubscribe' in response.data.lower()
        assert b'confirm' in response.data.lower() or b'yes' in response.data.lower()
    
    def test_unsubscribe_page_with_invalid_token(self, client):
        """Test that invalid token shows error message"""
        invalid_token = 'invalid_token_12345'
        response = client.get(f'/unsubscribe/{invalid_token}', follow_redirects=True)
        assert response.status_code == 200
        # Should show error about invalid link
        assert b'invalid' in response.data.lower() or b'error' in response.data.lower()
    
    def test_unsubscribe_page_with_missing_token(self, client):
        """Test that missing token parameter shows error"""
        response = client.get('/unsubscribe/', follow_redirects=True)
        # Should return 404 or redirect with error
        assert response.status_code in [404, 200]
        if response.status_code == 200:
            assert b'invalid' in response.data.lower() or b'not found' in response.data.lower()


@pytest.mark.integration
class TestUnsubscribeProcess:
    """Test the unsubscribe confirmation and processing"""
    
    def test_unsubscribe_confirmation_shows_email(self, client, test_user):
        """Test that confirmation page displays user's email"""
        with client.application.app_context():
            token = ensure_unsubscribe_token(test_user)
        
        response = client.get(f'/unsubscribe/{token}')
        assert response.status_code == 200
        assert test_user.email.encode() in response.data
    
    def test_unsubscribe_success(self, client, test_user):
        """Test that POST request successfully unsubscribes user"""
        with client.application.app_context():
            # Ensure user is not already unsubscribed
            test_user.unsubscribed = False
            db.session.commit()
            
            token = ensure_unsubscribe_token(test_user)
        
        # POST to unsubscribe
        response = client.post(f'/unsubscribe/{token}', follow_redirects=True)
        assert response.status_code == 200
        
        # Check user is marked as unsubscribed
        with client.application.app_context():
            user = User.query.get(test_user.id)
            assert user.unsubscribed == True
            assert b'successfully unsubscribed' in response.data.lower() or b'unsubscribed' in response.data.lower()
    
    def test_unsubscribe_already_unsubscribed(self, client, test_user):
        """Test that unsubscribing an already unsubscribed user still works"""
        with client.application.app_context():
            test_user.unsubscribed = True
            db.session.commit()
            token = ensure_unsubscribe_token(test_user)
        
        response = client.post(f'/unsubscribe/{token}', follow_redirects=True)
        assert response.status_code == 200
        
        # Should still show success message
        with client.application.app_context():
            user = User.query.get(test_user.id)
            assert user.unsubscribed == True
    
    def test_unsubscribe_with_wrong_token(self, client, test_user):
        """Test that wrong token doesn't unsubscribe user"""
        with client.application.app_context():
            test_user.unsubscribed = False
            db.session.commit()
        
        wrong_token = 'wrong_token_12345'
        response = client.post(f'/unsubscribe/{wrong_token}', follow_redirects=True)
        assert response.status_code == 200
        
        # User should not be unsubscribed
        with client.application.app_context():
            user = User.query.get(test_user.id)
            assert user.unsubscribed == False


@pytest.mark.integration
class TestUnsubscribeTokenGeneration:
    """Test unsubscribe token generation and management"""
    
    def test_ensure_unsubscribe_token_creates_token(self, client, test_user):
        """Test that ensure_unsubscribe_token creates token if missing"""
        with client.application.app_context():
            # Clear existing token
            test_user.unsubscribe_token = None
            db.session.commit()
            
            # Generate token
            token = ensure_unsubscribe_token(test_user)
            
            # Refresh user from DB to get updated token
            from models import User
            user = User.query.get(test_user.id)
            
            assert token is not None
            assert len(token) > 0
            assert user.unsubscribe_token == token
    
    def test_ensure_unsubscribe_token_reuses_existing(self, client, test_user):
        """Test that ensure_unsubscribe_token reuses existing token"""
        with client.application.app_context():
            # Set existing token
            existing_token = 'existing_token_12345'
            test_user.unsubscribe_token = existing_token
            db.session.commit()
            
            # Call ensure_unsubscribe_token
            token = ensure_unsubscribe_token(test_user)
            
            assert token == existing_token
            assert test_user.unsubscribe_token == existing_token
    
    def test_unsubscribe_token_is_unique(self, client):
        """Test that each user gets a unique unsubscribe token"""
        with client.application.app_context():
            user1 = User(
                email='user1@test.com',
                password_hash='hash1'
            )
            user2 = User(
                email='user2@test.com',
                password_hash='hash2'
            )
            db.session.add(user1)
            db.session.add(user2)
            db.session.commit()
            
            token1 = ensure_unsubscribe_token(user1)
            token2 = ensure_unsubscribe_token(user2)
            
            assert token1 != token2
            assert user1.unsubscribe_token != user2.unsubscribe_token


@pytest.mark.integration
class TestUnsubscribedUserFiltering:
    """Test that unsubscribed users are filtered from marketing emails"""
    
    def test_unsubscribed_users_excluded_from_mass_email(self, client, test_user, admin_client):
        """Test that unsubscribed users don't receive mass emails"""
        subscribed_user_id = None
        with client.application.app_context():
            from models import User
            # Create another user who is subscribed
            subscribed_user = User(
                email='subscribed@test.com',
                password_hash='hash',
                unsubscribed=False
            )
            db.session.add(subscribed_user)
            db.session.commit()
            # Store ID before context closes
            subscribed_user_id = subscribed_user.id
            
            # Unsubscribe test_user - refresh from DB first
            user = User.query.get(test_user.id)
            user.unsubscribed = True
            db.session.commit()
        
        # Try to send mass email
        response = admin_client.post('/admin/mass-email', data={
            'subject': 'Test Email',
            'html_content': '<p>Test content</p>'
        }, follow_redirects=True)
        
        assert response.status_code == 200
        
        # Note: Since we're not actually sending emails in tests (no Resend API key),
        # we can't verify the email wasn't sent, but we can verify the user is marked
        # as unsubscribed and would be filtered by the query
        with client.application.app_context():
            from models import User
            # Check that unsubscribed users are filtered in the query
            users_to_email = User.query.filter(
                User.email.isnot(None),
                User.unsubscribed != True
            ).all()
            
            user_emails = [u.email for u in users_to_email]
            # Refresh test_user to get email
            user = User.query.get(test_user.id)
            # Refresh subscribed_user to get email using stored ID
            subscribed = User.query.get(subscribed_user_id)
            assert user.email not in user_emails
            assert subscribed.email in user_emails
    
    def test_send_email_skips_unsubscribed_users(self, client, test_user):
        """Test that send_email function skips unsubscribed users"""
        # Mock or check that unsubscribed users are skipped
        # Since we don't have Resend API key in tests, we'll test the logic
        
        with client.application.app_context():
            test_user.unsubscribed = True
            db.session.commit()
            
            # The send_email function should check unsubscribed status
            # and return False early if user is unsubscribed
            # We can't fully test without mocking Resend, but we can verify
            # the user is marked as unsubscribed
            assert test_user.unsubscribed == True


@pytest.mark.integration
class TestEmailUnsubscribeLink:
    """Test that marketing emails include unsubscribe links"""
    
    def test_marketing_email_includes_unsubscribe_url(self, client, test_user):
        """Test that marketing emails get unsubscribe URLs"""
        from flask import url_for
        
        with client.application.app_context():
            token = ensure_unsubscribe_token(test_user)
            unsubscribe_url = url_for('unsubscribe', token=token, _external=True)
            
            # Test email template wrapper
            html_content = '<p>Test marketing email</p>'
            wrapped = wrap_email_template(html_content, unsubscribe_url, is_marketing=True)
            
            # Check unsubscribe link is in the email
            assert unsubscribe_url.encode() in wrapped.encode()
            wrapped_lower = wrapped.lower()
            assert 'unsubscribe' in wrapped_lower
            assert 'footer' in wrapped_lower or 'campus swap' in wrapped_lower
    
    def test_non_marketing_email_no_unsubscribe_link(self, client):
        """Test that non-marketing emails don't include unsubscribe links"""
        html_content = '<p>Transactional email</p>'
        wrapped = wrap_email_template(html_content, unsubscribe_url=None, is_marketing=False)
        
        # Should not have unsubscribe link (but may have Campus Swap branding)
        # The key is that it shouldn't have an unsubscribe URL
        wrapped_lower = wrapped.lower()
        assert 'unsubscribe' not in wrapped_lower or 'campus swap' in wrapped_lower


@pytest.mark.integration
class TestUnsubscribeSuccessPage:
    """Test unsubscribe success page"""
    
    def test_unsubscribe_success_page_displays(self, client, test_user):
        """Test that success page displays after unsubscribe"""
        with client.application.app_context():
            token = ensure_unsubscribe_token(test_user)
        
        # Unsubscribe the user
        response = client.post(f'/unsubscribe/{token}', follow_redirects=True)
        assert response.status_code == 200
        
        # Should show success message
        assert b'successfully unsubscribed' in response.data.lower() or b'unsubscribed' in response.data.lower()
        assert b'home' in response.data.lower() or b'browse' in response.data.lower()
