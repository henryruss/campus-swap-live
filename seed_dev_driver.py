"""
Seed a local dev driver scenario for testing the placement flow.

Run once:  python3 seed_dev_driver.py

Creates:
  - driver@test.com / driver123  (approved driver)
  - A ShiftWeek + Shift (today, AM slot)
  - ShiftRun (in_progress so End Shift is reachable)
  - 3 sellers with 2 items each, all assigned to the driver's truck
  - ShiftPickup rows with status='completed' (placement guard fires)
  - Items with placement_status=None (need to be placed)

Re-running is safe — existing records are reused.
"""

from dotenv import load_dotenv
load_dotenv()

from app import app, db
from models import (
    User, InventoryItem, InventoryCategory,
    ShiftWeek, Shift, ShiftAssignment, ShiftPickup, ShiftRun,
)
from werkzeug.security import generate_password_hash
from datetime import date, datetime


def run():
    with app.app_context():
        today = date.today()

        # ── Driver account ──────────────────────────────────────────────
        driver = User.query.filter_by(email='driver@test.com').first()
        if not driver:
            driver = User(
                email='driver@test.com',
                full_name='Dev Driver',
                is_worker=True,
                worker_status='approved',
                worker_role='driver',
            )
            driver.password_hash = generate_password_hash('driver123')
            db.session.add(driver)
            db.session.flush()
            print(f'Created driver: id={driver.id}')
        else:
            driver.is_worker = True
            driver.worker_status = 'approved'
            driver.worker_role = 'driver'
            driver.password_hash = generate_password_hash('driver123')
            print(f'Reused driver: id={driver.id}')

        # ── Category ────────────────────────────────────────────────────
        cat = InventoryCategory.query.first()

        # ── Sellers with items ──────────────────────────────────────────
        seller_data = [
            ('dev_seller1@test.com', 'Jamie Doe',   [('Desk lamp', 25.0), ('Mini-fridge', 85.0)]),
            ('dev_seller2@test.com', 'Taylor Smith', [('Couch', 120.0),   ('Bookshelf', 40.0)]),
            ('dev_seller3@test.com', 'Morgan Lee',  [('Coffee table', 55.0), ('Desk chair', 45.0)]),
        ]
        sellers = []
        for email, name, items_data in seller_data:
            s = User.query.filter_by(email=email).first()
            if not s:
                s = User(
                    email=email,
                    full_name=name,
                    is_seller=True,
                    pickup_location_type='on_campus',
                    pickup_dorm='Test Hall',
                    pickup_room='101',
                    unsubscribed=True,
                )
                s.password_hash = generate_password_hash('test123')
                db.session.add(s)
                db.session.flush()
                print(f'Created seller: {name} (id={s.id})')
            sellers.append((s, items_data))

        # ── Ensure each seller has unplaced items ───────────────────────
        for s, items_data in sellers:
            existing_count = InventoryItem.query.filter_by(
                seller_id=s.id, placement_status=None
            ).count()
            if existing_count == 0:
                for desc, price in items_data:
                    item = InventoryItem(
                        description=desc,
                        price=price,
                        status='available',
                        seller_id=s.id,
                        category_id=cat.id if cat else None,
                        quality=3,
                        placement_status=None,
                    )
                    db.session.add(item)
                db.session.flush()
                print(f'  Added items for {s.full_name}')

        # ── ShiftWeek ───────────────────────────────────────────────────
        # Use the Monday of this week
        monday = today - __import__('datetime').timedelta(days=today.weekday())
        week = ShiftWeek.query.filter_by(week_start=monday, is_tutorial=False).first()
        if not week:
            week = ShiftWeek(
                week_start=monday,
                status='published',
                is_tutorial=False,
            )
            db.session.add(week)
            db.session.flush()
            print(f'Created ShiftWeek: {monday}')

        # ── Shift (today, AM) ───────────────────────────────────────────
        day_map = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
        dow = day_map[today.weekday()]
        shift = Shift.query.filter_by(week_id=week.id, day_of_week=dow, slot='am').first()
        if not shift:
            shift = Shift(
                week_id=week.id,
                day_of_week=dow,
                slot='am',
                trucks=1,
                is_active=True,
            )
            db.session.add(shift)
            db.session.flush()
            print(f'Created Shift: {dow} AM (id={shift.id})')

        # ── ShiftRun (in_progress so driver can end it) ─────────────────
        run = ShiftRun.query.filter_by(shift_id=shift.id).first()
        if not run:
            run = ShiftRun(
                shift_id=shift.id,
                started_at=datetime.utcnow(),
                started_by_id=driver.id,
                status='in_progress',
            )
            db.session.add(run)
            db.session.flush()
            print(f'Created ShiftRun (in_progress)')

        # ── ShiftAssignment (driver on truck 1) ─────────────────────────
        assignment = ShiftAssignment.query.filter_by(
            shift_id=shift.id, worker_id=driver.id
        ).first()
        if not assignment:
            assignment = ShiftAssignment(
                shift_id=shift.id,
                worker_id=driver.id,
                truck_number=1,
                role_on_shift='driver',
            )
            db.session.add(assignment)
            db.session.flush()
            print(f'Created ShiftAssignment for driver on truck 1')

        # ── ShiftPickup rows (completed, so placement guard fires) ───────
        for i, (s, _) in enumerate(sellers):
            pickup = ShiftPickup.query.filter_by(
                shift_id=shift.id, seller_id=s.id
            ).first()
            if not pickup:
                pickup = ShiftPickup(
                    shift_id=shift.id,
                    seller_id=s.id,
                    truck_number=1,
                    stop_order=i + 1,
                    status='completed',
                    notified_at=datetime.utcnow(),
                )
                db.session.add(pickup)
                print(f'  Created ShiftPickup for {s.full_name} (completed)')

        db.session.commit()
        print(f'\nDone. Go to http://localhost:4242/crew/shift/{shift.id}')
        print('Login: driver@test.com / driver123')


if __name__ == '__main__':
    run()
