# Campus Swap — Spec Sign-Off Checklist

> These are human verification steps — things you personally check before
> declaring a spec done and moving to the next one. Not automated tests.
> Check each box yourself. If anything fails, go back to Claude Code.
>
> When a spec is fully signed off, update HANDOFF.md and change the spec
> status in OPS_SYSTEM.md to ✅ Done.

---

## Spec #1 — Worker Accounts

**Sign-off status:** ⬜ Not started

### Application Flow
- [✅] Visit `/crew/apply` without being logged in — page loads correctly
- [✅] Try submitting with a Gmail address — get a clear error message
- [✅] Submit with a `.edu` address — application created, confirmation page shown
- [✅] Log in as an existing Campus Swap seller, visit `/crew/apply` — name/email/phone pre-filled
- [✅] Submit as existing user — no duplicate account created, one `WorkerApplication` record in DB
- [✅] Try submitting a second application with the same account — get a clear error

### Availability Grid
- [✅] Grid loads with all 14 cells green (fully available) by default
- [✅] Tap an AM cell on mobile — it turns grey, hidden input updates
- [✅] Tap the same cell again — it returns to green
- [✅] Tap PM cell on same day — both AM and PM can be individually toggled
- [✅] Submit with some cells blacked out — DB record reflects correct True/False values
- [✅] Verify in DB: `SELECT mon_am, mon_pm, tue_am FROM worker_availability WHERE user_id = X`

### Admin Approval
- [✅] Log in as admin, open admin panel — "Crew" section visible with pending count badge
- [✅] Click View on an application — availability grid displays correctly, blacked-out cells clear
- [✅] Click Approve — modal appears with role selector
- [✅] Select "Driver", confirm — `is_worker=True`, `worker_status='approved'`, `worker_role='driver'` in DB
- [✅] Approval email arrives in inbox with correct content and `/crew` link
- [✅] Click Reject with email toggle on — rejection email sent
- [✅] Click Reject with email toggle off — no email sent

### Worker Portal Access
- [✅] Log in as approved worker, visit `/crew` — dashboard loads
- [✅] Log in as pending applicant, visit `/crew` — pending page shown, not an error
- [✅] Visit `/crew` while logged out — redirected to login, then back to `/crew`
- [✅] Log in as a regular buyer (non-worker), visit `/crew` — redirected appropriately
- [✅] Check nav as approved worker — "Crew Portal" link visible
- [✅] Check nav as non-worker — "Crew Portal" link not visible

### Weekly Availability Update
- [✅] Log in as approved worker, visit `/crew/availability` — grid pre-filled from application submission
- [✅] Change some cells, submit — DB record upserted correctly (no duplicate created)
- [✅] Verify `(user_id, week_start)` uniqueness: two records exist — one with `week_start=NULL` (application) and one with the current Monday's date (weekly update)
- [✅] Manually set date past Tuesday deadline, visit `/crew/availability` — form is locked with clear message

### Database & Migrations
- [✅] `flask db migrate` runs with no errors
- [✅] `flask db upgrade` runs with no errors
- [✅] `User` table has three new columns: `is_worker`, `worker_status`, `worker_role`
- [✅] `worker_application` table exists with correct schema
- [✅] `worker_availability` table exists with all 14 boolean columns
- [✅] AppSetting keys seeded: `crew_applications_open`, `availability_deadline_day`, `drivers_per_truck`, `organizers_per_truck`, `max_trucks_per_shift`

### Existing Features (Regression Check)
- [✅] Regular seller can still log in and access `/dashboard`
- [✅] Admin panel existing sections (inventory, approvals) still work
- [✅] Buyer can still browse `/inventory` and view product pages
- [✅] Stripe webhook endpoint still responds correctly


**unc.edu back in**
**Sign-off date:** 4/6/26
**Signed off by:** Henry Russell

---

## Spec #2 — Shift Scheduling

**Sign-off status:** ⬜ Not yet signed off

### Database & Migrations
- [✅] `flask db migrate -m "shift_scheduling"` runs with no errors
- [✅] `flask db upgrade` runs with no errors
- [✅] `shift_week` table exists with columns: `id`, `week_start`, `status`, `created_at`, `created_by_id`
- [✅] `shift` table exists with columns: `id`, `week_id`, `day_of_week`, `slot`, `trucks`, `is_active`, `created_at`
- [✅] `shift_assignment` table exists with columns: `id`, `shift_id`, `worker_id`, `role_on_shift`, `assigned_at`, `assigned_by_id`
- [✅] No existing tables modified

### Week Creation
- [✅] Visit `/admin/schedule` as super admin — page loads, existing weeks listed (empty at first)
- [✅] Visit `/admin/schedule` as regular admin (not super) — get a 403 or redirect
- [✅] Create a new week: pick a Monday date, submit — `ShiftWeek` record created with `status='draft'`
- [✅] Verify DB: 14 `Shift` records created (one per active slot), all with `is_active=True` by default
- [✅] Create a week with some slots toggled off (e.g., Sunday AM/PM) — those `Shift` records have `is_active=False`
- [✅] Try creating a second week with the same Monday date — get a clear error, no duplicate created

### Schedule Builder
- [✅] Visit `/admin/schedule/<week_id>` — page loads, all active shifts shown grouped by day
- [✅] Each shift row shows driver slots and organizer slots as empty badges
- [✅] Each shift row shows status badge: "Unassigned"
- [✅] Change trucks count on a shift from 2 to 3 — driver and organizer slot counts update immediately (no page reload)
- [✅] Change trucks count from 2 to 1 — slot counts reduce; confirm warning appears if workers already assigned
- [✅] Worker dropdowns on driver slots only show drivers and "both" role workers
- [✅] Worker dropdowns on organizer slots only show organizers and "both" role workers
- [✅] Unavailable workers (blacked out for that slot) do not appear in dropdowns
- [✅] Manually assign a worker to a slot, click Save — `ShiftAssignment` record created in DB with `assigned_by_id` = admin user
- [✅] Assign enough workers to fully staff a shift — status badge updates to "Fully Staffed"
- [✅] Leave a shift partially staffed — status badge shows "Understaffed"

### Optimizer
- [✅] Click "Run Optimizer" on a week with workers who have submitted availability — optimizer runs, assignments appear
- [✅] Verify no worker is assigned to a slot they blacked out (check against `worker_availability`)
- [✅] Verify workers with role `driver` are only assigned as drivers; `organizer` only as organizers; `both` can fill either
- [✅] Verify load spreading: workers with fewer total shifts in the week are preferred over those with more
- [✅] Verify double-shift avoidance: a worker is not assigned AM and PM on the same day unless no other option existed
- [✅] Shift with insufficient available workers shows "Understaffed" badge — no error thrown
- [✅] Flash message after optimizer run correctly states how many shifts are fully staffed vs. understaffed
- [✅] Run optimizer a second time on a week that already has assignments — confirmation prompt appears, assignments replaced cleanly on confirm

### Publishing
- [✅] "Publish Schedule" button is disabled when no shifts have any assignments
- [✅] Click "Publish Schedule" — `ShiftWeek.status` set to `'published'` in DB
- [✅] Every worker with at least one assignment receives a notification email listing their shifts
- [✅] Workers with no assignments do not receive an email
- [✅] After publish, button changes to "Unpublish"
- [✅] Click "Unpublish" — status returns to `'draft'`, no emails sent
- [✅] Verify no assignments are deleted on unpublish

### Last-Minute Swaps (Published Schedule)
- [✅] On a published week, click an assigned worker's name badge — "Remove & Replace" option appears
- [✅] Replacement dropdown shows only workers available for that slot, not already assigned to it, role-filtered
- [✅] If no eligible replacements exist — message says so, no broken dropdown
- [✅] Select a replacement — `ShiftAssignment` record updated in DB
- [✅] Removed worker receives swap notification email
- [✅] Added worker receives scheduling notification email
- [✅] Shift status badge recalculates after swap (e.g., if slot was understaffed and is now filled)

### Worker Dashboard — Schedule View
- [✅] Log in as approved worker, visit `/crew` — "My Schedule" column shows placeholder when no published week exists
- [✅] After publishing a week with assignments for this worker — next shift card appears with correct day, slot, and role
- [✅] "See full week schedule" button appears below next shift card
- [✅] Click it — full week schedule loads (via fetch, no page reload)
- [✅] Full schedule shows all shifts and all assigned worker names
- [✅] Current worker's own assignments are visually highlighted
- [✅] Click button again — schedule collapses (toggle behavior)
- [✅] Log in as a different approved worker with no assignments — "My Schedule" shows week is published but worker has no shifts assigned
- [✅] Visit `/crew/schedule/<week_id>` directly as a non-worker — 403 or redirect
- [✅] Visit `/crew/schedule/<week_id>` for a draft (unpublished) week — 404 or redirect, not visible to workers

### Availability Fallback Logic
- [✅] Create a worker who submitted application availability but has NOT submitted a weekly update for the current week
- [✅] Run optimizer — worker is still considered (using their application `week_start=NULL` availability)
- [✅] Create a worker with no availability record at all — optimizer treats them as unavailable, does not assign them

### Existing Features (Regression Check)
- [✅] `/crew/apply`, `/crew/pending`, `/crew/availability` all still work normally
- [✅] Admin panel crew section (approve/reject) still works
- [✅] Regular seller dashboard, item approval queue, and inventory page unaffected
- [✅] Stripe webhook still responds correctly

**Sign-off date:** 4/6/26
**Signed off by:** Henry Russell

---

## Spec #3 — Driver Shift View

**Sign-off status:** ⬜ Spec not yet written

---

## Spec #4 — Organizer Intake

**Sign-off status:** ⬜ Spec not yet written

---

## Spec #5 — Payout Reconciliation

**Sign-off status:** ⬜ Spec not yet written

---

## Spec #6 — Route Planning

**Sign-off status:** ⬜ Spec not yet written

---

## Spec #7 — Seller Progress Tracker

**Sign-off status:** ⬜ Spec not yet written

---

## Spec #8 — Seller Rescheduling

**Sign-off status:** ⬜ Spec not yet written

---

## Spec #9 — SMS Notifications

**Sign-off status:** ⬜ Spec not yet written
