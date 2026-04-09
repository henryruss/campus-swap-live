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

**Sign-off status:** ⬜ Not started

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

## Spec #10 — Admin Dashboard Overhaul

**Sign-off status:** ⬜ Spec not yet written
