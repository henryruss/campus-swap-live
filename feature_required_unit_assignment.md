# Feature Spec: Required Unit Assignment with Visual Picker

## Goal

Unit assignment for trucks is currently optional and often skipped, with the destination communicated out-of-band (text messages). This creates operational gaps: drivers don't have a canonical record of where to go, and the system has no awareness of warehouse capacity when building routes.

This spec makes unit assignment a first-class part of route setup by:
1. Replacing the dropdown on the ops page with a **visual unit picker card grid** (matching the warehouse floor aesthetic) that shows live capacity state
2. **Requiring** a unit to be assigned before the first seller stop can be added to any truck
3. **Prefilling the destination unit** in the driver's placement step at end of shift, so drivers always know exactly where to bring items
4. Showing a soft warning (not a hard block) when assigning a truck to a full unit

---

## UX Flow

### A — Explicit "Assign Unit" button (truck card header, no stops yet)

1. Admin opens the Ops page for a shift. Each truck card header shows a prominent **"Assign Unit"** button (amber, since unassigned is the action-needed state) in place of the current dropdown.
2. Admin clicks **"Assign Unit"**. A modal opens: **Unit Picker**.
3. The Unit Picker modal shows a card grid of all active storage locations, sorted by: available first (non-full), then full. Within each group, sorted by name.
4. Each unit card shows:
   - **Unit name** (large, e.g. "Unit 503")
   - **Capacity note** (e.g. "10×20") — from `StorageLocation.capacity_note`
   - **Item count** (e.g. "16 items")
   - **Battery bar** — same `_battery_macro.html` used on the warehouse floor
   - **"Full" badge** in red if `is_full=True`
5. If a unit is `is_full=True`, its card is rendered with a muted/greyed style and shows a **"⚠ Full — assign anyway?"** inline warning label. It is **selectable** (not disabled).
6. Admin clicks a unit card. If the unit is full, a **confirmation step** appears inside the modal: *"Unit 503 is marked full. Assign anyway?"* with Confirm and Cancel buttons.
7. On confirm (or immediate selection if not full): modal closes, unit chip updates on the truck card header to green with the unit name. The assignment is saved via `POST /admin/crew/shift/<shift_id>/truck/<truck_number>/assign_unit` (existing route, unchanged behavior).
8. If admin re-opens the picker after a unit is already assigned, the currently assigned card is highlighted with a selected ring. Picking a different card reassigns freely (no warning needed — free reassignment was explicitly decided).

### B — Implicit gate: adding first stop with no unit assigned

1. Admin tries to add the first seller stop to a truck (via the unassigned panel assign form) on a truck that has no unit assigned.
2. Instead of processing the stop, the system **opens the Unit Picker modal** with a banner: *"Assign a destination unit before adding stops to Truck N."*
3. After admin selects a unit and confirms, the modal closes and the **stop assignment proceeds automatically** — the form submission that was blocked is re-submitted after the unit saves successfully.
4. If admin dismisses the modal without picking a unit, the stop is not added and a brief inline message appears: *"A destination unit is required before adding stops."*

### C — Reassignment (unit already assigned, admin wants to change)

1. The truck card header shows the assigned unit as a green chip with a small pencil/edit icon.
2. Clicking the chip (or a separate "Change" link) opens the Unit Picker modal with the current unit highlighted.
3. Admin picks a new unit. Assignment saves. The chip updates. All pending `ShiftPickup` records for that truck have their `storage_location_id` updated (existing behavior of `admin_shift_assign_unit`). Completed stops are NOT updated (existing behavior, unchanged).

### D — Driver shift view (crew/shift/<id>)

1. The driver's shift view currently shows their stop list. At the top of the page, a new **destination banner** is added:
   ```
   📦 Drop off at: Unit 503
   ```
   Shown as a prominent, pinned strip just below the shift header. If no unit is assigned, this strip is omitted entirely (no error, no placeholder).
2. This uses the unit from `Shift.truck_unit_plan` for the driver's truck number. No new model field needed.

### E — Driver placement prefill (crew/shift_placement_partial)

1. When the driver reaches the placement step (before End Shift), the **"Select Unit" dropdown in the placement modal is prefilled** with the truck's assigned unit from `truck_unit_plan`.
2. The driver can still open the dropdown and change to a different unit if needed (soft prefill, not locked).
3. If no unit is assigned to the truck, the dropdown behaves as it does today (no prefill, empty default).

---

## New Routes

None. All backend behavior uses the existing `admin_shift_assign_unit` route.

---

## Modified Routes

### `POST /admin/crew/shift/<shift_id>/truck/<truck_number>/assign_unit` — no logic change

This route already writes to `Shift.truck_unit_plan` and syncs to pending `ShiftPickup.storage_location_id`. No changes to the backend logic. The only change is that this route is now also called from the new modal JS before re-attempting a blocked stop assignment.

### `POST /admin/crew/shift/<shift_id>/assign` (`admin_shift_assign_seller`) — add gate

Add a pre-check at the top of the route:

```python
# Gate: unit must be assigned before first stop on this truck
truck_number = int(request.form.get('truck_number') or request.json.get('truck_number'))
plan = json.loads(shift.truck_unit_plan or '{}')
existing_stops = ShiftPickup.query.filter_by(
    shift_id=shift.id, truck_number=truck_number
).count()
if existing_stops == 0 and str(truck_number) not in plan:
    return jsonify({'error': 'unit_required', 'truck_number': truck_number}), 422
```

The `422` response with `error: 'unit_required'` is the signal to the frontend to open the Unit Picker modal before retrying.

---

## Model Changes

**None.** No new fields, no migration.

- Unit assignment already stored in `Shift.truck_unit_plan` (JSON, existing field)
- `ShiftPickup.storage_location_id` already synced by existing route
- `StorageLocation` already has `is_full`, `snapshot_capacity`, `capacity_note`, `items` relationship

---

## Template Changes

### `templates/admin/ops.html`

**Truck card header — current state:**
Each truck card has a destination unit dropdown (rendered as a `<select>`).

**New state:**
Replace the `<select>` dropdown with:

```html
<!-- Unassigned state -->
<button class="btn-assign-unit" 
        data-shift-id="{{ shift.id }}" 
        data-truck="{{ truck_num }}">
  + Assign Unit
</button>

<!-- Assigned state -->
<button class="unit-assigned-chip"
        data-shift-id="{{ shift.id }}"
        data-truck="{{ truck_num }}">
  <span class="unit-chip-icon">📦</span>
  <span class="unit-chip-name">{{ assigned_unit.name }}</span>
  <span class="unit-chip-edit">✎</span>
</button>
```

The assigned state is computed in the route from `truck_unit_plan` and the `StorageLocation` lookup. Pass a `truck_unit_map` dict to the template: `{truck_number: StorageLocation or None}`.

**Unit Picker Modal** — new modal at the bottom of `ops.html` (one modal, reused for all trucks):

```html
<div id="unit-picker-modal" class="modal-overlay" hidden>
  <div class="modal-panel unit-picker-panel">
    <div class="modal-header">
      <h3 id="unit-picker-title">Assign Destination Unit</h3>
      <button class="modal-close" data-action="close-unit-picker">✕</button>
    </div>
    <p id="unit-picker-subtext" class="text-muted"></p>  {# populated by JS #}
    <div id="unit-picker-grid" class="unit-picker-grid">
      {# Populated via fetch to GET /admin/ops/unit-picker-partial #}
    </div>
    <div id="unit-picker-confirm" hidden>
      {# Confirmation step for full units — populated by JS #}
    </div>
  </div>
</div>
```

The grid content is fetched once on first modal open (lazy) and cached in the DOM. Unit selection is handled entirely by JS event delegation on `data-unit-id` attributes.

### New partial: `templates/admin/ops_unit_picker_partial.html`

No layout. Renders the card grid. One card per active `StorageLocation`:

```html
{% for loc in locations %}
<div class="unit-picker-card {% if loc.is_full %}unit-picker-card--full{% endif %}"
     data-unit-id="{{ loc.id }}"
     data-unit-name="{{ loc.name }}"
     data-is-full="{{ 'true' if loc.is_full else 'false' }}">
  <div class="unit-picker-card__header">
    <span class="unit-picker-card__name">{{ loc.name }}</span>
    {% if loc.is_full %}
      <span class="badge badge--red">Full</span>
    {% endif %}
  </div>
  {% if loc.capacity_note %}
    <div class="unit-picker-card__size">{{ loc.capacity_note }}</div>
  {% endif %}
  <div class="unit-picker-card__count">{{ loc.items | selectattr('storage_location_id', 'equalto', loc.id) | list | length }} items</div>
  {{ battery_bar(loc_pct[loc.id], loc.is_full) }}
  {% if loc.is_full %}
    <div class="unit-picker-card__full-warning">⚠ Full — assign anyway?</div>
  {% endif %}
</div>
{% endfor %}
```

Battery percentage computed in the route using `snapshot_capacity` (same logic as warehouse floor).

### New route for the partial

| Method | Path | Function | Description |
|--------|------|----------|-------------|
| `GET` | `/admin/ops/unit-picker-partial` | `admin_ops_unit_picker_partial` | HTML partial. All active StorageLocations with item counts and battery pct. `_has_ops_access()`. |

### `templates/crew/shift.html`

Add destination banner below shift header, above stop list:

```html
{% if destination_unit %}
<div class="driver-destination-banner">
  <span class="destination-icon">📦</span>
  <span class="destination-label">Drop off at:</span>
  <strong class="destination-unit">{{ destination_unit.name }}</strong>
</div>
{% endif %}
```

`destination_unit` is a `StorageLocation` object passed from `crew_shift_view` by reading `truck_unit_plan` for the driver's `truck_number`. If no unit assigned, `destination_unit=None` and the banner is omitted.

### `templates/crew/shift_placement_partial.html`

The "Select Unit" dropdown in the placement modal currently renders all active locations. Change: if a `preferred_unit_id` is passed, render that option first and mark it `selected`. All other options still present (driver can override).

`preferred_unit_id` is passed from the route that renders this partial, derived from `truck_unit_plan[truck_number]`.

---

## Business Logic

### `admin_ops_unit_picker_partial` route

```python
@app.route('/admin/ops/unit-picker-partial')
@_has_ops_access
def admin_ops_unit_picker_partial():
    locations = StorageLocation.query.filter_by(is_active=True).order_by(
        StorageLocation.is_full.asc(),   # available first
        StorageLocation.name.asc()
    ).all()
    
    # Compute battery pct per location (same as warehouse floor logic)
    loc_pct = {}
    for loc in locations:
        item_count = len([i for i in loc.items])
        if loc.snapshot_capacity and loc.snapshot_capacity > 0:
            loc_pct[loc.id] = round((item_count / loc.snapshot_capacity) * 100)
        else:
            loc_pct[loc.id] = None
    
    return render_template(
        'admin/ops_unit_picker_partial.html',
        locations=locations,
        loc_pct=loc_pct
    )
```

### `crew_shift_view` route modification

Add to the existing route that renders `crew/shift.html`:

```python
# Determine destination unit for this driver's truck
destination_unit = None
plan = json.loads(shift.truck_unit_plan or '{}')
truck_num_str = str(current_assignment.truck_number)
if truck_num_str in plan:
    destination_unit = StorageLocation.query.get(plan[truck_num_str])
```

Pass `destination_unit` to `render_template`.

### `crew_shift_placement_partial` route modification

Same pattern — read `truck_unit_plan` for the driver's truck, pass `preferred_unit_id` to the template.

### JS in `ops.html`

Key behaviors (all using `data-*` attributes per project rule #8):

```javascript
// State
let pendingTruckNumber = null;
let pendingStopFormData = null;  // FormData to retry after unit assigned
let pickerLoaded = false;

// Open picker — two entry points
function openUnitPicker(shiftId, truckNumber, { subtext = '', pendingForm = null } = {}) {
  pendingTruckNumber = truckNumber;
  pendingStopFormData = pendingForm;
  document.getElementById('unit-picker-title').textContent = `Assign Unit — Truck ${truckNumber}`;
  document.getElementById('unit-picker-subtext').textContent = subtext;
  document.getElementById('unit-picker-modal').hidden = false;
  if (!pickerLoaded) {
    fetch('/admin/ops/unit-picker-partial')
      .then(r => r.text())
      .then(html => {
        document.getElementById('unit-picker-grid').innerHTML = html;
        pickerLoaded = true;
        // Highlight currently assigned unit if any
        highlightCurrentUnit(shiftId, truckNumber);
      });
  }
}

// Entry point 1: explicit "Assign Unit" button click
document.addEventListener('click', e => {
  const btn = e.target.closest('[data-action="open-unit-picker"]');
  if (!btn) return;
  openUnitPicker(btn.dataset.shiftId, btn.dataset.truck);
});

// Entry point 2: stop assignment blocked (422 unit_required)
// (in the existing stop-assign fetch handler, add):
// if (data.error === 'unit_required') {
//   openUnitPicker(shiftId, data.truck_number, {
//     subtext: `Assign a destination unit before adding stops to Truck ${data.truck_number}.`,
//     pendingForm: originalFormData
//   });
// }

// Unit card click — handle full units with confirmation
document.addEventListener('click', e => {
  const card = e.target.closest('.unit-picker-card');
  if (!card || !card.closest('#unit-picker-grid')) return;
  
  const isFull = card.dataset.isFull === 'true';
  if (isFull) {
    // Show inline confirmation
    const confirm = document.getElementById('unit-picker-confirm');
    confirm.hidden = false;
    confirm.innerHTML = `
      <div class="unit-picker-confirm-box">
        <p><strong>${card.dataset.unitName}</strong> is marked full. Assign anyway?</p>
        <button class="btn-primary btn-sm" data-action="confirm-full-unit" 
                data-unit-id="${card.dataset.unitId}"
                data-unit-name="${card.dataset.unitName}">Assign anyway</button>
        <button class="btn-outline btn-sm" data-action="cancel-full-confirm">Cancel</button>
      </div>`;
  } else {
    assignUnit(card.dataset.unitId, card.dataset.unitName);
  }
});

// Confirm full unit assignment
document.addEventListener('click', e => {
  if (e.target.closest('[data-action="confirm-full-unit"]')) {
    const btn = e.target.closest('[data-action="confirm-full-unit"]');
    assignUnit(btn.dataset.unitId, btn.dataset.unitName);
  }
  if (e.target.closest('[data-action="cancel-full-confirm"]')) {
    document.getElementById('unit-picker-confirm').hidden = true;
  }
});

function assignUnit(unitId, unitName) {
  const shiftId = /* from modal state */ currentShiftId;
  fetch(`/admin/crew/shift/${shiftId}/truck/${pendingTruckNumber}/assign_unit`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ storage_location_id: unitId })
  })
  .then(r => r.json())
  .then(data => {
    if (data.success) {
      closeUnitPicker();
      updateTruckChip(pendingTruckNumber, unitName);
      // If we have a pending stop form to retry:
      if (pendingStopFormData) {
        retryStopAssignment(pendingStopFormData);
        pendingStopFormData = null;
      }
    }
  });
}
```

---

## CSS

Add to `static/style.css` under `/* Unit Picker Modal */`:

```css
/* Truck card header chips */
.btn-assign-unit {
  padding: 5px 14px;
  border-radius: 20px;
  border: 1.5px dashed var(--accent);
  background: transparent;
  color: var(--accent);
  font-size: 0.85rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s;
}
.btn-assign-unit:hover {
  background: var(--accent);
  color: var(--text-light);
}

.unit-assigned-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 12px;
  border-radius: 20px;
  background: #d4edda;
  color: #1A5C2A;
  border: none;
  font-size: 0.85rem;
  font-weight: 500;
  cursor: pointer;
}
.unit-assigned-chip:hover .unit-chip-edit { opacity: 1; }
.unit-chip-edit { opacity: 0.4; font-size: 0.75rem; transition: opacity 0.15s; }

/* Unit picker modal */
.unit-picker-panel {
  width: 600px;
  max-width: 95vw;
  max-height: 80vh;
  overflow-y: auto;
}

.unit-picker-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 10px;
  margin-top: 12px;
}

.unit-picker-card {
  border: 1.5px solid var(--rule);
  border-radius: 10px;
  padding: 12px;
  cursor: pointer;
  transition: border-color 0.15s, box-shadow 0.15s;
  background: var(--card-bg);
}
.unit-picker-card:hover {
  border-color: var(--primary);
  box-shadow: 0 2px 8px rgba(0,0,0,0.08);
}
.unit-picker-card--selected {
  border-color: var(--primary);
  background: var(--bg-cream);
  box-shadow: 0 0 0 2px var(--primary);
}
.unit-picker-card--full {
  opacity: 0.65;
}
.unit-picker-card__name {
  font-weight: 600;
  font-size: 0.95rem;
  color: var(--text-main);
}
.unit-picker-card__size {
  font-size: 0.75rem;
  color: var(--text-muted);
  margin: 2px 0 4px;
}
.unit-picker-card__count {
  font-size: 0.8rem;
  color: var(--text-muted);
  margin-bottom: 6px;
}
.unit-picker-card__full-warning {
  font-size: 0.75rem;
  color: var(--accent);
  margin-top: 6px;
}
.unit-picker-confirm-box {
  border: 1px solid var(--accent);
  border-radius: 8px;
  padding: 12px;
  margin-top: 12px;
  background: #fff8ee;
}

/* Driver destination banner */
.driver-destination-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  background: var(--bg-cream);
  border: 1px solid var(--rule);
  border-radius: 8px;
  margin-bottom: 16px;
  font-size: 0.95rem;
}
.destination-label { color: var(--text-muted); }
.destination-unit { color: var(--primary); font-size: 1rem; }
```

---

## Surfaces Touched Summary

| Surface | Change |
|---------|--------|
| `templates/admin/ops.html` | Replace dropdown with assign chip/button; add unit picker modal |
| New: `templates/admin/ops_unit_picker_partial.html` | Card grid of storage locations with capacity data |
| New route: `GET /admin/ops/unit-picker-partial` | Serves the card grid partial |
| `POST /admin/crew/shift/<id>/truck/<n>/assign_unit` | No logic change — called from new modal JS |
| `POST /admin/crew/shift/<id>/assign` | Add 422 gate: unit required before first stop |
| `templates/crew/shift.html` | Add destination unit banner |
| `templates/crew/shift_placement_partial.html` | Prefill Select Unit dropdown from truck_unit_plan |
| Route: `crew_shift_view` | Pass `destination_unit` to template |
| Route: serves placement partial | Pass `preferred_unit_id` to template |
| `static/style.css` | Unit picker card grid, assign chip, driver banner |

---

## Constraints

- **Do not touch** the backend logic of `admin_shift_assign_unit` — it already handles `truck_unit_plan` write + pending pickup sync correctly.
- **Do not touch** the "Mark Full" logic on the warehouse floor — `is_full` is only ever set there, not from the ops page.
- **Completed `ShiftPickup` stops are never retroactively updated** when unit changes — existing behavior, must be preserved.
- The 422 gate in `admin_shift_assign_seller` must only fire when `existing_stops == 0` for that truck. Adding a second stop to a truck that already has one (and therefore already has a unit) must proceed normally.
- **No new model fields. No migration.**
- All JS must use `data-*` attributes for structured data — no inline `onclick`, no `tojson` in attributes (project rule #8).
- All colors via CSS variables — no hardcoded hex.
- The driver shift view (`crew/shift.html`) has no admin chrome — the destination banner must match the crew page's visual style, not the admin shell.
