# Feature Spec: Quick Capture ID Lookup

## Goal

After a driver quick-captures items during or between shifts, they need to physically tag each item with a sticker matching its item ID. Right now those items have no visible home — they don't appear in shift history (which is stop-based) and there's no other crew-facing surface that shows them. This spec adds two read-only surfaces so drivers can always find the IDs and photos of items they captured.

---

## Two Surfaces, No New Routes Required

### Surface 1 — Shift History Page (`/crew/shift/<shift_id>/history`)

The existing `crew_shift_history` template already shows completed stops and their items for the driver's truck. Add a **"Your Quick Captures"** section at the bottom of this page.

**Query:** All `InventoryItem` records where:
- `is_quick_capture = True`
- `quick_capture_shift_id = shift.id`
- `seller_id` in any user OR `seller.is_internal_account = True`
- Created by `current_user` — use a new `captured_by_id` field (see Model Changes below)

Display as a simple card list, one card per item:
- Photo thumbnail (left)
- Item ID as a large bold badge (e.g. `#1042`) — this is what the driver needs to write on the sticker
- Seller name (or "Campus Swap" for internal account items)
- Timestamp: "Captured at 2:14 PM"

If no quick captures exist for this shift, the section is hidden entirely (no empty state needed).

---

### Surface 2 — Crew Dashboard (`/crew`)

Add a **"Recent Captures"** card to the crew dashboard. This catches all quick-capture items the driver created that are NOT linked to any shift (`quick_capture_shift_id = NULL`), plus any shift-linked captures from the last 7 days that the driver may not have tagged yet.

**Query:** All `InventoryItem` records where:
- `is_quick_capture = True`
- `captured_by_id = current_user.id`
- `arrived_at_store_at IS NULL` — once the organizer has processed the item at intake, it's been tagged and the driver no longer needs to look it up
- `date_added >= now - 7 days` — rolling 7-day window; old captures that are still unprocessed after a week are an ops problem, not a driver UX problem

Order: `date_added DESC`.

Display: same card format as Surface 1 (photo, ID badge, seller name, timestamp). If the item has a `quick_capture_shift_id`, also show the shift date + slot as a small muted label (e.g. "May 6 · AM") so the driver knows which route it came from.

If the query returns zero items, **hide the card entirely** — no empty state, no visual clutter on the dashboard.

---

## Model Changes

### `InventoryItem`

Add one field:

```
captured_by_id (Integer, FK → User, nullable)
  — Set to current_user.id in crew_quick_capture at creation time.
  — NULL on all non-quick-capture items.
  — Never modified after creation.
```

One migration required.

Update `crew_quick_capture` in `app.py` to set `captured_by_id = current_user.id` on item creation. This is a one-line addition to the existing route.

---

## Route Changes

### `crew_shift_history` (existing route, modify only)

Add to the context passed to `crew/shift_history.html`:

```python
quick_captures = InventoryItem.query.filter_by(
    is_quick_capture=True,
    quick_capture_shift_id=shift.id,
    captured_by_id=current_user.id
).order_by(InventoryItem.date_added.desc()).all()
```

Pass `quick_captures` into the template. No other logic changes.

### `crew_dashboard` (existing route, modify only)

Add to the context passed to `crew/dashboard.html`:

```python
from datetime import timedelta

cutoff = _now_eastern() - timedelta(days=7)
recent_captures = InventoryItem.query.filter(
    InventoryItem.is_quick_capture == True,
    InventoryItem.captured_by_id == current_user.id,
    InventoryItem.arrived_at_store_at == None,
    InventoryItem.date_added >= cutoff
).order_by(InventoryItem.date_added.desc()).all()
```

Pass `recent_captures` into the template. No other logic changes.

---

## Template Changes

### `crew/shift_history.html` (modify existing)

After the existing completed stops section, add:

```
{% if quick_captures %}
<section class="quick-captures-section">
  <h3>Your Quick Captures</h3>
  {% for item in quick_captures %}
    <div class="capture-card">
      <img src="{{ url_for('uploaded_file', filename=item.photo_url) }}" ...>
      <div class="capture-info">
        <span class="item-id-badge">#{{ item.id }}</span>
        <span class="capture-seller">{{ item.seller.full_name }}</span>
        <span class="capture-time">Captured at {{ item.date_added | format_eastern_time }}</span>
      </div>
    </div>
  {% endfor %}
</section>
{% endif %}
```

Use existing CSS classes and CSS variables. The item ID badge should be visually prominent — large enough to read at a glance on a phone screen. Style consistently with the existing stop/item cards on this page.

### `crew/dashboard.html` (modify existing)

Add the "Recent Captures" card after the shift history card and before (or after) the schedule section — position it where it feels natural alongside existing dashboard cards.

```
{% if recent_captures %}
<div class="dashboard-card recent-captures-card">
  <h3>Recent Captures</h3>
  {% for item in recent_captures %}
    <div class="capture-card">
      <img src="{{ url_for('uploaded_file', filename=item.photo_url) }}" ...>
      <div class="capture-info">
        <span class="item-id-badge">#{{ item.id }}</span>
        <span class="capture-seller">{{ item.seller.full_name }}</span>
        {% if item.quick_capture_shift_id %}
          <span class="capture-shift-label">
            {{ item.shift_label }}  {# pass this from route context or compute in template #}
          </span>
        {% else %}
          <span class="capture-shift-label muted">Off-shift capture</span>
        {% endif %}
        <span class="capture-time">{{ item.date_added | format_eastern_time }}</span>
      </div>
    </div>
  {% endfor %}
</div>
{% endif %}
```

**Shift label:** For the dashboard card, the route should eager-load the related `Shift` via `joinedload` so the template can access `item.quick_capture_shift.date` and `item.quick_capture_shift.slot` without N+1 queries. Add a `quick_capture_shift` relationship to `InventoryItem` if it doesn't already exist (it should, since `quick_capture_shift_id` is a FK to `Shift`).

---

## Edge Cases

**Driver captures an item off-clock, then works a shift the same day:** The item appears on the dashboard card (off-clock, `quick_capture_shift_id=NULL`). It does NOT appear in that day's shift history (wrong `quick_capture_shift_id`). This is correct — the item isn't associated with the shift.

**Driver captures an item and the organizer processes it immediately:** Once `arrived_at_store_at` is set by the organizer during intake, the item drops off the dashboard card. The driver no longer needs to look it up — the organizer physically has it and the ID is in the system.

**Driver captures during a shift, checks history:** The item appears in the "Your Quick Captures" section at the bottom of that shift's history page. It also appears on the dashboard card until `arrived_at_store_at` is set (7-day window).

**Driver with no captures:** Both surfaces are hidden. Zero visual impact on the dashboard or history page.

**`format_eastern_time` filter:** If this Jinja filter doesn't already exist, add it as a simple helper that formats a UTC datetime as Eastern time in a short time-only string (e.g. "2:14 PM"). Use `_now_eastern()` pattern already in the codebase for timezone handling.

---

## Constraints

- No new routes. Only two existing routes modified (`crew_shift_history`, `crew_dashboard`), one existing route patched (`crew_quick_capture` — one line to set `captured_by_id`).
- No changes to any admin routes, seller routes, or Stripe logic.
- Do not surface these cards to non-workers or non-drivers. Both pages are already worker-gated — no additional access control needed.
- `arrived_at_store_at` is already set by the organizer intake flow. Do not modify that flow.
- Photo serving must use `url_for('uploaded_file', filename=item.photo_url)` — never `url_for('static', ...)`.
- All styling via CSS variables. No hardcoded colors.
