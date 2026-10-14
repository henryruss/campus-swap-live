# Feature Spec: Admin Seller Profile Panel

## Goal
Give admins a fast, complete view of any individual seller without leaving the admin panel. Clicking a seller's name anywhere in the admin UI slides open a panel showing their full profile: contact info, service tier, pickup status, payout details, and all their items. From this same panel, admins can send the seller a preset alert or a custom free-text message that appears on the seller's dashboard.

---

## UX Flow

### Opening the Panel
- Anywhere a seller's name appears in the admin UI (user table, item lifecycle table, approval queue, free-tier management list), the name is a clickable link
- Clicking it slides open a panel from the right side of the screen (standard slide-out drawer pattern)
- The rest of the admin page remains visible and interactive behind the panel
- Panel can be closed by clicking an X button, pressing Escape, or clicking outside the panel

### Panel Contents

**Section 1 — Seller Identity**
- Full name
- Email address (clickable mailto link)
- Phone number (or "—" if not provided)
- Date joined
- Account type badge: Guest / Full Account
- Admin badge if applicable

**Section 2 — Seller Status**
- Service tier: Free Plan / Pro (Valet Pickup)
- Payment status: Has Paid / Awaiting Payment / N/A
- Payout method + handle (e.g. "Venmo: @username"), or "—" if not set
- Referral source (where they heard about us)

**Section 3 — Pickup Info**
- Pickup location type: On-Campus or Off-Campus
- If on-campus: dorm name + room number
- If off-campus: address + any pickup note
- Pickup week selected: Week 1 (4/27–5/3) / Week 2 (5/4–5/10) / **Not selected** (shown in amber if missing)
- Preferred time of day (once pickup week updates are deployed): Morning / Afternoon / Evening / Not selected
- Move-out date (once pickup week updates are deployed): date or "Not provided"

**Section 4 — Items**
A compact list of all items this seller has submitted. For each item:
- Thumbnail (small, ~60x60px)
- Item title
- Category
- Price (or suggested price if not yet approved)
- Current status badge (color-coded: pending, needs info, approved, available, sold, rejected)
- Quick action link: "View" → opens item detail in admin approve view or admin panel

**Section 5 — Send Alert / Message**
A form at the bottom of the panel:
- **Preset alerts** (radio or dropdown, pick one):
  - "Please upload better photos for your item"
  - "A video is required for your item — please show it powering on"
  - "Please select your pickup week"
  - "Please confirm your pickup address"
  - "Please set up your payout method"
- **OR** select "Custom message" and write free text (textarea, max 500 chars)
- If a preset is selected that is item-specific (photos, video), a secondary dropdown appears: "Which item?" — lists the seller's items by title
- Send button: **"Send Alert"**
- On send: creates a `SellerAlert` record, shows success confirmation inline in the panel ("Alert sent.")
- The seller sees the alert on their dashboard (see dashboard alert rendering in `feature_item_action_requests.md`)

---

## New Routes

| Method | Path | Function | Description |
|--------|------|----------|-------------|
| `GET` | `/admin/seller/<user_id>/panel` | `admin_seller_panel` | Returns HTML partial for the slide-out panel. Fetches user, their items, their alerts. Admin only. |
| `POST` | `/admin/seller/<user_id>/send_alert` | `admin_send_seller_alert` | Creates a `SellerAlert` for this seller. Accepts `alert_type`, `preset_reason` or `custom_note`, and optional `item_id`. Admin only. |

The panel content is loaded via a JavaScript fetch call when the admin clicks a seller name — the response is an HTML partial that gets injected into a pre-existing panel container in the admin layout. This avoids a full page reload.

---

## Model Changes

### `SellerAlert` (defined in `feature_item_action_requests.md`)
No additional fields needed beyond what is defined there. The `alert_type` field covers all cases:
- `'needs_info'` — item-specific, set from approval queue
- `'pickup_reminder'` — not item-specific, set from pickup nudge feature
- `'custom'` — free-text from admin seller panel
- `'preset'` — preset reason from admin seller panel (non-item-specific presets)

The `item_id` field is nullable so alerts that are not tied to a specific item (e.g. "please select your pickup week") still work.

**Important:** `feature_item_action_requests.md` must be implemented first, or at the same time, since this feature depends on the `SellerAlert` model existing.

---

## Template Changes

### `templates/admin.html`
- Add a hidden slide-out panel container at the bottom of the page body:
  ```html
  <div id="seller-panel" class="seller-panel seller-panel--closed">
    <div class="seller-panel__overlay"></div>
    <div class="seller-panel__drawer">
      <button class="seller-panel__close">✕</button>
      <div id="seller-panel__content"><!-- loaded via fetch --></div>
    </div>
  </div>
  ```
- All seller name instances in the admin tables become `<a href="#" class="seller-panel-trigger" data-user-id="{{ user.id }}">{{ user.full_name }}</a>`
- Add JavaScript:
  - Click handler on `.seller-panel-trigger` → fetch `/admin/seller/<id>/panel` → inject HTML into `#seller-panel__content` → add class `seller-panel--open`
  - Close handlers: X button click, Escape key, overlay click → remove `seller-panel--open`
  - Send alert form submission → POST to `/admin/seller/<id>/send_alert` → show inline success message

### New Template: `templates/admin_seller_panel.html`
A standalone HTML partial (not extending `layout.html`) that renders the full panel content. Sections as described in UX Flow above. Uses the same CSS variables and component classes as the rest of the admin UI. This partial is only ever rendered inside the slide-out drawer, never as a standalone page.

### CSS additions to `static/style.css`
```css
.seller-panel { ... }           /* fixed overlay + drawer */
.seller-panel--closed { ... }   /* display: none or transform off-screen */
.seller-panel--open { ... }     /* visible, transformed on-screen */
.seller-panel__drawer { ... }   /* right-side panel, fixed width ~480px, scrollable */
.seller-panel__overlay { ... }  /* semi-transparent backdrop */
```
Use CSS variables throughout — no hardcoded colors.

---

## Business Logic

### Who Can Open the Panel
- Any user with `is_admin = True` or `is_super_admin = True`
- The route `/admin/seller/<user_id>/panel` must check admin status and return 403 otherwise

### What Alerts Are Shown in the Panel
- The panel does not show a history of sent alerts by default (keeps it clean)
- It shows only the count of currently unresolved alerts for that seller: e.g. "2 active alerts"
- This is enough context for the admin to know if they've already sent a nudge

### Item-Specific vs. Seller-Level Alerts
- If admin selects a preset like "better photos needed" from the seller panel, they must also select which item it applies to (secondary item dropdown appears)
- If admin selects "please select your pickup week" or writes a custom message, no item selection is needed
- The `item_id` on the `SellerAlert` record is set accordingly

### Alert Deduplication
- If an unresolved alert of the same type already exists for the same seller + item combination, warn the admin before sending another: *"An alert of this type is already pending for this seller."* Allow them to send anyway if they choose.

### Edge Cases
- **Seller has no items:** Panel still opens, Section 4 shows "No items submitted yet"
- **Seller is also an admin:** Panel still works — show admin badge in Section 1, all other info displayed normally
- **User ID does not exist:** Return 404
- **Panel opened for a buyer-only account (non-seller):** Still shows identity and status sections, but pickup info and items sections show "—" or "Not a seller"

---

## Constraints
- The panel must not trigger a full page reload when opening or closing — JavaScript fetch only
- Do not duplicate the `SellerAlert` model — it must be the same model used by `feature_item_action_requests.md` and `feature_pickup_nudge.md`
- Do not add email sending to this feature — all alerts go to the seller's dashboard only, not to their email inbox
- Do not show any buyer purchase history in this panel — it is a seller management tool only
- The panel HTML partial must be kept separate from `admin.html` to keep the template manageable
