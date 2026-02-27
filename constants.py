"""
Application-wide constants for Campus Swap
"""

# Payout Configuration (by collection method)
PAYOUT_PERCENTAGE_ONLINE = 0.50   # Sellers receive 50% when submitting through site
PAYOUT_PERCENTAGE_IN_PERSON = 0.33  # Sellers receive 33% for in-person drop-offs (Campus Swap takes 67%)
PAYOUT_PERCENTAGE = 0.50  # Legacy alias; use PAYOUT_PERCENTAGE_ONLINE

# Capacity Limits
WAREHOUSE_CAPACITY = 2000   # Total items we can physically store and sell at our warehouse
POD_CAPACITY = 250          # Total items that can be held across all campus PODs at once

# Free Tier Configuration
PAYOUT_PERCENTAGE_FREE = 0.20  # Free-tier sellers receive 20% (space-permitting pickup)
FREE_TIER_MAX_ITEMS = 3        # Max items a free-tier seller can list


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

# Pod change deadline: users can change their drop-off pod until this date (month, day)
POD_CHANGE_DEADLINE = (4, 20)  # April 20th
POD_CHANGE_DEADLINE_DISPLAY = 'April 20th'

# Recommended price ranges by category (min, max) in dollars.
# Keys match category names (case-insensitive, partial match).
PRICE_RANGES = {
    # Furniture
    "couch": (50, 150),
    "sofa": (50, 150),
    "headboard": (25, 80),
    "mattress": (40, 120),
    "rug": (20, 60),
    # Electronics
    "television": (50, 150),
    "tv": (50, 150),
    "gaming": (80, 250),
    "console": (80, 250),
    "printer": (15, 40),
    # Kitchen
    "mini fridge": (40, 80),
    "minifridge": (40, 80),
    "microwave": (15, 35),
    "air fryer": (15, 40),
    # Climate
    "ac unit": (30, 80),
    "ac": (30, 80),
    "heater": (15, 40),
}

# Generic fallback for categories without a specific range
PRICE_RANGE_FALLBACK = (20, 100)


def get_price_range_for_category(category_name: str) -> tuple[int, int]:
    """Return (min, max) price range for a category, or None if no match.
    Uses case-insensitive partial matching on category name."""
    if not category_name:
        return PRICE_RANGE_FALLBACK
    name_lower = category_name.lower()
    for key, value in PRICE_RANGES.items():
        if key in name_lower:
            return value
    return PRICE_RANGE_FALLBACK

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
