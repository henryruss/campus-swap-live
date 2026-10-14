# Mini-Spec: Admin Force-Remove & Reassign Stop (In-Progress Route)

## Goal

Allow an admin to remove a seller from an **already-started route** and optionally reassign them to a different shift. Currently `admin_shift_remove_stop` hard-blocks on `status != 'pending'`. Ops reality is that life happens mid-route — houses get rescheduled, sellers cancel — and admin needs an escape hatch that doesn't require a database hotfix.

---

## UX Flow

### Entry point: Admin Ops Page (`/admin/crew/shift/<shift_id>/ops`)

**Current behavior:** Remove button is hidden or disabled once a `ShiftRun` exists for the shift.

**New behavior:**

1. On each stop card, if the stop's `status == 'pending'` (not yet visited), a **"Reassign Stop"** button appears — visible even on an in-progress route.
2. Clicking it opens an inline confirmation panel (no page nav, same pattern as the existing flag/issue pickers) with:
   - Seller name + address displayed for confirmation
   - A **shift picker** dropdown showing upcoming shifts (today + future, not yet started, not `reschedule_locked`)
   - "Move to selected shift" button → POSTs to new route
   - "Just remove (no reassignment)" link below it
3. After action: page reloads, stop is gone from this shift, flash message confirms.

**Edge case — stop is `'issue'` or `'completed'`:** Don't show the Reassign button. Those stops are already resolved. Admin can use the existing revert → then reassign path if needed, but that's a separate concern. This spec only touches `pending` stops.

---

## New Routes

| Method | Path | Function | Description |
|--------|------|----------|-------------|
| `POST` | `/admin/crew/shift/<shift_id>/stop/<pickup_id>/force-remove` | `admin_shift_force_remove_stop` | Remove a `pending` stop regardless of ShiftRun state. Repacks `stop_order`. Redirects to ops page. |
| `POST` | `/admin/crew/shift/<shift_id>/stop/<pickup_id>/reassign` | `admin_shift_reassign_stop` | Force-remove from current shift + assign to a different shift. Single transaction. Redirects to ops page. |

Both require `is_admin`. Neither requires `is_super_admin` — ops admins need this in the field.

---

## Model Changes

None. No new fields or tables. The reassign action is a `ShiftPickup` mutation — all required fields (`shift_id`, `truck_number`, `stop_order`, `rescheduled_from_shift_id`, `rescheduled_at`, `notified_at`) already exist.

**No migration needed.**

---

## Template Changes

### `admin/shift_ops.html`

On each stop card where `pickup.status == 'pending'`:

1. **Replace** the existing "Remove" button (hidden on in-progress routes) with a **"Reassign"** button that is always visible for pending stops — regardless of `ShiftRun` state.

2. The button triggers an inline panel (same show/hide pattern as the flag picker in the driver view). Panel contains:
   - Seller name + address (confirmation context)
   - `<select name="target_shift_id">` populated from `eligible_shifts` template context. Shift label format: `[Day, Mon D] [AM/PM]` — same format used elsewhere in the ops system.
   - Submit button: **"Move to this shift"** → POSTs to `admin_shift_reassign_stop`
   - Secondary action: **"Remove without reassigning"** → small link below, POSTs to `admin_shift_force_remove_stop`

3. Pass `eligible_shifts` to the template from the `admin_shift_ops` route: shifts where `shift.date >= today_eastern()` AND `shift.run is None` AND `shift.reschedule_locked == False`, ordered by date ASC. Exclude the current shift.

4. Use `data-*` attributes to pass `pickup_id` to JS for panel toggling. No inline `tojson` in `onclick`.

---

## Business Logic

### `admin_shift_force_remove_stop`

1. Load `ShiftPickup` by `pickup_id`; 404 if not found.
2. **Guard:** `pickup.status` must be `'pending'`. If `'completed'` or `'issue'`, return 400 with flash: "Can't remove a stop that's already been visited."
3. Capture `old_shift_id = pickup.shift_id`.
4. Delete the `ShiftPickup`.
5. Repack `stop_order` on `old_shift_id` — call the existing `_do_reschedule` repacking helper. Do not duplicate the logic.
6. Flash "Stop removed from route." Redirect to ops page for `old_shift_id`.

### `admin_shift_reassign_stop`

1. Load `ShiftPickup` by `pickup_id`; 404 if not found.
2. **Guard:** `pickup.status == 'pending'`. If not, flash error and redirect back.
3. Load target `Shift` by `target_shift_id` from form POST; 404 if not found.
4. **Guard:** target shift must not have a `ShiftRun`. If started, flash: "Target shift is already in progress — can't assign to it." Redirect back.
5. **Guard:** target shift date must be `>= today_eastern()`. Prevents assigning to a past shift.
6. Determine `truck_number` for new shift — use `overflow_truck_number` from `Shift.truck_unit_plan` if set, otherwise truck 1. Same logic as `_do_reschedule`.
7. **Revoke open RescheduleTokens:** if the seller has any token where `used_at IS NULL` and `revoked_at IS NULL`, set `revoked_at = _now_eastern()`. The token pointed to the old pickup and no longer applies.
8. Update pickup in a single transaction:
   - `pickup.shift_id` → target shift ID
   - `pickup.truck_number` → overflow truck or truck 1
   - `pickup.stop_order` → `NULL` (goes to end of new route)
   - `pickup.rescheduled_from_shift_id` → old shift ID
   - `pickup.rescheduled_at` → `_now_eastern()`
   - `pickup.notified_at` → `NULL` (seller needs re-notification)
   - `pickup.capacity_warning` → recompute for new truck (same logic as `admin_routes_move_stop`)
9. Repack `stop_order` on old shift (same repacking call as `admin_shift_force_remove_stop`).
10. Flash "Stop moved to [new shift label]." Redirect to old shift's ops page.

**No SMS or email is sent by either route.** Admin is making a manual ops adjustment. Re-notification is handled explicitly via the "Notify Sellers" button on the new shift's ops page, which already guards on `notified_at IS NULL`.

---

## Constraints

- **Do not touch** `admin_shift_remove_stop` — keep it as-is for the normal (non-started) case. New routes are additive only.
- **Do not touch** `crew_shift_stop_update` or any driver-facing routes.
- **Do not touch** `_do_reschedule` — call it, don't rewrite it.
- `_get_payout_percentage` untouched.
- The unique constraint `(shift_id, seller_id)` on `ShiftPickup` is naturally satisfied — this is an UPDATE to `shift_id`, not a new INSERT.

---

## Open Questions

1. **Re-notification checkbox:** For real sellers, should the reassign panel include an "Also notify seller" checkbox that fires the same email/SMS as "Notify Sellers"? Or always leave re-notification as a separate explicit step?
2. **Eligible shift window:** Should the picker show all future shifts, or cap at the next 7 days?
3. **Target shift already started (super admin override):** If tomorrow's shift somehow has a ShiftRun, the guard blocks assignment. Should `is_super_admin` be able to override this?
