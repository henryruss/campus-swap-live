# Feature Spec: Seller Dashboard & Account Settings Redesign

## Goal

The seller onboarding wizard has been slimmed down to just item upload — account setup details (pickup week, address, payout info) are now collected post-signup. This leaves the dashboard and account settings cluttered, inconsistent, and visually behind the quality of the ops system UI. This spec redesigns both surfaces to be clean, hierarchy-driven, and mobile-friendly, using modals for all inline setup tasks.

---

## UX Flow

### Dashboard (`/dashboard`)

**Top to bottom layout:**

1. **Page header** — "Seller Studio" title + subtitle + Log Out button
2. **Setup strip** — shown only while any setup step is incomplete. Disappears when all three steps are done. Contains:
   - Phone number (always shown as ✓ done once set; the phone nag banner handles collection separately — this chip is display-only)
   - Pickup week & address (combined, opens modal — step 1)
   - Payout info (opens modal — step 2)
3. **Stats bar** — 4 cards: Potential Earnings, Paid Out, Items, Pickup Window. Pickup Window card is clickable and opens the pickup week & address modal.
4. **SellerAlert banners** — only `needs_info` and `pickup_reminder` alert types remain here. `pickup_reminder` opens the pickup week & address modal instead of linking away. No "items awaiting approval" banner — pending state is communicated on the item cards themselves.
5. **Saved drafts** — slim row per draft, only shown if drafts exist.
6. **My shop** — full-width item grid. 3 columns desktop, 2 columns mobile.
7. **Refer & Earn** — always-visible dark green card at bottom.

### Setup Strip Logic

- Strip is shown if any of the following are true: `current_user.phone is None`, `not current_user.has_pickup_location`, `current_user.payout_method is None`
- Strip is hidden entirely once all three are complete
- Phone chip: always shown. Green ✓ if `phone` is set, amber "Add phone →" if not. Clicking the amber state focuses the phone nag banner input (JS scroll + focus). Does not open a modal.
- Pickup week & address chip: amber with numbered badge "1" and arrow if incomplete, green ✓ if `has_pickup_location` and `pickup_week` are both set. Clicking opens the pickup/address modal.
- Payout info chip: amber with numbered badge "2" and arrow if incomplete, green ✓ if `payout_method` is set. Clicking opens the payout modal.

### Item Cards — Pending State

Pending items (`status == 'pending_valuation'` or `status == 'needs_info'`) get a frosted overlay on the thumbnail with large muted text: "Pending review" or "Needs update" respectively. No separate alert banner for pending-only state. The `needs_info` SellerAlert banner still appears above the grid for items needing action, since it contains the specific feedback the seller needs to act on.

### Pickup Week & Address Modal

Single modal covering both fields together. Fields:

- **Week** — two cards: Week 1 (dates), Week 2 (dates)
- **Time preference** — two cards: Morning / Afternoon (no Evening option)
- **Where do you live?** — two cards: On campus (dorm) / Off campus
- **Address** — text input (full address)
- **Additional directions** — optional text input

On save: POST to existing `/update_profile` for address fields, POST to `/api/user/set_pickup_week` for week + time preference. These can be two sequential fetch calls client-side, both must succeed before the modal closes and the strip/stat card updates. On failure, show inline error in the modal without closing it.

The modal is triggered from: setup strip chip, pickup window stat card, `pickup_reminder` SellerAlert button.

### Payout Modal

Fields:

- **Method** — three cards: Venmo / PayPal / Zelle
- **Handle / Phone or email** — text input. Label and placeholder change dynamically based on selected method: Venmo/PayPal show "Handle" with `@ username` placeholder; Zelle shows "Phone or email" with `e.g. 919-555-0123 or you@email.com` placeholder.
- **Confirm handle / Confirm phone or email** — confirmation input, label mirrors the field above.

On save: POST to existing `/update_payout`. Modal closes on success, setup strip and stat cards update inline. On failure, inline error without closing.

### Refer & Earn Card

Always visible. Dark green background (`--primary`). All text is white, cream (`--text-light` / `--bg-cream`), or sage (`--sage`). No dark text on this card anywhere.

Left side:
- Large payout rate (e.g. "20%") in cream
- "your payout rate" label in sage
- Progress bar (amber fill, white-tinted track) from 20% to 100% with percentage labels
- "X of 8 referrals completed" in sage-light
- Description copy in sage-light

Right side (separated by a faint vertical divider):
- "Your code" label in sage
- Code display box (semi-transparent white bg) with Copy button
- Share with friends button (ghost style, white border)
- Boost box (amber-tinted inset card) — shown only if `not has_paid_boost` and `payout_rate < 100`. Contains boost title in amber-light, description in sage-light, CTA button in amber. Hidden once boost is purchased or rate hits 100%.

---

### Account Settings (`/account_settings`)

Three sections only. Payout boost section removed entirely — it lives on the dashboard.

**Section 1: Account info**
- Email (read-only, with note "Email cannot be changed" or "Managed via Google" for OAuth users)
- Full name (editable)
- Phone number (editable)
- POST to `/update_account_info`

**Section 2: Change password**
- Only shown for non-OAuth accounts (check `current_user.oauth_provider is None`)
- Current password, new password, confirm new password
- POST to `/change_password`
- For OAuth users: replace this section with a single muted line — "Your account uses Google sign-in. Password is managed by Google."

**Section 3: Pickup & payout**
Two sub-cards within one section card, each with its own Save/Edit trigger:

- **Pickup location** — same dorm/address form as the modal. Shows current values pre-filled if set. POST to `/update_profile`.
- **Payout info** — method + handle fields, same as modal. Shows current values pre-filled. POST to `/update_payout`.

The "Payout Boost" card that currently lives at the bottom of `account_settings.html` is removed. No replacement — the dashboard is the home for that.

---

## New Routes

No new routes required. All existing POST endpoints are reused:

| Method | Path | Function | Used for |
|--------|------|----------|----------|
| POST | `/update_profile` | `update_profile` | Pickup address fields |
| POST | `/api/user/set_pickup_week` | `api_set_pickup_week` | Pickup week + time preference (AJAX, returns JSON) |
| POST | `/update_payout` | `update_payout` | Payout method + handle |
| POST | `/update_account_info` | `update_account_info` | Name + phone |
| POST | `/change_password` | `change_password` | Password change |

---

## Model Changes

None. No new fields or tables. No migration required.

---

## Template Changes

### `dashboard.html` — full rewrite of layout and structure

**Remove:**
- Two-column layout (items left, referral widget right)
- "Items Awaiting Approval" banner (the generic pending state banner — keep `needs_info` SellerAlert banners)
- "Boost Your Payout" standalone card section
- Address nag banner (replaced by setup strip)
- Upgrade card ("You're on the free plan...") — legacy, no longer relevant post-tier-removal

**Add:**
- Setup strip (phone ✓ chip, pickup week & address chip, payout info chip)
- Pickup week & address modal (`#modal-pickupaddr`) — HTML in template, shown/hidden via JS
- Payout modal (`#modal-payout`) — HTML in template, shown/hidden via JS
- Pending overlay on item thumbnails for `pending_valuation` and `needs_info` items
- Full-width item grid (3 col desktop / 2 col mobile)
- Full-width Refer & Earn card at bottom (all-light-text variant)

**Modify:**
- Stats bar: Pickup Window card gets `data-modal="pickupaddr"` and cursor pointer, opens modal on click
- SellerAlert `pickup_reminder` banner: button opens `#modal-pickupaddr` instead of linking to `/confirm_pickup`
- Item cards: add pending overlay logic; color-code border by status (amber border for `needs_info`, sage border for `approved`/`available`)

**JS additions (vanilla, in `<script>` at bottom of template):**
- `openModal(id)` / `closeModal(id)` — toggle `.open` class on `.modal-overlay`
- Overlay click-to-close: close if `event.target === overlay`
- Escape key handler: close any open modal
- Payout method selector: dynamically update handle label/placeholder based on selected method
- Pickup week & address save: two sequential fetch POSTs, inline error handling, strip/stat card update on success without full page reload
- Payout save: fetch POST to `/update_payout`, inline error handling, strip update on success
- Phone chip click: `window.scrollTo` to phone nag banner + `document.querySelector('#phone-input').focus()`

**Mobile modal behavior:**
On screens ≤ 540px, modals become bottom sheets: `position: fixed; bottom: 0; left: 0; right: 0; border-radius: 20px 20px 0 0; max-width: 100%`. Achieved via `@media (max-width: 540px)` CSS in `style.css` scoped to `.modal` within `.modal-overlay`.

### `account_settings.html` — restructure

**Remove:**
- Payout Boost card (entire section)
- "Pickup Preferences" card (pickup week display + time preference + moveout date) — this is now set via dashboard modal, not account settings
- Separate "Pickup Location" and "Payout Info" cards replaced by unified "Pickup & Payout" section

**Keep:**
- Account Info card (name, phone, email read-only) — reorder to be first
- Change Password card — second (hidden for OAuth users, replaced with single explanatory line)

**Add:**
- "Pickup & Payout" section as third card: two sub-sections (pickup location form, payout info form), each with its own submit button and action. Pre-fill current values from `current_user`.

---

## Business Logic

**Setup strip visibility:** Server computes three booleans passed to template context: `setup_phone_done = current_user.phone is not None`, `setup_pickup_done = current_user.has_pickup_location and current_user.pickup_week is not None`, `setup_payout_done = current_user.payout_method is not None`. Strip hidden via Jinja `if` when all three are true.

**Pending overlay:** Item card thumbnail overlay shown when `item.status in ('pending_valuation', 'needs_info')`. Text: "Pending review" for `pending_valuation`, "Needs update" for `needs_info`.

**Pickup week & address modal save sequence:**
1. Client POSTs address fields to `/update_profile` via fetch
2. On success, client POSTs week + time to `/api/user/set_pickup_week` via fetch
3. On both success: update setup strip chip to green ✓, update Pickup Window stat card inline, close modal
4. On either failure: show error message inside modal, do not close

**Payout modal validation:** Handle and confirm-handle must match before POST is sent (client-side check). If mismatch, show inline error "Handles don't match" without submitting.

**Evening option removed** from time preference everywhere (modal and account settings). If any existing users have `pickup_time_preference == 'evening'` in the DB, their value is preserved and displayed as-is in account settings — no migration needed, just remove Evening from the selection UI going forward.

**Refer & Earn card text colors:** Every text element on the dark green card must use `--text-light` (`#F5F0E8`), `--sage` (`#8AB88A`), or `--sage-lt` (`#C2D9C2`). The `--text-main` / `--primary` green is never used on this card. The boost box inset uses `--amber-lt` (`#F2DDB7`) for the title and `--sage-lt` for body text.

---

## Constraints

- Do not touch any route handler logic — all changes are template and CSS only, plus vanilla JS in the template.
- Do not remove the phone nag banner from `dashboard.html` — it remains as the primary phone collection mechanism. The setup strip phone chip is display-only (✓ or a scroll-to-banner link).
- Do not remove `confirm_pickup.html` — it is deprecated and unreachable but preserved for legacy link safety.
- Do not add Evening back to time preference UI.
- Pickup week dates shown in modal must match `PICKUP_WEEKS` / `PICKUP_WEEK_DATE_RANGES` from `constants.py` — never hardcode date strings in the template.
- `_get_payout_percentage(item)` is still used for earnings calculations — do not change this.
- The `address nag` banner (grey, links to account settings) is removed since the setup strip replaces its purpose. Confirm removal doesn't break any other logic before deleting.
- Do not modify any admin templates.
