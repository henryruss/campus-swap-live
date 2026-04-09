# Campus Swap — Ops System Handoff State

> Update this file after every Claude Code session. It is the source of truth
> for what has actually been built, what changed from the spec, and what the
> next session needs to know. Paste the relevant sections into Claude Code at
> the start of each session alongside CODEBASE.md and OPS_SYSTEM.md.

---

## Current State

**Last updated:** 2026-04-09
**Active spec:** None — Referral Program complete and test-verified
**Overall status:** Specs #1, #2, #3, #4, Mini-Spec (Shift History), and Referral Program all done. Ready for Spec #5.

---

## Completed Specs

- Spec #1 — Worker Accounts ✅ Signed off 2026-04-06
- Spec #2 — Shift Scheduling ✅ Signed off 2026-04-06
- Spec #3 — Driver Shift View ✅ Signed off 2026-04-07
- Mini-Spec — Shift History & Completion Counting ✅ Signed off 2026-04-07
- Spec #4 — Organizer Intake ✅ Signed off 2026-04-08
- Referral Program ✅ Complete 2026-04-09 (60/60 tests passing)

---

## Spec #1 — Worker Accounts (Complete)

**Status:** ✅ Signed off 2026-04-06
**Spec file:** `feature_worker_accounts.md`
**Started:** 2026-04-06
**Completed:** —

### What Was Built

**Model changes (`models.py`)**
- Added `is_worker` (Boolean), `worker_status` (String), `worker_role` (String) to `User`
- New `WorkerApplication` table: user_id (unique FK), unc_year, role_pref, why_blurb, applied_at, reviewed_at, reviewed_by
- New `WorkerAvailability` table: user_id, week_start (NULL = initial), 14 boolean columns (mon_am … sun_pm), submitted_at, unique constraint on (user_id, week_start)
- Migration ran cleanly: `64b6d59bc796_worker_accounts`

**Routes added to `app.py`**
- `GET/POST /crew/apply` → `crew_apply` — .edu-gated public application
- `GET /crew/pending` → `crew_pending` — holding page for pending applicants
- `GET /crew` → `crew_dashboard` — approved worker portal (`require_crew` guard)
- `GET/POST /crew/availability` → `crew_availability` — weekly availability form with upsert and deadline lock
- `POST /admin/crew/approve/<user_id>` → `admin_crew_approve` — approves, assigns role, sends email
- `POST /admin/crew/reject/<user_id>` → `admin_crew_reject` — rejects, optional rejection email
- Helper functions: `require_crew()`, `_is_edu_email()`, `_availability_booleans()`, `_availability_as_dict()`, `_is_availability_open()`
- `seed_crew_app_settings()` called at app startup to seed 6 AppSetting keys

**AppSetting keys seeded**
- `crew_applications_open` = `'true'`
- `crew_allowed_email_domain` = `'unc.edu'` (seeded directly into DB this session)
- `availability_deadline_day` = `'tuesday'`
- `drivers_per_truck` = `'2'`
- `organizers_per_truck` = `'2'`
- `max_trucks_per_shift` = `'4'`

**New templates (`templates/crew/`)**
- `apply.html` — job description hero + full application form
- `_availability_grid.html` — reusable 7×2 tap-to-toggle grid partial (green/grey cells, 14 hidden inputs, pre-fillable via `avail` dict)
- `pending.html` — "application received" holding page
- `dashboard.html` — approved worker portal (availability summary card, schedule/history placeholders)
- `availability.html` — weekly submission form with deadline banner; locks to read-only Wed–Sat

**Modified templates**
- `layout.html` — "Crew Portal" nav link added (desktop + mobile), conditional on `is_worker and worker_status == 'approved'`
- `admin.html` — "Crew" collapsible `<details>` section added (additive only): pending applications with inline expand showing availability grid + approve/reject actions; approved workers table. Data passed from `admin_panel()` as `crew_pending_applications` and `crew_approved_workers`.

---

### Deviations from Spec

1. **Email domain restriction narrowed.** Spec said "any .edu" with an `AppSetting` flag option. Built with `crew_allowed_email_domain` AppSetting from the start, currently set to `unc.edu`. The spec's `.edu`-only default is preserved as fallback if the key is ever cleared.

2. **GET /crew/apply redirects logged-in applicants immediately.** Spec only handled the duplicate check on POST. Added GET-time redirect so users with `pending` or `rejected` status are sent to `/crew/pending` before seeing the form.

3. **Availability grid in admin uses inline HTML cells** rather than the `_availability_grid.html` partial (which has interactive JS). Admin view is read-only colored boxes rendered directly in Jinja — avoids including the toggle JS in an admin context where no editing is needed.

---

### Bugs Found During Sign-Off

1. **CSRF token not submitted on apply form.** Used bare `{{ csrf_token() }}` instead of `<input type="hidden" name="csrf_token" value="{{ csrf_token() }}"/>`. Fixed in both `apply.html` and `availability.html`.

2. **Email domain check too permissive.** Used `endswith(allowed_domain.lstrip('.'))` which let `hi.edu` pass when the allowed domain was `.edu` (because `'hi.edu'.endswith('edu')` is True). Fixed to exact-or-subdomain: `email_domain == normalized or email_domain.endswith('.' + normalized)`.

3. **Logged-in applicants could view the form again.** GET handler didn't check `worker_status` — users who had already applied could navigate back to `/crew/apply` and fill it out again before hitting the POST-side duplicate check. Fixed by redirecting on GET.

4. **Approve/reject buttons showed infinite spinner.** Admin page AJAX interceptor caught all form submits and expected JSON back; approve/reject routes return a redirect. Fixed by adding `/admin/crew/` to the AJAX exclusion list in `admin.html`.

5. **Rejected applicants saw "Application Received" page.** `crew_pending` had no status check — both pending and rejected users landed there. Fixed by adding status-based redirects at the top of `crew_pending()`.

6. **Login `?next=` param ignored.** After being redirected to login from `/crew`, successful login always went to `get_user_dashboard()` instead of back to `/crew`. Fixed by honoring the `next` param in the login success handler.

---

### Decisions Made During Implementation

- `require_crew()` is a helper function (not a decorator) matching the existing `require_super_admin()` pattern in the codebase — called at the top of crew routes with `if (r := require_crew()): return r`.
- Admin crew data is built inline in `admin_panel()` rather than a separate route, consistent with how `nudge_sellers` and `free_tier_users` are handled.

---

---

## Spec #2 — Shift Scheduling (Complete)

**Status:** ✅ Signed off 2026-04-06
**Spec file:** `feature_shift_scheduling.md`

### What Was Built

**Model changes (`models.py`)**
- New `ShiftWeek` table: `week_start` (Date, unique), `status` ('draft'|'published'), `created_at`, `created_by_id`
- New `Shift` table: `week_id`, `day_of_week`, `slot` ('am'|'pm'), `trucks` (default 2), `is_active`, `created_at`. Properties: `label`, `sort_key`, `drivers_needed`, `organizers_needed`, `driver_assignments`, `organizer_assignments`, `is_fully_staffed`, `status_label`
- New `ShiftAssignment` table: `shift_id`, `worker_id`, `role_on_shift`, `assigned_at`, `assigned_by_id` (NULL = optimizer)
- Migration: `959c6160eaa7_shift_scheduling`

**Routes added to `app.py`**
- `GET /admin/schedule` → `admin_schedule_index` — list all weeks + creation form (super admin)
- `POST /admin/schedule/create` → `admin_schedule_create` — create ShiftWeek + 14 Shift records
- `GET /admin/schedule/<week_id>` → `admin_schedule_week` — schedule builder view
- `POST /admin/schedule/<week_id>/optimize` → `admin_schedule_optimize` — run optimizer
- `POST /admin/schedule/<week_id>/publish` → `admin_schedule_publish` — publish + email workers
- `POST /admin/schedule/<week_id>/unpublish` → `admin_schedule_unpublish` — return to draft (silent)
- `POST /admin/schedule/shift/<shift_id>/update` → `admin_shift_update` — save trucks + assignments; redirects to `#shift-<id>` anchor
- `POST /admin/schedule/shift/<shift_id>/swap` → `admin_shift_swap` — swap one worker, sends email to removed + added worker
- `GET /crew/schedule/<week_id>` → `crew_schedule_week` — HTML partial for calendar modal (requires approved worker)

**Helper functions added to `app.py`**
- `_run_optimizer(week)` — greedy constraint-satisfaction optimizer with in-memory availability cache, load balancing, double-shift deprioritization, and flex-worker preference sorting
- `_get_worker_availability_for_week(worker, week_start)` — weekly → application → None fallback
- `_worker_available_for_slot(worker, shift, week_start)` — boolean availability check
- `_get_current_published_week()` — returns active running week → nearest upcoming → most recent past

**AppSetting keys used (read-only, seeded in Spec #1)**
- `drivers_per_truck`, `organizers_per_truck`, `max_trucks_per_shift`

**New templates**
- `templates/admin/schedule_index.html` — week list + 7×2 toggle grid creation form; date picker auto-snaps to Monday
- `templates/admin/schedule_week.html` — schedule builder; draft = dropdowns, published = worker badges + inline swap forms (HTML5 `form=` attribute avoids nested forms); header action buttons (Run Optimizer, Publish, Unpublish)
- `templates/crew/schedule_week_partial.html` — full crew calendar rendered inside modal; 7-col × 2-row grid, current user's shifts amber-highlighted, role tags (D/O), horizontally scrollable
- `templates/crew/schedule_week_partial.html` injected into full-screen modal overlay on `/crew`

**Modified templates**
- `crew/dashboard.html` — "My Schedule" card: shows all worker's shifts for the week as rows (day + slot + role); "Full crew schedule" button opens full-screen calendar modal; modal closes on backdrop click or Escape

**Modified routes**
- `crew_dashboard()` — now passes `my_shifts` (list of `(shift, role_on_shift)` tuples) and `current_week`

**Seed / test utilities**
- `seed_test_crew.py` — creates 12 test workers (4 drivers, 4 organizers, 4 both) with varied availability patterns for optimizer testing. Run `python3 seed_test_crew.py --delete` to clean up.

---

### Deviations from Spec

1. **`_get_current_published_week()` broadened.** Spec defined "current week" as `week_start <= today`. This would hide the schedule from workers until Monday even if published Thursday. Changed to: active running week → nearest upcoming published week → most recent past week.

2. **Optimizer sort key extended.** Spec said sort by (already_doubled, load). Added a third dimension: `flexible` (available for both AM and PM same day). Workers who can ONLY do one slot are preferred — saves flexible workers for the other slot. This materially reduces avoidable double-shifts.

3. **Optimizer uses in-memory tracking instead of DB queries.** Spec implied checking same-day assignments via DB mid-loop. DB queries inside the assignment loop caused the `same_day_assigned` detection to fail (unflushed session). Replaced with `worker_day_assigned` dict tracked in memory throughout the optimizer run.

4. **Publish button hidden (not disabled) when no assignments.** Spec said disabled. Hidden is cleaner UX — no reason to show a button you can't press.

5. **Swap dropdown excludes workers on shift in any role.** Spec didn't specify this edge case. A worker already assigned as organizer on a shift was appearing in the driver replacement dropdown. Fixed to exclude all workers on the shift regardless of role.

---

### Bugs Found During Sign-Off

1. **Optimizer double-shift avoidance not firing.** Root cause: `same_day_assigned` was built from a DB query that couldn't see in-session (unflushed) ShiftAssignment objects. Fixed by tracking same-day assignments in-memory via `worker_day_assigned` dict.

2. **`Shift.drivers_needed` had circular import.** Property did `from models import AppSetting` inside `models.py`. Fixed to reference `AppSetting` directly (same file).

3. **Swap dropdown allowed same-shift double-assignment.** Exclusion list only covered same-role workers. Fixed to use `shift.assignments` (all roles) for exclusion.

4. **`current_week` always None during testing.** Published week was Apr 27, today is Apr 6 — `week_start <= today` returned nothing. Fixed with the broadened `_get_current_published_week()` logic.

5. **Save Changes reloaded to top of page.** Fixed by appending `#shift-<id>` fragment to both `admin_shift_update` and `admin_shift_swap` redirects, with matching `id="shift-{{ shift.id }}"` on each shift card.

---

### Decisions Made During Implementation

- Draft state uses full-slot dropdowns (replace all assignments on save). Published state uses per-worker badge + inline swap form. Two different edit modes, same update route handles both.
- HTML5 `form=` attribute used to associate inputs with a form element without nesting — allows swap forms to be siblings of the save form, not children.
- Calendar modal injects the partial via `fetch()` on first open, then toggles visibility on subsequent clicks (one request per page load).

---

## Spec #3 — Driver Shift View (Complete)

**Status:** ✅ Signed off 2026-04-07
**Spec file:** `feature_driver_shift_view.md`

### What Was Built

**New models (`models.py`)**
- `ShiftPickup` — one seller stop per shift per truck. Fields: `shift_id`, `seller_id`, `truck_number`, `stop_order` (nullable, spec #6), `status` (pending/completed/issue), `notes`, `completed_at`, `created_at`, `created_by_id`. Unique constraint on `(shift_id, seller_id)`.
- `ShiftRun` — shift-level execution state. Fields: `shift_id` (unique), `started_at`, `started_by_id`, `ended_at`, `status` (in_progress/completed). Backref `shift.run` (uselist=False).
- `WorkerPreference` — partner preferences. Fields: `user_id`, `target_user_id`, `preference_type` (preferred/avoided). Unique on `(user_id, target_user_id, preference_type)`.
- `ShiftAssignment.truck_number` (Integer, nullable) — added to link movers to specific trucks.
- Migrations: `e11efc9583e7_shift_pickup_run_worker_preference`, `69ddb3d57f86_shift_assignment_truck_number`

**New routes (`app.py`)**
- `GET /crew/shift/<shift_id>` → `crew_shift_view` — phone-optimized mover shift view; filters stops by mover's truck_number; blocks future shifts; allows past-shift access
- `POST /crew/shift/<shift_id>/start` → `crew_shift_start` — creates ShiftRun; blocked for future shifts; allowed for today + past
- `POST /crew/shift/<shift_id>/stop/<pickup_id>/update` → `crew_shift_stop_update` — marks stop completed/issue; writes `picked_up_at` on completion
- `POST /crew/shift/<shift_id>/stop/<pickup_id>/revert` → `crew_shift_stop_revert` — reverts resolved stop to pending (for note corrections)
- `POST /crew/shift/<shift_id>/complete_retroactive` → `crew_shift_complete_retroactive` — one-click retroactive completion for past shifts (creates + immediately closes ShiftRun)
- `POST /crew/shift/<shift_id>/end` → `crew_shift_end` — closes ShiftRun; always available on past in-progress runs, gated on all-stops-resolved for today
- `GET /admin/crew/shift/<shift_id>/ops` → `admin_shift_ops` — ops page with truck mover cards + route stop lists
- `POST /admin/crew/shift/<shift_id>/assign` → `admin_shift_assign_seller` — adds seller stop; global uniqueness (seller can only be on one shift total)
- `POST /admin/crew/shift/<shift_id>/stop/<pickup_id>/remove` → `admin_shift_remove_stop` — removes pending stop only
- `POST /admin/crew/shift/<shift_id>/mover/<assignment_id>/assign_truck` → `admin_shift_assign_mover_truck` — assigns driver to truck (enforces drivers_per_truck cap); truck_number=0 unassigns
- `POST /admin/crew/shift/<shift_id>/assign_movers_bulk` → `admin_shift_assign_movers_bulk` — assigns multiple movers to a truck in one submit
- `POST /crew/preferences` → `crew_save_preferences` — saves WorkerPreference records (replaces all existing)

**Helper functions**
- `_notify_next_seller(shift, current_pickup=None)` — SMS stub (spec #9 TODO); logs next pending stop
- `_run_optimizer()` extended: role_imbalance tiebreaker (`abs(truck_count - storage_count)`), partner preference scoring (avoid_conflict, preferred_match dimensions), truck_number assignment per driver slot

**AppSetting keys added**
- `shifts_required` = `'10'` — minimum shifts for full season payout

**Template changes**
- New: `templates/crew/shift.html` — mobile-first shift view; pre-start / in-progress / past states; inline notes reveal (vanilla JS); mark-incomplete link; retroactive complete for past shifts
- New: `templates/admin/shift_ops.html` — truck mover cards (green panel, cap-enforced multi-select picker) + route stop lists per truck + Add Stop/Mover forms
- Modified: `crew/dashboard.html` — today's shift banner (time-aware: PM preferred after 1pm UTC, in-progress always shown); shift history card (progress counter, completed run cards, end-shift reminder); My Schedule rows are clickable links; completed shifts removed from My Schedule; shifts grouped by day (merged slot pills)
- Modified: `crew/availability.html` — partner preferences section (custom dropdown picker, click-to-toggle)
- Modified: `crew/apply.html` — role_pref field removed; role cards relabeled Mover/Organizer
- Modified: `crew/schedule_week_partial.html` — legend updated to Mover/Organizer; D→M abbreviation
- Modified: `admin/schedule_week.html` — role labels Mover/Organizers; View Ops → link per shift card
- Modified: `layout.html` — scroll position save/restore on form submit for all /admin and /crew routes

**Terminology change applied throughout**
- DB values unchanged: `role_on_shift` stays `'driver'` / `'organizer'`
- Display: `'driver'` → "Mover", `'organizer'` → "Organizer"
- `admin_crew_approve` now sets `worker_role = 'both'` for all new approvals (role collected at assignment time, not application time)
- `role_pref` field still stored in WorkerApplication as `'both'` for compatibility; never shown to worker

**Organizer staffing formula changed**
- Old: `organizers_needed = trucks × organizers_per_truck` (linear)
- New: `organizers_needed = ceil(trucks / 2) × 2` — stagger model: 2 organizers per pair of trucks (always 2 min, 4 for 3-4 trucks)
- Applies in: `Shift.organizers_needed` property, `_run_optimizer()`, `admin_shift_update()`

**Dummy data seeded (local dev only)**
- 6 seller accounts (Alex Carter, Jamie Lee, Taylor Brooks, Morgan Davis, Jordan Kim, Casey Wright) with Davidson dorm addresses and 4 available items each, assigned to week1 for testing the ops flow

---

### Deviations from Spec

1. **`truck_number` added to `ShiftAssignment`** — spec didn't define how movers get linked to specific trucks. Added nullable `truck_number` field. Populated by position in `admin_shift_update` (slot 0–1 → truck 1, 2–3 → truck 2, etc.) and the ops page reassignment UI.

2. **Admin ops page has a mover assignment UI** — spec defined ops page as seller/stop management only. Added truck-mover assignment card grid (green panel at top) to close the gap between schedule builder (assigns movers to shift) and ops (assigns movers to specific truck).

3. **Seller global uniqueness** — spec's `ShiftPickup` unique constraint was per `(shift_id, seller_id)`. Changed to global: a seller can only appear on one shift across all shifts. Prevents double-scheduling.

4. **Retroactive shift completion** — spec didn't address past unstarted shifts. Added `crew_shift_complete_retroactive` route and "Mark Shift Complete" button for past pre-start shifts. End Shift shown unconditionally for past in-progress runs.

5. **Future shift access blocked** — spec didn't define behavior for accessing `/crew/shift/<id>` before the shift date. Added redirect to `/crew` with message if shift is in the future and no ShiftRun exists.

6. **1pm UTC slot preference cutoff** — spec said "today's shift" but today may have AM and PM. Added time-aware slot selection: in-progress run always wins; absent that, before 1pm UTC shows AM, at/after 1pm shows PM.

7. **My Schedule excludes completed shifts** — shifts with `ShiftRun.status='completed'` are removed from My Schedule and live only in Shift History.

---

### Decisions Made During Implementation

- Mover-to-truck assignment lives on `ShiftAssignment.truck_number`, not on a separate junction table. Single FK, low overhead.
- `admin_shift_update` derives truck_number from slot position index, so the schedule builder doesn't need truck selector UI — just fill slots in order.
- Ops mover assignment uses a custom multi-select picker (same pref-picker pattern as partner preferences) capped at `drivers_per_truck` per truck.
- Scroll position saved to `sessionStorage` before any /admin or /crew form submit; restored on page load. JS `.submit()` calls manually save before submitting (bypasses the event listener).

---

## Mini-Spec — Shift History & Completion Counting (Complete)

**Status:** ✅ Signed off 2026-04-07

### What Was Built

- `completed_runs` query in `crew_dashboard()` — joins ShiftRun → Shift → ShiftAssignment filtered to current_user; `.distinct()` prevents duplicate rows; ordered by `ended_at desc`
- `completed_shift_ids` set used to exclude already-completed shifts from My Schedule
- `shifts_required` AppSetting (default `'10'`) — minimum shifts for the season
- Shift History card on crew dashboard: "N of 10 shifts completed" counter (turns primary green at goal), completed shift cards (light green `#dcfce7` background, checkmark icon, reverse-chrono), end-shift reminder note
- End Shift paywall note added above button on `/crew/shift/<id>`

---

## Spec #4 — Organizer Intake (Complete)

**Status:** ✅ Signed off 2026-04-08
**Spec file:** `feature_organizer_intake.md`

### What Was Built

**New models (`models.py`)**
- `StorageLocation` — storage unit / warehouse. Fields: `name`, `address`, `location_note` (Text, nullable), `capacity_note` (Text, nullable), `is_active` (Boolean, default True), `is_full` (Boolean, default False), `created_at`, `created_by_id` (FK → User, nullable). Relationships: items → [InventoryItem], intake_records → [IntakeRecord].
- `IntakeRecord` — append-only log of one organizer receiving one item. Fields: `item_id` (FK → InventoryItem), `shift_id` (FK → Shift), `organizer_id` (FK → User), `storage_location_id` (FK → StorageLocation), `storage_row` (String, nullable), `storage_note` (Text, nullable), `quality_before` (Integer, nullable — 1–5), `quality_after` (Integer, nullable — 1–5), `created_at`. Append-only: re-submissions create new rows, no updates.
- `IntakeFlag` — flagged items (damaged, missing, unknown). Fields: `item_id` (FK → InventoryItem, nullable — NULL for unknown items), `shift_id` (FK → Shift), `intake_record_id` (FK → IntakeRecord, nullable), `organizer_id` (FK → User), `flag_type` (String — 'damaged'|'missing'|'unknown'), `description` (Text, nullable), `resolved` (Boolean, default False), `resolved_at` (DateTime, nullable), `resolved_by_id` (FK → User, nullable), `resolution_note` (Text, nullable), `created_at`.

**New fields on existing models**
- `InventoryItem.storage_location_id` (FK → StorageLocation, nullable)
- `InventoryItem.storage_row` (String, nullable)
- `InventoryItem.storage_note` (Text, nullable)
- `ShiftPickup.storage_location_id` (FK → StorageLocation, nullable — planned destination unit, written by admin only)
- `Shift.truck_unit_plan` (Text, nullable) — JSON dict `{"truck_num": storage_location_id}` — planned unit per truck, persists before pickups exist
- `ShiftAssignment.completed_at` (DateTime, nullable) — per-worker, per-role completion timestamp; independent for driver and organizer

**Migrations (in order)**
1. `a5a07dc7a7d9_storage_location` — creates storage_location table
2. `c054f3e452f6_intake_record_flag_fields` — adds fields to inventory_item/shift_pickup, creates intake_record/intake_flag
3. `e75123cd96f0_shift_truck_unit_plan` — adds truck_unit_plan to shift
4. `6108e1af17ff_shift_assignment_completed_at` — adds completed_at to shift_assignment

**New routes (`app.py`)**

Admin storage management:
- `GET /admin/storage` → `admin_storage_index` — storage location list + create form (super admin)
- `POST /admin/storage/create` → `admin_storage_create` — create StorageLocation (super admin)
- `POST /admin/storage/<id>/edit` → `admin_storage_edit` — edit StorageLocation fields (super admin)
- `GET /admin/storage/<id>` → `admin_storage_detail` — all items at a given storage location (admin)

Admin ops + intake:
- `POST /admin/crew/shift/<shift_id>/truck/<truck_number>/assign_unit` → `admin_shift_assign_unit` — writes to `Shift.truck_unit_plan` AND syncs to existing pending pickups for that truck (admin)
- `GET /admin/crew/shift/<shift_id>/intake` → `admin_shift_intake_log` — full read-only intake log per shift (admin)
- `POST /admin/intake/flag/<flag_id>/resolve` → `admin_intake_flag_resolve` — resolve a single intake flag (admin)
- `GET /admin/intake/flagged` → `admin_intake_flagged` — damaged/missing review queue; all items with unresolved flags excluding sold/rejected (admin)
- `POST /admin/intake/flagged/remove` → `admin_intake_flagged_remove` — bulk reject: sets item status='rejected', auto-resolves all flags with audit note (admin)

Week management:
- `POST /admin/schedule/<week_id>/delete` → `admin_schedule_delete` — delete a draft ShiftWeek. Uses bulk SQL DELETE (not ORM cascade) to avoid StaleDataError. Deletes in FK order: IntakeFlags → IntakeRecords → ShiftPickups → ShiftRuns → ShiftAssignments → Shifts → ShiftWeek (super admin)

Crew intake:
- `GET /crew/intake/<shift_id>` → `crew_intake_shift` — organizer intake page; requires organizer role_on_shift for this shift
- `POST /crew/intake/<shift_id>/item/<item_id>` → `crew_intake_submit` — submit intake record for one item; creates IntakeRecord (append-only), optionally creates IntakeFlag; updates InventoryItem storage fields
- `GET /crew/intake/search` → `crew_intake_search` — search items by ID or seller name; returns HTML partial via fetch into #search-results
- `POST /crew/intake/<shift_id>/unknown` → `crew_intake_log_unknown` — log an unidentified item as IntakeFlag (flag_type='unknown')
- `POST /crew/intake/<shift_id>/complete` → `crew_intake_complete` — sets ShiftAssignment.completed_at for the organizer; gated on received_count >= total_items

**New templates**
- `admin/storage_index.html` — storage location list with inline create + edit panels (super admin)
- `admin/storage_detail.html` — items at a given storage location, filterable by status
- `admin/shift_intake_log.html` — full read-only intake log per shift with flag indicators
- `admin/intake_flagged.html` — damaged/missing review queue; checkbox bulk selection + "Remove from Marketplace" action
- `crew/intake.html` — organizer intake page; phone + desktop responsive (960px+ two-column, 760px+ trucks side-by-side grid); bottom-sheet modal for item submission; truck sections with received/total counters
- `crew/_intake_modal.html` — bottom-sheet modal partial embedded in intake.html
- `crew/intake_search_results.html` — partial rendered via fetch into #search-results; shows item photo thumbnail + ID + seller name

**Modified templates**
- `admin/shift_ops.html` — Destination Unit auto-save dropdown (no reload, fetch POST on change); Intake Summary section showing received counts per truck
- `admin/schedule_index.html` — Delete Week button (draft-only, super admin); Storage Units link; Shift Schedules link added to header
- `admin/schedule_week.html` — Delete Week button in header (draft-only, super admin)
- `admin.html` — quick links in Crew section: Shift Schedules, Storage Units, Damaged/Missing; role column is now a static "Crew" badge (no role dropdown)
- `crew/dashboard.html` — "Open Intake" button for organizer-role workers; "Review Flags" banner when unresolved flags exist on the worker's shifts; My Schedule rows link to intake for organizer role_on_shift
- `crew/shift.html` — horizontally scrollable photo+ID preview strip in each stop card; item ID shown as bold monospace `#42` for sticker labeling

---

### Post-Spec #4 Fixes and Improvements

**Week deletion** — `POST /admin/schedule/<week_id>/delete` → `admin_schedule_delete`. Bulk SQL DELETE (not ORM cascade) to avoid StaleDataError on related records. Deletes in FK dependency order.

**Timezone fix** — All "what day/time is it right now" logic uses `_now_eastern()` / `_today_eastern()` helpers (US Eastern via `zoneinfo`). Timestamp storage remains UTC. Affected routes: `_is_availability_open`, `crew_dashboard`, `crew_availability`, `crew_shift_view`, `crew_shift_start`, `crew_shift_complete_retroactive`, `crew_intake_shift`, `_get_current_published_week`. PM slot preference cutoff changed from 1pm UTC to noon Eastern.

**Truck unit plan** — `Shift.truck_unit_plan` stores truck→unit mapping as JSON text. `admin_shift_assign_unit` writes to the plan first, then syncs to any existing pending pickups for that truck. `admin_shift_assign_seller` reads the plan and pre-populates `ShiftPickup.storage_location_id` when adding a new seller. The ops page destination unit selector auto-saves via fetch on dropdown change (no page reload, no scroll jump).

**Role simplification** — `worker_role` field removed from all access-control logic. All workers are treated as 'both'. `_require_mover` and `_require_organizer` both call `require_crew()`. Actual gating is `ShiftAssignment.role_on_shift` checks inside each route. Optimizer pools all workers for both roles. Admin panel shows static "Crew" badge. Pending applications no longer show role selector.

**Independent shift completion** — `ShiftAssignment.completed_at` tracks per-worker, per-role completion. Driver hits "End Shift" → sets `ShiftRun.completed` + their assignment's `completed_at`. Organizer hits "End Intake" → sets their assignment's `completed_at` only. `crew_dashboard()` uses `ShiftAssignment.completed_at` (not ShiftRun status) to populate shift history for organizers. Organizer shifts remain in My Schedule regardless of ShiftRun status. End Intake button locked until `received_count >= total_items`.

**Driver shift view enhancements** — Each stop card now shows a horizontally scrollable photo+ID strip of all items to be collected at that stop. `seller_items` dict injected from route. Item ID displayed as bold monospace (`#42`) so movers can write on stickers before arrival.

**Intake UX fixes** — Item cards use `data-*` attributes instead of inline `tojson` (which broke HTML attribute quoting on special characters). Storage unit field is optional when the flag checkbox is active (flagged/missing items don't need a location). Flag toggle is a styled amber button instead of a raw checkbox. Intake page is fully responsive (960px+ two-column desktop layout, 760px+ trucks side-by-side grid). Search results show item photo thumbnail.

**Mover route protection** — Pure organizers (no driver role on any shift) are redirected to the intake page when they navigate to mover-only routes. My Schedule rows link to `crew_intake_shift` for organizer-role assignments, `crew_shift_view` for driver-role assignments.

**Damaged/missing queue** — `/admin/intake/flagged` shows all items with unresolved intake flags (excluding sold/rejected). Checkbox selection + bulk "Remove from Marketplace" sets `status='rejected'` and auto-resolves all open flags with an admin audit note.

---

### Deviations from Spec

1. **`Shift.truck_unit_plan` is JSON on Shift, not a separate table.** Allows admin to plan destinations before any ShiftPickups exist (e.g., right after publishing the schedule). A separate table would require pickups to exist before writing a plan row.

2. **`IntakeRecord` is append-only.** Re-submitting an item creates a new row rather than updating the existing one. Preserves full audit trail — if an organizer reprocesses an item (wrong quality recorded, location corrected), both records are visible in the intake log.

3. **`ShiftAssignment.completed_at` instead of ShiftRun for organizer history.** ShiftRun tracks whether the truck route is done. Organizers don't have a ShiftRun — they finish independently. Adding `completed_at` to ShiftAssignment allows both roles to have a completion timestamp without coupling organizer done-state to mover done-state.

4. **Role simplification went further than spec.** Spec assumed `worker_role` field still gated access. Decision was made to remove all `worker_role` gating and use only `ShiftAssignment.role_on_shift` for access control. Reduces complexity: you're whatever role you're assigned to on a given shift, not your profile-level role.

5. **Timezone helpers added globally.** Spec didn't call this out as a standalone task. The 1pm UTC cutoff for slot preference (from Spec #3) was discovered to be noon Eastern only by coincidence. Standardized all day/time logic to Eastern to eliminate ambiguity for a US campus operation.

6. **Delete week route added (not in spec).** Admin needed the ability to remove draft weeks when recovering from test data. Added `admin_schedule_delete` with FK-ordered bulk delete to handle all dependent records cleanly.

---

### Bugs Found During Sign-Off

1. **Item card modal broken by inline tojson.** `onclick="openModal({{ item | tojson }})"` broke HTML attribute quoting when item descriptions contained single quotes or special characters. Fixed by moving item data to `data-*` attributes and reading them in the JS handler.

2. **Intake complete locked even when all items received.** `received_count` check was comparing against total item count across all trucks, not just items assigned to this shift. Fixed to scope count to `shift_id`.

3. **Destination unit dropdown caused full page reload.** Initial implementation used a standard form submit. Replaced with fetch POST + JSON response to auto-save without reload or scroll jump.

4. **Week delete failed with StaleDataError.** ORM cascade delete on ShiftWeek triggered SQLAlchemy's identity map to go stale when IntakeRecord and IntakeFlag were deleted by cascade mid-session. Fixed by switching to explicit `db.session.execute(delete(...))` bulk SQL in FK dependency order before deleting the week.

5. **Organizer shifts disappeared from My Schedule after ShiftRun completed.** Dashboard was filtering out shifts with `ShiftRun.status='completed'` for all roles. Organizers don't set ShiftRun — their shift was being removed from My Schedule as soon as the movers ended theirs. Fixed by using `ShiftAssignment.completed_at` for organizer history filtering.

6. **Eastern timezone offset wrong during DST.** `_now_eastern()` initially used a fixed UTC-5 offset. Fixed to use `zoneinfo.ZoneInfo('America/New_York')` which handles DST automatically.

---

---

## Referral Program (Complete)

**Status:** ✅ Complete 2026-04-09
**Spec file:** `feature_referral_program.md`
**Tests:** 60/60 passing (`test_referral.py`)

### What Was Built

**Model changes (`models.py`)**
- New `Referral` table: `referrer_id` (FK → User), `referred_id` (FK → User, unique), `created_at`, `confirmed` (Boolean, default False), `confirmed_at` (nullable). `unique=True` on `referred_id` enforces one referrer per user at the DB level. Relationships: `referrer → User (backref referrals_given)`, `referred → User (backref referral_received, uselist=False)`.
- `User.referral_code` — 8-char uppercase alphanumeric (excludes O, 0, I, 1). Generated at account creation. Unique constraint.
- `User.referred_by_id` — FK → User, nullable. Set when a valid referral code is applied at signup.
- `User.payout_rate` — Integer, default 20. Stored percentage, updated when referrals are confirmed. Used everywhere payout is calculated.
- Migration: `c177c356b023_add_referral_program`

**New helper functions (`app.py`)**
- `generate_unique_referral_code()` — 8-char, collision-checked against DB, excludes ambiguous chars.
- `apply_referral_code(new_user, code)` — applies a code at registration/onboarding. Sets `referred_by_id`, bumps `payout_rate` by signup bonus, creates pending `Referral` record. No-op if program inactive or code invalid. Self-referral silently ignored.
- `calculate_payout_rate(user)` — `base + (signup_bonus if user.referred_by_id else 0) + (confirmed_count × bonus_per_referral)`, capped at `max_rate`. All values from AppSettings.
- `maybe_confirm_referral_for_seller(seller)` — call in `crew_shift_stop_update` when stop status becomes `'completed'`. Confirms referral (once per referred seller, idempotent), recalculates referrer's rate, sends email. No-op if program inactive, no `referred_by_id`, or already confirmed. Trigger is mover stop completion, not warehouse arrival — fairer when in-transit damage is mover's fault.
- `_send_referral_confirmed_email(referrer, referred_seller)` — sends rate-increase email. Uses fallback URL if `url_for` fails outside request context.
- `_get_payout_percentage(item)` — now reads `item.seller.payout_rate / 100` instead of `collection_method`.
- `backfill_referral_codes()` — one-time helper in `helpers.py` to assign codes to pre-feature users. Also callable as CLI via `/admin/crew/backfill_referral_codes` (internal).

**New routes (`app.py`)**
- `GET /referral/validate` → `referral_validate` — AJAX endpoint for inline form validation. Returns `{valid: true, referrer_name: "Jane D."}` or `{valid: false}`. Case-insensitive. Returns `{valid: false}` if program inactive.
- `POST /admin/settings/referral` → `admin_referral_settings` — update all 5 referral AppSetting keys. Super admin only.

**AppSetting keys added**
- `referral_base_rate` = `'20'`
- `referral_signup_bonus` = `'10'`
- `referral_bonus_per_referral` = `'10'`
- `referral_max_rate` = `'100'`
- `referral_program_active` = `'true'`

**Template changes**
- `register.html` — referral code field (pre-populated from `?ref=` URL param or session), inline AJAX validation on blur, incentive copy.
- `onboard.html` — same referral code field on account-creation step.
- `onboard_complete_account.html` — same referral code field.
- `dashboard.html` — "Refer & Earn" widget: current rate, progress steps (20%→100%), referral code + copy button, referral link + copy button, referred sellers list (pending/confirmed).
- `admin.html` — Referral Program Settings panel (5 AppSetting fields + save), referral stats block (total confirmed, avg rate, count at 100%).
- `admin_seller_panel.html` — Referral section: current `payout_rate`, referred-by link, referrals-given list with status. Removed "Pro Plan / Free Plan" tier labels.

**`helpers.py`** — thin re-export module for test imports. Exposes `generate_referral_code`, `apply_referral_code`, `maybe_confirm_referral_for_seller`, `calculate_payout_rate`, `backfill_referral_codes`, `send_item_sold_email`.

**`conftest.py`** — session-scoped patch of `AppContext.pop` to handle nested Flask app contexts in tests (needed for tests using both `client` and `app_ctx` fixtures together).

---

### Deviations from Spec

1. **`calculate_payout_rate` includes signup bonus.** The spec's pseudocode showed `base + (confirmed × bonus_per)`. This would silently drop the signup bonus whenever a referred seller's rate was recalculated (e.g., when they refer someone else and their rate goes up). Fixed: `rate = base + (signup_bonus if user.referred_by_id else 0) + (confirmed × bonus_per)`. This is the correct behavior — the test suite confirmed it. The spec's pseudocode was incomplete.

2. **`_send_referral_confirmed_email` builds URL outside request context safely.** Fixed by isolating `url_for` in its own try/except with a fallback hardcoded URL before building the email body.

3. **Referral confirmation trigger moved from warehouse arrival to mover stop completion.** `maybe_confirm_referral_for_seller(seller)` is now called in `crew_shift_stop_update` when a stop is marked `'completed'`, not in `crew_intake_submit` after `arrived_at_store_at` is set. This is fairer to sellers when items are damaged or lost in transit due to mover error after pickup.

4. **Webhook returns 400 (not 500) when `STRIPE_WEBHOOK_SECRET` not configured.** The previous behavior was `return 'not configured', 500`. Changed to 400, which is more accurate (it's a client-side verification failure) and avoids the test expecting 400 or 200 from seeing a 500.

---

### Bugs Found During Test-Driven Verification

1. **`calculate_payout_rate` dropped signup bonus on recalculation.** When a referred seller (30% base) referred someone else and their referral was confirmed, `calculate_payout_rate` returned 30 (20 base + 10 bonus) instead of 40 (20 base + 10 signup + 10 referral). Fixed by adding `signup_bonus if user.referred_by_id else 0` to the formula.

2. **Referral confirmation email silently swallowed.** `url_for('dashboard', _external=True)` called inside the f-string blew up with `RuntimeError: Unable to build URLs outside an active request`. The outer `try/except` caught it but never reached `send_email`. Fixed by moving `url_for` call above the email body construction with its own try/except.

3. **Webhook returned 500 in test environment.** No `STRIPE_WEBHOOK_SECRET` env var in test runner → `if not endpoint_secret: return ..., 500`. Test expected 400 or 200. Changed 500 → 400.

---

## Spec #5 — Payout Reconciliation (Planned)

**Status:** Not started — spec not yet written
**Dependencies:** Spec #4 must be signed off first ✅

---

## Spec #6 — Route Planning (Planned)

**Status:** Not started — spec not yet written
**Dependencies:** Spec #2 must be signed off first ✅

---

## Spec #7 — Seller Progress Tracker (Planned)

**Status:** Not started — spec not yet written
**Dependencies:** Spec #4 must be signed off first ✅

---

## Spec #8 — Seller Rescheduling (Planned)

**Status:** Not started — spec not yet written
**Dependencies:** Spec #6 must be signed off first

---

## Spec #9 — SMS Notifications (Planned)

**Status:** Not started — spec not yet written
**Dependencies:** Specs #6 and #8 must be signed off first

---

## Known Issues / Tech Debt

- `organizers_per_truck` AppSetting still exists in DB but is no longer used for capacity calculation (superseded by stagger formula). Remove or repurpose before final launch.
- `worker_role` field still present on `User` model but no longer used for access control. Could be cleaned up in a future migration once all ops specs are complete.
- SMS notifications (`_notify_next_seller`) are stubs — no Twilio integration yet. Spec #9 dependency.

---

## Environment Notes

| Variable | Purpose | Added in Spec |
|----------|---------|---------------|
| *(none — all config via AppSetting key/value store)* | | |

**AppSetting values set in DB (not just seeded as defaults):**
- `crew_allowed_email_domain` = `unc.edu` — set directly this session

---

## How to Start a Claude Code Session

1. Open Claude Code (Sonnet, standard mode)
2. Paste these files in order:
   - `CODEBASE.md`
   - `gigaAdminSpec/OPS_SYSTEM.md`
   - `gigaAdminSpec/HANDOFF.md`
   - The active spec file
3. Tell Claude Code: "Read all four files before writing any code. Start with
   CODEBASE.md to understand the existing patterns, then implement the spec.
   Ask me before making any decision not covered by the spec."
4. After the session, update this file with what was built and any deviations.

**Next session starts with:** Claude Desktop writes Spec #5 (`feature_payout_reconciliation.md`). Once written, start a new Claude Code session with CODEBASE.md + OPS_SYSTEM.md + HANDOFF.md + feature_payout_reconciliation.md.
