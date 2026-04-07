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
phone, pickup_address, pickup_location_type ('on_campus'|'off_campus')
pickup_dorm, pickup_room, pickup_note, pickup_lat, pickup_lng
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
```

### InventoryCategory
```
id, name, image_url, count_in_stock
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
'drivers_per_truck', 'organizers_per_truck', 'max_trucks_per_shift'
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
Relationships: week → ShiftWeek, assignments → [ShiftAssignment]
Properties: label, sort_key, drivers_needed, organizers_needed,
            driver_assignments, organizer_assignments, is_fully_staffed, status_label
```

### ShiftAssignment
```
One worker assigned to one shift in a specific role.
id, shift_id (FK), worker_id (FK → User), role_on_shift ('driver'|'organizer')
assigned_at, assigned_by_id (FK → User, nullable — NULL = optimizer)
Relationships: shift → Shift, worker → User, assigned_by → User
```

---

## Route Map (`app.py` — 6,300+ lines)

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
| `GET/POST /register` | `register` | New account |
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
| `POST /admin/crew/approve/<user_id>` | `admin_crew_approve` | Approve worker application |
| `POST /admin/crew/reject/<user_id>` | `admin_crew_reject` | Reject worker application |

### Crew (Worker Accounts)
| Route | Function | Notes |
|---|---|---|
| `GET/POST /crew/apply` | `crew_apply` | Worker application form |
| `GET /crew/pending` | `crew_pending` | Pending approval holding page |
| `GET /crew` | `crew_dashboard` | Approved worker dashboard — passes `my_shifts`, `current_week` |
| `GET/POST /crew/availability` | `crew_availability` | Worker weekly availability update |
| `GET /crew/schedule/<week_id>` | `crew_schedule_week` | Full week calendar HTML partial (approved workers only, published weeks only) |

### Shift Scheduling (Admin)
| Route | Function | Notes |
|---|---|---|
| `GET /admin/schedule` | `admin_schedule_index` | List all ShiftWeeks + creation form. Super admin only. |
| `POST /admin/schedule/create` | `admin_schedule_create` | Create ShiftWeek + 14 Shift records from form. |
| `GET /admin/schedule/<week_id>` | `admin_schedule_week` | Schedule builder. Draft = dropdowns, published = badge + swap UI. |
| `POST /admin/schedule/<week_id>/optimize` | `admin_schedule_optimize` | Run greedy optimizer, clear + rewrite all ShiftAssignments. |
| `POST /admin/schedule/<week_id>/publish` | `admin_schedule_publish` | Set status=published, email all assigned workers. |
| `POST /admin/schedule/<week_id>/unpublish` | `admin_schedule_unpublish` | Return to draft. Silent. |
| `POST /admin/schedule/shift/<shift_id>/update` | `admin_shift_update` | Save trucks count + all assignments for one shift. Redirects to `#shift-<id>`. |
| `POST /admin/schedule/shift/<shift_id>/swap` | `admin_shift_swap` | Replace one worker on a published shift. Sends swap emails. |

### Upload / QR
| Route | Function | Notes |
|---|---|---|
| `POST /api/upload_session/create` | `create_upload_session` | Create QR session token |
| `GET /api/upload_session/status` | `upload_session_status` | Poll for mobile uploads |
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
admin.html                     — Admin panel (bulk edit, mark sold, exports)
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
crew/apply.html                — Worker application form
crew/pending.html              — Application submitted / awaiting approval
crew/dashboard.html            — Approved worker dashboard (my shifts list + full-schedule modal trigger)
crew/availability.html         — Weekly availability update form
crew/_availability_grid.html   — Availability grid partial
crew/schedule_week_partial.html — Full crew calendar injected into modal via fetch(); no layout.html
admin/schedule_index.html      — Week list + 7×2 slot toggle creation form
admin/schedule_week.html       — Schedule builder (draft dropdowns / published badge+swap UI)
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
  picked_up_at       — item collected from seller
  arrived_at_store_at — item physically arrived at warehouse
```

### Service Tiers
Both tiers include free pickup — the difference is the revenue split and guarantee level.

| Tier | `collection_method` | Payout to Seller | Fee | Item Limit | Pickup |
|------|-------------------|-----------------|-----|------------|--------|
| **Pro Plan** | `online` | 50% of sale price | $15 one-time | Unlimited | Guaranteed |
| **Free Plan** | `free` | 20% of sale price | $0 | Unlimited | Space-permitting |

- **All new sellers start on the Free plan.** Service tier is no longer selected during onboarding — it defaults to `'free'`. Upgrade is a deliberate dashboard action.
- Pickup week is set per-user (`User.pickup_week`) during onboarding (optional, skippable) or from the dashboard modal at any time.
- Pro sellers pay $15 via `/upgrade_pickup` ($15 Stripe checkout) — flow unchanged.
- The admin free-tier confirm/reject system still exists but is no longer the gate to activity. Commented out from active UI; preserved for ops flexibility.

### Admin Roles
- `is_admin`: access to admin panel (inventory, approvals, free-tier management)
- `is_super_admin`: full access (user management, database reset, mass email, category management)
- Pre-approved via `AdminEmail` table — role assigned at signup

### Worker / Crew Accounts
- Users apply at `/crew/apply` — sets `worker_status='pending'`, creates `WorkerApplication`
- Admin approves/rejects at `/admin/crew/approve|reject/<user_id>`
- Approved workers (`is_worker=True`, `worker_status='approved'`) access `/crew` dashboard
- Workers submit weekly availability via `/crew/availability` → stored in `WorkerAvailability`

### AppSetting Flags
- `reserve_only_mode`: 'true'/'false' — hides buy buttons, shows reserve only
- `pickup_period_active`: 'true'/'false' — enables pickup scheduling
- `current_store`: store name for display
- `store_open_date`: date string shown on inventory banner when store not yet open

### Stripe Integration
- Item purchase: standard Checkout Session
- Pro pickup fee ($15): Checkout Session at onboarding or confirm_pickup
- Payment method save: SetupIntent (for deferred charge at pickup)
- Stripe webhook at `/webhook` handles all post-payment state changes

---

## Key Patterns

1. **Server-rendered only** — no React/Vue. All state changes go through form POST → redirect. Use Vanilla JS for interactivity only.

2. **Flash messages** — use `flash('message', 'success'|'error'|'info')` for user feedback. Rendered in `layout.html`.

3. **Auth guards** — `@login_required` for user routes. Admin routes check `current_user.is_admin`. Super admin routes use `@require_super_admin` decorator.

4. **New routes** — add to `app.py` following existing patterns. Group logically near related routes.

5. **New templates** — extend `layout.html`. Use CSS variables (never hardcode colors). Use `.card`, `.btn-primary`, `.btn-outline` classes.

6. **Database changes** — always add a Flask-Migrate migration (`flask db migrate -m "description"`). Never modify the DB directly.

7. **Photo uploads** — use `validate_file_upload()` helper. Store to `/var/data/` (Render) or `static/uploads/` (local). Serve via `url_for('uploaded_file', filename=...)`.

8. **Email** — use `send_email(to, subject, html)`. Wrap HTML with `wrap_email_template()` for consistent styling.

9. **SellerAlert system** — reusable alert model for dashboard notifications. Types: `needs_info` (item-specific, from approval queue), `pickup_reminder` (account-level, from nudge), `preset` / `custom` (from seller profile panel). Alerts auto-resolve when the seller takes the required action (resubmit item, select pickup week, etc.).

10. **Seller profile panel** — slide-out drawer (480px right-side) fetched as HTML partial via `/admin/seller/<id>/panel`. Used on admin.html and admin_approve.html. Triggered by clicking seller names.

11. **Constants** — shared constants in `constants.py`: `VIDEO_REQUIRED_CATEGORIES`, `category_requires_video()`, `PICKUP_WEEKS`, `PICKUP_WEEK_DATE_RANGES`, `PICKUP_TIME_OPTIONS`. Import into `app.py` and use via context processor for templates.

12. **Shift optimizer** — `_run_optimizer(week)` in `app.py`. Pre-caches all worker availability at the start (no DB queries mid-loop). Tracks load and same-day assignments in-memory. Sort key: `(already_doubled, flexible_for_other_slot, load)` — prefers workers who can only do one slot, then by load, then deprioritizes double-shifts. `assigned_by_id=NULL` on ShiftAssignment means optimizer-assigned; non-NULL means manual.

13. **Cron jobs** — digest email triggered via POST `/admin/digest/trigger` with `X-Cron-Secret` header or `?secret=` query param matching `DIGEST_CRON_SECRET` env var. Set up as Render cron job.

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
