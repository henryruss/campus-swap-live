"""
seed_db.py — Campus Swap local development seed file

Wipes the local database and rebuilds a full fake dataset for visual testing.
Designed to stress-test the route planner with 25+ sellers, full shift schedule,
varied item mixes, and all account types needed for admin inspection.

SAFETY: Refuses to run if DATABASE_URL contains 'render.com' or 'amazonaws'
to prevent accidental production wipes.

Usage:
    python seed_db.py

Workflow:
    flask db upgrade      # apply migrations first
    python seed_db.py     # wipe and rebuild
    flask run             # everything ready

Fixed credentials seeded every run:
    Super admin:  admin@test.com        / password
    Worker:       worker1@unc.edu       / password  (mover)
    Worker:       worker2@unc.edu       / password  (organizer)
    Worker:       worker3@unc.edu       / password
    Worker:       worker4@unc.edu       / password
    Seller:       seller_am@test.com    / password  (week1, morning, Granville Towers)
    Seller:       seller_pm@test.com    / password  (week1, afternoon, off-campus)
"""

import os
import sys
import random
from datetime import date, datetime, timedelta, timezone

# ── Safety guard ──────────────────────────────────────────────────────────────
db_url = os.environ.get('DATABASE_URL', '')
if any(x in db_url for x in ['render.com', 'amazonaws', 'heroku', 'railway']):
    print("🚨 REFUSING TO RUN: DATABASE_URL looks like a production database.")
    print(f"   URL: {db_url[:60]}...")
    print("   This script is for local development only.")
    sys.exit(1)

# ── App bootstrap ─────────────────────────────────────────────────────────────
from app import app, db
from models import (
    User, InventoryItem, InventoryCategory, InventoryCategory,
    AppSetting, ShiftWeek, Shift, ShiftAssignment, ShiftPickup,
    WorkerApplication, WorkerAvailability, StorageLocation,
)
try:
    from constants import OFF_CAMPUS_COMPLEXES
except ImportError:
    OFF_CAMPUS_COMPLEXES = ['The Lofts at 140', 'Shortbread Lofts', 'Carraway Village',
                            'Chapel Hill North', 'Greenbridge', 'Lot 5', 'Granville Towers']

# ── Coordinate data for Chapel Hill area ─────────────────────────────────────
# (lat, lng) for realistic clustering
DORM_COORDS = {
    'Granville Towers':     (35.9155, -79.0521),
    'Ehringhaus':           (35.9098, -79.0534),
    'Morrison':             (35.9071, -79.0548),
    'Craige':               (35.9082, -79.0562),
    'Hinton James':         (35.9047, -79.0488),
    'Avery':                (35.9123, -79.0501),
    'Carmichael':           (35.9110, -79.0577),
    'Cobb':                 (35.9135, -79.0512),
}

PARTNER_APT_COORDS = {
    'The Lofts at 140':     (35.9210, -79.0598),
    'Shortbread Lofts':     (35.9195, -79.0582),
    'Carraway Village':     (35.9232, -79.0611),
    'Chapel Hill North':    (35.9178, -79.0557),
}

OFF_CAMPUS_ADDRESSES = [
    ('412 W Franklin St, Chapel Hill, NC',   35.9142, -79.0578),
    ('201 S Columbia St, Chapel Hill, NC',   35.9118, -79.0521),
    ('311 Pittsboro St, Chapel Hill, NC',    35.9103, -79.0544),
    ('105 Mason Farm Rd, Chapel Hill, NC',   35.9067, -79.0531),
    ('88 Laurel Hill Rd, Chapel Hill, NC',   35.9088, -79.0612),
    ('220 Estes Dr, Chapel Hill, NC',        35.9199, -79.0489),
    ('450 Meadowmont Ln, Chapel Hill, NC',   35.9231, -79.0433),
]

ITEM_DATA = {
    'Couch / Sofa': [
        ('Grey sectional couch', 'Comfortable grey sectional, seats 4. Some wear on armrests but in great condition overall. Perfect for a living room or common area.', 150),
        ('Blue velvet couch', 'Beautiful blue velvet couch, lightly used. No stains, non-smoking home.', 200),
        ('IKEA EKTORP sofa', 'Classic IKEA sofa in beige. Slipcover is washable. Light use, 2 years old.', 120),
        ('Futon couch/bed', 'Convertible futon in dark brown. Doubles as a guest bed. Easy to move.', 80),
    ],
    'Mini Fridge': [
        ('Galanz 3.1 cu ft mini fridge', 'Black mini fridge with small freezer compartment. Works perfectly, very clean inside.', 75),
        ('Insignia mini fridge', '2.6 cu ft, stainless steel finish. Quiet motor, energy efficient.', 65),
        ('Magic Chef mini fridge with freezer', 'Great for dorm or small apartment. Holds a good amount, runs cold.', 55),
    ],
    'Dresser': [
        ('6-drawer IKEA HEMNES dresser', 'White, solid wood. All drawers open and close smoothly. Minor scuff on top.', 90),
        ('4-drawer dark wood dresser', 'Sturdy dark walnut finish dresser. Fits a lot of clothes. 36" wide.', 70),
        ('IKEA MALM 6-drawer dresser', 'White high gloss. Smooth-running drawers. 2 years old.', 85),
    ],
    'Desk': [
        ('IKEA MICKE desk', 'White desk with cable management. 28" x 50". Good working condition.', 60),
        ('Standing desk converter', 'Flexispot sit-stand desk riser. Adjustable height, fits monitors.', 80),
        ('Wooden corner desk', 'L-shaped corner desk, light oak finish. Plenty of surface area.', 75),
    ],
    'Microwave': [
        ('Toshiba 0.9 cu ft microwave', 'Compact black microwave, 900 watts. Works great, very clean.', 35),
        ('Amazon Basics microwave', '700 watt, small footprint. Great for dorms. Barely used.', 30),
        ('Panasonic microwave 1.2 cu ft', 'Full size microwave, stainless finish. Inverter technology for even heating.', 45),
    ],
    'Chair': [
        ('Ergonomic desk chair', 'Black mesh back, lumbar support, adjustable height. Used for one school year.', 60),
        ('Accent armchair', 'Mustard yellow accent chair. Great condition, like new.', 85),
        ('Bean bag chair', 'Large navy bean bag. Filled and ready to use. Great for gaming or lounging.', 40),
    ],
    'Bookshelf': [
        ('IKEA KALLAX 4x2 shelf unit', 'White, 8 cubbies. Great for storage, fits cube bins.', 55),
        ('5-shelf standing bookcase', 'Black metal and wood, industrial style. Sturdy and stylish.', 65),
        ('IKEA BILLY bookcase', 'White, tall. Adjustable shelves. Classic dorm staple.', 45),
    ],
    'TV': [
        ('TCL 43" 4K Roku TV', 'Smart TV with built-in Roku. Excellent picture, remote included.', 120),
        ('Samsung 32" HD TV', 'Perfect dorm size. HDMI ports, remote included. Works perfectly.', 80),
        ('Vizio 50" 4K TV', 'Great picture quality. Includes wall mount bracket.', 150),
    ],
    'Lamp': [
        ('Arc floor lamp', 'Modern arc lamp with white shade. Great for living room. Bulb included.', 35),
        ('LED desk lamp', 'Adjustable brightness, USB charging port. Like new.', 25),
        ('Tripod floor lamp', 'Industrial style, matte black. 65" tall. Creates great ambiance.', 40),
    ],
    'Miscellaneous': [
        ('Keurig K-Mini coffee maker', 'Single serve, black. Works great. Includes descaling solution.', 30),
        ('Instant Pot 6 quart', 'Duo 7-in-1. Used occasionally. All accessories included.', 50),
        ('Dyson V7 cordless vacuum', 'Lightweight, powerful suction. Battery holds charge well.', 100),
        ('Full-length mirror', 'Leaning mirror, 65" tall, black frame. No cracks or chips.', 45),
        ('Dish drying rack', 'Stainless steel 2-tier dish rack. Holds lots, drains well.', 20),
    ],
}

# ── Chapel Hill dorm names ────────────────────────────────────────────────────
DORMS = list(DORM_COORDS.keys())
PARTNER_APTS = list(PARTNER_APT_COORDS.keys())
ACCESS_TYPES = ['elevator', 'stairs_only', 'ground_floor']
TIME_PREFS = ['morning', 'afternoon', 'evening']
YEARS = ['freshman', 'sophomore', 'junior', 'senior', 'grad']

FIRST_NAMES = [
    'Alex', 'Jordan', 'Taylor', 'Morgan', 'Casey', 'Riley', 'Avery', 'Quinn',
    'Peyton', 'Skyler', 'Cameron', 'Drew', 'Blake', 'Reese', 'Logan', 'Jamie',
    'Parker', 'Sam', 'Bailey', 'Emerson', 'Harper', 'Finley', 'River', 'Sage',
    'Dakota', 'Kendall', 'Rowan', 'Ellis', 'Hayden', 'Lennon',
]
LAST_NAMES = [
    'Johnson', 'Williams', 'Brown', 'Jones', 'Garcia', 'Miller', 'Davis',
    'Wilson', 'Moore', 'Anderson', 'Taylor', 'Thomas', 'Jackson', 'White',
    'Harris', 'Martin', 'Thompson', 'Young', 'Robinson', 'Lewis',
]


def random_name():
    return f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"


def random_phone():
    return f"919{random.randint(1000000, 9999999)}"


def make_seller(email, full_name, pickup_week, time_pref, location_type,
                dorm=None, partner_building=None, address=None,
                lat=None, lng=None, access_type=None, floor=None,
                payout_rate=20):
    u = User(
        email=email,
        full_name=full_name,
        phone=random_phone(),
        is_seller=True,
        pickup_week=pickup_week,
        pickup_time_preference=time_pref,
        pickup_location_type=location_type,
        pickup_dorm=dorm,
        pickup_partner_building=partner_building,
        pickup_address=address,
        pickup_lat=lat,
        pickup_lng=lng,
        pickup_access_type=access_type or random.choice(ACCESS_TYPES),
        pickup_floor=floor or random.randint(1, 6),
        payout_rate=payout_rate,
        payout_method='venmo',
        payout_handle=f'@{full_name.replace(" ", "").lower()}',
    )
    u.set_password('password')
    return u


def add_items_for_seller(seller, categories_by_name, num_items=None):
    """Add 1–4 available items for a seller, drawn from realistic categories."""
    if num_items is None:
        num_items = random.randint(1, 4)
    category_names = list(ITEM_DATA.keys())
    chosen_cats = random.sample(category_names, min(num_items, len(category_names)))
    items = []
    for cat_name in chosen_cats:
        cat = categories_by_name.get(cat_name)
        if not cat:
            continue
        title, desc, base_price = random.choice(ITEM_DATA[cat_name])
        price = base_price + random.randint(-10, 20)
        item = InventoryItem(
            description=title,
            long_description=desc,
            price=price,
            suggested_price=price + random.randint(0, 15),
            quality=random.randint(3, 5),
            status='available',
            seller_id=seller.id,
            category_id=cat.id,
            collection_method='free',
            pickup_week=seller.pickup_week,
            photo_url='https://placehold.co/400x300/e8f5e9/2e7d32?text=Item+Photo',
        )
        items.append(item)
    return items


with app.app_context():

    # ── Ensure schema exists (handles the case where tests dropped all tables
    #    but left alembic_version intact, causing flask db upgrade to no-op) ──
    db.create_all()

    # ── Wipe everything ───────────────────────────────────────────────────────
    print("🗑  Wiping database...")

    # Drop in FK-safe order
    from sqlalchemy import text
    tables_in_order = [
        'intake_flag', 'intake_record', 'shift_pickup', 'shift_run',
        'shift_assignment', 'worker_preference', 'worker_availability',
        'worker_application', 'shift', 'shift_week',
        'item_reservation', 'item_photo', 'inventory_item',
        'referral', 'buyer_order', 'shop_notify_signup',
        'seller_alert', 'digest_log', 'admin_email',
        'storage_location', 'app_setting', 'upload_session', 'temp_upload',
        '"user"',
        'inventory_category',
    ]
    for table in tables_in_order:
        try:
            db.session.execute(text(f'DELETE FROM {table}'))
        except Exception as e:
            db.session.rollback()
            print(f"   ⚠ Could not wipe {table}: {e}")
    db.session.commit()
    print("   ✓ Database wiped")

    # ── AppSettings ───────────────────────────────────────────────────────────
    print("⚙️  Seeding AppSettings...")
    settings = {
        'truck_raw_capacity': '18',
        'truck_capacity_buffer_pct': '10',
        'route_am_window': '9am–1pm',
        'route_pm_window': '1pm–5pm',
        'maps_static_api_key': '',
        'drivers_per_truck': '2',
        'max_trucks_per_shift': '4',
        'shifts_required': '10',
        'referral_base_rate': '20',
        'referral_signup_bonus': '10',
        'referral_bonus_per_referral': '10',
        'referral_max_rate': '100',
        'referral_program_active': 'true',
        'reserve_only_mode': 'false',
        'pickup_period_active': 'true',
        'crew_applications_open': 'true',
        'current_store': 'UNC Chapel Hill',
        'warehouse_lat': '35.9049',
        'warehouse_lng': '-79.0469',
        'delivery_radius_miles': '50',
        'shop_teaser_mode': 'false',
    }
    for key, value in settings.items():
        AppSetting.set(key, value)
    db.session.commit()
    print(f"   ✓ {len(settings)} AppSettings seeded")

    # ── Categories ────────────────────────────────────────────────────────────
    print("📦 Seeding categories...")
    category_defaults = {
        'Couch / Sofa': 3.0,
        'Mattress (Full/Queen)': 2.0,
        'Mattress (Twin)': 1.5,
        'Dresser': 2.0,
        'Desk': 1.5,
        'Mini Fridge': 1.0,
        'Microwave': 0.5,
        'Chair': 1.0,
        'Bookshelf': 1.5,
        'TV': 0.5,
        'Lamp': 0.5,
        'Miscellaneous': 0.5,
    }
    categories_by_name = {}
    for name, unit_size in category_defaults.items():
        cat = InventoryCategory(name=name, default_unit_size=unit_size)
        db.session.add(cat)
        categories_by_name[name] = cat
    db.session.commit()
    print(f"   ✓ {len(categories_by_name)} categories seeded")

    # ── Storage location ──────────────────────────────────────────────────────
    print("🏭 Seeding storage location...")
    storage = StorageLocation(
        name='Campus Swap Main Storage',
        address='104 Airport Dr, Chapel Hill, NC 27599',
        location_note='Unit 14B — code is 4821. Loading dock on east side.',
        capacity_note='~80 items max. Keep large items near the door.',
        is_active=True,
        lat=35.9049,   # coordinates for nearest-neighbor stop ordering
        lng=-79.0469,
    )
    db.session.add(storage)
    db.session.commit()
    print(f"   ✓ Storage location: {storage.name}")

    # ── Admin account ─────────────────────────────────────────────────────────
    print("👤 Seeding admin account...")
    admin = User(
        email='admin@test.com',
        full_name='Admin User',
        phone='9195551234',
        is_admin=True,
        is_super_admin=True,
    )
    admin.set_password('password')
    db.session.add(admin)
    db.session.commit()
    print("   ✓ admin@test.com / password")

    # ── Worker accounts ───────────────────────────────────────────────────────
    print("👷 Seeding worker accounts...")
    worker_data = [
        ('worker1@unc.edu', 'Marcus Johnson', '9195550001'),
        ('worker2@unc.edu', 'Priya Patel',    '9195550002'),
        ('worker3@unc.edu', 'Tyler Brooks',   '9195550003'),
        ('worker4@unc.edu', 'Sofia Martinez', '9195550004'),
        ('worker5@unc.edu', 'James Kim',      '9195550005'),
        ('worker6@unc.edu', 'Olivia Chen',    '9195550006'),
        ('worker7@unc.edu', 'Ethan Davis',    '9195550007'),
        ('worker8@unc.edu', 'Ava Wilson',     '9195550008'),
    ]
    workers = []
    for email, name, phone in worker_data:
        w = User(
            email=email,
            full_name=name,
            phone=phone,
            is_worker=True,
            worker_status='approved',
            worker_role='both',
        )
        w.set_password('password')
        db.session.add(w)
        workers.append(w)
    db.session.commit()

    # Worker applications + availability
    for w in workers:
        app_record = WorkerApplication(
            user_id=w.id,
            unc_year=random.choice(YEARS),
            role_pref='both',
            why_blurb='I want to help out and earn some cash during move-out.',
            applied_at=datetime.now(timezone.utc) - timedelta(days=14),
            reviewed_at=datetime.now(timezone.utc) - timedelta(days=10),
            reviewed_by=admin.id,
        )
        db.session.add(app_record)
        avail = WorkerAvailability(
            user_id=w.id,
            week_start=None,
            mon_am=True, mon_pm=True,
            tue_am=True, tue_pm=random.choice([True, False]),
            wed_am=True, wed_pm=True,
            thu_am=random.choice([True, False]), thu_pm=True,
            fri_am=True, fri_pm=True,
            sat_am=True, sat_pm=random.choice([True, False]),
            sun_am=False, sun_pm=False,
        )
        db.session.add(avail)
    db.session.commit()
    print(f"   ✓ {len(workers)} workers seeded (worker1@unc.edu … worker8@unc.edu / password)")

    # ── Shift schedule ────────────────────────────────────────────────────────
    print("📅 Seeding shift schedule...")

    week1 = ShiftWeek(
        week_start=date(2026, 4, 27),
        status='published',
        created_by_id=admin.id,
    )
    week2 = ShiftWeek(
        week_start=date(2026, 5, 4),
        status='published',
        created_by_id=admin.id,
    )
    db.session.add_all([week1, week2])
    db.session.flush()

    # Week 1: Mon–Fri, AM + PM, 2 trucks each
    # Week 2: Mon–Thu, AM + PM, 2 trucks each
    shift_map = {}  # (week_label, day, slot) → Shift
    week1_days = ['mon', 'tue', 'wed', 'thu', 'fri']
    week2_days = ['mon', 'tue', 'wed', 'thu']

    for day in week1_days:
        for slot in ['am', 'pm']:
            s = Shift(week_id=week1.id, day_of_week=day, slot=slot,
                      trucks=2, is_active=True)
            db.session.add(s)
            shift_map[('week1', day, slot)] = s

    for day in week2_days:
        for slot in ['am', 'pm']:
            s = Shift(week_id=week2.id, day_of_week=day, slot=slot,
                      trucks=2, is_active=True)
            db.session.add(s)
            shift_map[('week2', day, slot)] = s

    db.session.flush()

    # Assign workers to shifts (movers to trucks, organizers separate)
    worker_pool = list(workers)
    random.shuffle(worker_pool)
    all_shifts = list(shift_map.values())

    for i, shift in enumerate(all_shifts[:8]):  # staff first 8 shifts
        w1 = worker_pool[(i * 2) % len(worker_pool)]
        w2 = worker_pool[(i * 2 + 1) % len(worker_pool)]
        org = worker_pool[(i + 4) % len(worker_pool)]
        a1 = ShiftAssignment(shift_id=shift.id, worker_id=w1.id,
                             role_on_shift='driver', truck_number=1,
                             assigned_by_id=admin.id)
        a2 = ShiftAssignment(shift_id=shift.id, worker_id=w2.id,
                             role_on_shift='driver', truck_number=1,
                             assigned_by_id=admin.id)
        a3 = ShiftAssignment(shift_id=shift.id, worker_id=org.id,
                             role_on_shift='organizer',
                             assigned_by_id=admin.id)
        db.session.add_all([a1, a2, a3])

        # Assign storage unit to truck 1
        import json
        shift.truck_unit_plan = json.dumps({"1": storage.id, "2": storage.id})

    db.session.commit()
    print(f"   ✓ {len(all_shifts)} shifts across 2 weeks, first 8 staffed")

    # ── Sellers ───────────────────────────────────────────────────────────────
    print("🛋  Seeding sellers...")
    sellers = []

    # --- Fixed seller for reliable testing ---
    fixed_am = make_seller(
        'seller_am@test.com', 'Henry Test Seller',
        'week1', 'morning', 'on_campus',
        dorm='Granville Towers',
        lat=DORM_COORDS['Granville Towers'][0],
        lng=DORM_COORDS['Granville Towers'][1],
        access_type='elevator', floor=4,
    )
    db.session.add(fixed_am)
    db.session.flush()
    for item in add_items_for_seller(fixed_am, categories_by_name, num_items=3):
        db.session.add(item)
    sellers.append(fixed_am)

    fixed_pm = make_seller(
        'seller_pm@test.com', 'PM Test Seller',
        'week1', 'afternoon', 'off_campus_other',
        address='412 W Franklin St, Chapel Hill, NC',
        lat=35.9142, lng=-79.0578,
        access_type='stairs_only', floor=2,
    )
    db.session.add(fixed_pm)
    db.session.flush()
    for item in add_items_for_seller(fixed_pm, categories_by_name, num_items=2):
        db.session.add(item)
    sellers.append(fixed_pm)

    # --- On-campus dorm sellers (week 1, varied time prefs) ---
    dorm_sellers_week1 = [
        # Granville cluster — 5 sellers
        ('Granville Towers', 'week1', 'morning'),
        ('Granville Towers', 'week1', 'morning'),
        ('Granville Towers', 'week1', 'morning'),
        ('Granville Towers', 'week1', 'afternoon'),
        ('Granville Towers', 'week1', 'afternoon'),
        # Ehringhaus cluster — 3 sellers
        ('Ehringhaus', 'week1', 'morning'),
        ('Ehringhaus', 'week1', 'morning'),
        ('Ehringhaus', 'week1', 'afternoon'),
        # Morrison cluster — 3 sellers
        ('Morrison', 'week1', 'morning'),
        ('Morrison', 'week1', 'afternoon'),
        ('Morrison', 'week1', 'evening'),
        # Scattered dorms
        ('Craige', 'week1', 'morning'),
        ('Hinton James', 'week1', 'afternoon'),
        ('Avery', 'week1', 'morning'),
        ('Carmichael', 'week1', 'afternoon'),
        ('Cobb', 'week1', 'morning'),
    ]
    for i, (dorm, week, time_pref) in enumerate(dorm_sellers_week1):
        lat, lng = DORM_COORDS[dorm]
        lat += random.uniform(-0.0005, 0.0005)
        lng += random.uniform(-0.0005, 0.0005)
        seller = make_seller(
            f'dorm_w1_{i}@test.com', random_name(),
            week, time_pref, 'on_campus',
            dorm=dorm, lat=lat, lng=lng,
            access_type=random.choice(ACCESS_TYPES),
            floor=random.randint(1, 8),
        )
        db.session.add(seller)
        db.session.flush()
        for item in add_items_for_seller(seller, categories_by_name):
            db.session.add(item)
        sellers.append(seller)

    # --- Partner apartment sellers (week 1) ---
    partner_sellers = [
        ('The Lofts at 140', 'week1', 'morning'),
        ('The Lofts at 140', 'week1', 'morning'),
        ('The Lofts at 140', 'week1', 'afternoon'),
        ('Shortbread Lofts', 'week1', 'morning'),
        ('Shortbread Lofts', 'week1', 'afternoon'),
        ('Carraway Village', 'week1', 'morning'),
        ('Chapel Hill North', 'week1', 'afternoon'),
    ]
    for i, (building, week, time_pref) in enumerate(partner_sellers):
        lat, lng = PARTNER_APT_COORDS[building]
        lat += random.uniform(-0.0003, 0.0003)
        lng += random.uniform(-0.0003, 0.0003)
        seller = make_seller(
            f'apt_w1_{i}@test.com', random_name(),
            week, time_pref, 'off_campus_complex',
            dorm=building,
            partner_building=building,
            lat=lat, lng=lng,
            access_type=random.choice(ACCESS_TYPES),
            floor=random.randint(1, 4),
        )
        db.session.add(seller)
        db.session.flush()
        for item in add_items_for_seller(seller, categories_by_name):
            db.session.add(item)
        sellers.append(seller)

    # --- Off-campus other sellers (week 1) ---
    for i, (address, lat, lng) in enumerate(OFF_CAMPUS_ADDRESSES[:4]):
        time_pref = random.choice(TIME_PREFS)
        seller = make_seller(
            f'offcampus_w1_{i}@test.com', random_name(),
            'week1', time_pref, 'off_campus_other',
            address=address, lat=lat, lng=lng,
            access_type='ground_floor', floor=1,
        )
        db.session.add(seller)
        db.session.flush()
        for item in add_items_for_seller(seller, categories_by_name):
            db.session.add(item)
        sellers.append(seller)

    # --- Week 2 sellers ---
    week2_dorms = [
        ('Granville Towers', 'morning'), ('Granville Towers', 'morning'),
        ('Ehringhaus', 'afternoon'), ('Morrison', 'morning'),
        ('Craige', 'afternoon'), ('Hinton James', 'morning'),
    ]
    for i, (dorm, time_pref) in enumerate(week2_dorms):
        lat, lng = DORM_COORDS[dorm]
        lat += random.uniform(-0.0005, 0.0005)
        lng += random.uniform(-0.0005, 0.0005)
        seller = make_seller(
            f'dorm_w2_{i}@test.com', random_name(),
            'week2', time_pref, 'on_campus',
            dorm=dorm, lat=lat, lng=lng,
            access_type=random.choice(ACCESS_TYPES),
            floor=random.randint(1, 6),
        )
        db.session.add(seller)
        db.session.flush()
        for item in add_items_for_seller(seller, categories_by_name):
            db.session.add(item)
        sellers.append(seller)

    week2_apts = [
        ('The Lofts at 140', 'morning'), ('Shortbread Lofts', 'afternoon'),
    ]
    for i, (building, time_pref) in enumerate(week2_apts):
        lat, lng = PARTNER_APT_COORDS[building]
        seller = make_seller(
            f'apt_w2_{i}@test.com', random_name(),
            'week2', time_pref, 'off_campus_complex',
            dorm=building, partner_building=building,
            lat=lat, lng=lng,
            access_type='elevator', floor=random.randint(1, 4),
        )
        db.session.add(seller)
        db.session.flush()
        for item in add_items_for_seller(seller, categories_by_name):
            db.session.add(item)
        sellers.append(seller)

    # --- Seller with no pickup week (should be excluded from route builder) ---
    no_week_seller = make_seller(
        'seller_noweek@test.com', 'No Week Seller',
        None, None, 'on_campus',
        dorm='Morrison',
        lat=DORM_COORDS['Morrison'][0],
        lng=DORM_COORDS['Morrison'][1],
    )
    no_week_seller.pickup_time_preference = None
    db.session.add(no_week_seller)
    db.session.flush()
    item = InventoryItem(
        description='Desk lamp', status='available',
        seller_id=no_week_seller.id,
        category_id=categories_by_name['Lamp'].id,
        price=25, collection_method='free',
        photo_url='https://placehold.co/400x300/e8f5e9/2e7d32?text=Item+Photo',
    )
    db.session.add(item)
    sellers.append(no_week_seller)

    db.session.commit()

    total_sellers = len(sellers)
    total_items = InventoryItem.query.filter_by(status='available').count()
    print(f"   ✓ {total_sellers} sellers seeded ({total_items} available items)")
    print(f"   ✓ seller_am@test.com / password  (week1 morning, Granville Towers)")
    print(f"   ✓ seller_pm@test.com / password  (week1 afternoon, off-campus)")
    print(f"   ✓ seller_noweek@test.com          (no pickup week — excluded from route builder)")

    # ── Summary ───────────────────────────────────────────────────────────────
    week1_sellers = User.query.filter_by(pickup_week='week1').count()
    week2_sellers = User.query.filter_by(pickup_week='week2').count()
    morning_sellers = User.query.filter_by(pickup_time_preference='morning').count()
    afternoon_sellers = User.query.filter_by(pickup_time_preference='afternoon').count()

    print()
    print("✅ Seed complete!")
    print()
    print("  Accounts:")
    print("    admin@test.com / password           → super admin")
    print("    worker1@unc.edu … worker8@unc.edu / password → approved workers")
    print("    seller_am@test.com / password       → week1, morning, Granville Towers")
    print("    seller_pm@test.com / password       → week1, afternoon, off-campus")
    print()
    print("  Dataset:")
    print(f"    {total_sellers} sellers total")
    print(f"    {week1_sellers} week1 sellers  |  {week2_sellers} week2 sellers")
    print(f"    {morning_sellers} morning  |  {afternoon_sellers} afternoon")
    print(f"    {total_items} available items")
    print(f"    {len(all_shifts)} shifts across 2 weeks (all unassigned — run auto-assign to populate)")
    print(f"    {len(workers)} approved workers")
    print(f"    1 storage location")
    print()
    print("  Next steps:")
    print("    flask run")
    print("    → /admin/routes to run auto-assignment and inspect the route planner")
    print("    → /admin/crew/schedule to view the shift schedule")
    print("    → /admin to see the full admin panel")
