# Mini-Spec: Worker Shift Preview (Read-Only + Double-Shift Navigation)

**Status:** Ready for implementation
**Dependency:** Spec #3 (complete)

---

## Goal

Two problems:

1. Workers can't preview a future assigned shift at all — navigating to `/crew/shift/<id>` redirects them away. They should be able to see their stops, co-workers, and item photos ahead of time.
2. When a worker is assigned to both AM and PM on the same day, only the AM shift is reachable from My Schedule (slots are merged into a single pill). They need to navigate between both.

---

## UX Flow

### Fix 1 — Future Shift Preview

1. Worker taps a shift row in My Schedule → navigates to `/crew/shift/<id>`.
2. Route detects: `shift_date > today_eastern` and `shift.run is None` → renders in **preview mode** instead of redirecting.
3. Preview mode shows:
   - Shift header: day, date, slot (AM/PM), truck number, co-worker name(s) on same truck.
   - A prominent info banner: **"Preview — your shift is on [Weekday, Month D]. Actions are disabled until the day of."**
     Style: `--bg-cream` background, `--primary` border-left (same pattern as the existing "not today" warning banner).
   - Stop list (if stops assigned): seller name, address, item count, access type badge (stairs/elevator), item photo strip. Workers benefit from seeing item photos before arrival — do not suppress.
   - If no stops yet: "Stops haven't been assigned yet — check back closer to your shift date."
   - **All action buttons hidden:** no Start Shift, no Completed/Issue, no End Shift.
   - **"Preview next shift →" button** at bottom of page if a same-day PM shift exists (see Fix 2).
   - Auto-refresh (`setInterval`) disabled — no polling needed for future shifts.
4. On the day of the shift, the page transitions to normal pre-start / in-progress behavior — no change to existing logic.

### Fix 2 — Same-Day Double-Shift Navigation

**Dashboard (`/crew`):**

My Schedule currently groups same-day shifts into merged slot pills linked to a single shift. When a worker has both AM and PM on the same day, each slot needs its own independent link.

- If a worker has **one** shift on a day: render as a single linked row (unchanged).
- If a worker has **two** shifts on a day (AM + PM): render **two separate rows** for that day, each with its own slot badge (amber "AM", blue "PM") and its own link to `/crew/shift/<id>`. Do not merge.

**Shift page (`/crew/shift/<id>`):**

At the bottom of the shift page, add a **"Preview next shift →"** button when all of the following are true:
- The current shift is AM slot.
- The worker has a PM shift assignment on the same calendar date.
- The PM shift has not yet started (`next_shift.run is None` or `next_shift.run.status != 'in_progress'`).

Button label: **"Preview [Day] PM shift →"** (e.g. "Preview Tuesday PM shift →").
Behavior: navigates to `/crew/shift/<pm_shift_id>`.

The symmetric case — "← Back to AM shift" from the PM page — is not needed; the dashboard already provides navigation back.

### Edge Cases

- Worker not assigned to shift → existing 403, unchanged.
- Past shift → existing behavior (retroactive complete, etc.), unchanged.
- Shift is today, no `ShiftRun` yet → existing pre-start state, unchanged.
- Shift is today, `ShiftRun` exists → existing in-progress state, unchanged.
- No stops assigned on a future shift → show "check back" message (same copy as pre-start "no stops" state).
- Worker assigned to AM only (no PM that day) → no "Preview next shift" button.
- Worker assigned to PM only → no button needed (no "next" shift that day).
- PM shift is already in-progress when viewing AM → do not show "Preview next shift" button; worker is actively on the PM shift and the dashboard banner handles that case.
- Worker on AM + PM, AM is a future date → preview mode applies to AM; "Preview next shift →" button still shown if PM assignment exists.

---

## New Routes

None. All changes are inside existing routes and templates.

---

## Model Changes

None. No migration needed.

---

## Route Changes

### `crew_shift_view` (`GET /crew/shift/<shift_id>`)

**Remove** the existing redirect that fires when `shift_date > today_eastern` and `shift.run is None`.

**Replace with** `is_preview = True` when all three hold:
- `shift_date > _today_eastern()` (strictly future — not today)
- `shift.run is None`
- Worker is assigned to this shift (403 check already runs first, unchanged)

**Add** computation of `next_shift`:
- If `current_shift.slot == 'am'`: query for a `Shift` on the same `week_id` + `day_of_week` with `slot == 'pm'` that the current worker is also assigned to via `ShiftAssignment`.
- If `current_shift.slot == 'pm'` or no same-day PM assignment found: `next_shift = None`.
- Gate the button on `next_shift is not None` **and** `(next_shift.run is None or next_shift.run.status != 'in_progress')`.

Pass to template: `is_preview`, `next_shift`.

---

## Template Changes

### `templates/crew/shift.html`

**1. Preview banner** — render at top when `is_preview`:
```
[info icon]  Preview — your shift is on [Weekday, Month D].
Actions are available on the day of the shift.
```
Style: `--bg-cream` background, `--primary` left border. Same visual as the existing "not today" warning banner. That banner should be **removed** — preview mode supersedes it.

**2. Start Shift button** — already gated on `not shift.run and stops`. Add `and not is_preview` to that condition.

**3. Stop cards** — render normally in preview mode. Completed/Issue action buttons are already absent when `shift.run` is None — no additional hiding needed.

**4. Photo strip** — render in preview mode. Workers need to see item photos ahead of pickup. If the photo strip is currently gated on `shift.run` existing, remove that gate so it shows in pre-start and preview states alike.

**5. Auto-refresh** — wrap the `setInterval` block polling `/crew/shift/<id>/stops_partial` in `{% if not is_preview %}`.

**6. "Preview next shift →" button** — render at the bottom of the page when `next_shift` is not None:
```html
<a href="{{ url_for('crew_shift_view', shift_id=next_shift.id) }}" class="btn btn-secondary">
  Preview {{ next_shift.label }} shift →
</a>
```
Position: below the stop list, above the footer.

### `templates/crew/dashboard.html`

In the My Schedule section, change same-day shift rendering:

- **One shift on a day** → single row, unchanged.
- **Two shifts on a day** → two separate rows, each independently linked to `/crew/shift/<id>` with its own slot badge (amber "AM", blue "PM"). Do not merge into a single pill/row when both AM and PM are assigned.

The `my_shifts` list passed from `crew_dashboard()` already contains one tuple per shift — no route change needed. The fix is purely in how the template groups or iterates over that list.

---

## Business Logic

- `is_preview` is computed in `crew_shift_view` and never stored.
- No POST routes are touched — `crew_shift_start`, `crew_shift_stop_update`, and `crew_shift_end` already reject future-shift requests independently.
- `next_shift` query: filter `Shift` joined to `ShiftAssignment` where `week_id == current_shift.week_id`, `day_of_week == current_shift.day_of_week`, `slot == 'pm'`, `ShiftAssignment.worker_id == current_user.id`. One extra query per page load; negligible at current data volume.

---

## Constraints

- Do not touch any POST routes.
- Do not change behavior for today's shifts or past shifts.
- Do not change the 403 for unassigned workers.
- No new routes, no DB changes, no migration.
- The existing "not today" warning banner should be removed (preview mode supersedes it) — if removal feels risky, suppressing it with `{% if not is_preview %}` is an acceptable alternative.
