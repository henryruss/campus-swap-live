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
| **Quick Capture** | A field photo taken by a mover of a found/donated item with no existing listing. Creates an `InventoryItem` with `is_quick_capture=True`, `status='pending_valuation'`. Category is collected at capture time. Items are eligible for AI autofill (`ai_generated_at IS NULL`) and surface in the AI review queue after the next generation run. They also remain in the dedicated admin queue at `/admin/items/needs_info` (`admin_needs_info_queue`), which lists QC items in `pending_valuation`/`needs_info`. |
| **Internal account** | The seeded "Campus Swap" user (`is_internal_account=True`) that owns donated or unclaimed items captured without an associated seller. `seller_id` on `InventoryItem` is never nullable — this account is the fallback. |
| **Campus Director (CD)** | A privileged seller account (`is_campus_director=True`) that can access the admin ops panel via a role switcher in the nav. CDs are not `is_admin` or `is_super_admin`. They see a subset of admin functionality (ops, crew, schedule) intended for on-the-ground coordinators at a campus location. |
| **CD view** | Session state (`session['cd_view']`) set to `'seller'` by `/switch-role/seller` or `'admin'` by `/switch-role/admin`. Controls which context a campus director sees. When set to `'seller'`, the CD sees the normal seller dashboard. |
| **TutorialSession** | DB model tracking a campus director's tutorial progress (`step` 0–7, `started_at`, `completed_at`, `tutorial_week_id`, `is_retaking`). Step advances via POST; seed fixtures are re-applied on each restart. |

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

**Campus Director role.** Campus directors (`is_campus_director=True`) are neither workers nor full admins. They can access the ops panel (Ops, Crew, Schedule tabs) but not super-admin-only pages (Settings, User Management, Exports). The role switcher pill in the header nav lets them toggle between their seller dashboard and admin ops context without logging out. Auth guard for CD-accessible routes is `_has_ops_access()` (not `is_admin`).

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

**AI autofill pipeline:**
Quick-capture items are eligible for AI autofill (`ai_generated_at IS NULL`). Items are enqueued on a background worker queue (`_ai_queue`, drained by a daemon thread `_ai_queue_worker`); each item retries up to `_AI_MAX_RETRIES = 3` times (tracked by `InventoryItem.ai_retry_count`) before being hard-stopped. After generation, items with AI data appear in the AI review queue (`/admin/ai/review`) where admin can approve or discard. The dedicated `/admin/items/needs_info` queue (`admin_needs_info_queue`) still lists QC items awaiting completion. Items are excluded from the standard approval queue and approval digest email.

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

**A truck is pickup OR delivery, never both.** Delivery trucks (Spec D1) carry buyer
`DeliveryStop`s; pickup trucks carry seller `ShiftPickup`s. This is enforced on both assign
paths: `admin_routes_assign_seller` returns 422 (and creates nothing) if you try to assign a
seller pickup to a truck that already has `DeliveryStop` records, and the delivery add-stop
path blocks the reverse. (Before this guard the ops assign path silently created an orphan
`ShiftPickup` that never rendered and dropped the seller from the unassigned list.)

**Ops-page sidebar (2026-06-22).** The ops page (`/admin/crew/shift/<id>/ops`) shows the
buyer name on delivery-queue cards and renders each unassigned seller's pickup week as a
compact date range (e.g. "Jun 22–28") via the `pickup_week_range` Jinja filter
(`PICKUP_WEEK_DATE_RANGES`), instead of a bare week key. When a shift has delivery stops, a
"Notify Buyers" button sits next to "Notify Sellers" (bulk notify route above).

**Delivery origin / warehouse coordinates.** The delivery distance/zone math originates from
the warehouse coordinates, now editable as `warehouse_lat` / `warehouse_lng` AppSettings in
Settings → Route & capacity (`save_route_settings`). When blank they fall back to module
constants `WAREHOUSE_DEFAULT_LAT` / `WAREHOUSE_DEFAULT_LNG` (515 S Greensboro St, Carrboro NC),
so checkout fails open rather than hard-erroring.

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

## Seller-Facing Features (built)

The ops system connects back to the seller experience in three ways (all shipped — specs #7, #8, #9):

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
| — | `feature_quick_capture.md` | ✅ Done (in production ~2026-05-20) | Driver field photo capture, internal Campus Swap account, admin needs_info queue |
| — | `feature_approval_queue_modal.md` | ✅ Done (built 2026-05-21) | Single-page modal flow for approval queue — fetch partial detail + fetch POST actions, no new tabs |
| — | `feature_cd_tutorial.md` | ✅ Done (built 2026-05-21) | Campus Director onboarding tutorial — 10-step interactive walkthrough with sandbox data isolation, role switcher, auth guard fixes |
| — | `feature_storage_audit_and_placement.md` | ✅ Done (built 2026-05-28) | Admin storage audit tool (`/admin/storage/audit`) to view/correct item locations; driver placement flow at End Shift (zone diagram modal, "Not picked up"); storage unit management overhaul (inline edit, delete, bulk xlsx import with OOM-safe streaming); Postgres startup fix (`db.create_all()` unconditional) |
| — | `feature_ai_autofill.md` | ✅ Done (built 2026-05-28) | Claude vision API generates title/description/price/retail for items; staged review queue; ai_approved gates shop visibility; retail price shown to buyers as savings callout |
| — | `feature_warehouse_floor.md` | ✅ Done (built 2026-05-28) | Replaces storage audit tool; unit card grid with capacity batteries; Log Item modal (photo→category→location→seller); Needs New Photo + Photo Verification queues; removes QC admin queue |
| — | `feature_required_unit_assignment.md` | ✅ Done (built 2026-05-29) | Visual unit picker modal on ops page; required unit assignment gate before first stop; destination banner on driver shift view; placement prefill |
| — | `feature_warehouse_route_browse.md` | ✅ Done (built 2026-05-29) | Browse by Route tab on warehouse floor; shift chip list; route item results |
| D1 | `feature_delivery_routes.md` | ✅ Done (built 2026-05-29) | Buyer delivery routes — `DeliveryStop`/`DeliveryRun` models, delivery queue (`/admin/ops/delivery-queue`), delivery truck assignment, crew delivery shift view (`/crew/delivery/*`). **Notify Buyers bulk action** (`POST /admin/crew/shift/<id>/notify-buyers`, `_has_ops_access()`) added 2026-06-22 — emails every delivery-route buyer with `notified_at IS NULL`; shares `_send_delivery_scheduled_email(stop)` with the per-stop notify. |
| A | `feature_delivery_fees.md` | ✅ Done (in production 2026-06-14) | Zone-based delivery pricing (20-mile cutoff), 7.25% sales tax on item price, Flexible Delivery via Stripe coupon; `BuyerOrder` gained delivery/tax fields; `checkout_review` route; webhook idempotency + double-sale guard |
| B | `feature_cart_bundle.md` | ✅ Done (in production 2026-06-18) | Cart + Bundle & Save — `Cart`/`CartItem`/`Order` models, multi-item cart (`/cart/*`), bundle free delivery (`item_count >= bundle_min_items`), guest carts via `cart_token`, pending `Order` created before Stripe redirect |
| — | AI autofill background queue | ✅ Done (in production 2026-06-21) | `_ai_queue` worker thread drains autofill jobs; `ai_retry_count` with `_AI_MAX_RETRIES = 3` hard-stop |
| — | Shop + Delivery Ops Pass | ✅ Done (in production 2026-06-22) | Google Places autocomplete + in-range check at checkout; two-radio delivery picker + `_delivery_window()` date ranges; checkout-based cart hold (`Cart.checkout_started_at` / `checkout_hold_minutes`); Notify Buyers bulk route; mixed-truck guard on the ops assign path; buyer name + `pickup_week_range` chips on the ops sidebar; `warehouse_lat`/`warehouse_lng` configurable in Settings → Route & capacity; idempotent `wrap_email_template` + PNG logo + photo thumbnails in order emails |
| — | `feature_warehouse_rephotography.md` | ✅ Done (built 2026-07-08, migration `4091b1a0e9c8`) | Search-first guided three-shot (front/side/back) capture flow for re-photographing warehouse items; per-photo instant compressed upload, "Re-shot today" badge, add-missing-item path. Routes under `/admin/warehouse/rephoto/*` (`_has_ops_access()`); `ItemPhoto` gained `captured_at`/`sort_order`/`view` |
| — | `feature_route_photo_report.md` | ✅ Done (built 2026-07-16) | Read-only printable photo audit of a route (`GET /admin/warehouse/routes/<shift_id>/photo-report`) and of every route on one page (`GET /admin/warehouse/routes/photo-report`), both `_has_warehouse_access()`. All-routes view is a dense packed 7-wide grid per route; cards show the seller's ORIGINAL (non-AI) photo via `InventoryItem.original_photo_url`. No model changes |
| — | Item Dimensions | ✅ Done (built 2026-07-17, migration `74fd31ce2f07`) | Optional L/W/H inches on `InventoryItem` (`length_in`/`width_in`/`height_in`, `Numeric(5,1)` nullable); add/edit item forms + buyer product page; `_parse_dimension` helper (blank/invalid → NULL, never blocks save) |
| — | Rephoto Matching | ✅ Done (built 2026-07-17, migration `454f7f6bc046`) | "Matching game" at `/admin/warehouse/rephoto/report` (`_has_ops_access()`): reassign Campus-Swap-owned rephotographed items to real sellers via a modal (title/seller/original-to-replace/dimensions); hides the seller's original listing (`ai_approved=False`) and links it (`InventoryItem.replaced_by_item_id`). Deferred: AI re-run + seller-dashboard grouping |

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
| `app.py` | All routes (~17,000 lines, ~263 routes) |
| `models.py` | All SQLAlchemy models |
| `static/style.css` | Full design system (CSS variables, component classes) |
| `templates/layout.html` | Base template — nav, footer, flash, analytics |
| `CODEBASE.md` | Route map, model schemas, template list — read before every session |
| `OPS_SYSTEM.md` | This file — ops platform master reference |
| `HANDOFF.md` | Current build state — what's done, what changed |
| `SPEC_CHECKLIST.md` | Human sign-off gates between specs |
| `DECISIONS.md` | Design decision log with reasoning |
