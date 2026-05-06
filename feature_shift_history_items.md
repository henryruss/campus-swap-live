# Feature Spec: Completed Shift Item History

## Goal

After a driver ends a shift, they can tap into any completed shift from
their Shift History on the crew dashboard and see a full list of the items
they collected — with photo, item ID, description, and seller name. Useful
when a driver drops items at the storage unit and needs to recall ID numbers
after ending the shift.

No new models or migrations required.

---

## UX Flow

1. Driver visits `/crew` — Shift History shows completed shift cards as today
2. Driver taps a completed shift card → navigates to
   `GET /crew/shift/<shift_id>/history`
3. Page loads showing:
   - Shift label at top (e.g. "Tuesday AM · May 6")
   - "← Back to dashboard" link
   - List of all stops on this shift (filtered to the driver's truck) where
     `ShiftPickup.status = 'completed'`
   - Each stop card shows all items collected from that seller
4. Read-only. No actions available.

---

## New Route

| Method | Path | Function | Description |
|--------|------|----------|-------------|
| `GET /crew/shift/<shift_id>/history` | `crew_shift_history` | Read-only completed shift item list for the current worker |

### Logic

```python
@app.route('/crew/shift/<int:shift_id>/history')
@login_required
def crew_shift_history(shift_id):
    require_crew()

    shift = Shift.query.get_or_404(shift_id)

    # Must be assigned to this shift
    assignment = ShiftAssignment.query.filter_by(
        shift_id=shift_id,
        worker_id=current_user.id
    ).first()
    if not assignment:
        abort(403)

    # Must be a completed shift
    run = ShiftRun.query.filter_by(
        shift_id=shift_id,
        status='completed'
    ).first()
    if not run:
        flash('This shift has not been completed yet.', 'info')
        return redirect(url_for('crew_dashboard'))

    # Get completed stops for this driver's truck
    pickups = (
        ShiftPickup.query
        .filter_by(
            shift_id=shift_id,
            truck_number=assignment.truck_number,
            status='completed'
        )
        .order_by(ShiftPickup.stop_order.asc().nullslast())
        .all()
    )

    # Build items dict keyed by seller_id
    # Include all pickup-eligible statuses — same as crew_shift_view
    PICKUP_ELIGIBLE_STATUSES = ('pending_logistics', 'approved', 'available', 'sold')
    seller_ids = [p.seller_id for p in pickups]
    items_by_seller = {}
    if seller_ids:
        items = InventoryItem.query.filter(
            InventoryItem.seller_id.in_(seller_ids),
            InventoryItem.status.in_(PICKUP_ELIGIBLE_STATUSES)
        ).all()
        for item in items:
            items_by_seller.setdefault(item.seller_id, []).append(item)

    return render_template(
        'crew/shift_history.html',
        shift=shift,
        assignment=assignment,
        pickups=pickups,
        items_by_seller=items_by_seller,
        run=run
    )
```

---

## Template Changes

### `crew/dashboard.html` — Shift History Cards

Make each completed shift card a link to the history page:

```html
<!-- BEFORE: shift card is a static div -->
<div class="shift-history-card">...</div>

<!-- AFTER: wrap in anchor -->
<a href="{{ url_for('crew_shift_history', shift_id=shift.id) }}"
   class="shift-history-card shift-history-card--link">
  ...existing card content...
</a>
```

Add to `static/style.css`:
```css
.shift-history-card--link {
  display: block;
  text-decoration: none;
  color: inherit;
}
.shift-history-card--link:hover {
  box-shadow: 0 2px 8px rgba(0,0,0,0.08);
}
```

### New Template: `crew/shift_history.html`

Extends `layout.html`. Phone-optimized — same design language as
`crew/shift.html`.

```
{% extends "layout.html" %}
{% block content %}

<div class="crew-shift-history">

  <!-- Header -->
  <div class="shift-history-header">
    <a href="{{ url_for('crew_dashboard') }}" class="back-link">← Dashboard</a>
    <h2>{{ shift.label }}</h2>
    <p class="shift-date muted">
      {{ shift | shift_date_display }}
      · Ended {{ run.ended_at | format_datetime_eastern }}
    </p>
  </div>

  <!-- Summary -->
  <p class="shift-history-summary">
    {{ pickups | length }} stop{{ 's' if pickups | length != 1 }}
    collected on Truck {{ assignment.truck_number }}.
  </p>

  {% if not pickups %}
    <p class="muted">No completed stops found for your truck on this shift.</p>
  {% endif %}

  <!-- Stop cards -->
  {% for pickup in pickups %}
    {% set seller_items = items_by_seller.get(pickup.seller_id, []) %}
    <div class="history-stop-card">

      <!-- Stop header -->
      <div class="history-stop-header">
        <span class="stop-number">#{{ loop.index }}</span>
        <span class="stop-seller-name">{{ pickup.seller.full_name }}</span>
        <span class="stop-address muted">{{ pickup.seller.pickup_display }}</span>
      </div>

      <!-- Items -->
      {% if seller_items %}
        <div class="history-item-list">
          {% for item in seller_items %}
            <div class="history-item-card">
              {% if item.photo_url %}
                <img
                  src="{{ url_for('uploaded_file', filename=item.photo_url) }}"
                  class="history-item-photo"
                  alt="{{ item.description }}"
                >
              {% else %}
                <div class="history-item-photo history-item-photo--empty"></div>
              {% endif %}
              <div class="history-item-info">
                <span class="item-id-badge">#{{ item.id }}</span>
                <span class="history-item-desc">{{ item.description }}</span>
              </div>
            </div>
          {% endfor %}
        </div>
      {% else %}
        <p class="muted history-no-items">No items on record for this stop.</p>
      {% endif %}

    </div>
  {% endfor %}

</div>

{% endblock %}
```

### CSS (add to `static/style.css`)

```css
.crew-shift-history {
  max-width: 600px;
  margin: 0 auto;
  padding: 16px;
}

.shift-history-header {
  margin-bottom: 16px;
}
.shift-history-header h2 {
  margin: 4px 0 2px;
  font-size: 22px;
}
.back-link {
  font-size: 14px;
  color: var(--primary);
  text-decoration: none;
}
.shift-history-summary {
  font-size: 14px;
  color: var(--text-muted);
  margin-bottom: 20px;
}

.history-stop-card {
  background: var(--bg-white, #fff);
  border: 1px solid var(--border-color, #e8e8e8);
  border-radius: 12px;
  padding: 14px;
  margin-bottom: 14px;
}
.history-stop-header {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-bottom: 12px;
}
.stop-number {
  font-size: 12px;
  color: var(--text-muted);
  font-weight: 500;
}
.stop-seller-name {
  font-weight: 600;
  font-size: 16px;
}
.stop-address {
  font-size: 13px;
}

.history-item-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.history-item-card {
  display: flex;
  align-items: center;
  gap: 12px;
}
.history-item-photo {
  width: 56px;
  height: 56px;
  object-fit: cover;
  border-radius: 8px;
  flex-shrink: 0;
  background: var(--bg-cream, #f5f5f0);
}
.history-item-photo--empty {
  background: var(--bg-cream, #f5f5f0);
}
.history-item-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.item-id-badge {
  font-family: monospace;
  font-weight: 700;
  font-size: 13px;
  color: var(--primary);
}
.history-item-desc {
  font-size: 14px;
  color: var(--text-main);
}
.history-no-items {
  font-size: 13px;
  margin: 4px 0 0;
}
```

---

## Constraints

- Read-only page — no forms, no POST actions.
- Gated on `ShiftAssignment` for current user — a worker can only see
  their own completed shifts, not other workers' shifts.
- Gated on `ShiftRun.status='completed'` — in-progress or never-started
  shifts redirect to dashboard with a flash message.
- Items query uses the same `PICKUP_ELIGIBLE_STATUSES` tuple as
  `crew_shift_view` — keep these in sync if statuses are ever updated.
- No migration needed.
- Do not modify `crew_shift_view` or `crew_shift_end` — this is an
  additive new page only.
- The future inventory reconciliation spec (walk the line, scan IDs,
  find unaccounted items) will query `picked_up_at IS NOT NULL AND
  storage_location_id IS NULL` — no prep work needed now beyond what
  already exists.
