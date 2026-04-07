# Feature Spec: Pickup Week in Onboarding + Dashboard Modal + Phone Required + Tier Simplification

**Date:** April 2026  
**Status:** Ready for implementation  
**Affects:** `onboard.html`, `add_item.html`, `dashboard.html`, `register.html`, `account_settings.html`, `app.py`, `models.py`

---

## Goal

Reduce post-onboarding friction by letting sellers set their pickup week while they're already in the flow. Make the experience feel complete in one sweep — item details, pickup preference, payout setup — without requiring a separate confirm-pickup page later. Collect phone number at account creation everywhere it happens, since it's operationally critical for pickup coordination. Simplify service tier architecture: everyone starts free, upgrade is a deliberate dashboard action, not an onboarding gate.

---

## Summary of Changes

1. **Remove service tier step from onboarding wizard** — everyone starts as free tier
2. **Add optional pickup week step to onboarding** (step 7, after suggested price, before payout)
3. **Add phone number to account creation** — required everywhere, not optional
4. **Replace `/confirm_pickup` page with a dashboard modal**
5. **Add "Upgrade Plan" card to dashboard** linking to existing `/upgrade_pickup`
6. **Deprecate free-tier capacity gating** (admin confirm/reject flow)

---

## 1. Remove Service Tier Step from Onboarding

### What changes
- Remove step 7 (service tier selection) from `onboard.html` entirely
- All new sellers are created with `collection_method = 'free'` by default
- Remove tier selection from `add_item.html` as well if it appears there

### New default behavior
- `InventoryItem.collection_method` defaults to `'free'` on creation
- Payout percentage defaults to 33% until seller upgrades
- No Stripe charge at onboarding time

### What does NOT change
- The upgrade flow (`/upgrade_pickup`, `upgrade_pickup.html`) stays exactly as-is
- Stripe checkout for the $15 fee is untouched
- `collection_method` field stays on the model — it's still set, just always starts as `'free'`

---

## 2. New Onboarding Step Order

| Step | Name | Notes |
|------|------|-------|
| 1 | Category | Unchanged |
| 2 | Condition | Unchanged |
| 3 | Photos & Video | Unchanged |
| 4 | Item Title | Unchanged |
| 5 | Long Description | Unchanged |
| 6 | Suggested Price | Unchanged |
| 7 | **Pickup Week** | New — optional, skippable |
| 8 | Payout Method | Unchanged (was step 8, now renumbered) |
| 9 | Review & Submit | Unchanged |
| 10–11 | Account Creation | Guests only — phone added here (see §3) |

---

## 3. New Step 7 — Pickup Week (Optional)

### UX

**Heading:** "When are you moving out?"  
**Subheading:** "Pick the week that works best. We'll assign a specific time closer to pickup."

Two large radio-button cards:
- **Week 1** — April 27 – May 3
- **Week 2** — May 4 – May 10

Below the week cards, a second set of radio buttons for time-of-day preference:
- Morning (9am – 1pm)
- Afternoon (1pm – 5pm)
- Evening (5pm – 9pm)

**Skip button** — prominently placed, same visual weight as the Back button (not a ghost link, a real button). Label: "Skip for now" with helper text underneath: "You can set or change this anytime from your dashboard."

**If a week is selected, time preference is required** before continuing. If neither is selected (skip), both save as null.

### Data saved
- `User.pickup_week` — new field (see §6 Model Changes)
- `User.pickup_time_preference` — already exists on User model

### Behavior
- If user already has `pickup_week` set (returning seller adding another item via `add_item`), show current selection pre-filled with an "Update" option
- Skip is always available regardless

### add_item wizard
Add the same optional pickup week step to `add_item.html` at the equivalent position. Since the seller already has an account, skip the account creation steps. If they already have a week set, pre-fill and let them update or keep as-is.

---

## 4. Phone Number — Required Everywhere

Phone is operationally critical. We text sellers about pickup. It is required at all account creation touchpoints.

### 4a. Email/password registration (`/register`, `register.html`)
- Add required `phone` field below email, above password
- Label: "Phone number"
- Helper text: "We'll text you updates about your pickup — nothing else."
- Format validation: must match a 10-digit US number (strip formatting, store as digits or formatted `(XXX) XXX-XXXX` — match existing pattern in `confirm_pickup`)
- Server-side: reject registration if phone missing or invalid

### 4b. Onboarding guest account creation (steps 10–11 in `onboard.html`)
- Add required `phone` field to the guest account creation step, alongside name and email
- Same label and helper text as above
- Saved to `User.phone` on account creation

### 4c. Google OAuth account creation
- After OAuth callback creates a new account, check `current_user.phone is None`
- If phone is missing, redirect to `/complete_profile` before sending user to their intended destination
- `/complete_profile` is a new lightweight page (see §5 New Routes) — just a single required phone field, branded simply
- Store `next` URL in session so redirect works correctly after phone is saved

### 4d. Homepage email signup (guest account flow)
- Guest accounts created at `/` don't collect phone at creation time — this is intentional (frictionless capture)
- When a guest later enters the onboarding wizard, phone is collected at the account creation step (4b above)
- If a guest hits the dashboard before completing onboarding (edge case), show the phone nag banner (see 4e)

### 4e. Existing users without phone — nag banner
- On `dashboard.html`: if `current_user.phone is None`, show an amber banner at the top of the page
- Text: "Add your phone number to receive pickup updates." with an inline input + Save button
- Banner persists until phone is saved. Not dismissible without saving.
- POST to `/update_account_info` (existing route) — no new route needed

### 4f. Account Settings (`/account_settings`, `account_settings.html`)
- Phone field in the Account Info card is already present — make it required on form submit if not yet set
- If phone is already set, allow editing with same validation

---

## 5. New Routes

| Method | Path | Function | Description |
|--------|------|----------|-------------|
| `GET/POST` | `/complete_profile` | `complete_profile` | Collect required phone after Google OAuth. Redirects to `next` or `/dashboard` on save. |
| `POST` | `/api/user/set_pickup_week` | `api_set_pickup_week` | AJAX endpoint for dashboard modal to save pickup week + time preference. Returns JSON `{success: true}`. |

### `/complete_profile`
- Requires login (`@login_required`)
- If `current_user.phone` is already set, redirect to dashboard (idempotent)
- Single form: phone number (required) + submit
- On success: redirect to `session.pop('next', '/dashboard')`
- Template: `complete_profile.html` — extends `layout.html`, minimal, centered card

### `/api/user/set_pickup_week`
- Requires login
- Accepts POST with `pickup_week` (`week1` | `week2`) and `pickup_time_preference` (`morning` | `afternoon` | `evening`)
- Validates both fields present and valid values
- Saves to `current_user`, commits, returns `{"success": true, "pickup_week": ..., "pickup_time_preference": ...}`
- Used by dashboard modal only

---

## 6. Model Changes

### User model — add `pickup_week` field

Currently `pickup_week` lives on `InventoryItem`. For the new flow, pickup week is a **per-user** preference (not per-item), which is consistent with how `pickup_time_preference` and `moveout_date` are already stored on `User`.

```python
pickup_week = db.Column(db.String(10), nullable=True)  
# values: 'week1' | 'week2' | None
```

**Migration:** `flask db migrate -m "add pickup_week to user"`

### InventoryItem.pickup_week
- Keep the field on `InventoryItem` — do not remove it. It may be populated by admin or used in reporting.
- For new items, leave it null on creation. Admin can set it if needed.
- The `User.pickup_week` is the seller's stated preference; ops uses it to schedule actual pickup.

---

## 7. Dashboard Changes

### 7a. Remove service tier from onboarding — add Upgrade card to dashboard

Add a prominent card to `dashboard.html` in the action cards section:

**If `collection_method == 'free'`:**
```
[ Upgrade to Pro ]
You're on the free plan — keeping 20% of each sale.
Upgrade for guaranteed pickup and 50% payout.
$15 one-time fee.                    [ Upgrade → ]
```
Links to `/upgrade_pickup` (existing page, no changes needed).

**If `collection_method == 'online'` (Pro):**
Show a green "Pro Plan" badge in the stats bar or plan badge area. No upgrade card shown.

### 7b. Pickup week display + modal

**In the stats bar**, the existing "Pickup Window" column shows:
- If `User.pickup_week` and `pickup_time_preference` are set: "Wk 1 · Morning" (existing format)
- If only week is set: "Week 1 — time TBD"
- If neither is set: "Not scheduled" in amber, with a small "Set now →" link that opens the modal

**Clickable pickup card** — clicking anywhere on the Pickup Window stats cell, or the "Set now" link, opens the pickup week modal.

### 7c. Pickup week modal

A centered overlay modal (not a page navigation). Triggered by JS, no new route needed for display.

**Modal contents:**
- Heading: "Your Pickup Week"
- Two week cards (radio buttons): Week 1 (Apr 27–May 3), Week 2 (May 4–May 10) — pre-selected if already set
- Time preference radio buttons: Morning / Afternoon / Evening — pre-selected if already set
- Helper text: "We'll assign a specific time closer to pickup and text you to confirm."
- Save button — POSTs to `/api/user/set_pickup_week` via fetch, closes modal on success, updates stats bar inline
- Cancel / close (X) button

**If seller is on free plan**, below the save button show:
> "You're on the free plan — [Upgrade to Pro](link to /upgrade_pickup) for guaranteed pickup and 50% payout."

**If seller is on Pro plan**, show:
> "You're on the Pro plan ✓"

### 7d. Deprecate admin free-tier confirm/reject flow

The warehouse capacity counter, confirm/reject buttons, and `admin_free_notify_all` route are no longer the gating mechanism. **Do not remove this code yet** — comment it out or leave it in place behind a flag. Ben and team should decide when to fully remove it. Note in code comments: "Superseded by open-enrollment model — storage units added on demand."

---

## 8. Deprecate `/confirm_pickup`

### What to do
- **Do not delete the route or template yet** — redirect `/confirm_pickup` to `/dashboard` with a flash message: "You can set your pickup week from your dashboard."
- Keep `confirm_pickup.html` in place but make it a redirect-only route
- The address/phone collection that lived in confirm_pickup is now handled by: phone at account creation (§4), address at account settings

### Address collection
The confirm_pickup page also collected pickup address (dorm/off-campus). This now lives in `/account_settings` only. The dashboard pickup modal does NOT collect address — just week and time preference. Address is a one-time setup in account settings.

If a seller hasn't set their pickup address yet, show a secondary banner on the dashboard (lower priority than phone nag): "Add your pickup address so we know where to find you." Links to `/account_settings`.

---

## 9. Template Changes

| Template | Change |
|----------|--------|
| `onboard.html` | Remove tier step; add pickup week step (step 7); add phone field to guest account creation step |
| `add_item.html` | Remove tier step if present; add optional pickup week step |
| `dashboard.html` | Add pickup week modal (JS + HTML); add Upgrade card; add phone nag banner; update stats bar pickup cell to be clickable |
| `register.html` | Add required phone field |
| `account_settings.html` | Make phone required on submit if not yet set |
| `complete_profile.html` | New template — phone collection post-OAuth |

---

## 10. Business Logic & Edge Cases

**Seller sets pickup week during onboarding, then adds another item later via add_item:**
- Show current week pre-filled in add_item pickup step. Let them update or skip. Saving updates `User.pickup_week`.

**Seller skips pickup week in onboarding:**
- `User.pickup_week = None`, `pickup_time_preference = None`
- Dashboard shows amber "Not scheduled" with "Set now" link
- Existing pickup nudge SellerAlert system continues to function — admin can still send pickup_reminder alerts manually

**Seller tries to access `/confirm_pickup` directly:**
- Redirect to `/dashboard` with info flash message

**Google OAuth user with no phone tries to access any protected route:**
- The `/complete_profile` redirect should be triggered at the OAuth callback, not on every protected route. Store `next` in session at callback time. This avoids needing middleware on every route.

**Existing sellers (before this deploy) with no phone:**
- Nag banner on dashboard (§4e) handles this. They are not locked out.

**Pickup week on InventoryItem vs. User:**
- `User.pickup_week` = seller's stated preference (what we use for scheduling)
- `InventoryItem.pickup_week` = can be set by admin per-item if needed (keep for ops flexibility)
- These are independent fields. Do not sync them automatically.

**Free tier payout percentage:**
- Free = 20%, Pro = 50%. This is confirmed across CODEBASE.md and website-feature-log.md. Make sure email templates, become_a_seller page, and payout calculation logic all reflect 20% for free tier.

---

## 11. Constraints — Do Not Touch

- Stripe webhook handler (`/webhook`) — no changes
- `/upgrade_pickup` and `upgrade_pickup.html` — no changes, used as-is for upgrade flow
- `InventoryItem` status lifecycle — no changes
- Admin approval queue — no changes
- Existing `pickup_time_preference` and `moveout_date` fields on `User` — no changes to these fields, just new `pickup_week` field added alongside them
- SellerAlert system — no changes; pickup_reminder alert type continues to work as admin manual tool
- Photo upload logic in onboarding — do not touch `handleImageUpload`, `handleCoverPhotoSelection`, or the QR upload flow
