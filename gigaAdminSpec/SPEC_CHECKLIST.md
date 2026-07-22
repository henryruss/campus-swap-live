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

**Sign-off status:** ⬜ Not yet signed off

### Database & Migrations
- [✅] `flask db migrate -m "shift_pickup_run_worker_preference"` runs with no errors
- [✅] `flask db upgrade` runs with no errors
- [✅] `shift_pickup` table exists with all fields; unique constraint on `(shift_id, seller_id)`
- [✅] `shift_run` table exists; unique constraint on `shift_id`
- [✅] `worker_preference` table exists; unique constraint on `(user_id, target_user_id, preference_type)`
- [✅] No existing tables modified

### Terminology
- [✅] "Driver" no longer appears in any crew-facing template (apply, dashboard, shift, availability)
- [✅] Admin schedule view shows "Mover (Truck)" and "Mover (Storage)" — not "Driver" / "Organizer"
- [✅] Role preference field (`role_pref`) is gone from the worker application form at `/crew/apply`

### Mover Shift View (`/crew/shift/<id>`)
- [✅] A worker not assigned to that shift gets a 403
- [✅] Pre-start state loads correctly: shift date, slot, truck number, stop count visible
- [✅] If no stops assigned yet: Start Shift button is hidden and a "check back soon" message shows
- [✅] Tapping Start Shift creates a `ShiftRun` record in the DB
- [✅] `[SMS HOOK]` log line appears in Render logs on shift start (first seller notification)
- [✅] In-progress state: stop cards show seller name, address, and item count
- [✅] Progress indicator at top ("X of Y stops done") is correct
- [✅] Tapping "Completed" reveals an optional notes field without a page reload
- [✅] Submitting Completed sets `status='completed'` and writes `picked_up_at` on seller's `available` items
- [✅] `picked_up_at` is NOT overwritten if it was already set on an item
- [✅] Tapping "Issue" reveals a notes field marked required
- [✅] Submitting Issue without a note is rejected
- [✅] `[SMS HOOK]` log line appears in Render logs after every stop completion
- [✅] After all stops are resolved, "End Shift" button appears
- [✅] End Shift sets `ShiftRun.status='completed'` and `ended_at`, redirects to `/crew` with flash message
- [✅] If shift is not today, a warning banner shows on the pre-start state (Start Shift still works)
- [✅] Two workers on the same truck both see the same stop list and each other's status updates on refresh

### Admin Ops View (`/admin/crew/shift/<id>/ops`)
- [✅] Page loads with shift header: date, slot, mover names, status, `started_at` if applicable
- [✅] Stop list is grouped by truck number
- [✅] "Add Stop" seller dropdown only shows sellers with `available` items not already on this shift
- [✅] Adding a stop creates a `ShiftPickup` record and reloads the page with a flash confirmation
- [✅] Remove button is visible on `pending` stops and hidden on `completed`/`issue` stops
- [✅] Attempting to remove a non-pending stop returns a flash error
- [✅] "View Ops →" link appears on each published shift card on `/admin/schedule/<week_id>`

### Partner Preferences (`/crew/availability`)
- [✅] Preferences section renders below the availability grid
- [✅] Both multi-selects are pre-populated with the worker's existing preferences on page load
- [✅] Submitting with the same worker in both lists returns a flash error
- [✅] Valid submission saves to DB and redirects back with "Preferences saved" flash
- [✅] Resubmitting replaces old preferences entirely — no duplicates accumulate in DB

### Crew Dashboard (`/crew`)
- [✅] "Today's Shift" banner only appears on the actual day of the shift
- [✅] Banner links to the correct `/crew/shift/<id>`
- [✅] If a `ShiftRun` already exists for that shift, button reads "Continue Shift"
- [✅] No banner shown on days with no shift assigned

### Optimizer (Re-run on an existing draft week)
- [✅] Optimizer still runs cleanly and produces valid assignments — no errors or regressions
- [✅] Workers with more truck shifts historically get storage assignments as a tiebreaker (check a few manually)
- [✅] Add two workers as a preferred pair, re-run — they land on the same shift where possible
- [✅] Add an avoided pair, re-run — they are not placed on the same shift
- [✅] Manual swap via admin schedule page still works on a published schedule

### Existing Features (Regression Check)
- [✅] `/crew/apply`, `/crew/pending`, `/crew/availability` all still load and function
- [✅] Admin crew approve/reject flow still works
- [✅] Existing published schedules still display correctly
- [✅] Regular seller dashboard and item approval queue unaffected
- [✅] Stripe webhook still responds correctly

**Sign-off date: 4/7/2026**
**Signed off by: Henry Russell**

---

## Mini-Spec — Shift History & Completion Counting

**Sign-off status:** ⬜ Signed off

- [✅] `shifts_required` AppSetting key exists in DB with value `'10'`
- [✅] Shift History column shows "0 of 10 shifts completed" when no shifts done
- [✅] Completing a shift (tapping End Shift) causes it to appear in history column on next dashboard load
- [✅] Completed shift cards show correct date, slot, and role
- [✅] Cards appear in reverse chronological order (most recent first)
- [✅] Progress counter increments correctly with each completed shift
- [✅] At 10+ shifts, counter reads "10 shifts completed ✓" in green
- [✅] Warning note appears above End Shift button on the shift view page
- [✅] `crew_dashboard()` query does not return shifts the worker was assigned to but did not end (no ShiftRun or ShiftRun.status != 'completed')
- [✅] Today's shift banner still works correctly alongside the history column

**Sign-off date: 4/7/26**
**Signed off by: Henry Russell**

---

## Spec #4 — Organizer Intake

**Sign-off status:** ⬜ Signed off

---

### Storage Location Management (Admin)

- [✅] Navigate to `/admin/storage` as super admin — see list of all storage locations with name, address, status badges, and item count
- [✅] Navigate to `/admin/storage` as regular admin — 403 or redirect
- [✅] Create a new storage location — appears in list with `is_active=True`, `is_full=False`
- [✅] Edit a storage location — name, address, location_note, capacity_note, is_active, is_full all update correctly
- [✅] Toggle `is_full=True` on a location — it disappears from the truck assignment dropdown on the ops page
- [✅] Toggle `is_active=False` on a location — it disappears from all dropdowns
- [✅] Attempt to delete a location that has items tagged to it — not possible (no delete route exists)
- [✅] Navigate to `/admin/storage/<id>` — see all items currently tagged to that location with correct columns

---

### Truck-to-Unit Assignment (Admin Ops Page)

- [✅] Open `/admin/crew/shift/<shift_id>/ops` — each truck card shows a "Destination Unit" dropdown of active, non-full locations
- [✅] Assign a unit to a truck — all *pending* ShiftPickups on that truck get `storage_location_id` updated
- [✅] Completed ShiftPickup stops are NOT updated when truck unit is reassigned
- [ ] Truck card shows green chip when unit assigned, amber "No unit assigned" when not *(UI — verify visually)*
- [✅] Reassign a truck to a different unit mid-shift — pending stops update, completed stops retain original value

---

### Organizer Intake — Shift-Scoped View

- [✅] Navigate to `/crew/intake/<shift_id>` as an organizer-role worker — page loads with shift label and item list
- [✅] Navigate to `/crew/intake/<shift_id>` as a mover-role worker — 403 or redirect
- [✅] Navigate to `/crew/intake/<shift_id>` as a non-worker logged-in user — 403 or redirect
- [✅] Navigate to `/crew/intake/<shift_id>` for a future shift — flash error, redirect to `/crew`
- [ ] Page shows trucks as collapsible sections, each with planned unit name or amber warning if none assigned *(UI — verify visually)*
- [ ] Each item card shows item ID badge, description, seller name, condition, and status chip (Pending) *(UI — verify visually)*
- [ ] Live counter shows "0 of Y items received" on page load *(UI — verify visually)*

---

### Organizer Intake — Submitting Intake

- [ ] Tap an item card — bottom-sheet modal opens with storage unit pre-populated from truck's planned unit *(UI — verify on device)*
- [ ] Storage unit dropdown shows only active locations (full and inactive excluded) *(UI — verify on device)*
- [✅] Change the storage unit in the modal to a different unit — submits with the new unit, not the planned one
- [✅] Submit intake — `InventoryItem.arrived_at_store_at` is set, `storage_location_id`/`storage_row`/`storage_note` are written, `IntakeRecord` is created
- [✅] Submit intake with condition change — `InventoryItem.quality` updates, `IntakeRecord.quality_before` captures old value, `IntakeRecord.quality_after` captures new value
- [✅] Submit intake without changing condition — `quality_before` and `quality_after` are equal
- [ ] After submit: item card turns green with checkmark, live counter increments *(UI — page reload reflects server state)*
- [✅] Re-submit intake on an already-received item — `arrived_at_store_at` is NOT overwritten, location/row/note/quality DO update, a new `IntakeRecord` row is appended (old one preserved)

---

### Organizer Intake — Flags

- [ ] Check "Flag issue" in the modal — flag description field appears *(UI — JS toggle)*
- [✅] Submit with flag checked but no description — validation error, form does not submit
- [✅] Submit with flag — `IntakeFlag` record created, item card turns amber with flag icon
- [✅] Flag appears in the Intake Summary section on the admin ops page
- [✅] Admin resolves flag via `/admin/intake/flag/<id>/resolve` with a resolution note — `resolved=True`, `resolved_at` set, `resolution_note` saved
- [ ] Resolved flag is visually distinguished (not deleted) on the admin intake log *(UI — verify visually)*

---

### Organizer Intake — Search Fallback

- [✅] Search by item ID on `/crew/intake/search` — matching item appears with intake status
- [✅] Search returns no results — "No items found" message shown
- [ ] Tap a search result — intake modal opens and submits correctly (no shift-scoping required) *(UI — verify on device)*
- [ ] Submit intake via search for an item not on the current shift manifest — intake records correctly, no error *(UI — verify on device)*

---

### Unknown Item Flow

- [ ] Item physically present but not found in search — "Log Unknown Item" form is available *(UI — verify visually)*
- [✅] Submit unknown item — `IntakeFlag` created with `flag_type='unknown_item'`, `item_id=NULL`, description saved
- [✅] Unknown item flag appears in admin intake log for the shift

---

### Admin Intake Log

- [✅] Navigate to `/admin/crew/shift/<shift_id>/intake` — full table of all IntakeRecords for the shift, grouped by truck
- [ ] Condition change shown in amber when `quality_before != quality_after` *(UI — verify visually)*
- [ ] Planned unit vs. actual unit visible per item (divergence is visible, no error state) *(UI — verify visually)*
- [✅] Ops page Intake Summary section shows per-truck "X of Y received" progress and open flags

---

### Crew Dashboard Integration

- [✅] Organizer-role worker with an in-progress shift sees "Open Intake →" button on today's shift banner
- [✅] Mover-role worker does NOT see the intake button
- [ ] Past shift with unresolved flags shows amber "Review Flags →" button *(UI — requires past shift with open flags)*

---

### Regression Check

- [✅] Existing mover shift view (`/crew/shift/<shift_id>`) unaffected
- [✅] Existing admin ops page mover assignment panel unaffected
- [✅] `ShiftPickup.status` (pending/completed/issue) unchanged by intake flow
- [✅] `InventoryItem.status` unchanged by intake flow
- [✅] `picked_up_at` unchanged by intake flow
- [ ] Stripe webhook still responds correctly *(unchanged — no Stripe code touched)*

**Sign-off date: 4/8/26**
**Signed off by: Henry Russell**


---


## Spec #5 — Payout Reconciliation

**Sign-off status:** ✅ Signed off 2026-04-14

### Database & Migration
- [✅] `flask db migrate` and `flask db upgrade` run with no errors
- [✅] `inventory_item` table has new `payout_sent_at` (DateTime, nullable) column
- [✅] Existing items with `payout_sent=True` have `payout_sent_at=NULL` — no errors, display as "—"

### Page Access & Layout
- [✅] Visit `/admin/payouts` as admin — page loads correctly
- [✅] Visit `/admin/payouts` as non-admin logged-in user — 403 or redirect
- [✅] Visit `/admin/payouts` while logged out — redirected to login
- [✅] Both "Unpaid" and "Paid" tabs are present and toggle correctly
- [✅] "Export Payouts CSV" button is visible on both tabs

### Unpaid Queue — Display
- [✅] Seller with one unpaid sold item appears as a card in the Unpaid tab
- [✅] Card shows seller name, email, payout method, and payout handle
- [✅] Payout handle renders as a copyable chip — clicking it copies to clipboard and briefly shows "Copied!"
- [✅] Seller's current payout rate (%) is shown on the card (e.g. "40%")
- [✅] Item row shows thumbnail, title, item ID, sale price, and computed payout amount
- [✅] Payout amount uses `seller.payout_rate`, not a hardcoded 20% or 50%
- [✅] Verify with a seller who has a non-base rate (e.g. 30% or 40% from referrals) — payout amount is correct
- [✅] `sold_at` date displayed on each item row
- [✅] Sellers sorted by total unpaid amount descending — largest balance at the top
- [✅] Seller with no unpaid items does not appear in the Unpaid tab

### Unpaid Queue — Warning Badges
- [✅] Item with no `IntakeRecord` shows amber "No intake record" badge
- [✅] Item with an `IntakeRecord` does NOT show the intake badge
- [✅] Item with an unresolved `IntakeFlag` shows amber "Flagged: damaged" or "Flagged: missing" badge
- [✅] Flag badge links to `/admin/intake/flagged`
- [✅] Item with a resolved `IntakeFlag` does NOT show the flag badge
- [✅] Both badges can appear simultaneously on the same item row
- [✅] Warning badges do not block the Mark Paid button

### Unpaid Queue — Missing Payout Handle
- [✅] Seller with no `payout_handle` set — card shows amber warning "Missing payout handle — ask seller to update their account"
- [✅] Mark Paid button still present and functional for sellers with no handle

### Mark Paid — Flow
- [✅] Click "Mark Paid" — button changes inline to "Confirm? ✓ ✗" (no modal, no page reload)
- [✅] Click ✗ — button reverts to "Mark Paid", nothing submitted
- [✅] Click ✓ — POST fires, page reloads
- [✅] After marking paid: `payout_sent=True` and `payout_sent_at` set in DB
- [✅] `payout_sent_at` is a recent UTC timestamp (within a minute of the action)
- [✅] Item row disappears from the seller's card after marking paid
- [✅] If that was the seller's last unpaid item, the entire seller card disappears from the Unpaid tab
- [✅] If the seller has other unpaid items, the card remains with the remaining item rows
- [✅] Payout confirmation email sent to seller (check inbox)
- [✅] Marking an already-paid item (e.g. double POST) — flash "Already marked paid", no error, no duplicate email

### Payout Confirmation Email
- [✅] Email arrives at seller's address after marking paid
- [✅] Subject: "You've been paid for your Campus Swap item!"
- [✅] Email shows item title, sale price, correct payout rate (%), and correct payout amount
- [✅] Payout amount in email matches what was shown on the `/admin/payouts` page
- [✅] Email shows payout method and handle (e.g. "Venmo — @janedoe")
- [✅] Seller with no payout handle — email sends successfully, "Sent to" line is omitted
- [✅] Email uses `wrap_email_template()` styling (consistent with other system emails)

### Paid History Tab
- [✅] Items marked paid appear in the Paid tab
- [✅] Items are sorted reverse-chronologically by `payout_sent_at`
- [✅] Each row shows: item thumbnail, title, seller name, sale price, payout rate (%), payout amount, payout method + handle, `payout_sent_at` date, "View Item" link
- [✅] Seller name links to the seller profile slide-out panel
- [✅] "View Item" link goes to the correct admin item edit page
- [✅] Items with `payout_sent=True` but `payout_sent_at=NULL` (pre-spec legacy) display "—" for date, no error
- [✅] Pagination works correctly at 50 items per page (if enough paid items exist to test)

### CSV Export
- [✅] Click "Export Payouts CSV" — file downloads
- [✅] CSV contains all sold items (both paid and unpaid)
- [✅] Columns present: `item_id`, `item_title`, `seller_name`, `seller_email`, `payout_method`, `payout_handle`, `sale_price`, `payout_rate`, `payout_amount`, `sold_at`, `payout_sent`, `payout_sent_at`, `has_intake_record`, `has_unresolved_flag`
- [✅] `payout_rate` column reflects `seller.payout_rate` (not hardcoded 20 or 50)
- [✅] `payout_amount` column is correct (`sale_price × payout_rate / 100`)
- [✅] `has_intake_record` is `True` for items with an `IntakeRecord`, `False` otherwise
- [✅] `has_unresolved_flag` is `True` for items with an unresolved `IntakeFlag`, `False` otherwise
- [✅] `payout_sent_at` is ISO format for paid items, empty string for unpaid

### Admin Panel — Payout Section Removed
- [✅] Visit `/admin` — old item-level payout section with "Mark Paid" buttons is gone
- [✅] In its place: a summary card showing count of items awaiting payout and total amount owed
- [✅] Summary card links to `/admin/payouts`
- [✅] `unpaid_items_count` and `unpaid_total` values in the summary are correct

### Existing Features (Regression Check)
- [✅] `/admin/export/sales` CSV still exists and downloads correctly
- [✅] Seller dashboard still shows correct payout status per item (unaffected)
- [✅] Referral program logic unchanged — `payout_rate` on sellers is not modified by any route in this spec
- [✅] Stripe webhook still processes purchases correctly and does NOT set `payout_sent`
- [✅] Organizer intake flow (`/crew/intake/<shift_id>`) unaffected
- [✅] Seller profile panel slide-out still loads and displays correctly

**Sign-off date:**
**Signed off by:**

---

## Spec #6 — Route Planning

**Sign-off status:** ⬜ Not yet signed off
**Automated tests:** 69/69 passing (`pytest test_route_planning.py`)

> Items marked [✅] are covered by passing automated tests.
> Items marked [ ] require your eyes on the running app — run `python3 seed_db.py && flask run` first.

---

### Database & Migrations

- [✅] Migration `add_route_planning_fields` runs cleanly with `flask db upgrade`
- [✅] `inventory_category` table has `default_unit_size` column (Float, default 1.0)
- [✅] `inventory_item` table has `unit_size` column (Float, nullable)
- [✅] `shift` table has `sellers_notified` column (Boolean, default False)
- [✅] `shift_pickup` table has `notified_at` (DateTime) and `capacity_warning` (Boolean) columns
- [✅] `user` table has `pickup_partner_building` column (String, nullable)
- [✅] `storage_location` table has `lat` and `lng` columns (Float, nullable)
- [✅] AppSettings seeded: `truck_raw_capacity` (18), `truck_capacity_buffer_pct` (10), `route_am_window`, `route_pm_window`, `maps_static_api_key`
- [ ] Verify in DB: couch/sofa category has `default_unit_size = 3.0`, microwave has `0.5`

---

### Item Unit Sizing

- [✅] `get_item_unit_size(item)` returns category default (3.0 for couch) when no per-item override
- [✅] `get_item_unit_size(item)` returns the per-item `unit_size` when set
- [✅] `unit_size = 0.0` on an item is respected (not treated as NULL)
- [✅] Falls back to `1.0` when item has no category
- [✅] Falls back to `1.0` when category has no `default_unit_size`
- [✅] `get_seller_unit_count(seller)` sums only `available` items — sold, pending, rejected excluded
- [ ] Open an item in the approval panel — "Unit size override" float field is visible with category default as placeholder *(UI)*

---

### Truck Capacity

- [✅] `get_effective_capacity()` = `floor(18 × 0.9)` = 16 with default settings
- [✅] Zero buffer → effective cap = raw cap exactly
- [✅] Floor is applied (e.g. raw=10, buffer=15% → floor(8.5) = 8)
- [✅] Falls back to defaults when AppSettings not set
- [✅] Route settings page loads at `/admin/settings/route`
- [✅] Saving route settings persists new `truck_raw_capacity` and `truck_capacity_buffer_pct`
- [✅] Saving category unit sizes persists per-category `default_unit_size`
- [✅] Non-super-admin cannot POST to `/admin/settings/route` (403 or redirect)
- [ ] Open `/admin/settings/route` — "Effective capacity: X units" preview updates live as you change the inputs *(JS)*
- [ ] Capacity gauge on ops page shows green when under 75%, yellow at 75–100%, red when over *(UI)*

---

### Route Builder (`/admin/routes`)

- [✅] Page loads and requires admin (non-admin redirected)
- [✅] Sellers without `pickup_week` set do NOT appear in the unassigned panel
- [✅] Sellers with available items and a pickup_week ARE shown in the unassigned panel
- [✅] Shift capacity board loads with all active shifts
- [ ] Navigate to `/admin/routes` — unassigned sellers are grouped by cluster label (dorm name, building name, or street) *(UI)*
- [ ] Each seller card shows name, unit count, week, and AM/PM badge *(UI)*
- [ ] seller_noweek@test.com is NOT visible in the unassigned panel *(visual confirm)*
- [ ] Shift board shows capacity gauge per truck with correct load/cap numbers *(UI)*
- [ ] "Add Truck" button on a shift card works — truck count increments, page reloads with new truck *(UI)*
- [ ] "Order Route" button appears per shift card *(UI)*
- [ ] "Notify Sellers" button appears per shift card *(UI)*

---

### Auto-Assignment

- [✅] Sellers with `morning` preference are placed on `am` shifts, `afternoon` → `pm`
- [✅] Seller with no matching slot goes to TBD list with a reason string
- [✅] TBD response includes `seller_id` and non-empty `reason`
- [✅] Over-capacity assignment still succeeds — `capacity_warning=True` on the `ShiftPickup`
- [✅] Re-running auto-assign skips sellers who already have a `ShiftPickup`
- [✅] Sellers without `pickup_week` are excluded (not in assigned OR tbd lists)
- [✅] Largest unit-count sellers are placed first
- [ ] Click "Run Auto-Assignment" — spinner appears, page reloads with sellers assigned to shifts *(UI)*
- [ ] TBD section appears at top if any sellers couldn't be placed — shows reason *(UI)*
- [ ] Over-cap warnings section appears if any truck exceeded effective capacity *(UI)*
- [ ] seller_noweek@test.com is not placed on any shift after running auto-assign *(visual confirm)*

---

### Geographic Clustering

- [✅] Two sellers in the same dorm share a cluster with that dorm's name as the label
- [✅] Two sellers in different dorms get different cluster labels
- [✅] Two sellers at the same partner apartment building cluster together by building name
- [✅] A partner apartment seller is NOT grouped by lat/lng proximity with a nearby off-campus seller
- [✅] Two off-campus sellers within 0.25 miles are clustered together
- [✅] Two off-campus sellers more than 0.25 miles apart get separate clusters
- [✅] Sellers with no lat/lng and no building name go to the "Unlocated" cluster

---

### Stop Ordering (Nearest-Neighbor)

- [✅] "Order Route" populates `stop_order` on all pickups for the shift
- [✅] Multiple stops get unique, sequential `stop_order` values
- [✅] Stops with no lat/lng are assigned higher `stop_order` values than located stops
- [✅] Manual reorder (`POST /admin/crew/shift/<id>/stop/<pid>/reorder`) updates `stop_order`
- [ ] After clicking "Order Route" on the ops page, stop cards render in the new order *(UI)*
- [ ] Stop with no address appears at the bottom of the list *(UI)*
- [ ] If storage unit has no lat/lng set, "Order Route" falls back to insertion order and shows a flash warning *(set storage lat/lng to NULL to test)*

---

### Add Truck

- [✅] POST to add-truck increments `Shift.trucks` by 1
- [✅] Response JSON contains `new_truck_number`
- [✅] New truck number = `max(existing truck numbers) + 1`
- [✅] Requires admin (worker gets 403/redirect)
- [✅] Works during an active `ShiftRun` (mid-shift add)
- [ ] After clicking "Add Truck" on the route builder, the new truck appears with "Workers TBD" and empty stop list *(UI)*
- [ ] After clicking "Add Truck" on the ops page, the new truck section appears *(UI)*

---

### Stop Movement

- [✅] Moving a stop to a different truck updates `truck_number`
- [✅] Moving a stop to a different shift updates `shift_id`
- [✅] Moving a stop to a truck under effective capacity clears `capacity_warning`
- [✅] Manual assign creates a `ShiftPickup` (200 OK)
- [✅] Manual assign when seller already has a pickup returns 409
- [ ] Click "Move →" on a stop card — dropdown appears with all shift+truck options *(UI)*
- [ ] After moving, the stop disappears from the old truck and appears on the new one *(UI)*

---

### Seller Notification

- [✅] POST to notify sends one email per seller with `notified_at IS NULL`
- [✅] `Shift.sellers_notified` is set to True after notifying
- [✅] Re-running notify does NOT re-send to already-notified sellers (idempotent)
- [✅] Newly added seller (after first notify) gets email on second notify; first seller does not
- [ ] Click "Notify Sellers" — flash confirmation appears with count of emails sent *(UI)*
- [ ] "Notified ✓" badge appears in shift header after sending *(UI)*
- [ ] Check inbox — email arrives with correct subject "Your Campus Swap pickup is [shift label]" and time window *(email)*

---

### Mover Shift View Upgrades

- [✅] `/crew/shift/<id>/stops_partial` requires crew login (non-crew redirected)
- [✅] Partial returns HTML with the mover's seller name visible
- [✅] Partial only shows stops for the mover's truck (other trucks' stops excluded)
- [✅] Navigate button is present and contains `maps.google.com` link
- [ ] Open the shift view as a mover — stops appear in `stop_order` sequence *(UI)*
- [ ] Each stop card shows a "Navigate →" button that opens Google Maps in a new tab *(UI)*
- [ ] Seller with `pickup_access_type = 'elevator'` shows "🛗 Elevator" badge *(UI)*
- [ ] Seller with `pickup_access_type = 'stairs_only'` shows "🪜 Stairs" badge *(UI)*
- [ ] Wait 30 seconds with the shift view open — stop list auto-refreshes silently (no page flash) *(UI — add a new stop via ops page, watch it appear)*

---

### Ops Page Upgrades

- [✅] Issue alert banner appears when a stop has `status = 'issue'`
- [✅] Issue banner shows the stop's notes text
- [✅] No banner when all stops are `pending` or `completed`
- [✅] Stairs badge present on stop card when seller has `pickup_access_type = 'stairs'`
- [✅] Elevator badge present on stop card when seller has `pickup_access_type = 'elevator'`
- [ ] Open `/admin/crew/shift/<id>/ops` — stops are shown in ascending `stop_order` order, nulls last *(UI)*
- [ ] Stop cards show stop number badge (#1, #2…), seller name, access badge, and capacity warning badge if flagged *(UI)*
- [ ] "Add Truck" and "Notify Sellers" buttons visible in shift header *(UI)*
- [ ] "Order Route" button visible per truck section *(UI)*

---

### Static Map URL

- [✅] `build_static_map_url` returns `None` when `maps_static_api_key` is empty
- [✅] Returns a URL string containing `maps.googleapis.com` and the API key when key is set
- [✅] Returned URL includes `markers` params for stops
- [ ] On ops page without API key configured — text address list renders instead of map image, no error *(UI)*
- [ ] *(Optional, skip until key is provisioned)* Set `maps_static_api_key` in AppSettings → map image renders per truck *(UI)*

---

### Regression Check

- [✅] Existing ops page (`/admin/crew/shift/<id>/ops`) still loads
- [✅] Existing mover shift view (`/crew/shift/<id>`) still loads
- [✅] Admin panel still loads
- [✅] Seller dashboard still loads
- [✅] `_get_payout_percentage` helper untouched and returns correct float
- [✅] Existing `admin_shift_assign_seller` route (ops page "Add Stop" form) still works

---

**Sign-off date: 4/14/26**
**Signed off by: Henry Russell**

---
## Spec #7 — Seller Progress Tracker

**Sign-off status:** ✅ Signed off

### No Migration
- [✅] Confirm no `flask db migrate` was run — `git diff --name-only` confirmed `models.py` not in diff; no new migration file created

### Tracker Visibility Logic
- [✅] Log in as a seller with setup strip incomplete (missing phone, pickup week, or payout) — tracker is NOT shown, setup strip is shown as normal *(manual + automated)*
- [✅] Complete all three setup tasks — setup strip disappears, tracker appears in its place *(manual + automated)*
- [✅] Both are never visible simultaneously *(manual + automated)*

### Stage 1 — Submitted
- [✅] Seller with at least one non-rejected item sees Stage 1 as completed, Stage 2 as active *(automated)*

### Stage 2 — Approved
- [✅] Item in `pending_valuation` → Stage 2 is active *(automated)*
- [✅] Item approved (status `available`) → Stage 2 completed, Stage 3 active *(automated)*
- [✅] Item in `needs_info` → Stage 2 still active + amber interrupt callout appears below tracker with link to edit item *(automated)*

### Stage 3 — Scheduled
- [✅] Seller has no `ShiftPickup` → Stage 3 active *(automated)*
- [✅] Admin adds seller to a route → Stage 3 completed, Stage 4 active *(automated)*
- [✅] `ShiftPickup.status = 'issue'` → Stage 3 stays active + amber interrupt "There was an issue with your pickup" appears *(automated)*
- [✅] Issue resolved (stop re-completed) → interrupt disappears, Stage 3 completes on next page load *(automated)*

### Stage 4 — Picked Up
- [✅] Before mover completes stop → Stage 4 active *(automated)*
- [✅] Mover completes stop (sets `picked_up_at`) → Stage 4 completed on next dashboard load *(automated)*

### Stage 5 — At Campus Swap
- [✅] Before organizer intake → Stage 5 active *(automated)*
- [✅] Organizer submits intake (sets `arrived_at_store_at`) → Stage 5 completed on next dashboard load *(automated)*

### Stage 6 — In the Shop
- [✅] `shop_teaser_mode = 'true'` → Stage 6 active (not yet complete) even if items are available *(automated)*
- [✅] `shop_teaser_mode = 'false'` and at least one item is `available` or `sold` → Stage 6 completed *(automated)*
- [✅] All 6 stages completed → tracker remains visible, all nodes green, message "Your items are in the shop. Good luck! 🎉" *(automated)*

### Visual
- [✅] Completed nodes are filled green with a checkmark *(manual)*
- [✅] Active node is filled amber with a pulse animation *(manual)*
- [✅] Upcoming nodes are grey stroke only *(manual)*
- [✅] Connecting line is solid green between completed nodes, dashed grey after active node *(manual)*
- [✅] Active stage label is bolder than upcoming labels *(manual)*
- [✅] Contextual message below track matches the active stage (see spec for copy) *(manual)*

### Item Tile
- [✅] The 4-item checklist (Approved / Pickup confirmed / Awaiting pickup / In store) is removed from item tiles *(automated)*
- [✅] "Pricing update" badge on price row is present; UX improved — hover reveals × to dismiss, click acknowledges *(manual)*
- [✅] Tile color-coded backgrounds present; scheme updated: gray (waiting), yellow (action needed / unacknowledged price change), green (sold), red (rejected) *(manual)*

### Mobile
- [✅] On a narrow screen (< 600px) — tracker renders without breaking layout *(manual)*
- [✅] Non-active stage labels are hidden; active stage label is visible below the track *(manual)*

### Regression Check
- [✅] Seller dashboard still loads with no errors for sellers who have NOT completed setup (setup strip shows normally) *(automated)*
- [✅] Seller dashboard still loads for sellers with zero items *(automated)*
- [✅] Admin panel still loads *(manual)*
- [✅] `_get_payout_percentage` untouched *(confirmed via git diff)*

---

**Sign-off date: 2026-04-14**
**Signed off by: Henry Russell**

---

## Spec #8 — Seller Rescheduling

**Sign-off status:** ✅ Signed off 2026-04-14

### Database & Migrations
- [x] `flask db migrate -m "add_seller_rescheduling"` runs with no errors
- [x] `flask db upgrade` runs with no errors
- [x] `reschedule_token` table exists with correct schema (token, pickup_id, seller_id, created_at, used_at, expires_at)
- [x] `shift_pickup` table has new columns: `rescheduled_from_shift_id`, `rescheduled_at`
- [x] `shift` table has new columns: `overflow_truck_number`, `reschedule_locked`
- [x] AppSettings seeded: `reschedule_token_ttl_days`, `reschedule_max_weeks_forward`, `reschedule_urgent_alert_days`
- [x] `User.moveout_date` column already exists — no migration error

### Move-Out Date — Pickup Modal
- [x] Open pickup week modal on dashboard — move-out date input appears below time preference buttons
- [x] Input is pre-populated if `moveout_date` is already set on the user
- [x] Save with a date — `User.moveout_date` updated in DB
- [x] Save with blank date — `User.moveout_date` set to NULL in DB
- [x] Modal does not break for sellers with no `ShiftPickup` yet

### Pickup Window Stat Cell — Post-Notification Upgrade
- [x] Before notification: cell shows "Wk 1 · Morning" format *(or equivalent)*
- [x] After notification (`notified_at IS NOT NULL`): cell shows specific date "Tue, Apr 29 · Morning"
- [x] "Reschedule →" link appears in cell when notified and shift not started
- [x] If seller is moved to a new shift and `notified_at` is cleared: cell reverts to week format
- [x] Clicking cell still opens pickup modal

### Pickup Modal — Post-Notification Read-Only State
- [x] When `notified_at IS NOT NULL`: week and time preference fields are read-only (not inputs)
- [x] "Need a different time? Reschedule →" link appears inside modal, links to `/seller/reschedule`
- [x] Move-out date input remains editable regardless of notification state

### Notify Sellers — Confirmation Dialog
- [x] "Notify Sellers" button has `data-unnotified-count` attribute with correct count
- [x] Clicking Notify Sellers triggers a JS confirmation dialog before submitting
- [x] Dialog copy references the correct seller count
- [x] "Go Back" cancels the form; "Send Notifications" proceeds
- [x] Sellers with `notified_at` already set do NOT receive a duplicate email *(existing idempotency)*

### Reschedule Token — Email Entry
- [x] After admin sends notifications, check a seller's email — reschedule CTA button present
- [x] Button URL contains a token: `https://usecampusswap.com/reschedule/<token>`
- [x] `reschedule_token` record exists in DB with correct `pickup_id`, `seller_id`, `expires_at`
- [x] Re-running Notify Sellers for a new seller — their token is fresh; existing seller token unchanged
- [x] Visit token URL without being logged in — reschedule page loads correctly

### Reschedule Page — Grid UI
- [x] Grid renders as day-columns × AM/PM rows *(mirrors worker availability style)*
- [x] Eligible slots appear as selectable cards; ineligible dates are greyed/disabled
- [x] Seller's current pickup cell is visually distinguished ("current" badge or style)
- [x] Clicking a card selects it (`.is-selected` class applied), deselects all others
- [x] Submit button starts disabled; enables once a card is selected
- [x] "Keep my current pickup →" link present, returns to dashboard
- [x] If zero eligible slots: grid hidden, amber callout shown with contact info

### Reschedule — Bidirectional Eligibility
- [x] Seller can select a slot earlier than their current pickup (if still in future)
- [x] Seller can select a slot later than their current pickup
- [x] Same-day AM→PM move is available when seller is on AM and PM shift exists today
- [x] Seller CANNOT select a date on or after their `moveout_date` (if set)
- [x] Locked shifts (`reschedule_locked=True`) do not appear as options
- [x] Shifts with `ShiftRun.status='in_progress'` do not appear as options

### Reschedule — Submission (Token Path)
- [x] Selecting an eligible slot and submitting moves `ShiftPickup.shift_id` to new shift
- [x] `pickup.truck_number` set to overflow truck (or truck 1 if none designated)
- [x] `pickup.stop_order` set to NULL on new shift
- [x] `pickup.rescheduled_from_shift_id` set to old shift ID
- [x] `pickup.rescheduled_at` set to current Eastern time
- [x] `pickup.notified_at` set to NULL
- [x] Token `used_at` set — token cannot be reused
- [x] Confirmation page shown with new shift label
- [x] Revisiting the used token URL shows "already used" error page

### Reschedule — Submission (Auth / Dashboard Path)
- [x] Visit `/seller/reschedule` as logged-in seller with a `ShiftPickup` — page loads with grid
- [x] Submitting a valid slot moves the pickup correctly (same checks as token path above)
- [x] Visit `/seller/reschedule` as seller with no `ShiftPickup` — 404

### Reschedule — Old Route Repacking
- [x] After reschedule, remaining stops on old shift have sequential `stop_order` values (no gaps)
- [x] Stops that had NULL `stop_order` before remain at the end after repacking
- [x] Rescheduled seller is gone from old shift stop list entirely

### Reschedule — Edge Cases
- [x] Expired token (manually set `expires_at` to past) → "link expired" error page
- [x] Selecting current shift → redirect to dashboard, "No changes made" flash
- [x] Shift starts mid-reschedule (ShiftRun created between GET and POST) → abort(400) or clean error

### Admin Ops — Overflow Truck
- [x] Each truck card on ops page has an "Overflow" toggle button
- [x] Clicking toggle sets `Shift.overflow_truck_number` to that truck; green "Overflow" badge appears
- [x] Clicking the active truck's toggle clears it (sets to NULL)
- [x] Only one truck per shift can be overflow at a time
- [x] Rescheduled seller lands on overflow truck; falls back to truck 1 if none set

### Admin Ops — Reschedule Lock
- [x] "Lock Rescheduling" button appears in shift header
- [x] Clicking it sets `reschedule_locked=True`; red "Rescheduling Locked" badge appears
- [x] Locked shift does not appear in any seller's reschedule slot grid
- [x] Clicking again unlocks it

### Admin Ops — Reschedule Activity Panel
- [x] Panel appears at bottom of ops page
- [x] "Added via Reschedule" section shows sellers who rescheduled onto this shift with old shift label + timestamp
- [x] "Moved Away" section shows sellers who left this shift with new shift label + timestamp
- [x] Each entry links to correct `/admin/seller/<id>`
- [x] Empty state shown when no reschedule activity

### Admin Ops — Stale Route Notice
- [x] Amber banner appears on ops page when any pickup has `rescheduled_at IS NOT NULL` and `stop_order IS NULL`
- [x] Banner disappears after "Order Route" is run and all stops have `stop_order` set

### Mover Shift View — Rescheduled Stop Notice
- [x] Amber notice appears above stop list when a rescheduled-in stop with NULL `stop_order` exists on that truck
- [x] Notice shows correct count if multiple rescheduled stops
- [x] Rescheduled stop appears at bottom of stop list (NULL stop_order sorts last)

### Admin Route Builder — Move-Out Date
- [x] Seller card in unassigned panel shows "Moves out: Apr 29" when `moveout_date` is set
- [x] Seller with no `moveout_date` shows no move-out line (no blank/null display)

### Auto-Assign — Move-Out Date Gate
- [x] Run auto-assign with a seller who has `moveout_date` set — seller is not placed on any shift on or after that date
- [x] If no valid shift exists before move-out date, seller appears in TBD with reason "No eligible shift before move-out date"
- [x] Seller with no `moveout_date` — auto-assign behavior unchanged

### `notified_at` Clear Rules
- [x] Move seller to a different shift via stop movement — `notified_at` is cleared
- [x] Reassign seller to a different truck on the same shift — `notified_at` is NOT cleared
- [x] Reorder stops (run "Order Route") — `notified_at` is NOT cleared

### Admin Alert Email
- [x] Reschedule a seller whose new shift is within 2 days — admin alert email sent
- [x] Check email: subject contains seller name and both shift labels
- [x] Body contains link to `/admin/seller/<id>`
- [x] Reschedule a seller whose new shift is > 2 days out — no email sent, ops panel only

### Regression Check
- [x] Seller dashboard loads normally for sellers with no `ShiftPickup`
- [x] Existing pickup week modal save (week + time preference) still works without `moveout_date`
- [x] "Notify Sellers" still works and sends correct email for sellers without a reschedule token yet
- [x] Admin ops page loads with no errors for shifts with no reschedule activity
- [x] Worker shift view loads normally for movers with no rescheduled stops
- [x] Auto-assign runs cleanly for sellers with no `moveout_date`
- [x] `_get_payout_percentage` untouched

---

**Sign-off date:** 2026-04-14
**Signed off by:** Henry Russell

## Spec #9 — SMS Notifications

**Sign-off status:** ✅ In production (42/42 automated tests passing)

---

### Migration & Schema

- [x] `flask db migrate -m "add_sms_and_no_show_fields"` runs with no errors
- [x] `flask db upgrade` runs with no errors
- [x] `User.sms_opted_out` column exists in DB, default False
- [x] `ShiftPickup.issue_type` column exists, nullable, no default
- [x] `ShiftPickup.no_show_email_sent_at` column exists, nullable DateTime
- [x] `RescheduleToken.revoked_at` column exists, nullable DateTime
- [x] AppSetting `sms_enabled` seeded with value `'true'`
- [x] AppSetting `sms_reminder_hour_eastern` seeded with value `'9'`
- [x] AppSetting `no_show_email_enabled` seeded with value `'true'`
- [x] AppSetting `no_show_email_hour_eastern` seeded with value `'18'`
- [x] Running migration twice (idempotent check) — no error, no duplicate columns

---

### `_send_sms` Helper — Guard Conditions

- [x] `user.phone = None` → returns False, no exception, no Twilio call
- [x] `user.phone = ''` → returns False, no exception
- [x] `user.sms_opted_out = True` → returns False, no Twilio call
- [x] AppSetting `sms_enabled = 'false'` → returns False for any user with valid phone
- [x] `TWILIO_ACCOUNT_SID` not set in env → returns False, logs warning, no crash
- [x] `TWILIO_AUTH_TOKEN` not set in env → returns False, logs warning, no crash
- [x] `TWILIO_FROM_NUMBER` not set in env → returns False, logs warning, no crash

### `_send_sms` Helper — Phone Normalization

- [x] `'4105551234'` (10 digits) → normalized to `'+14105551234'` before Twilio call
- [x] `'14105551234'` (11 digits, leading 1) → normalized to `'+14105551234'`
- [x] `'+14105551234'` (already E.164) → passed through unchanged
- [x] `'410-555-1234'` (dashes) → normalized to `'+14105551234'`
- [x] `'(410) 555-1234'` (parens/spaces) → normalized to `'+14105551234'`
- [x] `'555-1234'` (7 digits, unparseable) → returns False, logs warning, no crash
- [x] `'abcdefghij'` (non-numeric) → returns False, logs warning, no crash

---

### Notify Sellers — SMS Integration

- [x] Seller with phone + `notified_at = NULL` → `_send_sms` called once with scheduled confirmation message
- [x] Message body contains the shift day name (e.g. "Tuesday")
- [x] Message body contains the shift date (e.g. "Apr 29")
- [x] Message body contains the slot label ("AM" or "PM")
- [x] Message body contains "Reply STOP to opt out"
- [x] Seller with `phone = None` → email sent normally, `_send_sms` not called, no crash
- [x] Seller with `sms_opted_out = True` → email sent normally, `_send_sms` returns False, no crash
- [x] Seller with `notified_at` already set (already notified) → neither email nor SMS re-sent (existing idempotency)
- [x] Shift has 3 sellers: 2 with phone, 1 without → 2 SMS sent, 1 skipped, all 3 emails sent
- [x] Twilio env vars absent → emails send normally, SMS skipped, flash message still shows sent count

---

### Cron — SMS 24hr Reminder

- [x] POST to `/admin/cron/sms-reminders` with no `Authorization` header → 403
- [x] POST with wrong secret → 403
- [x] POST with correct `CRON_SECRET` and no shifts tomorrow → returns `{"sent": 0, "skipped": 0}`, status 200
- [x] Shift exists tomorrow (correct date), seller has phone + `notified_at` set, `status = 'pending'` → SMS sent, `sent` count = 1
- [x] Message body contains "tomorrow" and the shift date
- [x] Message body contains the AM/PM slot label
- [x] Message body contains "Reply STOP to opt out"
- [x] Seller has `notified_at = NULL` (never formally notified) → SMS NOT sent, `skipped` incremented
- [x] Seller has `phone = None` → skipped, `skipped` incremented, no crash
- [x] Seller has `sms_opted_out = True` → skipped, `skipped` incremented
- [x] Seller's stop has `status = 'issue'` → skipped (don't remind for flagged stops)
- [x] Shift is tomorrow but `is_active = False` → sellers on that shift not messaged
- [x] Shift is today (not tomorrow) → sellers not messaged by this cron
- [x] Shift is 2 days out → sellers not messaged
- [x] Multiple shifts tomorrow (AM + PM) → sellers on both shifts messaged correctly
- [x] Cron runs twice same day → same sellers messaged twice (reminder cron has no idempotency guard — it's expected to run once daily via Render schedule; document this)

---

### Stop Card — Seller Phone Number (UI)

- [x] Mover shift view stop card contains `<a href="tel:...">` element with seller's phone *(UI)*
- [x] Tapping phone link on mobile opens native dialer *(UI — manual)*
- [x] Seller with `phone = None` → "No phone on file" text shown in muted color, no `<a>` tag, no broken link *(UI)*
- [x] Phone number visible without expanding or tapping anything — always shown on stop card *(UI)*

---

### Issue Flagging — `issue_type` Picker (UI + Backend)

- [x] Tapping "Flag Issue" on a stop card reveals a two-option picker before submission *(UI)*
- [x] Picker shows exactly two options: "Seller wasn't home" and "Item or access problem" *(UI)*
- [x] Notes textarea still present for both options *(UI)*
- [x] Selecting neither option and submitting → form does not submit (client-side validation) *(UI)*
- [x] Submit with "Seller wasn't home" → POST includes `issue_type=no_show`
- [x] Submit with "Item or access problem" → POST includes `issue_type=other`
- [x] `crew_shift_stop_update` with `status=issue, issue_type=no_show` → `pickup.issue_type = 'no_show'` saved in DB
- [x] `crew_shift_stop_update` with `status=issue, issue_type=other` → `pickup.issue_type = 'other'` saved in DB
- [x] `crew_shift_stop_update` with `status=issue` but no `issue_type` field → defaults gracefully (either `'other'` or rejected with 400 — document which)
- [x] Existing `notes` field still saved correctly alongside `issue_type`
- [x] Ops page issue banner still appears for flagged stops *(UI — regression)*

---

### Issue Flagging — Token Extension (no_show)

- [x] Seller has active token (`used_at=NULL, revoked_at=NULL`); stop flagged `no_show` → `token.expires_at` extended by `reschedule_token_ttl_days` from now
- [x] Extended `expires_at` is strictly greater than the original `expires_at`
- [x] Stop flagged `other` → `token.expires_at` unchanged
- [x] Stop flagged `no_show` but seller has no token (edge case) → logged warning, no crash, `issue_type` still saved
- [x] Stop flagged `no_show` but token already `used_at` set (seller already rescheduled) → token not modified, no crash
- [x] Stop flagged `no_show` but token already `revoked_at` set → token not modified, no crash

---

### Stop Revert — `issue_type` Clearing

- [x] Revert stop from `issue` to `pending` → `pickup.issue_type` set to `NULL`
- [x] Revert does NOT clear `pickup.no_show_email_sent_at` (even if set)
- [x] Revert still clears `pickup.notes` per existing behavior (confirm unchanged)
- [x] Re-flag reverted stop as `no_show` → `issue_type` saved again, but no second email sent (`no_show_email_sent_at` still set from first flag)

---

### Route Started SMS (`crew_shift_start`)

- [x] Mover on truck 2 starts shift → all pending sellers on truck 2 receive SMS
- [x] Sellers on truck 1 and truck 3 do NOT receive SMS
- [x] Message body contains "started" and "today"
- [x] Message body contains "we'll text you again"
- [x] Seller on mover's truck with `status = 'completed'` (already done) → NOT messaged
- [x] Seller on mover's truck with `status = 'issue'` → NOT messaged
- [x] Seller with `phone = None` → skipped, no crash, other sellers still messaged
- [x] Seller with `sms_opted_out = True` → skipped, no crash
- [x] `shift.run` already exists (ShiftRun present) → `crew_shift_start` returns early, no new ShiftRun created, no SMS sent
- [x] `crew_shift_complete_retroactive` for a past shift → no SMS sent to any seller

---

### You're Next SMS + Token Revocation (`crew_shift_stop_update`)

- [x] Mark stop 1 of 3 complete → stop 2's seller receives "You're up next" SMS
- [x] Mark stop 2 of 3 complete → stop 3's seller receives "You're up next" SMS
- [x] Mark stop 3 of 3 (last stop) complete → no SMS sent, no crash
- [x] Single-stop truck: complete the only stop → no "you're next" SMS sent, no crash
- [x] Stop 2 has `issue_type = 'no_show'` → skip stop 2, send SMS to stop 3's seller instead
- [x] Stop 2 has `issue_type = 'other'` → skip stop 2, send SMS to stop 3's seller instead
- [x] Stop 2 and stop 3 both have `issue_type` set → no SMS sent (no clean pending stops), no crash
- [x] Next seller has `phone = None` → SMS skipped, no crash
- [x] Next seller has `sms_opted_out = True` → SMS skipped, no crash
- [x] Stop ordering respects `stop_order` (ascending, nulls last) — stop with `stop_order=2` messaged before `stop_order=3`
- [x] Stops with `NULL stop_order` come after ordered stops when determining "next"

### Token Revocation on Completion

- [x] Stop marked complete; seller has active token → `token.revoked_at` set to a non-null datetime
- [x] `revoked_at` is a naive datetime (no tzinfo) consistent with other token datetimes
- [x] Stop marked complete; seller's token has `used_at` already set (seller rescheduled themselves) → `revoked_at` NOT set, `used_at` unchanged
- [x] Stop marked complete; seller has no token → no crash, completion proceeds normally
- [x] Stop marked complete; seller has multiple tokens (edge) → all active (unused, unrevoked) tokens get `revoked_at` set
- [x] `picked_up_at` still set correctly on completion (regression — token revocation must not interfere)

---

### Cron — No-Show Recovery Emails

- [x] POST to `/admin/cron/no-show-emails` with no `Authorization` header → 403
- [x] POST with wrong secret → 403
- [x] `no_show_email_enabled = 'false'` → returns `{"sent": 0, "skipped": N}`, no emails sent
- [x] No stops flagged `no_show` today → returns `{"sent": 0, "skipped": 0}`, no error
- [x] Stop flagged `no_show`, `no_show_email_sent_at = NULL`, shift date = today, active token exists → email sent via Resend
- [x] Email recipient is `pickup.seller.email`
- [x] Email subject contains seller's first name
- [x] Email subject contains "missed" or "sorry"
- [x] Email body contains a reschedule link with the token string (`/reschedule/<token>`)
- [x] Email body contains "reschedule" CTA
- [x] `no_show_email_sent_at` set on the pickup after email sends
- [x] Cron runs again immediately → same pickup NOT emailed again (`no_show_email_sent_at` guard)
- [x] Stop flagged `no_show` but `no_show_email_sent_at` already set → skipped
- [x] Stop flagged `no_show`, shift date is tomorrow (future) → NOT emailed today
- [x] Stop flagged `no_show`, shift date was yesterday → emailed (catches any missed previous-day runs)
- [x] Seller has `sms_opted_out = True` → email still sent (opted out of SMS, not email)
- [x] Seller's token has `used_at` set (already rescheduled) → skipped (`skipped` incremented); no second email
- [x] Seller's token has `revoked_at` set → skipped; no email
- [x] Seller has no token at all → skipped, warning logged, `skipped` incremented, no crash
- [x] Multiple no-show stops on same shift → each seller gets their own email
- [x] Response JSON `sent + skipped` equals total no-show stops processed

---

### Inbound Webhook (`/sms/webhook`)

- [x] POST with valid Twilio signature, body `STOP`, matching phone → `user.sms_opted_out = True` in DB, returns 200
- [x] POST with valid signature, body `STOPALL` → `sms_opted_out = True`
- [x] POST with valid signature, body `UNSUBSCRIBE` → `sms_opted_out = True`
- [x] POST with valid signature, body `CANCEL` → `sms_opted_out = True`
- [x] POST with valid signature, body `END` → `sms_opted_out = True`
- [x] POST with valid signature, body `QUIT` → `sms_opted_out = True`
- [x] POST with valid signature, body `START` → `sms_opted_out = False`
- [x] POST with valid signature, body `UNSTOP` → `sms_opted_out = False`
- [x] POST with valid signature, body `YES` → `sms_opted_out = False`
- [x] Body with mixed case (e.g. `Stop`, `stop`) → treated same as uppercase
- [x] Body with leading/trailing whitespace (e.g. `  STOP  `) → still matches
- [x] POST with invalid Twilio signature → 403
- [x] POST with missing `X-Twilio-Signature` header → 403
- [x] `From` number matches no User in DB → 200 returned, warning logged, no crash, no DB write
- [x] `From` number in format `+14105551234` matches user stored as `4105551234` (normalization works both ways)
- [x] Response Content-Type is `text/xml`
- [x] Response body is valid TwiML: contains `<Response>` with no nested verb (empty response)
- [x] Route accessible without login (no redirect to login page)

---

### `/reschedule/<token>` — `revoked_at` Error State

- [x] Token with `revoked_at` set → page renders "already completed" message (not a 404, not "already rescheduled")
- [x] "Already completed" message is distinct from "already rescheduled" (`used_at`) message
- [x] "Already completed" message is distinct from "link expired" message
- [x] Token with `used_at` set (but not `revoked_at`) → existing "already rescheduled" message unchanged
- [x] Token expired (`expires_at` in past, neither `used_at` nor `revoked_at` set) → existing "link expired" message unchanged
- [x] Valid token (no `used_at`, no `revoked_at`, not expired) after no-show flag → reschedule grid loads normally, seller can pick new slot

---

### Admin Settings Page

- [x] Super admin can see and edit `sms_enabled` AppSetting *(UI)*
- [x] Super admin can see and edit `sms_reminder_hour_eastern` *(UI)*
- [x] Super admin can see and edit `no_show_email_enabled` *(UI)*
- [x] Super admin can see and edit `no_show_email_hour_eastern` *(UI)*
- [x] Non-super-admin cannot access these settings *(regression)*

---

### Regression

- [x] Existing "Notify Sellers" email content and subject unchanged — SMS is additive only
- [x] `admin_shift_notify_sellers` still sets `notified_at` and `Shift.sellers_notified` correctly
- [x] `crew_shift_start` still creates `ShiftRun` with correct `started_at` and `started_by_id`
- [x] `crew_shift_stop_update` with `status=completed` still sets `pickup.completed_at` and `item.picked_up_at`
- [x] `crew_shift_stop_revert` still works and resets `pickup.status` to `'pending'`
- [x] Ops page issue banner still shows for stops with `issue_type = 'no_show'` and `'other'`
- [x] Ops page still loads with no errors when no stops are flagged
- [x] Spec #8 `/reschedule/<token>` flow (used_at, expired) still works for tokens without `revoked_at`
- [x] Spec #8 `/seller/reschedule` (authenticated path) unaffected
- [x] Seller dashboard loads normally for sellers with and without `ShiftPickup`
- [x] Admin panel loads normally
- [x] Worker shift view loads normally for movers with no stops
- [x] `_get_payout_percentage` untouched — confirm via `git diff` that function body is unchanged

---

**Sign-off date:** In production as of ~2026-04-27
**Signed off by:** Henry Russell (production operation)

## Admin UI Redesign (feature_admin_redesign.md)

**Sign-off status:** ✅ In production
**Automated tests:** 69/69 route planning + 42/42 SMS passing

> Items marked [✅] are covered by passing automated tests or confirmed at build time.
> Items marked [ ] require your eyes on the running app.

### Migration & Schema
- [✅] `flask db upgrade` runs cleanly — `admin_redesign_shift_last_notified` applied
- [✅] `shift` table has new `last_notified_at` (DateTime, nullable) column
- [✅] AppSettings `pickup_week_start` and `pickup_week_end` seeded with empty string defaults
- [ ] Verify in DB: `SELECT last_notified_at FROM shift LIMIT 5;` — all NULL until Notify Sellers runs

### Shell Layout (`admin_layout.html`)
- [ ] Visit `/admin/ops` as admin — 52px sidebar visible on left with all icons
- [ ] Hover each icon — tooltip appears with label name
- [ ] Active tab icon has sage/green background; others are muted
- [ ] Resize to mobile (≤768px) — sidebar collapses to horizontal top bar, icons still visible
- [ ] Admin nav in header now shows single "Admin" link to `/admin/ops` (not "Admin Panel" + "Routes")

### Redirects
- [ ] Visit `GET /admin` as admin — 302 redirect fires immediately to `/admin/ops`
- [ ] Visit `GET /admin/routes` — 302 to `/admin/ops`
- [ ] Visit `GET /admin/approve` — 302 to `/admin/items?view=approve`
- [ ] Visit `GET /admin/settings/route` as super admin — 302 to `/admin/settings#route`
- [ ] Visit `GET /admin/storage` as super admin — 302 to `/admin/settings#storage`
- [ ] POST to `/admin` (existing toggle forms) still works without redirect
- [ ] POST to `/admin/settings/route` (existing save form) still works without redirect

### Ops Tab (`/admin/ops`)
- [ ] Page loads — three-zone layout: shift list (left), truck cards (center), unassigned panel (right)
- [ ] Shift list shows all shifts grouped by week with "Week of [Month Day]" headers
- [ ] Clicking a shift row navigates to `?shift_id=<id>` — browser back button works
- [ ] Active shift row highlighted in sage green
- [ ] Shift rows show correct slot badges (amber AM, blue PM)
- [ ] Unnotified count badge appears ("X new") when sellers added since last notify
- [ ] "Notified ✓" checkmark shows after notify runs with no new sellers
- [ ] Shift with no stops shows muted "X trucks · Y stops" text
- [ ] "Week overview →" link at bottom of panel links to schedule builder for that week
- [ ] No shifts exist → empty state with "Generate shifts in Settings →" link

### Ops Tab — Truck Cards
- [ ] Each truck card shows: "Truck N" label, storage location chip (green assigned / amber unassigned), capacity bar, unit count "X/Yu"
- [ ] Capacity bar is green ≤75%, amber 75–100%, red >100%
- [ ] "View stops" button on every truck card opens the truck detail drawer
- [ ] Stop list shows seller name, address, stop order circle, badges ("new" amber, "moved" blue)
- [ ] "new" badge appears on stops created after last notify (or when never notified)
- [ ] "moved" badge appears on rescheduled-in stops
- [ ] Pre-shift stop list: "Re-order route", "View map", "Assign unit" buttons in footer
- [ ] Live state: when ShiftRun exists, truck card shows "In progress" or "Complete" pill + live summary row
- [ ] Live summary row shows: stops done counter, total items, current stop name
- [ ] Issue alert strip appears in amber when `status='issue'` stop exists on that truck

### Ops Tab — Top Bar
- [ ] "Add Truck" → form POST → page reloads with new truck card
- [✅] "Order Routes" → fetch POST to `/admin/crew/shift/<id>/order` → page reload (redirect to ops)
- [ ] "Order Routes" button shows spinner during ordering
- [✅] "Notify Sellers" → confirmation dialog → POST → page reload
- [ ] Notify dialog says "Send pickup confirmation to X unnotified sellers?"
- [✅] `Shift.last_notified_at` is set in DB after notify runs
- [ ] Alert bar appears (amber) when `unnotified_count > 0` and `sellers_notified=True`
- [ ] "Re-order & notify" in alert bar chains order then notify (both fetch, page reload after)

### Ops Tab — Unassigned Panel
- [ ] Panel shows sellers grouped by cluster label
- [ ] Only sellers matching shift slot are shown by default (morning→AM, afternoon→PM)
- [ ] Seller card shows name, cluster label, unit count, week, AM/PM pref badge
- [ ] Orange dot on seller cards joined in last 24h
- [ ] Clicking a seller card opens inline assign form with shift+truck selector
- [ ] "Show all unassigned" checkbox reveals dimmed slot-unmatched sellers
- [ ] "Auto-Assign" button at top → POST `/admin/routes/auto-assign` → page reload
- [✅] Auto-assign now uses cluster-first sort (partner buildings → dorms → proximity → Unlocated)
- [ ] Empty panel state: "All eligible sellers are assigned" with green checkmark

### Truck Detail Modal
- [ ] Clicking "View stops" on a truck card opens 480px right-side drawer
- [ ] Drawer fetched via `GET /admin/ops/truck-detail?shift_id=<id>&truck=<n>`
- [ ] Drawer shows: truck header, capacity bar, assigned movers, full stop list
- [ ] Stop list shows status circles: gray=pending, green=completed (with time), red=issue (with type)
- [ ] Pre-shift: "Remove" button visible on pending stops, submits to remove route, page reloads
- [ ] Close: X button, Escape key, overlay click all close drawer
- [ ] 403 returned (not redirect) when non-admin fetches partial

### Items Tab (`/admin/items`)
- [ ] Visit `/admin/items` — page loads with stats bar (Total, Pending, Available, Sold)
- [ ] "All Items" tab active by default; "Approval Queue" tab visible for super admins
- [ ] Filter bar: category dropdown, seller email field, item title field — submit filters table
- [ ] "Clear" link resets all filters
- [ ] Item table shows: description, seller (→ panel), category, price, status pill, date, payout
- [ ] Seller name click → slide-out seller profile panel opens (existing panel, unchanged)
- [ ] Store controls section: toggle (collapsible, collapsed by default)
- [ ] Store controls shows pickup period, reserve-only, shop teaser toggles + store open date
- [ ] Approval Queue tab shows pending items with price input + Approve / Reject / Need Info buttons
- [ ] Visit `GET /admin/approve` — redirects to `/admin/items?view=approve`

### Sellers Tab (`/admin/sellers`)
- [ ] Visit `/admin/sellers` — page loads with seller table
- [ ] Search bar filters table client-side by name or email (no page reload)
- [ ] Table columns: Name, Email, Phone, Pickup week, Items, Payout rate, Days since joined
- [ ] Seller name → slide-out seller profile panel
- [ ] "Pickup nudge" collapsible shows sellers with items but no pickup week
- [ ] "Remind Selected" and "Remind All" buttons visible in nudge section
- [ ] Free-tier queue collapsible shows pending free sellers with Approve/Reject buttons
- [ ] All existing nudge + free-tier POST routes still work unchanged

### Crew Tab (`/admin/crew`)
- [ ] Visit `/admin/crew` — page loads with pending apps + approved workers sections
- [ ] Pending app row is clickable to expand → shows availability grid + why blurb
- [ ] Availability grid shows colored AM/PM cells (green=available, red=unavailable)
- [ ] Approve / Reject buttons work → existing POST routes unchanged
- [ ] Approved workers table shows name, email, role badge, shifts completed count

### Settings Tab (`/admin/settings`)
- [ ] Visit `/admin/settings` as super admin — page loads with all 9 sections
- [ ] Visit as regular admin — 403
- [ ] Quick nav links at top scroll to correct anchor sections
- [ ] **Pickup window section:** date inputs save via POST; "Generate shifts" button shows confirmation dialog
- [ ] Generate shifts: creates AM+PM shift records for each date in range; idempotent (re-run shows "Generated 0 shifts")
- [ ] Pickup window start/end saved correctly in AppSettings
- [ ] **Route & capacity:** saves truck_raw_capacity, buffer %, windows, maps key, category unit sizes
- [ ] **Storage locations:** existing locations listed with active/inactive dots; create form works
- [ ] **SMS notifications:** sms_enabled toggle, hour fields save *(NOTE: there is no "Referral program" section in `templates/admin/settings.html`, and no `/admin/settings/referral` route exists — referral settings are not edited here. Section anchors present: shop, pickup-week-override, route, storage, sms, user-management, exports, mass-email, campus-directors, db-reset)*
- [ ] **User management:** current admin list shown; grant/revoke admin by email works
- [ ] **Data exports:** CSV download buttons work; preview links load
- [ ] **Mass email:** form present; test-only checkbox visible
- [ ] **Database reset:** requires typing "reset database"; dangerous confirm dialog

### Modified Templates — Admin Shell
- [ ] `/admin/crew/shift/<id>/ops` (shift_ops.html) — sidebar visible, active tab = Ops
- [ ] `/admin/schedule` (schedule_index.html) — sidebar visible, active tab = Schedule
- [ ] `/admin/schedule/<week_id>` (schedule_week.html) — sidebar visible, active tab = Schedule
- [ ] `/admin/settings/route` redirects to `/admin/settings#route`
- [ ] `/admin/storage/<id>` (storage_detail.html) — sidebar visible, active tab = Settings
- [ ] `/admin/intake/flagged` (intake_flagged.html) — sidebar visible, active tab = Items
- [ ] `/admin/crew/shift/<id>/intake` (shift_intake_log.html) — sidebar visible, active tab = Ops
- [ ] `/admin/payouts` (payouts.html) — sidebar visible, active tab = Payouts

### Regression Check
- [✅] 69/69 route planning tests still passing
- [✅] 42/42 SMS notification tests still passing
- [ ] `/crew/shift/<id>` mover shift view — loads normally, no sidebar, crew-only content unchanged
- [ ] Seller dashboard (`/dashboard`) — loads normally, zero admin shell visible
- [ ] Stripe webhook still responds (unchanged)
- [ ] Seller reschedule flow (`/reschedule/<token>`) — unchanged
- [ ] Worker application (`/crew/apply`) — unchanged
- [✅] `admin_shift_notify_sellers` still sets `notified_at` on each pickup AND `sellers_notified=True` on shift
- [✅] `admin_shift_notify_sellers` now also sets `last_notified_at` on shift

---

**Sign-off date:** In production as of ~2026-04-27
**Signed off by:** Henry Russell (production operation)

---

## Feature: Driver Quick Capture

**Sign-off status:** ⬜ Not yet signed off
**Spec files:** `feature_quick_capture.md`, `feature_quick_capture_ux_fixes.md`

### Database & Schema
- [ ] `flask db upgrade` runs with no errors
- [ ] `User` table has `is_internal_account` column (Boolean, default False)
- [ ] `InventoryItem` table has `is_quick_capture` column (Boolean, default False)
- [ ] `InventoryItem` table has `quick_capture_shift_id` column (Integer, nullable FK → shift)
- [ ] `InventoryItem` table has `captured_by_id` column (Integer, nullable FK → user)
- [ ] Internal account exists: `SELECT email, is_internal_account FROM "user" WHERE email = 'internal@campusswap.com'` → row exists with `is_internal_account = true`

### Crew Dashboard Entry Point
- [ ] Visit `/crew` as approved worker — "Quick Capture" button visible above schedule section
- [ ] Tap Quick Capture — modal opens with camera activating immediately (rear camera on mobile)
- [ ] Seller dropdown shows only "Campus Swap" (no shift context)
- [ ] No shift context — save creates item with `quick_capture_shift_id = NULL`

### Shift View Entry Point
- [ ] Visit `/crew/shift/<id>` as assigned mover with an active shift — "Quick Capture" button visible in header area
- [ ] Tap Quick Capture — modal opens, seller dropdown pre-selects current active stop's seller
- [ ] If all stops are completed, seller dropdown defaults to Campus Swap
- [ ] Seller dropdown includes all sellers on this truck's route in stop_order sequence

### Modal — Camera & Capture
- [ ] Camera preview appears (rear camera) on HTTPS — video element streams
- [ ] On plain HTTP or camera denied — file input fallback appears with "Tap to Take Photo"
- [ ] Tap "Take Photo" — thumbnail replaces live preview, "Retake" button appears
- [ ] Notes textarea appears below thumbnail (hidden before photo taken)
- [ ] "Save Item →" button is disabled until a photo has been taken
- [ ] Tap "Retake" — live camera preview resumes, thumbnail hidden, notes hidden and cleared
- [ ] Close (×) or Cancel — modal closes, camera stream stopped

### Modal — State Reset
- [ ] Take a photo and save it — modal closes with "Item #XXXX captured" flash on button
- [ ] Reopen the modal — no "Saving…" text, no old thumbnail, no old notes, Save button disabled
- [ ] Partially fill a capture (take photo, add note) then close without saving — reopen modal shows clean empty state

### Save & Immediate Feedback
- [ ] Take a photo, select seller, add a note, tap Save — JSON response `{success: true, item_id: N}`
- [ ] Stop list (#stop-list) updates immediately (before 30s refresh cycle) — new QC thumbnail visible on seller's stop card
- [ ] `InventoryItem` record in DB: `is_quick_capture=True`, `status='pending_valuation'`, `picked_up_at` set, `long_description` = note text (or NULL if empty)
- [ ] `captured_by_id` on the item matches the worker who captured it

### Stop Card Photo Strip
- [ ] QC items for the current seller/shift appear as 64×64 thumbnails below the stop card
- [ ] Each thumbnail shows the item ID badge in bottom-left corner
- [ ] `×` button visible in top-right of each thumbnail
- [ ] 30-second auto-refresh still works — stop list refreshes silently, QC thumbnails persist

### Crew Delete (✕ on stop card)
- [ ] Tap `×` on a QC thumbnail — confirmation dialog appears ("This cannot be undone")
- [ ] Confirm — thumbnail removed from stop card immediately, no page reload
- [ ] Item record gone from DB, photo file gone from disk
- [ ] Decline — nothing happens
- [ ] Log in as a different worker, attempt to delete another worker's capture via direct POST → 403 returned

### Admin Queue (`/admin/items/needs_info`)
- [ ] Visit `/admin/items/needs_info` as admin — page loads with Quick Captures table
- [ ] All `is_quick_capture=True` items with status `pending_valuation` or `needs_info` appear
- [ ] Columns: ID badge, photo thumbnail, seller name, shift date + slot (or "No shift"), date captured, Edit button, Approve button, Delete button
- [ ] "Quick Captures" link visible in admin nav with count badge matching queue size
- [ ] Count badge is 0 when queue is empty

### Admin Approve Button
- [ ] Click Approve on a row — row disappears from table immediately, no page reload
- [ ] Item in DB: `status='available'`
- [ ] No price or description required to approve
- [ ] Non-quick-capture items cannot be approved via this route (400 returned)

### Admin Delete Button
- [ ] Click Delete on a row — confirmation dialog ("Permanently delete… cannot be undone")
- [ ] Confirm — row removed from table, item + photo gone from DB and disk
- [ ] Decline — nothing happens

### Notes → `long_description`
- [ ] Enter a note in the modal before saving — check item in admin edit view: `long_description` contains the note text
- [ ] Save with no note — `long_description` is NULL

### Standard Approval Queue Isolation
- [ ] Visit `/admin/items?view=approve` — no quick-capture items appear in the list
- [ ] Pending approval count badge in admin nav shows 0 when only QC items are `pending_valuation`
- [ ] Trigger the digest email manually — email body does not reference any QC items

### Seller Dashboard (Regression)
- [ ] Quick-capture item with `status='available'` appears normally on seller's dashboard item grid — no special messaging or pending state
- [ ] Seller dashboard loads normally for sellers with no QC items

### Regression Check
- [ ] Normal `add_item` flow unaffected — no `is_quick_capture` flag set on manually added items
- [ ] Standard approval queue (`/admin/items?view=approve`) still works for regular items
- [ ] 30-second stop list auto-refresh still works on `/crew/shift/<id>`
- [ ] Existing stop card data (address, navigate button, item count, status badge) unchanged

---

**Sign-off date:**
**Signed off by:**

---

## Feature: Approval Queue Modal Flow

**Sign-off status:** ⬜ Not started
**Spec file:** `feature_approval_queue_modal.md`

### Card Grid
- [ ] Visit `/admin/items?view=approve` — approval queue cards load without inline forms or action buttons
- [ ] Each card shows thumbnail, title, seller name, date, category, and suggested price badge (if present)
- [ ] Hovering a card shows hover lift effect and "Click to review" hint arrow
- [ ] Clicking anywhere on the card opens the modal (not a new tab)
- [ ] Clicking the seller name on a card opens the seller profile panel without opening the modal

### Modal — Load and Display
- [ ] Clicking a card shows the modal immediately with a spinner
- [ ] Spinner replaced by full item detail: gallery, title, category, quality, date added, long description
- [ ] Seller name link in modal opens the existing seller profile panel (both panels can be open simultaneously)
- [ ] Suggested price callout appears when item has a `suggested_price`
- [ ] Price input pre-filled with `suggested_price` value when present; empty otherwise
- [ ] Gallery prev/next buttons work; counter shows "1 / N" updating correctly
- [ ] Items with no gallery photos show a placeholder icon (no JS errors)
- [ ] Escape key closes modal without any action
- [ ] Clicking the overlay (outside the panel) closes modal without any action
- [ ] × close button closes modal without any action

### Approve Action
- [ ] Click Approve with a valid price — fetch POST fires, modal closes, card removed from grid
- [ ] Item appears as `status='available'` in DB after approval
- [ ] Click Approve with empty price field — inline error shown ("Please set a price"), modal stays open
- [ ] Page count badge in admin nav decrements after successful approval
- [ ] No new tab or page navigation occurs

### Reject Action
- [ ] Click Reject — confirmation dialog appears before firing the request
- [ ] Confirm reject — fetch POST fires, modal closes, card removed from grid
- [ ] Item appears as `status='rejected'` in DB after rejection
- [ ] Cancel reject — modal stays open with no change

### Need Info Action
- [ ] Click Need Info — footer swaps to Need Info sub-panel (reason checkboxes + note textarea + Cancel/Send)
- [ ] Click Cancel — sub-panel hides, footer returns, no request fired
- [ ] Submit with no reasons and no note — inline error shown, no request fired
- [ ] Submit with a reason checked — fetch POST fires, modal closes, card removed from grid
- [ ] Item no longer appears in approval queue after Need Info (status changed to `needs_info`)
- [ ] Item appears in quick-capture/needs_info queue at `/admin/items/needs_info`

### Empty State
- [ ] After approving/rejecting all cards: empty-queue state message shown ("No items pending approval" or equivalent)
- [ ] No JS errors when last card is removed from DOM

### Regression
- [ ] "All Items" sub-tab (`/admin/items?view=all`) completely unchanged — no new modal, no missing forms
- [ ] Quick Captures queue (`/admin/items/needs_info`) completely unchanged
- [ ] Seller profile panel (slide-out drawer) still works on "All Items" tab
- [ ] Stats bar counts unchanged
- [ ] No new tabs opened at any point in the approval flow

---

**Sign-off date:**
**Signed off by:**

---

## Feature: Campus Director Tutorial

**Sign-off status:** ⬜ Not yet signed off
**Built:** 2026-05-21

### Database & Schema
- [ ] `flask db upgrade` runs with no errors
- [ ] `tutorial_session` table exists with columns: `id`, `user_id`, `step`, `started_at`, `completed_at`, `tutorial_week_id`, `last_retake_at`, `is_retaking` *(field is `step`, not `current_step` — verified models.py)*
- [ ] `user` table has `is_campus_director` column (Boolean, default False)
- [ ] At least one user has `is_campus_director=True` in DB (manually created or seeded)

### Role Switcher — Header Pill
- [ ] Log in as a campus director — role switcher pill visible in header nav between dashboard link and user icon
- [ ] Pill shows "Seller" and "Admin" buttons; active button highlighted
- [ ] On `/dashboard` and all non-admin pages — "Seller" button is active
- [ ] On `/admin/*` pages — "Admin" button is active
- [ ] Click "Admin" button — redirects to `/admin/ops` or tutorial start, CD view switches
- [ ] Click "Seller" button — redirects to `/dashboard`, CD sees seller view
- [ ] Role switcher NOT visible for regular sellers or admins who are not campus directors
- [ ] Header does not clip or overflow horizontally with pill present (scroll left/right on mobile)

### CD Seller View — Dashboard
- [ ] With `cd_view='seller'` in session, visit `/dashboard` as a CD — page loads (no redirect to admin)
- [ ] With `cd_view='seller'`, visiting `/dashboard` as a CD who has no items does NOT redirect to `/onboard`
- [ ] Seller dashboard renders normally with item grid (empty state or items)
- [ ] Role switcher pill shows "Seller" as active

### Tutorial Entry
- [ ] Visit `/admin/tutorial` as a campus director — welcome page renders *(route is `/admin/tutorial` → `admin_tutorial_welcome`, not `/admin/tutorial/welcome`)*
- [ ] Visit `/admin/tutorial` as a non-CD user — 403 or redirect
- [ ] Click "Start Tutorial" — POST to `/admin/tutorial/start`, creates `TutorialSession` record in DB with `step=0`
- [ ] Starting tutorial again (already started) does NOT create a duplicate `TutorialSession` row

### Tutorial Steps 0–5 (Orientation)
- [ ] Each step page loads without error when accessed in sequence
- [ ] Advancing a step (clicking "Next") increments `TutorialSession.step` in DB
- [ ] Navigating away and returning drops the CD back at their current step (not step 0)
- [ ] Back/forward browser navigation does not corrupt step state

### Tutorial Steps 6–8 (Functional Actions)
- [ ] Step 6: page shows sellers assigned to the tutorial shift (seed data visible in stops list)
- [ ] Step 7: "Re-order route" action executes and `stop_order` values are updated on tutorial pickups
- [ ] Step 8: "Notify sellers" action executes — no real SMS/emails sent (tutorial sellers are flagged)
- [ ] Each step action advances `TutorialSession.step` to the next value *(per models.py, step 7 = complete)*

### Tutorial Seed Fixtures
- [ ] Fixture data uses `is_tutorial=True` on `ShiftWeek` and `is_tutorial_user=True` on worker accounts
- [ ] Tutorial sellers and stops do NOT appear in the real ops panel when a non-tutorial shift is selected
- [ ] Tutorial workers do NOT appear in Crew HQ approved workers list
- [ ] Re-starting the tutorial (POST `/admin/tutorial/start` again) resets fixtures to canonical state

### Tutorial Completion
- [ ] Advancing past the final step — `TutorialSession.completed_at` set in DB *(models.py marks step 7 as complete; flow may differ from original 0–9 numbering)*
- [ ] Completion page (`/admin/tutorial/complete`) renders correctly
- [ ] "Go to Admin Panel" link on completion page navigates to `/admin/ops`
- [ ] Completed tutorial: visiting welcome page again shows completion state, not a new tutorial start

### Tutorial Exit
- [ ] "Exit tutorial" link available on all tutorial step pages
- [ ] Clicking exit — confirmation dialog or direct redirect to `/admin/ops`
- [ ] `TutorialSession.step` preserved (not reset) on exit — can resume where left off

### Auth Guard Audit — CD Access to Ops Routes
- [ ] As a campus director in admin view, open `/admin/ops` → page loads (no 403)
- [ ] As CD, trigger quick-remove on a crew member (Crew HQ) — 200, not 403
- [ ] As CD, trigger override availability on a worker — 200, not 403
- [ ] As CD, add truck to a shift — 200, not 403
- [ ] As CD, remove truck from a shift — 200, not 403
- [ ] As CD, reorder a stop — 200, not 403

### Regression Check
- [ ] Regular seller `is_campus_director=False` — role switcher pill not visible in header
- [ ] Admin (`is_admin=True`, `is_campus_director=False`) — role switcher pill not visible
- [ ] `/dashboard` for a regular seller with no items still redirects to `/onboard`
- [ ] All 69/69 route planning tests still pass (`pytest test_route_planning.py`)
- [ ] All 42/42 SMS tests still pass (`pytest test_sms_notifications.py`)

---

**Sign-off date:**
**Signed off by:**

---

## Feature: Required Unit Assignment with Visual Picker

**Sign-off status:** ⬜ Not yet signed off
**Built:** 2026-05-29
**Spec file:** `feature_required_unit_assignment.md`

### Ops Page — Unit Chip Buttons
- [ ] Open `/admin/ops` on a shift with an assigned unit — truck card shows green chip with edit icon instead of dropdown
- [ ] Truck card with no unit assigned shows amber "+ Assign unit" chip
- [ ] Clicking the chip opens the unit picker modal (not a dropdown)

### Unit Picker Modal
- [ ] Modal loads with card grid of active StorageLocations
- [ ] Each card shows name, item count, capacity battery bar
- [ ] Full units are visually distinguished
- [ ] Selecting a card closes the modal and saves the unit (green chip appears)
- [ ] Modal can be dismissed without selecting (chip state unchanged)

### Unit Required Gate
- [ ] Try adding a seller stop to a truck with 0 stops and no unit assigned — unit picker modal opens instead of adding stop
- [ ] After assigning a unit via the picker, the stop add retries and succeeds
- [ ] Adding a stop to a truck that already has stops does NOT trigger the unit gate (even if unit later unassigned)

### Driver Shift View
- [ ] Open `/crew/shift/<id>` as an assigned driver — destination banner shows assigned unit (or nothing if unassigned)
- [ ] Driver shift view loads without errors when `truck_unit_plan` has no entry for this truck

### Placement Flow Prefill
- [ ] Open placement section after all stops complete — Select Unit dropdown is prefilled from truck_unit_plan
- [ ] Dropdown still manually changeable (prefill is a default, not a lock)

### Add Truck Button
- [ ] "Add Truck" button visible in ops topbar (was previously hidden)
- [ ] Clicking it adds a new truck card with no unit assigned (amber chip)

### Regression
- [ ] Existing stops on trucks with units still display correctly
- [ ] `POST /admin/crew/shift/<id>/truck/<n>/assign_unit` still saves correctly when called directly
- [ ] Ops page loads without errors on shifts with no stops

---

**Sign-off date:**
**Signed off by:**

---

## Feature: Warehouse Route Browse

**Sign-off status:** ⬜ Not yet signed off
**Built:** 2026-05-29
**Spec file:** `feature_warehouse_route_browse.md`

### Tab Pills
- [ ] Open `/admin/warehouse` — "Search Items" and "Browse by Route" tab pills visible above search area
- [ ] "Search Items" is active by default; existing search input and results area work unchanged
- [ ] Clicking "Browse by Route" shows the route container and hides the search input

### Route Chip List
- [ ] Clicking "Browse by Route" triggers a fetch to `/admin/warehouse/routes`
- [ ] Shift chips appear sorted most-recent-first
- [ ] Each chip shows shift label and item count
- [ ] Shifts with zero seller items are omitted from the list
- [ ] Empty state shown when no shifts have items

### Route Results
- [ ] Clicking a shift chip loads item results in the #warehouse-search-results container
- [ ] All items from sellers on that shift appear (no status filter — approved, pending, sold all included)
- [ ] Items already assigned a storage location show a green unit chip instead of the "Select Unit" picker
- [ ] Items without a storage location show the normal inline "Select Unit" picker (functional as usual)

### Search Tab Regression
- [ ] Switching back to "Search Items" tab restores the search input and clears route results
- [ ] Text search still works after browsing routes
- [ ] Unit-scoped search (from unit drawer) still works

---

**Sign-off date:**
**Signed off by:**

---

## Spec D1 — Delivery Routes

**Sign-off status:** ✅ Shipped 2026-05-29 (in production)
**Spec file:** `feature_delivery_routes.md`

> No detailed pass/fail checklist was recorded for this spec at sign-off.
> This is a status note added during the 2026-06-21 documentation audit so the
> shipped feature has coverage. Routes/models below verified against app.py / models.py.

- Buyer-delivery routing built as a parallel system to seller pickups. Delivery vs. pickup
  is determined **at the truck level** by the presence of `DeliveryStop` (delivery) vs.
  `ShiftPickup` (pickup) records — `shift_type` is NOT a stored column.
- Models: `DeliveryStop` (shift_id, buyer_order_id, truck_number, stop_order, status, notes,
  completed_at, notified_at, capacity_warning, created_at, created_by_id; unique on
  `(shift_id, buyer_order_id)`) and `DeliveryRun` (shift_id unique, started_at, started_by_id,
  ended_at, status).
- `Shift.has_delivery_trucks` is a computed property (counts `DeliveryStop` records).
- Admin routes: `GET /admin/ops/delivery-queue` (`admin_ops_delivery_queue`),
  `POST /admin/delivery/shift/<id>/add-stop`, `POST /admin/delivery/shift/<id>/remove-stop/<sid>`,
  `POST /admin/delivery/stop/<sid>/notify`, `GET /admin/ops/delivery-truck-detail`.
- Crew routes: `GET /crew/delivery/<id>`, `GET /crew/delivery/<id>/stops-partial`,
  `POST /crew/delivery/<id>/start`, `POST /crew/delivery/stop/<sid>/update`,
  `POST /crew/delivery/<id>/end`.
- Mixed-truck guard enforced in both `admin_shift_assign_seller` (blocks if DeliveryStops exist
  on target truck) and `admin_delivery_add_stop` (blocks if ShiftPickups exist).

**Sign-off date:** Shipped to production; no formal checklist sign-off recorded.

---

## Spec A — Delivery Fees (Zone Pricing, Sales Tax, Flexible Delivery)

**Sign-off status:** ✅ Shipped 2026-06-14 (in production)
**Spec file:** `feature_delivery_fees.md`
**Automated tests:** 31/31 (`test_delivery_fees.py`) at last count after Spec B updates.

> Status note added during the 2026-06-21 documentation audit. Facts verified against
> app.py / models.py. No per-checkbox sign-off recorded for this spec.

- Zone-based delivery pricing (20-mile cutoff replaced the older 50-mile radius). Helpers:
  `calculate_delivery_zone()`, `compute_sales_tax()`, `_to_cents()`.
- New checkout flow: `GET/POST /checkout/review` (`checkout_review`) does the pricing work;
  `/checkout/pay/<id>` reduced to a redirect. Legacy per-item routes preserved as redirects:
  `/checkout/delivery/<id>` (`checkout_delivery_legacy`), `/checkout/review/<id>`
  (`checkout_review_legacy`).
- `/webhook` extended with an idempotency guard (`stripe_checkout_session_id`) and a
  double-sale guard (raises `SellerAlert`). Stripe webhook remains the only source of truth
  for payment state.
- Tax = 7.25% on item price only, never on the delivery fee. All AppSettings have hardcoded
  fallback defaults.
- Flexible Delivery uses a Stripe Coupon (AppSetting `stripe_flexible_coupon_id`), not a
  negative line item; the toggle is hidden when the coupon id is absent.
- `BuyerOrder` gained: `delivery_zone`, `delivery_fee`, `is_flexible_delivery`,
  `flexible_discount`, `sales_tax`, `distance_miles`, `items_subtotal`, `total_paid`,
  `stripe_checkout_session_id` (migration `buyer_order_delivery_fee_fields`).

**Sign-off date:** Shipped to production; no formal checklist sign-off recorded.

---

## Spec B — Cart / Bundle & Save

**Sign-off status:** ✅ Shipped 2026-06-18 (in production)
**Spec file:** `feature_cart_bundle.md`
**Automated tests:** 61 total (31 Spec A + 30 Spec B) passing
(`pytest test_delivery_fees.py test_cart_bundle.py`).

> Status note added during the 2026-06-21 documentation audit. Facts verified against
> app.py / models.py. No per-checkbox sign-off recorded for this spec.

- New models: `Order` (parent — buyer info, delivery_* fields, `bundle_free_delivery`,
  `status` pending→paid, `has_conflict`; `line_items` → `[BuyerOrder]`), `Cart`
  (user_id, session_token, created_at, updated_at), `CartItem` (cart_id, item_id, added_at;
  unique on `(cart_id, item_id)`). `BuyerOrder` gained `order_id` FK → `Order`. Existing rows
  backfilled 1 `Order` per `BuyerOrder`.
- Cart routes: `POST /cart/add/<id>`, `POST /cart/remove/<id>`, `GET /cart` (`cart_view`),
  `POST /cart/checkout` (`cart_checkout`). Multi-item checkout entry: `GET/POST /checkout/review`.
- Lazy hold expiry via AppSetting `cart_hold_minutes` (no cron); `item_is_held(item,
  exclude_cart_id)` checks `Cart.updated_at >= cutoff`.
- Bundle & Save: `item_count >= bundle_min_items` (default 2) → `delivery_fee = 0`,
  `bundle_free_delivery = True`. Flexible −$5 still works via the Spec A coupon; for bundles
  (delivery = $0) the $5 comes off the total instead of the fee.
- Pending `Order` created before Stripe redirect; items marked sold only in the webhook
  (source-of-truth preserved). Webhook CASE 0 handles `type='cart_order'` metadata; CASE 1
  unchanged for legacy single-item.
- Guest carts via `cart_token` in session; `_merge_guest_cart_into_user()` called on login
  and register.

**Sign-off date:** Shipped to production; no formal checklist sign-off recorded.

---

## Feature: AI Item Generation & Review

**Sign-off status:** ✅ Shipped (in production)

> Status note added during the 2026-06-21 documentation audit — this shipped feature had no
> checklist coverage. Routes/fields verified against app.py / models.py. Listed here for
> completeness; no per-checkbox sign-off recorded.

- Admin routes: `/admin/ai/generate` (`admin_ai_generate_page`), `POST /admin/ai/generate/run`,
  `POST /admin/ai/generate/cancel`, `GET /admin/ai/generate/status`, `/admin/ai/review`
  (`admin_ai_review_queue`), `/admin/ai/item/<id>/detail`, `POST /admin/ai/item/<id>/approve`,
  `POST /admin/ai/item/<id>/discard`, `POST /admin/ai/item/<id>/reset`,
  `POST /admin/ai/item/<id>/set-cover-photo`, `POST /admin/item/<id>/delete-gallery-photo`
  (`admin_ai_delete_gallery_photo` — see 2026-06-22 pass below; **this route EXISTS**, contrary
  to an earlier note that called it phantom/removed).
- `InventoryItem` AI fields: `ai_description`, `ai_long_description`, `ai_price`,
  `ai_retail_price`, `ai_review_pending`, `ai_generated_at`, `ai_approved`, `ai_retry_count`
  (Integer default 0, hard-stop at 3 retries), `ai_photo_enhanced`, `seller_description`,
  `seller_long_description`, `was_previously_approved`.

**Sign-off date:** Shipped to production; no formal checklist sign-off recorded.

---

## Spec #10 — Admin Dashboard Overhaul

**Sign-off status:** ⬜ Superseded by Admin UI Redesign (already built)

---

## Shop + Delivery Ops Pass — 2026-06-22

**Sign-off status:** ✅ Shipped (in production)

> A round of buyer-checkout and delivery-ops work done after the 2026-06-21
> documentation audit. Routes/fields/behaviors verified against app.py / models.py.
> Listed for completeness; no per-checkbox sign-off recorded.

### Checkout — address & delivery picker
- `checkout_delivery` passes `google_maps_key`, `warehouse_lat`/`warehouse_lng`, and
  `max_delivery_miles` to the template; `checkout_delivery.html` runs Google Places
  autocomplete with a map preview and hidden lat/lng. Client (Places) lat/lng is preferred
  over Nominatim. "Address confirmed" only shows when the address is within the delivery
  radius; an out-of-area message shows otherwise. (`.pac-container` z-index fix; `gm_authFailure`
  note for a bad/missing key.)
- Warehouse origin falls back to module constants `WAREHOUSE_DEFAULT_LAT`/`_LNG`
  (35.9030324, -79.0709049 — 515 S Greensboro St, Carrboro NC) when the `warehouse_lat`/
  `warehouse_lng` AppSettings are blank, so checkout fails open instead of hard-erroring.
- `checkout_review.html` replaces the single Flexible checkbox with a two-radio picker
  (Standard / Flexible). Delivery date ranges come from `_delivery_window()` (upcoming
  Fri/Sat; Mon–Thu → this week, Fri–Sun → next week), surfaced via `delivery_window` in
  the confirmation email, `item_success.html`, and `checkout_review`. `item_success.html`
  dropped the "may shift to the following weekend" caveat.

### Cart hold — now checkout-based
- New `Cart.checkout_started_at` (DateTime, nullable; migration `c3d4e5f6a7b8`, down_revision
  `f7e8d9c0b1a2`), set at "Proceed to Payment". New AppSetting `checkout_hold_minutes`
  (default `'15'`).
- `item_is_held(item, exclude_cart_id)` REWRITTEN — an item is held against other buyers only
  while `Cart.checkout_started_at` is within `checkout_hold_minutes`. The old membership-based
  hold (`cart_hold_minutes`, default 30, just from being in a cart) is gone.
- `cart_add`: "Buy Now" (full-page POST) now flashes and redirects to the product page on
  errors instead of returning raw JSON; async "Add to Cart" still returns JSON.

### Delivery ops
- NEW route `POST /admin/crew/shift/<id>/notify-buyers` (`admin_shift_notify_buyers`,
  `_has_ops_access()`): bulk-sends the delivery-scheduled email to every buyer on the shift's
  delivery route with `notified_at IS NULL`, flashes the count, redirects to ops. Shares
  `_send_delivery_scheduled_email(stop)` with the per-stop `admin_delivery_notify_buyer`.
- `admin/ops.html`: blue "Notify Buyers" button next to Notify Sellers (only when the shift
  has delivery stops); truck drawer re-executes injected `<script>` so `notifyDeliveryBuyer`
  works; `delivery_queue` mapped to `orders` for the unassigned-deliveries partial; pickup-week
  chips show a date range via the `pickup_week_range` Jinja filter. Per-stop "Notify Buyer"
  works in `ops_delivery_truck_detail` now; `ops_delivery_queue_partial.html` shows buyer name
  on cards and the assign form stops click propagation.
- Mixed-truck guard added to `admin_routes_assign_seller`: assigning a pickup to a truck that
  already has `DeliveryStop` records returns 422 (flash) and creates nothing — previously this
  silently created an orphan `ShiftPickup` that never rendered and dropped the seller from the
  unassigned list. (A truck is pickup OR delivery, enforced on the ops assign path as well as
  the delivery add-stop path.)
- `warehouse_lat`/`warehouse_lng` are now editable in Settings → Route & capacity
  (`save_route_settings` action in `admin_settings`); blank values fall back to the
  `WAREHOUSE_DEFAULT_*` constants.

### AI review — gallery photo delete
- `POST /admin/item/<id>/delete-gallery-photo` (`admin_ai_delete_gallery_photo`, super admin):
  removes a photo from an item in AI review — works for a seller-uploaded gallery photo OR the
  AI-enhanced cover. Deleting the cover promotes another photo so the item is never imageless;
  blocks if it's the only photo; clears `ai_photo_enhanced` when an `ai_enhanced_*` file is
  removed; deletes the underlying file. **This route EXISTS** — an earlier note documented it
  as phantom/removed; that was wrong.

### Email fixes
- `wrap_email_template` is now idempotent (returns content unchanged if it's already a full
  `<!DOCTYPE>` document), fixing the double-logo bug where callers pre-wrapped and `send_email`
  wrapped again. Logo is now `faviconNew.PNG` (not SVG — clients block SVG), built from the
  public base URL (`APP_BASE_URL`/`BASE_URL`/usecampusswap.com), not the request host.
- New helper `_email_photo_url(filename)` returns an absolute, email-safe image URL (prefers a
  direct S3/CDN URL with no redirect; falls back to the external `uploaded_file` route, then
  `BASE_URL/uploads`). `_send_buyer_order_confirmation` now includes item photo thumbnails
  (table rows) via this helper.

### Misc
- `product.html` cart badge reveals on first add (0→1). `static/style.css` removed the `.card`
  hover lift (translateY) and `.item-card` image hover zoom.
- Migrations remain a single linear head (`c3d4e5f6a7b8`) — no multiple-heads/merge issue.
- App is now ~281 routes (as of 2026-07-17).

**Sign-off date:** Shipped to production; no formal checklist sign-off recorded.

---

## Rephoto follow-ons + Stock + Mattress (2026-07-21/22)

**Sign-off status:** ⬜ Not started — code in production, **⚠️ `flask db upgrade` still pending on Render** (migrations `46f98d884eeb` → `c2554b94906c` → `700635cb195e`). Run it first, or every check below will error on missing columns.

### Route Photo Report — "Not yet matched" toggle
- [ ] `/admin/warehouse/routes/photo-report` shows an "All items / Not yet matched" toggle
- [ ] Match an item (rephoto), refresh with the toggle ON — the matched item AND its replacement are BOTH gone from the list
- [ ] A genuinely unmatched item still shows; routes with nothing unmatched drop out

### Route Photo Report — lightbox carousel
- [ ] Click a photo with multiple originals — arrows + `N/M` counter appear; ←/→ keys and image-click page through; Escape/backdrop closes
- [ ] A single-photo item opens with no arrows/counter

### Rephoto dispositions (discard / keep / restore)
- [ ] In the matching modal, "Discard duplicate" removes an item from the backlog; it still appears under "All rephotographed" with a Discarded badge and is NOT in the shop
- [ ] "Keep & list for Campus Swap" requires a storage location (dimensions optional); the item leaves the backlog with a Kept badge and appears in the shop once approved+priced
- [ ] "Restore to backlog" on a discarded/kept item returns it to the backlog (a listed keeper is pulled from the shop)

### Revert to Campus Swap
- [ ] "Revert to Campus Swap" on a matched item (or picking Campus Swap in the seller search) moves it back to the backlog, pulls it from the shop, and un-hides the original it had replaced

### Multi-unit stock
- [ ] "Keep & list" with Quantity = N shows ONE shop card labeled "N available"
- [ ] Buying one unit drops the count to N-1; the card disappears only when the last sells
- [ ] Two simultaneous buyers get different units (no oversell of the same unit)

### Mattress size
- [ ] The match modal has a "Mattress size" dropdown; picking Queen/King/etc. autofills Length & Width
- [ ] The product page shows e.g. "Queen mattress · 60" W × 80" L" (nominal size + dimensions), numbers with no trailing `.0`
- [ ] A multi-unit mattress listing carries the size onto every unit
