# Spec #D1 — Delivery Routes

**Status:** 🔲 Not yet built
**Depends on:** Buyer Delivery Flow ✅, Spec #6 Route Planning ✅, Spec #5 Payout Reconciliation ✅
**Followed by:** Spec #D2 — Delivery Route Ordering (Google Maps integration, out of scope here)

---

## Goal

Give admin visibility into sold items that need to go out for delivery, and the ability to build a
delivery run: create a delivery shift, assign stops from the unassigned buyer queue, assign a
driver, and let that driver execute the run from their phone. Closes the operational gap between
"Stripe says item is sold" and "item is physically in the buyer's hands."

---

## Key Design Decisions

**Delivery shifts reuse `Shift` + `ShiftWeek`.** No new scheduling model. Admin creates a shift
via the schedule page and marks it as `shift_type='delivery'`. It appears in the same Ops left
panel alongside pickup shifts. Workers use the same assignment UI. This keeps the ops page as the
single control surface for all field ops.

**`shift_type` is set implicitly by the first stop added to a truck, not by a form field.** There
is no shift type radio anywhere. Admin creates a shift exactly as today (calendar-based, no new
UI). The moment admin adds the first stop to a truck, the system knows what kind of truck it is:
if the first add is a seller (via `admin_shift_assign_seller`), the truck triggers the existing
storage unit picker gate. If the first add is a buyer order (via `admin_delivery_add_stop`), the
truck is a delivery truck — no storage unit needed. `Shift.shift_type` is derived from whether
any `DeliveryStop`s exist on the shift (checked at render time), not stored as a form-selected
value. The field on the model exists purely as a runtime convenience cache — it is written
automatically when the first delivery stop is added and cleared if all delivery stops are removed.

**A truck is either pickup or delivery — never both.** A truck that has at least one `ShiftPickup`
cannot receive a `DeliveryStop`, and vice versa. Enforced server-side on both add routes, with a
clear error message. This prevents mixed trucks from creating driver confusion.

**Order Route is out of scope for this spec.** Delivery route ordering will be addressed in
Spec #D2 using Google Maps. For now, admin manually assigns stops; `stop_order` defaults to
insertion order. Notify Buyer is available as soon as a stop is added — no ordering gate.

---

## UX Flow

### Admin — Creating a Delivery Shift

No new UI. Admin creates a shift exactly as today — select a date on the calendar, pick AM or PM,
done. The shift starts neutral. It becomes a "delivery shift" implicitly once the first buyer stop
is added to one of its trucks (see Building the Delivery Run below).

In the Ops left panel, once at least one `DeliveryStop` exists on a shift, a teal **"Delivery"**
badge appears next to the shift label. Shifts with only `ShiftPickup`s show the existing amber AM /
blue PM badge unchanged. A shift can have some pickup trucks and some delivery trucks — the badge
just indicates at least one delivery truck is present.

### Admin — Building the Delivery Run

1. Admin selects the delivery shift in the Ops left panel.
2. **Main area** shows truck cards as usual — one per truck. Truck cards for delivery shifts show
   delivery stops (item thumbnail, buyer address, unit size) instead of seller stops. The storage
   location chip is absent (not relevant for outbound delivery). All other chrome — capacity bar,
   "Add Truck" button, truck detail drawer — works identically.
3. **Right sidebar** — below the existing "Unassigned Sellers" section, a new
   **"Unassigned Deliveries"** section appears. Always visible regardless of which shift is
   selected. Each card shows:
   - Item thumbnail
   - Item title + `#ID` badge
   - Buyer address (short: city + street)
   - Unit size
   - Days since purchase (oldest first)
4. Admin clicks a buyer card → inline assign form expands: truck selector dropdown + submit
   button. Same UX pattern as seller assignment.
5. Submit → `POST /admin/delivery/shift/<shift_id>/add-stop`. Server validates:
   - Shift is `shift_type='delivery'`
   - `BuyerOrder` has no existing `DeliveryStop` (globally unique)
   - Target truck has no `ShiftPickup`s (no mixed trucks)
   - If truck has existing `DeliveryStop`s, allow (same truck, different stop)
   - Returns 409 with user-readable error if any guard fails. Error shown inline below the card.
6. On success: page reloads to `?shift_id=<id>`. Stop appears on the truck card. Buyer card
   disappears from the Unassigned Deliveries panel.

### Admin — Notifying a Buyer

On each delivery stop card (in the truck detail drawer), an envelope icon / "Notify" button
appears. Clicking sends a delivery scheduled email to `BuyerOrder.buyer_email` and sets
`DeliveryStop.notified_at`. Button changes to "Notified ✓" after send. Re-clicking resends and
updates timestamp (idempotent).

No bulk notify for now. Per-stop only.

### Admin — Removing a Stop

In the truck detail drawer, a "Remove" button on each pending stop (same as pickup flow). Only
available before the `DeliveryRun` exists (pre-run). POST to remove route → page reload.

### Admin — Live Monitoring

Once the driver starts the run (`DeliveryRun` created), the truck card switches to live state:
- "In progress" / "Complete" pill
- Stops done counter (e.g. "3 / 5 delivered")
- Issue alert strip if any stop is flagged

Truck detail drawer shows live status per stop (gray = pending, green = delivered + timestamp,
red = issue).

### Driver — Crew Dashboard (`/crew`)

The existing crew dashboard shows "Today's shift" and "My schedule." Delivery shifts appear
alongside pickup shifts in both sections. The shift row label reads the delivery shift date + a
teal "Delivery" badge. Clicking the row links to `/crew/delivery/<shift_id>` instead of
`/crew/shift/<shift_id>`. No other dashboard changes.

### Driver — Delivery Run View (`/crew/delivery/<shift_id>`)

Phone-optimized. Mirrors `/crew/shift/<shift_id>` closely.

**Pre-run state** (no `DeliveryRun` yet):
```
[Header card]
  Delivery Run · [Date]
  Truck [N] · [X] stops · [Y] units

[Stop list — ordered by stop_order, nulls last]
  Each stop card:
    #N  [thumbnail]  Item Title
        123 Main St, Unit 4, Chapel Hill
        1.5 units
        ○ Pending

[Start Run button — bottom of page]
```

**Live state** (after Start Run):
- Same stop list, stop cards are now tappable.
- Tapping a pending stop expands two actions:
  - **"Mark Delivered"** → POST to update route, sets stop `completed`, triggers delivery
    confirmation email to buyer (Spec #D3, not in scope here — placeholder only).
  - **"Flag Issue"** → text input + submit, sets stop `issue`.
- Completed stops show green circle + timestamp.
- Issue stops show red circle + notes.

**Auto-refresh:** 30-second interval on stop list (same `fetch` + `innerHTML` pattern as
`crew/shift.html` / `stops_partial.html`). A `GET /crew/delivery/<shift_id>/stops-partial`
endpoint returns the stop list HTML partial.

**End Run:** Button appears when all stops are `completed` or `issue` (no pending). Tapping →
confirmation screen ("Are you sure? X delivered, Y issues.") → POST to end route → completion
screen.

---

## New Routes

| Method | Path | Function | Description |
|--------|------|----------|-------------|
| `GET /admin/ops/delivery-queue` | `admin_ops_delivery_queue` | HTML partial: all unassigned `BuyerOrder`s (sold, no `DeliveryStop`, not yet delivered). Sorted oldest-purchase-first. Rendered into right sidebar on ops page load. |
| `POST /admin/delivery/shift/<shift_id>/add-stop` | `admin_delivery_add_stop` | Add `DeliveryStop` to shift. Validates shift type, unique order, no mixed truck. Returns JSON `{stop_id, unit_total}` or `{error}`. |
| `POST /admin/delivery/shift/<shift_id>/remove-stop/<stop_id>` | `admin_delivery_remove_stop` | Remove `DeliveryStop`. Pre-run only (`DeliveryRun` must not exist). Returns JSON. |
| `POST /admin/delivery/stop/<stop_id>/notify` | `admin_delivery_notify_buyer` | Send delivery scheduled email to buyer. Sets `DeliveryStop.notified_at`. Idempotent. Returns JSON `{notified_at}`. |
| `GET /crew/delivery/<shift_id>` | `crew_delivery_view` | Phone-optimized delivery run view. Requires `is_worker` or `is_admin`. Shift must be `shift_type='delivery'`. |
| `GET /crew/delivery/<shift_id>/stops-partial` | `crew_delivery_stops_partial` | HTML partial for 30s auto-refresh of stop list. No layout. |
| `POST /crew/delivery/<shift_id>/start` | `crew_delivery_start` | Creates `DeliveryRun`. Guards: no existing run, shift is delivery type, worker assigned to shift. |
| `POST /crew/delivery/stop/<stop_id>/update` | `crew_delivery_stop_update` | Mark stop `completed` or `issue`. Sets `BuyerOrder.delivered_at` on completion. Worker must be assigned to shift. |
| `POST /crew/delivery/<shift_id>/end` | `crew_delivery_end` | Marks `DeliveryRun` complete. Guard: no pending stops (or admin `force=true`). Sets `ended_at`. |

---

## Model Changes

### `Shift` (existing) — add `has_delivery` property / cache

`shift_type` as a stored column is dropped from this spec. Instead, a shift is considered a
"delivery shift" at the truck level, not the shift level. Whether a given truck is pickup or
delivery is determined by which stop type it has:

```python
# Runtime check used in templates and route guards:
def truck_is_delivery(shift, truck_number):
    return DeliveryStop.query.filter_by(
        shift_id=shift.id, truck_number=truck_number
    ).count() > 0

def truck_is_pickup(shift, truck_number):
    return ShiftPickup.query.filter_by(
        shift_id=shift.id, truck_number=truck_number
    ).count() > 0
```

A shift-level `has_delivery_trucks` convenience property on `Shift` (computed, not stored) returns
`True` if any `DeliveryStop` exists for that shift. Used for the teal badge in the ops left panel
and for gating the crew delivery link.

**No migration needed for `shift_type`.**

Existing ops queries, auto-assignment, rescheduling, SMS, and notification flows are guarded
differently: they filter `ShiftPickup` specifically (not `Shift.shift_type`), so they are
naturally unaffected by delivery stops. The only explicit guards needed are in routes that
enumerate *shifts* for pickup purposes — add a subquery exclusion for shifts where
`has_delivery_trucks == True` only if that route would incorrectly act on a delivery truck.
In practice: `_run_auto_assignment`, `_get_eligible_reschedule_slots`, `admin_shift_notify_sellers`,
`cron_sms_reminders`, `cron_no_show_emails` all act on `ShiftPickup` records directly, so no
shift-level filter is needed. Review each route during implementation.

### `BuyerOrder` (existing) — add `delivered_at`

```python
delivered_at = db.Column(db.DateTime, nullable=True)
# Set when DeliveryStop is marked completed. Operational milestone only.
# Does not change item.status or payout_sent.
```

### `DeliveryStop` (new)

```
One buyer stop per delivery shift. Analogous to ShiftPickup.

id                  Integer PK
shift_id            FK → Shift (must be shift_type='delivery')
buyer_order_id      FK → BuyerOrder  — UNIQUE globally (one stop per order ever)
truck_number        Integer, default 1
stop_order          Integer, nullable — insertion order for now; nearest-neighbor in Spec #D2
status              String: 'pending' | 'completed' | 'issue'   default: 'pending'
notes               Text, nullable
completed_at        DateTime, nullable
notified_at         DateTime, nullable  — when delivery confirmation email was sent to buyer
capacity_warning    Boolean, default False
created_at          DateTime, default utcnow
created_by_id       FK → User, nullable

Unique constraint: (shift_id, buyer_order_id)

Relationships:
  shift        → Shift (backref: delivery_stops)
  buyer_order  → BuyerOrder (backref: delivery_stop, uselist=False)
  created_by   → User
```

### `DeliveryRun` (new)

```
Run-level execution state. Analogous to ShiftRun.

id              Integer PK
shift_id        FK → Shift, UNIQUE
started_at      DateTime
started_by_id   FK → User
ended_at        DateTime, nullable
status          String: 'in_progress' | 'completed'

Relationships:
  shift       → Shift (backref: delivery_run, uselist=False)
  started_by  → User
```

### Migration

Name: `add_delivery_models`

1. Add `BuyerOrder.delivered_at` (DateTime, nullable)
2. Create `delivery_stop` table
3. Create `delivery_run` table

No `Shift` column changes needed. All steps idempotent (check column/table existence before adding).

---

## Template Changes

### `admin/schedule_week.html` (no changes)

No modifications to the schedule creation form. Shifts are created exactly as today.

### `admin/ops.html` — shift list panel badge logic

In the shift list left panel, each shift row currently shows an amber AM or blue PM slot badge.
Add a teal **"Delivery"** badge that appears *alongside* the slot badge when
`shift.has_delivery_trucks` is `True`. The slot badge stays — it still conveys when the shift
runs. The teal badge just signals there's at least one delivery truck on this shift.

### `admin/ops.html` (modify)

**Right sidebar — add Unassigned Deliveries section below Unassigned Sellers:**

```html
<section class="unassigned-deliveries">
  <h4>Unassigned Deliveries</h4>
  <!-- fetched via GET /admin/ops/delivery-queue on page load -->
  <div id="delivery-queue">...</div>
</section>
```

Loaded via `fetch` on page load (same pattern as any ops partial). Each card:

```
[thumbnail]  Item Title  #42
             123 Main St · Chapel Hill
             1.5u · 3 days ago
```

Click to expand inline assign form: delivery shift selector + truck selector + "Add to Route"
button. On success, JS reloads the page to `?shift_id=<selected_shift_id>`.

**Main area — conditional on shift type:**

`admin_ops` route passes `shift.shift_type` to the template. The truck card render block is
wrapped in `{% if shift.shift_type == 'delivery' %}` / `{% else %}` branches:

- Pickup branch: existing truck card template (unchanged)
- Delivery branch: same truck card chrome (header, capacity bar, "Add Truck" button), but stop
  list rows show item thumbnail, item title, buyer address, unit size badge. No storage chip.
  No "Notify Sellers" top-bar button; instead: no bulk notify (per-stop only from detail drawer).

**Top bar — delivery shift selected:**
- "Add Truck" → same behavior, same route
- "Order Route" button hidden (Spec #D2)
- "Notify Sellers" button hidden
- "Refresh" button unchanged

### `admin/ops_truck_detail.html` (modify)

Add conditional branch: `{% if shift.shift_type == 'delivery' %}` renders delivery stop rows
(thumbnail, item title, address, status circle, "Notify" button, "Remove" button pre-run).
Pickup branch is untouched.

### `templates/crew/delivery.html` (new)

Extends `layout.html`. Phone-optimized. See UX Flow section above for structure. Closely mirrors
`crew/shift.html` — same header card pattern, same stop card pattern, same Start/End button
placement, same auto-refresh via partial fetch.

Key differences from `crew/shift.html`:
- No "Navigate →" address tap-to-map button... actually yes, include it. Buyer address is a real
  delivery address — driver needs navigation. Tap buyer address line → opens maps URL.
- No access type badge (elevator/stairs — not relevant for delivery)
- No seller phone number
- Stop card shows item thumbnail instead of seller info
- "Mark Delivered" instead of "Mark Picked Up"
- No intake / placement flow after End Run (items are leaving the warehouse, not arriving)

### `templates/crew/delivery_stops_partial.html` (new)

No layout. Stop list only. Used by 30s auto-refresh fetch. Same pattern as
`crew/stops_partial.html`.

---

## Business Logic

**Mixed truck guard (server-side):**

In `admin_delivery_add_stop`:
```python
existing_pickups = ShiftPickup.query.filter_by(
    shift_id=shift_id, truck_number=truck_number
).count()
if existing_pickups > 0:
    return jsonify(error="This truck already has pickup stops. "
                         "A truck can only be used for pickup or delivery, not both."), 409
```

Symmetric guard in `admin_shift_assign_seller` (existing pickup add route):
```python
existing_deliveries = DeliveryStop.query.filter_by(
    shift_id=shift_id, truck_number=truck_number
).count()
if existing_deliveries > 0:
    return jsonify(error="This truck already has delivery stops."), 409
```

**`stop_order` on insertion:**
No nearest-neighbor for now. `stop_order` is set to `max(stop_order) + 1` for that shift on
each add. Gaps are fine — ordering is visual only. Spec #D2 will overwrite these with optimized
values.

**Capacity for delivery:**
Same `_get_effective_capacity()` logic. Item unit size: `item.unit_size` if set, else
`item.category.default_unit_size`, else `1.0`. `capacity_warning=True` when truck total exceeds
effective cap. Soft cap — no hard block.

**`BuyerOrder` unassigned delivery queue filter:**
```python
BuyerOrder.query
  .join(InventoryItem)
  .filter(
    InventoryItem.status == 'sold',
    ~BuyerOrder.delivery_stop.has(),   # no DeliveryStop exists
    BuyerOrder.delivered_at == None
  )
  .order_by(BuyerOrder.created_at.asc())
```

**Crew dashboard delivery link:**

In `crew_dashboard()`, the query building `my_shifts` already pulls from `ShiftAssignment`.
Delivery shifts will appear naturally. Template renders `{% if shift.shift_type == 'delivery' %}`
to link to `/crew/delivery/<shift.id>` instead of `/crew/shift/<shift.id>`, and shows the teal
"Delivery" badge.

**Mark delivered:**
- Sets `DeliveryStop.status = 'completed'`, `DeliveryStop.completed_at = _now_eastern()`
- Sets `BuyerOrder.delivered_at = _now_eastern()`
- Both in the same `db.session.commit()`
- `delivered_at` is an operational milestone — does NOT change `item.status` (already `'sold'`)
  or `item.payout_sent` (admin controls that via `/admin/payouts`)

**Delivery scheduled email (notify buyer):**
- Sent via `send_email()` + `wrap_email_template()`
- Subject: "Your Campus Swap delivery is scheduled"
- Body: item title, thumbnail, delivery address, delivery date (from shift's date), note that
  they'll receive a heads-up on the day
- `DeliveryStop.notified_at` set. Re-send allowed (admin can correct mistakes).

**Auth guards:**
- All `/crew/delivery/*` routes: `login_required` + `is_worker or is_admin`
- Worker must have a `ShiftAssignment` on the shift to call start/stop/end routes (same as
  pickup shift guard)
- `is_admin` bypasses the assignment check (admin can operate in an emergency)

---

## Pickup Flow Regression Notes

Because `shift_type` is not a stored column, existing pickup routes are naturally safe — they
operate on `ShiftPickup` records, which are only created by pickup-specific routes. A delivery
truck simply has no `ShiftPickup`s, so pickup routes that enumerate stops will find nothing.

The only routes that need an explicit guard are the ones where passing a delivery-truck number to
a pickup route could cause a misleading success (e.g. "assigned" with no effect):

- `admin_shift_assign_seller` — add the mixed-truck guard (no `DeliveryStop` on target truck).
  Already adding this guard for the opposite direction. Symmetric.
- `admin_shift_order_stops` — operates on `ShiftPickup.stop_order` only; naturally a no-op on
  delivery trucks. No guard needed, but add a flash if no `ShiftPickup`s found.
- `crew_shift_start`, `crew_shift_stop_update`, `crew_shift_end` — operate on `ShiftPickup`;
  naturally safe. No guard needed.
- `cron_sms_reminders`, `cron_no_show_emails` — query `ShiftPickup` directly; naturally safe.
- `_get_eligible_reschedule_slots` — queries `ShiftPickup`; naturally safe.

**Tutorial sandbox:** The tutorial's `seed_tutorial_fixtures()` only creates `ShiftPickup`
records, so delivery trucks never appear in the tutorial context. No explicit guard needed.

---

## Constraints

- Do NOT modify the Stripe webhook, `BuyerOrder` creation, or any checkout routes.
- Do NOT touch payout reconciliation or `/admin/payouts`. `delivered_at` is informational only.
- No `Order Route` feature in this spec. That's Spec #D2.
- No buyer-facing SMS or post-delivery email in this spec. That's Spec #D3.
- Day/time helpers: use `_now_eastern()` for all new timestamps. Store naive (no tzinfo),
  consistent with existing `ShiftRun` / `RescheduleToken` datetime pattern.
- Migration must be idempotent.
- Tutorial flow is pickup-only. No explicit guard needed — tutorial fixtures only create
  `ShiftPickup` records, so delivery trucks are never present in the sandbox.
