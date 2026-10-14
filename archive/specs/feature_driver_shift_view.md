# Spec #3 — Driver Shift View

## Goal

Give movers a phone-optimized day-of interface showing their assigned pickup stops and
letting them log what happened at each house (completed / issue). Stop completions write
to `ShiftPickup` and `InventoryItem.picked_up_at`, and leave a clearly marked hook for
spec #9 SMS notifications (next seller gets a text when the previous stop is marked
complete). Also introduces the `ShiftPickup` model (shared foundation for spec #6 route
planning), the `WorkerPreference` model (partner preferences for the optimizer), and
role-balance tracking in the shift optimizer.

---

## Terminology Change (Apply Throughout)

- "Driver" -> "Mover" in all templates, emails, flash messages, and code comments.
- `role_on_shift` DB values stay 'driver' and 'organizer' (renaming requires a
  migration and touches live records). Display labels change:
  - 'driver'    -> renders as "Mover (Truck)"
  - 'organizer' -> renders as "Mover (Storage)"
- Worker application form: remove role preference (role_pref) field entirely.
  All workers are movers. User.worker_role is set to 'both' on approval and is
  never shown to the worker.

---

## New Models

### ShiftPickup

Links a seller to a specific shift and truck. One record per seller per shift.
Spec #6 will populate stop_order with proper route sequencing. Until then,
stop_order is nullable and display order falls back to insertion order (id asc).

```
id
shift_id          FK -> Shift
seller_id         FK -> User
truck_number      Integer (1-max_trucks_per_shift)
stop_order        Integer, nullable  <- spec #6 populates this
status            String: 'pending' | 'completed' | 'issue'   default: 'pending'
notes             Text, nullable  (required when status = 'issue')
completed_at      DateTime, nullable  set when status -> completed or issue
created_at        DateTime, default utcnow
created_by_id     FK -> User  (admin who assigned this seller to the shift)

Relationships:
  shift       -> Shift
  seller      -> User (backref: shift_pickups)
  created_by  -> User
```

Constraint: unique on (shift_id, seller_id) -- a seller appears on a shift once only.

Side effect on completion: when status transitions to 'completed', set
InventoryItem.picked_up_at = utcnow() on all 'available'-status items belonging to
that seller. Do not overwrite picked_up_at if already set.

SMS hook: after marking a stop 'completed' or 'issue', call
_notify_next_seller(shift, current_pickup) -- a stub function in app.py that identifies
the next pending stop and logs a TODO line. Spec #9 implements the Twilio call inside
this stub. Do not couple any Twilio logic here.

---

### ShiftRun

Tracks shift-level execution state. One record per shift, created when a mover taps
"Start Shift."

```
id
shift_id          FK -> Shift, unique
started_at        DateTime, default utcnow
started_by_id     FK -> User  (mover who tapped Start Shift)
ended_at          DateTime, nullable
status            String: 'in_progress' | 'completed'   default: 'in_progress'

Relationships:
  shift       -> Shift (backref: run, uselist=False)
  started_by  -> User
```

When ShiftRun is created, call _notify_next_seller() for the first pending stop --
the first seller gets notified when the shift kicks off.

---

### WorkerPreference

Stores partner preferences between movers. Two separate row types rather than one row
with both fields.

```
id
user_id           FK -> User
target_user_id    FK -> User
preference_type   String: 'preferred' | 'avoided'
created_at        DateTime, default utcnow

Relationships:
  user        -> User (backref: worker_preferences)
  target_user -> User
```

Constraint: unique on (user_id, target_user_id, preference_type).

Optimizer rule (symmetric with avoid-override):
- A pair is treated as mutually preferred if either worker has listed the other as
  'preferred' AND neither has listed the other as 'avoided'.
- If either worker has listed the other as 'avoided', the pairing is never made,
  regardless of any 'preferred' entries in either direction.

No limit on number of preferences per worker.

---

Migration required for all three models:
  flask db migrate -m "shift_pickup_run_worker_preference"

---

## UX Flow

### Mover -- Day-of Shift View

1. Mover opens /crew dashboard. If they have a shift today, a prominent banner shows:
   "You have a shift today -- [Day] [AM/PM]" with a "Go to Shift" button.
   Button is only shown when shift.day_of_week matches today's weekday abbreviation.

2. Mover taps "Go to Shift" -> /crew/shift/<shift_id>.

3. Pre-start state: page shows shift details (date, slot, truck number, stop count)
   and a large "Start Shift" button. If ShiftRun already exists for this shift,
   skip to step 5.

4. Mover taps "Start Shift" -> POST /crew/shift/<shift_id>/start.
   - Creates ShiftRun.
   - Calls _notify_next_seller() for the first pending stop.
   - Redirects back to /crew/shift/<shift_id>.

5. In-progress state: stop list for this mover's truck, ordered by
   stop_order asc nulls last, id asc. Each stop card shows:
   - Seller name and pickup address (large text)
   - Number of items to collect (count of seller's 'available' items)
   - Current status badge
   - If pending: "Completed" and "Issue" buttons
   - If completed or issue: status badge + notes (read-only)
   - Progress indicator at top: "X of Y stops done"

6. Mover taps "Completed":
   - Optional notes field appears inline (vanilla JS show/hide).
   - Mover taps "Confirm" -> POST /crew/shift/<shift_id>/stop/<pickup_id>/update.
   - Sets status='completed', completed_at=now().
   - Writes picked_up_at on seller's items.
   - Calls _notify_next_seller().
   - Redirects back to shift view.

7. Mover taps "Issue":
   - Notes field appears inline, marked required.
   - Mover taps "Confirm" -> same POST route.
   - Sets status='issue', completed_at=now(), saves note.
   - Calls _notify_next_seller().
   - Redirects back to shift view.

8. When all stops are 'completed' or 'issue', an "End Shift" button appears.
   Tapping -> POST /crew/shift/<shift_id>/end -> sets ShiftRun.status='completed',
   ended_at=now(). Redirects to /crew with flash "Shift complete -- great work!"

Edge cases:
- Mover not assigned to this shift -> 403.
- Shift not today -> still accessible, but "Start Shift" shows a warning banner:
  "This shift is not scheduled for today."
- No stops assigned yet -> pre-start state shows "No stops have been assigned to this
  shift yet. Check back soon." Start Shift button is hidden.
- Two movers on the same truck share the same stop list. Status updates from either
  are visible on page refresh. No real-time sync needed.

---

### Admin -- Assign Sellers to a Shift

1. Admin navigates to /admin/crew/shift/<shift_id>/ops.

2. Page header: shift date, slot, assigned mover names, shift status (not started /
   in progress / completed), started_at if applicable.

3. Stop list grouped by truck number. Each stop row shows:
   - Seller name, pickup address, item count
   - Status badge (pending / completed / issue)
   - Notes if any
   - Remove button (hidden if status is not 'pending')

4. "Add Stop" form at the bottom of each truck group:
   - Seller dropdown: all sellers with 'available' items not already on this shift.
     Label format: "Seller Name (N items)"
   - Submit -> POST /admin/crew/shift/<shift_id>/assign
   - Creates ShiftPickup. Redirects back with flash "Seller added to Truck X."

5. Remove stop -> POST /admin/crew/shift/<shift_id>/stop/<pickup_id>/remove.
   - Blocked if status != 'pending'. Flash error: "Cannot remove a stop that is
     already in progress."

6. Link to this ops page is added to each published shift card on
   /admin/schedule/<week_id>: "View Ops ->"

---

### Worker -- Partner Preferences

1. Preferences section lives at the bottom of /crew/availability, below the
   availability grid. Separate form posting to /crew/preferences.

2. Two labeled multi-select inputs:
   - "Prefer to work with" -- all approved workers except self
   - "Prefer not to work with" -- same list

3. Pre-populated from existing WorkerPreference records for this user.

4. Submit -> POST /crew/preferences:
   - Validate: if same worker appears in both lists, reject with flash error:
     "A worker can't be in both lists."
   - Delete all existing WorkerPreference records for this user.
   - Insert new records from submitted values.
   - Flash "Preferences saved." Redirect back to /crew/availability.

---

## New Routes

| Method | Path | Function | Description |
|--------|------|----------|-------------|
| GET | /crew/shift/<shift_id> | crew_shift_view | Phone-optimized mover shift view |
| POST | /crew/shift/<shift_id>/start | crew_shift_start | Create ShiftRun, notify first seller |
| POST | /crew/shift/<shift_id>/stop/<pickup_id>/update | crew_shift_stop_update | Mark stop completed or issue |
| POST | /crew/shift/<shift_id>/end | crew_shift_end | Close ShiftRun |
| GET | /admin/crew/shift/<shift_id>/ops | admin_shift_ops | Live admin ops view |
| POST | /admin/crew/shift/<shift_id>/assign | admin_shift_assign_seller | Add seller stop to shift |
| POST | /admin/crew/shift/<shift_id>/stop/<pickup_id>/remove | admin_shift_remove_stop | Remove pending stop |
| POST | /crew/preferences | crew_save_preferences | Save partner preferences |

All /crew/* routes: require_crew() guard.
All /admin/crew/* routes: current_user.is_admin check.

---

## Model Changes

| Model | Change | Migration? |
|-------|--------|------------|
| ShiftPickup | New table | Yes |
| ShiftRun | New table | Yes |
| WorkerPreference | New table | Yes |
| User.worker_role | No schema change -- set to 'both' on approval, never shown to worker | No |

Single migration for all three tables:
  flask db migrate -m "shift_pickup_run_worker_preference"

---

## Template Changes

### New: templates/crew/shift.html
- Extends layout.html. Mobile-first, single column, no sidebars.
- Minimum button tap target: 48px tall.
- Pre-start state: shift summary card + large "Start Shift" button. Warning banner
  if shift is not today.
- In-progress state: progress indicator ("X of Y stops done") at top. Stop cards
  stacked vertically. Each card: seller name (large), address, item count, status
  badge, action buttons or read-only resolved state.
- Inline notes field: hidden by default, revealed by vanilla JS on button tap.
  Notes input and Confirm button are inside a form posting to the update route.
- Status badge colors via CSS variables:
    pending   -> --text-muted
    completed -> --primary
    issue     -> --accent
- "End Shift" button shown only when all stops are resolved.

### New: templates/admin/shift_ops.html
- Extends layout.html with admin_sidebar.html.
- Shift header: date, slot, mover names, status, started_at.
- Stop list grouped by truck. Each row: seller info, status badge, notes, remove button.
- "Add Stop" form per truck group.

### Modified: templates/crew/availability.html
- Add partner preferences section below the availability grid.
- Two multi-select inputs, pre-populated from DB.
- Separate form with {{ csrf_token() }} posting to /crew/preferences.

### Modified: templates/crew/dashboard.html
- "Today's Shift" banner if mover has a shift today.
- "Go to Shift" button -> /crew/shift/<shift_id>.
- If ShiftRun exists for that shift: button label is "Continue Shift".

### Modified: templates/crew/apply.html
- Remove role_pref field entirely from the application form.

### Modified: templates/admin/schedule_week.html
- "Driver" -> "Mover (Truck)", "Organizer" -> "Mover (Storage)" in all labels,
  dropdowns, and worker badges.
- Add "View Ops ->" link to each published shift card pointing to
  /admin/crew/shift/<shift_id>/ops.

---

## Business Logic

### Stop Ordering (Temporary, Pre Spec #6)

  ORDER BY stop_order ASC NULLS LAST, id ASC

Since stop_order is null until spec #6, all stops sort by insertion order.
Admins control sequence by the order they add sellers via the ops page.

---

### _notify_next_seller(shift, current_pickup=None) Stub

```python
def _notify_next_seller(shift, current_pickup=None):
    # TODO (spec #9): Send SMS to next seller in queue via Twilio.
    # Next stop = lowest stop_order (nulls last) / id among status='pending' stops
    # on this shift.
    next_pickup = (
        ShiftPickup.query
        .filter_by(shift_id=shift.id, status='pending')
        .order_by(ShiftPickup.stop_order.asc().nullslast(), ShiftPickup.id.asc())
        .first()
    )
    if next_pickup:
        app.logger.info(
            f"[SMS HOOK] Would notify seller {next_pickup.seller_id} "
            f"for shift {shift.id}, stop {next_pickup.id}"
        )
```

---

### picked_up_at Write on Completion

```python
items = InventoryItem.query.filter_by(
    seller_id=pickup.seller_id, status='available'
).all()
for item in items:
    if not item.picked_up_at:
        item.picked_up_at = datetime.utcnow()
db.session.commit()
```

---

### Optimizer -- Role Balance Tiebreaker

Before running the optimizer, tally historical ShiftAssignment records per worker:

```python
truck_count[worker_id]    # role_on_shift == 'driver'
storage_count[worker_id]  # role_on_shift == 'organizer'
role_imbalance[worker_id] = truck_count[worker_id] - storage_count[worker_id]
# positive -> this worker has done more truck; prefer storage next
# negative -> this worker has done more storage; prefer truck next
```

Add role_imbalance as the final tiebreaker in the optimizer sort key:
  (already_doubled, flexible_for_other_slot, load, abs(role_imbalance))

When assigning role_on_shift for a slot:
- If role_imbalance > 0, prefer role_on_shift = 'organizer'
- If role_imbalance < 0, prefer role_on_shift = 'driver'
- If tied, assign whichever role the shift needs more of

---

### Optimizer -- Partner Preferences

Before running, build preference and avoid sets from WorkerPreference:

```python
preferred_pairs = set()  # frozenset({id_a, id_b})
avoided_pairs   = set()  # frozenset({id_a, id_b})

for pref in WorkerPreference.query.all():
    pair = frozenset({pref.user_id, pref.target_user_id})
    if pref.preference_type == 'avoided':
        avoided_pairs.add(pair)
    else:
        preferred_pairs.add(pair)

preferred_pairs -= avoided_pairs  # avoid always overrides prefer
```

Applied during truck-level assignment (same shift, same truck):
1. Never place an avoided pair on the same shift if an alternative exists.
2. Prefer to place preferred pairs on the same shift where staffing allows.
Staffing coverage always takes priority over both constraints.

---

### Auth: Shift View Ownership Check

crew_shift_view, crew_shift_start, crew_shift_stop_update, crew_shift_end:
after require_crew(), verify current_user has a ShiftAssignment for this shift.
If not, abort(403).

---

## Constraints -- Do Not Touch

- Stripe webhook and all payment logic.
- Item status lifecycle -- picked_up_at is an operational milestone only, it does
  not change InventoryItem.status.
- Existing ShiftAssignment records -- optimizer changes are additive (new sort key
  dimensions only). No re-running or invalidation of published schedules.
- admin_shift_update and admin_shift_swap routes -- no changes.
- WorkerAvailability model and availability deadline logic -- preferences are a
  separate form and route, purely additive.
- User.worker_role schema -- no migration. Set to 'both' on new approvals going
  forward. Existing records left as-is.

---

## Sign-off Checklist

Work through these manually after Claude Code finishes. Check each one before
signing off in SPEC_CHECKLIST.md.

### Migration & Models
- [ ] Migration ran cleanly with no errors
- [ ] ShiftPickup table exists with all fields including stop_order (nullable)
- [ ] ShiftRun table exists with unique constraint on shift_id
- [ ] WorkerPreference table exists with unique constraint on (user_id, target_user_id, preference_type)

### Terminology
- [ ] "Driver" no longer appears in any crew-facing template (apply, dashboard, shift, availability)
- [ ] Admin schedule view shows "Mover (Truck)" and "Mover (Storage)" labels
- [ ] role_pref field is gone from the worker application form

### Mover Shift View (/crew/shift/<id>)
- [ ] Page is inaccessible to workers not assigned to that shift (expect 403)
- [ ] Pre-start state: shift details visible, Start Shift button present
- [ ] Pre-start state: if no stops assigned, Start Shift button is hidden and message shows
- [ ] Start Shift creates a ShiftRun record in the DB
- [ ] In-progress state: stop list renders with seller name, address, item count
- [ ] Progress indicator ("X of Y stops done") updates correctly
- [ ] "Completed" button tap reveals optional notes field without a page reload
- [ ] Submitting Completed sets status and writes picked_up_at on seller's items
- [ ] picked_up_at is NOT overwritten if already set on an item
- [ ] "Issue" button tap reveals notes field marked required
- [ ] Submitting Issue without a note is rejected
- [ ] After all stops resolved, End Shift button appears
- [ ] End Shift sets ShiftRun.status='completed' and ended_at, redirects to /crew
- [ ] [SMS HOOK] log line appears in app logs on every stop completion (check Render logs)

### Admin Ops View (/admin/crew/shift/<id>/ops)
- [ ] Page loads and shows shift header (date, slot, mover names, status)
- [ ] Stop list is grouped by truck number
- [ ] "Add Stop" dropdown only shows sellers with available items not already on this shift
- [ ] Adding a stop creates a ShiftPickup record and refreshes the page
- [ ] Remove button is visible on pending stops and hidden on completed/issue stops
- [ ] Attempting to remove a non-pending stop returns a flash error
- [ ] "View Ops ->" link appears on each published shift card on /admin/schedule/<week_id>

### Partner Preferences (/crew/availability)
- [ ] Preferences section renders below the availability grid
- [ ] Both multi-selects are pre-populated with existing preferences on page load
- [ ] Submitting with the same worker in both lists returns a flash error
- [ ] Valid submission saves to DB and redirects back with "Preferences saved" flash
- [ ] Resubmitting replaces old preferences entirely (no duplicates accumulate)

### Crew Dashboard (/crew)
- [ ] "Today's Shift" banner appears only on the day of the shift
- [ ] Banner links to the correct /crew/shift/<id>
- [ ] If ShiftRun already exists, button reads "Continue Shift" not "Go to Shift"
- [ ] No banner shown on days with no shift

### Optimizer
- [ ] Re-run optimizer on a draft week and confirm it still produces valid assignments
- [ ] Check that workers with more truck shifts get storage assignments as tiebreaker
- [ ] Add two workers as preferred pair, run optimizer -- confirm they land on same shift where possible
- [ ] Add an avoid pair, run optimizer -- confirm they are not placed on same shift
- [ ] Manual swap via admin_shift_swap still works on a published schedule (not broken by optimizer changes)

