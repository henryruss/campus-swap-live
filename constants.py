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

# Homepage curation limits
HOMEPAGE_FEATURED_LIMIT = 12  # max items in the foreground curated grid
HOMEPAGE_HERO_TILE_LIMIT = 12  # max photo tiles in the hero mosaic background

# Category names excluded from hero mosaic tiles (decorative/misc items don't read well as background)
HOMEPAGE_MOSAIC_EXCLUDE_CATEGORIES = {'Other'}

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
    ('week4', 'May 18 – May 24'),
    ('week5', 'May 25 – May 31'),
    ('week6', 'June 1 – June 7'),
    ('week7', 'June 8 – June 14'),
    ('week8', 'June 15 – June 21'),
    ('week9', 'June 22 – June 28'),
    ('week10', 'June 29 – June 30'),
]

# Date ranges for each pickup week (used for moveout_date validation)
PICKUP_WEEK_DATE_RANGES = {
    'week1': ('2026-04-27', '2026-05-03'),
    'week2': ('2026-05-04', '2026-05-10'),
    'week3': ('2026-05-11', '2026-05-17'),
    'week4': ('2026-05-18', '2026-05-24'),
    'week5': ('2026-05-25', '2026-05-31'),
    'week6': ('2026-06-01', '2026-06-07'),
    'week7': ('2026-06-08', '2026-06-14'),
    'week8': ('2026-06-15', '2026-06-21'),
    'week9': ('2026-06-22', '2026-06-28'),
    'week10': ('2026-06-29', '2026-06-30'),
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

# Known off-campus apartment complexes (validated server-side for off_campus_complex branch)
OFF_CAMPUS_COMPLEXES = [
    "Granville Towers",
    "Lark Chapel Hill Apartments",
    "The Warehouse",
    "The Edition on Rosemary",
    "Shortbread Lofts",
    "Union Chapel Hill",
    "Carolina Square",
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


# ─────────────────────────────────────────────────────────────────────────────
# FACEBOOK MARKETPLACE EXPORT
# Used only by /admin/fb-export to build copy-paste listing data for a worker who
# manually recreates live shop listings on Facebook Marketplace.
# ─────────────────────────────────────────────────────────────────────────────

# Shipping component added to the site price before the markup multiplier.
# Tiered rather than flat: median site price is ~$55 and ~47% of inventory is under $50,
# so a flat $15 would be ~94% of a $16 lamp but ~5% of a $287 couch — punishing cheap
# items and barely touching the ones with real margin. Tiers hold markup near 25-30%
# across the whole catalog. Evaluated in order; first matching upper bound wins.
# (upper_bound_exclusive | None for "no upper bound", dollars_added)
FB_SHIPPING_TIERS = [
    (50, 5),
    (100, 10),
    (None, 15),
]

# Multiplier applied after the tier add. Overridable at runtime via the
# `fb_price_markup` AppSetting; this is the fallback default.
FB_PRICE_MARKUP_DEFAULT = 1.1

# Every item is listed as this condition. `quality` defaults to 1 and the vast majority
# of shop-visible items sit at that default with zero rows at quality 2, so quality==1
# means "never assessed", not "poor" — and quality_to_label() would otherwise tag ~76%
# of a professionally rephotographed catalog as "Fair" on Facebook. Nothing is new and
# nothing is bad, so one honest value is used and the worker gets no dropdown.
FB_CONDITION_DEFAULT = 'Used - Good'

# Closing block appended to every FB description. Rotated per item (by item id) rather than
# reused verbatim: a byte-identical block across hundreds of listings is trivially
# fingerprintable, and "same text + same outbound link, repeated many times" is the signature
# Marketplace spam detection targets. Varying the prose weakens that signal — it does NOT
# eliminate it, since the URL itself stays constant. Posting velocity is the bigger lever.
#
# Every variant must state: the 30-mile Chapel Hill radius, the shop URL, and that more
# inventory is listed there. No emojis — they render inconsistently in FB descriptions.
FB_CTA_VARIANTS = [
    (
        "Local delivery available within 30 miles of Chapel Hill.\n"
        "\n"
        "Delivery and discounts available through our website:\n"
        "https://usecampusswap.com/shop\n"
        "\n"
        "Hundreds more dorm and apartment items listed there, with full photos, sizes,\n"
        "and delivery pricing on every listing."
    ),
    (
        "We deliver anywhere within 30 miles of Chapel Hill.\n"
        "\n"
        "Book delivery and see current discounts on our site:\n"
        "https://usecampusswap.com/shop\n"
        "\n"
        "That is where our full inventory lives. Hundreds of dorm and apartment pieces,\n"
        "each with measurements and a delivery quote up front."
    ),
    (
        "Delivery available to any address within 30 miles of Chapel Hill.\n"
        "\n"
        "Full catalog, delivery booking, and bundle discounts:\n"
        "https://usecampusswap.com/shop\n"
        "\n"
        "We keep hundreds of dorm and apartment items listed there, every one with\n"
        "dimensions and an upfront delivery price."
    ),
    (
        "Delivering across Chapel Hill and everywhere inside a 30 mile radius.\n"
        "\n"
        "Check the site for delivery options and this week's discounts:\n"
        "https://usecampusswap.com/shop\n"
        "\n"
        "Hundreds more move-out furniture pieces and dorm essentials are listed, with\n"
        "full measurements and delivery pricing shown before you buy."
    ),
]

# Kept as the fallback single value (and for callers that want one canonical block).
FB_CTA_DEFAULT = FB_CTA_VARIANTS[0]

# "Parent > Subcategory" -> the leaf category name the worker types into Facebook's
# search-as-you-type category picker. Facebook's taxonomy shifts over time; unmapped
# keys fall back to showing the raw Campus Swap category with a "verify on FB" note
# rather than silently guessing. See _fb_category().
FB_CATEGORY_MAP = {
    'Bedroom > Mattress':                                  'Beds & Mattresses',
    'Bedroom > Headboard':                                 'Beds & Mattresses',
    'Bedroom > Other Bedroom':                             'Bedroom Furniture',
    'Furniture > Couch / Sofa':                            'Sofas',
    'Furniture > Futon':                                   'Sofas',
    'Furniture > Armchair / Accent Chair':                  'Chairs',
    'Furniture > Desk Chair':                              'Office Chairs',
    'Furniture > Gaming Chair':                            'Office Chairs',
    'Furniture > Desk':                                    'Desks',
    'Furniture > Dresser':                                 'Dressers & Armoires',
    'Furniture > Bookshelf / Shelving':                    'Bookcases & Shelving',
    'Furniture > Coffee Table':                            'Coffee Tables',
    'Furniture > Side Table':                              'End & Side Tables',
    'Furniture > TV Stand / Media Console':                'TV Stands & Entertainment Centers',
    'Furniture > Storage Ottoman':                         'Ottomans & Benches',
    'Furniture > Other Furniture':                         'Furniture',
    'Kitchen & Appliances > Mini Fridge':                  'Refrigerators',
    'Kitchen & Appliances > Microwave':                    'Microwaves',
    'Kitchen & Appliances > Air Fryer':                    'Small Kitchen Appliances',
    'Kitchen & Appliances > Toaster Oven':                 'Small Kitchen Appliances',
    'Kitchen & Appliances > Coffee Maker / Espresso Machine': 'Small Kitchen Appliances',
    'Kitchen & Appliances > Blender':                      'Small Kitchen Appliances',
    'Kitchen & Appliances > Instant Pot / Rice Cooker':    'Small Kitchen Appliances',
    'Kitchen & Appliances > Knife Set':                    'Kitchen & Dining',
    'Kitchen & Appliances > Other Kitchen':                'Kitchen & Dining',
    'Climate & Comfort > Portable AC Unit':                'Heating & Cooling',
    'Climate & Comfort > Space Heater':                    'Heating & Cooling',
    'Climate & Comfort > Tower Fan':                       'Heating & Cooling',
    'Climate & Comfort > Humidifier / Dehumidifier':       'Heating & Cooling',
    'Climate & Comfort > Other Climate':                   'Heating & Cooling',
    'Electronics > TV':                                    'TVs',
    'Electronics > Monitor':                               'Computer Monitors',
    'Electronics > Laptop':                                'Laptops',
    'Electronics > Keyboard / Mouse':                      'Computer Accessories',
    'Electronics > Printer / Scanner':                     'Printers & Scanners',
    'Electronics > Speakers / Soundbar':                   'Audio Equipment',
    'Electronics > Headphones':                            'Headphones',
    'Electronics > Gaming Console':                        'Video Game Consoles',
    'Electronics > Other Electronics':                     'Electronics',
    'Rugs > Area Rug':                                     'Rugs',
    'Bikes & Scooters > Bike':                             'Bicycles',
    'Bikes & Scooters > Electric Scooter':                 'Scooters',
}

# Fallback for items whose subcategory is NULL or unmapped (the "Other" bucket — ~6% of the
# shop, and over a third of those are lamps). Matched against the lowercased title, first hit
# wins, so order these most-specific first. Purpose is to keep the worker on pure data entry
# instead of making a category judgment per item. Anything that misses every keyword falls
# through to a "choose it on Facebook" prompt rather than a misleading pasteable value.
FB_TITLE_KEYWORD_CATEGORIES = [
    ('desk lamp',      'Lamps'),
    ('floor lamp',     'Lamps'),
    ('table lamp',     'Lamps'),
    ('lamp',           'Lamps'),
    ('area rug',       'Rugs'),
    ('rug',            'Rugs'),
    ('shoe rack',      'Storage & Organization'),
    ('drawer tower',   'Storage & Organization'),
    ('storage bin',    'Storage & Organization'),
    ('shelf',          'Bookcases & Shelving'),
    ('shelving',       'Bookcases & Shelving'),
    ('bookcase',       'Bookcases & Shelving'),
    ('bar cart',       'Kitchen & Dining'),
    ('rolling cart',   'Storage & Organization'),
    ('cart',           'Storage & Organization'),
    ('mirror',         'Home Decor'),
    ('welcome mat',    'Home Decor'),
    ('mat',            'Home Decor'),
    ('cushion',        'Home Decor'),
    ('pillow',         'Home Decor'),
    ('curtain',        'Home Decor'),
    ('hamper',         'Household Supplies'),
    ('trash can',      'Household Supplies'),
    ('drying rack',    'Household Supplies'),
    ('fan',            'Heating & Cooling'),
    ('heater',         'Heating & Cooling'),
    ('bag',            'Bags & Luggage'),
    ('backpack',       'Bags & Luggage'),
    ('suitcase',       'Bags & Luggage'),
]


# ─────────────────────────────────────────────────────────────────────────────
# DELIVERY ZONES
# Fallback defaults for the `delivery_zone_boundaries` / `delivery_zone_fees`
# AppSettings, so a missing row never breaks checkout. Kept here (not inline in
# app.py) because the value is read from three separate places — inline copies are
# how the buyer-visibility filters drifted between /shop and /admin/fb-export.
#
# Upper bounds are inclusive and evaluated in order: <=5mi, <=10mi, <=15mi, <=20mi,
# <=30mi. Beyond the last boundary calculate_delivery_zone() returns None and
# checkout refuses the address.
#
# The 20-30 mile band was added 2026-08-05 so the radius matches what the Facebook
# Marketplace listings advertise. It is a 10-mile band (twice the width of the
# others), priced at $40 to keep the roughly $5-per-5-miles rate of the earlier
# zones. Override either list via AppSetting — no deploy needed.
# ─────────────────────────────────────────────────────────────────────────────
DELIVERY_ZONE_BOUNDARIES_DEFAULT = '5,10,15,20,30'
DELIVERY_ZONE_FEES_DEFAULT = '15,20,25,30,40'

# Fallback used when the boundaries setting is unparseable — keep in sync with the
# largest value above.
MAX_DELIVERY_MILES_DEFAULT = 30.0
