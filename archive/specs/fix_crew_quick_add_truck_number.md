# Fix: Crew HQ Quick-Add — Worker Not Appearing After Assignment

## Problem

When a worker is added to a shift via the Crew HQ quick-add route
(`POST /admin/crew/shift/<shift_id>/quick-add`), the `ShiftAssignment` is
created with `truck_number=None`. This causes two symptoms:

1. **Ops page shows "No movers available to add"** — the worker is correctly
   excluded from the add dropdown (they're already assigned), but they don't
   appear in any truck card because no truck card renders `NULL` truck numbers.
   The worker is in limbo: assigned but invisible.

2. **Worker sees nothing on the crew side** — `crew_shift_view` requires the
   worker to be assigned with `role_on_shift='driver'`, which is satisfied, but
   the shift may not surface correctly in the crew dashboard if truck context
   is missing.

## Root Cause

In `admin_crew_quick_add`, the `ShiftAssignment` is created with
`truck_number=None` for driver-role assignments. The ops page truck cards only
render workers with a real `truck_number` value (1, 2, etc.).

## Fix

In `admin_crew_quick_add` in `app.py`, change the `ShiftAssignment` creation
so that driver-role assignments default to `truck_number=1`.

### Find this block in `admin_crew_quick_add`:

```python
assignment = ShiftAssignment(
    shift_id=shift_id,
    worker_id=worker_id,
    role_on_shift=role,
    assigned_at=_now_eastern(),
    assigned_by_id=current_user.id,
    truck_number=None
)
```

### Replace with:

```python
# Drivers default to truck 1 so they appear immediately on the ops page.
# Admin can reassign to a specific truck from the ops page if needed.
truck_number = 1 if role == 'driver' else None

assignment = ShiftAssignment(
    shift_id=shift_id,
    worker_id=worker_id,
    role_on_shift=role,
    assigned_at=_now_eastern(),
    assigned_by_id=current_user.id,
    truck_number=truck_number
)
```

## Also Fix: Existing Bad Records

The worker who was already assigned with `truck_number=NULL` needs to be
patched. Add a one-time data fix at the bottom of `admin_crew_quick_add` is
not the right place — instead, run this as a direct DB fix:

```python
# Run once in flask shell or as a migration data fix:
from models import ShiftAssignment, db
bad = ShiftAssignment.query.filter(
    ShiftAssignment.role_on_shift == 'driver',
    ShiftAssignment.truck_number == None
).all()
for a in bad:
    a.truck_number = 1
db.session.commit()
print(f"Fixed {len(bad)} assignment(s)")
```

Run this in the Flask shell (`flask shell`) before testing.

## Constraints

- Do not touch any other route.
- No migration needed — this is a logic change only.
- `truck_number=1` is the correct default: all shifts have at least 1 truck,
  and the ops page always has a truck 1 card. Admin can reassign via
  `POST /admin/crew/shift/<shift_id>/mover/<assignment_id>/assign_truck`
  if the worker should be on a different truck.
