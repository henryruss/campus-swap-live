# Fix Spec: Crew Shift View — Items Showing 0 + Phone Number Display

## Problem 1: Stop Cards Show "0 item(s)"

### Root Cause

`crew_shift_view` builds a `seller_items` dict by querying `InventoryItem`
filtered to `status='available'`. However, items assigned to a pickup stop
may still be in `status='approved'` (the state before a seller completes
their logistics setup). These items are correctly assigned to the seller and
will be picked up — but the strict `available` filter excludes them, so the
stop card shows 0.

### Fix

In `crew_shift_view`, change the `seller_items` query to include all item
statuses that represent "this item is real and needs to be picked up":

```python
# BEFORE (approximate):
seller_items = {}
seller_ids = [p.seller_id for p in pickups]
items = InventoryItem.query.filter(
    InventoryItem.seller_id.in_(seller_ids),
    InventoryItem.status == 'available'
).all()
for item in items:
    seller_items.setdefault(item.seller_id, []).append(item)

# AFTER:
PICKUP_ELIGIBLE_STATUSES = ('approved', 'available')

seller_items = {}
seller_ids = [p.seller_id for p in pickups]
items = InventoryItem.query.filter(
    InventoryItem.seller_id.in_(seller_ids),
    InventoryItem.status.in_(PICKUP_ELIGIBLE_STATUSES)
).all()
for item in items:
    seller_items.setdefault(item.seller_id, []).append(item)
```

This is the only change needed for item count and the photo strip to work
correctly. The template lookup `seller_items[pickup.seller_id]` is correct —
the bug is purely in the query filter.

**Do not change** `picked_up_at` write logic (in `crew_shift_stop_update` or
the upcoming end-shift commit step) — that already correctly targets
`status='available'` items only, which is right: `approved` items that haven't
been confirmed by the seller shouldn't have `picked_up_at` written on them.
Only the display query needs broadening.

---

## Problem 2: Phone Number Not Shown on Stop Cards

### Root Cause

The spec checklist marks phone number display as complete, but looking at the
screenshot it is not visible on any stop card. Either it was not implemented,
or it is hidden behind the stop expand and not visible at the pre-start state.

### Fix

In `crew/shift.html`, ensure the seller's phone number is displayed directly
on each stop card — always visible, no tap required. Place it below the
address line.

```html
<!-- Below the address line in each stop card -->
<div class="stop-contact">
  {% if pickup.seller.phone %}
    <a href="tel:{{ pickup.seller.phone }}" class="stop-phone-link">
      📞 {{ pickup.seller.phone }}
    </a>
  {% else %}
    <span class="stop-phone-missing">No phone on file</span>
  {% endif %}
</div>
```

CSS (add to `static/style.css` if not already present):
```css
.stop-phone-link {
  color: var(--primary);
  font-size: 14px;
  text-decoration: none;
  display: inline-block;
  margin-top: 2px;
}
.stop-phone-link:hover {
  text-decoration: underline;
}
.stop-phone-missing {
  color: var(--text-muted);
  font-size: 13px;
}
```

Phone number must be visible:
- Before shift starts (pre-start state)
- During shift (in-progress state)
- On completed stops (so movers can call back if needed)

---

## Constraints

- No model changes, no migration.
- Do not change `picked_up_at` write logic — the `status='available'` filter
  there is correct and intentional.
- Do not change the photo strip template logic — only the route-level query
  needs updating.
- Phone link uses `tel:` protocol — tapping on mobile opens the native dialer.
