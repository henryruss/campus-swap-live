"""
Integration tests for email sending functionality.

These test the email sending system including:
- send_email function with various parameters
- Marketing vs transactional emails
- Email template wrapping
- Plain text generation
- Email headers for marketing emails
- Mass email functionality

Run: pytest tests/test_email_sending.py -v
"""
import pytest
from unittest.mock import patch, MagicMock, call
import app
from app import db, User, send_email, wrap_email_template, html_to_text, ensure_unsubscribe_token


@pytest.mark.integration
class TestSendEmailFunction:
    """Test the send_email function"""
    
    @patch('app.resend.Emails.send')
    def test_send_email_basic(self, mock_send, client, test_user):
        """Test basic email sending"""
        app.resend.api_key = 'test_api_key'  # Set API key for test
        mock_send.return_value = {'id': 'test_email_id'}
        
        with client.application.app_context():
            result = send_email(
                to_email=test_user.email,
                subject='Test Subject',
                html_content='<p>Test content</p>'
            )
        
        assert result == True
        mock_send.assert_called_once()
        call_args = mock_send.call_args[0][0]
        assert call_args['to'] == test_user.email
        assert call_args['subject'] == 'Test Subject'
        assert 'html' in call_args
        assert 'text' in call_args  # Plain text version should be included
    
    @patch('app.resend.Emails.send')
    def test_send_email_no_api_key(self, mock_send, client, test_user):
        """Test that send_email returns False when API key is missing"""
        app.resend.api_key = None  # Clear API key
        
        with client.application.app_context():
            result = send_email(
                to_email=test_user.email,
                subject='Test Subject',
                html_content='<p>Test content</p>'
            )
        
        assert result == False
        mock_send.assert_not_called()
    
    @patch('app.resend.Emails.send')
    def test_send_email_custom_sender(self, mock_send, client, test_user):
        """Test email sending with custom sender"""
        app.resend.api_key = 'test_api_key'
        mock_send.return_value = {'id': 'test_email_id'}
        
        with client.application.app_context():
            result = send_email(
                to_email=test_user.email,
                subject='Test Subject',
                html_content='<p>Test content</p>',
                from_email='Custom Sender <custom@example.com>'
            )
        
        assert result == True
        call_args = mock_send.call_args[0][0]
        assert call_args['from'] == 'Custom Sender <custom@example.com>'
    
    @patch('app.resend.Emails.send')
    def test_send_email_default_sender(self, mock_send, client, test_user):
        """Test that default sender is used when not specified"""
        app.resend.api_key = 'test_api_key'
        mock_send.return_value = {'id': 'test_email_id'}
        
        with client.application.app_context():
            result = send_email(
                to_email=test_user.email,
                subject='Test Subject',
                html_content='<p>Test content</p>'
            )
        
        assert result == True
        call_args = mock_send.call_args[0][0]
        # Should use team@usecampusswap.com as default
        assert 'team@usecampusswap.com' in call_args['from'] or 'Campus Swap' in call_args['from']
    
    @patch('app.resend.Emails.send')
    def test_send_email_marketing_with_unsubscribe(self, mock_send, client, test_user):
        """Test marketing email includes unsubscribe link and headers"""
        app.resend.api_key = 'test_api_key'
        mock_send.return_value = {'id': 'test_email_id'}
        
        with client.application.app_context():
            token = ensure_unsubscribe_token(test_user)
            result = send_email(
                to_email=test_user.email,
                subject='Marketing Email',
                html_content='<p>Marketing content</p>',
                is_marketing=True,
                user=test_user
            )
        
        assert result == True
        call_args = mock_send.call_args[0][0]
        
        # Check headers are included
        assert 'headers' in call_args
        assert 'List-Unsubscribe' in call_args['headers']
        assert 'List-Unsubscribe-Post' in call_args['headers']
        assert call_args['headers']['Precedence'] == 'bulk'
        
        # Check unsubscribe URL is in the email content
        assert token in call_args['html'] or '/unsubscribe/' in call_args['html']
    
    @patch('app.resend.Emails.send')
    def test_send_email_marketing_skips_unsubscribed(self, mock_send, client, test_user):
        """Test that marketing emails skip unsubscribed users"""
        app.resend.api_key = 'test_api_key'
        
        with client.application.app_context():
            test_user.unsubscribed = True
            db.session.commit()
            
            result = send_email(
                to_email=test_user.email,
                subject='Marketing Email',
                html_content='<p>Marketing content</p>',
                is_marketing=True,
                user=test_user
            )
        
        assert result == False
        mock_send.assert_not_called()
    
    @patch('app.resend.Emails.send')
    def test_send_email_transactional_no_unsubscribe(self, mock_send, client, test_user):
        """Test transactional emails don't include unsubscribe links"""
        app.resend.api_key = 'test_api_key'
        mock_send.return_value = {'id': 'test_email_id'}
        
        with client.application.app_context():
            result = send_email(
                to_email=test_user.email,
                subject='Transaction Email',
                html_content='<p>Transaction content</p>',
                is_marketing=False
            )
        
        assert result == True
        call_args = mock_send.call_args[0][0]
        
        # Should not have unsubscribe headers
        assert 'headers' not in call_args or 'List-Unsubscribe' not in call_args.get('headers', {})
    
    @patch('app.resend.Emails.send')
    def test_send_email_includes_plain_text(self, mock_send, client, test_user):
        """Test that emails include plain text version"""
        app.resend.api_key = 'test_api_key'
        mock_send.return_value = {'id': 'test_email_id'}
        
        html_content = '<h1>Title</h1><p>Paragraph with <strong>bold</strong> text.</p>'
        
        with client.application.app_context():
            result = send_email(
                to_email=test_user.email,
                subject='Test Subject',
                html_content=html_content
            )
        
        assert result == True
        call_args = mock_send.call_args[0][0]
        
        # Should have both HTML and text versions
        assert 'html' in call_args
        assert 'text' in call_args
        
        # Plain text should not contain HTML tags
        assert '<' not in call_args['text'] or call_args['text'].count('<') == 0
        # But should contain the content
        assert 'Title' in call_args['text']
        assert 'Paragraph' in call_args['text']
    
    @patch('app.resend.Emails.send')
    def test_send_email_handles_api_error(self, mock_send, client, test_user):
        """Test that send_email handles API errors gracefully"""
        app.resend.api_key = 'test_api_key'
        mock_send.side_effect = Exception('API Error')
        
        with client.application.app_context():
            result = send_email(
                to_email=test_user.email,
                subject='Test Subject',
                html_content='<p>Test content</p>'
            )
        
        assert result == False
        mock_send.assert_called_once()


@pytest.mark.integration
class TestEmailTemplateWrapping:
    """Test email template wrapping functionality"""
    
    def test_wrap_email_template_marketing_with_unsubscribe(self, client, test_user):
        """Test that marketing emails are wrapped with unsubscribe link"""
        from flask import url_for
        
        with client.application.app_context():
            token = ensure_unsubscribe_token(test_user)
            unsubscribe_url = url_for('unsubscribe', token=token, _external=True)
            
            html_content = '<p>Marketing content</p>'
            wrapped = wrap_email_template(html_content, unsubscribe_url, is_marketing=True)
        
        # Should include unsubscribe URL
        assert unsubscribe_url in wrapped
        assert 'unsubscribe' in wrapped.lower()
        
        # Should include proper HTML structure
        assert '<!DOCTYPE html>' in wrapped
        assert '<html' in wrapped
        assert '<body' in wrapped
        
        # Should include footer
        assert 'footer' in wrapped.lower() or 'Campus Swap' in wrapped
        
        # Original content should be preserved
        assert 'Marketing content' in wrapped
    
    def test_wrap_email_template_non_marketing(self, client):
        """Test that non-marketing emails don't include unsubscribe"""
        html_content = '<p>Transactional content</p>'
        wrapped = wrap_email_template(html_content, unsubscribe_url=None, is_marketing=False)
        
        # Should not have unsubscribe link
        assert 'unsubscribe' not in wrapped.lower()
        
        # But should still have proper structure
        assert '<!DOCTYPE html>' in wrapped
        assert html_content in wrapped
    
    def test_wrap_email_template_includes_address_placeholder(self, client, test_user):
        """Test that email template includes address placeholder"""
        from flask import url_for
        
        with client.application.app_context():
            token = ensure_unsubscribe_token(test_user)
            unsubscribe_url = url_for('unsubscribe', token=token, _external=True)
            
            wrapped = wrap_email_template('<p>Content</p>', unsubscribe_url, is_marketing=True)
        
        # Should mention address (placeholder)
        assert 'address' in wrapped.lower() or 'coming soon' in wrapped.lower()


@pytest.mark.integration
class TestHtmlToText:
    """Test HTML to plain text conversion"""
    
    def test_html_to_text_removes_tags(self):
        """Test that HTML tags are removed"""
        html = '<h1>Title</h1><p>Paragraph</p>'
        text = html_to_text(html)
        
        assert '<' not in text
        assert '>' not in text
        assert 'Title' in text
        assert 'Paragraph' in text
    
    def test_html_to_text_handles_nested_tags(self):
        """Test that nested HTML tags are handled"""
        html = '<div><p>Text with <strong>bold</strong> and <em>italic</em></p></div>'
        text = html_to_text(html)
        
        assert '<' not in text
        assert 'Text with' in text
        assert 'bold' in text
        assert 'italic' in text
    
    def test_html_to_text_handles_empty_html(self):
        """Test that empty HTML returns empty string"""
        text = html_to_text('')
        assert text == '' or text.strip() == ''
    
    def test_html_to_text_preserves_content(self):
        """Test that content is preserved"""
        html = '<p>Important: Your item has sold!</p>'
        text = html_to_text(html)
        
        assert 'Important' in text
        assert 'Your item has sold' in text


@pytest.mark.integration
class TestMassEmail:
    """Test mass email functionality"""
    
    @patch('app.send_email')
    def test_mass_email_sends_to_all_users(self, mock_send_email, admin_client, test_user):
        """Test that mass email sends to all subscribed users"""
        mock_send_email.return_value = True
        
        # Create additional users
        with admin_client.application.app_context():
            user2 = User(
                email='user2@test.com',
                password_hash='hash',
                unsubscribed=False
            )
            user3 = User(
                email='user3@test.com',
                password_hash='hash',
                unsubscribed=False
            )
            db.session.add(user2)
            db.session.add(user3)
            db.session.commit()
        
        response = admin_client.post('/admin/mass-email', data={
            'subject': 'Test Mass Email',
            'html_content': '<p>Test content</p>'
        }, follow_redirects=True)
        
        assert response.status_code == 200
        
        # Should have called send_email for each user
        # Note: send_email is called with is_marketing=True
        assert mock_send_email.called
        
        # Check that it was called with marketing flag
        calls = mock_send_email.call_args_list
        for call_args in calls:
            kwargs = call_args[1] if len(call_args) > 1 else {}
            # Should be called with is_marketing=True
            assert kwargs.get('is_marketing') == True
    
    @patch('app.send_email')
    def test_mass_email_excludes_unsubscribed_users(self, mock_send_email, admin_client, test_user):
        """Test that unsubscribed users don't receive mass emails"""
        mock_send_email.return_value = True
        
        # Create subscribed and unsubscribed users
        with admin_client.application.app_context():
            subscribed_user = User(
                email='subscribed@test.com',
                password_hash='hash',
                unsubscribed=False
            )
            test_user.unsubscribed = True
            db.session.add(subscribed_user)
            db.session.commit()
        
        response = admin_client.post('/admin/mass-email', data={
            'subject': 'Test Mass Email',
            'html_content': '<p>Test content</p>'
        }, follow_redirects=True)
        
        assert response.status_code == 200
        
        # Check that send_email was NOT called for unsubscribed user
        # (it should be filtered out before sending)
        calls = mock_send_email.call_args_list
        emails_sent_to = [call[0][0] for call in calls if len(call[0]) > 0]
        
        # Unsubscribed user should not be in the list
        assert test_user.email not in emails_sent_to
    
    def test_mass_email_requires_admin(self, client, test_user):
        """Test that mass email requires admin access"""
        response = client.post('/admin/mass-email', data={
            'subject': 'Test Mass Email',
            'html_content': '<p>Test content</p>'
        }, follow_redirects=True)
        
        assert response.status_code == 200
        assert b'access denied' in response.data.lower() or b'login' in response.data.lower()
    
    def test_mass_email_requires_subject_and_content(self, admin_client):
        """Test that mass email requires both subject and content"""
        # Missing subject
        response = admin_client.post('/admin/mass-email', data={
            'html_content': '<p>Test content</p>'
        }, follow_redirects=True)
        
        assert response.status_code == 200
        assert b'required' in response.data.lower()
        
        # Missing content
        response = admin_client.post('/admin/mass-email', data={
            'subject': 'Test Subject'
        }, follow_redirects=True)
        
        assert response.status_code == 200
        assert b'required' in response.data.lower()
    
    @patch('app.send_email')
    def test_mass_email_handles_send_failures(self, mock_send_email, admin_client, test_user):
        """Test that mass email handles individual send failures gracefully"""
        # First call succeeds, second fails
        mock_send_email.side_effect = [True, False, True]
        
        # Create multiple users
        with admin_client.application.app_context():
            user2 = User(email='user2@test.com', password_hash='hash')
            user3 = User(email='user3@test.com', password_hash='hash')
            db.session.add(user2)
            db.session.add(user3)
            db.session.commit()
        
        response = admin_client.post('/admin/mass-email', data={
            'subject': 'Test Mass Email',
            'html_content': '<p>Test content</p>'
        }, follow_redirects=True)
        
        assert response.status_code == 200
        # Should still show success message even if some failed
        assert mock_send_email.called
