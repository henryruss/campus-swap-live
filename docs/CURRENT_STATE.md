# Campus Swap — Current State Inventory

> Snapshot as of 2026-10-13. This is the "before" half of the revamp diff: what the site *is*, not what it should be.
> Built by reading the code (app.py ~23k lines / 314 routes), not by clicking through the live site.
> Line numbers (`:1234`) refer to app.py at commit 7ae3211.

---

## 0. At a glance

| Surface | Who | Home page | ~Pages | Health |
|---|---|---|---|---|
| Public / marketing | Visitors, parents | `/` | 7 | Old claims (free pickup, 50/50, referral tiers) conflict across pages |
| Seller | Students | `/dashboard` | 12 | Long funnel: 8–9 wizard steps, then 3 setup modals |
| Shop | Buyers | `/shop` | 6 | Solid. Delivery fee only shown at the last step; pickup hidden behind a "code" |
| Admin: items / money | Henry, admins | `/admin/items` | 20 | Item takes 6–8 queues to go live; price set in 3 places; many pages with no nav link |
| Admin: logistics | Admins, campus directors | `/admin/ops` | 12 | Two ops pages (new + legacy); 3 ways to create shifts; CDs blocked from key actions |
| Crew | Drivers, workers | `/crew` | 10 | 3 taps plus a full page reload per stop; Quick Capture is broken |

The public pages have no admin editor. Most config (delivery zones, tax, bundle, flexible) lives only in AppSettings rows, with no UI to change it.

---

## 1. Navigation today

**Main nav** (`layout.html`):
- Logo · About · Parents · "Your store: UNC Chapel Hill" (a picker with one option) · Become a Seller · Shop The Drop · Cart
- Sign In when logged out. When logged in: Dashboard (or Crew Portal) and a user menu.
- Campus directors also get a Seller/Admin switch.

**Admin nav** (`admin/admin_layout.html`): an icon-only sidebar with these tabs:
`Ops · Items(badge) · Payouts · Crew · Warehouse | Settings (super) / CD Settings (CD)`
- **No nav entry** for: Sellers, Schedule, Quick-Capture queue, Storage Audit, FB Export, Intake Flagged, AI Generate/Review standalone pages.
- Active-tab highlighting is wrong on `/admin/sellers` (nothing highlights) and `/admin/storage/*` (Settings highlights).
- Plain admins see Items but only the "All Items" sub-tab. Approval, Background Removal and Photo Verification are super-admin only.

**Crew nav:** "Crew Portal" link → `/crew`. Everything else is reached through buttons on that page. The Warehouse button opens the admin layout.

---

## 2. Page map by surface

### 2.1 Public / marketing
| URL | Purpose | Main blocks |
|---|---|---|
| `/` | Homepage | Hero cards set by `homepage_mode` (pinned to `dual`: Shop card + Sell card) → category chips → featured grid + quickview → 3 testimonials |
| `/about` | Mission | Problem / Solution / environment story |
| `/parents` | Parent-to-student referral | Urgency bar → hero → trust bar → 4 steps → earnings table → copy-and-share text |
| `/become-a-seller` | Seller pitch | "What's your room worth?" calculator → How It Works → 50/50 → FAQ → CTA |
| `/contact` | Contact form | Turnstile; emails the founders |
| legal ×3 | Terms / Privacy / Refund | Static text |

`homepage_mode` options: `dual | buyer_only | seller_only | off_season | auto`.

### 2.2 Seller
| URL | Purpose |
|---|---|
| `/onboard` | 8-step first-item wizard (category → condition → photos → title → description → price → class year → review), plus step 9 "create account" for guests |
| `/login`, `/register`, `/auth/google`, `/complete_profile`, `/claim/<token>` | Auth. **Signup exists in 4 places.** |
| `/dashboard` | "Seller Studio": setup checklist (phone / pickup / payout) **or** 6-stage tracker → stats → pickup date → alerts → item grid |
| `/add_item` | 7-step wizard for each extra item; QR code for phone upload |
| `/edit_item/<id>` | Edit or resubmit (used for needs-info) |
| `/account_settings` | Profile, password, pickup location, payout, delete |
| `/seller/reschedule`, `/reschedule/<token>` | Pick a new pickup slot (logged-in version and token version) |

### 2.3 Shop
| URL | Purpose |
|---|---|
| `/shop` | Grid with filters + infinite scroll. Can instead render as **closed** (`shop_closed_mode`), **teaser** (`shop_teaser_mode` + `store_open_date`) or browse-only. |
| `/item/<id>` | Gallery, price vs. retail, Add to Cart / Buy Now, related items. Has a super-admin inline edit mode. |
| `/cart` | Line items, bundle hint, subtotal |
| `/checkout/delivery` | Address (Google Places) **or** a hidden "I'm picking up" panel that needs a code |
| `/checkout/review` | Price breakdown, Standard/Flexible, promo → Stripe |
| `/item_success` | Confirmation |

### 2.4 Admin: items, sellers, money
| URL | Purpose |
|---|---|
| `/admin/items` | Megatable plus sub-views: all / approval queue (modal) / AI review / photo verification. Plus AI Autofill modal, seller panel and item drawer. |
| `/admin/items/needs_info` | Crew quick-capture queue *(no nav link)* |
| `/admin/sellers` | Seller list, nudges, proxy sellers *(no nav link)* |
| `/admin/payouts` | Unpaid by seller / Paid / CSV. Works well. |
| `/admin/settings` | Everything global: shop toggles, uploads, pickup window, routes, storage CRUD, SMS, users, exports, mass email, CDs, FB posters, DB reset |
| `/admin/warehouse` (+ `/rephoto`, `/rephoto/report`) | Unit browser, item search, log item, rephoto campaign, seller matching |
| `/admin/storage/audit` | Find an item, set its location or photo *(no nav link)* |
| `/admin/ai/generate`, `/admin/ai/review` | Standalone copies of Items sub-features |
| `/admin/fb-export` (+ `/takedowns`) | One-item-per-screen FB posting tool (user layout, not the admin layout) |

### 2.5 Admin: logistics
| URL | Purpose |
|---|---|
| `/admin/ops` | **Main hub.** Shift list → truck cards (pickup or delivery) → unassigned sellers + auto-assign → delivery / pickup-order queues → truck drawer |
| `/admin/ops/shift/<id>/truck/<n>/reorder` | Drag to reorder stops |
| `/admin/crew` | Workers, applications, weekly shift board, optimizer |
| `/admin/schedule`, `/admin/schedule/<week>` | Create weeks; read-only week view *(no nav link)* |
| `/admin/crew/shift/<id>/ops` | **Legacy ops page.** Still the only UI for reassigning a pickup to another shift, the reschedule lock, the overflow truck and reschedule activity. |
| `/admin/tutorial` | Campus director sandbox onboarding |

### 2.6 Crew
| URL | Purpose |
|---|---|
| `/crew/apply` → `/crew/pending` | Apply (creates a user with no password), then wait |
| `/crew` | Today banner, schedule, availability, history, Quick Capture, Warehouse button |
| `/crew/availability` | Weekly AM/PM grid, partner preferences |
| `/crew/shift/<id>` | Pickup driver route: start → stop cards → placement → end-confirm |
| `/crew/delivery/<id>` | Delivery run: load checklist, optimize, proof-of-delivery photo |
| `/crew/shift/<id>/history` | Completed shift, read-only |
| `/crew/intake/<id>` | **Deprecated** organizer intake, still reachable |

---

## 3. Core journeys (step counts)

**Seller: land → listed → scheduled → paid**
1. `/` → Start listing → `/become-a-seller` (calculator) → Start Selling
2. `/onboard`: 8 steps, plus 9 for guests (account creation)
3. `/dashboard`: setup checklist with 3 modals (phone, pickup week + location, payout ×2). The tracker stays hidden until all three are done.
4. Wait for approval (1–2 days); possibly a needs-info → edit → resubmit loop
5. Admin assigns a shift → date shows on the dashboard → SMS/email with reschedule link
6. Item sells → email → admin pays manually (Venmo etc.) → no seller payout page

**≈ 3 page loads + 8–9 wizard steps + 3 modals before the first item is fully set up.**

**Buyer: browse → paid**
`/shop` → `/item/<id>` → Add to Cart / Buy Now (both go to the cart) → `/cart` → `/checkout/delivery` → `/checkout/review` → Stripe → `/item_success`
**≈ 6 screens and 5 clicks; the delivery fee is unknown until screen 5.**

**Item: submitted → live in shop (admin)**
Approval queue (price set) → pickup → warehouse log / storage audit (location) → rephoto → rephoto report (seller match) → AI Autofill → Background Removal Review (re-prices) → [Photo Verification (re-prices)] → live → [FB Export]
**6–8 separate pages or queues; price set in up to 3 places; "live" defined differently in the items filter vs. the Meta feed.**

**Pickup week setup (ops)**
Create shifts (3 conflicting paths) → staff them (Crew HQ quick-add or optimizer, which wipes the week) → set a storage unit per truck (**admin-only, so CDs can't**) → assign sellers (manual or auto) → order stops (shift-wide nearest-neighbour, or per-truck drag) → notify (window hardcoded "10am–3pm")

**Driver pickup shift**
Start (reload) → each stop: Completed/Issue → notes → confirm → **full page reload** → once all stops are resolved: place each item (Assign → unit → zone → Save, ~4 taps each) → End → confirm page → done.
No photo is taken at pickup stops. The only pickup photo tool is Quick Capture.

---

## 4. Broken right now (found during the inventory, not fixed)

| What | Evidence |
|---|---|
| **Crew Quick Capture can't save.** The Save button stays off until a category is picked, but neither crew route passes `categories`, so the grid is empty. | `quick_capture_modal.html:25,148`; renders at app.py:10461, :10708 pass no categories |
| "+ New Seller" button on Items calls a deleted route | items.html:1213 → `/admin/warehouse/seller/create` (removed in b52e16b) |
| AI reset-all and warehouse photo-note call deleted routes | items.html:2210, warehouse.html:805 |
| Items "Export CSV" is shown to plain admins but is super-admin only | `admin_export_items` guard |
| Campus directors can't set a truck's storage unit, so they can't start a truck | `assign_unit` is admin-only (:12264) |
| Week delete skips DeliveryStop / RescheduleToken / DeliveryRun / DeliveryRoutePlan | :13606, foreign-key failure risk |
| Pickup orders get delivery wording on the success page and email; the promised "ready to collect" email doesn't exist | item_success.html; app.py:1310–1340 |
| Displayed Flexible discount comes from an AppSetting; the charged one comes from the Stripe coupon, so they can differ | checkout_review |
| Crew login → `/dashboard` → bounced to **seller onboarding** if the worker has no items | app.py:7044 |
| Unsubscribe page has uncommitted edits | `templates/unsubscribe_confirm.html` (pre-existing) |

---

## 5. Contradictions in what we tell customers

- **Payout:** "Straight 50/50" (become-a-seller) vs. "20% growing to 100% as you refer friends" (about.html:112) vs. a retired-route flash about referral-based rates
- **Room value:** "$300–$600 typical" vs. the example table, which totals $230–$415 (parents)
- **Approval time:** 1 day vs. 1–2 days
- **Testimonials** are Davidson '26 students on a UNC site
- **"Free pickup" / "$0 upfront" / "It's Free"** everywhere. All of it goes away with the paid model.

---

## 6. Dead, duplicate and legacy (cleanup candidates)

**Templates never rendered:** `signup.html`, `upload.html`, `upgrade_boost_success.html`, `upgrade_pickup.html`, `director.html`, `reserve_success.html`, `_inventory_cards.html`, `admin/storage_index.html`, `admin/routes.html`, `admin/route_settings.html`. `admin.html` / `admin_sidebar.html` / `admin_approve.html` are POST-only or `?item=`-only.

**Routes that only redirect or flash:** `/inventory`, `/upgrade_pickup*`, `/upgrade_checkout`, `/onboard_cancel`, `/confirm_pickup` (Stripe $15 code still below the redirect), `/admin/routes`, `/admin/settings/route`, legacy `/checkout/*/<id>`.

**Still live with no UI:** `/buy_item/<id>` (creates real Stripe sessions with no tax or delivery), webhook CASE 1, `/create_checkout_session` item branch, `/admin/ops/delivery-truck-detail`, category CRUD (only in the legacy admin.html), schedule publish/unpublish/swap, generate-shifts, digest/send, toggle-featured.

**Duplicates:**
- Approval ×3
- AI review ×2
- AI generate ×2
- pickup nudge ×2
- make-admin ×2
- store toggles ×2
- signup ×4
- reschedule entry ×2
- pickup-location editor ×2
- ops page ×2
- delivery drawer ×2

**Retired concepts still in code:**
- organizer role and intake (the auto-scheduler still creates organizer assignments)
- referral codes
- payout boost
- pods (`dropoff_pod`)
- `collection_method` / `has_paid` / free vs. pro plan constants
- reservations (the model, `reserve_only_mode`, the 'reserved' card overlay; `test_reservations.py` imports functions that no longer exist)
- `worker_role`
- seller payment-method gates

**Unused static images:** `campusSwapPod.png`, `campusSwapPickup.png`, `freeplan.png`, `thirdPic.png`, `unitpic.jpg`, `logo.jpg`, `campus-swap-full-logo-dark.svg`.

---

## 7. Structural blockers for the pivot

### Junk removal
- **No "job" or "customer" concept.** A stop is either a `ShiftPickup` (FK to a seller User, unique per shift) or a `DeliveryStop` (FK to a BuyerOrder line). A junk job fits neither.
- **No upfront service payment.** Seller money only flows *out*. The only seller charge flow (`confirm_pickup` $15) is dead.
- **No per-truckload photos,** no before/after, no on-site junk-vs-keep tagging, no on-site quote, no customer sign-off.
- **No disposal tracking:** no dump/donate destination, no fees, no weigh tickets.
- **Capacity is measured in item units,** not truck volume.
- **Trucks are not an entity.** A truck is `(shift_id, truck_number)`, and its type is inferred from which stop table has rows.
- **Notify copy** says "selling with Campus Swap".

### Multi-school
- **Pickup dates are hardcoded for 2026** (`constants.py:81–105`), and code only accepts week1/week2 (app.py:5409, :19017).
- **One global pickup window** and **one warehouse** (Carrboro defaults, app.py:167). `StorageLocation` has no campus field.
- **UNC geography is hardcoded:** dorms and complexes in `constants.py:156–168` drive route clustering.
- **Slots are fixed** at am/pm/daily, with "10–3" labels and a hardcoded notify window.
- **`campus_director_school`** is free text and never filters anything. Every ops query is global.
- **The store picker** has one hardcoded option.

---

## 8. What works and should carry forward
- Stripe cart → Order/BuyerOrder → webhook as the source of truth (bundle, zones, tax, promo)
- Delivery routing: Google Routes plus fallback, per-truck plan cache, move-stop with history, buyer grouping
- Payouts page (reconciliation, CSV)
- Warehouse floor and rephoto pipeline, storage zones
- SMS and email infrastructure (Twilio, Resend throttling, reschedule tokens)
- Crew delivery view (AJAX, polling, proof-of-delivery photo). This is the model the pickup view should copy.
- Seller progress tracker concept
- Campus director role plus `_has_ops_access()`, which is the seed of per-school ops
