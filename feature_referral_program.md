# Feature Spec: Referral Program

## Goal

Replace the two-tier payout system (Free at 20%, Pro at 50%) with a single referral-driven payout system. All sellers start at 20%. Every valid referral — defined as a referred friend whose item physically arrives at the storage unit — earns the referrer +10%, up to a hard cap of 100%. Referred sellers start at 30% (a 10% signup bonus) and can also grow their own rate by referring others.

This replaces Campus Swap's upgrade upsell with a viral growth loop: the incentive to recruit isn't a social ask, it's money.

---

## UX Flow

### New Seller Signing Up With a Referral Code

1. A current seller shares their unique referral link (e.g. `usecampusswap.com/register?ref=ABC123`) or just their code (`ABC123`) with a friend.
2. The friend clicks the link and lands on the **register page** (`/register`). The referral code is pre-filled in a visible, editable text field labeled "Referral code (optional)." A note reads: *"Using a referral code gives you 30% payout instead of 20%."*
3. The friend creates an account. The referral code is validated on submit:
   - If valid: `referred_by_id` is saved to the new user. The new user's `payout_rate` is set to `30`.
   - If invalid/blank: `payout_rate` defaults to `20`, no `referred_by_id` set.
4. The new seller proceeds through normal onboarding. No referral-specific steps are added to the wizard.

### Existing User Signing Up via Google OAuth

1. If the referral code was in the URL (`?ref=ABC123`), it is saved to the Flask session before the OAuth redirect.
2. On OAuth callback, the session value is read and applied the same way as step 3 above.

### Guest Account Flow

1. If the user begins the onboarding wizard without an account (guest flow), and a `?ref=` param is present in the URL at any entry point, store it in the session immediately.
2. When the guest account is created at the end of the wizard (step 10–11 in `onboard.html`, or via `onboard_complete_account.html`), apply the referral code from session at that point, same validation rules.

### Where the Referral Code Field Appears

The referral code input appears on:
- `register.html` — standalone registration page
- `onboard.html` — the account-creation step of the onboarding wizard
- `onboard_complete_account.html` — the post-wizard account completion page

In all cases: the field is pre-populated from `?ref=` URL param or session, is visible and editable (not hidden), and shows the "30% instead of 20%" incentive copy inline.

### Seller Dashboard — Referral Widget

On `dashboard.html`, every seller sees a new **"Refer & Earn"** section:

- Their unique referral code (e.g. `ABC123`) displayed prominently
- A copyable referral link (`usecampusswap.com/register?ref=ABC123`)
- Current payout rate (e.g. **40%**) shown as a progress bar or step indicator: `20% → 30% → 40% → ... → 100%`
- Count of valid referrals so far (e.g. "3 of 8 referrals completed")
- Short explainer: *"Each friend whose item arrives at our warehouse earns you +10%. Refer 8 friends and keep 100% of your sales."*
- List of referred sellers (first name + last initial only, for privacy), with status: **Pending** (signed up, item not yet received) or **Confirmed** (item arrived at storage → payout boosted).

### When a Referral Is Confirmed (Item Arrives at Storage)

The referral is confirmed at the moment an organizer submits an intake record for any item belonging to a referred seller — specifically when `InventoryItem.arrived_at_store_at` is set (this happens inside `crew_intake_submit`).

At that moment:
1. Check if this seller has a `referred_by_id`.
2. Check if a `Referral` record already exists for this `(referrer_id, referred_id)` pair with `confirmed=True`. If so, skip — one referral credit per person regardless of item count.
3. If not yet confirmed: mark the `Referral` record `confirmed=True`, set `confirmed_at`.
4. Recalculate the referrer's `payout_rate`: `base_rate + (confirmed_referral_count × bonus_per_referral)`, capped at `max_payout_rate`.
5. All rates come from `AppSetting` — see Configuration section below.
6. Save updated `payout_rate` to `User`.
7. Send the referrer an email: *"Your referral [First Name] just had their item received. Your payout rate is now X%!"*

### Referral Window Closes

There is no automatic closing — the referral program is passive. Since `arrived_at_store_at` is only set during active intake shifts, and intake shifts only happen during the item collection period, no new referral confirmations are possible once item collection ends. No code change needed to enforce this.

### Admin View

In the seller profile panel (`admin_seller_panel.html`), add a **Referral** section:
- Current `payout_rate`
- Number of confirmed referrals
- Who referred this seller (if anyone), with a link to their panel
- List of sellers this user has referred, with confirmed/pending status

In the admin panel overview (`admin.html`), add a small **Referral Program Stats** block (super admin only):
- Total referrals confirmed
- Average payout rate across all sellers
- Number of sellers at 100%

---

## New Routes

| Method | Path | Function | Description |
|--------|------|----------|-------------|
| `GET` | `/referral/validate` | `referral_validate` | AJAX endpoint. Accepts `?code=ABC123`, returns JSON `{valid: true, referrer_name: "Jane D."}` or `{valid: false}`. Used for inline validation on the registration form. |
| `GET` | `/dashboard/referrals` | `dashboard_referrals` | Full referral history page (if the widget on dashboard.html links out to a detail view — optional, only if dashboard gets too crowded). |

All other referral logic is handled inside existing routes:
- `register` (POST) — apply referral code at account creation
- `onboard` (POST, account-creation step) — apply referral code from session
- `onboard_complete_account` (POST) — apply referral code from session
- `crew_intake_submit` (POST) — trigger referral confirmation when `arrived_at_store_at` is set

---

## Model Changes

### New Model: `Referral`

```python
class Referral(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    referrer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    referred_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, unique=True)
    # unique=True on referred_id: a user can only be referred by one person
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    confirmed = db.Column(db.Boolean, default=False)
    confirmed_at = db.Column(db.DateTime, nullable=True)

    referrer = db.relationship('User', foreign_keys=[referrer_id], backref='referrals_given')
    referred = db.relationship('User', foreign_keys=[referred_id], backref='referral_received', uselist=False)
```

**Migration required.**

### Changes to `User` Model

Add the following fields:

```python
referral_code = db.Column(db.String(8), unique=True, nullable=True)
# Generated at account creation. 8-char uppercase alphanumeric. Unique.

referred_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
# FK to the User who gave them their referral code.

payout_rate = db.Column(db.Integer, default=20, nullable=False)
# Stored integer percentage (20, 30, 40 ... 100).
# Updated whenever a referral is confirmed. Used everywhere payout is calculated.
```

**Migration required.**

### Existing Fields to Retire (Soft)

`collection_method` on `InventoryItem` currently drives payout rate ('online' → 50%, 'free' → 20%). With this change, payout rate moves to `User.payout_rate`. The `collection_method` field should be **retained in the DB** (no migration needed to remove it — avoid unnecessary risk), but payout calculations must switch to reading `User.payout_rate` instead. The Pro upgrade flow (`/upgrade_pickup`, `/upgrade_checkout`) should be removed from the UI but the routes can remain inactive to avoid 404s on any bookmarked links.

### AppSetting Keys (New)

These control the referral program behavior and allow dialing it back without code changes:

| Key | Default | Description |
|-----|---------|-------------|
| `referral_base_rate` | `'20'` | Payout % for a new seller with no referral code |
| `referral_signup_bonus` | `'10'` | Extra % granted to a seller who signs up with a referral code |
| `referral_bonus_per_referral` | `'10'` | Extra % added to referrer per confirmed referral |
| `referral_max_rate` | `'100'` | Hard cap on payout rate |
| `referral_program_active` | `'true'` | Master kill switch. If `'false'`, codes are not accepted, no bonuses granted, payout rate frozen at current stored value |

To dial back the program (e.g. cap everyone at 60%), set `referral_max_rate` to `'60'`. Existing stored `payout_rate` values above 60 would need a one-time admin migration script — note this in DECISIONS.md when/if it happens.

These keys should be editable from the admin panel (super admin only), in a new **Referral Program Settings** panel alongside the existing AppSetting toggles on `admin.html`.

---

## Template Changes

### `register.html`
- Add referral code text input field (pre-populated from `?ref=` URL param via Jinja or JS on load).
- Add incentive copy inline below the field: *"Have a referral code? Enter it here for 30% payout instead of 20%."*
- Add AJAX inline validation: on blur, call `/referral/validate?code=XYZ`, show `"✓ Code accepted — Jane D. referred you"` or `"✗ Code not found"`. Non-blocking — submission still proceeds without a valid code.

### `onboard.html`
- On the account-creation step, add the same referral code field.
- Pre-populate from session (`referral_code` key) if present.

### `onboard_complete_account.html`
- Same as above.

### `dashboard.html`
- Add **"Refer & Earn"** section (position: below item list, above payout settings).
- Contents:
  - Headline: *"Refer friends. Earn more."*
  - Current rate display: large number (`40%`) with label *"your current payout rate"*
  - Progress indicator: row of 9 steps (20%, 30%, ... 100%), current step highlighted
  - Referral code: displayed in a styled `<code>` block with a copy button (vanilla JS `navigator.clipboard`)
  - Referral link: full URL with copy button
  - Referred sellers list: table with First Name + Last Initial, Status (Pending / Confirmed), Date confirmed (if applicable)
  - If no referrals yet: empty state — *"Share your code to start earning more."*

### `admin_seller_panel.html`
- Add **Referral** section to the seller profile drawer:
  - Current `payout_rate` (large, prominent)
  - Referred by: name + email (if any), with link to open their panel
  - Referrals given: list of referred sellers (name, status, date confirmed)
  - Confirmed referral count

### `admin.html`
- Add **Referral Program Settings** panel (super admin section):
  - Editable fields for all 5 `AppSetting` keys above (text inputs + save button)
  - Referral stats block: total confirmed referrals, avg payout rate, count at 100%
- Update payout rate display throughout — anywhere that currently reads `collection_method` to show "Free (20%)" or "Pro (50%)" should now read `payout_rate` directly (e.g. "Payout: 40%").

### `admin_seller_panel.html` (Seller Status section)
- Replace "Service Tier: Free Plan / Pro Plan" with "Payout Rate: X%"
- Replace "Payment Status: Paid / Unpaid" (Pro fee) with nothing, or repurpose for a future use. The $15 fee is gone.

### Payout Emails
- The existing item-sold email template shows the payout amount and the seller's Venmo/Zelle handle. It currently calculates payout from `collection_method`. Switch to `seller.payout_rate / 100 * item.price`.
- Update copy to not reference "Free Plan" or "Pro Plan."

---

## Business Logic

### Referral Code Generation
- Generated at account creation (not at signup-link click).
- 8 characters, uppercase alphanumeric, excluding ambiguous characters (0, O, I, 1).
- Use `secrets.token_hex` or a custom generator with collision check.
- Stored on `User.referral_code`. Must be unique across all users.
- Existing users (pre-feature) get codes generated in a one-time migration script (loop over all users without a code, generate and assign).

### Payout Rate Calculation
```python
def calculate_payout_rate(user):
    base = int(AppSetting.get('referral_base_rate', '20'))
    max_rate = int(AppSetting.get('referral_max_rate', '100'))
    bonus_per = int(AppSetting.get('referral_bonus_per_referral', '10'))
    signup_bonus = int(AppSetting.get('referral_signup_bonus', '10')) if user.referred_by_id else 0
    confirmed_count = Referral.query.filter_by(referrer_id=user.id, confirmed=True).count()
    rate = base + signup_bonus + (confirmed_count * bonus_per)
    return min(rate, max_rate)
```

> **Implementation note:** The original pseudocode above omitted `signup_bonus`. The actual implementation includes it. A referred seller who also refers others must retain their signup bonus when their rate is recalculated — otherwise confirming a referral would paradoxically not change their rate (20 + 10 = 30, same as their existing 30). The correct formula: `base + signup_bonus (if referred) + (confirmed × bonus_per)`. See DECISIONS.md for full reasoning.
```

This is called when a referral is confirmed and the result stored in `User.payout_rate`. The stored value is what gets used everywhere — do not recompute dynamically at payout time, since AppSettings could change.

### Payout Amount Calculation (Item Sold)
```python
payout_amount = item.price * (item.seller.payout_rate / 100)
```

Replaces all existing logic that reads `collection_method`.

### Applying a Referral Code at Registration
```python
def apply_referral_code(new_user, code):
    if not code:
        return
    if AppSetting.get('referral_program_active', 'true') != 'true':
        return
    referrer = User.query.filter_by(referral_code=code.strip().upper()).first()
    if not referrer or referrer.id == new_user.id:
        return  # invalid or self-referral
    signup_bonus = int(AppSetting.get('referral_signup_bonus', '10'))
    max_rate = int(AppSetting.get('referral_max_rate', '100'))
    new_user.referred_by_id = referrer.id
    new_user.payout_rate = min(new_user.payout_rate + signup_bonus, max_rate)
    referral = Referral(referrer_id=referrer.id, referred_id=new_user.id)
    db.session.add(referral)
    # Do NOT update referrer's payout_rate here — that only happens on item arrival
```

### Confirming a Referral (Inside `crew_intake_submit`)
When `arrived_at_store_at` is being set on an item for the first time:
```python
def maybe_confirm_referral(item):
    seller = item.seller
    if not seller.referred_by_id:
        return
    existing = Referral.query.filter_by(
        referrer_id=seller.referred_by_id,
        referred_id=seller.id,
        confirmed=True
    ).first()
    if existing:
        return  # already confirmed from a previous item of this seller
    referral = Referral.query.filter_by(
        referrer_id=seller.referred_by_id,
        referred_id=seller.id
    ).first()
    if not referral:
        return
    referral.confirmed = True
    referral.confirmed_at = datetime.utcnow()
    referrer = referral.referrer
    referrer.payout_rate = calculate_payout_rate(referrer)
    db.session.commit()
    send_referral_confirmed_email(referrer, seller)
```

**Important:** Only trigger `maybe_confirm_referral` when `arrived_at_store_at` transitions from `None` to a value — not on every intake submission (items can have multiple intake records due to the append-only design).

### Edge Cases

| Case | Behavior |
|------|----------|
| User enters invalid referral code | Code field ignored, `payout_rate` stays at 20%, no error blocks signup |
| User enters their own referral code | Detected by `referrer.id == new_user.id` — ignored silently |
| Referred seller's item is rejected/flagged | Referral not confirmed (only `arrived_at_store_at` triggers it, which isn't set for rejected items) |
| Referred seller has multiple items | First item to arrive confirms the referral; subsequent items do not grant additional credit |
| Referrer already at 100% | `calculate_payout_rate` returns 100 (capped); no error, just no change |
| `referral_program_active` set to `'false'` | Code validation returns invalid; no bonuses applied; stored `payout_rate` values are frozen and used as-is |
| Existing sellers (pre-feature) | Given codes via migration script. `payout_rate` set to 20 via migration. `referred_by_id` = None. They can start referring immediately. |
| OAuth signup with referral code in URL | Code saved to Flask session before OAuth redirect, applied on callback |
| Guest onboarding with referral code in URL | Code saved to session at any entry point, applied when account is created at wizard end |

---

## Constraints

The following must not be touched:

- **Stripe webhook logic** — no changes. The webhook sets `has_paid` and activates sellers. Payout rate is not involved in the purchase flow.
- **`collection_method` field on `InventoryItem`** — retain in DB. New sellers will still get `collection_method='free'` as default (the Pro upgrade UI is removed, but the field stays). Do not add migration to remove it.
- **`/upgrade_pickup` and `/upgrade_checkout` routes** — leave routes in place (return 404 or redirect to dashboard). Do not delete — avoids broken bookmarks or email links.
- **`has_paid` on User** — leave as-is. Previously tracked Pro fee payment. Harmless to retain.
- **Item status lifecycle** — no changes. `arrived_at_store_at` is already set by the intake flow; this spec only reads that event, doesn't modify when/how it's set.
- **Admin two-tier role system** (`is_admin` / `is_super_admin`) — no changes.
- **SellerAlert system** — no changes, though a new `alert_type` of `'referral_confirmed'` could be added in a future iteration to surface the confirmation in-dashboard without email. Out of scope for this spec.
- **The Free Tier confirm/reject system** — already commented out of UI. Leave it. Do not re-activate.
- **Payout is still manual** — admin marks payout sent via the existing `payout_sent` boolean. This spec does not automate payouts. The payout amount shown to admin (and in emails) simply uses `payout_rate` instead of `collection_method`.
