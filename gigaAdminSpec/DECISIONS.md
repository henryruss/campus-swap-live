# Campus Swap — Design Decision Log

> Every meaningful design decision made during planning, with the reasoning.
> When Claude Code asks "why did we do it this way?", the answer is here.
> Add to this file whenever a non-obvious choice is made — during planning
> or during implementation.

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

### Decision: No whole-day blackout shortcut in the grid
**Date:** Spec #1 final revision
**Originally planned:** A "✕ Day" toggle column that blacks out both AM and PM
**Removed because:** "Keep it simple" — tapping two cells (AM + PM) achieves
the same result with no extra JS state to manage and no extra column to render.
The grid is already intuitive enough without a shortcut.
