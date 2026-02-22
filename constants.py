"""
Application-wide constants for Campus Swap
"""

# Payout Configuration (by collection method)
PAYOUT_PERCENTAGE_ONLINE = 0.50   # Sellers receive 50% when submitting through site
PAYOUT_PERCENTAGE_IN_PERSON = 0.33  # Sellers receive 33% for in-person drop-offs (Campus Swap takes 67%)
PAYOUT_PERCENTAGE = 0.50  # Legacy alias; use PAYOUT_PERCENTAGE_ONLINE

# Payment Configuration
SERVICE_FEE_CENTS = 1500  # $15 service fee (guarantees space + move-out pickup)
LARGE_ITEM_FEE_CENTS = 1000  # $10 per additional large item (first included in SERVICE_FEE_CENTS)


def calc_pickup_fee_cents(large_count: int) -> int:
    """$15 base includes 1 oversized; each additional oversized = $10."""
    return SERVICE_FEE_CENTS + (LARGE_ITEM_FEE_CENTS * max(0, large_count - 1))
SELLER_ACTIVATION_FEE_CENTS = 1500  # Legacy alias

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

# Pickup weeks (pickup users select after approval - decision is final)
PICKUP_WEEKS = [
    ('week1', 'April 26 – May 2'),
    ('week2', 'May 3 – May 9'),
]

# Pod locations (pod users select after approval)
POD_LOCATIONS = [
    ('greek_row', 'Greek row pod'),
    ('apartment', 'Apartment pod'),
]

# Residence halls by store (for on-campus pickup selection)
RESIDENCE_HALLS_BY_STORE = {
    'UNC Chapel Hill': {
        'North Campus': [
            'Alderman Residence Hall',
            'Alexander Residence Hall',
            'Cobb Residence Hall',
            'Connor Residence Hall',
            'Everett Residence Hall',
            'Graham Residence Hall',
            'Grimes Residence Hall',
            'Joyner Residence Hall',
            'Kenan Residence Hall',
            'Lewis Residence Hall',
            'Mangum Residence Hall',
            'Manly Residence Hall',
            'McClinton Residence Hall',
            'McIver Residence Hall',
            'Old East Residence Hall',
            'Old West Residence Hall',
            'Ruffin Jr Residence Hall',
            'Spencer Residence Hall',
            'Stacy Residence Hall',
            'Winston Residence Hall',
        ],
        'Mid-Campus': [
            'Avery Residence Hall',
            'Carmichael Residence Hall',
            'Parker Residence Hall',
            'Teague Residence Hall',
        ],
        'South Campus': [
            'Baity Hill 1101 Mason Farm Road',
            'Baity Hill 1351 Mason Farm Road',
            'Baity Hill 1401 Mason Farm Road',
            'Baity Hill 1501 Mason Farm Road',
            'Baity Hill 1600 Student Fam. Housing',
            'Baity Hill 1700 Student Fam. Housing',
            'Baity Hill 1800 Student Fam. Housing',
            'Baity Hill 1900 Student Fam. Housing',
            'Baity Hill 2000 Student Fam. Housing',
            'Craige Residence Hall',
            'Craige North Residence Hall',
            'Ehringhaus Residence Hall',
            'Hardin Residence Hall',
            'Hinton James Residence Hall',
            'Horton Residence Hall',
            'Koury Residence Hall',
            'Morrison Residence Hall',
            'Ram Village 1',
            'Ram Village 2',
            'Ram Village 3',
            'Ram Village 5',
            'Taylor Hall',
        ],
    },
}
