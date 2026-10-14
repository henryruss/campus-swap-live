# feature_retire_pending_logistics.md

## Goal

The `pending_logistics` status is a legacy artifact from when Campus Swap had a
Pro/Free tier model requiring seller payment before pickup. That model no longer
exists. Today, admin approves an item and it should immediately be `available` —
no intermediate state, no seller action required.

Currently the approval route still writes `pending_logistics` for some sellers
(specifically those who completed their profile before admin approval), making
them invisible in the ops unassigned panel.

---

## UX Flow

**Before (broken):**
1. Seller signs up, fills out pickup week, address, payout info
2. Admin approves item → item set to `pending_logistics`
3. Nothing triggers the flip to `available` — no payment step exists
4. Seller invisible in ops panel forever

**After (fixed):**
1. Seller signs up, fills out profile
2. Admin approves item → item immediately set to `available`
3. Seller appears in ops unassigned panel

---

## New Routes
None.

---

## Model Changes
None. The `pending_logistics` value can remain valid in the DB column — we are
just stopping the code from writing it and removing it as a gate.

---

## App.py Changes

### Approval route (`admin_approve` POST handler)
- Find every line that sets `item.status = 'pending_logistics'`
- Replace with `item.status = 'available'`
- Applies unconditionally — no scenario exists where `pending_logistics` is
  correct post-approval

### `admin_free_confirm` route
- Same change — replace any `pending_logistics` write with `available`

### `has_paid` checks
- Search `app.py` for any route or helper that checks `user.has_paid` as a gate
  for item visibility, ops eligibility, or seller activation
- Remove those checks or replace with hardcoded `True`
- Do NOT delete the `has_paid` DB column — just stop reading it as a gate

### `_ops_build_unassigned_panel()` and `_run_auto_assignment()`
- No change needed — filter already uses `status NOT IN ('rejected',
  'needs_info')` which covers all broken states
- Confirm no secondary `has_paid` filter is applied to the seller query here

---

## Template Changes
None required.

---

## Business Logic

### New item lifecycle
pending_valuation → (admin approves) → available → (sold) → sold
→ (admin rejects) → rejected
→ (admin requests info) → needs_info
→ (seller resubmits) → pending_valuation
→ (admin cancels) → pending_valuation

`pending_logistics` and `approved` are retired. Neither should be written
by any route going forward.

### One-time data fix (run in psql after deploy)
```sql
UPDATE inventory_item
SET status = 'available'
WHERE status IN ('pending_logistics', 'approved')
AND seller_id IN (
  SELECT id FROM "user" WHERE pickup_week IS NOT NULL
);
```

---

## Constraints
- Do NOT delete `pending_logistics` or `approved` as valid string values
- Do NOT touch the Stripe webhook handler — leave `has_paid` writes there alone
- Do NOT touch `picked_up_at` write logic — it correctly targets `available` only
- `admin_cancel_info_request` returning items to `pending_valuation` is correct,
  leave it unchanged