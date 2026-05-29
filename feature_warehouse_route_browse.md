# Feature Spec: Warehouse Route Browse

## Goal

Campus directors physically in the warehouse often need to identify an unlabeled item and confirm or assign its storage location. They may not know the item's name, ID, or seller — but they do know which route brought it in (e.g. "this whole unit came off the Tuesday AM truck") or roughly when it arrived. This spec adds a **Browse by Route** mode to the warehouse floor search bar, letting the director select any past shift and see a flat list of all items from sellers on that route, with the same inline unit assignment UI already used in search results.

---

## UX Flow

### Entry Point

The warehouse floor page (`/admin/warehouse`) currently shows a search bar at the top. Below the search input, two tab pills are added:

```
[ 🔍 Search Items ]  [ 🚛 Browse by Route ]
```

"Search Items" is active by default — existing behavior is completely unchanged.

### Browse by Route Tab

1. User clicks **Browse by Route**.
2. The search input is hidden (or replaced with a label). A loading spinner appears briefly.
3. A lazy `fetch` request hits `GET /admin/warehouse/routes` — a new HTML partial endpoint.
4. The partial renders a **scrollable list of shift chips**, sorted most-recent-first:

   ```
   Mon May 26 AM  ·  18 items
   Mon May 26 PM  ·  9 items
   Sat May 24 AM  ·  22 items
   ...
   ```

   Each chip shows: day of week, date, slot (AM/PM), and item count (total items from all sellers on that shift, regardless of item status). Shifts with zero associated items are omitted.

5. User taps a chip. Items load in the results area below via `GET /admin/warehouse/search?shift_id=<id>` — the existing search endpoint extended with a new `shift_id` param.

6. Results render identically to current text-search results:
   - Item thumbnail, name/description, seller name, status chip
   - If `storage_location_id` is set: green **Unit 503** label in place of the "Select Unit" picker
   - If `storage_location_id` is null: inline **Select Unit** picker (existing component, unchanged)
   - Camera button if `needs_new_photo=True`

7. The selected shift chip gets an active/highlighted state. Clicking a different chip replaces the results.

8. Switching back to **Search Items** restores the text input and clears the results area.

### Edge Cases

- **Shift with no items:** Omitted from the chip list entirely.
- **Item with `storage_location_id` set:** Shown with green unit label. Label is non-interactive (director can see it's placed; reassignment still possible via search if needed — no requirement to add a re-assign affordance here).
- **Item `status = 'rejected'`:** Still shown. A seller's items are shown regardless of status — the director may be looking at a physical item that was rejected in the system and needs to reconcile.
- **Seller on the route but `picked_up_at IS NULL`:** Still shown. Decision: show all items from sellers on the route regardless of pickup status, to avoid hiding anything the director might be holding.
- **No shifts exist at all:** The route browse area shows a single muted line: "No routes found."
- **Unit-scoped context:** If the director arrived at route browse from inside a specific unit drawer, `unit_id` context is cleared — route browse is always global (you're looking for an item you can't identify yet; scoping to a unit would defeat the purpose).

---

## New Routes

| Method | Path | Function | Description |
|--------|------|----------|-------------|
| `GET` | `/admin/warehouse/routes` | `admin_warehouse_routes` | HTML partial. Returns shift chip list, sorted most-recent-first. Omits shifts with zero seller items. `_has_ops_access()`. |

### Modified Route

`GET /admin/warehouse/search` (`admin_warehouse_search`) gains one new query param:

| Param | Type | Behavior |
|-------|------|----------|
| `shift_id` | Integer | When present, ignores `q`. Queries all `InventoryItem` records whose `seller_id` is in the set of seller IDs from `ShiftPickup.query.filter_by(shift_id=shift_id)`. Returns the same item row HTML partial as text search. |

The `q` and `shift_id` params are mutually exclusive. If both are present, `shift_id` takes precedence. `unit_id` scoping is ignored when `shift_id` is present (route browse is always global).

---

## Model Changes

**None.** All data needed exists:

- `Shift` has date/slot info (via `ShiftWeek.label` or computed from shift fields)
- `ShiftPickup` links `shift_id → seller_id`
- `InventoryItem` has `seller_id`, `storage_location_id`, `needs_new_photo`, `status`

No migration needed.

---

## Template Changes

### `templates/admin/warehouse.html`

1. **Add tab pills** below the search input:
   ```html
   <div class="warehouse-search-tabs">
     <button class="warehouse-tab active" data-tab="search">🔍 Search Items</button>
     <button class="warehouse-tab" data-tab="routes">🚛 Browse by Route</button>
   </div>
   ```

2. **Wrap existing search input** in a `<div id="search-mode">` that is shown/hidden by tab state.

3. **Add a new `<div id="route-mode">` container** (hidden by default). On first activation, JS fetches `/admin/warehouse/routes` and injects the HTML. Subsequent tab switches reuse the cached HTML (no re-fetch).

4. **Results area** (`#warehouse-search-results`) is shared between both modes — existing partial swap behavior is reused as-is.

### New partial: `templates/admin/warehouse_routes_partial.html`

No layout. Renders the shift chip list. Each chip:

```html
<button class="route-chip" data-shift-id="{{ shift.id }}">
  <span class="route-chip__label">{{ shift_label }}</span>
  <span class="route-chip__count">{{ item_count }} items</span>
</button>
```

Active chip gets `.route-chip--active` class (set via JS on click).

### `templates/admin/warehouse_search_results.html`

Already renders item rows with inline unit picker and camera button. **One addition:** when `storage_location_id` is set on an item, render a non-editable green unit chip instead of the Select Unit picker:

```html
{% if item.storage_location_id %}
  <span class="unit-chip unit-chip--placed">{{ item.storage_location.name }}</span>
{% else %}
  {# existing Select Unit picker #}
{% endif %}
```

This chip already needs to exist for clarity even in text-search results (currently items show nothing if already placed), so this is a dual-benefit improvement.

---

## Business Logic

### `admin_warehouse_routes` query

```python
# All shifts that have at least one seller with at least one item,
# sorted most-recent-first.

from sqlalchemy import func

shifts_with_items = (
    db.session.query(Shift, func.count(InventoryItem.id).label('item_count'))
    .join(ShiftPickup, ShiftPickup.shift_id == Shift.id)
    .join(InventoryItem, InventoryItem.seller_id == ShiftPickup.seller_id)
    .group_by(Shift.id)
    .having(func.count(InventoryItem.id) > 0)
    .order_by(Shift.id.desc())   # Shift IDs are monotonically increasing; if Shift has a date field, order by that instead
    .all()
)
```

Shift label display: use the existing shift label convention from the codebase (check how `admin_shift_ops` or `admin_routes_index` formats shift labels — replicate that pattern exactly).

### `admin_warehouse_search` — new `shift_id` branch

```python
shift_id = request.args.get('shift_id', type=int)
if shift_id:
    seller_ids = [
        p.seller_id for p in ShiftPickup.query.filter_by(shift_id=shift_id).all()
    ]
    items = InventoryItem.query.filter(
        InventoryItem.seller_id.in_(seller_ids)
    ).order_by(InventoryItem.id.desc()).all()
```

No status filter. No `storage_location_id` filter. All items from all sellers on that shift.

### JS behavior (`warehouse.html`)

```javascript
// Tab switching
document.querySelectorAll('.warehouse-tab').forEach(tab => {
  tab.addEventListener('click', () => {
    const mode = tab.dataset.tab;
    document.querySelectorAll('.warehouse-tab').forEach(t => t.classList.remove('active'));
    tab.classList.add('active');
    document.getElementById('search-mode').hidden = (mode !== 'search');
    document.getElementById('route-mode').hidden = (mode !== 'routes');
    if (mode === 'routes' && !routesLoaded) {
      loadRoutes(); // fetch + inject; set routesLoaded = true
    }
    if (mode === 'search') {
      // clear results when switching back
      document.getElementById('warehouse-search-results').innerHTML = '';
    }
  });
});

// Route chip click
function onRouteChipClick(shiftId) {
  document.querySelectorAll('.route-chip').forEach(c => c.classList.remove('route-chip--active'));
  event.currentTarget.classList.add('route-chip--active');
  fetch(`/admin/warehouse/search?shift_id=${shiftId}`)
    .then(r => r.text())
    .then(html => {
      document.getElementById('warehouse-search-results').innerHTML = html;
    });
}
```

Event delegation should be used on the route chip list (the container exists at page load; chips are injected dynamically). Follow the `data-*` attribute pattern per project rule #8 — no inline `onclick`.

---

## CSS

Add to `static/style.css` under a `/* Warehouse Route Browse */` section:

```css
.warehouse-search-tabs {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}

.warehouse-tab {
  padding: 6px 16px;
  border-radius: 20px;
  border: 1px solid var(--rule);
  background: transparent;
  color: var(--text-muted);
  font-size: 0.875rem;
  cursor: pointer;
  transition: all 0.15s;
}

.warehouse-tab.active {
  background: var(--primary);
  color: var(--text-light);
  border-color: var(--primary);
}

.route-chip {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;
  padding: 10px 14px;
  margin-bottom: 6px;
  border: 1px solid var(--rule);
  border-radius: 8px;
  background: var(--card-bg);
  cursor: pointer;
  text-align: left;
  transition: border-color 0.15s;
}

.route-chip:hover {
  border-color: var(--primary);
}

.route-chip--active {
  border-color: var(--primary);
  background: var(--bg-cream);
}

.route-chip__label {
  font-weight: 500;
  color: var(--text-main);
}

.route-chip__count {
  font-size: 0.8rem;
  color: var(--text-muted);
}

.unit-chip--placed {
  display: inline-block;
  padding: 3px 10px;
  border-radius: 12px;
  background: #d4edda;
  color: #1A5C2A;
  font-size: 0.8rem;
  font-weight: 500;
}
```

---

## Constraints

- **Do not touch** the existing `admin_warehouse_search` result HTML structure — the inline unit picker, camera button, and `set-location` POST interaction must remain unchanged for the text-search path.
- **Do not touch** `admin_warehouse_unit` (the unit drawer partial) — route browse is always global and never enters a unit-scoped context.
- **Do not touch** the Needs New Photo or Photo Verification Queue sections.
- The `shift_id` filter in `admin_warehouse_search` must be a new branch — existing `q` + `unit_id` logic must be unmodified.
- No new models. No migration.
- JS must use `data-shift-id` attribute on chips, not inline `onclick` (project rule #8).
- All colors via CSS variables — no hardcoded hex in templates or new JS.
