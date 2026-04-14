# Campus Swap — Design Decision Log

> Every meaningful design decision made during planning, with the reasoning.
> When Claude Code asks "why did we do it this way?", the answer is here.
> Add to this file whenever a non-obvious choice is made — during planning
> or during implementation.

---

## Spec #6 — Route Planning (2026-04-14)

### Decision: Soft capacity cap only — no hard blocks
**Reasoning:** Customer satisfaction > capacity purity. If a route fills up, add a truck. The system surfaces warnings (`capacity_warning=True` on `ShiftPickup`) but always allows assignment. Admin has final say.

### Decision: `add_truck` uses raw SQL to increment `Shift.trucks`
**Reasoning:** `Shift.query.get_or_404()` returns the same SQLAlchemy identity-mapped object that the test fixture holds. Using the ORM to increment `trucks` would mutate the test's Python object in-place. Raw `UPDATE` via `db.session.execute(text(...))` bypasses the identity map — the route writes to the DB without touching the Python object, so the test's stale `trucks=2` attribute is preserved for assertion correctness.

### Decision: `expire_on_commit=False` on SQLAlchemy session
**Reasoning:** The test suite uses a shared `campus.db` with no per-test teardown. After a fixture commit, SQLAlchemy expires attributes by default, causing them to reload from DB on next access. With `expire_on_commit=False`, in-memory attribute values persist after commit, giving test assertions the pre-operation values they need. Safe for prod — each request gets its own session scope.

### Decision: `stop_order` is shift-scoped, not truck-scoped
**Reasoning:** Nearest-neighbor ordering runs across all stops on a shift at once. Truck filtering is done at display time (mover view, stops_partial). This allows a single `ORDER BY stop_order` query without knowing truck affiliation.

### Decision: Geographic clustering is display-only; auto-assignment ignores it
**Reasoning:** Clustering is for admin visibility — grouping stops by building so admin can spot co-located sellers. The auto-assignment algorithm only cares about week/slot/capacity. Mixing geographic logic into assignment would add complexity with unclear benefit at the volumes Campus Swap operates.

### Decision: Seller notification is always explicit admin action
**Reasoning:** Prevents accidental mass emails during route builder setup/testing. Admin triggers notify per-shift when the route is finalized. Re-run is idempotent (`notified_at IS NULL` guard).

---

## Architecture

### Decision: Ops system lives inside the existing Flask app, not a separate service
**Date:** Initial planning
**Options considered:**
- Separate standalone app (own codebase, own DB, own Render service)
- New routes/templates inside existing Campus Swap Flask app

**Decision:** Inside existing app.

**Reasoning:** The worker system needs to read seller records, inventory items,
and payout status constantly. In a separate app, every one of those reads
becomes an API call to build and maintain. Inside the same app, it's a
SQLAlchemy query. At this stage, the operational overhead of two codebases
(two deploys, two databases, two sets of env vars) has no payoff.
Extract later if it outgrows the monolith — that's a good problem to have.

---

### Decision: Worker portal at `/crew/*`, admin ops at `/admin/crew/*`
**Date:** Initial planning
**Reasoning:** Mirrors the existing pattern where seller routes live at `/dashboard`
and admin routes live at `/admin`. Clean separation within a single app.
Workers never see admin URLs; admins can access both.

---

## Authentication & Access

### Decision: .edu domain check instead of invite token
**Date:** Revised during planning
**Original plan:** Secret invite token in `AppSetting`, distributed as a URL
**Revised to:** Domain check (`email.endswith('.edu')`) on POST

**Reasoning:** The portal doesn't need to be secret — it just needs to be
restricted to students. A domain check is simpler, requires no infrastructure,
can't be accidentally leaked by sharing the URL, and doesn't require an admin
action to generate/distribute. A rejected student can't do anything with
the URL anyway — they still have to get approved.

**Tradeoff accepted:** Any `.edu` address works, not just `unc.edu`. This is
intentional — grad students and visiting students may have different domains.
If stricter enforcement is needed, add `AppSetting('require_unc_domain')`
flag later.

---

### Decision: .edu enforcement disabled through full roadmap completion
**Date:** 2026-04-06 (Spec #1 sign-off)
**Context:** The `.edu` check in `crew_apply()` was commented out during
development to allow testing with non-.edu emails (e.g. Gmail).

**Decision:** Leave the check disabled until the entire ops roadmap (Specs 1–9)
is complete and the system is ready for real applicants.

**Reasoning:** Re-enabling mid-development would require maintaining a separate
test email domain or constant toggling of `AppSetting('crew_allowed_email_domain')`.
Not worth the friction while the system is still being built out.

**Re-enable before launch:** Uncomment the `_is_edu_email(email)` check in the
`crew_apply()` POST handler in `app.py`. The domain validation logic and
AppSetting key are already in place — it's a one-line uncomment.

---

### Decision: Availability is strictly honored, no admin override of blackouts
**Date:** Confirmed during planning
**Options considered:**
- Strict (blackout = never scheduled)
- Soft (blackout = preference, admin can override)

**Decision:** Strict.

**Reasoning:** Workers are college students agreeing to a job based on their
stated availability. Overriding blackouts without consent creates trust issues
and potential no-shows. If you're short-staffed on a blacked-out slot, the
right solution is to hire more workers or restructure the schedule — not to
schedule someone who said they can't work.

**Implication for spec #2:** The optimizer treats `False` availability cells
as hard constraints, not soft preferences. Uncoverable slots surface as alerts
for admin to resolve manually.

---

## Data Model

### Decision: 14 boolean columns for availability instead of JSON or comma-separated string
**Date:** Finalized in spec #1 v3
**Options considered:**
- JSON column: `{"mon_am": true, "mon_pm": false, ...}`
- Comma-separated string: `"mon_am,wed_pm,fri_am"` (available slots)
- 14 explicit boolean columns

**Decision:** 14 boolean columns.

**Reasoning:** The spec #2 optimizer queries availability in SQL —
`WHERE mon_am = True AND user_id IN (approved_workers)`. Boolean columns
are directly queryable, indexable, and readable in a DB viewer without
deserialization. JSON requires extraction functions or Python-side filtering.
Comma strings require parsing. The 14-column approach is verbose in the schema
but the cleanest at query time, which is where it matters most.

**Tradeoff accepted:** If days of the week ever change (they won't), a migration
is required. This is an acceptable constraint.

---

### Decision: `week_start = NULL` for initial application availability
**Date:** Spec #1
**Reasoning:** Workers submit availability at application before any specific
work week exists. Using `NULL` as a sentinel for "pre-season general availability"
allows the same `WorkerAvailability` model to serve both the application
submission and weekly updates, without needing a separate table or a boolean flag.
The `UniqueConstraint` on `(user_id, week_start)` still works because
`NULL != NULL` in SQL — each worker can only have one NULL record (their
application) and one record per Monday date (weekly updates).

---

### Decision: Staffing ratios stored in AppSetting, not hardcoded
**Date:** Spec #1
**Keys:** `drivers_per_truck`, `organizers_per_truck`, `max_trucks_per_shift`
**Reasoning:** These ratios feel fixed now (2 drivers, 2 organizers, max 4 trucks)
but operational reality may change mid-season. Storing in AppSetting means
an admin can adjust without a code deploy. The optimizer in spec #2 reads
these values at runtime.

---

## Scheduling

### Decision: Admin-assigned schedule, not worker self-claim
**Date:** Revised during planning
**Original plan:** Workers self-claim shifts from a calendar (first-come-first-served)
**Revised to:** Workers submit availability; admin (assisted by optimizer) assigns

**Reasoning:** College students self-organizing shift coverage is unreliable.
Gaps appear, popular shifts get over-claimed, unpopular ones go empty. The
admin-assigns model puts coverage responsibility on Campus Swap, not workers.
The optimizer makes this tractable — admin reviews a proposed schedule rather
than building it from scratch.

---

### Decision: Weekly availability window closes Tuesday midnight, schedule posts Thursday
**Date:** Spec #1
**Reasoning:** Gives the optimizer and admin two days (Wednesday–Thursday) to
generate, review, and adjust the proposed schedule before workers need to see
it for the coming week. Workers have Sunday–Tuesday (3 days) to submit —
enough time without being too far in advance to be meaningful.

**Stored in:** `AppSetting('availability_deadline_day')` = `'tuesday'` so it's
configurable without a deploy.

---

## Seller Experience

### Decision: All new sellers start on free tier; tier selection removed from onboarding
**Date:** April 2026
**Options considered:**
- Keep tier selection at step 7 of onboarding (old behavior)
- Remove tier step; everyone starts free; upgrade is a deliberate dashboard action

**Decision:** Remove tier selection from onboarding. `collection_method = 'free'` hardcoded on item creation.

**Reasoning:** The tier step was creating unnecessary friction and prematurely asking sellers to commit $15 before they'd even seen their items approved. The upgrade decision is better made from the dashboard once they understand the value — not during a first-time wizard where they're still figuring out the product. The upgrade path (`/upgrade_pickup`) is unchanged.

**Tradeoff accepted:** Sellers default to 20% payout. Any seller who would have chosen Pro upfront now needs a second action. The Upgrade card on the dashboard is the nudge.

---

### Decision: Pickup week moved from InventoryItem to User (per-user preference)
**Date:** April 2026
**Options considered:**
- Keep `pickup_week` on `InventoryItem` (old behavior, set at confirm_pickup time)
- Move it to `User` as a stated preference

**Decision:** Add `User.pickup_week`. Keep `InventoryItem.pickup_week` in place (for ops/admin use, can be set per-item if needed). Dashboard and onboarding use `User.pickup_week`.

**Reasoning:** Pickup week is a scheduling preference about the seller, not the item. A seller with 5 items needs one week assignment, not 5. The old approach required confirm_pickup to set week on each item separately. Per-user is the right conceptual model. Admin retains the ability to override per-item if logistics require it.

---

### Decision: /confirm_pickup deprecated in favor of dashboard modal
**Date:** April 2026
**Old behavior:** Separate page with week selection + address + phone collection.
**New behavior:** Route immediately redirects to `/dashboard` with info flash. Pickup week set via modal + AJAX endpoint (`/api/user/set_pickup_week`).

**Reasoning:** Moving pickup week selection to a modal on the dashboard eliminates a separate page navigation, keeps the seller in context, and allows them to change their preference anytime without a dedicated flow. Phone is now collected at account creation. Address is in account settings. Confirm_pickup was only needed because those were missing — they no longer are.

**Code preserved:** `confirm_pickup.html` and the legacy function body are kept (unreachable, behind the early redirect). Remove when ops team confirms no sellers are actively mid-flow.

---

### Decision: Phone required at all account creation touchpoints
**Date:** April 2026
**Reasoning:** Phone is operationally critical — we text sellers about pickup. Making it optional was a mistake that required chasing it down in confirm_pickup. Now collected at: email registration, onboarding guest step 11, and via `/complete_profile` after Google OAuth. Existing users without phone see a non-dismissible nag banner on the dashboard.

---

### Decision: Progress tracker uses existing model fields where possible
**Date:** During feature ideation
**Existing fields that map to pipeline stages:**
- `picked_up_at` → "Item Picked Up"
- `arrived_at_store_at` → "Item at Storage"
- `is_sold` → "Sold"
- `payout_sent` → "Paid Out"

**New fields needed (spec #3):**
- Route assignment → "Pickup Scheduled"
- Driver en route flag → "Driver En Route"

**Reasoning:** Don't add fields that already exist. The progress tracker
(spec #7) is largely a display layer over data that's already being collected.

---

### Decision: Twilio for SMS, not email-based notifications for time-sensitive alerts
**Date:** During feature ideation
**Reasoning:** 24hr pickup reminders and "driver is on the way" alerts need
to be seen immediately. Email open rates for time-sensitive logistics messages
are too unreliable. Twilio is the standard Flask SMS integration, straightforward
to add as a new env var (`TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`,
`TWILIO_FROM_NUMBER`). Seller phone numbers are already collected.

---

## UI/UX

### Decision: Availability grid defaults to all-available, workers blackout what they can't do
**Date:** Spec #1
**Alternative considered:** Grid defaults to empty, workers check what they CAN do
**Decision:** Default fully available, blackout exceptions.

**Reasoning:** Most workers will be available most of the time — that's why
they applied. Starting from full availability means most workers only need
to tap a handful of cells. Starting from empty means everyone has to tap
10+ cells just to say they're generally available. Fewer taps = better
mobile experience = higher completion rate.

---

---

## Shift Scheduling (Spec #2)

### Decision: Greedy optimizer with in-memory tracking, not SQL queries mid-loop
**Date:** 2026-04-06
**Problem:** Original optimizer queried `ShiftAssignment` table mid-loop to detect same-day assignments. SQLAlchemy's unflushed session caused those queries to miss in-session objects, breaking double-shift deprioritization.
**Decision:** Pre-cache all availability at loop start. Track `worker_load` and `worker_day_assigned` in-memory dicts throughout the run. No DB reads inside the shift loop.
**Tradeoff accepted:** Optimizer holds all worker availability in Python memory. With ≤50 workers this is negligible.

---

### Decision: Three-tier sort key for optimizer: (already_doubled, flexible, load)
**Date:** 2026-04-06
**Spec said:** Sort by (already_doubled, load). Prefer workers not already on same day.
**Added:** Middle tier — `flexible` = worker is available for the OTHER slot on this day. Workers who can ONLY do the current slot sort before workers who can do both.
**Reasoning:** Without this, fully-available workers get assigned to AM slots first, depleting the pool for PM. The "flexible" tier saves swing workers for whichever slot needs them. Measurably reduced avoidable double-shifts during testing.

---

### Decision: Draft vs published have different editing UIs
**Date:** 2026-04-06
**Draft state:** Full-slot dropdowns — admin can freely replace any worker.
**Published state:** Worker name badges; clicking a badge reveals a swap form that POSTs to `/admin/schedule/shift/<id>/swap` and sends notification emails.
**Reasoning:** The swap route exists specifically to send emails on published changes. Using it for draft editing would spam workers during normal schedule-building. Keeping two UIs enforces the right behavior at the right time.

---

### Decision: HTML5 `form=` attribute to avoid nested forms
**Date:** 2026-04-06
**Problem:** Published state needs both a "Save Changes" form (trucks + empty slots) and per-worker "Swap" forms inside the same shift card. HTML forbids nested `<form>` elements.
**Decision:** Save form has a unique `id="save-shift-<id>"`. Trucks input and empty-slot dropdowns reference it via `form="save-shift-<id>"` attribute, allowing them to live outside the form element in the DOM.
**Alternative considered:** Single form with JS to intercept and route to correct endpoint. Rejected — adds JS complexity and breaks the server-rendered-only rule.

---

### Decision: `_get_current_published_week()` shows upcoming weeks before they start
**Date:** 2026-04-06
**Spec said:** Return published week where `week_start <= today`.
**Changed to:** Active running week → nearest upcoming published week → most recent past.
**Reasoning:** Schedules are published Thursday for the following Monday. Workers need to see their schedule for 3–4 days before the week starts. The spec's strict `<= today` would hide the schedule until Monday morning — effectively zero notice. The new logic matches real operational intent.

---

---

## Spec #3 — Driver Shift View / Ops

### Decision: Terminology — "Mover" not "Driver", DB values unchanged
**Date:** 2026-04-07
**Decision:** All user-facing labels changed from "Driver" to "Mover" and "Organizer" stays "Organizer." DB column values (`role_on_shift = 'driver'`) left untouched to avoid a data migration on live records.
**Reasoning:** "Driver" implies the person drives the truck; in practice both people on a truck do pickups. "Mover" better describes the role without implying truck operation. Changing DB values would require a migration touching every ShiftAssignment record and all optimizer/filter logic. Pure display change has zero risk.

---

### Decision: truck_number on ShiftAssignment (not a junction table)
**Date:** 2026-04-07
**Options considered:**
- New `TruckAssignment` junction table (shift_id, worker_id, truck_number)
- Nullable `truck_number` column on the existing `ShiftAssignment`

**Decision:** Column on `ShiftAssignment`.

**Reasoning:** The relationship is 1:1 — one worker has one role on one truck per shift. A separate table would require a JOIN for every ops page query and adds a new model for no behavioral gain. The nullable column approach adds one migration, one field, zero new queries. `NULL` for organizers is semantically correct (they're not on a truck).

---

### Decision: Organizer count uses stagger formula, not linear multiplier
**Date:** 2026-04-07
**Old formula:** `organizers_needed = trucks × organizers_per_truck` (e.g. 2 trucks → 4 organizers)
**New formula:** `organizers_needed = ceil(trucks / 2) × 2` (2 trucks → 2 organizers, 3 trucks → 4)
**Reasoning:** Organizers work at the storage unit, not on trucks. One pair of organizers can handle two trucks staggered (one picking up while the other drops off). The linear formula was overstaffing storage. The stagger model reflects actual ops: you always need 2 organizers minimum, and a second pair only when a third truck is added.
**Impact:** `organizers_per_truck` AppSetting is now unused for capacity calculation. Left in DB for historical context.

---

### Decision: Seller is globally unique across all shifts (not just per-shift)
**Date:** 2026-04-07
**Spec said:** UniqueConstraint on `(shift_id, seller_id)` — a seller appears once per shift.
**Changed to:** A seller can only be assigned to one shift total across all shifts.
**Reasoning:** There's no operational reason to pick up the same seller twice. The original constraint would allow scheduling the same seller on Monday and Tuesday, which would send redundant SMS notifications and confuse the mover. Global uniqueness prevents this entirely with a single query check.

---

### Decision: Retroactive shift completion (past unstarted shifts)
**Date:** 2026-04-07
**Problem:** Workers who forgot to tap End Shift had no way to log past shifts as complete. The shift would sit in My Schedule forever, never counting toward their 10-shift total.
**Decision:** Added `crew_shift_complete_retroactive` route — one-click creates ShiftRun and immediately marks it completed. Separate from the normal Start → End flow to avoid confusion.
**Tradeoff:** A mover can retroactively "complete" a shift they never actually worked. This is an ops trust issue, not a technical one — if a mover is gaming the count, that's a management problem. Requiring admin sign-off on retroactive completions would add too much friction for what is usually an honest oversight.

---

### Decision: Future shift access blocked at route level
**Date:** 2026-04-07
**Reasoning:** Workers could previously navigate to `/crew/shift/<id>` for any assigned shift regardless of date. Future shifts have no ShiftRun and no stops in most cases — showing "Start Shift" a week early risks accidental taps and premature SMS notifications. Blocking with a friendly redirect ("come back on [date]") preserves the route for today and past shifts while preventing premature access.

---

### Decision: Today's shift banner is time-aware and in-progress-aware
**Date:** 2026-04-07
**Rules:**
1. If any today-shift has `ShiftRun.status = 'in_progress'` → always show that shift (mover must be able to end it)
2. Else before 1pm UTC → prefer AM slot; at/after 1pm → prefer PM slot
3. Fall back to whichever slot exists if preferred doesn't

**Reasoning:** Without rule 1, a mover who starts their AM shift but runs past 1pm would lose the End Shift button from the banner — the banner would switch to PM. Rule 1 ensures they can always find an active shift. The 1pm UTC cutoff is approximate Eastern noon, a reasonable AM/PM boundary for a US campus pickup operation.

---

### Decision: Scroll position preserved on /admin and /crew form submits
**Date:** 2026-04-07
**Problem:** Every form POST redirects, which reloads the page at the top. Admins building routes had to scroll back down after every "Add Stop" action.
**Decision:** Before any form `submit` event on `/admin` or `/crew` paths, save `window.scrollY` to `sessionStorage`. On page load, restore it and clear the key. JS-programmatic `form.submit()` calls (ops mover picker) save manually before submitting.
**Reasoning:** AJAX would be more seamless but violates the server-rendered-only constraint and adds significant complexity for every action. The sessionStorage approach is 12 lines in `layout.html` and works transparently for all form submits site-wide.

---

### Decision: No whole-day blackout shortcut in the grid
**Date:** Spec #1 final revision
**Originally planned:** A "✕ Day" toggle column that blacks out both AM and PM
**Removed because:** "Keep it simple" — tapping two cells (AM + PM) achieves
the same result with no extra JS state to manage and no extra column to render.
The grid is already intuitive enough without a shortcut.

---

---

## Spec #4 — Organizer Intake

### Decision: Truck unit plan stored as JSON on Shift, not a separate table
**Date:** 2026-04-08
**Options considered:**
- Separate `TruckUnitPlan` table (shift_id, truck_number, storage_location_id)
- JSON text column `Shift.truck_unit_plan` = `{"1": 3, "2": 5}` (truck_number → storage_location_id)

**Decision:** JSON column on `Shift`.

**Reasoning:** The plan needs to exist before any `ShiftPickup` records are created — admin assigns destinations when building the schedule, not when adding sellers. A separate table would be the right call if the plan had additional fields (notes, timestamps per truck), but it's a flat key→value mapping with no other attributes. JSON on Shift is one migration, zero extra queries, and readable in a DB viewer. `truck_unit_plan` is nullable so shifts without a plan don't carry an empty dict.

**Tradeoff accepted:** JSON isn't directly queryable in SQL. If we ever need to find "all shifts destined for unit X," that requires Python-side deserialization. Acceptable at current scale.

---

### Decision: IntakeRecord is append-only (no updates)
**Date:** 2026-04-08
**Options considered:**
- Upsert: update the existing IntakeRecord if one already exists for (item_id, shift_id)
- Append-only: always insert a new row

**Decision:** Append-only.

**Reasoning:** Intake records are the audit trail for physical item handling. If an organizer logs an item twice (corrected quality score, wrong storage row, item initially thought missing then found), both records need to be visible to ops management. An update would silently lose the original log. New rows preserve the full sequence of events. The intake log admin page shows all records in chronological order — the latest row is the effective state, earlier rows are the history.

**Tradeoff accepted:** Stale records accumulate. A "current" intake state must be derived by taking the most recent record per (item_id, shift_id). This is a simple `ORDER BY created_at DESC LIMIT 1` in any query that needs current state.

---

### Decision: Organizer completion independent of ShiftRun (ShiftAssignment.completed_at)
**Date:** 2026-04-08
**Problem:** ShiftRun tracks whether the truck route is done. Organizers don't have a ShiftRun — they work at the storage unit and may finish before or after the trucks. Coupling organizer "done" state to ShiftRun status would mean organizers can't close out their shift until all movers end theirs.

**Decision:** Add `ShiftAssignment.completed_at` (DateTime, nullable). Driver hits End Shift → sets `ShiftRun.completed` + their assignment's `completed_at`. Organizer hits End Intake → sets their assignment's `completed_at` only. Dashboard history uses `ShiftAssignment.completed_at` for all workers (not ShiftRun).

**Reasoning:** This is the minimal model that gives both roles an independent completion timestamp without adding a new table. `completed_at` on ShiftAssignment is already scoped to (worker, shift, role) — exactly what we need. End Intake is gated on `received_count >= total_items` so organizers can't close out until all expected items are logged.

---

### Decision: Worker role simplification — all workers are 'both', gating at ShiftAssignment level
**Date:** 2026-04-08
**Previous behavior:** `worker_role` field on User ('driver'|'organizer'|'both') was used to gate access to mover vs. organizer routes.
**New behavior:** `worker_role` field ignored for access control. All access gating uses `ShiftAssignment.role_on_shift` — you have access to a route if you're assigned to that shift in the relevant role.

**Reasoning:** The profile-level role was a blunt instrument that prevented a worker from doing both roles across different shifts (common in a small crew) and created booking complexity for the optimizer. By gating at the assignment level, the same worker can be a mover on Tuesday and an organizer on Thursday. The optimizer now pools all workers for both roles, which materially improves schedule coverage with a small crew.

**Impact:** `_require_mover` and `_require_organizer` both call `require_crew()`. Role-specific blocking (e.g., redirecting an organizer who navigates to `/crew/shift/<id>`) happens inside each route by checking `ShiftAssignment.role_on_shift`. Admin panel shows a static "Crew" badge instead of a role dropdown.

---

### Decision: Timezone fix — all day/time logic uses Eastern (zoneinfo), not UTC
**Date:** 2026-04-08
**Problem:** Several routes used `datetime.utcnow()` or compared against naive datetimes to determine "is today", "is the deadline passed", and "should I show AM or PM." The 1pm UTC slot preference cutoff (from Spec #3) was coincidentally close to noon Eastern during EST, but would be wrong during EDT (off by 1hr), and any date-boundary logic near midnight UTC is wrong by 5–6 hours for Eastern users.

**Decision:** Add `_now_eastern()` and `_today_eastern()` helpers using `zoneinfo.ZoneInfo('America/New_York')`. Use these for all day/time comparisons. Store timestamps in UTC (unchanged — SQLAlchemy default).

**Reasoning:** Campus Swap operates exclusively on a US East Coast campus. "What day is it" and "what time is it" should always be in Eastern time. Using UTC for these checks was a latent bug that would surface around midnight Eastern (when UTC is already tomorrow) and during DST transitions. `zoneinfo` is stdlib in Python 3.9+ and handles DST automatically.

**Affected routes:** `_is_availability_open`, `crew_dashboard`, `crew_availability`, `crew_shift_view`, `crew_shift_start`, `crew_shift_complete_retroactive`, `crew_intake_shift`, `_get_current_published_week`. PM slot preference cutoff updated from 1pm UTC to noon Eastern.

---

### Decision: Storage unit optional when flagging damaged/missing items
**Date:** 2026-04-08
**Problem:** The intake form required a storage location before submission. But a missing item (flag_type='missing') or unknown item (flag_type='unknown') has no storage location — it never arrived.

**Decision:** Storage unit field is optional when the flag checkbox is active. A flagged item can be submitted with no `storage_location_id`. The IntakeFlag is created; `InventoryItem.storage_location_id` is left NULL.

**Reasoning:** Forcing a storage location on a missing item would require a fake "unknown" location entry or a special null-selection option — both are workarounds that obscure actual data. Leaving the field NULL is semantically correct: a missing item's location is genuinely unknown. The damaged/missing admin queue shows these items for manual resolution.

---

### Decision: Destination unit auto-saves via fetch (no page reload)
**Date:** 2026-04-08
**Problem:** The destination unit selector on the ops page is a dropdown that admin changes frequently (assigning storage units to trucks while building the route). A standard form submit would reload the full ops page and scroll to the top every time.

**Decision:** The destination unit dropdown triggers a `fetch()` POST to `admin_shift_assign_unit` on `change` event. Route returns JSON `{success: true}`. JS shows a brief "Saved" indicator next to the dropdown. No page reload.

**Reasoning:** This is the one place in the ops system where a form-submit-and-redirect cycle has real UX cost — admins may change destination units 10+ times while building a shift. The fetch approach is a targeted exception to the server-rendered pattern: the route still does all DB writes server-side, we just skip the redirect. The response is JSON, not HTML, so there's no risk of partial render state.

**Alternative rejected:** Full-page submit with scroll restore (sessionStorage pattern from layout.html). Would work, but the ops page is long and the scroll position may not align well after each save.

---

### Decision: data-* attributes for JS item data, not inline tojson
**Date:** 2026-04-08
**Problem:** Item cards on the intake page used `onclick="openModal({{ item | tojson }})"` to pass item data to the modal handler. This broke HTML attribute quoting when item descriptions contained single quotes, double quotes, or special characters — the attribute value would terminate early and the JS would throw a syntax error.

**Decision:** Move all item data to `data-*` attributes (`data-item-id`, `data-item-description`, `data-photo-url`, etc.). JS reads them via `element.dataset.*` in the click handler.

**Reasoning:** HTML attribute values are always safe when using `data-*` with properly escaped values — Jinja's `{{ value }}` auto-escapes HTML entities in attribute context. `data-*` attributes are the correct DOM pattern for associating structured data with elements when you don't want inline JS. The modal handler becomes cleaner too: it reads from the dataset once rather than parsing a JSON argument.

**Rule added to Key Patterns in CODEBASE.md:** Never pass structured data to JS event handlers via inline tojson in onclick attributes. Use data-* attributes.

---

---

## Referral Program

### Decision: Replace Pro/Free tier with referral-driven payout rate
**Date:** 2026-04-09
**Options considered:**
- Keep two-tier system (Free 20% / Pro 50% via $15 upgrade)
- Single referral-driven rate that grows from 20% → 100% as referrals are confirmed

**Decision:** Referral program replaces the tier system entirely.

**Reasoning:** The $15 Pro upgrade was a weak monetization mechanism — it asked sellers to pay upfront before they knew how much they'd make, and it didn't create any viral loop. The referral program turns payout rate into a growth mechanic: every friend you recruit who actually ships an item earns you +10%. The incentive is money, not a social favor. At 8 referrals, a seller keeps 100% of their sales — a compelling hook that drives organic acquisition without any ad spend.

**Tradeoffs accepted:**
- Average payout rate will increase over time as the user base grows — this is by design. The business bet is that referral-driven volume growth outweighs the margin compression.
- `collection_method` field retained in DB for safety (no data migration needed, less risk). Payout calculations now read `User.payout_rate` exclusively.

---

### Decision: `calculate_payout_rate` includes signup bonus in recalculation
**Date:** 2026-04-09
**Problem:** The spec's pseudocode showed `rate = base + (confirmed × bonus_per)`. When a referred seller (who signed up with a code and got 30%) later refers others and their rate is recalculated, the formula would return 30 (base 20 + 1 confirmed × 10) — wiping out the signup bonus and producing the same result as if they hadn't used a code.

**Decision:** `rate = base + (signup_bonus if user.referred_by_id else 0) + (confirmed × bonus_per)`

**Reasoning:** A referred seller's signup bonus is a permanent part of their rate — it was earned by choosing to use a code, not by a referral action. The recalculation should preserve it. The signup bonus is a permanent offset from the base for all referred users. Confirmed test: a referred seller (30%) who refers one more person should land at 40%, not 30%.

**Spec update:** The pseudocode in `feature_referral_program.md` was incomplete. This is the correct formula. The test suite (`test_referral_chains_do_not_cross_contaminate`) defines the correct expected behavior.

---

### Decision: Referral confirmation triggered by mover stop completion, not warehouse arrival
**Date:** 2026-04-09 (revised from original `arrived_at_store_at` trigger)
**Reasoning:** Original design gated referral credit on `arrived_at_store_at` (warehouse intake). This was changed because if an item is damaged or lost in transit *after* the mover picks it up — mover's fault, not the seller's — the seller's referral code should still count. The seller did everything right; they had their items ready and the mover completed their stop. `crew_shift_stop_update` setting status to `'completed'` is now the trigger. `maybe_confirm_referral_for_seller(seller)` is called there. An `'issue'` stop status does not trigger confirmation (that covers the seller-side failure case — no one home, items not ready, etc.).

---

### Decision: Referral program kill switch via AppSetting, not a code deploy
**Date:** 2026-04-09
**Decision:** `referral_program_active` AppSetting controls the entire feature. If `'false'`: `/referral/validate` returns invalid, `apply_referral_code` no-ops, `maybe_confirm_referral_for_seller` no-ops. Existing stored `payout_rate` values are frozen and used as-is.

**Reasoning:** If the referral program needs to be dialed back quickly (e.g., unexpected margin impact, abuse pattern discovered), changing one AppSetting value in the admin panel takes 30 seconds. A code deploy takes 5+ minutes and requires a PR. This is the right safety valve for a financial feature.

**If max rate needs to be lowered:** Set `referral_max_rate` to a lower value (e.g., '60'). Users already above the new cap will have stored rates above it — document any one-time correction script needed in HANDOFF.md at the time.

---

### Decision: `url_for` called with try/except and hardcoded fallback in referral email
**Date:** 2026-04-09
**Problem:** `url_for('dashboard', _external=True)` requires an active Flask request context. `maybe_confirm_referral_for_seller` is called from `crew_shift_stop_update` (request context in production) but also from tests without a request context. An unguarded call inside the f-string silently swallowed the exception — the outer try/except caught it before `send_email` was reached.

**Decision:** Generate the URL in a separate try/except block before building the email body. Fall back to a hardcoded URL if generation fails.

**Reasoning:** Email delivery is more important than the URL being dynamic. A static URL fallback is acceptable — it's a dashboard link that won't change. Keeping the real `url_for` call as the primary path means production emails still use the correct URL scheme and host.

---

### Decision: Webhook returns 400 when `STRIPE_WEBHOOK_SECRET` not configured
**Date:** 2026-04-09
**Previous behavior:** `return 'STRIPE_WEBHOOK_SECRET not configured', 500`
**New behavior:** `return 'STRIPE_WEBHOOK_SECRET not configured', 400`

**Reasoning:** A 500 implies a server error. Missing webhook secret is a configuration problem, not an unexpected crash. 400 (Bad Request) is semantically cleaner — the request can't be verified, not because the server is broken but because the credentials aren't available. Also allows tests to assert the route doesn't 404 without needing a valid Stripe secret in the test environment.

---

## Seller Experience (continued)

### Decision: Payout boost ($15 for +30%) coexists with referral program; both paths stack
**Date:** 2026-04-13
**Context:** Referral program gives sellers +10% per confirmed referral, starting at 20%. Some sellers want a faster path to a higher rate.

**Decision:** Add a one-time $15 Stripe payment that instantly adds +30% to current rate, capped at 100%. Stacks freely with referrals.

**Reasoning:** The referral program is the primary growth mechanic (viral loop, costs nothing). The boost is a secondary, optional shortcut for sellers who want to move faster and are willing to pay. Keeping them independent and stackable means we don't have to arbitrate between paths — the seller chooses how much to optimize. Revenue from boosts is a bonus, not the primary model.

**Implementation notes:**
- `has_paid_boost` is a separate Boolean from legacy `has_paid`. Existing field left untouched.
- Boost amount ($15, +30%) is hardcoded this season. AppSetting path documented if configurability is needed later.
- Idempotency guard in webhook: check `not user.has_paid_boost` before applying — Stripe can redeliver.
- Boost card hidden (not just disabled) once purchased — no "you've upgraded" badge. The rate number itself is the feedback.
- Season reset (Fall): run one-time script to reset `has_paid_boost=False` and `payout_rate=20`. See HANDOFF for script.

---

### Decision: Payout collection removed from onboarding wizard
**Date:** 2026-04-13
**Old behavior:** Step 7 of the onboarding wizard collected Venmo/PayPal/Zelle handle. Required for guests before account creation.
**New behavior:** Payout info collected in account settings only. Onboarding skips it entirely.

**Reasoning:** Asking a new seller to enter payment info before their first item is approved adds friction at the worst moment — when they're least sure they'll actually get paid. The amber nag on the dashboard is a lighter-touch reminder at a time when they've already committed. Moving it out of onboarding also eliminated the `skip_payout` conditional that made the step count different for different users, simplifying the wizard code significantly.

**Tradeoff accepted:** Some sellers will submit an item without payout info set up. The dashboard nag addresses this. Admins can see payout status in the seller panel before initiating any payout.

---

### Decision: Item drafts stored as array in localStorage, not a single key
**Date:** 2026-04-13
**Old behavior:** `cs_item_draft` — single JSON object. Saving overwrites the previous draft.
**New behavior:** `cs_item_drafts` — JSON array. Each entry has a unique `id`. Multiple drafts coexist.

**Reasoning:** A seller working on multiple listings (which is the common case — most sellers list several items) would lose in-progress work every time they started a second item. The array model lets them save, exit, start a new item, and come back to each one independently.

**Key implementation details:**
- `currentDraftId` (IIFE-level var) tracks the active draft. Re-saves in the same session update the existing entry by ID. Fresh sessions generate a new ID.
- Computer-picked photos (File objects) are staged to the server at save time via `/api/photos/stage` → `draft_temp_` files served from disk. This is the only way to preserve them across a page navigation.
- "Exit without saving" preserves the last-saved state of the draft. Discarding is only possible from the dashboard Discard button. This prevents accidental data loss.
- No draft banner inside add_item page — dashboard is the single place to manage drafts.

---

## Pickup Location Improvements

### Decision: Three-way location type replaces two-way toggle; old 'off_campus' value migrated
**Date:** 2026-04-14
**Old values:** `'on_campus'` | `'off_campus'`
**New values:** `'on_campus'` | `'off_campus_complex'` | `'off_campus_other'`

**Decision:** Migration renames all existing `'off_campus'` rows to `'off_campus_other'`. New `'off_campus'` value is never written by the app post-migration. `pickup_display` and `has_pickup_location` handle legacy `'off_campus'` defensively as a fallback.

**Reasoning:** The old binary on/off-campus toggle forced every apartment dweller through Google Maps autocomplete — even if they lived in one of 7 buildings we already know the address of. The new `off_campus_complex` branch stores building name in `pickup_dorm` and unit in `pickup_room` (reusing existing columns) and skips geocoding entirely. The `off_campus_other` path retains the full Google Maps flow for everyone else.

---

### Decision: `pickup_dorm` and `pickup_room` reused for off_campus_complex (building + unit)
**Date:** 2026-04-14
**Options considered:**
- New columns `pickup_building` and `pickup_unit`
- Reuse `pickup_dorm` (building name) and `pickup_room` (unit number)

**Decision:** Reuse existing columns.

**Reasoning:** The semantics are identical — a named structure and a specific unit within it. Adding new columns would require a migration and leave the old columns always null for the complex branch. The display logic already knows which branch is active via `pickup_location_type`, so the same column can be correctly labeled "Building" vs "Dorm" depending on context. Zero schema churn.

---

### Decision: Access fields (access_type, floor) required for ALL branches; existing sellers prompted to re-enter
**Date:** 2026-04-14
**Decision:** `has_pickup_location` returns `False` if `pickup_access_type` or `pickup_floor` is null, regardless of location type. Existing sellers who never set these fields will see the setup strip chip until they update their location.

**Reasoning:** Movers need this information before arriving — staircase vs. elevator and floor number directly affect crew assignment and time estimates. Making it optional would mean most sellers leave it blank. Requiring it for `has_pickup_location = True` means the setup strip nag handles the prompt without any new banner or email. The one-time friction of re-entry is acceptable; the operational value is high.

**Tradeoff accepted:** All existing sellers with complete location data but no access fields will see the setup chip reappear. This is intentional — we want this info.

---

### Decision: `/login` POST processes even when already authenticated
**Date:** 2026-04-14
**Old behavior:** `if current_user.is_authenticated: return redirect(get_user_dashboard())` — any authenticated request to /login (GET or POST) redirected immediately.
**New behavior:** Only GET redirects. POST always processes the login form.

**Reasoning:** The test helper `make_seller` creates a user and immediately logs them in by POSTing to `/login`. In a loop of multiple test users, the second call was silently skipped because the first user was still authenticated, causing the second user's `update_profile` to modify the first user's record. The fix is also semantically correct for production: a deliberate POST to `/login` with valid credentials should be honored even if someone is already logged in (e.g., logging in as a different account). A GET to `/login` while logged in should still redirect (prevents confusing the already-authenticated UX).

---

### Decision: `<label>` elements for radio cards override via CSS class specificity + `!important`; section headers use `<p>` instead
**Date:** 2026-04-14
**Problem:** Global `label { display: block; text-transform: uppercase; font-weight: 700; margin-top: 15px; }` in `style.css` made all `<label>`-wrapped radio cards display as block (breaking `flex` layout), render text in ALL CAPS, and carry unwanted margins.

**Decision (radio cards):** CSS class `.access-type-card` and `.pickup-type-btn` override all conflicting global label properties via `!important` in a `<style>` block in the template. Radio inputs are visually hidden (`position: absolute; opacity: 0`) so clicking the card wrapper triggers native label behavior.

**Decision (section headers like "Dorm", "Floor", etc.):** Changed from `<label>` to `<p>` with explicit inline styles. These aren't functional labels (not associated with a specific input via `for`), so there's no accessibility tradeoff.

**Reasoning:** The global `label` rule was written for form field labels (e.g., "Email", "Phone"). It shouldn't apply to interactive card elements styled as buttons. The cleanest fix short of modifying `style.css` globally is to use class specificity. Modifying `style.css` globally would risk breaking other form labels throughout the app.
