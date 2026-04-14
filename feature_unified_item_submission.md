# Feature Spec: Unified Item Submission Flow

**Status:** Ready for implementation  
**Date:** April 2026  
**Replaces:** Separate `/onboard` and `/add_item` flows

---

## Goal

Onboarding (`/onboard`) and add-item (`/add_item`) are two parallel implementations of the same item-creation wizard that have diverged over time. The only real differences were: onboarding collected pickup week preference (step 7) and payout method (step 8), while add-item skipped both. Now that pickup week lives on the dashboard (modal + `/api/user/set_pickup_week`) and was already skippable in onboarding, the two flows are functionally identical for item-related steps. This spec merges them into a single, canonical item submission flow with conditional steps based on user state.

**Secondary goal:** Remove the pickup week step from onboarding entirely. The dashboard already supports full pickup week management (modal, nag nudge, `api_set_pickup_week` endpoint). No new dashboard work is needed — this spec only removes the redundant onboarding step.

---

## What Changes, What Doesn't

### Removed from onboarding
- **Step 7 (Pickup Week)** — deleted entirely. `User.pickup_week` and `User.pickup_time_preference` are set exclusively via the dashboard modal going forward.
- Any session keys saving `onboard_pickup_week` / `onboard_time_preference` during the guest save flow.

### Unchanged
- Dashboard pickup week modal and `/api/user/set_pickup_week` — no changes needed.
- Address nag banner on dashboard — no changes needed.
- All item model fields, status transitions, and admin flows.
- Photo upload logic (`handleImageUpload`, QR flow, `TempUpload` records) — do not touch.
- `/onboard_complete`, `/onboard_cancel`, `/onboard/complete_account` routes.
- `edit_item` route and template.

---

## Unified Step Sequence

Steps 1–6 are identical for all users. Steps 7–9 are conditional.

| Step | Name | All users | Logged-in, payout on file | Guest / no payout |
|------|------|-----------|--------------------------|-------------------|
| 1 | Category + subcategory | ✅ | ✅ | ✅ |
| 2 | Condition | ✅ | ✅ | ✅ |
| 3 | Photos + video | ✅ | ✅ | ✅ |
| 4 | Item title | ✅ | ✅ | ✅ |
| 5 | Long description | ✅ | ✅ | ✅ |
| 6 | Suggested price | ✅ | ✅ | ✅ |
| 7 | Payout method | skip if `payout_method` already set on `User` | ❌ skipped | ✅ shown |
| 8 | Review & submit | ✅ | ✅ | ✅ |
| 9–10 | Account creation | guests only | ❌ skipped | ✅ shown |

**Payout skip condition:** `current_user.is_authenticated and current_user.payout_method is not None and current_user.payout_handle is not None`

---

## UX Flow

### Path A — Logged-in seller with payout on file (returning seller, "Add Another Item")
1. User clicks "Add Another Item" on dashboard → `GET /add_item` (or `/onboard` — see route note below)
2. Steps 1–6 (item details)
3. Step 7: Review & submit — summary shows payout method already on file
4. POST → item created as `pending_valuation`, redirect to `/dashboard` with success flash
5. No redirect to `/onboard_complete` for returning sellers — dashboard is the right landing spot

### Path B — Logged-in seller, no payout on file (edge case: payout cleared or OAuth user who never completed onboarding)
1. Steps 1–6
2. Step 7: Payout method (Venmo/PayPal/Zelle, handle, confirm handle)
3. Step 8: Review & submit
4. POST → item created, payout saved to `User`, redirect to `/dashboard`

### Path C — Guest (new user, no account)
1. Steps 1–6
2. Step 7: Payout method
3. Step 8: Review & submit (shows "Create account to submit")
4. Steps 9–10: Account creation (name, email, phone, password — or Google OAuth)
5. POST → account created, item created, redirect to `/onboard_complete`

### Draft / save-and-exit
- Guest save via `/onboard/guest/save` continues to work as before.
- Session keys for `onboard_pickup_week` / `onboard_time_preference` are **not** saved — remove from guest save handler if present.

### Edge cases
- **User starts onboarding, logs in mid-flow (OAuth):** After OAuth callback, resume at the step stored in session. Payout step is shown if not yet set on the now-authenticated user.
- **Logged-in user hits `/onboard` directly:** Treat as "add another item" — skip account creation steps, skip payout if on file.
- **Video required but not uploaded:** Block submission at review step (existing behavior — do not change).
- **User navigates back past step 1:** Preserve all session data. Back navigation must not clear already-entered fields.

---

## New Routes

No new routes required. The change is internal to the existing route handlers.

| Route | Change |
|-------|--------|
| `GET/POST /onboard` | Remove step 7 (pickup week). Add payout-skip logic based on user state. |
| `GET/POST /add_item` | Options: (a) redirect to `/onboard` with a flag, or (b) keep as separate route sharing the same step logic. Claude Code to decide based on refactor complexity. If kept separate, both must have identical step 1–6 logic with no divergence. |
| `POST /onboard/guest/save` | Strip `onboard_pickup_week` and `onboard_time_preference` from saved session keys. |

---

## Model Changes

**None.** All required fields already exist:
- `User.payout_method`, `User.payout_handle` — already present
- `User.pickup_week`, `User.pickup_time_preference` — already present, set via dashboard only going forward
- `InventoryItem` — no changes

No migration needed.

---

## Template Changes

### `onboard.html`
- Remove step 7 (pickup week) UI entirely — the two week-selection radio cards, time preference buttons, "Skip for now" button, and associated JS.
- Remove any JS that reads/writes `onboard_pickup_week` or `onboard_time_preference` from session or form state.
- Renumber steps: what was step 8 (payout) becomes step 7; what was step 9 (review) becomes step 8; account creation steps shift accordingly.
- Step 7 (payout): shown conditionally. If user is authenticated and payout is on file, this step is skipped in the backend step counter — do not render it. If shown, review card should display "Payout already on file" with the masked handle instead.
- Progress indicator (if present) must reflect the dynamic step count: 8 steps for guests without payout, 7 steps for guests with payout, 6 steps for logged-in sellers without payout, 5 steps for fully set up returning sellers (just the item steps + review).

### `add_item.html`
- If Claude Code keeps `add_item` as a separate route: ensure step sequence matches onboard steps 1–6 + conditional payout + review exactly. No divergence.
- If Claude Code redirects `add_item` → `onboard`: template may be retired. Keep until redirect is confirmed working.

### Dashboard (no changes)
- Pickup week modal already exists.
- Address nag banner already exists.
- No template changes needed.

---

## Business Logic

### Payout step skip logic (backend)
```python
def _user_has_payout(user):
    return (
        user.is_authenticated
        and user.payout_method is not None
        and user.payout_handle is not None
        and user.payout_handle.strip() != ''
    )
```
If this returns `True` when the user reaches what would be the payout step, increment the step counter past it and do not validate payout fields on POST.

### Item creation on submit (unchanged)
- `collection_method` hardcoded to `'free'`
- `status` set to `'pending_valuation'`
- Payout fields saved to `User` (not duplicated on item)
- `item.seller = current_user` (or newly created user for guests)

### What happens to sellers who set pickup week in onboarding before this change
- Their `User.pickup_week` and `User.pickup_time_preference` values are preserved in the database.
- The dashboard modal will pre-fill with their saved values.
- No migration or data cleanup needed.

---

## Constraints

1. **Do not touch photo upload logic.** `handleImageUpload`, the QR code flow, `TempUpload` records, and `/api/upload_session/*` endpoints are out of scope.
2. **Do not modify the dashboard pickup week modal or `/api/user/set_pickup_week`.** These are already correct.
3. **Do not change item status transitions or admin approval flows.** Out of scope.
4. **`/onboard_complete` route and template are unchanged** — still used for guest → new account path.
5. **Stripe and payout flows are unchanged.** The payout *method* (Venmo handle etc.) collected here is distinct from the Pro upgrade ($15 Stripe fee). Do not conflate.
6. **`collection_method` stays hardcoded to `'free'`** on item creation. No tier selection in this flow.
