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

Properties: has_pickup_location, pickup_display, is_guest_account
```

### InventoryItem
```
id, description, long_description
price, suggested_price, quality (1-5 int)
status: 'pending_valuation' | 'approved' | 'available' | 'sold' | 'rejected'
date_added
collection_method: 'online' | 'in_person'
is_large (bool) — set by admin at approval
oversize_included_in_service_fee (bool)
oversize_fee_paid (bool)
pickup_week: 'week1' (Apr 26–May 2) | 'week2' (May 3–May 9)
dropoff_pod: 'greek_row' | 'apartment'
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
id, item_id, user_id, created_at
Non-binding reservation (no payment) for pre-launch reserve-only mode.
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

### AppSetting
```
Key-value store for runtime flags.
AppSetting.get(key, default), AppSetting.set(key, value)
Current keys in use: 'reserve_only_mode', 'pickup_period_active', 'current_store'
```

---

## Route Map (`app.py` — 5,400+ lines)

### Public
| Route | Function | Notes |
|---|---|---|
| `GET /` | `index` | Homepage + waitlist signup form |
| `GET /about` | `about` | About page |
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
| `GET/POST /onboard` | `onboard` | Main multi-step onboarding wizard |
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
| `POST /confirm_pickup` | `confirm_pickup` | Seller confirms pickup logistics |
| `GET /confirm_pickup_success` | `confirm_pickup_success` | |
| `GET/POST /upgrade_pickup` | `upgrade_pickup` | Upgrade from free to valet |
| `GET /upgrade_pickup_success` | `upgrade_pickup_success` | |
| `GET/POST /pay_oversize_fee/<id>` | `pay_oversize_fee` | Pay $10 oversize fee |
| `GET /pay_oversize_fee_success` | `pay_oversize_fee_success` | |
| `POST /confirm_dropoff` | `confirm_dropoff` | Self drop-off confirmation |

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
| `POST /admin/mass-email` | `admin_mass_email` | |
| `POST /admin/database/reset` | `admin_database_reset` | Super admin only |

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
layout.html          — Base template (nav, footer, analytics)
index.html           — Homepage (hero, waitlist form, interactive room)
about.html
inventory.html       — Shop front (category grid + item cards)
product.html         — Product detail page (gallery, buy button)
dashboard.html       — Seller dashboard (items, status, upgrade prompts)
admin.html           — Admin panel (bulk edit, mark sold, exports)
admin_approve.html   — Item approval queue
admin_sidebar.html   — Admin nav sidebar partial
login.html
register.html
signup.html          — Waitlist signup
onboard.html         — Multi-step seller onboarding wizard
onboard_complete_account.html
add_item.html        — Item upload form (QR upload, photo carousel)
edit_item.html       — Edit existing item
upload.html          — Upload page
upload_from_phone.html
become_a_seller.html — Seller landing page
confirm_pickup.html  — Seller confirms pickup logistics
upgrade_pickup.html  — Upgrade from drop-off to valet
pay_oversize_fee.html
pay_oversize_fee_blocked.html
account_settings.html
add_payment_method.html
reserve_success.html
item_success.html    — Post-purchase success
error.html
privacy_policy.html
refund_policy.html
terms_conditions.html
unsubscribe_confirm.html
unsubscribe_success.html
data_preview.html    — Admin data preview
director.html        — Internal ops view
_category_grid.html  — Category grid partial
dashboard_pickup_form.html — Pickup form partial
```

---

## Business Logic

### Item Status Lifecycle
```
pending_valuation → (admin approves) → approved → (seller confirms logistics) → available → (sold) → sold
                  → (admin rejects) → rejected
```

### Service Tiers
- **Valet Pickup** (premium): $15 upfront service fee, 50% payout to seller
- **Self Drop-off** (free): $0 upfront, 33% payout to seller
- Sellers can upgrade from drop-off to valet from dashboard

### Oversize Fee
- Admin marks `is_large = True` at approval
- First oversized item: included in $15 service fee (`oversize_included_in_service_fee`)
- Additional oversized items: $10 fee (`oversize_fee_paid`)

### Admin Roles
- `is_admin`: access to admin panel (inventory, approvals)
- `is_super_admin`: full access (user management, database reset, mass email)
- Pre-approved via `AdminEmail` table — role assigned at signup

### AppSetting Flags
- `reserve_only_mode`: 'true'/'false' — hides buy buttons, shows reserve only
- `pickup_period_active`: 'true'/'false' — enables pickup scheduling
- `current_store`: store name for display

### Stripe Integration
- Item purchase: standard Checkout Session
- Valet pickup fee ($15): Checkout Session at onboarding
- Oversize fee ($10): Checkout Session
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
