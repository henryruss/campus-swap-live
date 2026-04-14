"""
Application-wide constants for Campus Swap
"""
import re

# Payout Configuration (by collection method)
PAYOUT_PERCENTAGE_ONLINE = 0.50   # Sellers receive 50% when submitting through site
# PAYOUT_PERCENTAGE_IN_PERSON removed — pod drop-off option discontinued
PAYOUT_PERCENTAGE = 0.50  # Legacy alias; use PAYOUT_PERCENTAGE_ONLINE

# Capacity Limits
WAREHOUSE_CAPACITY = 2000   # Total items we can physically store and sell at our warehouse

# Free Tier Configuration
PAYOUT_PERCENTAGE_FREE = 0.20  # Free-tier sellers receive 20% (space-permitting pickup)


# Payment Configuration
SERVICE_FEE_CENTS = 1500  # $15 service fee (Pro plan — guarantees space + move-out pickup)
SELLER_ACTIVATION_FEE_CENTS = 1500  # Legacy alias

# File Upload Configuration
MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10MB
# JPG/JPEG/PNG/WebP work from desktop and phones (e.g. Android JPEG/WebP; iPhone use "Most Compatible" for JPEG)
ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'webp'}
ALLOWED_MIME_TYPES = {'image/jpeg', 'image/png', 'image/jpg', 'image/webp'}

# Video Upload Configuration
MAX_VIDEO_SIZE = 50 * 1024 * 1024  # 50MB
MAX_VIDEO_DURATION_SECONDS = 30
ALLOWED_VIDEO_EXTENSIONS = {'mp4', 'mov', 'webm'}
ALLOWED_VIDEO_MIME_TYPES = {'video/mp4', 'video/quicktime', 'video/webm'}

# Categories that require video upload (matched case-insensitive, partial match)
VIDEO_REQUIRED_CATEGORIES = [
    'tv', 'television', 'gaming console', 'printer', 'electronic',
    'mini fridge', 'fridge', 'microwave', 'heater', 'ac', 'air conditioner',
    'blender', 'scooter', 'air fryer'
]


def category_requires_video(category_name: str, subcategory_name: str = '') -> bool:
    """Return True if the category or subcategory requires a demo video upload."""
    names = ' '.join(n for n in (category_name, subcategory_name) if n).lower()
    if not names:
        return False
    return any(re.search(r'\b' + re.escape(key) + r'\b', names) for key in VIDEO_REQUIRED_CATEGORIES)


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
    ('week1', 'April 27 – May 3'),
    ('week2', 'May 4 – May 10'),
    ('week3', 'May 11 – May 17'),
]

# Date ranges for each pickup week (used for moveout_date validation)
PICKUP_WEEK_DATE_RANGES = {
    'week1': ('2026-04-27', '2026-05-03'),
    'week2': ('2026-05-04', '2026-05-10'),
    'week3': ('2026-05-11', '2026-05-17'),
}

# Time-of-day options for pickup preference
PICKUP_TIME_OPTIONS = ['am', 'pm', 'morning', 'afternoon', 'evening']

# Reserve-only mode: before this date (month, day), items are reserve-only (no Stripe charges)
RESERVE_ONLY_DEADLINE = (4, 20)  # April 20th

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
