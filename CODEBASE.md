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
referral_code (String 8, unique, nullable) — 8-char uppercase alphanumeric, generated at account creation
referred_by_id (FK → User, nullable) — who gave them the code
payout_rate (Integer, default 20) — stored percentage; updated when referrals are confirmed
has_paid_boost (Boolean, default False, server_default='0') — one-time $15 payout boost purchased flag; reset each season

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
sold_at, payout_sent (bool)
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
```

### InventoryCategory
```
id, name, image_url, count_in_stock
default_unit_size (Float, default 1.0, nullable) — truck space this category consumes; seeded for 12 furniture types
items → [InventoryItem]
```

### ItemPhoto
```
id, item_id, photo_url
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
Current keys in use: 'reserve_only_mode', 'pickup_period_active', 'current_store', 'store_open_date',
'crew_applications_open', 'crew_allowed_email_domain', 'availability_deadline_day',
'drivers_per_truck', 'organizers_per_truck' (unused for capacity — superseded by stagger formula), 'max_trucks_per_shift',
'shifts_required' (minimum shifts for season payout, default '10')
Referral program keys (defaults): 'referral_base_rate' ('20'), 'referral_signup_bonus' ('10'),
'referral_bonus_per_referral' ('10'), 'referral_max_rate' ('100'), 'referral_program_active' ('true')
Delivery keys: 'warehouse_lat', 'warehouse_lng', 'delivery_radius_miles' (default '50')
Teaser key: 'shop_teaser_mode' ('true' → show pre-launch teaser on /inventory; absent/'false' → normal shop)
Route planning keys: 'truck_raw_capacity' ('18'), 'truck_capacity_buffer_pct' ('10'),
  'route_am_window' ('9am–1pm'), 'route_pm_window' ('1pm–5pm'), 'maps_static_api_key' ('')
```

### ShopNotifySignup
```
Email capture for pre-launch Shop Drop teaser. No UNIQUE constraint — duplicates silently accepted.
id, email (String 120), created_at (DateTime), ip_address (String 45, nullable)
```

### BuyerOrder
```
Delivery details for each completed item purchase. One record per sold item.
id, item_id (FK → InventoryItem, unique), buyer_email (String 120)
delivery_address (String 300), delivery_lat (Float, nullable), delivery_lng (Float, nullable)
stripe_session_id (String 120, nullable), created_at (DateTime)
Relationships: item → InventoryItem (backref buyer_order, uselist=False)
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
id, week_start (Date, unique — Monday of the work week)
status: 'draft' | 'published'
created_at, created_by_id (FK → User, nullable)
Relationships: shifts → [Shift], created_by → User
```

### Shift
```
One AM or PM block per day within a ShiftWeek.
id, week_id (FK), day_of_week ('mon'|'tue'|'wed'|'thu'|'fri'|'sat'|'sun')
slot: 'am' | 'pm'
trucks (Integer, default 2), is_active (Boolean, default True)
created_at
truck_unit_plan (Text, nullable) — JSON dict {"truck_num": storage_location_id} — planned destination per truck;
  written by admin before pickups exist; synced to ShiftPickup.storage_location_id when pickups are added
sellers_notified (Boolean, default False) — True once admin has sent pickup confirmation emails for this shift
Relationships: week → ShiftWeek, assignments → [ShiftAssignment]
Properties: label, sort_key, drivers_needed, organizers_needed,
            driver_assignments, organizer_assignments, is_fully_staffed, status_label
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
created_at, created_by_id (FK → User)
Unique constraint: (shift_id, seller_id) — seller globally unique across all shifts
Relationships: shift → Shift, seller → User (backref: shift_pickups), created_by → User,
               storage_location → StorageLocation
```

### ShiftRun
```
Shift-level execution state. Created when mover taps Start Shift.
id, shift_id (FK → Shift, unique), started_at, started_by_id (FK → User)
ended_at (DateTime, nullable), status: 'in_progress' | 'completed'
Relationships: shift → Shift (backref: run, uselist=False), started_by → User
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

### StorageLocation
```
A physical storage unit or warehouse where items are held after pickup.
id, name (String), address (String)
location_note (Text, nullable) — directions, access code, landmarks
capacity_note (Text, nullable) — e.g. "Unit 14B, max ~80 items"
is_active (Boolean, default True), is_full (Boolean, default False)
lat (Float, nullable), lng (Float, nullable) — coordinates for nearest-neighbor stop ordering
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
flag_type: 'damaged' | 'missing' | 'unknown'
description (Text, nullable), resolved (Boolean, default False)
resolved_at (DateTime, nullable), resolved_by_id (FK → User, nullable)
resolution_note (Text, nullable), created_at
Relationships: item → InventoryItem, shift → Shift, intake_record → IntakeRecord,
               organizer → User, resolved_by → User
```

---

## Route Map (`app.py` — 10,000+ lines)

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
| `GET /uploads/<filename>` | `uploaded_file` | Serve uploaded files |
| `GET /unsubscribe/<token>` | `unsubscribe` | Email unsubscribe |

### Auth
| Route | Function | Notes |
|---|---|---|
| `GET/POST /login` | `login` | Email/password login |
| `GET/POST /register` | `register` | New account. Accepts ?ref= param (pre-fills referral code). |
| `GET /referral/validate` | `referral_validate` | AJAX: validate referral code; returns {valid, referrer_name} (first name + last initial only). Returns {valid: false} if program inactive. |
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
| `GET/POST /edit_item/<id>` | `edit_item` | Edit existing item |
| `DELETE /delete_photo/<id>` | `delete_photo` | Delete gallery photo |
| `POST /item/<id>/resubmit` | `resubmit_item` | Seller resubmits item after addressing "needs info" feedback |
| `GET/POST /confirm_pickup` | `confirm_pickup` | **Deprecated** — now redirects to `/dashboard`. Pickup week set via dashboard modal. |
| `GET /confirm_pickup_success` | `confirm_pickup_success` | |
| `GET/POST /upgrade_pickup` | `upgrade_pickup` | Upgrade from Free to Pro plan ($15) |
| `GET /upgrade_pickup_success` | `upgrade_pickup_success` | |
### Buyer
| Route | Function | Notes |
|---|---|---|
| `GET /reserve_item/<id>` | `reserve_item` | Non-binding reservation |
| `GET /buy_item/<id>` | `buy_item` | Initiate Stripe checkout |
| `GET /item_success` | `item_sold_success` | Post-purchase success |

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

### Admin (requires is_admin or is_super_admin)
| Route | Function | Notes |
|---|---|---|
| `GET/POST /admin` | `admin_panel` | Main admin dashboard |
| `GET/POST /admin/approve` | `admin_approve` | Item approval queue |
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
| `POST /admin/settings/referral` | `admin_referral_settings` | Update referral program AppSettings (super admin only) |
| `POST /admin/crew/approve/<user_id>` | `admin_crew_approve` | Approve worker (sets worker_role='both'); sends email |
| `POST /admin/crew/reject/<user_id>` | `admin_crew_reject` | Reject worker application |
| `GET /admin/crew/shift/<shift_id>/ops` | `admin_shift_ops` | Live ops view — mover-to-truck cards + route stop lists + destination unit selectors |
| `GET /admin/routes` | `admin_routes_index` | Route builder — unassigned sellers grouped by cluster + shift capacity board |
| `POST /admin/routes/auto-assign` | `admin_routes_auto_assign` | Run auto-assignment for all unassigned eligible sellers. Returns JSON {assigned, tbd, over_cap_warnings} |
| `POST /admin/routes/stop/<pickup_id>/move` | `admin_routes_move_stop` | Move ShiftPickup to different shift+truck; recalculates capacity_warning. Returns JSON |
| `POST /admin/routes/seller/<user_id>/assign` | `admin_routes_assign_seller` | Manually assign unassigned seller. Returns JSON (409 if seller already has ShiftPickup) |
| `POST /admin/crew/shift/<shift_id>/add-truck` | `admin_shift_add_truck` | Increment Shift.trucks by 1 via raw SQL. Returns JSON {new_truck_number} |
| `POST /admin/crew/shift/<shift_id>/order` | `admin_shift_order_stops` | Nearest-neighbor stop ordering from storage unit origin; writes stop_order to all ShiftPickups |
| `POST /admin/crew/shift/<shift_id>/stop/<pickup_id>/reorder` | `admin_shift_reorder_stop` | Set a specific stop_order value. Returns JSON |
| `POST /admin/crew/shift/<shift_id>/notify` | `admin_shift_notify_sellers` | Send pickup confirmation emails to unnotified sellers (idempotent). Redirect |
| `GET /crew/shift/<shift_id>/stops_partial` | `crew_shift_stops_partial` | HTML partial of stops for current mover's truck. Used by 30s auto-refresh |
| `GET+POST /admin/settings/route` | `admin_route_settings` | Capacity settings + category unit sizes. Super admin only |
| `POST /admin/crew/shift/<shift_id>/assign` | `admin_shift_assign_seller` | Add seller stop to shift (globally unique per seller); pre-populates storage_location_id from truck_unit_plan |
| `POST /admin/crew/shift/<shift_id>/stop/<pickup_id>/remove` | `admin_shift_remove_stop` | Remove pending stop only |
| `POST /admin/crew/shift/<shift_id>/mover/<assignment_id>/assign_truck` | `admin_shift_assign_mover_truck` | Assign driver to truck (cap-enforced); truck_number=0 unassigns |
| `POST /admin/crew/shift/<shift_id>/assign_movers_bulk` | `admin_shift_assign_movers_bulk` | Assign multiple movers to a truck in one submit |
| `POST /admin/crew/shift/<shift_id>/truck/<truck_number>/assign_unit` | `admin_shift_assign_unit` | Write truck→unit mapping to Shift.truck_unit_plan; sync to existing pending pickups for that truck. Returns JSON. |
| `GET /admin/crew/shift/<shift_id>/intake` | `admin_shift_intake_log` | Full read-only intake log for a shift (all records + flags) |
| `POST /admin/intake/flag/<flag_id>/resolve` | `admin_intake_flag_resolve` | Resolve a single IntakeFlag with resolution note |
| `GET /admin/intake/flagged` | `admin_intake_flagged` | Damaged/missing review queue — all items with unresolved flags (excl. sold/rejected) |
| `POST /admin/intake/flagged/remove` | `admin_intake_flagged_remove` | Bulk reject: sets status='rejected', auto-resolves all flags with audit note |
| `GET /admin/storage` | `admin_storage_index` | Storage location list + inline create form. Super admin only. |
| `POST /admin/storage/create` | `admin_storage_create` | Create StorageLocation. Super admin only. |
| `POST /admin/storage/<id>/edit` | `admin_storage_edit` | Edit StorageLocation fields. Super admin only. |
| `GET /admin/storage/<id>` | `admin_storage_detail` | All items at a storage location, filterable by status. Admin. |

### Crew (Worker Accounts)
| Route | Function | Notes |
|---|---|---|
| `GET/POST /crew/apply` | `crew_apply` | Worker application form (role_pref field removed; sets 'both') |
| `GET /crew/pending` | `crew_pending` | Pending approval holding page |
| `GET /crew` | `crew_dashboard` | Approved worker portal — my schedule (upcoming only, links to role-appropriate view), shift history, today's shift banner, Open Intake button for organizers |
| `GET/POST /crew/availability` | `crew_availability` | Weekly availability + partner preferences section |
| `POST /crew/preferences` | `crew_save_preferences` | Save WorkerPreference records (replaces all existing) |
| `GET /crew/schedule/<week_id>` | `crew_schedule_week` | Full week calendar HTML partial (approved workers, published weeks only) |
| `GET /crew/shift/<shift_id>` | `crew_shift_view` | Phone-optimized mover shift view; blocks future shifts; shows truck-filtered stops with item photo strip |
| `POST /crew/shift/<shift_id>/start` | `crew_shift_start` | Create ShiftRun; blocked for future shifts |
| `POST /crew/shift/<shift_id>/stop/<pickup_id>/update` | `crew_shift_stop_update` | Mark stop completed/issue; writes picked_up_at on completion |
| `POST /crew/shift/<shift_id>/stop/<pickup_id>/revert` | `crew_shift_stop_revert` | Revert resolved stop to pending |
| `POST /crew/shift/<shift_id>/complete_retroactive` | `crew_shift_complete_retroactive` | One-click retroactive completion for past shifts |
| `POST /crew/shift/<shift_id>/end` | `crew_shift_end` | Close ShiftRun; sets ShiftAssignment.completed_at for driver; unconditional for past shifts |
| `GET /crew/intake/<shift_id>` | `crew_intake_shift` | Organizer intake page; requires organizer role_on_shift; phone+desktop responsive |
| `POST /crew/intake/<shift_id>/item/<item_id>` | `crew_intake_submit` | Submit intake record for one item; creates IntakeRecord (append-only); optionally creates IntakeFlag; updates InventoryItem storage fields |
| `GET /crew/intake/search` | `crew_intake_search` | Search items by ID or seller name; returns HTML partial for fetch into #search-results |
| `POST /crew/intake/<shift_id>/unknown` | `crew_intake_log_unknown` | Log an unidentified item as IntakeFlag (flag_type='unknown') |
| `POST /crew/intake/<shift_id>/complete` | `crew_intake_complete` | Set ShiftAssignment.completed_at for organizer; gated on received_count >= total_items |

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
| `POST /upgrade_payout_boost` | `upgrade_payout_boost` | Create $15 Stripe Checkout Session for payout boost (login required) |
| `GET /upgrade_boost_success` | `upgrade_boost_success` | Post-payment confirmation page |
| `GET/POST /upload_from_phone` | `upload_from_phone[_post]` | Mobile upload page |
| `POST /upload_video_from_phone` | `upload_video_from_phone_post` | |

### API
| Route | Function | Notes |
|---|---|---|
| `POST /api/item/<id>/acknowledge_price_change` | `acknowledge_price_change` | Dismiss price-change badge |
| `GET /health` | `health_check` | Render health check |

---

## Templates

```
layout.html                    — Base template (nav, footer, analytics)
index.html                     — Homepage (hero, waitlist form, interactive room)
about.html
inventory.html                 — Shop front (category grid + item cards)
product.html                   — Product detail page (gallery, buy button)
dashboard.html                 — Seller dashboard (items, status, upgrade prompts)
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
become_a_seller.html           — Seller landing page
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
crew/shift.html                — Phone-optimized mover shift view: stops in stop_order; Navigate → button; stairs/elevator badge; 30s auto-refresh of #stop-list via stops_partial; pre-start/in-progress/past states; inline notes; retroactive complete
crew/stops_partial.html        — HTML partial (no layout): stop list for current mover's truck; used by 30s setInterval auto-refresh fetch
crew/intake.html               — Organizer intake page: truck sections with received/total counters, item search, bottom-sheet modal for submission; responsive (960px+ two-column, 760px+ trucks grid)
crew/_intake_modal.html        — Bottom-sheet modal partial embedded in crew/intake.html
crew/intake_search_results.html — Partial rendered via fetch into #search-results; shows item photo, ID, seller name
admin/schedule_index.html      — Week list sorted ascending by date + 7×2 slot toggle creation form; Delete Week button (draft-only); Storage Units link
admin/schedule_week.html       — Schedule builder; Movers/Organizers labels; View Ops → link per shift card; Delete Week button in header (draft-only)
admin/shift_ops.html           — Ops page: issue alert banner, green mover panel, ordered stop lists + badges (stop#, access type, cap warning), Order Route + Notify Sellers buttons, Intake Summary
admin/routes.html              — Route builder: unassigned sellers by cluster, shift capacity board, auto-assign, move/assign inline panels
admin/route_settings.html      — Capacity settings (raw cap, buffer%), time windows, Maps API key, per-category unit sizes
admin/storage_index.html       — Storage location list with inline create + edit panels (super admin)
admin/storage_detail.html      — Items at a given storage location, filterable by status
admin/shift_intake_log.html    — Full read-only intake log per shift with flag indicators and organizer notes
admin/intake_flagged.html      — Damaged/missing review queue; checkbox bulk selection + "Remove from Marketplace" bulk action
```

---

## Business Logic

### Item Status Lifecycle
```
pending_valuation → (admin approves) → approved → (seller confirms logistics) → available → (sold) → sold
                  → (admin rejects) → rejected
                  → (admin requests info) → needs_info → (seller resubmits) → pending_valuation
                                                       → (admin cancels request) → pending_valuation

Operational milestones (don't change status):
  picked_up_at         — item collected from seller
  arrived_at_store_at  — item physically arrived at warehouse
  storage_location_id  — set by organizer at intake (which unit the item is in)
  storage_row          — set by organizer at intake (aisle/row within unit)

Admin can set status='rejected' via the damaged/missing queue to remove flagged items from the marketplace.
```

### Payout Rate / Referral Program
The two-tier Pro/Free system is replaced by a referral-driven payout rate stored on `User.payout_rate`.

| Starting situation | payout_rate |
|--------------------|-------------|
| New seller, no referral code | 20% (base rate) |
| New seller who used a referral code | 30% (base + signup bonus) |
| Referrer, per confirmed referral | +10% per referral, up to 100% |

- `collection_method` field is retained on `InventoryItem` but no longer drives payout — `User.payout_rate` is used everywhere.
- Payout amount: `item.price * (seller.payout_rate / 100)`. No Pro/Free distinction.
- Referral is confirmed when `InventoryItem.arrived_at_store_at` is set during organizer intake — exactly one credit per referred seller regardless of item count.
- `calculate_payout_rate(user)` recalculates from AppSettings: `base_rate + (signup_bonus if referred_by_id else 0) + (confirmed_count × bonus_per_referral)`, capped at `max_rate`. Result written to `User.payout_rate` at confirmation time.
- `/upgrade_pickup` and `/upgrade_checkout` routes left in place (return redirect) to avoid broken bookmarks. UI entry points removed.
- The $15 Pro fee is gone. `has_paid` retained harmlessly.
- Referral program AppSetting keys: `referral_base_rate` ('20'), `referral_signup_bonus` ('10'), `referral_bonus_per_referral` ('10'), `referral_max_rate` ('100'), `referral_program_active` ('true').
- All new sellers still get `collection_method='free'` by default (field not removed).
- Pickup week is set per-user (`User.pickup_week`) during onboarding (optional, skippable) or from the dashboard modal at any time.
- The admin free-tier confirm/reject system is commented out from active UI; preserved for ops flexibility.

### Admin Roles
- `is_admin`: access to admin panel (inventory, approvals, free-tier management)
- `is_super_admin`: full access (user management, database reset, mass email, category management, schedule creation, storage unit management)
- Pre-approved via `AdminEmail` table — role assigned at signup

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
- `warehouse_lat` / `warehouse_lng`: warehouse coordinates for delivery radius check (fail-open if absent)
- `delivery_radius_miles`: max delivery distance, default '50'

### Stripe Integration
- Item purchase: standard Checkout Session
- Pro pickup fee ($15): Checkout Session at onboarding or confirm_pickup
- Payment method save: SetupIntent (for deferred charge at pickup)
- Stripe webhook at `/webhook` handles all post-payment state changes

---

## Key Patterns

1. **Server-rendered only** — no React/Vue. All state changes go through form POST → redirect. Use Vanilla JS for interactivity only. Exception: fetch POST for auto-save actions that would cause disruptive page reloads (e.g., destination unit dropdown on ops page) — route still does all DB writes server-side, returns JSON.

2. **Flash messages** — use `flash('message', 'success'|'error'|'info')` for user feedback. Rendered in `layout.html`.

3. **Auth guards** — `@login_required` for user routes. Admin routes check `current_user.is_admin`. Super admin routes use `@require_super_admin` decorator. Crew routes use `require_crew()` helper (not a decorator). Role-specific crew gating (mover vs. organizer) checks `ShiftAssignment.role_on_shift` inside each route — not `User.worker_role`.

4. **New routes** — add to `app.py` following existing patterns. Group logically near related routes.

5. **New templates** — extend `layout.html`. Use CSS variables (never hardcode colors). Use `.card`, `.btn-primary`, `.btn-outline` classes.

6. **Database changes** — always add a Flask-Migrate migration (`flask db migrate -m "description"`). Never modify the DB directly.

7. **Photo uploads** — use `validate_file_upload()` helper. Store to `/var/data/` (Render) or `static/uploads/` (local). Serve via `url_for('uploaded_file', filename=...)`.

8. **Email** — use `send_email(to, subject, html)`. Wrap HTML with `wrap_email_template()` for consistent styling.

9. **SellerAlert system** — reusable alert model for dashboard notifications. Types: `needs_info` (item-specific, from approval queue), `pickup_reminder` (account-level, from nudge), `preset` / `custom` (from seller profile panel). Alerts auto-resolve when the seller takes the required action (resubmit item, select pickup week, etc.).

10. **Seller profile panel** — slide-out drawer (480px right-side) fetched as HTML partial via `/admin/seller/<id>/panel`. Used on admin.html and admin_approve.html. Triggered by clicking seller names.

11. **Constants** — shared constants in `constants.py`: `VIDEO_REQUIRED_CATEGORIES`, `category_requires_video()`, `PICKUP_WEEKS`, `PICKUP_WEEK_DATE_RANGES`, `PICKUP_TIME_OPTIONS`. Import into `app.py` and use via context processor for templates.

12. **Shift optimizer** — `_run_optimizer(week)` in `app.py`. Pre-caches all worker availability at the start (no DB queries mid-loop). Tracks load and same-day assignments in-memory. Sort key: `(already_doubled, flexible_for_other_slot, load, abs(role_imbalance), avoid_conflict, not preferred_match)`. `truck_number` derived from slot index position (slot 0–1 → truck 1, etc.). `assigned_by_id=NULL` on ShiftAssignment means optimizer-assigned; non-NULL means manual.

13. **Cron jobs** — digest email triggered via POST `/admin/digest/trigger` with `X-Cron-Secret` header or `?secret=` query param matching `DIGEST_CRON_SECRET` env var. Set up as Render cron job.

14. **Eastern timezone helpers** — `_now_eastern()` and `_today_eastern()` in `app.py` use `zoneinfo.ZoneInfo('America/New_York')`. Use these for all "what day/time is it right now" logic. Never use `datetime.utcnow()` for date comparisons or slot-preference logic. Timestamps stored in DB remain UTC (SQLAlchemy default).

15. **data-* attributes for JS data passing** — never pass structured data to JS event handlers via inline `tojson` in onclick attributes (breaks on special characters in strings). Use `data-*` attributes on the element and read via `element.dataset.*` in the handler.

16. **Referral program helpers** — four functions in `app.py` (also re-exported via `helpers.py` for tests):
    - `generate_unique_referral_code()` — 8-char uppercase alphanumeric (excludes O, 0, I, 1), collision-checked against DB.
    - `apply_referral_code(new_user, code)` — looks up referrer, sets `referred_by_id`, bumps `payout_rate` by signup bonus. No-op if program inactive or code invalid.
    - `maybe_confirm_referral_for_seller(seller)` — call in `crew_shift_stop_update` when stop becomes `'completed'`. Confirms the referral (once per seller, idempotent), recalculates referrer's rate, sends email. No-op if program inactive, no `referred_by_id`, or already confirmed.
    - `calculate_payout_rate(user)` — `base + (signup_bonus if referred_by_id) + (confirmed × bonus_per)`, capped at max. All values from AppSettings. **Includes signup bonus in the recalculation** so a referred seller who also refers others doesn't lose their signup bonus when their rate is recalculated.

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
