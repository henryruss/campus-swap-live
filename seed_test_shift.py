"""
Seed a fake active Thursday AM shift so driver.alpha@test.com can test Quick Capture
from inside a running shift.  Run once: python seed_test_shift.py
"""
import datetime
from app import app, db
from models import (
    User, ShiftWeek, Shift, ShiftAssignment,
    ShiftPickup, ShiftRun
)

# ── helpers ──────────────────────────────────────────────────────────────────

def monday_of(d):
    return d - datetime.timedelta(days=d.weekday())


def make_seller(email, name, dorm, room_num, lat=None, lng=None):
    u = User.query.filter_by(email=email).first()
    if not u:
        u = User(
            email=email,
            full_name=name,
            is_seller=True,
            is_worker=False,
            is_admin=False,
            password_hash='!unusable',
            pickup_location_type='on_campus',
            pickup_dorm=dorm,
            pickup_room=room_num,
            pickup_lat=lat or 35.5015,
            pickup_lng=lng or -80.8476,
        )
        db.session.add(u)
        db.session.flush()
        print(f'  created seller {email} (id={u.id})')
    else:
        print(f'  seller {email} already exists (id={u.id})')
    return u


# ── main ──────────────────────────────────────────────────────────────────────

with app.app_context():
    driver = User.query.filter_by(email='driver.alpha@test.com').first()
    assert driver, 'driver.alpha@test.com not found — run seeds first'

    today = datetime.date.today()          # 2026-05-07 (Thursday)
    monday = monday_of(today)              # 2026-05-04

    # ── ShiftWeek ─────────────────────────────────────────────────────────────
    week = ShiftWeek.query.filter_by(week_start=monday).first()
    if not week:
        week = ShiftWeek(week_start=monday, status='published', created_by_id=driver.id)
        db.session.add(week)
        db.session.flush()
        print(f'Created ShiftWeek id={week.id} (week_start={monday})')
    else:
        week.status = 'published'
        print(f'ShiftWeek already exists id={week.id}')

    # ── Shift ─────────────────────────────────────────────────────────────────
    shift = Shift.query.filter_by(week_id=week.id, day_of_week='thu', slot='am').first()
    if not shift:
        shift = Shift(week_id=week.id, day_of_week='thu', slot='am', trucks=1, is_active=True)
        db.session.add(shift)
        db.session.flush()
        print(f'Created Shift id={shift.id} (thu AM)')
    else:
        print(f'Shift already exists id={shift.id}')

    # ── ShiftAssignment for driver ────────────────────────────────────────────
    existing_assign = ShiftAssignment.query.filter_by(
        shift_id=shift.id, worker_id=driver.id
    ).first()
    if not existing_assign:
        db.session.add(ShiftAssignment(
            shift_id=shift.id,
            worker_id=driver.id,
            role_on_shift='driver',
            truck_number=1,
        ))
        print(f'Assigned driver.alpha to shift id={shift.id} truck=1')
    else:
        print('Assignment already exists')

    # ── Fake sellers (stops) ──────────────────────────────────────────────────
    sellers = [
        make_seller('fake.seller1@test.com', 'Alex Martin',  'Belk', '203', 35.5020, -80.8480),
        make_seller('fake.seller2@test.com', 'Jamie Chen',   'Watts', '112', 35.5008, -80.8470),
        make_seller('fake.seller3@test.com', 'Morgan Davis', 'Richardson', '305', 35.5025, -80.8490),
    ]
    db.session.flush()

    # ── ShiftPickups ──────────────────────────────────────────────────────────
    for i, seller in enumerate(sellers, start=1):
        existing_sp = ShiftPickup.query.filter_by(
            shift_id=shift.id, seller_id=seller.id
        ).first()
        if not existing_sp:
            db.session.add(ShiftPickup(
                shift_id=shift.id,
                seller_id=seller.id,
                truck_number=1,
                stop_order=i,
                status='pending',
            ))
            print(f'  Added stop {i}: {seller.full_name}')
        else:
            print(f'  Stop for {seller.full_name} already exists')

    db.session.flush()

    # ── ShiftRun (in_progress) ────────────────────────────────────────────────
    run = ShiftRun.query.filter_by(shift_id=shift.id).first()
    if not run:
        run = ShiftRun(
            shift_id=shift.id,
            started_by_id=driver.id,
            status='in_progress',
        )
        db.session.add(run)
        print(f'Created ShiftRun (in_progress) for shift id={shift.id}')
    else:
        run.status = 'in_progress'
        run.ended_at = None
        print(f'ShiftRun already exists id={run.id}, set to in_progress')

    db.session.commit()
    print(f'\nDone. Visit /crew/shift/{shift.id} as driver.alpha@test.com')
