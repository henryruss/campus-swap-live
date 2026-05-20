# Campus Swap — Ops System Master Reference

## What This Is

An internal operations platform built into the existing Campus Swap Flask app
(`usecampusswap.com`) that manages a seasonal workforce across the UNC Chapel
Hill move-out season (~3 weeks, late April through mid-May). Workers apply,
submit availability, get scheduled by admins (assisted by an optimizer), execute
shifts in the field, and feed data back into the existing seller payout system.

This is not a separate app. All ops routes live inside the existing Flask
codebase at `/crew/*` (worker-facing) and `/admin/crew/*` (admin-facing).

---

## Glossary

| Term | Definition |
|------|------------|
| **Shift** | A single AM or PM work block on a specific date |
| **Slot** | One AM or PM half of a given day (e.g. "Tuesday AM") |
| **Truck** | One vehicle + its 2-mover crew operating during a shift |
| **Route** | The ordered list of pickup addresses assigned to one truck for one shift |
| **Worker** | An approved, hired Campus Swap seasonal employee |
| **Mover** | Worker role — rides in truck, executes pickups at seller addresses (`role_on_shift = 'driver'` in DB) |
| **Organizer** | Worker role — stays at storage unit, receives and tags incoming items (`role_on_shift = 'organizer'` in DB) |
| **Availability** | A worker's self-reported AM/PM availability per day of the week |
| **Blackout** | A slot a worker has marked as unavailable — strictly never scheduled |
| **Pickup** | A single seller address visit to collect consigned items |
| **ShiftPickup** | DB record linking a seller to a specific shift + truck (one per seller per shift, globally unique) |
| **ShiftRun** | DB record tracking shift execution state — created when mover taps Start Shift |
| **Intake** | The organizer-side process of receiving, logging, and tagging items at the storage unit |
| **Intake record** | An `IntakeRecord` row — append-only log of one organizer receiving one item. Re-submissions add a new row; earlier rows form the audit trail. |
| **StorageLocation** | A physical storage unit or warehouse where items are held after pickup. Managed by super admin at `/admin/storage`. |
| **Planned unit** | The `ShiftPickup.storage_location_id` (or truck entry in `Shift.truck_unit_plan`) — the destination a truck is expected to deliver to, set by admin before the shift. |
| **Actual unit** | The `InventoryItem.storage_location_id` — where an item physically ended up, set by the organizer during intake. |
| **Overflow truck** | A flex truck slot held in reserve to absorb rescheduled pickups |
| **Quick Capture** | A field photo taken by a mover of a found/donated item with no existing listing. Creates an `InventoryItem` with `is_quick_capture=True`, `status='pending_valuation'`. Admin completes the listing (title, price, category) afterward via the Quick Captures queue at `/admin/items/needs_info`. |
| **Internal account** | The seeded "Campus Swap" user (`is_internal_account=True`) that owns donated or unclaimed items captured without an associated seller. `seller_id` on `InventoryItem` is never nullable — this account is the fallback. |

---

## Staffing Model

| Unit | Composition |
|------|-------------|
| 1 truck | 2 movers |
| 1–2 trucks | 2 organizers (stagger model: one truck picks up while other drops off) |
| 3–4 trucks | 4 organizers |
| Max per shift | 4 trucks → 8 movers + 4 organizers = 12 workers |
| Min per shift | 1 truck → 2 movers + 2 organizers = 4 workers |

Admin sets trucks-per-shift when building the weekly schedule. Organizer count
uses the **stagger formula**: `ceil(trucks / 2) × 2`. Two trucks can share two
organizers because they stagger (one truck is picking up while the other drops
off). A third truck requires a second organizer pair.

**Role assignment is per-shift, not per-worker profile.** All workers are treated
as capable of both roles. The optimizer pools all workers for both mover and
organizer slots. A worker can be a mover on Tuesday and an organizer on Thursday.
The `ShiftAssignment.role_on_shift` field is the only authoritative gating —
`User.worker_role` is not used for access control.

**Organizer completion is independent of ShiftRun.** Movers end their shift by
tapping End Shift, which closes `ShiftRun` and sets their `ShiftAssignment.completed_at`.
Organizers end their work by tapping End Intake, which sets only their
`ShiftAssignment.completed_at` — the ShiftRun is not involved. This means an
organizer can close out before or after the trucks are done.

AppSetting keys (movers):
- `drivers_per_truck` = `'2'`
- `max_trucks_per_shift` = `'4'`
- `shifts_required` = `'10'` (minimum shifts for full season payout)

Note: `organizers_per_truck` AppSetting exists but is no longer used for capacity calculation (superseded by stagger formula).

---

## Pickup Types

Three scenarios that affect how routes are structured:

| Type | Description | Routing complexity |
|------|-------------|-------------------|
| **Bulk** | Entire building moving out (sorority, apartment complex) | Low — one address, whole shift |
| **Scattered** | Individual house-to-house pickups | High — multiple addresses, needs sequencing |
| **Mixed** | Combination in one shift | Medium |

Route planning (spec #6) handles sequencing. Earlier specs treat all pickups
as an unordered list assigned to a truck.

---

## Quick Capture Flow (feature_quick_capture.md)

Movers can photograph found, donated, or spot-consigned items in the field and add them to the Campus Swap inventory in under 10 seconds.

**Entry points:**
- `/crew` dashboard — Quick Capture button always visible. No shift context. Seller defaults to Campus Swap internal account.
- `/crew/shift/<id>` shift view — Quick Capture button in header. Seller auto-populates from the current active stop; dropdown shows all sellers on the truck's route.

**Capture flow:**
1. Mover taps Quick Capture → modal opens with rear camera activating.
2. Takes photo, optionally adds a note (condition, estimated price, etc.).
3. Selects which seller the item belongs to (or leaves as Campus Swap).
4. Taps Save → item created immediately; photo appears on the seller's stop card.

**Item created with:**
- `is_quick_capture = True`, `status = 'pending_valuation'`
- `picked_up_at` set to now (item is physically in the truck)
- `quick_capture_shift_id` = current shift (or NULL if from dashboard)
- `captured_by_id` = the mover's user ID
- `long_description` = mover's note (if provided)
- Seller: selected seller or internal Campus Swap account

**Admin completion queue (`/admin/items/needs_info`):**
Quick-capture items land in a dedicated queue. Admin fills in title, category, price, quality, then either approves (one-click, no price required) or edits via the standard edit_item flow. Items are excluded from the standard approval queue and approval digest email.

**Crew delete:** The capturing worker can hard-delete their own captures (photo + DB record) via the `×` button on the stop card photo strip, as long as the item is still in `pending_valuation` or `needs_info`. Hard delete only — no soft-reject path.

**Admin delete:** Admins can hard-delete any QC item from the quick captures queue.

---

## Availability Model

Workers submit a 7×2 grid of AM/PM availability for each day of the week.
Stored as 14 boolean columns in `WorkerAvailability`:

```
mon_am, mon_pm, tue_am, tue_pm, wed_am, wed_pm, thu_am, thu_pm,
fri_am, fri_pm, sat_am, sat_pm, sun_am, sun_pm
```

`True` = available. `False` = blacked out. Blackouts are strictly honored —
the optimizer never assigns a worker to a blacked-out slot.

Availability is submitted at application (`week_start = NULL`) and updated
weekly thereafter (`week_start = Monday date of that work week`). Deadline
for weekly updates is Tuesday at midnight. Optimizer runs after deadline.

---

## Worker Roles & Status

**Roles at assignment time:** `driver` | `organizer` (stored in `ShiftAssignment.role_on_shift`)
**Profile-level role:** `User.worker_role` exists but is not used for access control. All workers are approved as 'both'.

**Status lifecycle:**
```
None (never applied)
  → pending  (application submitted)
  → approved (admin approves — worker gets /crew access)
  → rejected (admin rejects)
```

**User model flags:**
- `is_worker` (Boolean) — True once approved
- `worker_status` (String) — see above
- `worker_role` (String) — legacy field, always 'both' for new approvals; not used for gating

---

## Storage & Intake System (Spec #4)

### Storage Location Management
Storage locations (units, warehouses) are created and managed by super admins at
`/admin/storage`. Each location has a name, address, optional notes, and active/full flags.

### Truck Unit Plan
Before a shift runs, admin assigns a destination storage unit to each truck via
the ops page (`/admin/crew/shift/<id>/ops`). The destination unit dropdown
auto-saves via fetch (no page reload). The mapping is stored as JSON on
`Shift.truck_unit_plan` — this allows planning before any `ShiftPickup` records exist.
When a new seller is added to a shift, their `ShiftPickup.storage_location_id` is
pre-populated from the truck's unit plan.

### Organizer Intake Flow
1. Organizer opens `/crew/intake/<shift_id>` — sees all trucks with their pending sellers
2. For each item: search by item ID or seller name, open the bottom-sheet modal
3. Confirm storage row, optionally flag as damaged/missing
4. Submit → creates `IntakeRecord` (append-only), updates `InventoryItem` storage fields
5. When `received_count >= total_items`, End Intake becomes available
6. End Intake sets `ShiftAssignment.completed_at` for the organizer

### Intake Flags
Organizers can flag items as `damaged`, `missing`, or `unknown` (unidentified item).
- Damaged/missing: linked to a known `InventoryItem`; storage unit is optional (missing items have no location)
- Unknown: no item_id; logged for admin to identify
- Admin reviews all unresolved flags at `/admin/intake/flagged`
- Bulk action: "Remove from Marketplace" sets `status='rejected'` and auto-resolves all flags with an audit note

---

## Seller-Facing Features (planned)

The ops system connects back to the seller experience in three ways:

1. **Progress tracker** — visual pipeline on seller dashboard showing:
   `Pickup Scheduled → Driver En Route → Item Received → Listed → Sold & Paid`
   Uses existing model fields (`picked_up_at`, `arrived_at_store_at`, `is_sold`,
   `payout_sent`) plus new route-state fields added in spec #3.
   `storage_location_id` and `storage_row` from intake (spec #4) can populate
   an "Item at Storage" stage.

2. **Self-serve rescheduling** — seller receives a message at start of week
   ("your pickup is Tuesday PM — can't make it? Reschedule here"), clicks link,
   picks new slot, automatically added to that day's route. Overflow truck
   slots absorb rescheduled pickups.

3. **SMS notifications** — automated texts via Twilio at:
   - Start of week: pickup scheduled notification + reschedule link
   - 24hrs before pickup: reminder
   - Shift start: "we're starting today's route"
   - ~1hr out: "driver is on the way"

---

## Feature Roadmap

| # | Spec File | Status | Description |
|---|-----------|--------|-------------|
| 1 | `feature_worker_accounts.md` | ✅ Done (signed off 2026-04-06) | Worker role, .edu gating, application, availability grid |
| 2 | `feature_shift_scheduling.md` | ✅ Done (signed off 2026-04-06) | Admin shift creation, greedy optimizer, schedule publishing, worker calendar view |
| 3 | `feature_driver_shift_view.md` | ✅ Done (signed off 2026-04-07) | Phone-optimized mover shift view, ops page, partner preferences, shift history |
| 4 | `feature_organizer_intake.md` | ✅ Done (signed off 2026-04-08) | Organizer intake page, storage locations, IntakeRecord/IntakeFlag, damaged/missing queue |
| 5 | `feature_payout_reconciliation.md` | ✅ Done (signed off 2026-04-14) | Close loop between intake and seller payout workflow |
| 6 | `feature_route_planning.md` | ✅ Done (signed off 2026-04-14) | Admin route-building tools, geographic clustering, nearest-neighbor ordering |
| 7 | `feature_seller_progress_tracker.md` | ✅ Done (signed off 2026-04-14) | Visual status pipeline on seller dashboard |
| 8 | `feature_seller_rescheduling.md` | ✅ Done (signed off 2026-04-14) | Self-serve reschedule flow, overflow truck slots |
| 9 | `feature_sms_notifications.md` | ✅ Done (in production, 42/42 tests) | Twilio integration, automated texts at route milestones |
| — | `feature_admin_redesign.md` | ✅ Done (in production) | Admin UI overhaul — ops tab, items tab, sellers tab, settings tab |
| — | `feature_crew_hq.md` | ✅ Done (in production ~2026-05-04) | Crew HQ — worker cards, shift board, quick-add/remove |
| — | `feature_admin_availability_override.md` | ✅ Done (in production ~2026-05-04) | Admin can override worker availability from Crew HQ |
| — | `feature_shift_history_items.md` | ✅ Done (in production ~2026-05-05) | Completed shift item history view for movers |
| — | `feature_ops_admin_fixes.md` | ✅ Done (in production ~2026-05-03) | Bulk week reassign, unassigned panel filter fix, assign-unit CSS fix |
| — | `feature_ops_fixes_round2.md` | ✅ Done (in production ~2026-05-03) | Eligibility filter expansion, week filter removal, auto-assign fetch, remove truck |
| — | `fix_crew_dashboard_and_soft_stops.md` | ✅ Done (in production ~2026-05-05) | Crew dashboard no publish-gate; soft stop actions until confirmed End Shift |
| — | `fix_remove_ai_pricing.md` | ✅ Done (in production ~2026-05-01) | Removed broken ItemAiResult model (was causing 500 errors) |

**Dependency order matters.** Do not begin a spec until all specs it depends on
are built and signed off in `SPEC_CHECKLIST.md`.

**Dependencies:**
- Spec 2 requires Spec 1 (workers must exist to schedule)
- Spec 3 requires Spec 2 (shifts must exist to view)
- Spec 4 requires Spec 3 (drivers must be logging progress for intake to connect)
- Spec 5 requires Spec 4 (items must be intake'd before payout reconciliation)
- Spec 6 requires Spec 2 (shifts must exist to build routes)
- Spec 7 requires Spec 4 (intake data populates the progress tracker)
- Spec 8 requires Spec 6 (routes must exist to reschedule into)
- Spec 9 requires Spec 6 + 8 (route state + reschedule links power SMS content)

---

## Tech Constraints (Never Violate)

- Server-rendered only. No React. Vanilla JS for interactivity.
- All new templates extend `layout.html`.
- Never hardcode colors — use CSS variables from `static/style.css`.
- All forms include `{{ csrf_token() }}`.
- Database changes always get a Flask-Migrate migration.
- Stripe webhook is the only source of truth for payment state.
- Admin roles: `is_admin` = panel access, `is_super_admin` = full access.
- Photo serving: always `url_for('uploaded_file', filename=...)`, never static path.
- Day/time logic uses Eastern time (`_now_eastern()` / `_today_eastern()`), not UTC. Timestamps stored in UTC.

---

## Key Files

| File | Purpose |
|------|---------|
| `app.py` | All routes (~6,300 lines) |
| `models.py` | All SQLAlchemy models |
| `static/style.css` | Full design system (CSS variables, component classes) |
| `templates/layout.html` | Base template — nav, footer, flash, analytics |
| `CODEBASE.md` | Route map, model schemas, template list — read before every session |
| `OPS_SYSTEM.md` | This file — ops platform master reference |
| `HANDOFF.md` | Current build state — what's done, what changed |
| `SPEC_CHECKLIST.md` | Human sign-off gates between specs |
| `DECISIONS.md` | Design decision log with reasoning |
