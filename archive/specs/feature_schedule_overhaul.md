# Feature Spec: Schedule Tab Removal + Calendar-Based Shift Creation + Single Daily Shift

## Goal

Three related changes shipped together:

1. **Remove the Schedule tab.** Replace the week-creation workflow with
   a simple date-picker calendar on the Ops tab. Admin clicks any date to
   create a shift for it — no ShiftWeek wizard, no pre-generating 14 shift
   records. The tab and all its routes are retired.

2. **Single daily shift from June 1 onwards.** Pre-June shifts keep their
   `slot='am'/'pm'` values untouched. New shifts created on or after
   June 1, 2026 get `slot='daily'` (10am–3pm Eastern). All display labels,
   SMS copy, and seller-facing text branch on slot value.

3. **Simplify the campus director tutorial.** Remove the schedule-creation
   step (old steps 1–2). The tutorial now starts on the Crew tab and runs
   one step shorter. Step numbers are renumbered throughout.

---

## Part 1 — Calendar-Based Shift Creation

### UX Flow

The Ops tab left panel (shift list) gains a **"+ New Shift"** button at the
bottom, below the shift list. Clicking it opens a small inline date picker
(or a compact modal — whichever is cleaner in the existing panel width).

Admin picks a date. The system:
1. Looks up or creates the containing `ShiftWeek` (week_start = Monday of
   that date) automatically — the admin never sees this.
2. Creates a single `Shift` record for that date with `slot` determined by
   the shift date: `'daily'` if date >= June 1, 2026; otherwise `'am'` (for
   any backfill of old dates, though this path is unlikely to be used).
3. Redirects to `?shift_id=<new_id>` so the new shift is selected.

No optimizer, no publish/unpublish, no 14-record generation. The shift exists
immediately and is ready for sellers to be assigned.

**Worker staffing** on the new shift still works via Crew HQ (quick-add
workers to shifts from the Crew tab), which is already built. The Schedule
tab's publish + email-all-workers flow is removed; individual worker
assignment happens via Crew HQ as it does today.

### Schedule tab removal

`GET /admin/schedule` → 302 to `/admin/ops` (matches the pattern of how
`/admin/routes` was retired).

All schedule-related routes are kept in `app.py` but are no longer linked
from any UI. They can be deleted in a future cleanup pass once confirmed
unused. The Schedule sidebar icon is removed from `admin_layout.html`.

The "Pickup window" section in Settings (`pickup_week_start`,
`pickup_week_end` AppSettings) and the `POST /admin/settings/generate-shifts`
route are removed from the Settings UI. Those AppSettings keys can stay in
the DB harmlessly.

### ShiftWeek auto-creation

New helper `_get_or_create_shift_week(date)`:
```python
week_start = date - timedelta(days=date.weekday())  # Monday
week = ShiftWeek.query.filter_by(
    week_start=week_start, is_tutorial=False
).first()
if not week:
    week = ShiftWeek(
        week_start=week_start,
        status='published',   # always published — no draft concept
        created_by_id=current_user.id
    )
    db.session.add(week)
    db.session.flush()
return week
```

New ShiftWeeks created this way are always `status='published'`. The
draft/published distinction was only meaningful for the old optimizer +
email-all-workers flow, which is gone.

---

## Part 2 — Single Daily Shift (June 1 +)

### Model change

`Shift.slot` currently accepts `'am' | 'pm'`. Add `'daily'` as a new valid
value. **No migration required** — it's a string column with no DB-level
constraint. Existing rows are untouched.

### New shift creation rule

In `POST /admin/schedule/shift/create` (new route, see below):
```python
DAILY_SHIFT_CUTOVER = date(2026, 6, 1)
slot = 'daily' if shift_date >= DAILY_SHIFT_CUTOVER else 'am'
```

### Label changes

`Shift.label` property currently returns e.g. `"Mon Jun 2 AM"`. Update to
return `"Mon Jun 2"` for `slot='daily'` (no slot suffix).

Anywhere `slot` is displayed to sellers or workers, branch on value:
- `'am'` → "Morning" / "AM"
- `'pm'` → "Afternoon" / "PM"  
- `'daily'` → "10am–3pm" (or just omit the time descriptor where space is
  tight, since there's only one shift per day)

### SMS copy updates

The two SMS templates that mention AM/PM need to branch:

**Pickup confirmed SMS** (sent by `admin_shift_notify_sellers`):
- Old: `"...scheduled for [Day, Mon D] AM/PM."`
- New: `"...scheduled for [Day, Mon D]{{ ' ' + slot_label if slot != 'daily' else '' }}."`
- Daily result: `"Your Campus Swap pickup is scheduled for Mon, Jun 2."`

**24hr reminder SMS** (sent by `cron_sms_reminders`):
- Old: `"...picking up your stuff tomorrow, [Day Mon D] AM/PM."`
- New: same branch — omit slot label for daily shifts.

### Reschedule grid

`seller/reschedule.html` currently renders a grid with AM/PM rows. For
pickup windows that only have daily shifts, the grid degenerates to one
option per date column. The template should:
- Render AM/PM rows only if any eligible shifts have `slot in ('am', 'pm')`
- Render a single "10am–3pm" row if all eligible shifts are `slot='daily'`
- Handle mixed windows (some old AM/PM + some new daily) gracefully — show
  all three rows, leave cells empty for slots that don't exist on that date.

### Seller dashboard pickup window display

`dashboard.html` pickup window stat cell shows `"Wk 1 · Morning"` format
before notification and `"Tue, Apr 29 · Morning"` after. For daily shifts:
- Before notification: `"Wk 1"` (no time suffix)
- After notification: `"Tue, Jun 2"` (no time suffix)

The pickup week modal's time preference buttons (Morning / Afternoon /
Evening) are only relevant for AM/PM slots. Hide the time preference row
when the seller's pickup window falls entirely within daily-shift dates.
This requires knowing the pickup window date range — use the existing
`pickup_week_start` / `pickup_week_end` AppSettings (or `_today_eastern()`
comparison against `DAILY_SHIFT_CUTOVER`) to determine whether to show the
time preference UI.

---

## Part 3 — Tutorial Renumbering

### New step sequence (8 steps, 0-indexed)

| Step | State | Location |
|------|-------|----------|
| 0 | Not started | — |
| 1 | Started; approve Sam Torres | Crew tab |
| 2 | Sam approved; assign crew to shift + assign sellers | Crew / Ops |
| 3 | Worker assigned; navigate to Ops; assign remaining sellers | Ops |
| 4 | (unused/skipped — kept as buffer) | — |
| 5 | All sellers assigned; click Reorder Stops | Ops |
| 6 | On reorder page | ops_reorder |
| 7 | Stops reordered; click Notify Sellers | Ops |
| 8 | Complete | — |

Old step 1 (schedule page, create week) is removed. Tutorial now starts
by redirecting the CD to `/admin/crew` instead of `/admin/schedule`.

`seed_tutorial_fixtures()` already creates the tutorial `ShiftWeek` and
`Shift` programmatically. That doesn't change — the CD just never sees
the schedule-creation UI.

### Changes required

**`TutorialSession` model** — step sequence documented in the docstring
only (no migration needed, it's just an integer).

**`admin_tutorial_start` route** — change post-start redirect from
`/admin/schedule` to `/admin/crew`.

**`seed_tutorial_fixtures()`** — no change needed. It already creates the
ShiftWeek directly.

**Tutorial gate** — change step 1 description and entry page. The gate
currently redirects to `/admin/tutorial` if `ts.step == 0`, then to
`/admin/schedule` after start. Change the post-start redirect to
`/admin/crew`.

**`tutorial_overlay.html`** — remove the schedule-page branch (step 1
content that highlighted the "Create Week" card). The overlay's crew-page
branch becomes the first active step. Update all step number comparisons:
- Old step 2 → new step 1 (approve Sam on Crew)
- Old step 3 → new step 2
- Old step 4 → new step 3
- Old step 6 → new step 5
- Old step 7 → new step 6
- Old step 8 → new step 7
- Old step 9 → new step 8

**`admin/schedule_index.html`** — remove the `{% include tutorial_overlay %}`
block.

**`admin/crew.html`** — tutorial overlay branch for step 1 is now the
first active content (was step 2). Update step number check.

**`admin/ops.html`** — update all `tutorial_step` comparisons:
- Unassigned panel highlight: was step 4, now step 3
- Reorder Stops highlight: was step 6, now step 5
- Notify Sellers disabled guard: was `< 8`, now `< 7`

**`admin/ops_reorder.html`** — Save Order button highlight: was step 7,
now step 6.

**`admin/admin_layout.html`**:
- Remove Schedule nav icon and link.
- Crew nav link tutorial-highlight: was step 2, now step 1.
- Ops nav link tutorial-highlight: was step 4, now step 3.

**Route guards in `app.py`**:
- `admin_schedule_create`: tutorial guard bumps step 1→2; now this route
  is unreachable from tutorial (no longer linked). Remove the tutorial
  guard from this route entirely.
- `admin_routes_assign_seller`: sets step 6 when all tutorial sellers
  assigned → update to step 5.
- `admin_ops_reorder_page` GET: bumps step 6→7 → update to step 5→6.
- `admin_ops_reorder_stops` POST: checks `ts.step == 7` → update to
  `ts.step == 6`, bumps to 7.
- `admin_shift_notify_sellers`: guard `ts.step < 8` → update to
  `ts.step < 7`. Bumps to 8 when step == 7.

---

## New Routes

| Method | Path | Function | Notes |
|--------|------|----------|-------|
| `POST` | `/admin/schedule/shift/create` | `admin_shift_create` | Create a single shift for a given date. Params: `shift_date` (ISO date string). Auto-creates ShiftWeek if needed. `slot` determined by DAILY_SHIFT_CUTOVER. Returns redirect to `/admin/ops?shift_id=<id>`. Auth: `_has_ops_access()`. |
| `GET` | `/admin/schedule` | `admin_schedule_index` | **Changed:** 302 → `/admin/ops`. |

---

## Model Changes

`Shift.slot` accepts new value `'daily'`. No migration — string column,
no DB constraint. Document in models.py comment.

---

## Template Changes

| Template | Change |
|----------|--------|
| `admin/admin_layout.html` | Remove Schedule sidebar icon + link |
| `admin/ops.html` | Add "+ New Shift" button + date picker in shift list panel; update tutorial step comparisons |
| `admin/ops_reorder.html` | Update tutorial step comparison |
| `admin/crew.html` | Update tutorial step comparison |
| `admin/settings.html` | Remove "Pickup window" section (date inputs + Generate Shifts button) |
| `admin/schedule_index.html` | Remove tutorial overlay include (template kept but unreachable) |
| `admin/tutorial_overlay.html` | Remove schedule-page branch; renumber all step comparisons |
| `crew/shift.html` | `slot='daily'` label: show "10am–3pm" instead of "AM/PM" |
| `seller/reschedule.html` | Handle daily slots in grid — one row per day when all slots are daily; mixed-mode rendering for transitional window |
| `dashboard.html` | Pickup window cell and modal: omit time suffix for daily shifts; hide time preference buttons when all available slots are daily |

---

## Business Logic

### DAILY_SHIFT_CUTOVER constant
```python
from datetime import date
DAILY_SHIFT_CUTOVER = date(2026, 6, 1)
```
Defined once at module level in `app.py`. Used in `admin_shift_create` and
anywhere slot-display branches.

### Shift.label property update
```python
@property
def label(self):
    d = _shift_date(self)
    day_str = d.strftime('%a %b %-d')
    if self.slot == 'daily':
        return day_str
    slot_str = 'AM' if self.slot == 'am' else 'PM'
    return f"{day_str} {slot_str}"
```

### Ops panel "+ New Shift" interaction
- Button in shift list panel footer.
- Opens a minimal inline form: `<input type="date" name="shift_date">` +
  Submit button.
- POST to `POST /admin/schedule/shift/create`.
- On success: redirect to `?shift_id=<new_id>` — new shift selected,
  ready for sellers to be assigned.
- Duplicate guard: if a shift already exists for that date (non-tutorial),
  flash "A shift already exists for that date" and redirect to
  `?shift_id=<existing_id>`.

### ShiftWeek status
New ShiftWeeks created via `_get_or_create_shift_week()` always have
`status='published'`. The draft state is no longer used for new weeks.
Existing draft weeks are unaffected.

---

## Constraints

- **All pre-existing Shift records untouched.** `slot='am'/'pm'` values
  on existing shifts are not modified. No data migration.
- **Schedule builder routes** (`/admin/schedule/*`) are kept in `app.py`
  but removed from all navigation. Do not delete them yet — existing
  tutorial fixture ShiftWeeks reference them indirectly and a cleanup pass
  should confirm nothing breaks before removal.
- **Worker availability grid** (`crew/availability.html`) uses AM/PM
  day columns. This is about worker scheduling preference, not seller
  pickups — leave it unchanged. Daily shifts will use the existing worker
  assignment flow via Crew HQ quick-add.
- **Optimizer** (`_run_optimizer`) is not called by the new flow. It
  remains in `app.py` unchanged — campus directors can still run it
  manually from a direct URL if needed, but it's no longer linked from
  any navigation.
- **`is_tutorial=True` ShiftWeek** created by `seed_tutorial_fixtures()`
  is excluded from all production ops queries. The new `+ New Shift` flow
  filters `is_tutorial=False` in the duplicate guard and ShiftWeek lookup.
- **42/42 SMS tests must continue passing.** The SMS copy changes are
  additive (branching on slot value) — tests for `slot='am'/'pm'` paths
  are unaffected.
