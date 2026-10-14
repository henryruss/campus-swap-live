# Fix: Reschedule Token Refresh + Issue-Status Stop Removal

**Date:** 2026-05-20
**Priority:** High — operationally blocking
**Scope:** Two targeted bug fixes, no new models, no migration needed

---

## Goal

Fix two related gaps in the seller rescheduling system:

1. **After a seller uses their reschedule token, they have no self-serve path to reschedule again.** The token is marked `used_at` and the dashboard reschedule link disappears (because `notified_at` was cleared by `_do_reschedule`). If they need to move again, they're stuck.

2. **Admin cannot remove a stop with `status='issue'` from the ops page.** `admin_shift_remove_stop` gates on `status='pending'` only. A stop marked as an issue (e.g. seller flagged a problem, or a driver attempt left an issue flag) cannot be removed even though the item was never picked up — blocking admin from moving the seller to a different shift.

Both issues converged for Nick Andrew: he rescheduled (token used, `notified_at` cleared), his stop ended up with `status='issue'`, and now neither he nor admin can move him.

---

## Fix 1 — Refresh RescheduleToken After Reschedule

### What's broken

`_do_reschedule(pickup, new_shift)` clears `notified_at` on the pickup. The dashboard Pickup Window cell and modal both gate the "Reschedule →" link on `notified_at IS NOT NULL`. After reschedule, `notified_at` is NULL, so the link disappears from the dashboard. The seller's previously issued token is also spent (`used_at` set). They have no entry point.

### Fix

At the end of `_do_reschedule`, after all other writes, call `_get_or_create_reschedule_token(pickup)` — but first invalidate the old token so a fresh one is issued.

**In `_do_reschedule` in `app.py`**, add after the existing writes but before `db.session.commit()`:

```python
# Invalidate any existing unused token for this pickup so a fresh one is issued
existing_token = RescheduleToken.query.filter_by(
    pickup_id=pickup.id,
    used_at=None,
    revoked_at=None
).first()
if existing_token:
    existing_token.used_at = datetime.now().replace(tzinfo=None)  # treat as spent

# Issue a fresh token so seller retains self-serve reschedule access
_get_or_create_reschedule_token(pickup)
```

**Why not just un-stamp `used_at`?** Reusing the same token URL leaves the old email link live. Better to mark it spent and generate a new token — same idempotency logic in `_get_or_create_reschedule_token` handles the create.

### Dashboard link gate

The "Reschedule →" link in `dashboard.html` and the pickup modal should gate on **`shift_pickup` exists** (i.e., seller is assigned to a shift), not on `notified_at IS NOT NULL`. The seller should always be able to reschedule if they have a pickup — whether or not they've been formally notified.

**In `dashboard.html`**, find the Pickup Window stat cell and the modal footer. Change the condition on the reschedule link from:

```jinja2
{% if shift_pickup and shift_pickup.notified_at %}
```

to:

```jinja2
{% if shift_pickup %}
```

This applies in two places:
- The stat cell "Reschedule →" link
- The modal "Need a different time? Reschedule →" link

The read-only display of week/time preference in the modal (gated on `ShiftPickup` existing) is unchanged — that lock is correct and intentional.

---

## Fix 2 — Allow Removal of Issue-Status Stops

### What's broken

`admin_shift_remove_stop` (`POST /admin/crew/shift/<shift_id>/stop/<pickup_id>/remove`) contains a guard:

```python
if pickup.status != 'pending':
    flash('Cannot remove a stop that has been completed or has an issue.', 'error')
    return redirect(...)
```

This blocks removal of `status='issue'` stops. But an issue stop means the pickup **failed** — the item was never collected. Admin should be able to remove it (e.g. to reassign the seller to a different shift or mark them as a no-show and handle offline).

A `status='completed'` stop correctly remains non-removable — the item was physically picked up.

### Fix

Change the guard in `admin_shift_remove_stop` to allow `'issue'` status:

```python
# Before (broken):
if pickup.status != 'pending':
    flash('Cannot remove a stop that has been completed or has an issue.', 'error')
    return redirect(url_for('admin_shift_ops', shift_id=shift_id))

# After (fixed):
if pickup.status == 'completed':
    flash('Cannot remove a completed stop — item has already been picked up.', 'error')
    return redirect(url_for('admin_shift_ops', shift_id=shift_id))
```

### Template — show Remove button for issue stops

In `admin/shift_ops.html`, the Remove button is likely rendered conditionally. Find the block that gates the button on `pickup.status == 'pending'` and expand it:

```jinja2
{# Before: #}
{% if pickup.status == 'pending' %}
  <button ...>Remove</button>
{% endif %}

{# After: #}
{% if pickup.status in ('pending', 'issue') %}
  <button ...>Remove</button>
{% endif %}
```

---

## Summary of Code Changes

### `app.py`

| Location | Change |
|---|---|
| `_do_reschedule(pickup, new_shift)` | After existing writes, invalidate any open token then call `_get_or_create_reschedule_token(pickup)` to issue a fresh one |
| `admin_shift_remove_stop` | Change guard from `status != 'pending'` to `status == 'completed'` |

### `templates/dashboard.html`

| Location | Change |
|---|---|
| Pickup Window stat cell reschedule link | Change condition from `shift_pickup and shift_pickup.notified_at` → `shift_pickup` |
| Pickup modal "Need a different time?" link | Same condition change |

### `templates/admin/shift_ops.html`

| Location | Change |
|---|---|
| Remove button visibility condition | Expand from `status == 'pending'` → `status in ('pending', 'issue')` |

---

## No Migration Needed

No model fields are added or changed. `_get_or_create_reschedule_token` already exists and creates a new `RescheduleToken` row — this just calls it in one additional code path.

---

## Edge Cases

- **Seller reschedules twice, then gets an issue on the second shift:** Each reschedule invalidates the prior token and issues a fresh one. The third attempt works correctly.
- **Admin removes an issue stop:** The stop is deleted. `_do_reschedule`'s route repack logic (repacking remaining stops with `nullslast`) is NOT called here — that's only for reschedule moves. The remaining stops keep their `stop_order` intact. This is correct: removing a stop doesn't need reordering — the gap is cosmetic.
- **Admin removes a pending stop that already has a RescheduleToken:** The token's `pickup_id` FK will point to a deleted row. Add a cascade or explicit delete of associated `RescheduleToken` rows in `admin_shift_remove_stop` before deleting the pickup:

```python
# In admin_shift_remove_stop, before db.session.delete(pickup):
RescheduleToken.query.filter_by(pickup_id=pickup.id).delete()
db.session.delete(pickup)
db.session.commit()
```

This is an existing gap (not introduced by this fix) but should be addressed here since we're touching this route.

---

## Testing Checklist

- [ ] Seller reschedules via token → token marked used, fresh token created in DB
- [ ] Seller visits dashboard after reschedule → "Reschedule →" link is visible even though `notified_at` is NULL
- [ ] Seller reschedules a second time (auth path `/seller/reschedule`) → works, new token issued
- [ ] Admin ops page: issue-status stop shows Remove button
- [ ] Admin removes issue-status stop → stop deleted, other stops unaffected
- [ ] Admin cannot remove completed stop → error flash, no change
- [ ] Removing a stop with an associated RescheduleToken → token rows cleaned up, no FK error
