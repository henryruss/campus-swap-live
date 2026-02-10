"""
Application-wide constants for Campus Swap
"""

# Payout Configuration
PAYOUT_PERCENTAGE = 0.50  # Sellers receive 50% of sale price

# Payment Configuration
SELLER_ACTIVATION_FEE_CENTS = 1500  # $15.00 in cents

# File Upload Configuration
MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10MB
# JPG/JPEG/PNG/WebP work from desktop and phones (e.g. Android JPEG/WebP; iPhone use "Most Compatible" for JPEG)
ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'webp'}
ALLOWED_MIME_TYPES = {'image/jpeg', 'image/png', 'image/jpg', 'image/webp'}

# Image Processing Configuration
IMAGE_QUALITY = 80  # JPEG quality (0-100)
THUMBNAIL_SIZE = (300, 300)  # Thumbnail dimensions

# Input Validation
MIN_PRICE = 0.01
MAX_PRICE = 10000.00
MIN_QUALITY = 1
MAX_QUALITY = 5
MAX_DESCRIPTION_LENGTH = 200
MAX_LONG_DESCRIPTION_LENGTH = 2000
MAX_EMAIL_LENGTH = 120
MAX_NAME_LENGTH = 100

# Pagination
ITEMS_PER_PAGE = 24

# Rate Limiting (requests per time period)
RATE_LIMIT_LOGIN = "5 per minute"
RATE_LIMIT_REGISTER = "3 per hour"
RATE_LIMIT_ADMIN = "100 per minute"
RATE_LIMIT_EMAIL = "10 per hour"
