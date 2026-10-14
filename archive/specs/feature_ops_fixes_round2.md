# feature_ops_fixes_round2.md

## Goal

Four bugs discovered during first live pickup week operation, plus one new feature (remove truck). All changes are in `app.py` and `templates/admin/ops.html`. No model changes, no migrations.

---

## Fix 1 — Seller Eligibility Filter: `approved` items should count

### Problem

`_ops_build_unassigned_panel()`, `_run_auto_assignment()`, and `get_seller_unit_count()` all filter on `status='available'`. In practice, items sit in `approved` status until after pickup (sellers are not required to take a confirmation action). This means sellers with approved-but-not-yet-available items show up as ineligible and are invisible to the ops system.

### Fix

In `app.py`, update all three functions to treat any item that isn't explicitly inactive as counting toward eligibility:

**Eligibility filter** (used in `_ops_build_unassigned_panel()` and `_run_auto_assignment()`):
- Old: seller must have at least one item with `status='available'`
- New: seller must have at least one item with `status NOT IN ('rejected', 'needs_info')`
- Statuses that now count: `pending_valuation`, `approved`, `available`

**Unit count** (used in `get_seller_unit_count()`):
- Old: sum unit sizes for items where `status='available'`
- New: sum unit sizes for items where `status NOT IN ('rejected', 'needs_info')`

**Existing rule that does NOT change:** Sellers without `pickup_week` set remain excluded from the unassigned panel and auto-assign entirely.

### Constraints

- Do not change `get_item_unit_size()` — that function is correct.
- Capacity bar math on truck cards uses `get_seller_unit_count()` — it will now show real unit counts instead of 0, which is the correct behavior.
- No change to how capacity warnings are computed.

---

## Fix 2 — Unassigned Panel: Week is a suggestion, not a filter

### Problem

The unassigned panel and auto-assign filter sellers by whether their `pickup_week` matches the currently selected shift's week number. Sellers who chose week 1 (which was skipped) are invisible during week 2 operations.

### Fix

In `_ops_build_unassigned_panel()` and `_run_auto_assignment()`, remove the `pickup_week == current_week` match requirement entirely. Show all sellers who have:
- `pickup_week IS NOT NULL` (still required — sellers who never set a week are excluded)
- At least one eligible item (per Fix 1 above)
- No existing `ShiftPickup`

The seller's stated `pickup_week` is still displayed as a badge on their card in the unassigned panel (e.g. "Wk 1", "Wk 2") so admin can see their preference — but it does not filter visibility.

The AM/PM time preference filter remains: sellers whose `pickup_time_preference` matches the selected shift's slot appear normally; non-matching sellers appear dimmed under the "Show all unassigned" toggle. This behavior is unchanged.

### Constraints

- Do not remove the `pickup_week IS NULL` exclusion — sellers who never picked a week should still not appear.
- Do not change the AM/PM slot filtering logic.
- The week badge on seller cards in the unassigned panel should remain visible.

---

## Fix 3 — Auto-Assign Button: JSON rendered as full page instead of fetch

### Problem

The Auto-Assign button on the ops page is wired as a plain `<form method="POST">` submit. `POST /admin/routes/auto-assign` returns JSON, so the browser navigates to a blank page showing raw JSON instead of staying on the ops page.

### Fix

In `templates/admin/ops.html`, change the Auto-Assign button from a form submit to a `fetch()` call:

```javascript
// Pseudocode — implement with vanilla JS, no frameworks
async function runAutoAssign(shiftId) {
    const btn = document.getElementById('auto-assign-btn');
    btn.disabled = true;
    btn.textContent = 'Assigning...';

    const resp = await fetch('/admin/routes/auto-assign', {
        method: 'POST',
        headers: { 'X-CSRFToken': getCsrfToken() }  // use existing CSRF pattern
    });
    const data = await resp.json();

    // Reload the page to reflect new assignments
    window.location.href = `/admin/ops?shift_id=${shiftId}`;
}
```

- On success: reload `?shift_id=<current_shift_id>` so the truck cards and unassigned panel refresh.
- On network error: show a flash-style error message inline (do not navigate away).
- The page must never navigate to `/admin/routes/auto-assign` directly.
- Use the same CSRF token pattern already used elsewhere in `ops.html`.

### Constraints

- Do not change the `admin_routes_auto_assign` route or its JSON response format.
- The JSON response `{assigned, tbd, over_cap_warnings}` does not need to be displayed to the user — a page reload is sufficient feedback.

---

## Fix 4 — Admin Items Stats Bar: Total count excludes rejected items

### Problem

The "Total items" count in the stats bar at `/admin/items` counts every `InventoryItem` row ever created. It increments on every seller submission and never decrements when items are rejected or deleted.

### Fix

In the `admin_items` route in `app.py`, change the total items count query to exclude `rejected` items:

```python
# Old
total_items = InventoryItem.query.count()

# New
total_items = InventoryItem.query.filter(
    InventoryItem.status != 'rejected'
).count()
```

No template changes needed — the count variable is passed in and rendered as-is.

### Constraints

- Only change the `total_items` count. Do not change the `pending`, `available`, or `sold` counts in the same stats bar — those are already filtered correctly.
- No model changes, no migration.

---

## Feature — Remove Truck Button

### Goal

Admin can remove the highest-numbered truck from a shift on the ops page, as long as it has no stops assigned. This is the inverse of the existing Add Truck button.

### UX

A small **"Remove truck"** button or × icon appears in the truck card header of the **highest-numbered truck only**. It is not shown on any other truck card.

- Placement: truck card header, right side, next to the truck label. Small and unobtrusive — a text link or icon button, not a prominent CTA.
- Only visible when `truck_number == shift.trucks` (i.e. this is the last/highest truck).
- Only visible when the truck has **zero stops** (`ShiftPickup` count for this shift + truck == 0).
- If the truck has any stops (even one), the button is hidden entirely — not disabled, hidden.
- Clicking submits a POST form (not fetch — consistent with Add Truck pattern).
- On success: redirect to `admin_ops?shift_id=<shift_id>`.
- On failure (stops exist, or trucks already at 0): return 400 with a flash error, redirect back to ops page.

### New Route

| Method | Path | Function | Description |
|--------|------|----------|-------------|
| `POST` | `/admin/crew/shift/<shift_id>/truck/<truck_number>/remove` | `admin_shift_remove_truck` | Decrements `Shift.trucks` by 1 using raw SQL. Validates: truck_number must equal current `Shift.trucks` (highest truck only). Validates: no `ShiftPickup` rows exist for this shift + truck_number. On success: redirect to `admin_ops?shift_id=<id>`. On failure: 400 + flash error + redirect. Admin only. |

### Business Logic

```python
# Pseudo-code
shift = Shift.query.get_or_404(shift_id)

# Guard: only highest truck can be removed
if truck_number != shift.trucks:
    flash("Only the highest-numbered truck can be removed.")
    return redirect(admin_ops, shift_id=shift_id), 400

# Guard: no stops on this truck
stop_count = ShiftPickup.query.filter_by(
    shift_id=shift_id,
    truck_number=truck_number
).count()
if stop_count > 0:
    flash("Remove all stops from this truck before deleting it.")
    return redirect(admin_ops, shift_id=shift_id), 400

# Decrement using raw SQL (same pattern as add_truck)
db.session.execute(
    text("UPDATE shift SET trucks = trucks - 1 WHERE id = :id"),
    {"id": shift_id}
)
db.session.commit()

# Also clear this truck from truck_unit_plan if present
# (Shift.truck_unit_plan is a JSON dict keyed by truck number string)
shift_fresh = Shift.query.get(shift_id)
if shift_fresh.truck_unit_plan:
    plan = shift_fresh.truck_unit_plan.copy()
    plan.pop(str(truck_number), None)
    shift_fresh.truck_unit_plan = plan
    db.session.commit()

flash(f"Truck {truck_number} removed.")
return redirect(admin_ops, shift_id=shift_id)
```

### Template Changes

In `templates/admin/ops.html`, in the truck card header section, add the Remove Truck button conditionally:

```html
{% if truck.truck_number == shift.trucks and truck.stop_count == 0 %}
  <form method="POST" action="/admin/crew/shift/{{ shift.id }}/truck/{{ truck.truck_number }}/remove">
    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
    <button type="submit" class="btn-remove-truck">Remove truck</button>
  </form>
{% endif %}
```

Style `.btn-remove-truck` using existing CSS variables — small, muted, destructive-adjacent (e.g. `color: var(--error)` or similar). Do not hardcode colors.

### Constraints

- Use raw SQL for the decrement, same as `admin_shift_add_truck`. Do not use ORM to mutate `Shift.trucks`.
- Never allow removing a truck with stops — the guard must be server-side, not just UI.
- Never allow removing any truck other than the highest-numbered one.
- `Shift.trucks` must never go below 1 — add a guard: if `shift.trucks <= 1`, return 400.
- Do not touch `ShiftAssignment` records for movers assigned to this truck — that is out of scope. Admin should unassign movers manually first if needed (existing behavior).
- Do not change the Add Truck button or its route.

---

## Implementation Order

1. **Fix 1** (eligibility filter + unit count) — unblocks seeing sellers and correct unit counts immediately.
2. **Fix 2** (week filter removal) — unblocks week-1 sellers appearing in panel.
3. **Fix 3** (auto-assign fetch) — fixes the JSON page navigation bug.
4. **Fix 4** (item count) — quick stats bar fix, no dependencies.
5. **Feature** (remove truck) — new route + UI, no dependencies on fixes above.

All five can be done in a single Claude Code session in this order.

---

## Files To Change

| File | Changes |
|------|---------|
| `app.py` | Fix 1: `_ops_build_unassigned_panel()`, `_run_auto_assignment()`, `get_seller_unit_count()`. Fix 2: same two functions. Fix 4: `admin_items` route total count query. Feature: new `admin_shift_remove_truck` route. |
| `templates/admin/ops.html` | Fix 3: Auto-Assign button → fetch. Feature: Remove Truck button in truck card header. |

## Migrations Required

None.
