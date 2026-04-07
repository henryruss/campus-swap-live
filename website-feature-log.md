# Campus Swap — Website Feature Log

> **Purpose:** Complete audit of every page, form, data flow, and feature on usecampusswap.com. Use this to identify metrics gaps, suggest features, and understand the full product without reading code.
>
> **Last updated:** 2026-04-06

---

## Table of Contents
1. [Global Layout & Navigation](#global-layout--navigation)
2. [Buyer Experience](#buyer-experience)
3. [Seller Experience](#seller-experience)
4. [Account Management](#account-management)
5. [Admin Features](#admin-features)
6. [Crew Portal (Worker Accounts)](#crew-portal-worker-accounts)
7. [Support & Contact](#support--contact)
8. [Auth Flows](#auth-flows)
9. [Emails Sent](#emails-sent)
10. [Analytics & Tracking](#analytics--tracking)
11. [Payments & Stripe Integration](#payments--stripe-integration)
12. [Data Collected Summary](#data-collected-summary)
13. [Item Lifecycle & Status Transitions](#item-lifecycle--status-transitions)
14. [Seller Activation Flows](#seller-activation-flows)
15. [Configuration & Constants](#configuration--constants)
16. [SEO & Structured Data](#seo--structured-data)
17. [Static / Legal Pages](#static--legal-pages)
18. [API Endpoints](#api-endpoints)
19. [Infrastructure & Error Handling](#infrastructure--error-handling)

---

## Global Layout & Navigation

**Base template:** `layout.html` — all pages extend this.

### Header (Desktop)
- Logo (SVG, links to `/`)
- "About Us" link
- Store selector dropdown (currently only "UNC Chapel Hill") — stores selection in `sessionStorage`, redirects to `/inventory?store=` on change
- "Become a Seller" link
- "Shop The Drop" link
- **Logged in:** Dashboard link, user icon dropdown (Admin Panel if admin, Dashboard if not, Account Settings, Logout)
- **Logged out:** Sign In icon

### Header (Mobile)
- Logo + hamburger menu
- Slide-in menu with: About Us, Become a Seller, Shop The Drop, store selector, and auth-conditional items (Dashboard, Account Settings, Admin Panel, Logout / Sign In)

### Footer
- Links: Shop, Become a Seller, About Us, FAQ, Login, Privacy Policy, Terms & Conditions, Refund Policy, Contact Us
- Store location placeholder
- Copyright 2026

### Global JavaScript Behaviors
- Form submit buttons auto-disable with spinner animation (10s timeout to re-enable)
- Flash messages auto-dismiss after 5 seconds with fade-out
- Click-outside-to-close for all dropdowns

### Flash Message System
- Success: green background, checkmark icon
- Error: red background, exclamation icon
- Auto-fade after 5 seconds

---

## Buyer Experience

### Homepage (`/`)
**What buyers see:**
- Hero: "Move Out. Cash In." tagline + announcement banner ("Doors open June 1st")
- Animated ticker of sample items with prices (Mini-fridge $55, Rug $40, Microwave $25, etc.)
- "What We Offer" carousel of product category images
- 3 value proposition cards
- 3 student testimonials (name, college, year, quote, headshot)
- CTA sections: "Start Selling" and "Shop Great Deals"
- Minimum item value notice: "$50 minimum" callout near the seller CTA (cream background, muted text, informational tone)

**Form fields collected:**
- Email address (for account creation or waitlist)
- Cloudflare Turnstile captcha
- Google OAuth option

**What happens on submit:**
- If pickup period active + user exists with password → redirect to login
- If pickup period active + user exists without password → auto-login
- If pickup period active + new user → create account, auto-login
- If pickup period closed → create guest account, show "period ended" message
- Source tracking via `?src=` query parameter stored in session → saved to `user.referral_source`

---

### Shop Front (`/inventory`)
**What buyers see:**
- Store indicator: "Showing items from [STORE NAME]"
- Banner with opening date if store not yet open
- Category cards grid (from `_category_grid.html` partial) with "View All" option
- Subcategory filter pills (dynamic, appear when category selected — fetched via AJAX from `/api/subcategories/<parent_id>`)
- Search box (searches `description` + `long_description`)
- Item count: "(X items total)"
- Product card grid showing: thumbnail, video badge (camera icon), price, status badge (Available/Reserved/SOLD), description
- Pagination controls (24 items per page)

**Filters available:** Category, subcategory, search text

**Sort order:** Available items first, then newest first

**Data NOT shown to buyers:** Seller info, suggested price, quality score number, collection method, pickup logistics

---

### Product Detail (`/item/<id>`)
**What buyers see:**
- Photo gallery with main image + thumbnails + lightbox zoom
- Video player (if uploaded)
- Item ID badge (#123)
- Status badge (Available / Reserved / Sold)
- Item title and long description
- Price (large, prominent)
- Condition label + quality rating (Like New / Good / Fair) — mapped from integer: 5=Like New, 4=Good, 3=Fair
- Delivery method: "In-Store Pickup" (no shipping)
- Share button with card preview + copy link (generates OG share card image via `/share/item/<id>/card.png`)

**Action buttons (conditional):**
| Condition | Button Shown |
|---|---|
| Item sold | Disabled "Item Sold" button |
| Store not open yet | "Reservations open [DATE]" |
| Already reserved by this user | "Cancel Reservation" |
| Reserved by someone else | "Reserved" badge (no action) |
| Reserve-only mode ON | "Reserve Item" |
| Item physically in store | "Buy Now" (Stripe checkout) |
| Item approved but not in store | "Reserve Item" |

**Data NOT shown to buyers:** Seller name/contact, pickup logistics, admin notes, suggested price vs. final price, collection method

**OG Meta Tags:** Product pages inject item-specific OpenGraph and Twitter Card meta tags in `layout.html` for social sharing (title, description, price, share card image).

---

### Post-Purchase (`/item_success`)
**What buyers see:**
- Success confirmation with item thumbnail and description
- Next steps:
  1. Check email for receipt and pickup instructions
  2. Visit Campus Swap Warehouse during store hours
  3. Show email receipt to claim item
- "Back to Shop" button

---

### Post-Reservation (`/reserve_success`)
**What buyers see:**
- "Item Reserved!" confirmation with item thumbnail, description, price
- Info box explaining reservation is non-binding and has an expiry
- "Back to Shop" button

---

## Seller Experience

### Seller Landing Page (`/become-a-seller`)
**What sellers see:**
- Interactive dorm room calculator: click items → receipt builds → shows total earnings
  - Item values: Mini-fridge $55, Rug $40, Microwave $25, Headboard $40, Mattress $80, Couch $70, AC Unit $50, TV $90
- How It Works timeline (5 steps): Sign Up → Items Approved → Secure Spot → Pickup → Get Paid
- Plan comparison side-by-side:
  - **Free Plan:** 20% of sale price, $0 fee, no guaranteed pickup, max 3 items
  - **Pro Plan:** 50% of sale price, $15 one-time fee, guaranteed pickup, unlimited items
- 6-item FAQ accordion (anchor target: `/become-a-seller#faq`)
- CTAs: "Start Selling", "Get Started" (Pro), "Start Free"

**No form fields on this page** — all CTAs link to `/onboard`

---

### Seller Onboarding (`/onboard`) — 9-11 Step Wizard

**Step 1: Category Selection**
- Fields: `category_id`, `selected_subcategory_id`
- UI: Visual category cards + optional subcategory selection (subcategories load via AJAX)

**Step 2: Condition**
- Fields: `quality` (3=Fair, 4=Good, 5=Like New)
- UI: Radio buttons with descriptions

**Step 3: Photos & Video**
- Fields: `photos` (multiple images), `video` (optional or required depending on category)
- Features: Add, remove, crop (via Cropper.js), reorder, set cover photo
- QR code phone upload flow: generates session token → shows QR code → phone visits `/upload_from_phone?token=...` → uploads photos → desktop polls `/api/upload_session/status` for new images
- Formats: JPEG, PNG, WebP for photos (max 10MB each); MP4, MOV, WebM for video (max 50MB, 30s)
- **Video required for categories:** TV, Television, Gaming, Console, Printer, Electronic, Mini Fridge, Fridge, Microwave, Heater, AC, Air Conditioner, Blender, Scooter, Air Fryer
- Video required banner shown when category matches (amber left-border callout)
- Backend enforcement: submission rejected without video for required categories

**Step 4: Item Title**
- Fields: `description` (max 200 chars)

**Step 5: Long Description**
- Fields: `long_description` (textarea, max 2000 chars)

**Step 6: Suggested Price**
- Fields: `suggested_price` (decimal, $0.01–$10,000)
- Note shown: "This is just a recommendation. We review each item..."
- Recommended price ranges shown based on category (e.g., Couch $50-150, Mini Fridge $40-80)

**Step 7: Pickup Week (Optional)**
- Fields: `onboard_pickup_week` ("week1" | "week2"), `onboard_time_preference` ("morning" | "afternoon" | "evening")
- UI: Two large radio cards (Week 1: Apr 27–May 3, Week 2: May 4–May 10) + time-of-day radio buttons (shown after week selected)
- Validation: if week selected, time preference is required. Both null = skip.
- "Skip for now" button same visual weight as Back — clears any selection and advances. Helper text: "You can set or change this anytime from your dashboard."
- Saves to `User.pickup_week` and `User.pickup_time_preference` on submit
- **Service tier selection removed from onboarding** — all sellers start Free. `collection_method` is hardcoded to `'free'` on item creation.

**Step 8: Payout Method**
- Fields: `payout_method` (Venmo/PayPal/Zelle), `payout_handle`, `payout_handle_confirm`
- Dynamic UI: prefix and placeholder change per method
  - Venmo: @username
  - PayPal: email
  - Zelle: email or phone

**Step 9: Review & Submit**
- Display-only summary of all entered data
- Action: "Submit for Approval"

**Steps 10-11 (Guests Only): Account Creation**
- Fields: `full_name`, `email`, `phone` (required), `password` (min 6 chars)
- Google OAuth option, Cloudflare Turnstile captcha
- Guest save progress: POST to `/onboard/guest/save` stores session data (includes pickup_week/time_pref if set)

**Post-onboard routes:**
- `/onboard_complete` — redirect destination on success
- `/onboard_cancel` — cancel button destination
- `/onboard/complete_account` — separate page for completing account setup after onboarding

---

### Add Additional Item (`/add_item`) — 7 Steps
Same as onboarding steps 1-6 + review, minus tier selection, payout, and account creation. Uses seller's existing preferences. Only available to users who are already sellers.

---

### Edit Item (`/edit_item/<id>`)
**Fields:**
- `description` (title), `category_id`, subcategory, `quality` (dropdown), `long_description`
- `price` — editable for drafts (`pending_valuation`), read-only after admin approval
- Photo management: view existing, delete individual (DELETE `/delete_photo/<id>`), add new
- Video management: view, replace, remove
- "Remove from Campus Swap" option (if not yet picked up) with confirmation modal

**Price change acknowledgment:** If admin changed the price from seller's suggested price, a badge appears until seller clicks acknowledge (POST `/api/item/<id>/acknowledge_price_change`).

**"Needs Info" feedback flow:** When item status is `needs_info`:
- Feedback banner at top shows admin's reasons and custom note (from SellerAlert)
- "Resubmit for Review" button at bottom (POSTs to `/item/<id>/resubmit`) — returns item to `pending_valuation` and resolves the alert
- Soft video reminder banner shown for video-required categories without video (no hard block)

---

### Seller Dashboard (`/dashboard`) — "Seller Studio"

**Nag Banners (above stats bar):**
- **Phone nag** (amber): shown if `current_user.phone is None`. Inline phone input + Save button, POSTs to `/update_account_info`. Not dismissible without saving.
- **Address nag** (grey): shown if no pickup location AND phone is set. "Add your pickup address..." link → `/account_settings`. Secondary priority.

**Alert Banners (action cards area):**
- Unresolved `SellerAlert` records rendered as amber cards
- `needs_info` alerts: lists admin's reasons + custom note, "Update Item" button → `/edit_item/<id>`
- `pickup_reminder` alerts: "Action needed: Please select your pickup week" + button → opens pickup week modal (not `/confirm_pickup` anymore)
- `preset` / `custom` alerts: from admin seller profile panel, message content shown directly

**Stats bar (4 columns):**
1. **Potential Earnings** — dollar amount based on approved items × payout percentage, or "—" with "Updates once items are approved"
2. **Paid Out** — amount already sent via payout
3. **Items** — "X live, Y sold" + pending count in orange
4. **Pickup Window** — uses `User.pickup_week` (not item pickup_week). Shows "Wk 1 · Morning" format when both set; "Not scheduled" in amber with "Set now →" if neither. Entire cell is clickable → opens pickup week modal.

**Plan badge:** Free Plan (grey) or Pro Plan (green) — driven by `user_collection_method`.

**Upgrade card** (shown for free-plan sellers): "You're on the free plan — keeping 20% of each sale. Upgrade for guaranteed pickup and 50% payout. $15 one-time fee. [Upgrade →]" — links to `/upgrade_pickup`.

**Pickup Week Modal** (centered overlay, no page navigation):
- Triggered by clicking pickup stats cell or "Set now →" link
- Week 1 / Week 2 cards (pre-filled if already set)
- Time preference buttons (Morning/Afternoon/Evening)
- Save: POSTs to `/api/user/set_pickup_week` via fetch, updates stats bar inline on success, reloads page
- Plan note at bottom: upgrade prompt (free) or "You're on the Pro plan ✓"

**Action cards (conditional):**
| Condition | Card Shown |
|---|---|
| Payment awaiting | Orange card + link to pay $15 → `/confirm_pickup` (now redirects to dashboard) |
| Free plan, items approved | "Set Pickup Week" button → opens modal |
| Free plan, no approved items | "Awaiting approval" |
| **Upgrade card** (always shown for free plan + Stripe configured) | "Upgrade to Pro" card → `/upgrade_pickup` |
| Guest mode | "Save Your Progress" with inline password input (POST `/set_password`) |
| Free tier rejected | Rejection message + upgrade option |

**Item grid — "My Shop":**
Each item tile shows:
- Thumbnail (100x100)
- Price badge (top-right)
- Title (2 lines max)
- Item type: Standard or Oversized
- Status checklist with icons:
  - Pending approval / Approved
  - Pickup confirmed / Pickup fee paid
  - Oversize fee status (if applicable)
  - Picked up / Dropped off
  - Arrived at store
- Color-coded background: Red (rejected), Green (sold/complete), Yellow (in process), Amber (needs_info / action needed)
- Price change badge (if admin adjusted price, until acknowledged)

**Actions:** "Add Another Item" button, item tiles link to edit, upgrade buttons

---

### Confirm Pickup (`/confirm_pickup`) — DEPRECATED
**Superseded by dashboard pickup week modal (April 2026).** Route now immediately redirects to `/dashboard` with flash: "You can set your pickup week from your dashboard."

- Template (`confirm_pickup.html`) and legacy code are preserved but unreachable.
- Address collection moved to `/account_settings` only.
- Phone collection moved to account creation and phone nag banner.
- Pickup week now set via `/api/user/set_pickup_week` AJAX endpoint from dashboard modal.

---

### Upgrade Pickup (`/upgrade_pickup`)
For Free-tier sellers upgrading to Pro.
- Pickup week selection (radio): Week 1 (April 27 – May 3), Week 2 (May 4 – May 10)
- Time-of-day preference (radio, required): Morning / Afternoon / Evening
- Move-out date (date picker, optional)
- Fee: $15 one-time
- Action: "Pay $15 & Upgrade to Pickup"
- Success page: `/upgrade_pickup_success`

### Add Payment Method (`/add_payment_method`)
- Stripe Elements card form (SetupIntent flow — card saved for deferred charge)
- Messaging: "You won't be charged until pickup week. One-time $15 pickup fee covers all your items."
- Success page: `/payment_method_success`

---

## Account Management

### Account Settings (`/account_settings`)

**Card 1: Change Password**
- `current_password` (optional if user has no existing password — e.g., OAuth or guest accounts)
- `new_password`, `confirm_password`
- POST to `/change_password`

**Card 2: Account Info**
- `full_name`, `phone`
- `email` (read-only, displayed but cannot be changed)
- POST to `/update_account_info`

**Card 3: Pickup Location**
- Same dorm/address form as confirm_pickup (on_campus: dorm dropdown + room; off_campus: Google Maps autocomplete + lat/lng + note)
- POST to `/update_profile`

**Card 4: Pickup Preferences** (only shown if seller has items with pickup week set)
- Pickup week (read-only display)
- `pickup_time_preference` (dropdown: Morning/Afternoon/Evening, editable)
- `moveout_date` (date picker, editable, constrained to pickup week range)
- POST to `/update_account_info`

**Card 5: Payout Info** (only shown if payout method previously set)
- `payout_method` (dropdown: Venmo/PayPal/Zelle), `payout_handle`, `payout_handle_confirm`
- POST to `/update_payout`

---

## Admin Features

### Role Hierarchy
- **Super Admin:** Full access — user management, database reset, mass email, category management, approvals, exports
- **Admin (Helper):** Approvals, item management, free-tier selection, quick add
- **Pre-approved via `AdminEmail` table** — role assigned automatically at signup when email matches

### Admin Dashboard (`/admin`)

**Overview Stats:**
- Total users, total items, sold items, pending items, available items
- Pickup Period toggle (OPEN/CLOSED) — sets `AppSetting('pickup_period_active')`
- Store open date (editable) — sets `AppSetting('store_open_date')`
- Reserve-only mode toggle — sets `AppSetting('reserve_only_mode')`

**Item Lifecycle Table:**
- Filterable by: category, seller email, item title
- Columns: Item thumbnail, subcategory, seller (clickable → profile panel), picked up (timestamp), at store (timestamp), status, reservation info, payout status, actions
- Status badges include: `needs_info` → "Awaiting Seller" (amber)
- Per-item actions: mark sold, mark payout sent, edit, delete, undo mark-sold, "Cancel Request" (for needs_info items → returns to pending_valuation)
- Bulk actions available
- Seller names are clickable → opens slide-out seller profile panel

**Free Tier Management:**
- Warehouse capacity counter (color-coded: green/yellow/red vs. 2000 limit)
- Ranked list of free-tier sellers by total approved item value
- Per user: name, email, item count + prices, total value, status badge
- Actions: Confirm (grants pickup), Reject (sends upgrade notice), Bulk notify all unconfirmed

**Pickup Nudge Section (collapsible, collapsed by default):**
- Header: "Pickup Week Not Selected (X sellers)" — amber badge if X > 0
- Table: checkbox, seller name (panel trigger), email, phone, tier badge (Free/Pro), approved item count, days since approval (color-coded: >7d red, >3d amber), last nudged date
- "Remind All" button: sends pickup_reminder SellerAlert to all eligible sellers (re-queries at send time, deduplicates)
- "Remind Selected" button: sends to checked sellers only
- Select/deselect all checkbox
- AJAX updates: "Last nudged" column updates inline on send success
- Sellers disappear from list only when they actually select a pickup week

**Seller Profile Panel (slide-out drawer):**
- 480px right-side drawer, opened by clicking seller names anywhere in admin views
- Fetched as HTML partial via GET `/admin/seller/<id>/panel`
- 5 sections:
  1. **Identity:** name, email (mailto), phone, date joined, account type badges
  2. **Seller Status:** service tier, payment status, payout method/handle, referral source
  3. **Pickup Info:** location type, dorm/address, pickup week, time preference, moveout date
  4. **Items:** scrollable list with thumbnails, title, category, price, status badges, "View" links
  5. **Send Alert:** radio toggle (preset/custom), preset dropdown (5 options), item selector, custom textarea (500 chars), inline success/error
- Close: X button, Escape key, overlay click

**Quick Add Item (Admin Helper):**
- For quickly adding items at events
- Fields: category, condition, description, long description, photo, seller name, seller email
- Creates pending item; links to existing user if email matches, creates new user if not

### Item Approval Queue (`/admin/approve`)
- Card grid view or single-item detail view
- Sort by: Price high/low, Date added oldest first
- Per item, admin sets:
  - `price` (final sale price — may differ from seller's `suggested_price`)
  - `category_id` / `subcategory_id`
  - `quality` (condition)
- Approve, Reject, or **"More Info Needed"** (keyboard shortcuts: A=approve, R=reject, I=info needed)
- "More Info Needed" opens modal with: 4 preset reason checkboxes (better photos, video required, better description, different angle) + custom note textarea (500 chars). Sends to `/admin/item/<id>/request_info` → sets item to `needs_info`, creates SellerAlert
- "Resubmitted" badge (blue) shown on items that were previously sent back and resubmitted by seller
- Seller names are clickable → opens slide-out seller profile panel
- Progress counter ("X of Y reviewed")

### Category Management (Super Admin)
- Add/edit/delete top-level categories with FontAwesome icons
- Subcategory management (add/edit/delete under parent categories)
- Essentials stock counts (Couch, Mattress, Mini-Fridge, Climate Control, TV) — `count_in_stock` field
- Bulk update stock counts

### User & Data Management (Super Admin)
- **Grant/revoke admin access** by email (POST `/admin/user/make-admin`, `/admin/user/revoke-admin`)
- **Delete user** + all their items (POST `/admin/user/delete/<id>`)
- **Data preview** (view before download): Users, Items, Sales (GET `/admin/preview/users|items|sales` → renders `data_preview.html`)
- **Data export** (CSV download): Users, Items, Sales (GET `/admin/export/users|items|sales`)
  - Users CSV: email, full_name, phone, payout_method, items_count, total_items_value, pickup_time_preference, moveout_date
  - Items CSV: item_id, subcategory, seller, price, picked_up, at_store, status
  - Sales CSV: item_id, seller, price, payout_percentage, payout_amount, payout_sent, sold_at
- **Mass email** (POST `/admin/mass-email`): custom subject + HTML body, sent to all non-unsubscribed users, rate-limited at 0.55s/email
- **Database reset** (POST `/admin/database/reset`): Super admin only, requires typing "reset database" to confirm

---

## Crew Portal (Worker Accounts)

*Spec #1 — signed off 2026-04-06. .edu enforcement currently disabled for development; re-enable before first real hiring cycle.*

### Application (`/crew/apply`)
- Publicly accessible, no login required
- Short job description hero: roles explained (Driver vs. Organizer), $130/shift, ~3-week season
- Form fields: full name, email, phone, UNC year, role preference (Driver/Organizer/Both), 7×2 availability grid, optional blurb (500 char max)
- If logged in: name/email/phone pre-filled and read-only
- On submit: creates `WorkerApplication` + initial `WorkerAvailability` (week_start=NULL), redirects to `/crew/pending`
- Duplicate check: pending → flash error; approved → redirect to `/crew`; rejected → flash "applications closed for this account"

### Availability Grid
- 7-day × AM/PM tap-to-toggle grid (14 cells)
- Default state: all green (fully available)
- Tap to blackout (grey); tap again to restore
- Outputs 14 hidden inputs (`mon_am` … `sun_pm`) read on POST
- Reused on apply form and weekly update page via `crew/_availability_grid.html` partial

### Pending Page (`/crew/pending`)
- Shown after application submit
- On refresh: checks live status — approved redirects to `/crew`, rejected redirects to index with flash

### Worker Dashboard (`/crew`)
- Requires `is_worker=True` and `worker_status='approved'`
- Shows role badge, last availability submission summary
- Placeholder sections for schedule and shift history (Specs #2, #3)

### Weekly Availability Update (`/crew/availability`)
- Available Sunday–Tuesday only; locked Wed–Sat with "schedule posts Thursday" message
- Grid pre-filled from most recent `WorkerAvailability` record
- Submit upserts by `(user_id, week_start)` — no duplicates

### Admin Crew Management (within `/admin`)
- "Crew" collapsible section with pending count badge
- Per-applicant expand: shows availability grid (read-only) + role preference + optional blurb
- **Approve:** role selector (Driver/Organizer/Both) → sets `is_worker=True`, `worker_status='approved'`, `worker_role` → sends approval email
- **Reject:** optional rejection email toggle → sets `worker_status='rejected'`

### Emails
- **Approval:** "You're on the Campus Swap Crew!" — role confirmed, $130/shift, link to `/crew`, availability deadline reminder
- **Rejection (optional):** Brief, kind decline — admin toggles on/off per applicant

---

## Support & Contact

### Contact Page (`/contact`)
**What users see:**
- "Get in touch" heading + "We're here to help — usually respond within a few hours."
- **Urgent help callout:** Phone number (919) 578-1764 with "call or text" CTA, "Available during business hours"
- Contact form

**Form fields:**
| Field | Type | Validation | Notes |
|---|---|---|---|
| `name` | text | required, max 100 chars | |
| `email` | email | required, max 254 chars | **Hidden for logged-in users** (auto-filled from account) |
| `subject` | text | required, max 200 chars | |
| `message` | textarea | required, max 5000 chars | |
| `website` | text (hidden) | honeypot — if filled, submission rejected | Anti-spam: hidden from real users via CSS |

**Security:** Cloudflare Turnstile captcha + honeypot field
**Rate limit:** 5 submissions per hour
**On submit:** Email sent to Ben@UseCampusSwap.com, Henry@UseCampusSwap.com, Jack@UseCampusSwap.com
**Success message:** "Message sent — we'll be in touch soon"

---

## Auth Flows

| Flow | Fields Collected | Route | Notes |
|------|-----------------|-------|-------|
| Email Login | email, password | `/login` | Turnstile captcha |
| Email Register | full_name, email, **phone** (required), password | `/register` | Phone required since April 2026. Turnstile captcha. |
| Google OAuth | (from Google: email, profile) | `/auth/google` → `/auth/google/callback` | New accounts redirected to `/complete_profile` to collect phone before proceeding. |
| Complete Profile (post-OAuth) | phone | `/complete_profile` | Required for new Google OAuth accounts. Idempotent — skips if phone already set. Redirects to `session['next_after_profile']`. |
| Homepage Signup | email | `/` (POST) | Creates guest account if new, auto-logs in during active period |
| Guest → Full Account (Dashboard) | password | POST `/set_password` | Inline on dashboard "Save Your Progress" card |
| Guest → Full Account (Onboard) | full_name, email, **phone** (required), password | `/onboard/complete_account` | Phone added to step 11 of onboarding wizard. |
| Password Change | current_password, new_password, confirm_password | POST `/change_password` | current_password optional if no existing hash (OAuth/guest accounts) |

---

## Emails Sent

### Transactional (11 emails)

| # | Trigger | Recipient | Subject | Key Content |
|---|---------|-----------|---------|-------------|
| 1 | User reserves item | Buyer | "You reserved {item} — Campus Swap" | Reservation confirmation, expiry date, item link |
| 2 | Reservation expires | Buyer | "Your reservation for {item} expired" | Expiry notice, item available again, re-reserve link |
| 3 | Item purchased | Seller | "Your Item Has Sold! - Campus Swap" | Item, sale price, payout amount + % (50%/20%), payout method/handle |
| 4 | Admin approves item | Seller | "Your Item Has Been Approved - Campus Swap" | Item details, final price (may differ from suggested), next steps by tier, fee breakdown, dashboard link |
| 5 | Item submitted (onboard/dashboard) | Seller | "Item Submitted - Campus Swap" | Submission confirmation, review timeline, dashboard link |
| 6 | Item submitted (guest signup flow) | Seller | "Item Submitted for Review - Campus Swap" | Submission + activation requirement note |
| 7 | Seller completes payment (webhook) | Seller | "Seller Activation Complete - Campus Swap" | Activation confirmed, pickup week selection info, dashboard link |
| 8 | Admin confirms free-tier pickup | Seller | "You're Confirmed for Pickup — Campus Swap" | Free pickup confirmed, add address + choose week, dashboard link |
| 9 | Admin rejects free-tier pickup | Seller | "Update on Your Free Plan Pickup — Campus Swap" | Capacity full, alternative: upgrade to Pro ($15/50%) |
| 10 | Admin bulk notifies free-tier users | Sellers | "Our Warehouse Is at Capacity — Campus Swap" | Same as #9, sent to all unconfirmed free-tier users |
| 11 | New account created | User | "Welcome to Campus Swap!" | Platform overview, quick start guide, dashboard link |

### Internal (2 types)

| # | Trigger | Recipient | Subject | Key Content |
|---|---------|-----------|---------|-------------|
| 12 | Contact form submitted | Ben@, Henry@, Jack@UseCampusSwap.com | "Contact: {subject}" | Sender name, email, message body |
| 14 | Hourly cron job or manual trigger | All admins/super admins (non-unsubscribed) | "X items waiting for approval — Campus Swap" | New pending items since last digest, category breakdown (top 8), amber CTA → `/admin/approve`. Tracked in `DigestLog` model. Triggered via POST `/admin/digest/trigger` (cron, `DIGEST_CRON_SECRET` auth) or `/admin/digest/send` (super admin manual). |

### Marketing (1 type)

| # | Trigger | Recipient | Subject | Key Content |
|---|---------|-----------|---------|-------------|
| 13 | Super admin sends mass email | All non-unsubscribed users | Custom subject | Custom HTML content, auto-added unsubscribe link, rate-limited at 0.55s/email |

**Email infrastructure:** Resend API, all emails wrapped in branded template (logo + footer), marketing emails include List-Unsubscribe headers, unsubscribed users automatically excluded.

**Unsubscribe flow:** One-click via `/unsubscribe/<token>` (unique per user) → confirmation page → success page noting transactional emails continue.

---

## Analytics & Tracking

### PostHog Events (Backend)
| Event | Trigger | Properties |
|-------|---------|------------|
| `backend_error` | Unhandled exception | error type, traceback |
| `item_sold` | Purchase completes | item_id, category, price |
| `payout_marked_sent` | Admin marks payout | item_id |
| `item_approved` | Admin approves | item_id, category, price |
| `seller_signed_up` | New registration | (user ID only) |
| `seller_upgraded_to_paid` | Seller upgrades to Pro | (user ID only) |
| `item_submitted` | Seller submits item | category, collection_method |

### PostHog (Frontend)
- Loaded on all pages via `layout.html` (if `posthog_api_key` configured)
- `person_profiles: 'identified_only'`
- No custom frontend events configured — relies on autocapture

### Google Analytics
- GA4 tag (G-T696XM5XN9) on all pages via layout.html
- Standard pageview + automatic event tracking only
- No custom GA events configured

### Referral Source Tracking
- `?src=` query parameter on any URL → stored in session → saved to `user.referral_source` at account creation
- Default value: `'direct'`

---

## Payments & Stripe Integration

### Payment Flows

| Flow | Stripe Method | Route | Amount | When |
|------|--------------|-------|--------|------|
| Item purchase (buyer) | Checkout Session | POST `/create_checkout_session` → `/item_success` | Item price | Buyer clicks "Buy Now" |
| Pro seller activation fee | Checkout Session | POST `/upgrade_checkout` or via confirm_pickup | $15 | Onboarding or confirm pickup |
| Pickup upgrade (Free→Pro) | Checkout Session | `/upgrade_pickup` | $15 | Seller upgrades from dashboard |
| Save payment method | SetupIntent | POST `/create_setup_intent` → `/add_payment_method` | $0 (deferred) | Card saved for later charge |

### Webhook (`/webhook`)
Handles:
- `checkout.session.completed` — marks item sold, activates seller
- `setup_intent.succeeded` — saves payment method to user (`stripe_payment_method_id`)
- Updates `has_paid`, `payment_declined` flags accordingly

### Success Pages
| Route | After |
|---|---|
| `/item_success` | Buyer purchases item |
| `/success` | Generic payment success (seller activation, upgrade) — context-specific flash message |
| `/confirm_pickup_success` | Seller confirms pickup week |
| `/upgrade_pickup_success` | Seller upgrades to Pro |
| `/payment_method_success` | Payment method saved |

---

## Data Collected Summary

### From Buyers
- Email, full name, password (or Google OAuth credentials)
- Reservation history: item_id, timestamp, expiry, cancellation
- Purchase history (via Stripe checkout sessions)

### From Sellers (all of the above, plus)
- Phone number
- Pickup location: type (on/off campus), dorm + room OR street address + lat/lng + directions note
- Payout method (Venmo/PayPal/Zelle) + handle
- Service tier choice (Free/Pro)
- Pickup week preference, time-of-day preference, move-out date (optional)
- Per item: category, subcategory, condition (1-5), title, long description, suggested price, photos (multiple), video (optional/required)
- Stripe customer ID + payment method ID (for deferred charges)
- Referral source

### From Admin Actions
- Item approval: final price, category/subcategory, condition
- "More Info Needed" requests: preset reasons + custom note → stored as SellerAlert
- Pickup nudge reminders → stored as SellerAlert
- Custom/preset alerts via seller profile panel → stored as SellerAlert
- Payout sent timestamps
- Free-tier confirm/reject decisions
- User admin role grants/revocations

---

## Item Lifecycle & Status Transitions

```
seller submits item
    ↓
pending_valuation
    ↓ admin approves (sets price, category, oversized flag)
    ↓                                  ↘ admin rejects → item hidden, seller notified
    ↓                                  ↘ admin requests info → needs_info (seller sees alert)
    ↓                                      → seller resubmits → back to pending_valuation
    ↓                                      → admin cancels → back to pending_valuation
pending_logistics
    ↓
    ├─ Pro seller: confirm_pickup → select week → pay $15 → available
    └─ Free seller: admin confirms capacity → available (or rejects → upgrade offered)
                                           ↓
                                       available
                                           ↓ buyer purchases (Stripe)
                                         sold
                                           ↓ admin marks payout sent
                                       payout_sent=True
```

### Operational Milestones (tracked separately, don't affect item status)
- `picked_up_at` — when item was collected from seller
- `arrived_at_store_at` — when item physically arrived at warehouse/store

### Reservations
- **Not a status** — tracked via separate `ItemReservation` model
- Non-binding, has expiry timestamp (`expires_at`)
- One active reservation per item at a time
- Buyer can cancel; reservation can expire automatically
- `expiry_email_sent` tracks whether expiry notification was sent

---

## Seller Activation Flows

### Pro Seller (`collection_method='online'`)
1. Submit item → `pending_valuation`
2. Admin approves → `pending_logistics`, seller emailed with final price
3. Seller goes to `/confirm_pickup` → selects pickup week → enters address/phone
4. Pay $15 via Stripe → `has_paid=True`
5. Webhook confirms → all items become `available`

### Free Tier Seller (`collection_method='free'`)
1. Submit item → `pending_valuation`
2. Admin approves → `pending_logistics`
3. Admin reviews capacity → Confirm or Reject
4. **Confirmed:** seller picks up week + address → items `available`, 20% payout
5. **Rejected:** seller offered alternative to upgrade to Pro ($15/50%)

### Guest Account Flow
- Guests can begin onboarding without an account
- Progress saved via session + `/onboard/guest/save`
- Account created at step 10-11 (or via Google OAuth)
- Guest can also set password later from dashboard (`/set_password`)

---

## Configuration & Constants

### Payout Rates
| Tier | `collection_method` | Payout % | Fee |
|------|-------------------|----------|-----|
| Pro Plan | `online` | 50% | $15 one-time |
| Free Plan | `free` | 20% | $0 |

Both tiers include free pickup. Pro guarantees it; Free is space-permitting.

### Capacity Limits
- Warehouse: 2,000 items

### Fee Structure
- Service fee (Pro): $15 (1500 cents) — covers all items, no per-item charges

### Key Deadlines (Configurable)
- `RESERVE_ONLY_DEADLINE`: April 20 — before this date, items are reserve-only (no Stripe charges); after, "Buy Now" enabled
- Pickup weeks: Week 1 (April 27 – May 3), Week 2 (May 4 – May 10)
- Pickup time options: Morning (9am–1pm), Afternoon (1pm–5pm), Evening (5pm–9pm)
- Video required category keywords (15): tv, television, gaming, console, printer, electronic, mini fridge, fridge, microwave, heater, ac, air conditioner, blender, scooter, air fryer

### File Upload Limits
- Photos: 10MB max, formats: JPG/JPEG/PNG/WebP
- Video: 50MB max, 30 seconds max, formats: MP4/MOV/WebM
- Image quality: 80 (JPEG compression)
- Thumbnails: 300×300

### Input Validation
- Price: $0.01 – $10,000
- Quality: 1–5 integer
- Description: max 200 chars
- Long description: max 2,000 chars
- Email: max 120 chars
- Name: max 100 chars

### Rate Limits
| Route | Limit |
|---|---|
| Login | 5 per minute |
| Register | 3 per hour |
| Admin routes | 100 per minute |
| Email-sending routes | 10 per hour |
| Contact form | 5 per hour |

### Runtime Feature Flags (`AppSetting`)
| Key | Values | Effect |
|-----|--------|--------|
| `reserve_only_mode` | `'true'`/`'false'` | Hides "Buy Now", shows "Reserve" only |
| `pickup_period_active` | `'true'`/`'false'` | Enables pickup scheduling for sellers |
| `current_store` | store name string | Displayed in header + inventory filter |
| `store_open_date` | date string | Shown on inventory banner when store not yet open |

### Recommended Price Ranges (shown during onboarding)
| Category | Min | Max |
|----------|-----|-----|
| Couch/Sofa | $50 | $150 |
| Headboard | $25 | $80 |
| Mattress | $40 | $120 |
| Rug | $20 | $60 |
| TV/Television | $50 | $150 |
| Gaming/Console | $80 | $250 |
| Printer | $15 | $40 |
| Mini Fridge | $40 | $80 |
| Microwave | $15 | $35 |
| Air Fryer | $15 | $40 |
| AC Unit/Heater | $15–30 | $40–80 |
| Fallback (other) | $20 | $100 |

### Residence Halls (UNC Chapel Hill)
Grouped by area for on-campus pickup dropdown:
- **North Campus:** 20 dorms (Alderman, Alexander, Cobb, Connor, Everett, Graham, Grimes, Joyner, Kenan, Lewis, Mangum, Manly, McClinton, McIver, Old East, Old West, Ruffin Jr, Spencer, Stacy, Winston)
- **Mid-Campus:** 4 dorms (Avery, Carmichael, Parker, Teague)
- **South Campus:** 21 dorms (Baity Hill complex ×8, Craige, Craige North, Ehringhaus, Hardin, Hinton James, Horton, Koury, Morrison, Ram Village ×4, Taylor Hall)

---

## SEO & Structured Data

### Meta Tags
- Primary: title, description, keywords
- OpenGraph + Twitter Card: dynamic for product pages (title, description, price, share card image), static for other pages

### Structured Data (JSON-LD)
1. **Organization** — name, URL, logo, search action
2. **LocalBusiness** — store address (dynamic from `get_store_info()`), area served
3. **WebSite** — search action target: `/inventory?search={query}`
4. **BreadcrumbList** — Home → Become a Seller → Shop The Drop → About Us

### Technical SEO
- `/sitemap.xml` — dynamic sitemap (all public routes + product pages)
- `/robots.txt` — robots exclusion file
- Favicon: SVG (`faviconNew.svg`) served as icon, apple-touch-icon, and shortcut icon

---

## Static / Legal Pages

| Page | Route | Notes |
|------|-------|-------|
| About | `/about` | Problem/solution narrative, store address, team info |
| Privacy Policy | `/privacy-policy` | Data collected, third parties (Google, Stripe, Resend, PostHog) |
| Terms & Conditions | `/terms-and-conditions` | |
| Refund Policy | `/refund-policy` | |
| Director | `/director` | Internal ops — "Become a Campus Director" recruiting page, links to jobs@campusswap.com |
| Unsubscribe Confirm | `/unsubscribe/<token>` | One-click marketing unsubscribe, unique token per user |
| Unsubscribe Success | (after confirm) | Confirms unsubscribe, notes transactional emails continue |

---

## API Endpoints

| Method | Route | Purpose | Auth |
|--------|-------|---------|------|
| GET | `/api/subcategories/<parent_id>` | Returns subcategories as JSON for AJAX category dropdowns | None |
| POST | `/api/item/<id>/acknowledge_price_change` | Seller dismisses price-change badge | Login required |
| POST | `/api/upload_session/create` | Create QR session token for phone photo upload | Login required |
| GET | `/api/upload_session/status` | Poll for new photos uploaded from phone | Login required |
| GET/POST | `/upload_from_phone` | Mobile upload page (accessed via QR code) | Token-based |
| POST | `/upload_video_from_phone` | Video upload from phone | Token-based |

### User API Routes (added April 2026)

| Method | Route | Purpose | Auth |
|--------|-------|---------|------|
| POST | `/api/user/set_pickup_week` | Save `User.pickup_week` + `pickup_time_preference` from dashboard modal. Returns JSON `{success, pickup_week, pickup_week_label, pickup_time_preference}`. | Login required |

### Admin API Routes (added April 2026)

| Method | Route | Purpose | Auth |
|--------|-------|---------|------|
| POST | `/admin/item/<id>/request_info` | "More Info Needed" — creates SellerAlert, sets item to needs_info | Admin |
| POST | `/admin/item/<id>/cancel_request` | Cancel info request, return item to pending_valuation | Admin |
| POST | `/item/<id>/resubmit` | Seller resubmits item after addressing feedback | Login (item owner) |
| GET | `/admin/seller/<user_id>/panel` | HTML partial for seller profile slide-out panel | Admin |
| POST | `/admin/seller/<user_id>/send_alert` | Create SellerAlert from profile panel | Admin |
| POST | `/admin/pickup-nudge/send` | Send pickup reminder alerts | Admin |
| POST | `/admin/digest/trigger` | Cron endpoint for approval digest email | Token (`DIGEST_CRON_SECRET`) |
| POST | `/admin/digest/send` | Manual trigger for approval digest | Super admin |

### QR Code Phone Upload Flow
1. Desktop: POST `/api/upload_session/create` → gets `session_token`
2. Desktop: generates QR code pointing to `/upload_from_phone?token=<session_token>`
3. Phone: opens QR link → uploads photos/video
4. Desktop: polls `/api/upload_session/status` → sees new `TempUpload` entries → displays them
5. Photos stored as `TempUpload` records until onboarding/add_item form submitted

---

## Infrastructure & Error Handling

### Error Pages (`/error`)
- **404:** Search icon + "Error 404" + "Go Home" + "Browse Items" buttons
- **500:** Warning icon + "Error 500" + same buttons
- **413:** Payload too large (file upload exceeds limit)

### Health Check (`/health`)
- JSON response: `status` (healthy/unhealthy), `database` (connected), `stripe` (configured), `resend` (configured), `timestamp`
- Used by Render for monitoring/load balancer

### File Serving
- `/uploads/<filename>` — serves uploaded files from `/var/data/` (production) or `static/uploads/` (local)

### Share Card Image (`/share/item/<id>/card.png`)
- Dynamically generates PNG share card via PIL/Pillow
- Card includes: item photo, title, price, condition, quality rating
- Used as OG image for social sharing
