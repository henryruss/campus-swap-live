"""
Unit tests for constants.

These verify that constants are set correctly.
Run: pytest tests/test_constants.py -v
"""
import pytest
from constants import (
    PAYOUT_PERCENTAGE, SELLER_ACTIVATION_FEE_CENTS,
    MAX_UPLOAD_SIZE, ALLOWED_EXTENSIONS, ALLOWED_MIME_TYPES,
    MIN_PRICE, MAX_PRICE, MIN_QUALITY, MAX_QUALITY,
    ITEMS_PER_PAGE
)


@pytest.mark.unit
class TestConstants:
    """Test that constants are set correctly"""
    
    def test_payout_percentage(self):
        """Test payout percentage is reasonable"""
        assert 0 < PAYOUT_PERCENTAGE < 1  # Should be between 0 and 1
        assert PAYOUT_PERCENTAGE == 0.40  # Should be 40%
    
    def test_seller_activation_fee(self):
        """Test seller activation fee"""
        assert SELLER_ACTIVATION_FEE_CENTS > 0
        assert SELLER_ACTIVATION_FEE_CENTS == 1500  # $15.00
    
    def test_upload_size_limit(self):
        """Test file upload size limit"""
        assert MAX_UPLOAD_SIZE > 0
        assert MAX_UPLOAD_SIZE == 10 * 1024 * 1024  # 10MB
    
    def test_allowed_extensions(self):
        """Test allowed file extensions"""
        assert 'jpg' in ALLOWED_EXTENSIONS
        assert 'jpeg' in ALLOWED_EXTENSIONS
        assert 'png' in ALLOWED_EXTENSIONS
        assert 'webp' in ALLOWED_EXTENSIONS
        assert 'exe' not in ALLOWED_EXTENSIONS
        assert 'pdf' not in ALLOWED_EXTENSIONS
    
    def test_price_bounds(self):
        """Test price validation bounds"""
        assert MIN_PRICE > 0
        assert MAX_PRICE > MIN_PRICE
        assert MAX_PRICE == 10000.00
    
    def test_quality_bounds(self):
        """Test quality rating bounds"""
        assert MIN_QUALITY == 1
        assert MAX_QUALITY == 5
        assert MAX_QUALITY > MIN_QUALITY
    
    def test_pagination(self):
        """Test pagination settings"""
        assert ITEMS_PER_PAGE > 0
        assert ITEMS_PER_PAGE == 24
