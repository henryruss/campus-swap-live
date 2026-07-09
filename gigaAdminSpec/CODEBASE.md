# Campus Swap — Codebase Reference

> This file is for Claude (Desktop or Code) to understand the current state of the codebase before designing or building features. Read this before writing specs or code.

---

## Tech Stack

| Layer | Tech |
|---|---|
| Backend | Flask 3.1 / Python 3.13 |
| Templating | Jinja2 (all pages server-rendered) |
| Database | PostgreSQL + SQLAlchemy ORM + Flask-Migrate |
| Auth | Google OAuth 2.0 + email/password (flask-login) |
| Payments | Stripe (checkout sessions + setup intents + webhooks) |
| Storage | CDN for carousel/product images; `/var/data/` on Render for uploads |
| Frontend | Custom CSS (no Tailwind, no Bootstrap), Vanilla JS |
| Email | Resend API |
| Analytics | PostHog, Google Analytics |
| Hosting | Render (web service + PostgreSQL) |

---

## Design System

All styling lives in `static/style.css`. CSS variables:

```css
--primary: #1A3D1A        /* Forest Green — headings, nav, borders */
--primary-light: #2E5C2E  /* Hover states, dividers */
--accent: #C8832A         /* Amber — CTAs, price tags */
--accent-hover: #A86A1F   /* Amber dark */
--text-main: #1A3D1A      /* Body text */
--text-muted: #6B8F6B     /* Secondary text */
--text-light: #F5F0E8     /* Text on dark backgrounds */
--bg-body: #FFFFFF        /* Page background */
--bg-cream: #F5F0E8       /* Alt section background */
--card-bg: #FFFFFF
--card-border: 1px solid #D8D0C4
--sage: #8AB88A
--rule: #D8D0C4
--glass-shadow: 0 20px 40px -10px rgba(0,0,0,0.1)
```

**Font:** DM Serif Display (headings), system sans-serif (body)

**Component classes:** `.card`, `.btn-primary` (amber), `.btn-outline` (green outline)

**Base template:** All pages extend `templates/layout.html` which includes nav, footer, PostHog, Google Analytics, and flash messages.

---

## Data Models (`models.py`)

### User
```
id, email, password_hash, full_name
is_admin, is_super_admin
phone, pickup_address, pickup_location_type ('on_campus'|'off_campus_complex'|'off_campus_other')
pickup_dorm, pickup_room, pickup_note (500 chars), pickup_lat, pickup_lng
pickup_access_type ('elevator'|'stairs_only'|'ground_floor', nullable)
pickup_floor (Integer 1–30, nullable)
pickup_partner_building (String 100, nullable) — partner apartment building name (used for geographic clustering)
sms_opted_out (Boolean, default False, server_default='0') — set True on STOP, False on UNSTOP/START via Twilio webhook; blocks SMS only, not email
payout_method, payout_handle
is_seller, has_paid, payment_declined
stripe_customer_id, stripe_payment_method_id
referral_source, unsubscribed, unsubscribe_token
oauth_provider, oauth_id
date_joined
pickup_week: 'week1' | 'week2' | None  — seller's stated preference (per-user, not per-item)
pickup_time_preference ('morning'|'afternoon'|'evening'|null)
moveout_date (Date, nullable)
is_worker (bool), worker_status (None|'pending'|'approved'|'rejected'), worker_role (None|'driver'|'organizer'|'both')
referral_code (String 8, unique, nullable) — 8-char uppercase alphanumeric, generated via _gen_referral_code() at proxy-seller creation (NOT on every account)
referred_by_id (FK → User, nullable) — column exists; the automatic referral-confirmation flow that would populate it is NOT currently wired up (see Payout Rate / Referral Program below)
payout_rate (Integer, model default 50) — stored payout percentage. Model default is 50; proxy-seller and tutorial-seed creation paths set 20 explicitly. No runtime referral-based recalculation exists.
has_paid_boost (Boolean, default False, server_default='0') — one-time $15 payout boost purchased flag; reset each season
is_campus_director (Boolean, default False) — has access to ops panel via role switcher; NOT is_admin/is_super_admin; gated by _has_ops_access()
is_internal_account (Boolean, default False, server_default='0') — marks the seeded "Campus Swap" account that owns donated/unclaimed QC items; excluded from seller-facing UI and payout exports
is_tutorial_user (Boolean, default False) — marks seed CD tutorial workers (Sam Torres, Riley Chen, Casey Brooks); excluded from all non-tutorial ops queries
class_year (String 20, nullable) — 'freshman'|'sophomore'|'junior'|'senior'|'grad'|NULL; collected at onboarding

Notes on pickup fields:
- off_campus_complex: pickup_dorm = building name (one of OFF_CAMPUS_COMPLEXES), pickup_room = unit number
- off_campus_other: pickup_address + pickup_lat/lng set; dorm/room cleared
- on_campus: pickup_dorm = dorm name, pickup_room = room number
- Legacy 'off_campus' value migrated to 'off_campus_other' via migration 773c1d40cca8
- has_pickup_location = False if pickup_access_type or pickup_floor is null

Properties: has_pickup_location, pickup_display, is_guest_account
```

### InventoryItem
```
id, description, long_description
price, suggested_price, quality (1-5 int)
status: 'pending_valuation' | 'needs_info' | 'approved' | 'available' | 'sold' | 'rejected'
date_added
collection_method: 'online' (Pro) | 'free' (Free)
pickup_week: 'week1' (Apr 27–May 3) | 'week2' (May 4–May 10)
dropoff_pod: deprecated (pod option removed)
sold_at, payout_sent (bool), payout_sent_at (DateTime, nullable) — timestamp set by admin via /admin/payouts
picked_up_at, arrived_at_store_at
category_id, seller_id
photo_url (cover photo), video_url
gallery_photos → [ItemPhoto]
price_changed_acknowledged (bool)
price_updated_at
storage_location_id (FK → StorageLocation, nullable) — where the item physically lives
storage_row (String, nullable) — aisle/row label within the storage location
storage_note (Text, nullable) — freeform note from organizer (e.g. "large box, shelf 3")
unit_size (Float, nullable) — per-item override for truck capacity calculation; NULL = use category default
is_quick_capture (Boolean, default False, server_default='0') — set only on items created via driver quick capture flow
quick_capture_shift_id (Integer, FK → Shift, nullable) — shift during which the item was captured (NULL if captured from crew dashboard with no shift)
captured_by_id (Integer, FK → User, nullable) — worker who took the QC photo; NULL on non-QC items
placement_status (String, nullable) — None | 'placed' | 'not_picked_up'; set by driver during placement flow at End Shift. crew_shift_end (confirmed path) blocks close if any items on the truck have placement_status IS NULL
needs_photo_refresh (Boolean, default False) — set True when replace_photo runs; used by review tools
retail_price (Numeric 10,2, nullable) — live retail reference set at AI approve time; shown to buyers as savings callout on inventory cards and product page
needs_new_photo (Boolean, default False, server_default='0') — hides item from shop; set at AI review approval when "Flag for new photo" checked; cleared by replace_photo route
needs_photo_verification (Boolean, default False, server_default='0') — item enters photo verification queue after replace_photo; cleared by verify-photo route when admin confirms photo looks good
subcategory_id (FK → InventoryCategory, nullable) — optional second-level category
ai_description, ai_long_description (Text, nullable) — staged AI-generated title and description; reviewed before going live
ai_price, ai_retail_price (Numeric 10,2, nullable) — staged AI-suggested price and retail reference; reviewed before going live
ai_review_pending (Boolean, default False, server_default='0') — item is in AI review queue awaiting admin approval
ai_generated_at (DateTime, nullable) — UTC timestamp of last AI generation attempt. NOTE: the retry/eligibility sentinel is now ai_description (NULL = not yet successfully generated), not ai_generated_at. Retries are capped by ai_retry_count.
ai_approved (Boolean, default False, server_default='0') — set True at approval; gates shop visibility (items must be ai_approved=True to appear in /inventory)
ai_retry_count (Integer, default 0, server_default='0') — AI autofill failure counter. Incremented on each failed attempt; hard stop at 3 (_AI_MAX_RETRIES). On failure under the cap, ai_generated_at is reset to NULL so the startup requeue picks the item up again.
ai_photo_enhanced (Boolean, default False, server_default='0') — True once OpenAI background-replacement photo enhancement succeeds for this item
seller_description, seller_long_description (Text, nullable) — write-once snapshot of the seller's original title/description at creation; never overwritten by AI or edits (preserves seller intent for the approval-modal comparison view)
was_previously_approved (Boolean, default False, server_default='0') — visibility fallback for items approved before the photo-enhancement rollout
needs_photo_note (Text, nullable) — optional note attached when an item is flagged for a new photo
is_featured (Boolean, default False, server_default='0') — admin-pinned homepage slot; guaranteed appearance in curated grid before blend-score ranked items
```

### InventoryCategory
```
id, name, image_url, icon (e.g. 'fa-couch'), count_in_stock
default_unit_size (Float, default 1.0, nullable) — truck space this category consumes; seeded for 12 furniture types
parent_id (FK → InventoryCategory, nullable) — self-referential; NULL = top-level category, set = subcategory
Relationships: parent → InventoryCategory (backref subcategories), items → [InventoryItem]
```

### ItemPhoto
```
id, item_id, photo_url
is_hidden (Boolean, default False, server_default='0') — hides photo from buyer-facing gallery via
  InventoryItem.visible_gallery_photos (Shop Edit Mode); also scaffolding for the rephoto post-process pass
captured_at (DateTime, nullable) — UTC; set ONLY by the warehouse rephoto capture flow.
  NULL = legacy / pre-campaign photo (no backfill by design)
sort_order (Integer, default 0, server_default='0') — gallery ordering; gallery_photos relationship
  orders by (sort_order, id) so legacy rows (all 0) keep their id order
view (String 10, nullable) — 'front' | 'side' | 'back' | NULL (legacy); lets the rephoto post-process
  pass pick the front shot deterministically
Migration: 4091b1a0e9c8 (captured_at/sort_order/view), 195e2dc3e376 (is_hidden)
```

### ItemReservation
```
id, item_id, user_id, created_at, expires_at, expiry_email_sent
Non-binding reservation (no payment). One active reservation per item at a time.
Buyer can cancel; reservations expire automatically.
```

### UploadSession / TempUpload
```
For QR code mobile-to-desktop photo upload flow.
UploadSession: session_token, user_id (nullable for guests), created_at
TempUpload: session_token, filename, created_at
```

### AdminEmail
```
Pre-approved emails that get admin/super_admin on signup.
id, email, is_super_admin, created_at
```

### SellerAlert
```
Reusable alert system for seller dashboard notifications.
id, item_id (FK to InventoryItem, nullable), user_id (FK to User)
created_by_id (FK to User, nullable — admin who created it)
alert_type: 'needs_info' | 'pickup_reminder' | 'custom' | 'preset'
reasons (Text, JSON-encoded list of preset reason strings)
custom_note (Text, nullable)
resolved (Boolean, default False), resolved_at (DateTime, nullable)
created_at (DateTime, default utcnow)
Relationships: item, user (backref seller_alerts), created_by
```

### DigestLog
```
Tracks admin approval digest email sends for deduplication.
id, sent_at (DateTime, default utcnow)
item_count (Integer), recipient_count (Integer)
```

### AppSetting
```
Key-value store for runtime flags.
AppSetting.get(key, default), AppSetting.set(key, value)
Store/shop keys: 'reserve_only_mode', 'pickup_period_active', 'current_store', 'store_open_date',
'shop_teaser_mode' ('true' → show pre-launch teaser on /inventory; absent/'false' → normal shop),
'pickup_week_start', 'pickup_week_end'
Crew/staffing keys: 'crew_applications_open', 'crew_allowed_email_domain',
'drivers_per_truck', 'organizers_per_truck' (unused for capacity — superseded by stagger formula), 'max_trucks_per_shift',
'shifts_required' (minimum shifts for season payout)
Free-tier bookkeeping: 'free_confirmed_user_ids', 'free_rejected_user_ids' (CSV id lists)
Delivery / pricing keys (Spec A): 'warehouse_lat', 'warehouse_lng' (now editable in Settings → Route & capacity;
  fall back to WAREHOUSE_DEFAULT_LAT/LNG when blank), 'delivery_zone_boundaries' (zone mile cutoffs),
  'delivery_zone_fees', 'flexible_delivery_discount', 'sales_tax_rate', 'stripe_flexible_coupon_id'.
  NOTE: zone-based pricing replaced the old 'delivery_radius_miles' radius model — that key is no longer used.
Cart / bundle keys (Spec B): 'checkout_hold_minutes' (default 15 — active-checkout hold window; replaces the
  membership-based use of 'cart_hold_minutes'), 'bundle_min_items' (default 2 → bundle free delivery)
AI autofill keys: 'ai_autofill_model', 'ai_autofill_run_log'
Rephoto key: 'rephoto_campaign_start' (date string, default '2026-07-08') — ✓-badge boundary for the
  warehouse re-photography campaign; parsed as Eastern midnight → UTC by _rephoto_campaign_start_utc()
Route planning keys: 'truck_raw_capacity', 'truck_capacity_buffer_pct',
  'route_am_window', 'route_pm_window', 'maps_static_api_key'
Rescheduling keys: 'reschedule_token_ttl_days', 'reschedule_urgent_alert_days'
SMS keys: 'sms_enabled' (master kill switch), 'sms_reminder_hour_eastern',
  'no_show_email_enabled', 'no_show_email_hour_eastern'
NOTE: the previously-documented referral_* AppSetting keys (referral_base_rate, etc.) are NOT referenced anywhere in app.py.
```

### ShopNotifySignup
```
Email capture for pre-launch Shop Drop teaser. No UNIQUE constraint — duplicates silently accepted.
id, email (String 120), created_at (DateTime), ip_address (String 45, nullable)
```

### Order (Spec B — cart parent)
```
Order-level parent record, one per Stripe checkout session (one per cart checkout).
id, buyer_id (FK → User, nullable), buyer_email, buyer_name
delivery_street/city/state/zip, delivery_lat, delivery_lng, distance_miles, delivery_zone
delivery_fee (Numeric), bundle_free_delivery (bool), is_flexible_delivery (bool), flexible_discount (Numeric)
sales_tax (Numeric), items_subtotal (Numeric), total_paid (Numeric)
stripe_checkout_session_id (String 120, nullable)
status ('pending' → 'paid'), has_conflict (bool — double-sale guard), created_at, paid_at
Relationships: buyer → User (backref orders), line_items → [BuyerOrder]
```

### BuyerOrder (per-item line)
```
Per-item purchase line under an Order. One record per sold item.
id, item_id (FK → InventoryItem, unique), buyer_email (String 120)
delivery_address (String 300), delivery_lat, delivery_lng
stripe_session_id (String 120, nullable), created_at, delivered_at (set when DeliveryStop completed; informational)
Spec A fields (legacy — Order is now source of truth for new orders):
  delivery_zone, delivery_fee, is_flexible_delivery, flexible_discount, sales_tax,
  distance_miles, items_subtotal, total_paid, stripe_checkout_session_id
Spec B fields: order_id (FK → Order, nullable), item_price_paid (Numeric), item_sales_tax (Numeric)
Relationships: item → InventoryItem (backref buyer_order, uselist=False), order → Order (backref line_items)
```

### Cart / CartItem (Spec B)
```
Cart: active shopping cart — one per logged-in user OR per guest session token.
  id, user_id (FK → User, nullable), session_token (String 64, nullable, indexed), created_at, updated_at
  checkout_started_at (DateTime, nullable) — set when buyer hits "Proceed to Payment". Migration c3d4e5f6a7b8.
  Relationships: user → User (backref carts), cart_items → [CartItem]
  Checkout-based hold (rewritten): item_is_held(item, exclude_cart_id) treats an item as held against
  OTHER buyers ONLY while some cart's Cart.checkout_started_at is within checkout_hold_minutes
  (AppSetting, default 15). No cron — expiry is computed at read time. The old membership-based hold
  (cart_hold_minutes from cart presence alone) is gone — leaving an item in a cart no longer holds it.
CartItem: one item in a cart. id, cart_id (FK → Cart), item_id (FK → InventoryItem), added_at
  Unique constraint: (cart_id, item_id)
```

### Referral
```
One record per (referrer_id, referred_id) pair. referred_id is unique (one referrer per user).
id, referrer_id (FK → User), referred_id (FK → User, unique)
created_at, confirmed (bool, default False), confirmed_at (nullable)
Relationships: referrer → User (backref referrals_given), referred → User (backref referral_received, uselist=False)
```

### WorkerApplication
```
One application per user. Stores role preference and availability blurb.
id, user_id (FK, unique), unc_year, role_pref ('driver'|'organizer'|'both')
why_blurb (Text, nullable), applied_at (DateTime)
reviewed_at (DateTime, nullable), reviewed_by (FK to User, nullable)
Relationships: user (backref worker_application, uselist=False), reviewer
```

### WorkerAvailability
```
One record per worker per week.
week_start=NULL for initial application submission; Monday date for weekly updates.
True = available, False = blacked out.
id, user_id (FK), week_start (Date, nullable)
Fields: mon_am, mon_pm, tue_am, tue_pm, wed_am, wed_pm, thu_am, thu_pm,
        fri_am, fri_pm, sat_am, sat_pm, sun_am, sun_pm (all Boolean, default True)
```

### ShiftWeek
```
One record per work week.
id, week_start (Date — Monday of the work week)
status: 'draft' | 'published'
is_tutorial (Boolean, default False) — marks the sandboxed tutorial shift week; excluded from all production ops queries. Unique constraint is (week_start, is_tutorial) allowing a tutorial and real week with the same start date.
created_at, created_by_id (FK → User, nullable)
Relationships: shifts → [Shift], created_by → User
```

### Shift
```
One AM or PM block per day within a ShiftWeek.
id, week_id (FK), day_of_week ('mon'|'tue'|'wed'|'thu'|'fri'|'sat'|'sun')
slot: 'am' | 'pm' | 'daily'
trucks (Integer, default 2), is_active (Boolean, default True)
created_at
truck_unit_plan (Text, nullable) — JSON dict {"truck_num": storage_location_id} — planned destination per truck;
  written by admin before pickups exist; synced to ShiftPickup.storage_location_id when pickups are added
sellers_notified (Boolean, default False) — True once admin has sent pickup confirmation emails for this shift
last_notified_at (DateTime, nullable) — timestamp of most recent notify-sellers run; used for "new" badge on stops added after last notification
overflow_truck_number (Integer, nullable) — overflow-designated truck for rescheduled sellers; NULL = truck 1
reschedule_locked (Boolean, default False) — excluded from seller reschedule slot grids when True
Relationships: week → ShiftWeek, assignments → [ShiftAssignment]
Properties: label, sort_key, drivers_needed, organizers_needed,
            driver_assignments, organizer_assignments, is_fully_staffed, status_label,
            has_delivery_trucks (computed — True if any DeliveryStop exists for this shift)
```

### ShiftAssignment
```
One worker assigned to one shift in a specific role.
id, shift_id (FK), worker_id (FK → User), role_on_shift ('driver'|'organizer')
truck_number (Integer, nullable — NULL for organizers; 1-N for movers)
assigned_at, assigned_by_id (FK → User, nullable — NULL = optimizer)
completed_at (DateTime, nullable) — per-worker, per-role completion timestamp;
  set when driver taps End Shift OR when organizer taps End Intake; independent
Relationships: shift → Shift, worker → User, assigned_by → User
```

### ShiftPickup
```
One seller stop per shift. Populated by admin via ops page.
id, shift_id (FK → Shift), seller_id (FK → User), truck_number (Integer)
stop_order (Integer, nullable) — populated by nearest-neighbor ordering; shift-scoped (not per-truck)
status: 'pending' | 'completed' | 'issue'   default: 'pending'
notes (Text, nullable), completed_at (DateTime, nullable)
storage_location_id (FK → StorageLocation, nullable) — planned destination unit;
  written by admin only; pre-populated from Shift.truck_unit_plan when seller is added
notified_at (DateTime, nullable) — timestamp when seller was sent pickup confirmation email
capacity_warning (Boolean, default False) — True when assigned to an over-capacity truck
rescheduled_from_shift_id (Integer, FK → Shift, nullable) — shift this stop was moved from; NULL = original assignment
rescheduled_at (DateTime, nullable) — Eastern timestamp of reschedule
issue_type (String 20, nullable) — 'no_show' | 'other' | NULL; set on issue flag, cleared on revert
no_show_email_sent_at (DateTime, nullable) — idempotency guard; set when recovery email sent; never cleared
created_at, created_by_id (FK → User)
Unique constraint: (shift_id, seller_id) — seller globally unique across all shifts
Relationships: shift → Shift (foreign_keys=[shift_id]), seller → User (backref: shift_pickups),
               created_by → User, storage_location → StorageLocation,
               rescheduled_from_shift → Shift (foreign_keys=[rescheduled_from_shift_id])
```

### ShiftRun
```
Shift-level execution state. Created when mover taps Start Shift.
id, shift_id (FK → Shift, unique), started_at, started_by_id (FK → User)
ended_at (DateTime, nullable), status: 'in_progress' | 'completed'
Relationships: shift → Shift (backref: run, uselist=False), started_by → User
```

### RescheduleToken
```
One-time token for email-linked seller reschedule (no login required).
id, token (String 64, unique, indexed), pickup_id (FK → ShiftPickup), seller_id (FK → User)
created_at, used_at (DateTime, nullable — NULL = unused), expires_at (DateTime)
revoked_at (DateTime, nullable) — set when associated stop is marked 'completed'; distinct from used_at (self-rescheduled)
Datetimes stored naive (no tzinfo). TTL configured via AppSetting 'reschedule_token_ttl_days'.
Relationships: pickup → ShiftPickup (backref: reschedule_tokens), seller → User
```

### WorkerPreference
```
Partner preferences between movers.
id, user_id (FK → User), target_user_id (FK → User)
preference_type: 'preferred' | 'avoided'
created_at
Unique constraint: (user_id, target_user_id, preference_type)
Relationships: user → User (backref: worker_preferences), target_user → User
```

### TutorialSession
```
One record per campus director. Tracks progress through the onboarding tutorial.
id, user_id (FK → User, unique), step (Integer, default 0)
started_at (DateTime, nullable), completed_at (DateTime, nullable)
tutorial_week_id (FK → ShiftWeek, nullable) — the sandboxed tutorial shift week created for this CD
last_retake_at (DateTime, nullable), is_retaking (Boolean, default False, server_default='0')

Step sequence (0–9):
  0 = not started
  1 = started; on schedule page, week not yet created
  2 = week created; on schedule or crew; approve Sam Torres
  3 = Sam approved; assign crew to shift and sellers to ops
  4 = worker assigned; navigate to Ops; assign remaining sellers
  5 = unused/skipped
  6 = all sellers assigned; click Reorder Stops
  7 = on reorder page (bumped from 6→7 on GET of ops_reorder_page)
  8 = stops reordered; click Notify Sellers
  9 = complete

Relationships: user → User (backref: tutorial_session, uselist=False), tutorial_week → ShiftWeek
```

### StorageLocation
```
A physical storage unit or warehouse where items are held after pickup.
id, name (String), address (String)
location_note (Text, nullable) — directions, access code, landmarks
capacity_note (Text, nullable) — e.g. "Unit 14B, max ~80 items"
is_active (Boolean, default True), is_full (Boolean, default False)
lat (Float, nullable), lng (Float, nullable) — coordinates for nearest-neighbor stop ordering
snapshot_capacity (Float, nullable) — set when admin marks unit full via warehouse floor; used to compute capacity battery %; NOT cleared when unit is marked available
created_at, created_by_id (FK → User, nullable)
Relationships: items → [InventoryItem], intake_records → [IntakeRecord]
```

### IntakeRecord
```
Append-only log of one organizer receiving one item at a storage location.
Re-submissions create new rows (not updates) — full audit trail preserved.
id, item_id (FK → InventoryItem), shift_id (FK → Shift), organizer_id (FK → User)
storage_location_id (FK → StorageLocation), storage_row (String, nullable)
storage_note (Text, nullable), quality_before (Integer, nullable — 1–5)
quality_after (Integer, nullable — 1–5), created_at
Relationships: item → InventoryItem, shift → Shift, organizer → User,
               storage_location → StorageLocation
```

### IntakeFlag
```
Flagged item during intake: damaged, missing, or completely unidentified.
id, item_id (FK → InventoryItem, nullable — NULL for unknown/unidentified items)
shift_id (FK → Shift), intake_record_id (FK → IntakeRecord, nullable)
organizer_id (FK → User)
flag_type: 'missing' | 'damaged' | 'wrong_item' | 'extra_item' | 'unknown_item' | 'other'
description (Text, NOT nullable), resolved (Boolean, default False)
resolved_at (DateTime, nullable), resolved_by_id (FK → User, nullable)
resolution_note (Text, nullable), created_at
Relationships: item → InventoryItem, shift → Shift, intake_record → IntakeRecord,
               organizer → User, resolved_by → User
```

### DeliveryStop (Spec D1)
```
One buyer delivery stop per shift. Analogous to ShiftPickup.
id, shift_id (FK → Shift), buyer_order_id (FK → BuyerOrder), truck_number (Integer, default 1)
stop_order (Integer, nullable), status ('pending'|'completed'|'issue'), notes (Text, nullable)
completed_at, notified_at, capacity_warning (bool), created_at, created_by_id (FK → User, nullable)
Unique constraint: (shift_id, buyer_order_id)
Relationships: shift → Shift (backref delivery_stops), buyer_order → BuyerOrder (backref delivery_stop, uselist=False)
```

### DeliveryRun (Spec D1)
```
Run-level execution state for a delivery shift. Analogous to ShiftRun.
id, shift_id (FK → Shift, unique), started_at, started_by_id (FK → User)
ended_at (DateTime, nullable), status ('in_progress'|'completed')
Relationships: shift → Shift (backref delivery_run, uselist=False), started_by → User
```

---

## Route Map (`app.py` — ~18,000 lines, 278 URL rules)

### Public
| Route | Function | Notes |
|---|---|---|
| `GET /` | `index` | Homepage + waitlist signup form |
| `GET /about` | `about` | About page |
| `GET /contact` | `contact` | Contact form (name, email, subject, message + Turnstile captcha) |
| `GET /privacy-policy` | `privacy_policy` | |
| `GET /terms-and-conditions` | `terms_conditions` | |
| `GET /refund-policy` | `refund_policy` | |
| `GET /inventory` | `inventory` | Shop front, category filter + search |
| `GET /item/<id>` | `product_detail` | Product page |
| `GET /become-a-seller` | `become_a_seller` | Landing page for sellers |
| `GET /share/item/<id>/card.png` | `share_card_image` | OG share card image |
| `GET /sitemap.xml` | `sitemap` | |
| `GET /robots.txt` | `robots_txt` | |
| `GET /catalog.xml` | `meta_catalog_feed` | Public Meta/Facebook product catalog (RSS 2.0). No auth. Module-level `_catalog_cache` + `CATALOG_CACHE_TTL=3600`. Eligibility mirrors shop filter. |
| `GET /uploads/<filename>` | `uploaded_file` | Serve uploaded files |
| `GET /unsubscribe/<token>` | `unsubscribe` | Email unsubscribe |
| `GET /parents` | `parents` | Parents landing page |

### Auth
| Route | Function | Notes |
|---|---|---|
| `GET/POST /login` | `login` | Email/password login |
| `GET/POST /register` | `register` | New account. |
| `GET /logout` | `logout` | |
| `GET /auth/google` | `auth_google` | OAuth redirect |
| `GET /auth/google/callback` | `auth_google_callback` | OAuth callback |
| `POST /set_password` | `set_password` | For guest → full account conversion |

### Seller Onboarding
| Route | Function | Notes |
|---|---|---|
| `GET/POST /onboard` | `onboard` | Main multi-step onboarding wizard (all sellers start free) |
| `POST /onboard/guest/save` | `onboard_guest_save` | Save guest onboard session |
| `GET /onboard/complete_account` | `onboard_complete_account` | Post-onboard account setup |
| `GET /onboard_complete` | `onboard_complete` | Success page |
| `GET /onboard_cancel` | `onboard_cancel` | Cancel flow |

### Item Management (Seller)
| Route | Function | Notes |
|---|---|---|
| `GET/POST /add_item` | `add_item` | Upload item (photo + details) |
| `GET/POST /edit_item/<id>` | `edit_item` | Edit existing item (owner or admin). Admin extras: seller reassignment via `new_seller_id` (admin-only form section, live search via seller-search endpoint; no notification sent) and post-save redirect to `/admin/items` (not admin_panel). |
| `GET /delete_photo/<id>` | `delete_photo` | Delete gallery photo (plain link from edit_item.html). Promotes another photo to cover if the cover was deleted. Always redirects back to `edit_item` — the old admin branch that bounced to `admin_panel`/ops was removed 2026-07-09. |
| `POST /item/<id>/resubmit` | `resubmit_item` | Seller resubmits item after addressing "needs info" feedback |
| `GET/POST /confirm_pickup` | `confirm_pickup` | **Deprecated** — now redirects to `/dashboard`. Pickup week set via dashboard modal. |
| `GET /confirm_pickup_success` | `confirm_pickup_success` | |
| `GET/POST /upgrade_pickup` | `upgrade_pickup` | Upgrade from Free to Pro plan ($15) |
| `GET /upgrade_pickup_success` | `upgrade_pickup_success` | |
### Buyer — Cart, Checkout & Purchase
| Route | Function | Notes |
|---|---|---|
| `POST /cart/add/<id>` | `cart_add` | Add item to active cart (user or guest session token) |
| `POST /cart/remove/<id>` | `cart_remove` | Remove item from cart |
| `GET /cart` | `cart_view` | Cart page — line items, bundle/delivery summary |
| `POST /cart/checkout` | `cart_checkout` | Begin checkout for the whole cart → delivery form |
| `GET/POST /checkout/delivery` | `checkout_delivery` | Buyer delivery address form + geocode + zone calc (cart-based) |
| `GET/POST /checkout/review` | `checkout_review` | Order review (subtotal, delivery fee, bundle/flexible, tax, total) → Stripe. Creates pending Order before redirect. |
| `GET/POST /checkout/delivery/<id>` | `checkout_delivery_legacy` | Legacy per-item delivery URL — redirects into cart flow |
| `GET /checkout/pay/<id>` | `checkout_pay` | Legacy — redirect |
| `GET/POST /checkout/review/<id>` | `checkout_review_legacy` | Legacy per-item review URL — redirect |
| `GET /buy_item/<id>` | `buy_item` | Initiate single-item Stripe checkout |
| `GET /item_success` | `item_sold_success` | Post-purchase success |

Bundle & Save: when `item_count >= bundle_min_items` (AppSetting, default 2) the order's delivery fee is set to 0 (`bundle_free_delivery=True`). Items are only marked sold in the Stripe webhook (source of truth); the pending Order/double-sale guard prevents reselling a held item.

### Payments & Stripe
| Route | Function | Notes |
|---|---|---|
| `POST /create_checkout_session` | `create_checkout_session` | Stripe checkout for item purchase |
| `POST /upgrade_checkout` | `upgrade_checkout` | Stripe checkout for pickup upgrade |
| `GET /success` | `payment_success` | Generic payment success |
| `GET /add_payment_method` | `add_payment_method` | Save card for deferred charge |
| `POST /create_setup_intent` | `create_setup_intent` | Stripe SetupIntent |
| `GET /payment_method_success` | `payment_method_success` | |
| `POST /webhook` | `webhook` | Stripe webhook handler |
| `POST /sms/webhook` | `sms_inbound_webhook` | Twilio inbound SMS. No login. Validates Twilio signature. Handles STOP/UNSTOP → sets sms_opted_out. |

### Dashboard & Account
| Route | Function | Notes |
|---|---|---|
| `GET /dashboard` | `dashboard` | Seller dashboard |
| `GET /account_settings` | `account_settings` | |
| `POST /update_profile` | `update_profile` | Name, phone, location |
| `POST /update_payout` | `update_payout` | Venmo/Zelle handle |
| `POST /update_account_info` | `update_account_info` | |
| `POST /change_password` | `change_password` | |
| `GET/POST /complete_profile` | `complete_profile` | Collect phone after Google OAuth (redirects to `next_after_profile` session key) |
| `POST /api/user/set_pickup_week` | `api_set_pickup_week` | AJAX: save User.pickup_week + pickup_time_preference; returns JSON |
| `GET /switch-role/seller` | `switch_role_seller` | CD only: sets session['cd_view']='seller', redirects to /dashboard |
| `GET /switch-role/admin` | `switch_role_admin` | CD only: sets session['cd_view']='admin', redirects to /admin/ops |

### Admin (requires is_admin or is_super_admin)
| Route | Function | Notes |
|---|---|---|
| `GET /admin/ops` | `admin_ops` | Main ops view — shift panel, truck cards, unassigned panel. Default entry point. |
| `GET /admin/ops/truck-detail` | `admin_ops_truck_detail` | HTML partial for truck detail drawer. Params: shift_id, truck. |
| `GET /admin/ops/unit-picker-partial` | `admin_ops_unit_picker_partial` | HTML partial — card grid of active StorageLocations with capacity data for unit picker modal. `_has_ops_access()`. |
| `GET /admin/catalog/preview` | `admin_catalog_preview` | Inline HTML table preview of first 10 catalog-eligible items. Super admin only. |
| `GET /admin/items` | `admin_items` | Items tab — approval queue + lifecycle table. view=approve|all. |
| `GET /admin/sellers` | `admin_sellers` | Sellers tab — list, nudge, free-tier. |
| `GET /admin/crew` | `admin_crew_panel` | Crew tab — pending applications + approved workers. |
| `GET/POST /admin/settings` | `admin_settings` | Settings tab — all config sections. Super admin only. |
| `POST /admin/settings/generate-shifts` | `admin_generate_shifts` | Generate AM+PM shifts for pickup date range. Super admin only. |
| `GET/POST /admin` | `admin_panel` | GET → 302 to `/admin/ops`. POST still handles all existing store/item form submissions. |
| `GET/POST /admin/approve` | `admin_approve` | GET → 302 to `/admin/items?view=approve`. POST (approval actions) unchanged. |
| `POST /admin/free/confirm/<user_id>` | `admin_free_confirm` | Approve free-tier seller |
| `POST /admin/free/reject/<user_id>` | `admin_free_reject` | Reject free-tier seller |
| `POST /admin/free/notify_all` | `admin_free_notify_all` | Email all pending free sellers |
| `POST /admin/category/add` | `admin_add_category` | |
| `POST /admin/category/edit/<id>` | `admin_edit_category` | |
| `POST /admin/category/bulk-update` | `admin_bulk_update_categories` | |
| `POST /admin/category/delete/<id>` | `admin_delete_category` | |
| `POST /admin/user/delete/<id>` | `admin_delete_user` | |
| `POST /admin/user/make-admin` | `admin_make_admin` | |
| `POST /admin/user/revoke-admin` | `admin_revoke_admin` | |
| `GET /admin/preview/users` | `admin_preview_users` | |
| `GET /admin/export/users` | `admin_export_users` | CSV download |
| `GET /admin/preview/items` | `admin_preview_items` | |
| `GET /admin/export/items` | `admin_export_items` | CSV download |
| `GET /admin/preview/sales` | `admin_preview_sales` | |
| `GET /admin/export/sales` | `admin_export_sales` | CSV download |
| `POST /admin/item/<id>/request_info` | `admin_request_info` | "More Info Needed" — sets item to needs_info, creates SellerAlert |
| `POST /admin/item/<id>/cancel_request` | `admin_cancel_info_request` | Cancel outstanding info request, returns item to pending_valuation |
| `GET /admin/seller/<user_id>/panel` | `admin_seller_panel` | Returns HTML partial for slide-out seller profile panel |
| `POST /admin/seller/<user_id>/send_alert` | `admin_send_seller_alert` | Creates SellerAlert (preset or custom) from seller panel |
| `POST /admin/pickup-nudge/send` | `admin_send_pickup_nudge` | Sends pickup reminder alerts to selected or all eligible sellers |
| `POST /admin/digest/trigger` | `digest_trigger` | Cron job endpoint for hourly approval digest email (auth via DIGEST_CRON_SECRET) |
| `POST /admin/digest/send` | `send_approval_digest` | Super admin manual trigger for digest email |
| `POST /admin/mass-email` | `admin_mass_email` | |
| `POST /admin/database/reset` | `admin_database_reset` | Super admin only |
| `POST /admin/crew/approve/<user_id>` | `admin_crew_approve` | Approve worker (sets worker_role='both'); sends email |
| `POST /admin/crew/reject/<user_id>` | `admin_crew_reject` | Reject worker application |
| `GET /admin/crew/shift/<shift_id>/ops` | `admin_shift_ops` | Live ops view — mover-to-truck cards + route stop lists + destination unit selectors |
| `GET /admin/routes` | `admin_routes_index` | GET → 302 to `/admin/ops`. Route planning absorbed into Ops tab. |
| `POST /admin/routes/auto-assign` | `admin_routes_auto_assign` | Run auto-assignment for all unassigned eligible sellers. Returns JSON {assigned, tbd, over_cap_warnings} |
| `POST /admin/routes/stop/<pickup_id>/move` | `admin_routes_move_stop` | Move ShiftPickup to different shift+truck; recalculates capacity_warning. Returns JSON |
| `POST /admin/routes/seller/<user_id>/assign` | `admin_routes_assign_seller` | Manually assign unassigned seller. Returns JSON (409 if seller already has ShiftPickup). Mixed-truck guard: returns 422 and creates nothing if the target truck already has DeliveryStops (previously created an orphan ShiftPickup that vanished from the unassigned list). |
| `POST /admin/crew/shift/<shift_id>/add-truck` | `admin_shift_add_truck` | Increment Shift.trucks by 1 via raw SQL. Returns JSON {new_truck_number} |
| `POST /admin/crew/shift/<shift_id>/order` | `admin_shift_order_stops` | Nearest-neighbor stop ordering from storage unit origin; writes stop_order to all ShiftPickups |
| `POST /admin/crew/shift/<shift_id>/stop/<pickup_id>/reorder` | `admin_shift_reorder_stop` | Set a specific stop_order value. Returns JSON |
| `POST /admin/crew/shift/<shift_id>/notify` | `admin_shift_notify_sellers` | Send pickup confirmation emails to unnotified sellers (idempotent). Redirect. (Spec #9: also sends SMS alongside email) |
| `POST /admin/cron/sms-reminders` | `cron_sms_reminders` | Daily 24hr SMS reminder cron. Auth: Authorization: Bearer <CRON_SECRET>. No login required. |
| `POST /admin/cron/no-show-emails` | `cron_no_show_emails` | End-of-day no-show recovery email cron. Auth: same. Idempotent via no_show_email_sent_at. |
| `GET /crew/shift/<shift_id>/stops_partial` | `crew_shift_stops_partial` | HTML partial of stops for current mover's truck. Used by 30s auto-refresh |
| `GET+POST /admin/settings/route` | `admin_route_settings` | GET → 302 to `/admin/settings#route`. POST saves capacity settings (unchanged). Super admin only. |
| `POST /admin/crew/shift/<shift_id>/assign` | `admin_shift_assign_seller` | Add seller stop to shift (globally unique per seller); pre-populates storage_location_id from truck_unit_plan; returns 422 `{error: 'unit_required'}` when truck has 0 stops and no unit assigned in truck_unit_plan |
| `POST /admin/crew/shift/<shift_id>/quick-add` | `admin_crew_quick_add` | Add worker to shift from Crew HQ. Driver defaults to truck_number=1. Auth: _has_ops_access() |
| `POST /admin/crew/shift/<shift_id>/quick-remove` | `admin_crew_quick_remove` | Remove ShiftAssignment from Crew HQ. No email sent. Auth: _has_ops_access() |
| `POST /admin/crew/worker/<user_id>/availability` | `admin_crew_override_availability` | Admin upserts WorkerAvailability for current week. Auth: _has_ops_access() |
| `POST /admin/crew/remove/<user_id>` | `admin_crew_remove` | Set is_worker=False, worker_status='rejected', bulk-delete all ShiftAssignments. Admin-only (not super admin). Hard-blocked for is_tutorial_user workers. |
| `POST /admin/crew/shift/<shift_id>/truck/<truck_number>/remove` | `admin_shift_remove_truck` | Decrement Shift.trucks by 1 via raw SQL. Validates: highest truck only, zero stops. Clears truck from truck_unit_plan. Auth: _has_ops_access() |
| `POST /admin/crew/shift/<shift_id>/stop/<pickup_id>/remove` | `admin_shift_remove_stop` | Remove pending stop only |
| `POST /admin/crew/shift/<shift_id>/mover/<assignment_id>/assign_truck` | `admin_shift_assign_mover_truck` | Assign driver to truck (cap-enforced); truck_number=0 unassigns |
| `POST /admin/crew/shift/<shift_id>/assign_movers_bulk` | `admin_shift_assign_movers_bulk` | Assign multiple movers to a truck in one submit |
| `POST /admin/crew/shift/<shift_id>/truck/<truck_number>/assign_unit` | `admin_shift_assign_unit` | Write truck→unit mapping to Shift.truck_unit_plan; sync to existing pending pickups for that truck. Returns JSON. |
| `GET /admin/crew/shift/<shift_id>/intake` | `admin_shift_intake_log` | Full read-only intake log for a shift (all records + flags) |
| `POST /admin/intake/flag/<flag_id>/resolve` | `admin_intake_flag_resolve` | Resolve a single IntakeFlag with resolution note |
| `GET /admin/intake/flagged` | `admin_intake_flagged` | Damaged/missing review queue — all items with unresolved flags (excl. sold/rejected) |
| `POST /admin/intake/flagged/remove` | `admin_intake_flagged_remove` | Bulk reject: sets status='rejected', auto-resolves all flags with audit note |
| `GET /admin/payouts` | `admin_payouts` | Payout reconciliation — Unpaid tab (seller cards) + Paid history tab + CSV export |
| `POST /admin/payouts/item/<id>/mark_paid` | `admin_payouts_mark_paid` | Mark item as paid — sets payout_sent=True, payout_sent_at=now, sends payout email |
| `GET /admin/payouts/export` | `admin_payouts_export` | CSV export of all sold items with payout data |
| `GET /admin/items/needs_info` | `admin_needs_info_queue` | Quick-capture items awaiting completion (is_quick_capture=True, status pending_valuation/needs_info). Renders `admin/needs_info.html`. Reachable via the `admin_request_info` redirect when a QC item gets an info request. |
| `POST /admin/item/<id>/approve` | `admin_item_approve` | One-click approve for quick-capture items only. No price required. Sets status='available'. Returns JSON. |
| `POST /admin/item/<id>/toggle-featured` | `admin_item_toggle_featured` | Toggle `InventoryItem.is_featured` (homepage pin). Admin only. Returns JSON `{success, is_featured}`. |
| `GET /admin/item/<id>/approval-detail` | `admin_item_approval_detail` | HTML partial (no layout) with full item data for approval modal. 404 if not pending_valuation or needs_info. |
| `POST /admin/item/<id>/approve-unified` | `admin_approve_unified` | Unified approve: writes AI staged fields → live fields, sets ai_approved=True, status='available', ai_review_pending=False, sends approval email. Super admin only. Returns JSON. |
| `POST /admin/quick_capture/<id>/delete` | `admin_quick_capture_delete` | Hard delete any QC item (photo + DB). No captured_by guard. |
| `POST /admin/settings/reassign-week` | `admin_reassign_week` | Bulk set pickup_week=2 for all sellers with pickup_week=1 and no ShiftPickup. Super admin only. |
| `GET /admin/tutorial` | `admin_tutorial_welcome` | Tutorial welcome/restart page for campus directors |
| `POST /admin/tutorial/start` | `admin_tutorial_start` | Creates or resets TutorialSession; calls seed_tutorial_fixtures() |
| `GET /admin/tutorial/complete` | `admin_tutorial_complete_page` | Completion page. Guard: ts.step >= 9 |
| `POST /admin/tutorial/exit` | `admin_tutorial_exit` | Marks tutorial complete for is_retaking CDs; redirects to ops |
| `GET /admin/cd-settings` | `admin_cd_settings` | CD Settings page — tutorial status, Retake/Continue button |
| `GET /admin/storage` | `admin_storage_index` | GET → 302 to `/admin/settings#storage`. Content moved to Settings tab. |
| `POST /admin/storage/create` | `admin_storage_create` | Create StorageLocation. Super admin only. |
| `POST /admin/storage/<id>/edit` | `admin_storage_edit` | Edit StorageLocation fields (name, address, capacity_note, is_active). Accepts `_next` form param for post-save redirect. Super admin only. |
| `POST /admin/storage/<id>/delete` | `admin_storage_delete` | Delete StorageLocation. Returns 409 JSON error if any items are assigned to the unit. Super admin only. |
| `GET /admin/storage/<id>` | `admin_storage_detail` | All items at a storage location, filterable by status. Admin. |
| `GET /admin/storage/audit` | — | **Redirects 302 to `/admin/warehouse`.** |
| `GET /admin/storage/audit/search` | — | **Redirects 302 to `/admin/warehouse/search`.** |
| `POST /admin/item/<id>/set_location` | `admin_item_set_location` | Update `storage_location_id`, `storage_row`, `storage_note` on item from audit tool. Returns JSON `{success}`. Admin. |
| `POST /admin/item/<id>/replace_photo` | `admin_item_replace_photo` | Replace item cover photo. Also sets needs_photo_verification=True, needs_new_photo=False, deletes old cover from ItemPhoto records (prevents carousel duplication). Returns JSON {success, photo_url}. Admin. |
| `GET /admin/storage/template` | `admin_storage_template` | Download xlsx template for bulk storage unit import. |
| `POST /admin/storage/import` | `admin_storage_import` | Bulk import storage units from xlsx/csv. 2 MB file size gate. openpyxl `read_only=True, data_only=True` streaming to prevent OOM. Skips rows with empty name. Returns flash + redirect. Super admin only. |
| `GET /admin/warehouse` | `admin_warehouse` | Warehouse Floor main page. Unit card grid with capacity battery bars, item counts, Full badges. Needs New Photo section (amber, collapsible). Photo Verification Queue (indigo, open by default). Global search. _has_ops_access(). |
| `GET /admin/warehouse/unit/<id>` | `admin_warehouse_unit` | HTML partial for unit drawer (item list, battery bar, toggle-full button, Log Item Here button). _has_ops_access(). |
| `POST /admin/warehouse/unit/<id>/toggle-full` | `admin_warehouse_toggle_full` | Toggle StorageLocation.is_full. On mark-full: snapshots current item volume into snapshot_capacity. Returns JSON {success, is_full, snapshot_capacity}. _has_ops_access(). |
| `GET /admin/warehouse/search` | `admin_warehouse_search` | HTML partial. Params: q (text search), unit_id (scope to one unit). Returns item rows with inline "Select Unit" location picker and camera button for needs_new_photo items. `shift_id` param: when present, returns all items from sellers on that shift (no status filter); uses `warehouse_route_results.html` partial instead of `warehouse_search_results.html`. _has_ops_access(). |
| `GET /admin/warehouse/routes` | `admin_warehouse_routes` | HTML partial — shift chip list sorted most-recent-first, omitting shifts with zero seller items. `_has_ops_access()`. |
| `POST /admin/warehouse/bulk-move` | `admin_warehouse_bulk_move` | Bulk-move items between storage units. _has_ops_access(). |
| `GET /admin/warehouse/seller-search` | `admin_warehouse_seller_search` | JSON live seller search (name/email, min 2 chars, 15 rows) used by Log Item and rephoto seller pickers. `_has_warehouse_access()`. |
| `POST /admin/warehouse/log-item` | `admin_warehouse_log_item` | Log Item modal submit: photo + category (+ optional unit/zone) + seller (internal / existing / new proxy via `_create_proxy_seller_from_form`). Creates QC item, enqueues AI autofill. `_has_warehouse_access()`. |
| `GET /admin/warehouse/rephoto` | `admin_rephoto_page` | Re-photography main page: campaign banner, debounced search, Add-item button, capture modal. `_has_ops_access()`. |
| `GET /admin/warehouse/rephoto/search` | `admin_rephoto_search` | HTML partial. Param `q` — synonym-expanded (`REPHOTO_SYNONYMS`) ILIKE over description/long_description/category name. Excludes `sold` + tutorial sellers; un-reshot items first, then date_added desc; cap 40. `_has_ops_access()`. |
| `POST /admin/warehouse/rephoto/add-item` | `admin_rephoto_create_stub` | Add path: create stub item (internal seller, `is_quick_capture=True`, `pending_valuation`, category NULL). Returns JSON {success, item_id}. `_has_ops_access()`. |
| `POST /admin/warehouse/rephoto/<item_id>/photo` | `admin_rephoto_add_photo` | Accept ONE compressed photo (fields: photo, view=front\|side\|back). Server `_downscale_image()` (≤1600px, JPEG q85, EXIF stripped) → `photo_storage`, filename `rephoto_<item_id>_<view>_<uuid8>.jpg`. Creates ItemPhoto with captured_at/view/sort_order; never touches cover, status, or ai_generated_at. Returns JSON {success, photo_id, photo_url}. `_has_ops_access()`. |
| `POST /admin/warehouse/rephoto/<item_id>/details` | `admin_rephoto_set_details` | Add path only (`is_quick_capture` guard): required category + optional `subcategory_id` (must be a child of the category, else silently NULLed — same rule as edit_item) + seller (internal / existing / new proxy at payout_rate=50) + optional storage unit/zone (`storage_location_id`, `storage_row` validated via `_validate_storage_zone`). Enqueues AI autofill if the item has gallery photos. `_has_ops_access()`. |
| `POST /admin/warehouse/rephoto/photo/<photo_id>/delete` | `admin_rephoto_delete_photo` | Remove a just-captured photo (per-slot retake/remove). Guarded: only rows with `captured_at` set (campaign photos) — legacy photos 400. Deletes file via `photo_storage.delete_photo()`. `_has_ops_access()`. |
| `POST /admin/item/<id>/verify-photo` | `admin_item_verify_photo` | Clear needs_photo_verification flag. Returns JSON {success}. _has_ops_access(). |
| `GET /admin/ai/generate` | `admin_ai_generate_page` | AI autofill generation page. Stats (eligible count, last run), model selector, run form, live progress bar, history. Super admin only. |
| `POST /admin/ai/generate/run` | `admin_ai_generate_run` | Start background AI generation job (threading). Returns JSON {job_id}. Super admin only. |
| `POST /admin/ai/generate/cancel` | `admin_ai_generate_cancel` | Cancel a stuck/running job by job_id. Returns JSON {success}. Super admin only. |
| `GET /admin/ai/generate/status` | `admin_ai_generate_status` | Poll job progress. Returns JSON {done, total, completed, errors, results: [{item_id, title, price, retail_price, status}]}. Super admin only. |
| `GET /admin/ai/review` | `admin_ai_review_queue` | AI review queue page. Card grid of items with ai_review_pending=True. Slide-in modal for detail/edit/approve/discard. Super admin only. |
| `GET /admin/ai/item/<id>/detail` | `admin_ai_review_detail` | HTML partial (no layout) for AI review modal content. Gallery with set-as-cover and delete buttons, editable fields, retail/savings display, "Flag for new photo" checkbox. Super admin only. |
| `POST /admin/ai/item/<id>/approve` | `admin_ai_approve` | Write staged AI fields (ai_description→description, ai_long_description→long_description, ai_price→price, ai_retail_price→retail_price) to live fields. Set ai_approved=True, ai_review_pending=False. Accepts needs_new_photo=1 to flag photo replacement. Returns JSON. Super admin only. |
| `POST /admin/ai/item/<id>/discard` | `admin_ai_discard` | Clear all ai_* staged fields, set ai_review_pending=False. Returns JSON. Super admin only. |
| `POST /admin/ai/item/<id>/reset` | `admin_ai_reset` | Clear AI fields + ai_generated_at so the item re-enters the autofill-eligible queue. Returns JSON. Super admin only. |
| `GET /admin/ai/generate` | `admin_ai_generate_page` | Manual AI-autofill control page (counts, model selector, run button, run history). Renders `admin/ai_generate.html`. Standalone page (not linked in nav); the automatic `_ai_queue` worker is the primary path. The companion `/admin/ai/generate/run\|status\|cancel` JSON endpoints are also triggered from the items.html approval modal. |
| `GET /admin/ai/review` | `admin_ai_review_queue` | AI review queue — card grid of items with ai_review_pending=True. Renders `admin/ai_review.html`. The same review/approve/discard actions are also embedded in the items.html approval modal via the `/admin/ai/item/<id>/*` partials. |
| `POST /admin/ai/item/<id>/set-cover-photo` | `admin_ai_set_cover_photo` | Swap a gallery photo (ItemPhoto) to become the cover: sets item.photo_url to the gallery photo's URL, moves old cover into an ItemPhoto record. Returns JSON {success, cover_url}. Super admin only. |
| `GET/POST /admin/item/<id>/delete` | `admin_delete_item_direct` | Standalone item delete (also the items-tab drawer's Delete). POST with `modal=1` returns JSON `{success}` for fetch callers; otherwise flash+redirect. Deletes item + gallery photo rows. **Sends no seller notification** (by design — same for `admin_quick_capture_delete` / `crew_quick_capture_delete`). Admin only. |
| `POST /admin/item/<id>/delete-gallery-photo` | `admin_ai_delete_gallery_photo` | **EXISTS** (previously documented as phantom/removed). Remove a photo from an item in AI review — works for both seller-uploaded gallery photos and the AI-enhanced cover. Deleting the cover promotes another photo to cover so the listing is never imageless; blocks if it's the only photo; clears `ai_photo_enhanced` when an `ai_enhanced_*` file is removed; deletes the underlying file. Returns JSON {success}. Super admin only. Used by the "Delete" button in the AI review gallery. |
| `GET /admin/diag` | `admin_diag` | Diagnostic page showing DB table row counts. Super admin only. |
| `POST /admin/crew/shift/<shift_id>/set-overflow-truck` | `admin_set_overflow_truck` | Toggle overflow truck designation; green badge when active |
| `POST /admin/crew/shift/<shift_id>/toggle-reschedule-lock` | `admin_toggle_reschedule_lock` | Lock/unlock shift from appearing in seller reschedule grids |
| `GET /reschedule/<token>` | `seller_reschedule_get` | Token-gated reschedule page — no login required |
| `POST /reschedule/<token>` | `seller_reschedule_post` | Submit reschedule via token |
| `GET /seller/reschedule` | `seller_reschedule_auth_get` | Auth-gated reschedule page for logged-in sellers |
| `POST /seller/reschedule` | `seller_reschedule_auth_post` | Submit reschedule via auth session |

### Crew (Worker Accounts)
| Route | Function | Notes |
|---|---|---|
| `GET/POST /crew/apply` | `crew_apply` | Worker application form (role_pref field removed; sets 'both') |
| `GET /crew/pending` | `crew_pending` | Pending approval holding page |
| `GET /crew` | `crew_dashboard` | Approved worker portal — my schedule (upcoming only, links to role-appropriate view), shift history, today's shift banner, Open Intake button for organizers |
| `GET/POST /crew/availability` | `crew_availability` | Weekly availability + partner preferences section |
| `POST /crew/preferences` | `crew_save_preferences` | Save WorkerPreference records (replaces all existing) |
| `GET /crew/schedule/<week_id>` | `crew_schedule_week` | Full week calendar HTML partial (approved workers, published weeks only) |
| `GET /crew/shift/<shift_id>` | `crew_shift_view` | Phone-optimized mover shift view; blocks future shifts; shows truck-filtered stops with item photo strip; passes `destination_unit` (StorageLocation or None from truck_unit_plan) to template |
| `POST /crew/shift/<shift_id>/start` | `crew_shift_start` | Create ShiftRun; blocked for future shifts. SMSes all pending sellers on mover's truck after ShiftRun creation (Spec #9) |
| `POST /crew/shift/<shift_id>/stop/<pickup_id>/update` | `crew_shift_stop_update` | Mark stop completed/issue; writes picked_up_at on completion. On completion: revokes open RescheduleTokens, SMSes next seller. On issue: saves issue_type ('no_show'\|'other', defaults 'other'); no_show extends token TTL |
| `POST /crew/shift/<shift_id>/stop/<pickup_id>/revert` | `crew_shift_stop_revert` | Revert resolved stop to pending. Clears issue_type; preserves no_show_email_sent_at |
| `POST /crew/shift/<shift_id>/complete_retroactive` | `crew_shift_complete_retroactive` | One-click retroactive completion for past shifts |
| `POST /crew/shift/<shift_id>/end` | `crew_shift_end` | Close ShiftRun; sets ShiftAssignment.completed_at for driver; unconditional for past shifts. Confirmed path checks for unplaced items — blocks with error if any pickup items have `placement_status IS NULL`. |
| `GET /crew/shift/<shift_id>/placement` | `crew_shift_placement` | HTML partial: items for driver's truck needing placement. Loaded via fetch into shift view after stops are complete. |
| `POST /crew/item/<item_id>/place` | `crew_item_place` | Save item placement: writes `storage_location_id` + `storage_row` + sets `placement_status='placed'`. Returns JSON `{success}`. Worker guard. |
| `POST /crew/item/<item_id>/not_picked_up` | `crew_item_not_picked_up` | Mark item as not collected: sets `placement_status='not_picked_up'`. Returns JSON `{success}`. Worker guard. |
| `GET /crew/intake/<shift_id>` | `crew_intake_shift` | Organizer intake page; requires organizer role_on_shift; phone+desktop responsive |
| `POST /crew/intake/<shift_id>/item/<item_id>` | `crew_intake_submit` | Submit intake record for one item; creates IntakeRecord (append-only); optionally creates IntakeFlag; updates InventoryItem storage fields |
| `GET /crew/intake/search` | `crew_intake_search` | Search items by ID or seller name; returns HTML partial for fetch into #search-results |
| `POST /crew/intake/<shift_id>/unknown` | `crew_intake_log_unknown` | Log an unidentified item as IntakeFlag (flag_type='unknown') |
| `POST /crew/intake/<shift_id>/complete` | `crew_intake_complete` | Set ShiftAssignment.completed_at for organizer; gated on received_count >= total_items |
| `GET /crew/shift/<shift_id>/end-confirm` | `crew_shift_end_confirm` | End Shift confirmation page — shows stop summary + warning before final End Shift POST |
| `GET /crew/shift/<shift_id>/history` | `crew_shift_history` | Read-only completed shift item history for the worker's truck. Linked from crew dashboard Shift History cards. |
| `POST /crew/quick_capture` | `crew_quick_capture` | Create item from driver photo. Returns JSON {success, item_id}. Worker-approved guard. |
| `POST /crew/quick_capture/<id>/delete` | `crew_quick_capture_delete` | Hard delete own capture (captured_by_id guard, is_quick_capture guard, status IN pending_valuation/needs_info). |

### Delivery Routes (Spec D1)
Delivery vs pickup is determined at the truck level by the presence of `DeliveryStop` (delivery) vs `ShiftPickup` (pickup) records — `shift_type` is NOT a stored column. A truck cannot mix both (guarded in the add-stop and assign-seller routes).

| Route | Function | Notes |
|---|---|---|
| `GET /admin/ops/delivery-queue` | `admin_ops_delivery_queue` | HTML partial — paid BuyerOrders awaiting delivery assignment. `_has_ops_access()`. |
| `POST /admin/delivery/shift/<shift_id>/add-stop` | `admin_delivery_add_stop` | Add a DeliveryStop (buyer order) to a shift+truck. Blocks if the truck has ShiftPickups. |
| `POST /admin/delivery/shift/<shift_id>/remove-stop/<stop_id>` | `admin_delivery_remove_stop` | Remove a DeliveryStop. |
| `POST /admin/delivery/stop/<stop_id>/notify` | `admin_delivery_notify_stop` | Notify buyer of delivery window (per-stop). |
| `POST /admin/crew/shift/<shift_id>/notify-buyers` | `admin_shift_notify_buyers` | Bulk-send the "delivery scheduled" email to every unnotified buyer on the shift's delivery route. Flashes count, redirects to `admin_ops`. `_has_ops_access()`. |
| `GET /admin/ops/delivery-truck-detail` | `admin_ops_delivery_truck_detail` | HTML partial for delivery truck drawer. Params: shift_id, truck. |
| `GET /crew/delivery/<shift_id>` | `crew_delivery_view` | Phone-optimized mover delivery view (analogous to crew_shift_view). |
| `GET /crew/delivery/<shift_id>/stops-partial` | `crew_delivery_stops_partial` | Stop list partial for auto-refresh. |
| `POST /crew/delivery/<shift_id>/start` | `crew_delivery_start` | Create DeliveryRun. |
| `POST /crew/delivery/stop/<stop_id>/update` | `crew_delivery_stop_update` | Mark a delivery stop completed/issue; sets BuyerOrder.delivered_at on completion. |
| `POST /crew/delivery/<shift_id>/end` | `crew_delivery_end` | Close DeliveryRun. |

### Shift Scheduling (Admin)
| Route | Function | Notes |
|---|---|---|
| `GET /admin/schedule` | `admin_schedule_index` | List all ShiftWeeks + creation form. Super admin only. |
| `POST /admin/schedule/create` | `admin_schedule_create` | Create ShiftWeek + 14 Shift records from form. |
| `GET /admin/schedule/<week_id>` | `admin_schedule_week` | Schedule builder. Draft = dropdowns, published = badge + swap UI. |
| `POST /admin/schedule/<week_id>/optimize` | `admin_schedule_optimize` | Run greedy optimizer, clear + rewrite all ShiftAssignments. |
| `POST /admin/schedule/<week_id>/publish` | `admin_schedule_publish` | Set status=published, email all assigned workers. |
| `POST /admin/schedule/<week_id>/unpublish` | `admin_schedule_unpublish` | Return to draft. Silent. |
| `POST /admin/schedule/<week_id>/delete` | `admin_schedule_delete` | Delete draft ShiftWeek. Bulk SQL DELETE in FK order: IntakeFlags → IntakeRecords → ShiftPickups → ShiftRuns → ShiftAssignments → Shifts → ShiftWeek. Super admin only. |
| `POST /admin/schedule/shift/<shift_id>/update` | `admin_shift_update` | Save trucks count + all assignments for one shift. Redirects to `#shift-<id>`. |
| `POST /admin/schedule/shift/<shift_id>/swap` | `admin_shift_swap` | Replace one worker on a published shift. Sends swap emails. |

### Upload / QR
| Route | Function | Notes |
|---|---|---|
| `POST /api/upload_session/create` | `create_upload_session` | Create QR session token |
| `GET /api/upload_session/status` | `upload_session_status` | Poll for mobile uploads |
| `POST /api/photos/stage` | `stage_draft_photos` | Stage computer-picked photos to temp storage for draft saving (login required) |
| `POST /api/photo/upload_temp` | `api_photo_upload_temp` | Upload a single temp photo (mobile/QR flow) |
| `GET/POST /upload_from_phone` | `upload_from_phone[_post]` | Mobile upload page |
| `POST /upload_video_from_phone` | `upload_video_from_phone_post` | |

### API
| Route | Function | Notes |
|---|---|---|
| `POST /api/item/<id>/acknowledge_price_change` | `acknowledge_price_change` | Dismiss price-change badge |
| `GET /api/subcategories/<parent_id>` | `api_subcategories` | JSON list of subcategories for a parent category |
| `GET /health` | `health_check` | Render health check |

---

## Templates

```
layout.html                    — Base template (nav, footer, analytics)
index.html                     — Homepage (season-aware: dual/buyer_only/seller_only/off_season modes; frosted-glass hero mosaic, category chips, curated grid via _item_card.html; no waitlist form)
about.html
inventory.html                 — Shop front (category grid + item cards)
product.html                   — Product detail page (gallery, buy button)
dashboard.html                 — Seller dashboard (setup strip OR progress tracker, stats bar, item grid, referral card)
_seller_tracker.html           — Seller progress tracker partial (included by dashboard.html when setup_complete=True)
admin.html                     — Admin panel (bulk edit, mark sold, exports); Crew section has quick links + static "Crew" badge
admin_approve.html             — Item approval queue
admin_seller_panel.html        — Slide-out seller profile panel partial (no layout extends)
admin_sidebar.html             — Admin nav sidebar partial
login.html
register.html
signup.html                    — Waitlist signup
onboard.html                   — Multi-step seller onboarding wizard
onboard_complete_account.html
add_item.html                  — Item upload form (QR upload, photo carousel)
edit_item.html                 — Edit existing item
upload.html                    — Upload page
upload_from_phone.html
become_a_seller.html           — Seller landing page (interactive room calculator, out-of-season banner + disabled CTA when pickup_period_active=false)
confirm_pickup.html            — Legacy (route now redirects to /dashboard)
complete_profile.html          — Post-OAuth phone collection (new, minimal)
upgrade_pickup.html            — Upgrade from Free to Pro plan
account_settings.html
add_payment_method.html
reserve_success.html
item_success.html              — Post-purchase success
error.html
privacy_policy.html
refund_policy.html
terms_conditions.html
unsubscribe_confirm.html
unsubscribe_success.html
data_preview.html              — Admin data preview
director.html                  — Internal ops view
_category_grid.html            — Category grid partial
dashboard_pickup_form.html     — Pickup form partial
crew/apply.html                — Worker application form (no role_pref field; Mover/Organizer role cards)
crew/pending.html              — Application submitted / awaiting approval
crew/dashboard.html            — Worker portal: today's shift banner (time+in-progress aware), my schedule (upcoming, clickable rows, role-aware links), shift history (progress counter + completed cards), Open Intake button for organizers, Review Flags banner
crew/availability.html         — Weekly availability update + partner preferences (custom dropdown picker)
crew/_availability_grid.html   — Availability grid partial
crew/schedule_week_partial.html — Full crew calendar injected into modal; M/O abbreviations; Mover/Organizer legend
crew/shift.html                — Phone-optimized mover shift view: stops in stop_order; Navigate → button; stairs/elevator badge; 30s auto-refresh of #stop-list via stops_partial; pre-start/in-progress/past states; inline notes; retroactive complete; seller phone as tel: link per stop card; two-option issue-type picker (Seller wasn't home / Item or access problem) with hidden issue_type input; destination unit banner (📦 Drop off at: Unit X) from truck_unit_plan
crew/stops_partial.html        — HTML partial (no layout): stop list for current mover's truck; used by 30s setInterval auto-refresh fetch
crew/intake.html               — Organizer intake page: truck sections with received/total counters, item search, bottom-sheet modal for submission; responsive (960px+ two-column, 760px+ trucks grid)
(intake submission modal markup is inline in crew/intake.html — there is no separate crew/_intake_modal.html partial)
crew/intake_search_results.html — Partial rendered via fetch into #search-results; shows item photo, ID, seller name
admin/schedule_index.html      — Week list sorted ascending by date + 7×2 slot toggle creation form; Delete Week button (draft-only); Storage Units link
admin/schedule_week.html       — Schedule builder; Movers/Organizers labels; View Ops → link per shift card; Delete Week button in header (draft-only)
admin/shift_ops.html           — Ops page: issue alert banner, green mover panel, ordered stop lists + badges (stop#, access type, cap warning), Order Route + Notify Sellers buttons, Intake Summary
admin/ops.html                 — Main ops view (Admin UI Redesign). 3-zone layout: shift list, truck cards, unassigned panel. Storage chip buttons on truck cards: assigned = green chip with edit icon, unassigned = amber "+ Assign unit" chip. Unit picker modal (lazy-loaded via fetch into ops modal). Add Truck button visible in topbar. "Assign unit" footer button in truck card when no unit assigned (opens unit picker modal via data-action="open-unit-picker"). Stop assign forms catch 422 unit_required and open unit picker before retrying. Delivery shifts show a blue "Notify Buyers" button next to "Notify Sellers" (bulk delivery-scheduled email → `admin_shift_notify_buyers`). Truck drawer re-executes injected `<script>` (fixes `notifyDeliveryBuyer`); pickup-week chip shows a compact date range via the `pickup_week_range` filter.
admin/routes.html              — Route builder: unassigned sellers by cluster, shift capacity board, auto-assign, move/assign inline panels
admin/route_settings.html      — Capacity settings (raw cap, buffer%), time windows, Maps API key, per-category unit sizes; SMS Notifications section (kill switches + cron hour settings)
admin/settings.html            — Redesigned Settings tab (rendered by `admin_settings`). Route & capacity section now includes editable Warehouse latitude / longitude fields (saved via `save_route_settings`; default to WAREHOUSE_DEFAULT_* when blank).
admin/storage_index.html       — Storage location list with inline create + edit panels (super admin)
admin/storage_detail.html      — Items at a given storage location, filterable by status
seller/reschedule.html         — Full pickup-window week grid (Mon–Sun columns, AM/PM rows), prev/next week navigation, radio cards
seller/reschedule_confirm.html — Shared success/error page for reschedule flow (already_used, expired, underway, success, revoked: pickup already completed)
admin/shift_intake_log.html    — Full read-only intake log per shift with flag indicators and organizer notes
admin/intake_flagged.html      — Damaged/missing review queue; checkbox bulk selection + "Remove from Marketplace" bulk action
admin/payouts.html             — Payout reconciliation: Unpaid tab (seller cards with copy handle + Mark Paid), Paid history tab, CSV export
admin/needs_info.html          — **Removed.** QC items now surface via AI autofill pipeline (`/admin/ai/review`).
admin/approval_detail_partial.html — HTML partial (no layout) for approval modal: gallery track, item meta, long description, suggested price. Root div carries data-item-id, data-seller-id, data-suggested-price.
admin/crew_shift_board_partial.html — Shift board partial for Crew HQ week navigation
admin/ops_reorder.html         — Route reorder page: drag-and-drop stop ordering per shift/truck; Save Order button gets tutorial-highlight at step 7
admin/tutorial_welcome.html    — Standalone CD tutorial welcome/restart page (extends layout.html)
admin/tutorial_complete.html   — Tutorial completion page with CSS checkmark animation and 6-item checklist
admin/tutorial_overlay.html    — Overlay partial included in schedule_index, crew, ops, ops_reorder; context-appropriate content per step; tutorial-highlight CSS class pulses ring on target elements
admin/cd_settings.html         — CD Settings page: tutorial status, Retake/Continue/Start button
parents.html                   — Parents landing page
inventory_teaser.html          — Pre-launch blurred mosaic + email capture (shown when shop_teaser_mode='true')
cart.html                      — Cart page: line items, remove buttons, bundle/delivery summary, checkout button (Spec B)
checkout_delivery.html         — Buyer delivery address form (Spec A; cart-based). Google Places autocomplete + map preview + hidden lat/lng inputs; "Address confirmed" shown only when within delivery radius, out-of-area message otherwise. `.pac-container` z-index fix; `gm_authFailure` note. Client (Google Places) lat/lng preferred over server-side Nominatim geocode.
checkout_review.html           — Order review: subtotal, delivery fee, bundle/flexible discount, sales tax, total → Stripe (Spec A/B). Two-radio delivery picker (Standard / Flexible) replacing the old single checkbox; delivery date ranges via `delivery_window`.
claim_account.html             — Proxy-seller account claim page (token link)
admin/ops_delivery_queue_partial.html — Delivery queue partial: paid BuyerOrders awaiting delivery assignment (Spec D1)
admin/ops_delivery_truck_detail.html  — Delivery truck drawer partial (Spec D1)
admin/ops_truck_detail.html    — Pickup truck drawer partial (loaded into ops truck detail drawer)
admin/item_detail_partial.html — Generic admin item detail partial
admin/pv_detail_partial.html   — Photo-verification detail partial
crew/shift_end_confirm.html    — End Shift confirmation page: stop summary, warning, confirmed POST
crew/shift_history.html        — Read-only completed shift item history for mover's truck; linked from crew dashboard
crew/quick_capture_modal.html  — Quick Capture modal partial (included in crew/dashboard.html and crew/shift.html): getUserMedia rear camera, file-input fallback, notes field, full state reset on open
crew/shift_placement_partial.html — HTML partial (no layout): placement items list for driver's truck; modal with zone diagram for assigning unit + zone; "Not picked up" button; status chips (Placed / Not picked up / Needs location); Select Unit dropdown prefilled from truck_unit_plan; loaded via fetch into crew/shift.html after #placement-section becomes visible
admin/storage_audit.html       — **Replaced by warehouse.html.** Route 302-redirects to `/admin/warehouse`.
admin/storage_audit_results.html — **Replaced by warehouse_search_results.html.**
admin/warehouse.html           — Warehouse Floor main page. Unit card grid (battery bars, item counts, Full badges). Needs New Photo section (amber, collapsible, collapsed by default). Photo Verification Queue section (indigo, open by default). Global debounced search (300ms). "Search Items / Browse by Route" tab pills; #search-mode and #route-mode containers; lazy route fetch on tab switch. Header has "Re-Photograph Items" button (btn-outline) linking to /admin/warehouse/rephoto next to Log Item. Extends admin_layout.html.
admin/warehouse_unit_partial.html — Unit drawer partial (no layout). Item list with inline storage row autosave, toggle-full button, Log Item Here button. Battery bar macro included.
admin/ops_unit_picker_partial.html  — Unit picker card grid (no layout). Active StorageLocations with item counts, battery bars, full badges. Loaded lazily via fetch into ops unit picker modal.
admin/warehouse_routes_partial.html — Warehouse route browse shift chip list (no layout). Each chip: shift label, item count, data-shift-id.
admin/warehouse_route_results.html  — Warehouse route browse item results (no layout). Same structure as warehouse_search_results.html but shows all items from shift sellers (no status filter); green unit chip if already placed.
admin/warehouse_log_modal.html — Log Item 4-step modal partial (photo → category → location → seller). Three seller modes: Campus Swap internal, existing seller (live search via seller-search endpoint), new proxy seller (name + email/phone).
admin/rephoto.html             — Re-photography main page (extends admin_layout.html). Campaign banner ("started <date>"), autofocused debounced (300ms) search box fetching the search partial into #rp-results (stale-response guard), "+ Add an item that isn't listed" button (creates stub → opens capture modal in add mode). Includes rephoto_capture_modal.html.
admin/rephoto_search_results.html — Search results partial (no layout). Rows: cover thumbnail (placeholder tile if photo_url NULL), description, category, ✓ "Re-shot today" badge (item has ItemPhoto captured_at >= campaign start), Reshoot button with data-item-id / data-item-label / data-cover-url. Empty state: "Don't see it? Add it".
admin/rephoto_capture_modal.html — Full-screen guided three-shot capture modal (no layout; included by rephoto.html). Purpose-built — deliberately separate from _qc_camera_block.html. FRONT→SIDE→BACK state machine with auto-advance; per-photo canvas compression (≤1600px longest edge, JPEG q0.82); each shot uploads the instant it's taken as its own POST with 3× retry (0.5s/1.5s/3s backoff); per-slot status dots (grey/pulsing/green/red tap-to-retry) + retake/remove; Done blocked while uploading/failed, disabled at 0, nudge under 3; ✕ back-to-search deletes uploaded photos in reshoot mode; add-path trailing details step (category grid → subcategory pill row fetched from /api/subcategories/<id> (hidden when skip_subcategory, auto-selects a single sub) + optional tap-through location picker: bottom-sheet unit grid → spatial 6-zone grid with skip, full units tappable but tagged + 3-mode seller picker reusing seller-search endpoint). getUserMedia rear camera with file-input capture=environment fallback; HEIC normalized via canvas. NOTE: style.css sets `input {width:100%; padding:12px 16px}` globally — any radio/checkbox in a fetch-free modal must pin explicit width/height (this bit both this modal and warehouse_log_modal).
admin/warehouse_search_results.html — Search results partial (no layout). Item rows with "Select Unit" inline picker that expands below the row, camera button for needs_new_photo items. Location autosave via existing POST /admin/item/<id>/set_location. Green unit chip shown when item already has storage_location_id set (instead of showing nothing).
admin/ai_generate.html         — Manual AI-autofill control page: eligible count, last-run stats, model selector, Run button, live progress, run history. Standalone (not nav-linked); the automatic _ai_queue worker is the primary generation path.
admin/ai_review.html           — AI review queue: card grid of items with ai_review_pending=True; opens the AI review modal. Same actions are embedded in the items.html approval modal.
admin/needs_info.html          — Quick-capture completion queue (is_quick_capture items in pending_valuation/needs_info). Reached via the admin_request_info redirect.
admin/ai_review_detail_partial.html — AI review modal content (no layout). Gallery carousel with "★ Set as cover" and "Delete" buttons on non-cover slides. Editable title, description, price, retail_price inputs. Savings callout display. "Flag for new photo" checkbox. Approve and Discard buttons.
_battery_macro.html            — Reusable Jinja2 macro `battery_bar(pct, is_full)`. Renders capacity battery bar: green 75–100%, amber 40–74%, red <40%, striped dark-red >100%, grey if pct is None. Included in warehouse.html and warehouse_unit_partial.html.
_qc_camera_block.html          — Reusable camera capture block (getUserMedia rear-camera + file-input fallback + thumbnail preview). Included in crew/quick_capture_modal.html and warehouse log/replace-photo modals.
```

---

## Business Logic

### Item Status Lifecycle
```
pending_valuation → (admin approves, sets price + ai_approved) → available → (sold) → sold
                  → (admin rejects) → rejected
                  → (admin requests info) → needs_info → (seller resubmits) → pending_valuation
                                                       → (admin cancels request) → pending_valuation

NOTE: the intermediate 'approved' status is vestigial — it is in the allowed-values list but is never
assigned by any route. Approval sets status DIRECTLY to 'available' (admin_approve_unified). The
InventoryItem statuses actually written in code are: pending_valuation, needs_info, available, sold, rejected.
(The 'pending'/'paid' statuses belong to Order; 'draft'/'published' to ShiftWeek; 'completed' to ShiftRun/stops.)

Operational milestones (don't change status):
  picked_up_at         — item collected from seller
  arrived_at_store_at  — item physically arrived at warehouse
  storage_location_id  — set by organizer at intake (which unit the item is in)
  storage_row          — set by organizer at intake (aisle/row within unit)

Admin can set status='rejected' via the damaged/missing queue to remove flagged items from the marketplace.
```

### Seller Progress Tracker
Account-level pipeline shown on `/dashboard` in place of the setup strip once setup is complete.

- `setup_complete` (bool, computed in `dashboard()` route) — True when `phone`, `pickup_week`, `has_pickup_location`, `payout_method`, and `payout_handle` are all set.
- When `setup_complete=False`: setup strip shown (Phone / Pickup week & address / Payout info chips).
- When `setup_complete=True` and `current_user.is_seller`: `_seller_tracker.html` partial included instead. Never both simultaneously.
- `_compute_seller_tracker(seller, items)` — helper in `app.py`. One `ShiftPickup` query total. Returns `{stages, active_message, interrupt}`.

Six stages (account-level, not per-item):
1. Submitted — has at least one non-rejected item
2. Approved — at least one item not in pending/needs_info/rejected
3. Scheduled — ShiftPickup exists with status != 'issue'
4. Picked Up — any item has `picked_up_at`
5. At Campus Swap — any item has `arrived_at_store_at`
6. In the Shop — `shop_teaser_mode != 'true'` AND any item `available` or `sold`

Active stage = first False condition. Interrupt callout (amber, below message) for `needs_info` items or pickup issue stops.

### Payout Rate / Referral Program
Payout is a flat stored percentage on `User.payout_rate`. The old two-tier Pro/Free fee model is gone.

⚠️ **The automatic referral-driven escalation described in earlier versions of this doc is NOT implemented.** Verified against current code:
- No route or helper ever creates a `Referral` record (`Referral(...)` is never instantiated).
- `referred_by_id` is never written.
- There is no `calculate_payout_rate`, `apply_referral_code`, or `maybe_confirm_referral_for_seller` function.
- The `referral_base_rate` / `referral_signup_bonus` / `referral_max_rate` / `referral_program_active` AppSetting keys are never read.

What actually exists:
- `User.payout_rate` (Integer). Model default 50. Proxy-seller and tutorial-seed creation set it to 20 explicitly; regular `register()` does not set it (falls to the model default).
- Payout amount: `item.price * (seller.payout_rate / 100)`. Used in `/admin/payouts` and exports.
- `User.referral_code` is generated by `_gen_referral_code()` only at proxy-seller creation. The `Referral` model and `referred_by_id` column exist but are dormant.
- `collection_method` field is retained on `InventoryItem` but does not drive payout.
- `/upgrade_pickup` and `/upgrade_checkout` routes left in place (return redirect) to avoid broken bookmarks. UI entry points removed. The $15 Pro fee is gone; `has_paid` retained harmlessly.
- Pickup week is set per-user (`User.pickup_week`) during onboarding (optional, skippable) or from the dashboard modal at any time.

### Admin Roles
- `is_admin`: access to admin panel (inventory, approvals, free-tier management)
- `is_super_admin`: full access (user management, database reset, mass email, category management, schedule creation, storage unit management)
- `is_campus_director`: access to ops panel tabs (Ops, Crew, Schedule) via `_has_ops_access()` guard. NOT `is_admin`. Cannot access Settings, User Management, Exports, or item approval. Role-switcher pill in nav lets CD toggle between seller dashboard and admin ops without logging out. Session key `cd_view` ('seller'|'admin') controls which context is shown.
- Pre-approved via `AdminEmail` table — role assigned at signup

### Campus Director Tutorial
New CDs without a completed tutorial are auto-redirected to `/admin/tutorial`. Tutorial is a 9-step interactive walkthrough using sandboxed fixture data.

- `seed_tutorial_fixtures()` — idempotent helper. Creates/resets three fixture workers (Sam Torres → pending, Riley Chen → approved, Casey Brooks → seller with ShiftPickup) and a `ShiftWeek` with `is_tutorial=True`. Called on every tutorial start/retake.
- Tutorial gate uses DB (`TutorialSession.step`, `completed_at`, `is_retaking`), not session — cookie-unreliable after POST/redirect cycles.
- `session['tutorial_active']` cached for template rendering only; all action-route guards read from DB.
- Tutorial-mode guards: `admin_crew_reject` blocked; `admin_crew_remove` hard-blocked for `is_tutorial_user` workers; `admin_schedule_create` creates 1-truck shift and redirects to schedule_index; `admin_routes_assign_seller` sets step=6 when all tutorial sellers assigned; `admin_shift_notify_sellers` disabled until step 8, bumps to 9 when done.
- `is_tutorial_user=True` workers are excluded from all production Crew HQ queries, optimizer runs, and ops assignment dropdowns.
- `is_tutorial=True` ShiftWeek is excluded from all production shift lists, ops panel, and route planning.

### Quick Capture Flow
Movers can photograph found/donated/spot-consigned items in the field.

Entry points:
- `/crew` dashboard — Quick Capture button, no shift context; seller defaults to Campus Swap internal account
- `/crew/shift/<id>` shift view — Quick Capture button in header; seller auto-populates from active stop

Flow: camera modal → photo + optional note → select seller → Save → `InventoryItem` created with `is_quick_capture=True`, `status='pending_valuation'`, `picked_up_at` set to now.

QC items (`is_quick_capture=True`, `status=pending_valuation`) are eligible for AI autofill (`ai_generated_at IS NULL`). They surface in the AI review queue after the next generation run. There is no longer a dedicated admin queue for QC items — the AI autofill pipeline handles them.

Category is now collected at crew quick capture (required in UI, null-safe on backend): category_id is sent with the POST to `/crew/quick_capture`.

Delete: mover can hard-delete own captures (photo + DB) while status is `pending_valuation` or `needs_info`. Admin can hard-delete any QC item via standard item delete.

QC items are excluded from: standard approval queue, approval digest email, pending-items counts in admin stats bar.

### Warehouse Re-Photography (rephoto)
Search-first guided three-shot (front/side/back) capture flow for campus directors walking the
warehouse — `/admin/warehouse/rephoto`, all routes `_has_ops_access()`.

- **Why search-first:** the crew reorganized every storage unit (grouped by category), so the
  warehouse tab's unit→item mapping is stale — browsing by unit can't find the item in hand.
- `REPHOTO_SYNONYMS` (module-level dict in `app.py`) — one-level synonym expansion per query token
  (couch → sofa/futon/loveseat/…); non-key tokens searched literally. ILIKE over
  `description`, `long_description`, and joined `InventoryCategory.name`.
- `_downscale_image(file_obj, max_edge=1600, quality=85)` — server-side Pillow bound (resize longest
  edge, re-encode JPEG, strips EXIF via re-encode after exif_transpose). Defense-in-depth behind the
  client's canvas compression (≤1600px, JPEG q0.82); covers the file-input fallback path.
- `_rephoto_campaign_start_utc()` / `_rephoto_reshot_item_ids(item_ids)` — campaign boundary +
  single-query ✓-badge set for a result page.
- `_create_proxy_seller_from_form(form, proxy_note)` — extracted from `admin_warehouse_log_item`;
  shared proxy-seller creation (payout_rate=50, `is_proxy_account=True`, flushed not committed) used
  by both Log Item and the rephoto details step.
- Reliability contract: each photo uploads the instant it is taken as its own multipart POST
  (never batched), client retries 3× (0.5s/1.5s/3s), red tap-to-retry dot on final failure, Done
  blocked while any upload is pending/failed.
- Photos land as `ItemPhoto(captured_at=utcnow, view, sort_order=max+1, is_hidden=False)` with
  filename `rephoto_<item_id>_<view>_<uuid8>.jpg` — the dated batch a later post-process pass
  (background removal, hide pre-campaign photos, promote front to cover) will operate on. This flow
  itself NEVER touches `item.photo_url` (cover), `item.status`, or `item.ai_generated_at`.
- Add path: stub created immediately (internal seller, `is_quick_capture=True`,
  `pending_valuation`, category NULL) → capture 3 → details step (category required + optional
  storage unit/zone via tap-through picker + seller). Details save enqueues `_ai_queue` directly —
  stubs have no cover so the startup requeue (which filters on `photo_url`) would never see them;
  the AI text phase reads gallery photos. Abandoned stubs stay internal-owned pending items (accepted).
- Location picker (2026-07-09 revision): the original spec left storage NULL ("units being
  reorganized separately") — reversed. Details step has a dashed "Select unit & spot" chip →
  bottom-sheet grid of active StorageLocations (full ones tappable, tagged "Full") → spatial
  6-zone grid (back/middle/front × left/right, `_VALID_STORAGE_ZONES`) with a skip option.
  Optional — Save works without it.

### AI Autofill Pipeline
When an item is submitted, its id is enqueued to an in-process `_ai_queue` (`queue.Queue`) drained by a single daemon thread (`_ai_queue_worker`) — items process one at a time to avoid the multi-item crash that the old batch run caused. The seller never waits on it.

- `_process_single_item_ai(app, item)` runs two phases: (1) OpenAI `gpt-image-1` background-replacement photo enhancement (skipped if `OPENAI_API_KEY` absent; failures are caught and logged, text still proceeds), (2) Anthropic vision+text generation that writes `ai_description`, `ai_long_description`, `ai_price`, `ai_retail_price` and sets `ai_review_pending=True`.
- **Success sentinel is `ai_description IS NOT NULL`** — not `ai_generated_at`. Retries are bounded by `ai_retry_count` (hard stop at `_AI_MAX_RETRIES = 3`). On a failure under the cap, `ai_generated_at` is reset to NULL so the startup requeue retries it; at the cap it's left set and the item is given up on.
- `_ai_startup_requeue()` runs ~5s after boot and re-enqueues every item with `ai_description IS NULL AND ai_retry_count < 3` and a photo — recovering items orphaned by a crash/restart mid-generation.
- Admin approval (`/admin/item/<id>/approve-unified`) copies the staged `ai_*` fields onto the live fields, sets `ai_approved=True` and `status='available'`. The approval modal's Approve button is always enabled — the "AI processing…" banner is informational only.

### Cart, Delivery Fees & Bundle (Spec A + B)
- **Cart:** one `Cart` per logged-in user or per guest `cart_token` (session). Guest carts merge into the user's cart on login/register (`_merge_guest_cart_into_user`). Adding an item creates a `CartItem`. An item is "held" (unavailable to others) only during active checkout — while some cart's `checkout_started_at` (set at "Proceed to Payment") is within `checkout_hold_minutes` (default 15). Expiry is computed at read time, no cron. Merely leaving an item in a cart no longer holds it (the old `cart_hold_minutes` membership hold is gone).
- **Delivery fee:** zone-based (Spec A). `calculate_delivery_zone(distance_miles)` maps distance to a zone via `delivery_zone_boundaries`; beyond the final boundary (~20 mi) delivery is unavailable. Fee comes from `delivery_zone_fees`.
- **Sales tax:** `compute_sales_tax(item_price)` — `sales_tax_rate` (default 7.25%) applied to item price only, never to the delivery fee.
- **Bundle & Save:** when cart `item_count >= bundle_min_items` (default 2), `delivery_fee` is set to 0 and `bundle_free_delivery=True`.
- **Flexible delivery:** optional discount applied through a Stripe Coupon (`stripe_flexible_coupon_id`), not a negative line item.
- **Order flow:** `checkout_review` creates a pending `Order` (status `'pending'`) before redirecting to Stripe. Items are marked sold ONLY in the Stripe webhook (source of truth). A double-sale guard sets `Order.has_conflict` / raises a `SellerAlert` if an item was already sold. Legacy per-item checkout URLs are preserved as redirects into the cart flow.

### Worker / Crew Accounts
- Users apply at `/crew/apply` — sets `worker_status='pending'`, creates `WorkerApplication`
- Admin approves/rejects at `/admin/crew/approve|reject/<user_id>`
- Approved workers (`is_worker=True`, `worker_status='approved'`) access `/crew` dashboard
- Workers submit weekly availability via `/crew/availability` → stored in `WorkerAvailability`
- All workers are treated as 'both' roles — actual role gating uses `ShiftAssignment.role_on_shift`, not `User.worker_role`

### Organizer Intake Flow
1. Admin assigns a storage unit to each truck via ops page (writes to `Shift.truck_unit_plan`; syncs to `ShiftPickup.storage_location_id`)
2. Organizer opens intake page (`/crew/intake/<shift_id>`) — sees trucks with pending pickups grouped by truck
3. For each item: search by ID or seller name, open modal, confirm storage row, optionally flag as damaged/missing
4. Submission creates `IntakeRecord` (append-only) and updates `InventoryItem.storage_location_id / storage_row`
5. Organizer taps "End Intake" when `received_count >= total_items` — sets `ShiftAssignment.completed_at`
6. Admin reviews flagged items at `/admin/intake/flagged` — can bulk-reject (status='rejected') or resolve individually

### AppSetting Flags
- `reserve_only_mode`: 'true'/'false' — hides buy buttons, shows reserve only
- `pickup_period_active`: 'true'/'false' — enables pickup scheduling
- `current_store`: store name for display
- `store_open_date`: date string shown on inventory banner when store not yet open
- `shop_teaser_mode`: 'true' → `/inventory` shows blurred mosaic + email capture (pre-launch); 'false'/absent → normal shop
- `warehouse_lat` / `warehouse_lng`: warehouse coordinates — origin for delivery distance/zone calculation. Editable in Settings → Route & capacity (`save_route_settings`); fall back to `WAREHOUSE_DEFAULT_LAT`/`WAREHOUSE_DEFAULT_LNG` (515 S Greensboro St, Carrboro NC) when blank (fail-open)
- `delivery_zone_boundaries` / `delivery_zone_fees`: zone-based delivery pricing (Spec A). Replaced the old `delivery_radius_miles` radius model. Beyond the final boundary (≈20 mi), delivery is unavailable.
- `sales_tax_rate`: sales tax applied to item price only (never to delivery fee). Default 7.25%.
- `flexible_delivery_discount` / `stripe_flexible_coupon_id`: flexible-delivery discount applied via a Stripe Coupon (not a negative line item)
- `checkout_hold_minutes`: active-checkout hold window (default 15). An item is held against other buyers only while a cart's `checkout_started_at` is within this window (lazy, read-time expiry). Replaces the membership-based use of `cart_hold_minutes`.
- `cart_hold_minutes`: legacy — no longer the hold basis (superseded by `checkout_hold_minutes`)
- `bundle_min_items`: cart size (default 2) at which delivery becomes free (Bundle & Save)

### Shop / Inventory Visibility
The `/inventory` route (and the `?ajax=1` infinite scroll endpoint) applies these filters:
- `ai_approved == True` — only items that have been through AI review appear to buyers
- `needs_new_photo == False` — items flagged for photo replacement are hidden until the photo is verified
- `status != 'rejected'`, `price > 0`
- `storage_location_id IS NOT NULL` — items must have a storage unit assigned before they appear in the shop

**Infinite scroll:** Replaced pagination with IntersectionObserver + `?ajax=1` endpoint. A sentinel `<div>` at the bottom of the item grid triggers the next page load 200px before it enters the viewport. Item count removed from the public shop header.

**Retail price + savings callout:** When `item.retail_price` is set, inventory cards and the product detail page show a callout like "~$200 retail · 40% off". The retail price is set at AI approve time by copying `ai_retail_price` to `retail_price`. The AI floors retail price so savings always appear ≥40%.

**Shop teaser mode:** When AppSetting `shop_teaser_mode == 'true'`, `/inventory` renders `inventory_teaser.html` (blurred mosaic + email capture) instead of the shop. The toggle is on the Admin Settings page.

### Stripe Integration
- Cart checkout: Checkout Session created from `checkout_review` (with delivery fee, tax, optional flexible-delivery coupon). A pending `Order` is created before redirect.
- Single-item purchase: `buy_item` Checkout Session.
- Payment method save: SetupIntent (legacy deferred-charge path).
- Stripe webhook at `/webhook` is the source of truth for all post-payment state: it marks items sold, sets `Order.status='paid'`, and handles both cart orders (metadata `type='cart_order'`, webhook CASE 0) and legacy single-item purchases (CASE 1). Idempotency via `stripe_checkout_session_id`; double-sale guard via `has_conflict` / `SellerAlert`.
- The old $15 Pro pickup fee is gone (`/upgrade_*` routes return redirects).

---

## Key Patterns

1. **Server-rendered only** — no React/Vue. All state changes go through form POST → redirect. Use Vanilla JS for interactivity only. Exception: fetch POST for auto-save actions that would cause disruptive page reloads (e.g., destination unit dropdown on ops page) — route still does all DB writes server-side, returns JSON.

2. **Flash messages** — use `flash('message', 'success'|'error'|'info')` for user feedback. Rendered in `layout.html`.

3. **Auth guards** — `@login_required` for user routes. Admin routes check `current_user.is_admin`. Super admin routes use `@require_super_admin` decorator. Crew routes use `require_crew()` helper (not a decorator). Ops/crew/schedule routes accessible to both admins and campus directors use `_has_ops_access()` (returns True for `is_admin` OR `is_campus_director`). Role-specific crew gating (mover vs. organizer) checks `ShiftAssignment.role_on_shift` inside each route — not `User.worker_role`.

4. **New routes** — add to `app.py` following existing patterns. Group logically near related routes.

5. **New templates** — extend `layout.html`. Use CSS variables (never hardcode colors). Use `.card`, `.btn-primary`, `.btn-outline` classes.

6. **Database changes** — always add a Flask-Migrate migration (`flask db migrate -m "description"`). Never modify the DB directly.

7. **Photo uploads** — use `validate_file_upload()` helper. Store to `/var/data/` (Render) or `static/uploads/` (local). Serve via `url_for('uploaded_file', filename=...)`.

8. **Email** — use `send_email(to, subject, html)`. Wrap HTML with `wrap_email_template()` for consistent styling. `wrap_email_template()` is **idempotent** — if the content is already a full `<!DOCTYPE>` document it is returned unchanged (fixes the double-logo bug where a caller pre-wraps and `send_email` wraps again). The header logo is `faviconNew.png` (PNG, not SVG — clients block SVG), built from the public base URL (`APP_BASE_URL` / `BASE_URL` / `https://usecampusswap.com`), never the request host. Buyer order confirmation emails (`_send_buyer_order_confirmation`) embed item photo thumbnails via `_email_photo_url()` (an absolute, email-safe image URL that prefers a direct S3/CDN URL with no redirect, then the external `uploaded_file` route, then `BASE_URL/uploads`).

9. **SellerAlert system** — reusable alert model for dashboard notifications. Types: `needs_info` (item-specific, from approval queue), `pickup_reminder` (account-level, from nudge), `preset` / `custom` (from seller profile panel). Alerts auto-resolve when the seller takes the required action (resubmit item, select pickup week, etc.).

10. **Seller profile panel** — slide-out drawer (480px right-side) fetched as HTML partial via `/admin/seller/<id>/panel`. Used on admin.html and admin_approve.html. Triggered by clicking seller names.

11. **Constants** — shared constants in `constants.py`: `VIDEO_REQUIRED_CATEGORIES`, `category_requires_video()`, `PICKUP_WEEKS`, `PICKUP_WEEK_DATE_RANGES`, `PICKUP_TIME_OPTIONS`. Import into `app.py` and use via context processor for templates. The `pickup_week_range` Jinja filter (`pickup_week_range_filter` in `app.py`) maps a pickup-week key (e.g. `'week9'`) to a compact date range (e.g. `'Jun 22–28'`) from `PICKUP_WEEK_DATE_RANGES`; used on the ops unassigned-seller chips.

12. **Shift optimizer** — `_run_optimizer(week)` in `app.py`. Pre-caches all worker availability at the start (no DB queries mid-loop). Tracks load and same-day assignments in-memory. Sort key: `(already_doubled, flexible_for_other_slot, load, abs(role_imbalance), avoid_conflict, not preferred_match)`. `truck_number` derived from slot index position (slot 0–1 → truck 1, etc.). `assigned_by_id=NULL` on ShiftAssignment means optimizer-assigned; non-NULL means manual.

13. **Cron jobs** — digest email triggered via POST `/admin/digest/trigger` with `X-Cron-Secret` header or `?secret=` query param matching `DIGEST_CRON_SECRET` env var. Set up as Render cron job.

14. **Eastern timezone helpers** — `_now_eastern()` and `_today_eastern()` in `app.py` use `zoneinfo.ZoneInfo('America/New_York')`. Use these for all "what day/time is it right now" logic. Never use `datetime.utcnow()` for date comparisons or slot-preference logic. Timestamps stored in DB remain UTC (SQLAlchemy default).

15. **data-* attributes for JS data passing** — never pass structured data to JS event handlers via inline `tojson` in onclick attributes (breaks on special characters in strings). Use `data-*` attributes on the element and read via `element.dataset.*` in the handler.

17. **`innerHTML` injection discards `<script>` tags** — browsers silently drop `<script>` elements added via `innerHTML`. After any `element.innerHTML = html` assignment that includes scripts (e.g., fetch-loaded partials), re-create each script node explicitly:
    ```javascript
    container.innerHTML = html;
    container.querySelectorAll('script').forEach(function(orig) {
      const s = document.createElement('script');
      s.textContent = orig.textContent;
      orig.parentNode.replaceChild(s, orig);
    });
    ```
    This pattern is used in `crew/shift.html` after loading `shift_placement_partial.html`.

18. **CSRF in inline `<script>` blocks** — `layout.html` does NOT include a `<meta name="csrf-token">` tag. Calling `document.querySelector('meta[name=csrf-token]').content` returns `null` and throws silently. Always render the token into a JS variable using Jinja2: `const _csrf = '{{ csrf_token() }}';` at the top of the template's `<script>` block.

    **Nav badge context processor:** the context processor is `inject_qc_pending_count` (there is no `inject_nav_counts`). It injects three values: `qc_pending_count` (quick-capture items in pending_valuation/needs_info), `ai_review_pending_count` (items with `ai_review_pending=True`), and `items_pending_total` (approval-queue count + ai_review count).

19. **openpyxl bulk import** — xlsx files have 1,048,576 rows by default. Always open with `read_only=True, data_only=True` to stream rows rather than load the full sheet into RAM. Also gate on a 2 MB file size check before loading. See `admin_storage_import` in `app.py`.

20. **Startup `db.create_all()`** — runs unconditionally at every app startup (not just when `DATABASE_URL` is absent). Required so a fresh Postgres database gets all tables on first deploy. `db.session.rollback()` is called in both seed exception handlers to prevent Postgres transaction abort cascade (one failed query aborts the entire session until an explicit rollback).

16. **Referral helpers** — ⚠️ STALE. Earlier docs described `generate_unique_referral_code`, `apply_referral_code`, `maybe_confirm_referral_for_seller`, and `calculate_payout_rate`. **None of these functions exist in the codebase.** The only referral-related helper is `_gen_referral_code()` (8-char code, used at proxy-seller creation). The automatic referral-confirmation / payout-escalation flow is not implemented (see Payout Rate / Referral Program above).

21. **422 gate for prerequisite actions** — `admin_shift_assign_seller` returns 422 `{error: 'unit_required', truck_number: N}` when the first stop is being added to a truck that has no unit assigned in `truck_unit_plan`. The frontend JS catches the 422 status code to distinguish "you need to do something first, then retry" from a 400 bad-request. After the unit picker modal completes and a unit is assigned, the form is retried automatically.

22. **Delivery helpers & warehouse origin** — `WAREHOUSE_DEFAULT_LAT='35.9030324'` / `WAREHOUSE_DEFAULT_LNG='-79.0709049'` (module constants, 515 S Greensboro St, Carrboro NC) are the default delivery origin used whenever the `warehouse_lat`/`warehouse_lng` AppSettings are unset. `_delivery_window(ref_date=None)` returns `{standard, flexible, friday, saturday, flex_end}` — deliveries run the upcoming Fri/Sat (Mon–Thu → this week, Fri–Sun → next week); used in the confirmation email, `item_success`, and `checkout_review`. `_send_delivery_scheduled_email(stop)` builds + sends one delivery-scheduled email and sets `notified_at` (caller commits); shared by `admin_delivery_notify_stop` (per-stop) and `admin_shift_notify_buyers` (bulk). `_email_photo_url(filename)` returns an absolute, email-safe image URL (see pattern #8).

16. **Bulk SQL DELETE for cascade deletes** — when deleting a parent record that has deep FK chains (ShiftWeek → Shifts → Assignments + Pickups → IntakeRecords → IntakeFlags), use `db.session.execute(delete(Model).where(...))` in FK dependency order rather than ORM cascade. ORM cascade on deeply nested relations causes StaleDataError when the session's identity map is invalidated mid-delete.

---

## Feature Spec Workflow

When Claude Desktop generates a feature spec, save it as a `.md` file in the project root named descriptively (e.g., `feature_buyer_reviews.md`). The spec should include:

- **Goal** — what problem it solves
- **UI/UX flow** — step by step user journey
- **New routes** — HTTP method, path, function name, what it does
- **Model changes** — new fields or tables (include migration note)
- **Template changes** — which templates to add/modify
- **Business logic** — edge cases, validation rules
- **Constraints** — what NOT to touch (existing logic to preserve)
