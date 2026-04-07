# Campus Swap — Ops System Handoff State

> Update this file after every Claude Code session. It is the source of truth
> for what has actually been built, what changed from the spec, and what the
> next session needs to know. Paste the relevant sections into Claude Code at
> the start of each session alongside CODEBASE.md and OPS_SYSTEM.md.

---

## Current State

**Last updated:** 2026-04-06
**Active spec:** None — awaiting Spec #3 design
**Overall status:** Specs #1 and #2 signed off. Ready for Spec #3.

---

## Completed Specs

- Spec #1 — Worker Accounts ✅ Signed off 2026-04-06
- Spec #2 — Shift Scheduling ✅ Signed off 2026-04-06

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

## Spec #3 — Driver Shift View (Planned)

**Status:** Not started — spec not yet written
**Dependencies:** Spec #2 must be signed off first ✅

---

## Spec #3 — Driver Shift View (Planned)

**Status:** Not started — spec not yet written
**Dependencies:** Spec #2 must be signed off first

---

## Spec #4 — Organizer Intake (Planned)

**Status:** Not started — spec not yet written
**Dependencies:** Spec #3 must be signed off first

---

## Spec #5 — Payout Reconciliation (Planned)

**Status:** Not started — spec not yet written
**Dependencies:** Spec #4 must be signed off first

---

## Spec #6 — Route Planning (Planned)

**Status:** Not started — spec not yet written
**Dependencies:** Spec #2 must be signed off first

---

## Spec #7 — Seller Progress Tracker (Planned)

**Status:** Not started — spec not yet written
**Dependencies:** Spec #4 must be signed off first

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

*None identified yet.*

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

**Next session starts with:** Claude Desktop writes Spec #2 (`feature_shift_scheduling.md`). Once written, start a new Claude Code session with CODEBASE.md + OPS_SYSTEM.md + HANDOFF.md + feature_shift_scheduling.md.
