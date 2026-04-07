"""
Seed script: creates dummy crew members for optimizer testing.
Run with: python3 seed_test_crew.py

Creates 12 test workers (4 drivers, 4 organizers, 4 both) with varied
availability patterns designed to stress-test:
  - Role enforcement (drivers only as drivers, etc.)
  - Load spreading (different total availability)
  - Double-shift avoidance (limited workers who can only fill same-day slots)

Safe to re-run — skips any email that already exists.
To clean up afterwards: python3 seed_test_crew.py --delete
"""

import sys
from app import app, db
from models import User, WorkerAvailability, WorkerApplication
from datetime import datetime

TEST_TAG = '[TEST]'

WORKERS = [
    # --- DRIVERS (4) ---
    # Fully available all week
    {'name': '[TEST] Driver Alpha',   'email': 'driver.alpha@test.com',   'role': 'driver',
     'avail': {d+s: True for d in ['mon','tue','wed','thu','fri','sat','sun'] for s in ['_am','_pm']}},
    # Available Mon-Thu only
    {'name': '[TEST] Driver Beta',    'email': 'driver.beta@test.com',    'role': 'driver',
     'avail': {d+s: d in ('mon','tue','wed','thu') for d in ['mon','tue','wed','thu','fri','sat','sun'] for s in ['_am','_pm']}},
    # Blackout all PMs — AM only
    {'name': '[TEST] Driver Gamma',   'email': 'driver.gamma@test.com',   'role': 'driver',
     'avail': {d+s: s == '_am' for d in ['mon','tue','wed','thu','fri','sat','sun'] for s in ['_am','_pm']}},
    # Very limited: only Tue AM, Wed AM, Thu PM
    {'name': '[TEST] Driver Delta',   'email': 'driver.delta@test.com',   'role': 'driver',
     'avail': {d+s: (d=='tue' and s=='_am') or (d=='wed' and s=='_am') or (d=='thu' and s=='_pm')
               for d in ['mon','tue','wed','thu','fri','sat','sun'] for s in ['_am','_pm']}},

    # --- ORGANIZERS (4) ---
    # Fully available
    {'name': '[TEST] Org Alpha',      'email': 'org.alpha@test.com',      'role': 'organizer',
     'avail': {d+s: True for d in ['mon','tue','wed','thu','fri','sat','sun'] for s in ['_am','_pm']}},
    # Weekends only
    {'name': '[TEST] Org Beta',       'email': 'org.beta@test.com',       'role': 'organizer',
     'avail': {d+s: d in ('sat','sun') for d in ['mon','tue','wed','thu','fri','sat','sun'] for s in ['_am','_pm']}},
    # PM only
    {'name': '[TEST] Org Gamma',      'email': 'org.gamma@test.com',      'role': 'organizer',
     'avail': {d+s: s == '_pm' for d in ['mon','tue','wed','thu','fri','sat','sun'] for s in ['_am','_pm']}},
    # Mon/Wed/Fri both slots
    {'name': '[TEST] Org Delta',      'email': 'org.delta@test.com',      'role': 'organizer',
     'avail': {d+s: d in ('mon','wed','fri') for d in ['mon','tue','wed','thu','fri','sat','sun'] for s in ['_am','_pm']}},

    # --- BOTH (4) — these are the swing workers that fill either role ---
    # Fully available — high load expected
    {'name': '[TEST] Both Alpha',     'email': 'both.alpha@test.com',     'role': 'both',
     'avail': {d+s: True for d in ['mon','tue','wed','thu','fri','sat','sun'] for s in ['_am','_pm']}},
    # Available Mon-Fri AM only — tests double-shift avoidance when PM is thin
    {'name': '[TEST] Both Beta',      'email': 'both.beta@test.com',      'role': 'both',
     'avail': {d+s: d in ('mon','tue','wed','thu','fri') and s == '_am'
               for d in ['mon','tue','wed','thu','fri','sat','sun'] for s in ['_am','_pm']}},
    # Only available Thu and Fri both slots — will be double-shifted if needed
    {'name': '[TEST] Both Gamma',     'email': 'both.gamma@test.com',     'role': 'both',
     'avail': {d+s: d in ('thu','fri') for d in ['mon','tue','wed','thu','fri','sat','sun'] for s in ['_am','_pm']}},
    # Fully available — second high-load swing worker
    {'name': '[TEST] Both Delta',     'email': 'both.delta@test.com',     'role': 'both',
     'avail': {d+s: True for d in ['mon','tue','wed','thu','fri','sat','sun'] for s in ['_am','_pm']}},
]


def create():
    with app.app_context():
        created = 0
        skipped = 0
        for w in WORKERS:
            if User.query.filter_by(email=w['email']).first():
                skipped += 1
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

            # Application record (required for FK integrity)
            app_rec = WorkerApplication(
                user_id=user.id,
                unc_year='2026',
                role_pref=w['role'],
                why_blurb='Test account',
                applied_at=datetime.utcnow(),
            )
            db.session.add(app_rec)

            # Availability (week_start=NULL = application-time availability)
            fields = {k.replace('-', '_'): v for k, v in {
                'mon_am': w['avail']['mon_am'],
                'mon_pm': w['avail']['mon_pm'],
                'tue_am': w['avail']['tue_am'],
                'tue_pm': w['avail']['tue_pm'],
                'wed_am': w['avail']['wed_am'],
                'wed_pm': w['avail']['wed_pm'],
                'thu_am': w['avail']['thu_am'],
                'thu_pm': w['avail']['thu_pm'],
                'fri_am': w['avail']['fri_am'],
                'fri_pm': w['avail']['fri_pm'],
                'sat_am': w['avail']['sat_am'],
                'sat_pm': w['avail']['sat_pm'],
                'sun_am': w['avail']['sun_am'],
                'sun_pm': w['avail']['sun_pm'],
            }.items()}
            avail = WorkerAvailability(user_id=user.id, week_start=None, **fields)
            db.session.add(avail)
            created += 1

        db.session.commit()
        print(f'Created {created} test workers, skipped {skipped} (already exist).')
        print_summary()


def delete():
    with app.app_context():
        test_users = User.query.filter(User.email.like('%@test.com')).all()
        for u in test_users:
            WorkerAvailability.query.filter_by(user_id=u.id).delete()
            WorkerApplication.query.filter_by(user_id=u.id).delete()
            db.session.delete(u)
        db.session.commit()
        print(f'Deleted {len(test_users)} test workers.')


def print_summary():
    from models import WorkerAvailability
    workers = User.query.filter(User.email.like('%@test.com'), User.is_worker==True).all()
    print(f'\n{"Name":<28} {"Role":<12} {"Available slots"}')
    print('-' * 65)
    for w in workers:
        avail = WorkerAvailability.query.filter_by(user_id=w.id, week_start=None).first()
        if avail:
            slots = sum(1 for f in ['mon_am','mon_pm','tue_am','tue_pm','wed_am','wed_pm',
                                     'thu_am','thu_pm','fri_am','fri_pm','sat_am','sat_pm',
                                     'sun_am','sun_pm'] if getattr(avail, f))
        else:
            slots = 0
        print(f'{w.full_name:<28} {w.worker_role:<12} {slots}/14 slots available')


if __name__ == '__main__':
    if '--delete' in sys.argv:
        delete()
    else:
        create()
