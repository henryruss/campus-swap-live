"""
seed_dev.py — Full dev database seed.

Creates:
  - 1 admin user (admin@campusswap.dev / password: admin)
  - 6 sellers with varied payout rates, methods, and states
  - ~30 inventory items covering all status types
  - IntakeRecords and IntakeFlags on some sold items (for payout badge testing)
  - 3 storage locations
  - 12 approved workers with availability (same as seed_test_crew.py)

Safe to re-run — skips records that already exist by email.
To wipe and reseed cleanly: python3 reset_db.py && python3 seed_dev.py

Usage:
    python3 seed_dev.py
    python3 seed_dev.py --delete   # removes all [DEV] tagged records
"""

import sys
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash
from app import app, db
from datetime import date
from models import (
    User, InventoryCategory, InventoryItem, AdminEmail,
    StorageLocation, IntakeRecord, IntakeFlag,
    WorkerApplication, WorkerAvailability,
    ShiftWeek, Shift,
)

TAG = '[DEV]'
DAYS = lambda n: datetime.utcnow() - timedelta(days=n)


# ---------------------------------------------------------------------------
# DATA DEFINITIONS
# ---------------------------------------------------------------------------

ADMIN = {
    'email': 'admin@campusswap.dev',
    'name': '[DEV] Admin',
    'password': 'admin',
}

SELLERS = [
    # name, email, payout_rate, payout_method, payout_handle
    ('[DEV] Alice Chen',    'alice@unc.edu',    40, 'Venmo',  '@alice-chen'),
    ('[DEV] Bob Torres',    'bob@unc.edu',      30, 'PayPal', 'bob.torres@gmail.com'),
    ('[DEV] Clara Nash',    'clara@unc.edu',    20, 'Zelle',  '919-555-0102'),
    ('[DEV] David Kim',     'david@unc.edu',    50, 'Venmo',  '@davidkim99'),
    # No payout handle — tests the missing-handle warning
    ('[DEV] Eve Park',      'eve@unc.edu',      20, 'Venmo',  None),
    # No payout method or handle at all
    ('[DEV] Frank Liu',     'frank@unc.edu',    20, None,     None),
]

STORAGE_LOCATIONS = [
    ('[DEV] Unit A — Main Storage',  '123 Campus Drive, Chapel Hill, NC',  False, False),
    ('[DEV] Unit B — Overflow',      '456 Franklin St, Chapel Hill, NC',   False, False),
    ('[DEV] Unit C — Full',          '789 MLK Blvd, Chapel Hill, NC',      False, True),  # is_full=True
]

WORKERS = [
    {'name': '[DEV] Mover Alpha',  'email': 'mover.alpha@unc.edu',  'role': 'both',
     'avail': {d+s: True for d in ['mon','tue','wed','thu','fri','sat','sun'] for s in ['_am','_pm']}},
    {'name': '[DEV] Mover Beta',   'email': 'mover.beta@unc.edu',   'role': 'both',
     'avail': {d+s: d in ('mon','tue','wed','thu') for d in ['mon','tue','wed','thu','fri','sat','sun'] for s in ['_am','_pm']}},
    {'name': '[DEV] Mover Gamma',  'email': 'mover.gamma@unc.edu',  'role': 'both',
     'avail': {d+s: s == '_am' for d in ['mon','tue','wed','thu','fri','sat','sun'] for s in ['_am','_pm']}},
    {'name': '[DEV] Mover Delta',  'email': 'mover.delta@unc.edu',  'role': 'both',
     'avail': {d+s: d in ('thu','fri','sat') for d in ['mon','tue','wed','thu','fri','sat','sun'] for s in ['_am','_pm']}},
    {'name': '[DEV] Org Alpha',    'email': 'org.alpha@unc.edu',    'role': 'both',
     'avail': {d+s: True for d in ['mon','tue','wed','thu','fri','sat','sun'] for s in ['_am','_pm']}},
    {'name': '[DEV] Org Beta',     'email': 'org.beta@unc.edu',     'role': 'both',
     'avail': {d+s: d in ('sat','sun') for d in ['mon','tue','wed','thu','fri','sat','sun'] for s in ['_am','_pm']}},
    {'name': '[DEV] Org Gamma',    'email': 'org.gamma@unc.edu',    'role': 'both',
     'avail': {d+s: s == '_pm' for d in ['mon','tue','wed','thu','fri','sat','sun'] for s in ['_am','_pm']}},
    {'name': '[DEV] Org Delta',    'email': 'org.delta@unc.edu',    'role': 'both',
     'avail': {d+s: d in ('mon','wed','fri') for d in ['mon','tue','wed','thu','fri','sat','sun'] for s in ['_am','_pm']}},
    {'name': '[DEV] Swing One',    'email': 'swing.one@unc.edu',    'role': 'both',
     'avail': {d+s: True for d in ['mon','tue','wed','thu','fri','sat','sun'] for s in ['_am','_pm']}},
    {'name': '[DEV] Swing Two',    'email': 'swing.two@unc.edu',    'role': 'both',
     'avail': {d+s: d in ('mon','tue','wed','thu','fri') and s == '_am'
               for d in ['mon','tue','wed','thu','fri','sat','sun'] for s in ['_am','_pm']}},
    {'name': '[DEV] Swing Three',  'email': 'swing.three@unc.edu',  'role': 'both',
     'avail': {d+s: d in ('thu','fri') for d in ['mon','tue','wed','thu','fri','sat','sun'] for s in ['_am','_pm']}},
    {'name': '[DEV] Swing Four',   'email': 'swing.four@unc.edu',   'role': 'both',
     'avail': {d+s: True for d in ['mon','tue','wed','thu','fri','sat','sun'] for s in ['_am','_pm']}},
]


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def _get_or_none(email):
    return User.query.filter_by(email=email).first()


def _first_cat(name):
    """Return first category whose name contains `name`, or fallback to cat id=1."""
    cat = InventoryCategory.query.filter(InventoryCategory.name.ilike(f'%{name}%')).first()
    return cat or InventoryCategory.query.first()


def _make_item(seller, desc, price, status, cat_name,
               sold_days_ago=None, payout_sent=False, payout_sent_at=None,
               picked_up=False, at_store=False):
    cat = _first_cat(cat_name)
    item = InventoryItem(
        description=desc,
        price=price,
        status=status,
        quality=3,
        collection_method='online',
        category_id=cat.id,
        seller_id=seller.id,
        date_added=DAYS(sold_days_ago + 7 if sold_days_ago else 14),
        sold_at=DAYS(sold_days_ago) if sold_days_ago else None,
        payout_sent=payout_sent,
        payout_sent_at=payout_sent_at,
        picked_up_at=DAYS(sold_days_ago + 2) if (sold_days_ago and picked_up) else None,
        arrived_at_store_at=DAYS(sold_days_ago + 1) if (sold_days_ago and at_store) else None,
    )
    db.session.add(item)
    return item


# ---------------------------------------------------------------------------
# SEED
# ---------------------------------------------------------------------------

def seed():
    with app.app_context():
        print('Seeding dev database...\n')

        # --- Admin ---
        admin = _get_or_none(ADMIN['email'])
        if not admin:
            admin = User(
                email=ADMIN['email'],
                full_name=ADMIN['name'],
                password_hash=generate_password_hash(ADMIN['password']),
                is_admin=True,
                is_seller=False,
            )
            db.session.add(admin)
            # Whitelist in AdminEmail so re-signup works too
            if not AdminEmail.query.filter_by(email=ADMIN['email']).first():
                db.session.add(AdminEmail(email=ADMIN['email'], is_super_admin=True))
            db.session.flush()
            print(f'  ✓ Admin: {ADMIN["email"]} / {ADMIN["password"]}')
        else:
            print(f'  · Admin already exists: {ADMIN["email"]}')

        # --- Storage Locations ---
        storage_map = {}  # name -> StorageLocation
        for (name, address, is_active_override, is_full) in STORAGE_LOCATIONS:
            loc = StorageLocation.query.filter_by(name=name).first()
            if not loc:
                loc = StorageLocation(
                    name=name,
                    address=address,
                    is_active=True,
                    is_full=is_full,
                    created_by_id=None,
                )
                db.session.add(loc)
                db.session.flush()
                print(f'  ✓ Storage: {name}')
            else:
                print(f'  · Storage exists: {name}')
            storage_map[name] = loc

        unit_a = storage_map[STORAGE_LOCATIONS[0][0]]
        unit_b = storage_map[STORAGE_LOCATIONS[1][0]]

        # --- Sellers ---
        seller_objs = []
        for (full_name, email, payout_rate, payout_method, payout_handle) in SELLERS:
            s = _get_or_none(email)
            if not s:
                s = User(
                    email=email,
                    full_name=full_name,
                    password_hash=generate_password_hash('password'),
                    is_seller=True,
                    payout_rate=payout_rate,
                    payout_method=payout_method,
                    payout_handle=payout_handle,
                )
                db.session.add(s)
                db.session.flush()
                print(f'  ✓ Seller: {full_name} ({payout_rate}% — {payout_method or "no method"} {payout_handle or "no handle"})')
            else:
                print(f'  · Seller exists: {full_name}')
            seller_objs.append(s)

        alice, bob, clara, david, eve, frank = seller_objs
        db.session.flush()

        # --- Items ---
        # Check if items already seeded (by looking for a dev-tagged item)
        existing_items = InventoryItem.query.filter(
            InventoryItem.description.like(f'{TAG}%')
        ).count()
        if existing_items:
            print(f'\n  · {existing_items} dev items already exist — skipping item seed.')
        else:
            print('\n  Seeding items...')
            items_created = []

            # --- Alice (40%) — 3 unpaid sold items, 1 paid, 2 available ---
            i1 = _make_item(alice, f'{TAG} IKEA KALLAX Shelf', 80, 'sold', 'Furniture', sold_days_ago=5, picked_up=True, at_store=True)
            i2 = _make_item(alice, f'{TAG} Mini Fridge (Insignia)', 120, 'sold', 'Mini Fridge', sold_days_ago=3, picked_up=True, at_store=True)
            i3 = _make_item(alice, f'{TAG} Tower Fan', 45, 'sold', 'Tower Fan', sold_days_ago=1)
            i4 = _make_item(alice, f'{TAG} Standing Desk', 200, 'sold', 'Desk', sold_days_ago=8,
                            payout_sent=True, payout_sent_at=DAYS(2))
            _make_item(alice, f'{TAG} Area Rug 5x7', 60, 'available', 'Rugs')
            _make_item(alice, f'{TAG} Desk Lamp', 25, 'available', 'Other')
            items_created += [i1, i2, i3]

            # --- Bob (30%) — 2 unpaid sold items ---
            i5 = _make_item(bob, f'{TAG} Samsung 32" TV', 180, 'sold', 'TV', sold_days_ago=4, picked_up=True, at_store=True)
            i6 = _make_item(bob, f'{TAG} PS4 Console', 150, 'sold', 'Gaming Console', sold_days_ago=2)
            _make_item(bob, f'{TAG} Keyboard + Mouse Combo', 40, 'available', 'Keyboard / Mouse')
            items_created += [i5, i6]

            # --- Clara (20%) — 1 unpaid sold item, 1 pending ---
            i7 = _make_item(clara, f'{TAG} Accent Chair (green)', 95, 'sold', 'Armchair / Accent Chair', sold_days_ago=6, picked_up=True, at_store=True)
            _make_item(clara, f'{TAG} Coffee Maker', 35, 'pending_valuation', 'Coffee Maker / Espresso Machine')
            items_created += [i7]

            # --- David (50%) — 1 large unpaid item ---
            i8 = _make_item(david, f'{TAG} Couch (gray sectional)', 350, 'sold', 'Couch / Sofa', sold_days_ago=7, picked_up=True, at_store=True)
            _make_item(david, f'{TAG} Futon', 120, 'approved', 'Futon')
            items_created += [i8]

            # --- Eve (20%, no handle) — 1 unpaid sold item ---
            i9 = _make_item(eve, f'{TAG} Portable AC Unit', 200, 'sold', 'Portable AC Unit', sold_days_ago=2)
            items_created += [i9]

            # --- Frank (20%, no method or handle) — 1 unpaid sold item ---
            i10 = _make_item(frank, f'{TAG} Gaming Chair', 110, 'sold', 'Gaming Chair', sold_days_ago=3)
            items_created += [i10]

            db.session.flush()
            print(f'  ✓ {InventoryItem.query.filter(InventoryItem.description.like(f"{TAG}%")).count()} items created')

            # --- Dummy Shift (required FK for IntakeRecord) ---
            # Use a past Monday so it doesn't interfere with scheduling tests
            past_monday = date(2026, 4, 7)  # Apr 7 2026 — a real Monday
            week = ShiftWeek.query.filter_by(week_start=past_monday).first()
            if not week:
                week = ShiftWeek(
                    week_start=past_monday,
                    status='published',
                    created_at=DAYS(10),
                    created_by_id=admin.id,
                )
                db.session.add(week)
                db.session.flush()
                dummy_shift = Shift(
                    week_id=week.id,
                    day_of_week='mon',
                    slot='am',
                    trucks=2,
                    is_active=True,
                    created_at=DAYS(10),
                )
                db.session.add(dummy_shift)
                db.session.flush()
            else:
                dummy_shift = Shift.query.filter_by(week_id=week.id).first()

            # --- IntakeRecords ---
            # i1 (Alice's shelf) — has intake record, no flag
            sid = dummy_shift.id
            ir1 = IntakeRecord(
                item_id=i1.id, shift_id=sid, organizer_id=admin.id,
                storage_location_id=unit_a.id, storage_row='A3',
                quality_before=3, quality_after=3,
                created_at=DAYS(4),
            )
            # i2 (Alice's fridge) — has intake record + unresolved damaged flag
            ir2 = IntakeRecord(
                item_id=i2.id, shift_id=sid, organizer_id=admin.id,
                storage_location_id=unit_a.id, storage_row='B1',
                quality_before=4, quality_after=2,
                created_at=DAYS(2),
            )
            # i5 (Bob's TV) — has intake record + unresolved missing flag
            ir5 = IntakeRecord(
                item_id=i5.id, shift_id=sid, organizer_id=admin.id,
                storage_location_id=unit_b.id, storage_row='C2',
                quality_before=3, quality_after=3,
                created_at=DAYS(3),
            )
            # i7 (Clara's chair) — has intake record, no flag
            ir7 = IntakeRecord(
                item_id=i7.id, shift_id=sid, organizer_id=admin.id,
                storage_location_id=unit_a.id, storage_row='D1',
                quality_before=3, quality_after=3,
                created_at=DAYS(5),
            )
            # i8 (David's couch) — has intake record, no flag
            ir8 = IntakeRecord(
                item_id=i8.id, shift_id=sid, organizer_id=admin.id,
                storage_location_id=unit_b.id, storage_row='A1',
                quality_before=2, quality_after=2,
                created_at=DAYS(6),
            )
            for r in [ir1, ir2, ir5, ir7, ir8]:
                db.session.add(r)
            db.session.flush()

            # --- IntakeFlags ---
            # i2 (Alice's fridge) — damaged, unresolved
            db.session.add(IntakeFlag(
                item_id=i2.id, shift_id=sid, intake_record_id=ir2.id,
                organizer_id=admin.id, flag_type='damaged',
                description='Dent on left side panel, door seal cracked.',
                resolved=False, created_at=DAYS(2),
            ))
            # i5 (Bob's TV) — missing, unresolved
            db.session.add(IntakeFlag(
                item_id=i5.id, shift_id=sid, intake_record_id=ir5.id,
                organizer_id=admin.id, flag_type='missing',
                description='Remote control not included.',
                resolved=False, created_at=DAYS(3),
            ))
            # i6 (Bob's PS4) — no intake record, no flag (tests "No intake record" badge)
            # i3 (Alice's fan) — no intake record, no flag (tests "No intake record" badge)
            # i8 has a resolved flag to verify it doesn't show
            db.session.add(IntakeFlag(
                item_id=i8.id, shift_id=sid, intake_record_id=ir8.id,
                organizer_id=admin.id, flag_type='damaged',
                description='Slight tear on armrest — resolved, acceptable.',
                resolved=True, resolved_at=DAYS(4),
                resolved_by_id=admin.id,
                resolution_note='Seller agreed; item listed as-is.',
                created_at=DAYS(6),
            ))
            print('  ✓ IntakeRecords and IntakeFlags created')

        # --- Workers ---
        workers_created = 0
        workers_skipped = 0
        for w in WORKERS:
            if _get_or_none(w['email']):
                workers_skipped += 1
                continue
            user = User(
                email=w['email'],
                full_name=w['name'],
                is_worker=True,
                worker_status='approved',
                worker_role=w['role'],
            )
            db.session.add(user)
            db.session.flush()
            db.session.add(WorkerApplication(
                user_id=user.id,
                unc_year='2026',
                role_pref=w['role'],
                why_blurb='Dev seed account.',
                applied_at=DAYS(14),
            ))
            fields = {
                f'{day}_{slot}': w['avail'][f'{day}_{slot}']
                for day in ['mon','tue','wed','thu','fri','sat','sun']
                for slot in ['am','pm']
            }
            db.session.add(WorkerAvailability(user_id=user.id, week_start=None, **fields))
            workers_created += 1

        db.session.commit()
        if workers_created:
            print(f'  ✓ {workers_created} workers created')
        if workers_skipped:
            print(f'  · {workers_skipped} workers already existed')

        # --- Summary ---
        print('\n' + '─' * 55)
        print('Dev seed complete.\n')
        print(f'  Admin login:   {ADMIN["email"]} / {ADMIN["password"]}')
        print(f'  Seller logins: <email> / password  (for any seller)')
        print()
        print('  Unpaid queue should show:')
        print('    Alice  (40%) — $80 shelf (no flag), $120 fridge (damaged⚠), $45 fan (no intake⚠)')
        print('    David  (50%) — $350 couch')
        print('    Bob    (30%) — $180 TV (missing⚠), $150 PS4 (no intake⚠)')
        print('    Clara  (20%) — $95 chair')
        print('    Eve    (20%) — $200 AC unit  ← missing handle warning')
        print('    Frank  (20%) — $110 gaming chair  ← missing handle warning')
        print()
        print('  Storage units: Unit A (active), Unit B (active), Unit C (full)')
        print('─' * 55)


def delete():
    with app.app_context():
        # Items first (to avoid FK issues with intake records/flags)
        dev_items = InventoryItem.query.filter(InventoryItem.description.like(f'{TAG}%')).all()
        item_ids = [i.id for i in dev_items]
        if item_ids:
            IntakeFlag.query.filter(IntakeFlag.item_id.in_(item_ids)).delete(synchronize_session=False)
            IntakeRecord.query.filter(IntakeRecord.item_id.in_(item_ids)).delete(synchronize_session=False)
        for item in dev_items:
            db.session.delete(item)

        # Users
        dev_emails = [ADMIN['email']] + [s[1] for s in SELLERS] + [w['email'] for w in WORKERS]
        for email in dev_emails:
            u = _get_or_none(email)
            if u:
                WorkerAvailability.query.filter_by(user_id=u.id).delete()
                WorkerApplication.query.filter_by(user_id=u.id).delete()
                db.session.delete(u)
        AdminEmail.query.filter_by(email=ADMIN['email']).delete()

        # Storage
        for (name, *_) in STORAGE_LOCATIONS:
            loc = StorageLocation.query.filter_by(name=name).first()
            if loc:
                db.session.delete(loc)

        db.session.commit()
        print('Dev seed records deleted.')


if __name__ == '__main__':
    if '--delete' in sys.argv:
        delete()
    else:
        seed()
