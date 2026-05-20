# Feature Spec: Proxy Seller Accounts

**Status:** Ready for implementation  
**Depends on:** Nothing — purely additive  

---

## Goal

Campus Swap occasionally acquires sellers through direct contact (text, call) who never self-onboarded — parents moving out a student's apartment, sellers who heard about us too late, etc. Staff have phone/address/item info but no account exists. This feature lets admins create a "proxy" account on the seller's behalf, pre-load their items, then hand off a claim link via text so the seller can take ownership. No code deploy needed for each new case.

---

## UX Flow

### Admin Side

1. Admin visits `/admin/sellers`.
2. Clicks **"+ Create Proxy Account"** button (top-right of sellers table).
3. A modal opens with fields:
   - **Name** (required)
   - **Phone** (required — primary contact method for these sellers)
   - **Email** (optional — if admin has it; otherwise left blank and a placeholder is generated)
   - **Pickup address** (optional — same on_campus / off_campus_other flow as existing; can be filled later)
   - **Note** (optional — internal note, e.g. "Mom of Jake, Apt 4B, texted 5/20")
4. Admin submits. Server creates the account with:
   - `is_proxy_account = True`
   - `proxy_temp_password` = randomly generated 6-character uppercase alphanumeric code (stored in plaintext for display; also set as actual password hash so it works at login)
   - Email = supplied email if provided, otherwise `proxy+<phone_digits>@usecampusswap.com`
   - `is_seller = True`, `payout_rate = 20` (standard base rate)
   - Referral code generated as normal
   - **No welcome email sent**
5. Modal closes, seller row appears in table with a **"⚠ Proxy"** amber badge.
6. Admin clicks the seller's name → existing slide-out panel opens. The panel shows a highlighted proxy banner at the top:
   - Temp password (copyable)
   - **"Copy Claim Link"** button → copies `/claim/<token>` URL to clipboard
   - **"Copy SMS Message"** button → copies a ready-to-send text: *"Hey [Name]! Campus Swap here — we picked up your stuff. Your account is ready: [claim link]. Temp password: [password]. You can log in to track your items and get paid. – Campus Swap Team"*
   - **"Mark as Contacted"** checkbox — sets `proxy_contacted_at` timestamp; proxy banner turns grey to indicate "done, waiting on them"
7. Admin can now add items to this account via the existing admin item-approval flow (items created directly against this `seller_id`), or drivers can use the existing quick-capture flow against this account during the shift.

### Seller (Claim) Side

1. Seller opens the `/claim/<token>` link on their phone.
2. Lands on `claim_account.html` — a minimal, friendly page (no nav, extends layout for footer/analytics). Feels like signing up for the first time, not a password-reset form. Layout:
   - Campus Swap logo centered
   - Headline: **"Your items are ready — claim your account"**
   - Short copy: "We've got your stuff. Set up your account to track your items and get paid when they sell."
   - **Google Sign-In button** (primary CTA, full-width) — same OAuth flow as `/auth/google`, but with `claim_token` stashed in session so the callback knows to finalize the claim
   - Divider: "or continue with email"
   - **Email** field
   - **Password** field + **Confirm password** field
   - Submit button: "Claim My Account"
3. On submit (email path):
   - Validate email format and uniqueness — if email already belongs to a *different* account, show inline error: "That email is already in use. Contact us if you need help."
   - If the account already had a real email (admin provided one at creation), pre-fill the email field and make it editable — seller can correct it
   - Password: min 6 chars, must match confirm
   - Email updated on the user record
   - Password updated to the new hash
   - `is_proxy_account = False`, `proxy_claim_token` cleared, `proxy_temp_password` cleared, `proxy_claimed_at` set
   - Seller logged in via `login_user()`, redirected to `/dashboard`
   - Flash: "Welcome to Campus Swap! Your items are listed below."
   - **Welcome email sent** at this point (not at account creation)
4. On submit (Google OAuth path):
   - Standard `/auth/google` redirect, but `claim_token` stored in session as `pending_claim_token`
   - In `auth_google_callback`: after Google returns the profile, check for `pending_claim_token` in session
   - Look up the proxy account by token — validate not expired, still proxy
   - If Google email already belongs to a *different* account: abort OAuth, redirect to `/claim/<token>` with flash error "That Google account is already connected to a different Campus Swap account."
   - Otherwise: update the proxy user's email to the Google email, set `oauth_provider='google'`, `oauth_id`, clear proxy fields, mark claimed, log in, redirect to `/dashboard` with welcome flash
   - Welcome email sent same as email path
5. If token is expired (>30 days) or already used: show error variant of `claim_account.html` with "Contact us" link — no form shown.

---

## New Routes

| Method | Path | Function | Description |
|--------|------|----------|-------------|
| `POST` | `/admin/seller/create-proxy` | `admin_create_proxy_seller` | Creates proxy account. Admin only. Returns JSON `{success, user_id, seller_name}` for modal feedback. |
| `POST` | `/admin/seller/<user_id>/generate-claim-link` | `admin_generate_claim_link` | Regenerates `proxy_claim_token` + `proxy_token_expires_at`. Returns JSON `{claim_url, sms_text, temp_password}`. Admin only. Called on first panel open if no token exists yet, or on explicit "Regenerate" click. |
| `POST` | `/admin/seller/<user_id>/proxy-contacted` | `admin_proxy_mark_contacted` | Sets `proxy_contacted_at = now()`. Admin only. Returns JSON `{success}`. |
| `GET` | `/claim/<token>` | `claim_account` | Renders claim page. Validates token exists + not expired + account still proxy. |
| `POST` | `/claim/<token>` | `claim_account_submit` | Validates passwords, updates account, logs seller in, redirects to `/dashboard`. |

---

## Model Changes

All changes to the `User` model. One migration required.

```python
# New fields on User
is_proxy_account      = db.Column(db.Boolean, default=False, server_default='0')
proxy_temp_password   = db.Column(db.String(20), nullable=True)   # plaintext, cleared on claim
proxy_claim_token     = db.Column(db.String(64), nullable=True, unique=True)
proxy_token_expires_at = db.Column(db.DateTime, nullable=True)    # UTC
proxy_contacted_at    = db.Column(db.DateTime, nullable=True)     # UTC, set by admin
proxy_claimed_at      = db.Column(db.DateTime, nullable=True)     # UTC, set on successful claim
proxy_note            = db.Column(db.String(500), nullable=True)  # internal admin note
```

Migration name suggestion: `add_proxy_seller_fields`

No new tables. No changes to `InventoryItem`.

---

## Template Changes

### New Template: `claim_account.html`
Extends `layout.html`. Minimal page, no sidebar nav. Contains:
- Logo centered at top
- Card: headline, subtext, password + confirm fields, submit button
- Error state variant (token invalid/expired): different headline + contact link
- Uses CSS variables only, no hardcoded colors

### Modified Template: `admin_seller_panel.html`
At the very top of the panel, before all existing content, add a **proxy banner block** (conditionally rendered when `user.is_proxy_account`):
- Amber `SellerAlert`-style card
- Label: "⚠ Proxy Account — Not Yet Claimed"
- Temp password display with copy button
- "Copy Claim Link" button (calls `admin_generate_claim_link` via fetch on first click if no token, then copies result URL)
- "Copy SMS Message" button (same fetch result, copies sms_text)
- "Mark as Contacted" checkbox (POSTs to `admin_proxy_mark_contacted`; checked + greyed if `proxy_contacted_at` is set)
- If `proxy_note` is set: display below in small muted text
- Once `is_proxy_account = False` (claimed): banner not shown

### Modified Template: `admin/sellers.html`
- **"+ Create Proxy Account"** button in the table header row (right-aligned)
- Clicking opens a modal (vanilla JS, no framework) with the creation form
- Proxy accounts in the seller table get an amber **"Proxy"** pill badge in the Name column
- Claimed proxy accounts (is_proxy_account=False but proxy_claimed_at set) get a subtle green **"Claimed"** pill — useful for audit trail

---

## Business Logic

### Account Creation
- If email is provided: use it as-is after basic format validation.
- If email is omitted: generate `proxy+<digits_only_from_phone>@usecampusswap.com`. This is a valid unique email that never receives mail (no MX record for that subdomain), which is intentional — all communication goes through phone.
- `referral_code` generated with `generate_unique_referral_code()` as normal.
- `payout_rate = 20` (base rate, no referral code applied).
- `is_seller = True` at creation so they show up in seller flows immediately.
- Temp password: 6-char uppercase alphanumeric, excluding O, 0, I, 1 (same charset as referral codes). Generated with a simple `secrets.choice` loop. Stored in `proxy_temp_password` as plaintext for admin display and separately hashed + stored in `password_hash` so login works.
- No welcome email at creation. Welcome email fires only on successful claim.

### Claim Token
- 64-char `secrets.token_urlsafe(48)` stored in `proxy_claim_token`.
- Expires 30 days from generation (`proxy_token_expires_at`).
- Token generated lazily on first call to `admin_generate_claim_link`, not at account creation (avoids generating tokens for accounts that never get a link sent).
- "Regenerate link" re-runs `admin_generate_claim_link` — overwrites old token and resets expiry. Old link immediately invalid.
- Token is single-use: cleared on successful claim.

### Claim Validation
- `GET /claim/<token>`: look up `User` by `proxy_claim_token`. If not found, expired (`proxy_token_expires_at < now()`), or `is_proxy_account=False` → render error variant of `claim_account.html` (no form). If valid, render form with email pre-filled if the account has a non-placeholder email.
- `POST /claim/<token>` (email path): re-validate token on submit (race condition guard). Validate email format. Check no *other* user has that email. Validate password min 6 chars + match. On success: update `email`, `password_hash`, clear `proxy_claim_token`, clear `proxy_temp_password`, set `proxy_claimed_at`, set `is_proxy_account=False`, `login_user()`, redirect to `/dashboard`.
- **Google OAuth path**: `GET /claim/<token>` stores `pending_claim_token` in session, then redirects to `/auth/google`. In `auth_google_callback`, after receiving Google profile, check `session.get('pending_claim_token')`. If present: look up proxy account by that token (re-validate), check Google email not in use by another account, apply Google credentials + clear proxy fields, claim the account, log in, redirect to `/dashboard`. Clear `pending_claim_token` from session on success or failure. The existing `auth_google_callback` logic for new vs. returning accounts is bypassed when `pending_claim_token` is present — claim path takes full control.

### Admin Panel — Generate Link Behavior
- `POST /admin/seller/<user_id>/generate-claim-link` is idempotent within a valid token window: if a token exists and is not expired, return the existing one. If expired or absent, generate a new one.
- Response JSON:
  ```json
  {
    "claim_url": "https://usecampusswap.com/claim/<token>",
    "sms_text": "Hey [Name]! Campus Swap here — we picked up your stuff. Claim your account and track your items here: https://usecampusswap.com/claim/<token> – Campus Swap",
    "temp_password": "ABC123"
  }
  ```
  Note: `temp_password` is still returned for the admin panel display (break-glass reference), but is no longer included in `sms_text`.

### Items
- No changes to item creation flow. Admins add items to a proxy account the same way they would any seller account — via the approval queue, quick capture during a shift, or by logging in as the user (existing admin impersonation if that exists, otherwise items are just attributed to the seller_id).
- Items created under a proxy account remain attached after claim — `seller_id` doesn't change.

### Edge Cases
- **Seller tries to log in before claiming:** Normal login won't work — they don't know the placeholder email or temp password. This is fine and expected. The claim link is the only path in.
- **Admin creates duplicate phone number:** No unique constraint on `phone` currently, so no change needed. If same phone submits, admin will see two accounts — expected behavior, admin resolves manually.
- **Proxy account with placeholder email:** No password reset possible (placeholder email receives no mail). Intentional — they claim via the token link only. After claiming with a real email, normal password reset works.
- **Google account already in use by another user:** Both paths (email + OAuth) check for email uniqueness against other accounts. Error shown inline on the claim page; seller contacts support to resolve.
- **Welcome email suppression:** Guard in account creation path — check `is_proxy_account=True` before sending any email. PostHog `seller_signed_up` event still fires at creation (want the analytics). Welcome email (#11) fires on claim completion only.
- **SMS text no longer includes temp password:** Since the claim page collects credentials fresh, there's no reason to put a temp password in the text. Updated SMS text: *"Hey [Name]! Campus Swap here — we picked up your stuff. Claim your account and track your items here: [claim_url] – Campus Swap"*

---

## Constraints

- **Do not touch** the existing `register`, `onboard`, or `onboard_complete_account` routes — proxy creation is a separate admin-only path.
- **Do not touch** Stripe or payout logic — proxy sellers have `payout_rate=20` like all sellers; nothing special.
- **Do not touch** the referral program — proxy accounts get a referral code generated (standard) but no referral code is applied at creation (no `referred_by_id`).
- **Do not touch** the existing seller panel HTML outside of adding the proxy banner block at the top — all existing panel sections (items, alerts, etc.) render as-is.
- **Do not send** the existing welcome email (#11 in the emails table) at proxy account creation. It fires on claim only.
- The `proxy+...@usecampusswap.com` placeholder email must never be sent to by any email helper. Add a guard: `if user.email.startswith('proxy+') and user.email.endswith('@usecampusswap.com'): skip_email`.
