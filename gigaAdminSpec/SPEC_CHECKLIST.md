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
- [ ] Visit `/crew/apply` without being logged in — page loads correctly
- [ ] Try submitting with a Gmail address — get a clear error message
- [ ] Submit with a `.edu` address — application created, confirmation page shown
- [ ] Log in as an existing Campus Swap seller, visit `/crew/apply` — name/email/phone pre-filled
- [ ] Submit as existing user — no duplicate account created, one `WorkerApplication` record in DB
- [ ] Try submitting a second application with the same account — get a clear error

### Availability Grid
- [ ] Grid loads with all 14 cells green (fully available) by default
- [ ] Tap an AM cell on mobile — it turns grey, hidden input updates
- [ ] Tap the same cell again — it returns to green
- [ ] Tap PM cell on same day — both AM and PM can be individually toggled
- [ ] Submit with some cells blacked out — DB record reflects correct True/False values
- [ ] Verify in DB: `SELECT mon_am, mon_pm, tue_am FROM worker_availability WHERE user_id = X`

### Admin Approval
- [ ] Log in as admin, open admin panel — "Crew" section visible with pending count badge
- [ ] Click View on an application — availability grid displays correctly, blacked-out cells clear
- [ ] Click Approve — modal appears with role selector
- [ ] Select "Driver", confirm — `is_worker=True`, `worker_status='approved'`, `worker_role='driver'` in DB
- [ ] Approval email arrives in inbox with correct content and `/crew` link
- [ ] Click Reject with email toggle on — rejection email sent
- [ ] Click Reject with email toggle off — no email sent

### Worker Portal Access
- [ ] Log in as approved worker, visit `/crew` — dashboard loads
- [ ] Log in as pending applicant, visit `/crew` — pending page shown, not an error
- [ ] Visit `/crew` while logged out — redirected to login, then back to `/crew`
- [ ] Log in as a regular buyer (non-worker), visit `/crew` — redirected appropriately
- [ ] Check nav as approved worker — "Crew Portal" link visible
- [ ] Check nav as non-worker — "Crew Portal" link not visible

### Weekly Availability Update
- [ ] Log in as approved worker, visit `/crew/availability` — grid pre-filled from application submission
- [ ] Change some cells, submit — DB record upserted correctly (no duplicate created)
- [ ] Verify `(user_id, week_start)` uniqueness: two records exist — one with `week_start=NULL` (application) and one with the current Monday's date (weekly update)
- [ ] Manually set date past Tuesday deadline, visit `/crew/availability` — form is locked with clear message

### Database & Migrations
- [ ] `flask db migrate` runs with no errors
- [ ] `flask db upgrade` runs with no errors
- [ ] `User` table has three new columns: `is_worker`, `worker_status`, `worker_role`
- [ ] `worker_application` table exists with correct schema
- [ ] `worker_availability` table exists with all 14 boolean columns
- [ ] AppSetting keys seeded: `crew_applications_open`, `availability_deadline_day`, `drivers_per_truck`, `organizers_per_truck`, `max_trucks_per_shift`

### Existing Features (Regression Check)
- [ ] Regular seller can still log in and access `/dashboard`
- [ ] Admin panel existing sections (inventory, approvals) still work
- [ ] Buyer can still browse `/inventory` and view product pages
- [ ] Stripe webhook endpoint still responds correctly

**Sign-off date:** ___________
**Signed off by:** ___________

---

## Spec #2 — Shift Scheduling

**Sign-off status:** ⬜ Spec not yet written

*Checklist will be added when spec is designed.*

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
