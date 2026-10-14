# feature_ops_admin_fixes.md

## Goal

Three separate issues are blocking the admin from building routes for pickup week 2:

1. **Sellers who chose Week 1 are invisible to the ops system.** The unassigned panel and auto-assign both filter on `User.pickup_week`. Sellers who selected week 1 don't match any week-2 shift and so disappear entirely. Admin needs to bulk-reassign them to week 2 without making sellers do anything.

2. **The unassigned panel shows "all eligible sellers assigned" even though nobody has been assigned.** This is almost certainly the same root cause: the panel filters sellers whose `User.pickup_week` matches the currently selected shift's week. If the `pickup_week_start`/`pickup_week_end` AppSettings define week 2 but sellers have `pickup_week = 1`, the filter returns zero results and the empty state fires incorrectly.

3. **"Assign unit" button is clipped and unreachable.** The truck card footer has two buttons ("Re-order route" and "Assign unit"). The Assign unit button is cut off by the card boundary — a CSS overflow or z-index issue.

---

## Fix 1 — Admin: Bulk Reassign Week 1 Sellers to Week 2

### UX Flow

A new action on the **Admin Settings page** (or optionally on the Ops page header) lets a super admin bulk-update all sellers whose `pickup_week = 1` to `pickup_week = 2`.

**Placement:** `/admin/settings` — new section called "Pickup Week Override" below the pickup window date fields.

**UI:**
- Small info card: "X sellers are currently assigned to Week 1. If Week 1 pickups are not running, reassign them to Week 2."
- Button: **"Move all Week 1 sellers → Week 2"**
- On click: standard `<form method="POST">` submitting to `POST /admin/settings/reassign-week`
- After redirect back to `/admin/settings`: flash message "Moved N sellers from Week 1 to Week 2."

**Edge cases:**
- Sellers who already have a `ShiftPickup` (i.e. already assigned to a route) are **excluded** from the bulk update. Their `pickup_week` field doesn't matter once they have a stop — we don't want to change anything that could confuse the ops view or trigger re-filtering.
- If a seller has `pickup_week = 1` but also a `ShiftPickup`, they are skipped silently (count not included in flash total).
- If zero sellers qualify, flash: "No Week 1 sellers without an existing route assignment."
- The route is super admin only.

### New Route

| Method | Path | Function | Description |
|--------|------|----------|-------------|
| `POST` | `/admin/settings/reassign-week` | `admin_reassign_week` | Bulk-sets `User.pickup_week = 2` for all sellers with `pickup_week = 1` and no `ShiftPickup`. Super admin only. Redirect to `/admin/settings` with flash. |

### Model Changes

None. Uses existing `User.pickup_week` (Integer).

### Business Logic

```python
# Pseudo-code
sellers_to_move = User.query.filter(
    User.pickup_week == 1,
    ~User.shift_pickups.any()  # no ShiftPickup exists
).all()

for seller in sellers_to_move:
    seller.pickup_week = 2

db.session.commit()
flash(f"Moved {len(sellers_to_move)} sellers from Week 1 to Week 2.")
```

### Constraints

- Do not touch sellers with an existing `ShiftPickup`.
- Do not change `InventoryItem.pickup_week` — that field is item-level and only matters for ops tracking after pickup.
- No migration needed.

---

## Fix 2 — Unassigned Panel Filter Bug

### Root Cause (hypothesis to confirm in code)

The unassigned panel query filters sellers by `User.pickup_week` matching the selected shift's week number. If `pickup_week_start` / `pickup_week_end` AppSettings define week 2 but all real sellers have `pickup_week = 1`, the filter returns zero — and the "all eligible assigned" empty state fires, which is misleading.

### Fix

**In `admin_ops` route** (and wherever `_get_unassigned_sellers()` is called): the filter for `User.pickup_week` should be loosened. Specifically:

A seller should appear in the unassigned panel if **either**:
- Their `pickup_week` matches the week of the currently viewed shift, **OR**
- Their `pickup_week` is set to a week whose date range has already passed (i.e. a "stranded" week-1 seller)

Actually, the cleaner fix is: **show all sellers with any `pickup_week` set and no `ShiftPickup`**, and display their stated week as a badge on the card. Admin can see who picked which week and assign accordingly. The panel already shows a "week" badge on each seller card — this just makes the filter non-exclusive.

**The slot filter (AM/PM) is still applied** — a seller who said "Morning" still shows under AM shifts by default, dimmed under PM. That behavior is correct and unchanged.

**Implementation note:** Check whether the week-match filter is in `_get_unassigned_sellers()`, in the `admin_ops` route itself, or in the Jinja template. Fix it at the source — don't work around it in the template. The fix is likely a one-line change removing or relaxing the `pickup_week == current_week` condition.

### Template Changes

- Seller cards in the unassigned panel already show a week badge ("Wk 1", "Wk 2"). No change needed there — the badge will now correctly display "Wk 1" for stranded sellers so admin can see them clearly.
- Consider adding a small amber indicator or tooltip on Wk 1 cards: "Picked week 1 — not yet run." This is cosmetic / optional.

### Constraints

- Auto-assign (`_run_auto_assignment()`) should also be checked: confirm it uses the same filter logic and receives the same fix. Auto-assign should place sellers regardless of whether their stated week matches — what matters is that they have no `ShiftPickup` and have approved items.
- The existing "Sellers without `pickup_week` set do NOT appear in the unassigned panel" rule stays in place. Only sellers with `pickup_week IS NULL` are excluded. Sellers with `pickup_week = 1` during a week-2 operation should be visible.

---

## Fix 3 — "Assign Unit" Button Clipped by Card

### Root Cause

The truck card footer contains two buttons side by side. At certain card widths the second button ("Assign unit") overflows the card boundary and gets clipped — either by `overflow: hidden` on the card or by the card's right edge cutting it off before the button is fully rendered.

### Fix

In `templates/admin/ops.html` (or wherever the truck card footer is rendered):

1. **Ensure the footer uses `flex-wrap: wrap`** so that if the two buttons don't fit on one line they wrap to a second line rather than overflow.
2. **Remove any `overflow: hidden` on the truck card** that would clip the footer. If the card has a border-radius and relies on `overflow: hidden` for clipping, switch to `overflow: visible` on the card itself and clip only the header/image if needed.
3. **Alternatively**, if both buttons always fit in context, check whether the card has a fixed `max-width` or `width` that's too narrow — widen it or let it stretch.

**Specific template change:** In the truck card footer `<div>`:
```html
<!-- Change from: -->
<div class="truck-footer">

<!-- To (add flex-wrap): -->
<div class="truck-footer" style="flex-wrap: wrap; gap: 8px;">
```
Or apply this in `style.css` under `.truck-footer` using the existing CSS variable system. Do not hardcode colors — button styles already use `--primary`, `--accent`, etc.

### Constraints

- Do not change button functionality.
- Do not move "Assign unit" to a different location in the UI.
- Verify on both desktop (wide) and a narrower viewport (1024px) that both buttons are fully visible.

---

## Template Changes Summary

| Template | Change |
|----------|--------|
| `templates/admin/settings.html` | Add "Pickup Week Override" section with seller count + bulk reassign form |
| `templates/admin/ops.html` | Fix truck card footer overflow (flex-wrap). Optional: amber badge on Wk 1 seller cards in unassigned panel. |

## Route Changes Summary

| Method | Path | Function | Notes |
|--------|------|----------|-------|
| `POST` | `/admin/settings/reassign-week` | `admin_reassign_week` | New. Super admin only. |

## Migration

None required.

---

## Implementation Order

1. **Fix 3 first** (truck card CSS) — purely cosmetic, zero risk, unblocks the assign unit flow immediately.
2. **Fix 2** (unassigned panel filter) — one-line query change; unblocks seeing all current sellers.
3. **Fix 1** (bulk reassign) — new route + settings UI; lets admin clean up the week-1 sellers properly.

After all three are in place, the full ops workflow (auto-assign → order routes → assign units → notify sellers) should work end-to-end for week 2.

---

## Constraints That Must Not Be Touched

- `_get_payout_percentage(item)` — untouched.
- `ShiftPickup` unique constraint `(shift_id, seller_id)` — unchanged.
- Stripe webhook handler — unchanged.
- Seller-facing reschedule flow — unchanged.
- Seller dashboard pickup modal — unchanged (sellers can still update their week via the modal; admin bulk-reassign is a separate admin-only action).
