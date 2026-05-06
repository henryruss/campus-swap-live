# Feature Spec: Admin Availability Override — Crew HQ Worker Card Modal

## Goal

Allow admin to temporarily unblock a worker's availability for the current
week by clicking their name on a Crew HQ worker card. Opens a modal showing
their availability grid for this week — admin can toggle cells and save.
The save upserts a `WorkerAvailability` record for the current week, which
becomes the authoritative availability used by the optimizer and the
`+ Add Worker` dropdown filter.

---

## UX Flow

1. Admin is on `/admin/crew` (Crew HQ)
2. Admin clicks a worker's **name** on their card
3. A modal opens showing:
   - Worker name as modal title
   - Their availability grid for the **current calendar week** — 7 columns
     (Mon–Sun), 2 rows (AM/PM), tap-to-toggle cells (green = available,
     grey = blacked out)
   - Grid is pre-filled from their most recent `WorkerAvailability` record
     (week-specific record if one exists, else application record
     `week_start=NULL`, else all-green fallback)
   - A "Save" button and a "Cancel" link
4. Admin toggles any cells they want to unblock (or re-block)
5. Admin clicks Save → POST to new route → upserts `WorkerAvailability` for
   `(worker_id, current_week_start)`
6. Modal closes, page reloads, worker card mini-grid reflects the update,
   worker now appears in the `+ Add Worker` dropdown for newly unblocked slots

---

## New Route

| Method | Path | Function | Description |
|--------|------|----------|-------------|
| `POST /admin/crew/worker/<user_id>/availability` | `admin_crew_override_availability` | Upsert WorkerAvailability for current week with admin-submitted grid values |

### Logic

```python
@app.route('/admin/crew/worker/<int:user_id>/availability', methods=['POST'])
@login_required
def admin_crew_override_availability(user_id):
    if not current_user.is_admin:
        abort(403)

    worker = User.query.get_or_404(user_id)
    if not worker.is_worker:
        abort(404)

    week_start = _today_eastern() - timedelta(days=_today_eastern().weekday())

    # Upsert: find existing record for this week or create new
    avail = WorkerAvailability.query.filter_by(
        user_id=worker.id,
        week_start=week_start
    ).first()

    if not avail:
        avail = WorkerAvailability(user_id=worker.id, week_start=week_start)
        db.session.add(avail)

    # Read 14 boolean fields from form (unchecked = False, checked = True)
    for day in ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']:
        for slot in ['am', 'pm']:
            field = f'{day}_{slot}'
            setattr(avail, field, field in request.form)

    db.session.commit()

    week_id = request.form.get('week_id')
    flash(f'Availability updated for {worker.full_name}.', 'success')

    redirect_url = url_for('admin_crew_panel')
    if week_id:
        redirect_url += f'?week_id={week_id}'
    return redirect(redirect_url)
```

---

## No Model Changes

`WorkerAvailability` already supports `week_start` as a date (Monday of the
week). Writing a record with `week_start = current Monday` is identical to
what the worker does when they submit their own weekly update. No migration
needed.

---

## Template Changes

### `admin/crew.html` — Worker Cards

**Make worker name a clickable trigger:**

```html
<!-- BEFORE: -->
<h3 class="worker-name">{{ worker.full_name }}</h3>

<!-- AFTER: -->
<button
  class="worker-name-btn"
  data-worker-id="{{ worker.id }}"
  data-worker-name="{{ worker.full_name }}"
  data-week-id="{{ displayed_week.id if displayed_week else '' }}"
  onclick="openAvailModal(this)"
>
  {{ worker.full_name }}
</button>
```

**Add modal (once, outside the card grid, inside the page):**

```html
<div id="avail-modal" class="modal-overlay" style="display:none">
  <div class="modal-box">
    <h3 id="avail-modal-title">Edit Availability</h3>
    <p class="modal-subtitle">Current week only. Overrides worker's submitted availability.</p>

    <form method="POST" id="avail-modal-form">
      <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
      <input type="hidden" name="week_id" id="avail-modal-week-id" value="">

      <table class="avail-grid-admin">
        <thead>
          <tr>
            <th></th>
            {% for label in ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'] %}
              <th>{{ label }}</th>
            {% endfor %}
          </tr>
        </thead>
        <tbody>
          {% for slot in ['am', 'pm'] %}
          <tr>
            <td class="slot-label">{{ slot.upper() }}</td>
            {% for day in ['mon','tue','wed','thu','fri','sat','sun'] %}
              {% set field = day + '_' + slot %}
              <td>
                <input
                  type="checkbox"
                  name="{{ field }}"
                  id="avail_{{ field }}"
                  class="avail-checkbox"
                  data-field="{{ field }}"
                >
                <label for="avail_{{ field }}" class="avail-cell-label"></label>
              </td>
            {% endfor %}
          </tr>
          {% endfor %}
        </tbody>
      </table>

      <div class="modal-actions">
        <button type="submit" class="btn btn-primary">Save</button>
        <a href="#" class="btn-link" onclick="closeAvailModal()">Cancel</a>
      </div>
    </form>
  </div>
</div>
```

**JavaScript (add to bottom of template, vanilla JS only):**

```javascript
// Availability data keyed by worker_id, injected from route
const workerAvailability = {{ worker_avail_json | tojson }};

function openAvailModal(btn) {
  const workerId = btn.dataset.workerId;
  const workerName = btn.dataset.workerName;
  const weekId = btn.dataset.weekId;
  const avail = workerAvailability[workerId] || {};

  document.getElementById('avail-modal-title').textContent = workerName;
  document.getElementById('avail-modal-week-id').value = weekId;
  document.getElementById('avail-modal-form').action =
    '/admin/crew/worker/' + workerId + '/availability';

  // Pre-fill checkboxes from worker's current availability
  const fields = ['mon','tue','wed','thu','fri','sat','sun'].flatMap(
    d => [d + '_am', d + '_pm']
  );
  fields.forEach(field => {
    const cb = document.getElementById('avail_' + field);
    if (cb) cb.checked = avail[field] !== false; // default true if missing
  });

  document.getElementById('avail-modal').style.display = 'flex';
}

function closeAvailModal() {
  document.getElementById('avail-modal').style.display = 'none';
}

// Close on backdrop click
document.getElementById('avail-modal').addEventListener('click', function(e) {
  if (e.target === this) closeAvailModal();
});
```

**Note on `data-*` usage:** Worker availability is passed as a flat dict
`{worker_id: {mon_am: true, mon_pm: false, ...}}` injected once into the
page as `worker_avail_json`. This avoids inline `tojson` in `onclick`
attributes (per project rule #8).

---

## Route Changes: `admin_crew_panel` (GET)

Pass `worker_avail_json` to the template — a dict of
`{str(worker.id): avail_dict}` for all approved workers, where `avail_dict`
maps each of the 14 field names to a bool.

```python
# Build availability dict for JS modal pre-fill
AVAIL_FIELDS = [
    f'{d}_{s}'
    for d in ['mon','tue','wed','thu','fri','sat','sun']
    for s in ['am','pm']
]

worker_avail_json = {}
for worker in approved_workers:
    avail = _get_worker_availability_for_week(worker, current_week_start)
    if avail:
        worker_avail_json[str(worker.id)] = {
            f: getattr(avail, f) for f in AVAIL_FIELDS
        }
    else:
        # No record — treat as all available
        worker_avail_json[str(worker.id)] = {f: True for f in AVAIL_FIELDS}
```

---

## CSS (add to `static/style.css`)

```css
.worker-name-btn {
  background: none;
  border: none;
  padding: 0;
  font: inherit;
  font-weight: 600;
  color: var(--primary);
  cursor: pointer;
  text-decoration: underline;
  text-decoration-style: dotted;
  text-underline-offset: 3px;
}
.worker-name-btn:hover {
  color: var(--primary-dark, var(--primary));
}

.avail-grid-admin {
  border-collapse: collapse;
  width: 100%;
  margin: 12px 0 20px;
}
.avail-grid-admin th {
  font-size: 12px;
  color: var(--text-muted);
  text-align: center;
  padding: 4px;
}
.avail-grid-admin td {
  text-align: center;
  padding: 2px;
}
.avail-grid-admin .slot-label {
  font-size: 11px;
  color: var(--text-muted);
  text-align: right;
  padding-right: 8px;
  font-weight: 500;
}

/* Hide actual checkbox, style the label as a colored cell */
.avail-checkbox {
  display: none;
}
.avail-cell-label {
  display: block;
  width: 28px;
  height: 20px;
  border-radius: 3px;
  background: #e0e0e0;
  cursor: pointer;
  margin: 0 auto;
  transition: background 0.15s;
}
.avail-checkbox:checked + .avail-cell-label {
  background: #c8e6c9;
}
```

---

## Constraints

- No migration — `WorkerAvailability` already supports week-scoped records.
- The upsert uses `week_start = current Monday` (via `_today_eastern()`),
  same as the worker's own weekly submission route.
- Do not modify `_worker_available_for_slot` or `_get_worker_availability_for_week`
  — they already read the most recent week-specific record, so the override
  is picked up automatically once saved.
- Do not modify the worker-facing `/crew/availability` route — workers can
  still submit their own updates; admin override just writes the same table.
- Modal pre-fill uses `workerAvailability` JS dict injected once at page
  render — no fetch required to open the modal.
- `data-*` attributes used for all data passed to JS (no inline `tojson`
  in event handlers).
