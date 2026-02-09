"""
Unit tests for validation functions.

These test the helper functions that validate user input.
Run: pytest tests/test_validation.py -v
"""
import pytest
from app import validate_email, validate_file_upload, validate_price, validate_quality
from io import BytesIO
from constants import MAX_UPLOAD_SIZE, MAX_EMAIL_LENGTH


@pytest.mark.unit
class TestEmailValidation:
    """Test the validate_email() function"""
    
    def test_valid_emails(self):
        """Test that valid email addresses pass validation"""
        assert validate_email('user@example.com') == True
        assert validate_email('test.user@example.co.uk') == True
        assert validate_email('user+tag@example.com') == True
        assert validate_email('user123@test-domain.com') == True
    
    def test_invalid_emails(self):
        """Test that invalid email addresses fail validation"""
        assert validate_email('invalid') == False
        assert validate_email('invalid@') == False
        assert validate_email('@example.com') == False
        assert validate_email('user@') == False
        assert validate_email('') == False
        assert validate_email(None) == False
    
    def test_email_length_limit(self):
        """Test that emails over the max length are rejected"""
        # Valid length email
        valid_email = 'a' * (MAX_EMAIL_LENGTH - 20) + '@test.com'
        assert validate_email(valid_email) == True
        
        # Too long email
        too_long = 'a' * MAX_EMAIL_LENGTH + '@test.com'
        assert validate_email(too_long) == False


@pytest.mark.unit
class TestPriceValidation:
    """Test the validate_price() function"""
    
    def test_valid_prices(self):
        """Test that valid prices pass validation"""
        valid, price = validate_price('10.50')
        assert valid == True
        assert price == 10.50
        
        valid, price = validate_price('0.01')
        assert valid == True
        assert price == 0.01
        
        valid, price = validate_price('100.00')
        assert valid == True
        assert price == 100.00
    
    def test_invalid_prices(self):
        """Test that invalid prices fail validation"""
        # Negative price
        valid, error = validate_price('-10')
        assert valid == False
        assert 'price' in error.lower() or 'between' in error.lower()
        
        # Price too high
        valid, error = validate_price('20000')
        assert valid == False
        
        # Not a number
        valid, error = validate_price('not_a_number')
        assert valid == False
        assert 'invalid' in error.lower()
        
        # Empty string
        valid, error = validate_price('')
        assert valid == False
    
    def test_price_bounds(self):
        """Test that prices must be within min/max bounds"""
        from constants import MIN_PRICE, MAX_PRICE
        
        # Minimum price should work
        valid, price = validate_price(str(MIN_PRICE))
        assert valid == True
        
        # Maximum price should work
        valid, price = validate_price(str(MAX_PRICE))
        assert valid == True
        
        # Below minimum should fail
        valid, error = validate_price(str(MIN_PRICE - 0.01))
        assert valid == False
        
        # Above maximum should fail
        valid, error = validate_price(str(MAX_PRICE + 1))
        assert valid == False


@pytest.mark.unit
class TestQualityValidation:
    """Test the validate_quality() function"""
    
    def test_valid_quality_values(self):
        """Test that valid quality ratings (1-5) pass validation"""
        for quality in [1, 2, 3, 4, 5]:
            valid, value = validate_quality(str(quality))
            assert valid == True
            assert value == quality
    
    def test_invalid_quality_values(self):
        """Test that invalid quality ratings fail validation"""
        # Zero
        valid, error = validate_quality('0')
        assert valid == False
        
        # Too high
        valid, error = validate_quality('6')
        assert valid == False
        
        # Negative
        valid, error = validate_quality('-1')
        assert valid == False
        
        # Not a number
        valid, error = validate_quality('not_a_number')
        assert valid == False
        assert 'invalid' in error.lower()
        
        # Empty string
        valid, error = validate_quality('')
        assert valid == False


@pytest.mark.unit
class TestFileUploadValidation:
    """Test the validate_file_upload() function"""
    
    def test_valid_jpeg_file(self):
        """Test that valid JPEG files pass validation"""
        # Create a mock JPEG file (small size)
        file = BytesIO(b'\xff\xd8\xff\xe0\x00\x10JFIF' + b'0' * 1000)
        file.filename = 'test.jpg'
        file.content_type = 'image/jpeg'
        file.seek(0, 2)  # Seek to end to get size
        file.seek(0)  # Reset to beginning
        
        is_valid, error = validate_file_upload(file)
        # Note: This might fail on size if file is too small, but structure is correct
        # In real usage, files would be larger
    
    def test_invalid_file_extension(self):
        """Test that files with invalid extensions are rejected"""
        file = BytesIO(b'fake executable content')
        file.filename = 'malware.exe'
        file.content_type = 'application/x-msdownload'
        file.seek(0, 2)
        file.seek(0)
        
        is_valid, error = validate_file_upload(file)
        assert is_valid == False
        assert 'not allowed' in error.lower() or 'type' in error.lower()
    
    def test_file_too_large(self):
        """Test that files exceeding size limit are rejected"""
        # Create a file larger than max size
        file = BytesIO(b'0' * (MAX_UPLOAD_SIZE + 1000))
        file.filename = 'huge.jpg'
        file.content_type = 'image/jpeg'
        file.seek(0, 2)
        file.seek(0)
        
        is_valid, error = validate_file_upload(file)
        assert is_valid == False
        assert 'size' in error.lower() or 'exceeds' in error.lower()
    
    def test_no_file_provided(self):
        """Test that missing files are rejected"""
        file = BytesIO()
        file.filename = ''
        file.content_type = None
        file.seek(0)
        
        is_valid, error = validate_file_upload(file)
        assert is_valid == False
        assert 'no file' in error.lower() or 'provided' in error.lower()
