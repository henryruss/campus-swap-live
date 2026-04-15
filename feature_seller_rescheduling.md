# Spec #8 — Seller Rescheduling

**Dependencies:** Spec #6 (Route Planning) ✅ signed off 2026-04-14
**Status:** Ready for implementation

---

## Goal

Sellers are notified of their pickup via email once admin runs "Notify Sellers"
(spec #6). Between that notification and shift day, life happens — sellers
move their timeline, have class conflicts, or aren't home. Right now there is
no self-serve escape hatch. This spec adds a token-gated reschedule flow that
lets sellers pick a new available slot, automatically moves their `ShiftPickup`
cleanly, and keeps admin informed without noise.

Additionally, `moveout_date` — already stored on `User` but not yet surfaced
in the main pickup modal — is wired into both the seller-facing flow (optional
input in the pickup week modal) and the auto-assignment optimizer (hard
constraint: never schedule a seller on or after their move-out date).

---

## UX Flow

### Seller Side — Reschedule

**Entry point 1 — pickup notification email.**
The pickup confirmation email contains a styled secondary CTA button below the
shift details block: "Need to reschedule? Pick a new time →". URL:
`https://usecampusswap.com/reschedule/<token>`.

**Entry point 2 — dashboard Pickup Window cell.**
After a seller has been notified (`ShiftPickup.notified_at IS NOT NULL`), the
Pickup Window stat cell upgrades from week/preference format ("Wk 1 · Morning")
to a specific date format ("Tue, Apr 29 · Morning"). The cell remains clickable
and opens the pickup week modal, but the week and time preference fields become
read-only — those are now controlled by ops. A "Need a different time?
Reschedule →" link appears inside the modal, going to `/seller/reschedule`.
The move-out date field remains editable at all times.

If `notified_at` is subsequently cleared (seller moved to a different shift),
the cell reverts to "Wk 1 · Morning" format until the next notification.

**Step 1 — Reschedule page (`GET /reschedule/<token>` or `GET /seller/reschedule`).**

Layout mirrors the worker availability grid on `/crew/availability`: a grid of
day-columns × AM/PM rows covering the eligible date range, each cell a toggle
card. Exactly one cell can be selected at a time (radio semantics, card UI).
Selected card gets `.is-selected` class via JS — same toggle pattern as
pickup-access-type cards in the dashboard modal. No `onclick` on cards; use
the `change` event on the underlying `<input type="radio">`.

Above the grid:
- Current pickup summary card: "Your current pickup: **Tuesday AM, April 29**"
- Amber callout: "Selecting a new time will move you off your current slot.
  Your items may be picked up on a different day than originally scheduled."

Below the grid:
- "Confirm Reschedule" submit button — disabled until a card is selected
  (JS toggles `disabled`).
- "Keep my current pickup →" link back to dashboard.
- If zero eligible cells: hide grid and button; show amber callout:
  "No open slots available right now. Reply to your confirmation email and
  we'll sort it out."

**Step 2 — Confirmation (`POST /reschedule/<token>` or `POST /seller/reschedule`).**

- Seller submits selected `new_shift_id`.
- Backend validates, moves the `ShiftPickup`, repacks old route, appends to
  overflow truck on new shift.
- Admin alert email sent if new shift is within urgency threshold.
- Token invalidated (one-time use).
- Seller lands on confirmation page: "You're all set — we'll send a new
  confirmation once the route is finalized. [Back to dashboard →]"

**Edge cases:**
- Token already used → confirmation page with `error='already_used'`.
- Token expired → confirmation page with `error='expired'` + contact email.
- Shift already in progress (`ShiftRun.status='in_progress'`) → error:
  "Your pickup is already underway."
- Seller selects their current shift → no-op, redirect to dashboard:
  "No changes made."
- Seller has no `ShiftPickup` → 404.

---

### Seller Side — Move-Out Date in Pickup Modal

The existing pickup week modal gains one new optional field below the time
preference buttons, above the Save button:

**"Move-out date (optional)"**
- `<input type="date">` named `moveout_date`.
- Pre-populated if `current_user.moveout_date` is set.
- Label: "Move-out date — helps us schedule your pickup before you leave."
- Client-side `min` = first day of selected pickup week; `max` = last day of
  pickup week + 3 days. Backend accepts any date without range-checking.
- Saved via the existing `POST /api/user/set_pickup_week` — add `moveout_date`
  to the fields it reads and persists. Empty string → set `None`.

No migration needed — `User.moveout_date` already exists.

---

### Admin Side

**"Notify Sellers" confirmation dialog.**
Before the existing notify POST fires, a JS confirmation dialog appears:

> "This will email [X] sellers their pickup date and time. Make sure the route
> is finalized before sending — sellers who've already been notified won't
> receive a duplicate. Continue?"

Two buttons: "Send Notifications" and "Go Back." X is the count of sellers
with `notified_at IS NULL` on that shift, rendered server-side into a
`data-unnotified-count` attribute on the Notify Sellers button. JS reads it
to build the message on `submit` of the notify form. No `onclick` — use a
`submit` event listener.

**Overflow truck designation (ops page).**
Each truck card on `/admin/crew/shift/<id>/ops` gets an "Overflow" toggle
button in the card header. Exactly one truck per shift can be designated at a
time. Active truck shows a green "Overflow" badge. Toggle POSTs to
`/admin/crew/shift/<id>/set-overflow-truck` with `truck_number` in the body.
Toggling the already-active truck sets it to NULL (off). If no overflow truck
is set, rescheduled pickups fall back to truck 1.

**Reschedule lock (ops page).**
"Lock Rescheduling" button in the shift header actions area. When locked, shift
is excluded from all seller slot menus. Red "Rescheduling Locked" badge in
header when active. Toggles via
`POST /admin/crew/shift/<id>/toggle-reschedule-lock`.

**Reschedule Activity panel (ops page).**
Read-only panel at the bottom of the ops page. Two subsections:
- "Added via Reschedule" — pickups where `shift_id = this shift` AND
  `rescheduled_from_shift_id IS NOT NULL`. Each row: seller name (links to
  `/admin/seller/<id>`), "from [old shift label]", timestamp.
- "Moved Away" — pickups where `rescheduled_from_shift_id = this shift.id`.
  Each row: seller name, "to [new shift label]", timestamp.
- Empty state: "No reschedule activity for this shift."

**Stale route notice (ops page).**
Amber banner at top of ops page if any pickup on this shift has
`rescheduled_at IS NOT NULL` AND `stop_order IS NULL`:
"Route order may be stale — a stop was rescheduled in since last ordering.
Re-run 'Order Route' before this shift starts."

**Mover shift view notice.**
On `/crew/shift/<id>`, if any stop on the mover's truck has `rescheduled_at
IS NOT NULL` AND `stop_order IS NULL`, show an amber notice above the stop
list: "1 stop was added after the route was ordered — it appears at the
bottom." (Count if > 1.)

**Move-out date on admin route builder.**
Each seller card in the unassigned panel at `/admin/routes` gains a "Moves
out: [date]" line below the AM/PM badge, rendered only if
`user.moveout_date IS NOT NULL`. Format: "Moves out: Apr 29".

---

## Notification Timing Rules

### When `notified_at` is cleared (seller becomes re-notifiable)

`ShiftPickup.notified_at` is set to `None` when the seller's `shift_id`
changes to a different shift — meaning a different date or slot, where the
email copy would be wrong. This happens in two places:

1. **`_do_reschedule`** — already specified below; `notified_at = None` is
   step 9.
2. **`admin_routes_stop_move`** (existing route from spec #6) — when a stop
   is moved to a different `shift_id`, add `pickup.notified_at = None` after
   updating `pickup.shift_id`. If only `truck_number` changes within the same
   shift, do not clear it.

### When `notified_at` is NOT cleared

- `truck_number` changes within the same shift (truck reassignment on ops page).
- `stop_order` changes (route reordering).
- Seller address or access info changes.

**The rule: shift identity changes = clear `notified_at`. Everything else =
leave it alone.**

---

## New Routes

| Method | Path | Function | Description |
|--------|------|----------|-------------|
| GET | `/reschedule/<token>` | `seller_reschedule_get` | Token-gated reschedule page (no login required) |
| POST | `/reschedule/<token>` | `seller_reschedule_post` | Submit via token |
| GET | `/seller/reschedule` | `seller_reschedule_auth_get` | Auth-gated reschedule page |
| POST | `/seller/reschedule` | `seller_reschedule_auth_post` | Submit via auth session |
| POST | `/admin/crew/shift/<id>/set-overflow-truck` | `admin_set_overflow_truck` | Set overflow truck (admin only) |
| POST | `/admin/crew/shift/<id>/toggle-reschedule-lock` | `admin_toggle_reschedule_lock` | Lock/unlock shift from reschedules (admin only) |

Both seller-facing GET/POST pairs share `_do_reschedule(pickup, new_shift)`,
`_get_eligible_reschedule_shifts(pickup)`, and
`_build_reschedule_grid(eligible, current_shift)` helpers. The only difference
between the two paths is how the seller and their `ShiftPickup` are resolved.

---

## Model Changes

### New model: `RescheduleToken`

```
id
token           String(64), unique, indexed  — secrets.token_urlsafe(48)
pickup_id       FK -> ShiftPickup
seller_id       FK -> User  (denormalized for fast lookup)
created_at      DateTime
used_at         DateTime, nullable  — NULL = unused; set on successful reschedule
expires_at      DateTime  — created_at + reschedule_token_ttl_days days
Relationships: pickup -> ShiftPickup (backref: reschedule_tokens), seller -> User
```

### New fields on existing models

**`ShiftPickup`**
- `rescheduled_from_shift_id` (Integer, FK -> Shift, nullable) — shift this
  stop was moved from. NULL = original assignment.
- `rescheduled_at` (DateTime, nullable) — Eastern-time timestamp of reschedule.

**`Shift`**
- `overflow_truck_number` (Integer, nullable) — overflow-designated truck.
  NULL = fall back to truck 1.
- `reschedule_locked` (Boolean, default False, server_default `'0'`).

**`User`** — no new columns. `moveout_date (Date, nullable)` already exists.
This spec wires it into the modal and optimizer only.

**Migration name:** `add_seller_rescheduling`

---

## Template Changes

### New templates

**`templates/seller/reschedule.html`** (extends `layout.html`)

Grid layout matching the worker availability style. Columns = dates spanning
the eligible range. Rows = AM / PM.

Each cell is a `<label>` wrapping `<input type="radio" name="new_shift_id"
value="{{ shift.id }}">`. Disabled/greyed cells for dates with no eligible
shift. The seller's current pickup cell renders with a "current" style note
but is still selectable (selecting it is a no-op on submission).

JS: on `change` of any radio, toggle `.is-selected` on parent label, remove
from all others, enable submit button. No `onclick` attributes.

Context variable `token` passed as a hidden input on the token path; form
action set to the appropriate endpoint based on which path is active.

**`templates/seller/reschedule_confirm.html`** (extends `layout.html`)
Shared by success and all error states.
- Success: "You're all set." + new shift label. "Back to dashboard →"
- Error: amber callout with `error_message`, contact email, "Back to
  dashboard →" link.

### Modified templates

**`templates/dashboard.html`**

*Pickup Week Modal:*
- Add `moveout_date` date input below time preference buttons, above Save.
  Label: "Move-out date (optional) — helps us schedule your pickup before
  you leave." Pre-populate from `current_user.moveout_date` if set.
  Include `moveout_date` in the fetch payload to `/api/user/set_pickup_week`.
- When `shift_pickup.notified_at IS NOT NULL`: week and time preference fields
  render as read-only display text (not inputs). Add "Need a different time?
  Reschedule →" link pointing to `/seller/reschedule`. Move-out date input
  remains editable regardless.

*Pickup Window stat cell:*
- Before notification: "Wk 1 · Morning" (existing format).
- After notification (`notified_at IS NOT NULL`): "Tue, Apr 29 · Morning"
  using the actual shift date. Derived from `shift_pickup.shift` in the
  dashboard context.
- If `notified_at` is cleared (seller moved shifts): reverts to week format.
- If `shift_pickup` exists, `notified_at IS NOT NULL`, and shift not started:
  render "Reschedule →" link below the date label. Links to
  `/seller/reschedule`.

**Pickup notification email template**
- Styled secondary CTA button below shift details block:
  "Need to reschedule? Pick a new time →"
- URL: `https://usecampusswap.com/reschedule/<token>`
- Token generated/retrieved inside `admin_notify_sellers` via
  `_get_or_create_reschedule_token(pickup)`. Existing idempotency guard
  (skip already-notified sellers) is unchanged — token generation piggybacks
  on the existing per-seller send loop.

**`templates/admin/shift_ops.html`**
- Notify Sellers button: add `data-unnotified-count="{{ unnotified_count }}"`
  attribute. `unnotified_count` = count of pickups on this shift with
  `notified_at IS NULL`, passed in template context. JS `submit` event
  listener on the notify form reads this attribute and shows the confirmation
  dialog before allowing the form to submit.
- Overflow toggle per truck card header (green "Overflow" badge when active).
- Reschedule lock toggle in shift header (red "Rescheduling Locked" badge
  when active).
- Stale route amber banner (server-rendered, conditional — any pickup with
  `rescheduled_at IS NOT NULL` AND `stop_order IS NULL`).
- Reschedule Activity panel at page bottom (two lists, server-rendered).
  Pass `rescheduled_in` and `rescheduled_out` lists in template context.

**`templates/admin/routes.html`**
- Seller card in unassigned panel: "Moves out: [date]" line below AM/PM
  badge, conditional on `user.moveout_date IS NOT NULL`.

**`templates/crew/shift.html`**
- Amber notice above stop list when any stop on the mover's truck has
  `rescheduled_at IS NOT NULL` AND `stop_order IS NULL`.

---

## Business Logic

### `api_set_pickup_week` — add moveout_date

```python
moveout_raw = request.json.get('moveout_date', '')
if moveout_raw:
    try:
        current_user.moveout_date = date.fromisoformat(moveout_raw)
    except ValueError:
        pass  # ignore malformed silently
else:
    current_user.moveout_date = None
```

### Slot eligibility: `_get_eligible_reschedule_shifts(pickup)`

A shift is eligible if ALL conditions are met:

1. `Shift.is_active = True`
2. `Shift.reschedule_locked = False`
3. Shift date is strictly in the future relative to `_today_eastern()`.
   Exception: a PM slot on today is eligible if the seller's current shift
   is an AM slot on the same date (same-day AM→PM move).
4. No `ShiftRun` with `status='in_progress'` for this shift.
5. Shift date is within `reschedule_max_weeks_forward` weeks forward of the
   seller's current pickup shift date. No backward cap beyond rule 3 — a
   seller may move to an earlier future date freely.
6. If `seller.moveout_date` is set: `shift_date < seller.moveout_date`
   (strictly before; seller cannot reschedule to their own move-out day).

Sort ascending by date, AM before PM within the same date. Return at most 6.

No capacity gate is exposed to the seller. The overflow truck uses the same
soft `capacity_warning` flag as auto-assign — rescheduling always succeeds
if a slot is eligible.

### Token lifecycle: `_get_or_create_reschedule_token(pickup)`

```python
ttl = int(_get_app_setting('reschedule_token_ttl_days', '7'))
now = _now_eastern()

existing = (RescheduleToken.query
    .filter_by(pickup_id=pickup.id)
    .filter(RescheduleToken.used_at.is_(None))
    .filter(RescheduleToken.expires_at > now)
    .order_by(RescheduleToken.created_at.desc())
    .first())
if existing:
    return existing

rec = RescheduleToken(
    token=secrets.token_urlsafe(48),
    pickup_id=pickup.id,
    seller_id=pickup.seller_id,
    created_at=now,
    expires_at=now + timedelta(days=ttl),
)
db.session.add(rec)
return rec  # caller commits
```

Called inside the existing `admin_notify_sellers` route at send time, once
per seller being notified. The resulting token URL is injected into the email.

### `_do_reschedule(pickup, new_shift)` helper

```
1.  overflow_truck = new_shift.overflow_truck_number or 1
2.  old_shift = pickup.shift  (hold reference before mutation)

    # Elegant removal from old route — repack remaining stop_order values
3.  remaining = (ShiftPickup.query
        .filter_by(shift_id=old_shift.id)
        .filter(ShiftPickup.id != pickup.id)
        .order_by(ShiftPickup.stop_order.nullslast(), ShiftPickup.id)
        .all())
    for i, p in enumerate(remaining, start=1):
        p.stop_order = i

    # Move to new shift
4.  pickup.shift_id = new_shift.id
5.  pickup.truck_number = overflow_truck
6.  pickup.stop_order = None         (appended last; shown at bottom of list)
7.  pickup.rescheduled_from_shift_id = old_shift.id
8.  pickup.rescheduled_at = _now_eastern()
9.  pickup.notified_at = None        (fresh notification needed for new shift)

    # Capacity warning on overflow truck
10. existing_count = ShiftPickup.query.filter_by(
        shift_id=new_shift.id, truck_number=overflow_truck
    ).count()
    effective_cap = _get_effective_truck_capacity()
    pickup.capacity_warning = (existing_count >= effective_cap)

11. db.session.commit()

    # Admin alert — immediate email only if shift is soon
12. days_until = (shift_date(new_shift) - _today_eastern()).days
    threshold = int(_get_app_setting('reschedule_urgent_alert_days', '2'))
    if days_until <= threshold:
        _send_admin_reschedule_alert(pickup, old_shift, new_shift)
    # Beyond threshold: ops page Reschedule Activity panel only, no email.
```

### `admin_routes_stop_move` — clear `notified_at` on shift change

In the existing stop movement route (spec #6), after updating `pickup.shift_id`:

```python
if pickup.shift_id != original_shift_id:
    pickup.notified_at = None
# Do NOT clear notified_at if only truck_number changed within the same shift
```

### Admin alert email

- To: `ADMIN_EMAIL` env var.
- Subject: `Reschedule alert: {seller.full_name} — {old_shift.label} -> {new_shift.label}`
- Body: seller name, old shift label + date, new shift label + date, link to
  `/admin/seller/{seller.id}`, timestamp (Eastern).
- Sent via existing Resend helper.

### Token-gated route logic

```
GET /reschedule/<token>:
    rec = RescheduleToken.query.filter_by(token=token).first_or_404()
    if rec.used_at:                              -> render confirm, error='already_used'
    if rec.expires_at < _now_eastern():          -> render confirm, error='expired'
    pickup = rec.pickup
    run = pickup.shift.run
    if run and run.status == 'in_progress':      -> render confirm, error='underway'
    eligible = _get_eligible_reschedule_shifts(pickup)
    dates, rows = _build_reschedule_grid(eligible, pickup.shift)
    render reschedule.html, token=token, pickup=pickup,
           dates=dates, rows=rows, eligible=eligible

POST /reschedule/<token>:
    [re-run all GET validations — do not trust form alone]
    new_shift_id = request.form.get('new_shift_id', type=int)
    if not new_shift_id: flash error, redirect GET
    new_shift = Shift.query.get_or_404(new_shift_id)
    eligible_ids = {s.id for s in _get_eligible_reschedule_shifts(pickup)}
    if new_shift_id not in eligible_ids: abort(400)
    if new_shift_id == pickup.shift_id:
        flash("No changes made.", "info")
        return redirect(url_for('dashboard'))
    _do_reschedule(pickup, new_shift)
    rec.used_at = _now_eastern()
    db.session.commit()
    render reschedule_confirm.html, new_shift=new_shift
```

Auth-gated flow (`/seller/reschedule`) is identical; pickup resolved via
`current_user.shift_pickups` (at most one, per global unique constraint from
spec #3). If none exists: 404.

### `_build_reschedule_grid(eligible_shifts, current_shift)`

```python
all_shifts = eligible_shifts + [current_shift]
start_date = min(s.date for s in all_shifts)
end_date   = max(s.date for s in all_shifts)
dates = [start_date + timedelta(days=i)
         for i in range((end_date - start_date).days + 1)]

shift_map   = {(s.date, s.slot): s for s in eligible_shifts}
current_key = (current_shift.date, current_shift.slot)

rows = {'am': [], 'pm': []}
for d in dates:
    for slot in ('am', 'pm'):
        key = (d, slot)
        rows[slot].append({
            'date':       d,
            'shift':      shift_map.get(key),
            'is_current': key == current_key,
            'disabled':   key not in shift_map and key != current_key,
        })
return dates, rows
```

Template iterates `dates` as columns, `rows['am']` and `rows['pm']` as the
two row bands.

### Move-out date gate in auto-assign (`_run_auto_assign`)

When evaluating candidate shifts for a seller, skip any shift where:

```python
seller.moveout_date and shift_date(shift) >= seller.moveout_date
```

If no valid shift passes after the gate, seller goes to TBD with reason:
`"No eligible shift before move-out date ({seller.moveout_date})"`

This applies to both the auto-assign route and the manual-assign route
(`/admin/routes/seller/<id>/assign`).

### `admin_set_overflow_truck`

```python
truck_number = request.form.get('truck_number', type=int)
shift = Shift.query.get_or_404(id)
shift.overflow_truck_number = (
    None if shift.overflow_truck_number == truck_number else truck_number
)
db.session.commit()
redirect ops page, flash "Overflow truck updated."
```

### `admin_toggle_reschedule_lock`

```python
shift = Shift.query.get_or_404(id)
shift.reschedule_locked = not shift.reschedule_locked
db.session.commit()
msg = "Rescheduling locked." if shift.reschedule_locked else "Rescheduling unlocked."
redirect ops page, flash msg
```

---

## AppSettings

Three new keys — seeded in migration (skip if key already exists):

| Key | Default | Description |
|-----|---------|-------------|
| `reschedule_token_ttl_days` | `'7'` | Days until a reschedule link expires |
| `reschedule_max_weeks_forward` | `'1'` | Weeks forward a seller can reschedule into (0 = same week only) |
| `reschedule_urgent_alert_days` | `'2'` | Reschedules within N days of shift fire an immediate admin email; others appear on ops page only |

All read via existing `_get_app_setting(key, default)` helper.

---

## Migration

**Name:** `add_seller_rescheduling`

Steps (idempotent — check column/table existence before adding, same pattern
as spec #6 migration):

1. Create `reschedule_token` table.
2. Add `shift_pickup.rescheduled_from_shift_id` (Integer, FK -> shift.id, nullable).
3. Add `shift_pickup.rescheduled_at` (DateTime, nullable).
4. Add `shift.overflow_truck_number` (Integer, nullable).
5. Add `shift.reschedule_locked` (Boolean, server_default `'0'`).
6. Seed AppSettings (skip if key exists):
   - `reschedule_token_ttl_days = '7'`
   - `reschedule_max_weeks_forward = '1'`
   - `reschedule_urgent_alert_days = '2'`

No `User` migration needed — `moveout_date` already exists.

---

## Constraints

- Do not touch `_get_payout_percentage`, payout logic, or Stripe flows.
- Do not modify the "Notify Sellers" idempotency guard (skip already-notified).
  Token generation piggybacks inside the existing per-seller send loop only.
- Do not modify the `ShiftPickup` global unique constraint on `seller_id`. The
  reschedule moves the existing row in place — it never creates a new one.
- `/reschedule/<token>` is unauthenticated. It must not expose any seller data
  beyond the current pickup summary and the slot grid scoped to that token.
- Stop order repacking in `_do_reschedule` step 3 must use `nullslast()` so
  stops already at NULL sort to the end, preserving order for the rest.
- `notified_at` is cleared only when `shift_id` changes. Truck reassignment
  and stop reordering within the same shift must never clear it.
- All datetime operations use `_now_eastern()` / `_today_eastern()`. No
  `datetime.utcnow()`.
- Move-out gate in auto-assign is additive — no other assignment logic changes.
- `RescheduleToken` has no deep FK chain — ORM deletion is safe.
