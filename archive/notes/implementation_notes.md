# Implementation Notes — Features 1–7 (April 4, 2026)

Exhaustive changelog of every change made across seven feature specs plus bug fixes.

---

## Feature 1: Admin Quick Fixes (`feature_admin_quick_fixes.md`)

### Fix 1 — Phone Number in Admin User Table
- **`app.py`** (`admin_preview_users` route, ~line 5682): Added `'Phone'` to `headers` list and `'phone': user.phone or '—'` to each row dict.
- **`templates/admin.html`** (~line 1059): Phone column was already rendered via the free-tier user cards; no additional table column needed since the user table is rendered via `data_preview.html` using the row data from the route.

### Fix 2 — Remove Item ID from Inventory Cards
- **`templates/inventory.html`**: Verified no item ID badge existed on inventory product cards. No change needed — the ID was never rendered there.

### Fix 3 — Minimum Item Value Notice on Homepage
- **`templates/index.html`**: Added informational callout inside the "Ready to sell?" card section. Uses `var(--bg-cream)` background, `var(--card-border)` border, `var(--text-muted)` color. Threshold set to **$50** (user changed from initial $25).

---

## Feature 2: Expanded Video Requirements (`feature_video_requirements.md`)

### Constants
- **`constants.py`** (~line 41): `VIDEO_REQUIRED_CATEGORIES` expanded from 6 to 15 keywords:
  ```python
  ['tv', 'television', 'gaming', 'console', 'printer', 'electronic',
   'mini fridge', 'fridge', 'microwave', 'heater', 'ac', 'air conditioner',
   'blender', 'scooter', 'air fryer']
  ```
- **`constants.py`** (~line 48): `category_requires_video(category_name, subcategory_name='')` updated to accept optional `subcategory_name` parameter. Does case-insensitive substring match against both names.

### Backend
- **`app.py`** (imports): Added `VIDEO_REQUIRED_CATEGORIES` to constants import.
- **`app.py`** (context processor `inject_store_functions`): Added `video_required_keywords=VIDEO_REQUIRED_CATEGORIES` so templates can use `{{ video_required_keywords | tojson }}` instead of hardcoding.
- **`app.py`** (onboard POST ~line 4351, guest POST ~line 4539, add_item POST ~line 5284): Updated backend video enforcement to pass subcategory name and use generic error message: *"A video is required for this item category."*

### Templates
- **`templates/onboard.html`** (~line 777): Replaced hardcoded JS `VIDEO_REQUIRED_KEYWORDS` array with `{{ video_required_keywords | tojson }}`. Added `video-required-banner` div (amber left-border callout). Updated `updateVideoBadge()` to toggle banner and update hint text.
- **`templates/add_item.html`** (~line 263): Same changes as onboard.html — template variable instead of hardcoded array, banner, updated validation.
- **`templates/edit_item.html`** (~line 137): Added soft reminder banner for video-required categories without video (no hard block on save).
- **`templates/admin_approve.html`** (~line 356): Added advisory note for missing video on required categories during approval review.

---

## Feature 3: Pickup Week Updates (`feature_pickup_week_updates.md`)

### Constants
- **`constants.py`**: Updated `PICKUP_WEEKS` from `('week1', 'April 26 – May 2'), ('week2', 'May 3 – May 9')` to `('week1', 'April 27 – May 3'), ('week2', 'May 4 – May 10')`.
- **`constants.py`**: Added `PICKUP_WEEK_DATE_RANGES = {'week1': ('2026-04-27', '2026-05-03'), 'week2': ('2026-05-04', '2026-05-10')}`.
- **`constants.py`**: Added `PICKUP_TIME_OPTIONS = ['morning', 'afternoon', 'evening']`.

### New Model Fields
- **`models.py`** (`User` model):
  - `pickup_time_preference = db.Column(db.String(20), nullable=True)` — values: `'morning'` | `'afternoon'` | `'evening'` | None
  - `moveout_date = db.Column(db.Date, nullable=True)` — seller's exact move-out date
- **Migration**: `b5c46df7b729` — adds both columns as nullable with no default.

### Backend
- **`app.py`** (imports): Added `PICKUP_WEEK_DATE_RANGES`, `PICKUP_TIME_OPTIONS` to constants import.
- **`app.py`** (`confirm_pickup` POST, both free and paid paths): Added `pickup_time_preference` validation (required, must be in `PICKUP_TIME_OPTIONS`), `moveout_date` validation (optional, must fall within selected week's date range), saves both to `current_user`.
- **`app.py`** (`upgrade_pickup` POST): Same validation and saving of new fields, with `db.session.commit()` before Stripe redirect.
- **`app.py`** (`dashboard` route): Computes `pickup_method_label` as `"Wk 1 · Morning"` format when time preference set.
- **`app.py`** (`update_account_info` handler): Accepts `pickup_time_preference` and `moveout_date` from form.
- **`app.py`** (CSV export `/admin/export/users`): Added `'Pickup Time Preference'` and `'Move-Out Date'` columns.

### Templates
- **`templates/confirm_pickup.html`**: Added time-of-day radio button group (morning/afternoon/evening). Added optional date picker with `min`/`max` constraints. Added JS to constrain date picker based on selected week, reset on week change. Added time preference validation in `validateStep`. Updated `populateReview` to show time preference and moveout date.
- **`templates/upgrade_pickup.html`**: Same three field additions as confirm_pickup.
- **`templates/account_settings.html`**: Added "Pickup Preferences" card (visible when user has items with pickup_week set). Shows read-only pickup week, editable time preference dropdown, editable moveout date picker.
- **`templates/dashboard.html`**: Updated "Pickup Window" stat cell to show `"Wk 1 · Morning"` format when both week + time preference are set.
- **`CODEBASE.md`**: Updated pickup_week date reference from old to new dates.

---

## Feature 4: Item Action Requests / "More Info Needed" (`feature_item_action_requests.md`)

### New Model
- **`models.py`**: `SellerAlert` model:
  ```python
  id              — Integer, PK
  item_id         — Integer, FK to InventoryItem, nullable
  user_id         — Integer, FK to User, not null
  created_by_id   — Integer, FK to User, nullable
  alert_type      — String(30), default 'needs_info' (values: 'needs_info' | 'pickup_reminder' | 'custom' | 'preset')
  reasons         — Text, nullable (JSON-encoded list)
  custom_note     — Text, nullable
  resolved        — Boolean, default False
  resolved_at     — DateTime, nullable
  created_at      — DateTime, default utcnow
  ```
  Relationships: `item`, `user` (backref `seller_alerts`), `created_by`
- **Migration**: `11e979ce55c8` — creates `seller_alert` table.

### New Item Status
- `'needs_info'` added as a valid `InventoryItem.status` value. Full list: `'pending_valuation'` | `'needs_info'` | `'approved'` | `'available'` | `'sold'` | `'rejected'`

### New Routes
| Method | Path | Function | Description |
|--------|------|----------|-------------|
| `POST` | `/admin/item/<id>/request_info` | `admin_request_info` | Admin submits "more info needed" request |
| `POST` | `/admin/item/<id>/cancel_request` | `admin_cancel_info_request` | Admin cancels outstanding info request |
| `POST` | `/item/<id>/resubmit` | `resubmit_item` | Seller resubmits item after addressing feedback |

### Backend
- **`app.py`** (imports): Added `SellerAlert` to models import.
- **`app.py`** (template filters): Added `fromjson` filter for parsing JSON strings in Jinja.
- **`app.py`** (`admin_approve` POST): Changed status check from `!= 'pending_valuation'` to `not in ('pending_valuation', 'needs_info')`. Auto-resolves alerts when approving/rejecting needs_info items.
- **`app.py`** (`admin_approve` GET): Computes `resubmitted_item_ids` set from resolved SellerAlert records.
- **`app.py`** (`dashboard` route): Added `unresolved_alerts` query to context.
- **`app.py`** (all `edit_item` render_template calls — 6 occurrences): Added `item_alert` parameter.

### Templates
- **`templates/admin_approve.html`**: Added "More Info Needed" button (amber) alongside Approve/Reject. Added modal with 4 checkbox preset reasons + custom note textarea. Added `'I'` keyboard shortcut. Added "Resubmitted" badge (blue) to browse cards and single-item review.
- **`templates/admin.html`**: Added `needs_info` → "Awaiting Seller" amber badge in lifecycle table. Added "Cancel Request" button for needs_info items.
- **`templates/dashboard.html`**: Added unresolved alert banner section (amber cards with reasons list, custom note, "Update Item" button). Added `needs_info` to bg_class conditions and checklist. Added `needs_info` to modal edit button condition and modal status badge ("Action Needed" in amber).
- **`templates/edit_item.html`**: Added feedback banner at top showing SellerAlert reasons/note when `item.status == 'needs_info'`. Added "Resubmit for Review" button at bottom (POSTs to `/item/<id>/resubmit`), visible only when `item.status == 'needs_info'`.

---

## Feature 5: Admin Seller Profile Panel (`feature_admin_seller_profile.md`)

### New Routes
| Method | Path | Function | Description |
|--------|------|----------|-------------|
| `GET` | `/admin/seller/<user_id>/panel` | `admin_seller_panel` | Returns HTML partial for slide-out panel |
| `POST` | `/admin/seller/<user_id>/send_alert` | `admin_send_seller_alert` | Creates SellerAlert from panel |

### New Template
- **`templates/admin_seller_panel.html`**: HTML partial (no layout extends) with 5 sections:
  1. **Identity**: name, email (mailto), phone, date joined, account type badges (Guest/Full/Admin/Super Admin)
  2. **Seller Status**: service tier, payment status, payout method + handle, referral source
  3. **Pickup Info**: location type, dorm/address, pickup week, time preference, moveout date
  4. **Items**: scrollable list with thumbnails (48x48), title, category, price, status badges, "View" links
  5. **Send Alert**: radio toggle (preset/custom), preset dropdown (5 options), item selector for item-specific presets, custom textarea (500 char max), inline success/error feedback

### CSS
- **`static/style.css`**: Added `.seller-panel`, `.seller-panel--open`, `.seller-panel--closed`, `.seller-panel__overlay`, `.seller-panel__drawer` (480px right-side), `.seller-panel__close`, `.seller-panel-trigger`. All using CSS variables, smooth transitions.

### Template Changes
- **`templates/admin.html`**: Seller names in free-tier section and lifecycle table wrapped in `<a class="seller-panel-trigger" data-user-id="...">`. Panel container injected via JS at page bottom. JS handles fetch → inject → open/close (X button, Escape, overlay click).
- **`templates/admin_approve.html`**: Seller names in single-item review and browse cards wrapped as panel triggers. Same panel JS added.
- **`templates/dashboard.html`**: Added rendering for `preset` and `custom` alert types (from seller panel) alongside existing `needs_info` alerts.

---

## Feature 6: Pickup Nudge (`feature_pickup_nudge.md`)

### New Route
| Method | Path | Function | Description |
|--------|------|----------|-------------|
| `POST` | `/admin/pickup-nudge/send` | `admin_send_pickup_nudge` | Sends pickup reminder alerts to selected or all eligible sellers |

### Backend
- **`app.py`** (`admin_panel` route): Added query for sellers needing nudge — sellers with `is_seller=True`, at least one item with status `approved` or `available`, no item with `pickup_week` set, not rejected free-tier, confirmed if free-tier. Sorted by days since first approval (most urgent first). Passed as `nudge_sellers` to template.
- **`app.py`** (`admin_send_pickup_nudge`): Supports `user_ids` list or `'all'`. Re-queries eligible sellers at send time for "Remind All". Deduplicates: skips sellers with existing unresolved `pickup_reminder` alert. Creates `SellerAlert` with `alert_type='pickup_reminder'`.
- **`app.py`** (auto-resolution in 4 places): After saving `pickup_week` on items, resolves any unresolved `pickup_reminder` SellerAlerts for the user:
  1. Free-tier `confirm_pickup` POST
  2. Stripe webhook `confirm_pickup` case
  3. `confirm_pickup_success` redirect handler
  4. `upgrade_pickup_success` redirect handler

### Templates
- **`templates/admin.html`**: Added collapsible "Pickup Week Not Selected" section after Item Lifecycle. Amber count badge. Table with columns: checkbox, seller name (panel trigger), email, phone, tier badge (Free/Pro), approved item count, days since approval (color-coded: >7d red, >3d amber), last nudged date. "Remind All" and "Remind Selected" buttons with AJAX, select/deselect all checkbox, inline column updates on send.
- **`templates/dashboard.html`**: Added `pickup_reminder` alert rendering: "Action needed: Please select your pickup week" with "Select Pickup Week" button linking to `/confirm_pickup`.

---

## Feature 7: Admin Approval Digest Email (`feature_admin_approval_digest.md`)

### New Model
- **`models.py`**: `DigestLog` model:
  ```python
  id              — Integer, PK
  sent_at         — DateTime, default utcnow
  item_count      — Integer, not null
  recipient_count — Integer, not null
  ```
- **Migration**: `bf6f8e209739` — creates `digest_log` table.

### New Routes
| Method | Path | Function | Description |
|--------|------|----------|-------------|
| `POST` | `/admin/digest/trigger` | `digest_trigger` | Cron job endpoint, authenticated via `DIGEST_CRON_SECRET` env var (header `X-Cron-Secret` or query `?secret=`) |
| `POST` | `/admin/digest/send` | `send_approval_digest` | Super admin manual trigger for testing |

### Backend
- **`app.py`** (imports): Added `DigestLog` to models import.
- **`app.py`** (`_run_approval_digest()` helper): Core digest logic:
  1. Gets cutoff from last `DigestLog.sent_at` (or 1 hour ago)
  2. Queries `pending_valuation` items created after cutoff
  3. Builds category breakdown (top 8 by count, "+ X more" overflow)
  4. Sends email to admins/super_admins where `unsubscribed=False`
  5. Per-admin error handling (one failure doesn't abort batch)
  6. Inserts `DigestLog` record
- Email uses `wrap_email_template()` via `send_email()`. Subject: `"X items waiting for approval — Campus Swap"`. Amber CTA button links to `/admin/approve`.

### Environment Variables
- `DIGEST_CRON_SECRET` — required on Render for cron job authentication.

---

## Bug Fixes & Infrastructure

### PostHog Local Fix
- **`app.py`** (~line 278): Added `posthog.api_key = 'disabled'` when no API key is set. Prevents `ValueError: API key is required` on `posthog.capture()` calls locally. The `posthog.disabled = True` flag prevents actual API calls.

### Database Reset & Seeding
- **`reset_db.py`**: Ran to recreate all tables from current models (including `seller_alert`, `digest_log`, new User columns).
- **`seed_categories.py`**: Rebuilt with `--items` flag support. Seeds 8 parent categories, 41 subcategories, and 42 dummy items (one per subcategory) with realistic descriptions/prices and rotating statuses. Idempotent.
- **`reset_categories.py`**: Simplified to wipe + re-seed using shared `seed_categories.seed()` function. Supports `--items`.

### Dashboard Modal Fixes
- **`templates/dashboard.html`** (line 366): Added `'needs_info'` to allowed statuses for modal edit button.
- **`templates/dashboard.html`** (line 380): Added `needs_info` status badge ("Action Needed" in amber) to modal badge display.

### Video Keywords Deduplication
- Replaced hardcoded JS arrays in `onboard.html` and `add_item.html` with `{{ video_required_keywords | tojson }}`, sourced from single `VIDEO_REQUIRED_CATEGORIES` constant via context processor.

---

## Complete New Routes Summary

| Method | Path | Function | Feature |
|--------|------|----------|---------|
| `POST` | `/admin/item/<id>/request_info` | `admin_request_info` | Item Action Requests |
| `POST` | `/admin/item/<id>/cancel_request` | `admin_cancel_info_request` | Item Action Requests |
| `POST` | `/item/<id>/resubmit` | `resubmit_item` | Item Action Requests |
| `GET` | `/admin/seller/<user_id>/panel` | `admin_seller_panel` | Seller Profile Panel |
| `POST` | `/admin/seller/<user_id>/send_alert` | `admin_send_seller_alert` | Seller Profile Panel |
| `POST` | `/admin/pickup-nudge/send` | `admin_send_pickup_nudge` | Pickup Nudge |
| `POST` | `/admin/digest/trigger` | `digest_trigger` | Approval Digest |
| `POST` | `/admin/digest/send` | `send_approval_digest` | Approval Digest |

## Complete New/Modified Models Summary

| Model | Type | Fields | Migration |
|-------|------|--------|-----------|
| `User` | Modified | +`pickup_time_preference` (String(20), nullable), +`moveout_date` (Date, nullable) | `b5c46df7b729` |
| `SellerAlert` | New | id, item_id, user_id, created_by_id, alert_type, reasons, custom_note, resolved, resolved_at, created_at | `11e979ce55c8` |
| `DigestLog` | New | id, sent_at, item_count, recipient_count | `bf6f8e209739` |

## Complete Template Changes Summary

| Template | Features Touching It |
|----------|---------------------|
| `templates/index.html` | Fix 3 (min value notice) |
| `templates/onboard.html` | Video Requirements |
| `templates/add_item.html` | Video Requirements |
| `templates/edit_item.html` | Video Requirements, Item Action Requests (banner + resubmit button) |
| `templates/admin_approve.html` | Video Requirements, Item Action Requests, Seller Profile Panel |
| `templates/admin.html` | Admin Quick Fixes, Item Action Requests, Seller Profile Panel, Pickup Nudge |
| `templates/dashboard.html` | Pickup Week Updates, Item Action Requests, Seller Profile Panel, Pickup Nudge |
| `templates/confirm_pickup.html` | Pickup Week Updates |
| `templates/upgrade_pickup.html` | Pickup Week Updates |
| `templates/account_settings.html` | Pickup Week Updates |
| `templates/inventory.html` | (verified no change needed) |
| `templates/admin_seller_panel.html` | **New** — Seller Profile Panel |

## Constants Defined/Modified (`constants.py`)

| Constant | Change |
|----------|--------|
| `VIDEO_REQUIRED_CATEGORIES` | Expanded from 6 to 15 keywords |
| `category_requires_video()` | Added optional `subcategory_name` param |
| `PICKUP_WEEKS` | Updated date ranges: April 27–May 3, May 4–May 10 |
| `PICKUP_WEEK_DATE_RANGES` | **New** — date range strings for validation |
| `PICKUP_TIME_OPTIONS` | **New** — `['morning', 'afternoon', 'evening']` |

## CSS Changes (`static/style.css`)

| Addition | Purpose |
|----------|---------|
| `.seller-panel`, `.seller-panel--open/--closed` | Slide-out drawer container |
| `.seller-panel__overlay` | Semi-transparent backdrop |
| `.seller-panel__drawer` | 480px right-side panel |
| `.seller-panel__close` | Close button |
| `.seller-panel-trigger` | Clickable seller name link style |
