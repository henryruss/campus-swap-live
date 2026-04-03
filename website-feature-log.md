# Campus Swap — Website Feature Log

> **Purpose:** User-facing audit of what the site currently does. Every page, every form field, every email, every data point displayed. Use this to audit metrics gaps and suggest features.
>
> **Last updated:** 2026-04-02

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

**Form fields collected:**
- Email address (for account creation or waitlist)
- Cloudflare Turnstile captcha
- Google OAuth option

**What happens on submit:**
- If pickup period active + user exists with password → redirect to login
- If pickup period active + user exists without password → auto-login
- If pickup period active + new user → create account, auto-login
- If pickup period closed → create guest account, show "period ended" message
- Source tracking via query parameter stored in session

---

### Shop Front (`/inventory`)
**What buyers see:**
- Store indicator: "Showing items from [STORE NAME]"
- Banner with opening date if store not yet open
- Category cards grid with "View All" option
- Subcategory filter pills (dynamic, appear when category selected)
- Search box
- Item count: "(X items total)"
- Product card grid showing: thumbnail, video badge, price, status badge (Available/Reserved/SOLD), description
- Pagination controls

**Filters available:** Category, subcategory, search (searches description + long_description)

**Sort order:** Available items first, then newest first

**Data NOT shown to buyers:** Seller info, suggested price, quality score number, collection method

---

### Product Detail (`/item/<id>`)
**What buyers see:**
- Photo gallery with main image + thumbnails + lightbox zoom
- Video (if uploaded)
- Item ID badge (#123)
- Status badge (Available / Reserved / Sold)
- Item title and long description
- Price (large, prominent)
- Condition label + quality rating (Like New / Good / Fair)
- Delivery method: "In-Store Pickup" (no shipping)
- Share button with card preview + copy link

**Action buttons (conditional):**
- Item sold → disabled "Item Sold" button
- Store not open → "Reservations open [DATE]"
- Already reserved by this user → "Cancel Reservation" button
- Reserved by someone else → "Reserved" badge (no action)
- Reserve-only mode → "Reserve Item"
- Item in store → "Buy Now"
- Item not yet in store → "Reserve Item"

**Data NOT shown to buyers:** Seller name/contact, pickup logistics, admin notes, suggested price vs. final price

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
- Info box explaining reservation is non-binding
- "Back to Shop" button

---

## Seller Experience

### Seller Landing Page (`/become-a-seller`)
**What sellers see:**
- Interactive dorm room calculator: click items → receipt builds → shows total earnings
- Item values used: Mini-fridge $55, Rug $40, Microwave $25, Headboard $40, Mattress $80, Couch $70, AC Unit $50, TV $90
- How It Works timeline (5 steps): Sign Up → Items Approved → Secure Spot → Pickup → Get Paid
- Plan comparison side-by-side:
  - **Free Plan:** 20% of sale price, $0 fee, no guaranteed pickup, max 3 items
  - **Pro Plan:** 50% of sale price, $15 one-time fee, guaranteed pickup, unlimited items
- 6-item FAQ accordion
- CTAs: "Start Selling", "Get Started" (Pro), "Start Free"

**No form fields on this page** — all CTAs link to `/onboard`

---

### Seller Onboarding (`/onboard`) — 9-11 Step Wizard

**Step 1: Category Selection**
- Fields: `category_id`, `selected_subcategory_id`
- UI: Visual category cards + optional subcategory selection

**Step 2: Condition**
- Fields: `quality` (3=Fair, 4=Good, 5=Like New)
- UI: Radio buttons with descriptions

**Step 3: Photos & Video**
- Fields: `photos` (multiple images), `video` (optional, max 30s/50MB)
- Features: Add, remove, crop, reorder, set cover photo, QR code phone upload flow
- Formats: JPEG, PNG, WebP for photos; MP4, MOV, WebM for video

**Step 4: Item Title**
- Fields: `description` (max 200 chars)

**Step 5: Long Description**
- Fields: `long_description` (textarea)

**Step 6: Suggested Price**
- Fields: `suggested_price` (decimal)
- Note shown: "This is just a recommendation. We review each item..."

**Step 7: Service Tier**
- Fields: `collection_method` ("online" for Pro, "free" for Free)
- UI: Two tier cards with pricing breakdown

**Step 8: Payout Method**
- Fields: `payout_method` (Venmo/PayPal/Zelle), `payout_handle`, `payout_handle_confirm`
- Dynamic UI: prefix and placeholder change per method (@username for Venmo, email for PayPal, email/phone for Zelle)

**Step 9: Review & Submit**
- Display-only summary of all entered data
- Action: "Submit for Approval"

**Steps 10-11 (Guests Only): Account Creation**
- Fields: `full_name`, `email`, `password` (min 6 chars)
- Google OAuth option, Cloudflare Turnstile captcha

---

### Add Additional Item (`/add_item`) — 7 Steps
Same as onboarding steps 1-6 + review, minus tier selection, payout, and account creation. Uses seller's existing preferences.

---

### Edit Item (`/edit_item/<id>`)
**Fields:**
- `description` (title), `category_id`, subcategory, `quality` (dropdown), `long_description`
- `price` — editable for drafts, read-only after admin approval
- Photo management: view existing, delete individual, add new
- Video management: view, replace, remove
- "Remove from Campus Swap" option (if not yet picked up) with confirmation modal

---

### Seller Dashboard (`/dashboard`) — "Seller Studio"

**Stats bar (4 columns):**
1. **Potential Earnings** — dollar amount or "—" with "Updates once items are approved"
2. **Paid Out** — amount already sent
3. **Items** — "X live, Y sold" + pending count in orange
4. **Pickup Window** — varies by plan status (week selected, pod location, or "pending")

**Plan badge:** Free Plan / Drop-off / Awaiting Payment / Pro User

**Action cards (conditional):**
- Awaiting Payment: orange card + link to pay $15
- Free Plan: reminder card + upgrade option
- Guest Mode: "Save Your Progress" with password input
- Free Tier Status: awaiting confirmation / approved / rejected messaging

**Item grid — "My Shop":**
Each item tile shows:
- Thumbnail (100x100)
- Price badge (top-right)
- Title (2 lines)
- Item type: Standard or Oversized
- Status checklist with icons:
  - Pending approval / Approved
  - Pod selected / Pickup confirmed / Pickup fee paid
  - Oversize fee status (if applicable)
  - Picked up / Dropped off
- Color-coded background: Red (rejected), Green (sold/complete), Yellow (in process)

**Actions:** "Add Another Item", item tiles link to edit, pod selection dropdown, upgrade buttons

---

### Confirm Pickup (`/confirm_pickup`) — 2-3 Step Wizard

**Step 1: Pickup Week**
- Fields: `pickup_week` (radio buttons with date ranges)
- Cannot be changed after confirmation

**Step 2: Address & Phone** (skipped if location already saved)
- `pickup_location_type`: on_campus or off_campus
- On-campus: `pickup_dorm` (dropdown by area), `pickup_room`
- Off-campus: `pickup_address` (Google Maps autocomplete), `pickup_lat`/`pickup_lng` (hidden), `pickup_note` (optional directions)
- `phone` (formatted as (XXX) XXX-XXXX) — "So we can text you when we're on the way"

**Step 3: Review & Pay**
- Summary of selections
- Fee display: "$15.00 one-time pickup fee" (Pro) or free (Free plan)
- Action: "Pay $15 & Confirm Pickup" or "Confirm Pickup"

---

### Upgrade Pickup (`/upgrade_pickup`)
- Pickup week selection (radio)
- Fee: $15 one-time
- Action: "Pay $15 & Upgrade to Pickup"

### Pay Oversize Fee (`/pay_oversize_fee/<id>`)
- Item thumbnail + title displayed
- Fee: $10 per additional oversized item
- Action: "Pay $10"

### Add Payment Method (`/add_payment_method`)
- Stripe Elements card form
- Messaging: "You won't be charged until pickup week"
- Fee breakdown: $15 one-time, +$10 per additional oversized

---

### Account Settings (`/account_settings`)
**Card 1: Change Password**
- `current_password` (optional if no existing password), `new_password`, `confirm_password`

**Card 2: Account Info**
- `full_name`, `phone`
- `email` (read-only, cannot be changed)

**Card 3: Pickup Location**
- Same dorm/address form as confirm_pickup

**Card 4: Payout Info** (if payout set)
- `payout_method` (dropdown), `payout_handle`, `payout_handle_confirm`

---

## Emails Sent

### Transactional (11 emails)

| # | Trigger | Recipient | Subject | Key Content |
|---|---------|-----------|---------|-------------|
| 1 | User reserves item | Buyer | "You reserved {item} — Campus Swap" | Reservation confirmation, expiry date, item link |
| 2 | Reservation expires | Buyer | "Your reservation for {item} expired" | Expiry notice, item available again, re-reserve link |
| 3 | Item purchased | Seller | "Your Item Has Sold! - Campus Swap" | Item, sale price, payout amount + % (50%/33%/20%), payout method/handle |
| 4 | Admin approves item | Seller | "Your Item Has Been Approved - Campus Swap" | Item details, final price, next steps by tier, fee breakdown, dashboard link |
| 5 | Item submitted (onboard/dashboard) | Seller | "Item Submitted - Campus Swap" | Submission confirmation, review timeline, dashboard link |
| 6 | Item submitted (guest signup flow) | Seller | "Item Submitted for Review - Campus Swap" | Submission + activation requirement note |
| 7 | Seller completes payment (webhook) | Seller | "Seller Activation Complete - Campus Swap" | Activation confirmed, pickup week selection info, dashboard link |
| 8 | Admin confirms free-tier pickup | Seller | "You're Confirmed for Pickup — Campus Swap" | Free pickup confirmed, add address + choose week, dashboard link |
| 9 | Admin rejects free-tier pickup | Seller | "Update on Your Free Plan Pickup — Campus Swap" | Capacity full, alternatives: POD drop-off (33%) or upgrade to Pro ($15/50%) |
| 10 | Admin bulk notifies free-tier users | Sellers | "Our Warehouse Is at Capacity — Campus Swap" | Same as #9, sent to all unconfirmed free-tier users |
| 11 | New account created | User | "Welcome to Campus Swap!" | Platform overview, quick start guide, dashboard link |

### Marketing (1 type)

| # | Trigger | Recipient | Subject | Key Content |
|---|---------|-----------|---------|-------------|
| 12 | Super admin sends mass email | All non-unsubscribed users | Custom subject | Custom HTML content, auto-added unsubscribe link, rate-limited at 0.55s/email |

**Email infrastructure:** Resend API, all emails wrapped in branded template (logo + footer), marketing emails include List-Unsubscribe headers, unsubscribed users automatically excluded.

---

## Admin Features

### Admin Dashboard (`/admin`)

**Role hierarchy:**
- **Super Admin:** Full access (user mgmt, database, mass email, categories)
- **Admin (Helper):** Approvals, item management, free-tier selection, quick add

### Overview Stats
- Total users, total items, sold items, pending items, available items
- Pickup Period toggle (OPEN/CLOSED)
- Store open date (editable)

### Item Approval Queue (`/admin/approve`)
- Card grid or single-item detail view
- Sort by: Price high/low, Date added oldest first
- Per item: set price, category/subcategory, condition, oversized flag
- Approve or Reject (keyboard shortcuts: A=approve, R=reject)
- Progress counter

### Item Lifecycle Table
- Filterable by: category, seller email, item title
- Columns: Item thumbnail, subcategory, seller, picked up, at store, status, reservation, payout, actions
- Per-item: mark sold, mark payout sent, edit, delete, undo

### Free Tier Management
- Warehouse + POD spot counters (color-coded)
- Ranked list by total approved item value
- Per user: name, email, items + prices, total value, status badge
- Actions: Confirm, Reject, Bulk notify all

### Category Management (Super Admin)
- Add/edit/delete categories with FontAwesome icons
- Subcategory management
- Essentials stock counts (Couch, Mattress, Mini-Fridge, Climate Control, TV)
- Bulk update

### User & Data Management (Super Admin)
- Grant/revoke admin access by email
- Data export: Users, Items, Sales (CSV)
- Preview before download
- Mass email
- Database reset (requires typing "reset database")

### Quick Add Item (Admin Helper)
- For in-person POD drop-offs
- Fields: category, condition, description, long description, photo, seller name, seller email
- Creates pending item; links to user if email exists, creates user if not

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

### Google Analytics
- GA4 tag (G-T696XM5XN9) on all pages via layout.html
- Standard pageview + automatic event tracking only
- No custom GA events configured

---

## Static / Legal Pages
| Page | Route | Notes |
|------|-------|-------|
| About | `/about` | Problem/solution narrative, store address |
| Privacy Policy | `/privacy-policy` | Data collected, third parties (Google, Stripe, Resend, PostHog) |
| Terms & Conditions | `/terms-and-conditions` | |
| Refund Policy | `/refund-policy` | |
| Unsubscribe Confirm | `/unsubscribe/<token>` | One-click marketing unsubscribe |
| Unsubscribe Success | (after confirm) | Confirms unsubscribe, notes transactional emails continue |
| Director | `/director` | Internal ops — jobs@campusswap.com recruiting page |

---

## Auth Flows
| Flow | Fields Collected | Notes |
|------|-----------------|-------|
| Email Login | email, password | |
| Email Register | full_name, email, password | Turnstile captcha |
| Google OAuth | (from Google) | email + profile info |
| Guest → Full Account | password (via dashboard) | Or full_name + email + password via onboard_complete_account |
| Password Change | current_password, new_password, confirm_password | current_password optional if no existing hash |

---

## Data Collected Summary

### From Buyers
- Email, full name, password (or Google OAuth)
- Reservation history (item_id, timestamp)
- Purchase history (via Stripe)

### From Sellers (all of the above, plus)
- Phone number
- Pickup location: type (on/off campus), dorm + room OR address + lat/lng + notes
- Payout method (Venmo/PayPal/Zelle) + handle
- Service tier choice (Free/Pro)
- Pickup week preference
- Per item: category, subcategory, condition, title, long description, suggested price, photos, video
- Stripe customer ID + payment method ID
- Referral source

### From Admin Actions
- Item approval with final price, category, condition, oversized flag
- Payout sent timestamps
- Free-tier confirm/reject decisions
