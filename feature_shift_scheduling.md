# Spec #2 — Shift Scheduling System

**Status:** Ready for implementation
**Depends on:** Spec #1 (Worker Accounts) — must be signed off first ✅
**Required before:** Spec #3 (Driver Shift View), Spec #6 (Route Planning)

---

## Goal

Give admins a way to create a week's worth of shifts, run an optimizer that
proposes worker assignments based on submitted availability, adjust those
assignments manually, and publish the schedule. Workers see their upcoming
shifts and the full crew schedule on `/crew`. Supports last-minute swaps on
published schedules.

---

## UX Flow

### Admin — Week Creation

1. Admin navigates to `/admin/schedule` (new page, super_admin only).
2. Page shows a list of all existing `ShiftWeek` records (most recent first),
   each with its date range, status (draft / published), and a link to manage.
3. Admin clicks **"Create New Week"** → modal (or inline form) appears.
4. Admin picks the week's **Monday date** from a date input. System shows the
   Mon–Sun range that results.
5. For each of the 7 days, admin sees two toggles: **AM** and **PM**. Default
   is all 14 on. Admin toggles off any slots that won't run (e.g., Sunday AM).
6. Admin submits → creates one `ShiftWeek` record and one `Shift` record per
   active slot. Status = `draft`. Redirect to `/admin/schedule/<week_id>`.

### Admin — Schedule Builder

`/admin/schedule/<week_id>` is the main working view for a week.

**Layout:** week date range in header, status badge (draft/published), two
action buttons top-right: **"Run Optimizer"** and **"Publish Schedule"**
(publish is disabled until at least one shift has assignments).

Below that, a list of shifts grouped by day. Each shift row shows:
- Day + slot label (e.g., "Tuesday AM")
- Trucks count (editable inline number input, min 1 max 4)
- Driver slots: `trucks × 2` — shows assigned names or empty badges
- Organizer slots: `trucks × 2` — same
- Status badge: `Fully Staffed` / `Understaffed` / `Unassigned`

**Run Optimizer button:**
- POST to `/admin/schedule/<week_id>/optimize`
- Runs the optimizer across all draft shifts in the week
- Clears any existing unconfirmed assignments, replaces with optimizer output
- Redirects back to `/admin/schedule/<week_id>` with a flash summary:
  "Optimizer ran. 8 of 10 shifts fully staffed. 2 shifts understaffed — see
  below."

**Manual adjustment (post-optimizer or from scratch):**
- Each empty worker slot is a dropdown. Options are workers available for that
  slot (role-filtered: driver slots show drivers + "both"; organizer slots show
  organizers + "both"). Unavailable workers are not shown.
- Changing trucks count (the inline number input) recalculates how many driver
  and organizer slots exist for that shift immediately (vanilla JS, no page
  reload). New empty slots appear; if reducing, a warning shows if it would
  remove an already-assigned worker.
- Admin saves individual shift changes via a **"Save"** button per shift row
  (POST to `/admin/schedule/shift/<shift_id>/update`).

**Publish Schedule button:**
- POST to `/admin/schedule/<week_id>/publish`
- Sets `ShiftWeek.status = 'published'`
- Sends notification email to every worker who has at least one assignment
  in the week
- Redirects back with flash: "Schedule published. X workers notified."
- Once published, publish button becomes **"Unpublish"** (returns to draft,
  does NOT re-notify workers — silent).

### Admin — Last-Minute Swap (Published Schedule)

When a worker drops out of a published shift:

1. Admin is on `/admin/schedule/<week_id>` (published state — editing still
   enabled).
2. Admin clicks the assigned worker's name badge in a shift slot → reveals a
   **"Remove & Replace"** button inline.
3. Clicking it opens a small dropdown in place of that slot showing only workers
   who are available for that slot AND not already assigned to it, role-filtered.
   If no eligible workers exist, a message says "No available workers — assign
   manually or leave understaffed."
4. Admin selects replacement → POST to `/admin/schedule/shift/<shift_id>/swap`
5. Assignment updates immediately. If the replacement worker has no other shifts
   that week, they receive a notification email: "You've been added to [Day]
   [AM/PM] shift." The removed worker receives: "Your [Day] [AM/PM] shift
   assignment has been updated — contact your admin with questions."
6. Shift status badge recalculates automatically.

### Worker — Crew Dashboard (`/crew`)

The existing three-column dashboard layout (from Spec #1 screenshot) gains
content in the **"My Schedule"** column:

**Before schedule is published for the current week:**
> "Your shift schedule will appear here once it's been built. Schedules post
> every Thursday."
(Unchanged from current placeholder)

**After schedule is published:**

- **Next shift card** shown prominently at top of the column: day, AM/PM,
  role for that shift, time (TBD — see constraints). Styled with `--accent`
  border.
- Below it: **"See full week schedule →"** link/button that expands an inline
  panel (vanilla JS toggle, no page load) showing the complete week's schedule
  — all shifts, all assigned workers by name, with the current worker's own
  assignments highlighted.
- The full week view is read-only for workers. It shows who is on each shift
  so workers can reach out to admin about trades.

**"Shift History"** column — unchanged placeholder for Spec #3+.

---

## New Routes

| Method | Path | Function | Description |
|--------|------|----------|-------------|
| `GET` | `/admin/schedule` | `admin_schedule_index` | List all ShiftWeeks; form to create new week. Super admin only. |
| `POST` | `/admin/schedule/create` | `admin_schedule_create` | Create ShiftWeek + Shifts from week form. Super admin only. |
| `GET` | `/admin/schedule/<week_id>` | `admin_schedule_week` | Schedule builder view for a single week. Super admin only. |
| `POST` | `/admin/schedule/<week_id>/optimize` | `admin_schedule_optimize` | Run optimizer, write ShiftAssignment records, redirect back. |
| `POST` | `/admin/schedule/<week_id>/publish` | `admin_schedule_publish` | Set status=published, send worker emails. |
| `POST` | `/admin/schedule/<week_id>/unpublish` | `admin_schedule_unpublish` | Return week to draft. Silent — no worker emails. |
| `POST` | `/admin/schedule/shift/<shift_id>/update` | `admin_shift_update` | Save trucks count + manual assignment changes for one shift. |
| `POST` | `/admin/schedule/shift/<shift_id>/swap` | `admin_shift_swap` | Replace one worker on a published shift. Sends swap emails. |
| `GET` | `/crew/schedule/<week_id>` | `crew_schedule_week` | Full week schedule view (all workers visible). Requires is_worker. Used by the expand panel on /crew. Returns HTML partial. |

---

## Model Changes

### New: `ShiftWeek`
```
id
week_start        Date — the Monday of this work week (unique)
status            String — 'draft' | 'published'
created_at        DateTime
created_by_id     FK → User (nullable)

Relationships:
  shifts → [Shift]
  created_by → User
```

### New: `Shift`
```
id
week_id           FK → ShiftWeek
day_of_week       String — 'mon'|'tue'|'wed'|'thu'|'fri'|'sat'|'sun'
slot              String — 'am'|'pm'
trucks            Integer — number of trucks for this shift (default 2, min 1, max 4)
is_active         Boolean — False if admin toggled this slot off during week creation
created_at        DateTime

Relationships:
  week → ShiftWeek
  assignments → [ShiftAssignment]

Properties:
  drivers_needed    → trucks × AppSetting('drivers_per_truck')
  organizers_needed → trucks × AppSetting('organizers_per_truck')
  is_fully_staffed  → len(driver assignments) == drivers_needed AND len(organizer assignments) == organizers_needed
  label             → e.g. "Tuesday AM"
```

### New: `ShiftAssignment`
```
id
shift_id          FK → Shift
worker_id         FK → User
role_on_shift     String — 'driver'|'organizer'
assigned_at       DateTime
assigned_by_id    FK → User (nullable — NULL = optimizer)

Relationships:
  shift → Shift
  worker → User
  assigned_by → User
```

**Migration note:** Three new tables. Run `flask db migrate -m "shift_scheduling"` and `flask db upgrade`.

No changes to existing models. No changes to `WorkerAvailability`.

---

## Template Changes

### New: `admin/schedule_index.html`
Extends `layout.html`. Shows list of `ShiftWeek` records (week range, status
badge, "Manage" link). Inline form at top or in a card: date picker for Monday,
7×2 toggle grid for active slots (similar visual style to `_availability_grid.html`
but checkboxes, not tap-to-toggle — all on by default). Submit creates the week.

### New: `admin/schedule_week.html`
Extends `layout.html`. The main schedule builder. See UX flow above.

Key JS behavior (vanilla only):
- Trucks count input change → recalculate slot counts inline (no page reload)
- "Remove & Replace" toggle on worker name badges
- Warn before reducing truck count if workers already assigned to those slots

### Modified: `crew/dashboard.html`
Replace the "My Schedule" placeholder card content with:

**Before publish:**
Unchanged — existing placeholder text.

**After publish (current week has a published ShiftWeek):**
- Next shift card (highlighted with `--accent` border)
- "See full week schedule" toggle button
- Hidden `<div>` containing full week schedule (fetched on first toggle via
  `fetch('/crew/schedule/<week_id>')`, injected into the div, then shown/hidden
  on subsequent clicks — one fetch per page load)

The template receives a `current_week` context variable (the published
`ShiftWeek` for the current week, or `None`), and `my_next_shift` (the next
`Shift` the worker is assigned to, or `None`).

### New: `crew/schedule_week_partial.html`
No `layout.html` — this is an HTML partial returned by `GET /crew/schedule/<week_id>`.
Renders the full week's shift grid: days as rows, AM/PM columns, each cell
listing assigned workers by name with role label. Current user's own assignments
are highlighted (e.g., with `--accent` text color or a small badge).

---

## Business Logic

### Optimizer Algorithm

Runs on `POST /admin/schedule/<week_id>/optimize`. Processes all active shifts
in the week. For each shift:

1. **Determine required staffing:** `drivers_needed = trucks × drivers_per_truck`,
   `organizers_needed = trucks × organizers_per_truck` (read from AppSetting at
   runtime).

2. **Build candidate pool:** Query all approved workers (`is_worker=True`,
   `worker_status='approved'`). For each worker, look up their `WorkerAvailability`
   for this week (`week_start = shift.week.week_start`). If no weekly record
   exists, fall back to their application availability (`week_start = NULL`).
   A worker is **eligible** for a slot if their availability boolean for that
   day+slot is `True`.

3. **Filter by role:**
   - Driver slots: eligible workers with `worker_role` in `('driver', 'both')`
   - Organizer slots: eligible workers with `worker_role` in `('organizer', 'both')`

4. **Sort candidates by load (ascending):** Count how many shifts each candidate
   is already assigned to in this week (across all shifts processed so far).
   Sort ascending — fewest shifts first. This spreads load evenly.

5. **Avoid double-shifts:** If a worker is already assigned to the other slot
   on the same day (e.g., already on Tuesday AM, now considering Tuesday PM),
   deprioritize them — move to end of sorted list. Only assign if no other
   eligible workers remain.

6. **Assign greedily:** Take the top N candidates from the sorted driver list
   (N = drivers_needed), assign as drivers. Take top M from organizer list
   (M = organizers_needed), assign as organizers. A worker assigned as a driver
   is not also assigned as an organizer for the same shift.

7. **Mark understaffed:** If after assignment, `len(driver assignments) <
   drivers_needed` OR `len(organizer assignments) < organizers_needed`, the
   shift is understaffed. No error is raised — admin sees the gap and fills
   manually or hires more workers.

8. **Clear before re-run:** Running the optimizer again on a week clears all
   existing `ShiftAssignment` records for that week before re-assigning. A
   confirmation prompt in the UI warns admin if the week already has assignments.

### Availability Lookup Priority

For a given worker and a given `ShiftWeek`:
1. Check for `WorkerAvailability` where `user_id = worker.id` AND `week_start =
   shift_week.week_start`. Use this if it exists.
2. Fall back to `WorkerAvailability` where `user_id = worker.id` AND
   `week_start IS NULL` (application-time availability).
3. If neither exists, treat worker as unavailable for all slots.

### Trucks Count Constraints
- Min: 1 truck per shift
- Max: read from `AppSetting('max_trucks_per_shift')` (currently `'4'`)
- Changing truck count on a shift that already has assignments: if reducing,
  warn admin and require confirmation if existing assignments exceed new
  capacity. Excess assignments are removed oldest-first (by `assigned_at`).

### Published Schedule Editing
- Published shifts can have assignments added, removed, or swapped.
- Unpublishing returns `ShiftWeek.status` to `'draft'`. Does NOT delete
  assignments. Admin can re-publish without re-running optimizer.
- There is no "locked" state — admin always has full edit access.

### Swap Notification Emails
On `POST /admin/schedule/shift/<shift_id>/swap`:
- Removed worker receives email: subject "Campus Swap Shift Update", body
  noting which shift changed and to contact admin.
- Added worker receives email: subject "You've Been Scheduled — Campus Swap",
  body with day, AM/PM, role, and link to `/crew`.
- Use existing `send_email()` + `wrap_email_template()` pattern.

### Publish Notification Email
On publish, send one email per worker who has ≥1 assignment in the week.
Subject: "Your Campus Swap Schedule — Week of [Mon date]"
Body: lists each shift the worker is assigned to (day, AM/PM, role).
Link to `/crew`.

### Worker Schedule Visibility
All approved workers (`is_worker=True`, `worker_status='approved'`) can see
the full published schedule at `/crew/schedule/<week_id>`. The route requires
`is_worker` — non-workers get a 403. The schedule shows all worker names.
Unpublished (draft) weeks are not accessible via crew routes.

### "Current Week" Logic
For `/crew` dashboard context:
- `current_week`: the `ShiftWeek` whose `week_start` is the most recent Monday
  ≤ today AND `status='published'`. If none, `None`.
- `my_next_shift`: the earliest `Shift` in `current_week` (by day+slot order)
  where the current user has a `ShiftAssignment`. If none, `None`.

---

## Constraints

The following existing logic must NOT be touched:

- `WorkerAvailability` model and its 14 boolean columns — read-only from this spec's perspective
- `WorkerApplication`, `User.worker_role`, `User.worker_status` — read-only
- All existing `/crew/*` routes (apply, pending, availability) — no changes
- All existing `/admin/crew/*` routes (approve, reject) — no changes
- `AppSetting` keys `drivers_per_truck`, `organizers_per_truck`, `max_trucks_per_shift` — read at runtime, never hardcoded
- Admin two-tier role system — all new `/admin/schedule/*` routes check `is_super_admin` (not just `is_admin`)
- Stripe webhook, item status lifecycle, seller onboarding — completely untouched
- `layout.html` — additive changes only (no nav changes needed for this spec)

---

## Open Questions for Future Specs

- Shift start/end times (AM = what hours? PM = what hours?) are not defined here.
  Spec #3 (Driver Shift View) should define this and add a `start_time`/`end_time`
  to `Shift` if needed, or handle it via AppSetting.
- Route assignment to trucks happens in Spec #6. `Shift` and `ShiftAssignment`
  are intentionally route-agnostic here.
- Shift pay ($130/shift) tracking and history live in Spec #5 (Payout
  Reconciliation). `ShiftAssignment` is the record that will anchor pay
  calculation — do not delete assignment records after shifts complete.
