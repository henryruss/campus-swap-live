# Feature Spec: Crew HQ — `/admin/crew` Redesign

## Goal

Replace the current flat crew page (pending applications + approved workers table) with a unified **Crew HQ** — a fast dispatch board that lets admin see all workers, their availability, and this week's shift assignments in one place, and reassign workers between shifts in a few clicks without navigating to the schedule builder.

The schedule builder at `/admin/schedule/<week_id>` is **not changed**. Crew HQ is a fast-tweak layer on top of it for day-to-day assignment work.

---

## UX Flow

### Page Layout (top to bottom)

**Section 1: Worker Cards**
One card per approved worker. Always shows the **current calendar week** regardless of which week is displayed in the shift board below.

Each card shows:
- Worker name + role badge (`BOTH` / `DRIVER` / `ORGANIZER`)
- Shifts assigned this week as small pills (e.g. `Tue AM · Thu PM`). If no shifts this week, show "No shifts this week" in muted text.
- Mini 7×2 availability grid (read-only). Columns = Mon–Sun, rows = AM/PM. Green cell = available, grey cell = blacked out. Uses the worker's most recent `WorkerAvailability` record (weekly update if one exists for this `week_start`, else application record `week_start=NULL`, else all-green fallback).

Cards are laid out in a responsive grid (2-up on desktop, 1-up on mobile).

**Section 2: Shift Board**
Header row: `← Week of [Mon date] →` with prev/next arrows. Default to the nearest upcoming `ShiftWeek` that has at least one `Shift` record. If none upcoming, show the most recent past week. If no weeks exist at all, show an empty state with a link to `/admin/schedule`.

Each shift in the displayed week renders as a row:
- **Left:** Day label + AM/PM pill (e.g. `Tuesday · AM`), date in muted text, truck count
- **Middle:** Assigned workers as name badges. Each badge has an `×` button to remove that worker. Workers assigned as `driver` show a steering wheel icon (🚗 or a simple `D` badge); organizers show an `O` badge.
- **Right:** `+ Add Worker` button — opens an inline dropdown listing workers who are (a) not blacked out for this shift's slot, and (b) not already assigned to this shift. Clicking a name immediately POSTs to add them. If all workers are already assigned or unavailable, show "All workers assigned."
- **Re-notify flag:** If `shift.last_notified_at` is set AND any assignment was added or removed after `last_notified_at`, show an amber `⚠ Re-notify needed` badge on that row. This is display-only — admin clicks through to the ops page to send notifications.

Below the shift list, a secondary `Run Optimizer` button runs the existing optimizer for the displayed week and reloads the page.

**Section 3: Applications**
Collapsible `<details>` section, collapsed by default if there are 0 pending applications, expanded if there are pending applications. Same UI as today — expand per applicant, read-only availability grid, approve/reject buttons.

---

## New Routes

| Method | Path | Function | Description |
|--------|------|----------|-------------|
| `GET /admin/crew` | `admin_crew_panel` | Replaces existing route. Accepts optional `?week_id=<id>` query param to display a specific week in the shift board. |
| `POST /admin/crew/shift/<shift_id>/quick-add` | `admin_crew_quick_add` | Add a worker to a shift from Crew HQ. Accepts `worker_id` and `role` (driver/organizer) as form fields. Returns redirect to `GET /admin/crew?week_id=<week_id>#shift-<shift_id>`. |
| `POST /admin/crew/shift/<shift_id>/quick-remove` | `admin_crew_quick_remove` | Remove a worker from a shift from Crew HQ. Accepts `assignment_id` as form field. Returns redirect to `GET /admin/crew?week_id=<week_id>#shift-<shift_id>`. Does NOT send any email. Sets no flags beyond what already exists (`last_notified_at` stays set, which surfaces the re-notify warning naturally). |

**Prev/Next week navigation** is implemented as plain `<a href="/admin/crew?week_id=<id>">` links. The route resolves prev/next week IDs at render time and passes them to the template. No JS required.

**Optimizer** reuses the existing `POST /admin/schedule/<week_id>/optimize` route. The "Run Optimizer" button on Crew HQ submits to that route with a hidden `next` field pointing back to `/admin/crew?week_id=<week_id>`. The existing optimize route must be updated to redirect to `request.form.get('next')` if present, otherwise fall back to the existing redirect.

---

## Model Changes

**No new models or migrations required.**

All data needed already exists:
- `WorkerAvailability` — availability grid data
- `ShiftAssignment` — who is on which shift, in which role
- `ShiftWeek` / `Shift` — week and shift records
- `Shift.last_notified_at` — already set by `admin_shift_notify_sellers`

The only new write operations are:
- `admin_crew_quick_add` — creates a `ShiftAssignment` record (same as `admin_shift_update` does today)
- `admin_crew_quick_remove` — deletes a `ShiftAssignment` record by `assignment_id`

---

## Template Changes

### Modified: `templates/admin/crew.html`

Full replacement of the existing template. Must extend `admin_layout.html` (not `layout.html`). Structure:

```
{% extends "admin/admin_layout.html" %}
{% block content %}

<!-- Section 1: Worker Cards -->
<section class="crew-hq-workers">
  <h2>Workers</h2>
  <div class="worker-card-grid">
    {% for worker in approved_workers %}
      <!-- card: name, role badge, shift pills, mini availability grid -->
    {% endfor %}
  </div>
</section>

<!-- Section 2: Shift Board -->
<section class="crew-hq-shifts">
  <div class="shift-board-header">
    {% if prev_week %}
      <a href="/admin/crew?week_id={{ prev_week.id }}">←</a>
    {% else %}
      <span class="arrow-disabled">←</span>
    {% endif %}
    <h2>Week of {{ displayed_week.week_start | format_date }}</h2>
    {% if next_week %}
      <a href="/admin/crew?week_id={{ next_week.id }}">→</a>
    {% else %}
      <span class="arrow-disabled">→</span>
    {% endif %}
  </div>

  {% if shifts %}
    {% for shift in shifts %}
      <div class="shift-row" id="shift-{{ shift.id }}">
        <!-- label, assigned workers with × forms, + Add dropdown, re-notify flag -->
      </div>
    {% endfor %}
  {% else %}
    <p>No shifts for this week. <a href="/admin/schedule">Manage schedules →</a></p>
  {% endif %}

  <!-- Run Optimizer -->
  <form method="POST" action="/admin/schedule/{{ displayed_week.id }}/optimize">
    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
    <input type="hidden" name="next" value="/admin/crew?week_id={{ displayed_week.id }}">
    <button type="submit" class="btn btn-secondary">Run Optimizer</button>
  </form>
</section>

<!-- Section 3: Applications -->
<details {% if pending_applications %}open{% endif %} class="crew-hq-applications">
  <summary>Pending Applications ({{ pending_applications | length }})</summary>
  <!-- existing application expand/approve/reject UI unchanged -->
</details>

{% endblock %}
```

**Mini availability grid** — rendered as a small inline table of colored `<span>` cells. Reuse the same green/grey color logic as the existing read-only admin grid in the current `crew.html`. Does NOT include the JS toggle (this is read-only). One row per slot (AM/PM), 7 columns (Mon–Sun). Day labels abbreviated (M T W T F S S).

**Re-notify flag logic** — computed in the route, not in the template. Pass a set `shifts_needing_renotify` (set of shift IDs) to the template. Template checks `{% if shift.id in shifts_needing_renotify %}`.

**`+ Add Worker` dropdown** — rendered as a `<select>` + submit button inside a small `<form>` that POSTs to `admin_crew_quick_add`. The `<select>` is populated with available workers (filtered in the route). If empty, render a disabled `<select>` with a single option "No workers available."

**Role assignment on quick-add** — the add form includes a `<select name="role">` with options `driver` / `organizer`. Default to `driver`. This keeps the new route simple and avoids guessing.

---

## Business Logic

### `admin_crew_panel` (GET)

```python
# Determine displayed week
week_id = request.args.get('week_id', type=int)
if week_id:
    displayed_week = ShiftWeek.query.get_or_404(week_id)
else:
    # nearest upcoming week with shifts, else most recent past, else None
    displayed_week = _get_nearest_week_with_shifts()

# Prev/next weeks (only weeks that have shifts)
prev_week, next_week = _get_adjacent_weeks(displayed_week)

# Shifts for displayed week, sorted by sort_key
shifts = Shift.query.filter_by(week_id=displayed_week.id, is_active=True)
         .order_by(Shift.sort_key).all() if displayed_week else []

# Approved workers
approved_workers = User.query.filter_by(is_worker=True, worker_status='approved').all()

# Current calendar week (for worker card shift pills — NOT displayed_week)
current_week_start = _today_eastern() - timedelta(days=_today_eastern().weekday())
current_week_end = current_week_start + timedelta(days=6)

# Per-worker: shifts this (calendar) week + availability
for worker in approved_workers:
    worker._week_shifts = ShiftAssignment.query.join(Shift).filter(
        ShiftAssignment.worker_id == worker.id,
        Shift.is_active == True
    ).join(ShiftWeek).filter(
        ShiftWeek.week_start == current_week_start
    ).all()
    worker._availability = _get_worker_availability_for_week(worker, current_week_start)

# Per-shift: assignments + available workers for dropdown
for shift in shifts:
    shift._assignments = ShiftAssignment.query.filter_by(shift_id=shift.id).all()
    assigned_ids = {a.worker_id for a in shift._assignments}
    shift._available_workers = [
        w for w in approved_workers
        if w.id not in assigned_ids
        and _worker_available_for_slot(w, shift, displayed_week.week_start)
    ]

# Re-notify flags: shift has last_notified_at AND any assignment
# was created/deleted after last_notified_at
# Deletions can't be tracked after the fact, so we track adds:
# ShiftAssignment.assigned_at > shift.last_notified_at
shifts_needing_renotify = set()
for shift in shifts:
    if shift.last_notified_at:
        late_add = any(
            a.assigned_at > shift.last_notified_at
            for a in shift._assignments
        )
        if late_add:
            shifts_needing_renotify.add(shift.id)
```

**Note on removal re-notify:** When a worker is removed via `admin_crew_quick_remove`, we cannot retroactively mark the shift. Instead, add a `crew_hq_last_modified_at` timestamp to `Shift` — **wait, no new migrations.** Use a simpler approach: the re-notify flag shows if any current assignment's `assigned_at > shift.last_notified_at`. Removals are not tracked (no new field). This is acceptable — admin will see the flag when they add someone new post-notify, and can choose to re-notify or not. Document this limitation in a template comment.

### `admin_crew_quick_add` (POST)

```python
shift = Shift.query.get_or_404(shift_id)
worker_id = int(request.form['worker_id'])
role = request.form.get('role', 'driver')  # 'driver' or 'organizer'

# Guard: worker not already on this shift
existing = ShiftAssignment.query.filter_by(
    shift_id=shift_id, worker_id=worker_id
).first()
if existing:
    flash('Worker already assigned to this shift.', 'warning')
    return redirect(...)

# Guard: valid role value
if role not in ('driver', 'organizer'):
    role = 'driver'

assignment = ShiftAssignment(
    shift_id=shift_id,
    worker_id=worker_id,
    role_on_shift=role,
    assigned_at=_now_eastern(),
    assigned_by_id=current_user.id,
    truck_number=None  # admin can assign truck from ops page
)
db.session.add(assignment)
db.session.commit()

week_id = shift.week_id
return redirect(url_for('admin_crew_panel', week_id=week_id) + f'#shift-{shift_id}')
```

### `admin_crew_quick_remove` (POST)

```python
assignment_id = int(request.form['assignment_id'])
assignment = ShiftAssignment.query.get_or_404(assignment_id)
shift = assignment.shift
week_id = shift.week_id

db.session.delete(assignment)
db.session.commit()

# No email sent. Re-notify flag will NOT auto-appear for removals
# (no new fields). Admin should check the ops page to re-notify.
flash(f'Worker removed from {shift.label}.', 'success')
return redirect(url_for('admin_crew_panel', week_id=week_id) + f'#shift-{shift.id}')
```

### `_get_nearest_week_with_shifts` (new helper)

```python
def _get_nearest_week_with_shifts():
    today = _today_eastern()
    # Upcoming (nearest first)
    upcoming = ShiftWeek.query.filter(ShiftWeek.week_start >= today)\
        .order_by(ShiftWeek.week_start.asc()).first()
    if upcoming:
        return upcoming
    # Most recent past
    return ShiftWeek.query.order_by(ShiftWeek.week_start.desc()).first()
```

### `_get_adjacent_weeks` (new helper)

```python
def _get_adjacent_weeks(current_week):
    if not current_week:
        return None, None
    prev = ShiftWeek.query.filter(
        ShiftWeek.week_start < current_week.week_start
    ).order_by(ShiftWeek.week_start.desc()).first()
    next_ = ShiftWeek.query.filter(
        ShiftWeek.week_start > current_week.week_start
    ).order_by(ShiftWeek.week_start.asc()).first()
    return prev, next_
```

### Optimizer redirect (modify existing route)

In `admin_schedule_optimize`:
```python
# After optimizer runs and redirect is determined:
next_url = request.form.get('next')
if next_url and next_url.startswith('/admin/'):
    return redirect(next_url)
# else existing redirect logic unchanged
```

---

## Template: Availability Grid Rendering

The mini grid in each worker card is a self-contained Jinja block. It does NOT use the `_availability_grid.html` partial (which has interactive JS). Render inline as colored `<span>` or `<td>` cells.

Days: `['M','T','W','T','F','S','S']` (abbreviated headers)
Slots: `am`, `pm`
Field names: `mon_am`, `mon_pm`, `tue_am` ... `sun_pm`

For each cell, check `avail.<field_name>` — if `True` or if availability record is `None`, render green. If `False`, render grey.

```html
<table class="mini-avail-grid">
  <tr>
    <th></th>
    {% for day_label in ['M','T','W','T','F','S','S'] %}
      <th>{{ day_label }}</th>
    {% endfor %}
  </tr>
  {% for slot in ['am', 'pm'] %}
  <tr>
    <td class="slot-label">{{ slot|upper }}</td>
    {% for day_key in ['mon','tue','wed','thu','fri','sat','sun'] %}
      {% set field = day_key + '_' + slot %}
      {% set available = avail[field] if avail else True %}
      <td class="avail-cell {% if available %}avail-green{% else %}avail-grey{% endif %}"></td>
    {% endfor %}
  </tr>
  {% endfor %}
</table>
```

CSS (add to `static/style.css`):
```css
.mini-avail-grid {
  border-collapse: collapse;
  font-size: 10px;
  margin-top: 8px;
}
.mini-avail-grid th, .mini-avail-grid td {
  width: 18px;
  height: 14px;
  text-align: center;
  padding: 0;
}
.mini-avail-grid .slot-label {
  color: var(--text-muted);
  font-size: 9px;
  padding-right: 4px;
}
.avail-cell.avail-green { background: #c8e6c9; border-radius: 2px; }
.avail-cell.avail-grey  { background: #e0e0e0; border-radius: 2px; }
```

---

## Constraints

1. **Do not modify** `admin_shift_update`, `admin_shift_swap`, `admin_schedule_optimize`, or any existing schedule builder routes beyond the single `next` redirect addition to `admin_schedule_optimize`.
2. **Do not modify** `admin_crew_approve` or `admin_crew_reject` routes.
3. **No migrations.** All reads and writes use existing model fields.
4. **No automatic emails** on quick-add or quick-remove.
5. **Server-rendered only.** The `+ Add Worker` dropdown and × remove buttons are plain HTML forms. No fetch/AJAX.
6. **Use CSS variables** from `static/style.css` throughout. Never hardcode colors.
7. **Extend `admin_layout.html`**, not `layout.html`.
8. **Anchor navigation** — both `admin_crew_quick_add` and `admin_crew_quick_remove` redirect back to `#shift-<id>` so the page scrolls to the relevant shift after the POST.
9. **`_get_worker_availability_for_week` already exists** — reuse it. Do not reimplement availability lookup.
10. **`_worker_available_for_slot` already exists** — reuse it for filtering the add dropdown.
