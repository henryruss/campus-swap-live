# Fix Spec: Crew — Dashboard Visibility + Reversible Stop Actions

## Overview

Three related fixes to the crew worker experience, addressed together since
they all touch the same area of the codebase.

---

## Fix 1: Crew Dashboard Shows Assigned Shifts Regardless of Published State

### Problem

`crew_dashboard()` builds `my_shifts` by calling `_get_current_published_week()`
and then filtering `ShiftAssignment` records for that week. If the week's
`ShiftWeek.status` is `'draft'`, `_get_current_published_week()` returns `None`
and the worker sees the "Schedules post every Thursday" placeholder even if
they have assignments.

In practice, admin now assigns workers from Crew HQ without a formal
publish step — especially for near-term shifts. Workers need to see their
assignments immediately.

### Fix

Change `crew_dashboard()` to build `my_shifts` from the worker's own
`ShiftAssignment` records directly, without gating on published state.
Find all upcoming shifts (shift date >= today) where the current user has
an assignment, regardless of `ShiftWeek.status`.

```python
# BEFORE (simplified):
current_week = _get_current_published_week()
my_shifts = ShiftAssignment.query.join(Shift).join(ShiftWeek).filter(
    ShiftAssignment.worker_id == current_user.id,
    ShiftWeek.id == current_week.id
).all() if current_week else []

# AFTER:
today = _today_eastern()
my_assignments = (
    ShiftAssignment.query
    .join(Shift, ShiftAssignment.shift_id == Shift.id)
    .join(ShiftWeek, Shift.week_id == ShiftWeek.id)
    .filter(
        ShiftAssignment.worker_id == current_user.id,
        ShiftAssignment.completed_at == None,
        ShiftWeek.week_start >= today - timedelta(days=today.weekday())
    )
    .order_by(ShiftWeek.week_start.asc(), Shift.sort_key.asc())
    .all()
)
my_shifts = [(a.shift, a.role_on_shift) for a in my_assignments]
```

The `crew_schedule_week` route (full calendar modal) should also be updated
to not 404/redirect on draft weeks — workers should be able to see the full
week view as long as they have at least one assignment in it.

### Constraints
- Do not change `_get_current_published_week()` — it is used elsewhere
  (ops page, schedule builder) and should not be affected.
- The "Today's Shift" banner logic is separate — keep its existing gating
  (checks for ShiftAssignment where shift date == today).
- Shift History section is unaffected — it reads completed ShiftRun records,
  not the published week.

---

## Fix 2: Stop Actions Are Soft Until End Shift

### Problem

Currently `crew_shift_stop_update` (marking a stop Completed or Issue)
immediately writes `picked_up_at` on the seller's items. This makes stop
actions permanent — a worker who accidentally taps Completed on the wrong
stop has no recovery path short of a shell fix.

### New Behavior

Stop status changes (`pending` → `completed` / `pending` → `issue` and
reversions) are **soft state on `ShiftPickup`** only. The hard write of
`picked_up_at` on `InventoryItem` is deferred until the worker confirms
End Shift.

#### During the shift

`crew_shift_stop_update` — mark Completed or Issue:
- Set `ShiftPickup.status = 'completed'` or `'issue'` as today
- **Do NOT write `picked_up_at` on any `InventoryItem`**
- No other item-level changes

`crew_shift_stop_revert` — revert to pending:
- Set `ShiftPickup.status = 'pending'`, clear `ShiftPickup.notes`
- **No item writes needed** (nothing was written on complete, so nothing
  to undo)
- This simplifies the existing revert route — remove any code that
  currently clears `picked_up_at` on items (it was a compensating write
  for the old eager behavior; it is no longer needed)

#### On End Shift (commit step)

`crew_shift_end` — worker taps End Shift:

1. Guard: all stops must be `completed` or `issue` (no `pending` remaining).
   If any stop is still `pending`, return an error — same as today.

2. Show confirmation before committing. Since this is server-rendered with
   no JS modals, implement as a **two-step POST**:
   - First tap of "End Shift" → redirects to a confirmation page
     (`GET /crew/shift/<shift_id>/end-confirm`) showing the stop summary
     and the warning: *"Once confirmed, this cannot be undone. Make sure
     all items have been accounted for."*
   - Confirmation page has a single "Confirm & End Shift" button that
     POSTs to `crew_shift_end` with a hidden `confirmed=1` field
   - If `confirmed=1` is present in the POST, proceed with commit

3. Commit step (only when `confirmed=1`):
   - For all `ShiftPickup` records on this shift with `status='completed'`:
     write `picked_up_at = _now_eastern()` on each seller's `InventoryItem`
     records that are `status='available'` and not already have `picked_up_at`
     set. (Keep the existing "don't overwrite if already set" guard.)
   - For `status='issue'` stops: write nothing to items (items remain
     `available` with no `picked_up_at`)
   - Close the `ShiftRun`: set `status='completed'`, `ended_at=_now_eastern()`
   - Set `ShiftAssignment.completed_at` for the current user on this shift
   - Redirect to `/crew` with flash "Shift complete. Great work!"

### New Route

| Method | Path | Function | Description |
|--------|------|----------|-------------|
| `GET /crew/shift/<shift_id>/end-confirm` | `crew_shift_end_confirm` | Confirmation page before End Shift commit. Requires: worker assigned to shift, ShiftRun in_progress, all stops resolved. |

### Template Changes

**`crew/shift.html`** (or equivalent mover shift template):
- "Completed" and "Issue" buttons: no change to UI
- Revert button: no change to UI
- End Shift button behavior: POSTs to existing `crew_shift_end` route
  without `confirmed` field (triggers redirect to confirm page)

**New template: `crew/shift_end_confirm.html`**:
- Extends `layout.html`
- Shows shift label (day, slot, date)
- Shows stop summary: list of seller names with their stop status
  (✓ Completed / ⚠ Issue)
- Warning text: *"Once confirmed, this cannot be undone. Make sure all
  items have been accounted for."*
- "Confirm & End Shift" button → POST to `crew_shift_end` with
  `confirmed=1`
- "Go Back" link → back to `/crew/shift/<shift_id>`

### Constraints
- No schema changes — `ShiftPickup.status` values are unchanged
  (`pending` / `completed` / `issue`)
- `InventoryItem.picked_up_at` is still the source of truth for
  downstream payout and intake logic — we are only changing WHEN it
  gets written, not whether
- Do not change the retroactive shift completion route
  (`crew_shift_complete_retroactive`) — it is an admin-facing escape
  hatch for past shifts and should write `picked_up_at` immediately
  as it does today
- Keep the "don't overwrite `picked_up_at` if already set" guard in
  the commit step

---

## Fix 3: Remove Orphaned `picked_up_at` Data (One-Time Shell Fix)

If any stops were completed under the old behavior (before this fix),
their items already have `picked_up_at` set but the operator may want
to clear them for testing. This is optional and admin-only:

```python
# Run in flask shell only if needed to reset test data:
from models import InventoryItem, db
from sqlalchemy import update

# Replace <seller_user_id> with the test seller's user ID
items = InventoryItem.query.filter_by(seller_id=<seller_user_id>).all()
for item in items:
    item.picked_up_at = None
db.session.commit()
print(f"Cleared picked_up_at on {len(items)} items")
```

---

## Summary of Route Changes

| Route | Change |
|-------|--------|
| `crew_dashboard` | Remove published-week gate for `my_shifts`; query assignments directly |
| `crew_schedule_week` | Allow draft weeks when current user has an assignment in that week |
| `crew_shift_stop_update` | Remove `picked_up_at` write; soft status only |
| `crew_shift_stop_revert` | Remove item-level compensating writes (now a no-op on items) |
| `crew_shift_end` | Add `confirmed` check; redirect to confirm page if not confirmed; commit `picked_up_at` writes on confirm |
| `crew_shift_end_confirm` (NEW) | Confirmation page — GET only; guards same as `crew_shift_end` |
