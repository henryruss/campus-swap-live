# Feature Spec B — Shopping Cart, Multi-Item Checkout & Bundle & Save

> **Read `CODEBASE.md` first**, and **build Spec A (`feature_delivery_fees.md`) before this one** — Spec B depends on the zone/tax/flexible logic and the Stripe coupon from Spec A. Verify every route, model, helper, and AppSetting against the actual code before changing it.

> **What Spec B does to Spec A:** Spec A put delivery/tax fields on `BuyerOrder` for single-item purchases. Spec B introduces an **`Order` parent** (where order-level money lives), turns `BuyerOrder` into a **line item** under an Order, **backfills** existing orders, and **refactors the checkout routes** so both single-item and multi-item purchases flow through the cart → Order pipeline. This is a planned, non-destructive promotion — see Model Changes § Migration.

---

## Goal

Buyers can only purchase one item at a time today. We are adding a **cart** so buyers can buy multiple items in a **single Stripe payment with one delivery fee**, and a **Bundle & Save** incentive: **2+ items → free delivery.** This also unlocks higher average order value and makes routes more efficient (more items per stop).

**Rules carried/extended from Spec A:**
- Delivery fee is **per order**, not per item, computed from the buyer's distance/zone (Spec A logic).
- **Bundle & Save:** an order with **2 or more items** gets **free delivery** (fee = $0), regardless of zone.
- **Sales tax:** 7.25% on the **sum of item prices only** (per-item rounded then summed), never on delivery.
- **Flexible Delivery (−$5):** applied via the Spec A Stripe coupon.
  - Single-item order: the $5 comes off the delivery fee (net effect, via coupon).
  - 2+ item order (delivery already free): the $5 comes off the **order total** (Henry's explicit decision).
  - Both cases are the same mechanism: full line items + a $5 coupon when flexible.
- Stripe's processing fee (2.9% + $0.30) is **absorbed silently**.

---

## UX Flow

### Adding to cart
1. **Product page** gains two actions:
   - **"Add to Cart"** — adds the item, stays on the page, shows a toast and updates the nav cart badge. Places a **hold** on the item (see Business Logic § Holds).
   - **"Buy Now"** — adds the item and redirects to `/cart`.
2. **Nav** shows a cart icon with an item-count badge (via a context processor) on every page.

### Cart page (`GET /cart`)
- Lists each cart item: thumbnail, title, price, "Remove."
- Shows **items subtotal**.
- **Bundle hint:** if exactly 1 item → "Add 1 more item for **free delivery**!" If 2+ → "🎉 You've unlocked free delivery."
- **"Proceed to Checkout"** button.
- **Empty state** with a "Browse the shop" link.
- If any item in the cart has become unavailable (sold, or its hold was claimed by a completed order), show it greyed with "No longer available" and a prompt to remove before proceeding.

### Checkout (order-level — refactored from Spec A's per-item routes)
3. **`POST /cart/checkout`** — validates every cart item is still available; if not, bounce back to `/cart` with a message and auto-remove the dead items. On success, store the active cart reference in the session and redirect to the address step.
4. **Address step** (`GET/POST /checkout/delivery`) — **no longer takes an `item_id`**; it operates on the whole cart/order. Geocode → distance → zone (Spec A helper). Out of range (>20 mi) → re-render with error. In range → store pending order context in session → redirect to review.
5. **Review step** (`GET /checkout/review`) — order breakdown:
   - Each item line (title + price).
   - Sales tax.
   - Delivery: zone fee if 1 item; **"FREE — Bundle & Save"** if 2+.
   - **Flexible Delivery** toggle (−$5), shown only if the Spec A coupon is configured. JS updates displayed total.
   - Order total.
   - "Proceed to Payment."
6. **`POST /checkout/review`** — recompute everything server-side, re-validate availability of all items, create one Stripe Checkout Session (one line item per cart item + tax line + delivery line if >$0, plus the $5 coupon if flexible), redirect to Stripe.
7. **Stripe Checkout** → buyer pays once for the whole order.
8. **Webhook** (`checkout.session.completed`) — source of truth: create the `Order` (status `paid`), create one `BuyerOrder` line per item, mark **all** items sold, clear the cart, send one confirmation email listing all items + delivery timing.
9. **Success page** — lists all purchased items and the delivery-timing copy (standard vs flexible).

### Guest carts & login
- Guests get a cart keyed by a signed `cart_token` (session/cookie). Logged-in users' carts key on `user_id`.
- On login/registration, if a guest cart exists in the session: if the user has no active cart, claim it (set `user_id`); if they already have one, **merge** (union of items, dedupe by `item_id`, drop any now-unavailable).

### Edge cases
- **Same item added twice** → no-op (one `CartItem` per item per cart; unique constraint).
- **Item held by another active cart** → "Add to Cart"/"Buy Now" blocked with "Someone's checking out this item — try again shortly." (See holds.)
- **Hold expires while item sits in a cart** → item silently becomes addable by others; if it gets sold by someone else, the holder sees "No longer available" at `/cart` or `POST /cart/checkout` and it's removed before payment.
- **All cart items become unavailable before payment** → bounce to `/cart` (now empty) with an explanation; never create a Stripe session for zero items.
- **Cart empty at `/checkout/*`** → redirect to `/cart`.
- **Bundle of 2+ where one item is removed at review, dropping to 1** → recompute: delivery fee returns; the review page must reflect the change (re-fetch on each GET; the "Proceed" POST recomputes regardless).
- **Webhook race (two paid orders touch the same item)** → per-item guard in the webhook (see Business Logic § Double-sale guard): mark only still-available items sold; flag the conflict for manual refund; the rest of the order proceeds.

---

## New Routes

| Method | Path | Function | Description |
|--------|------|----------|-------------|
| POST | `/cart/add/<item_id>` | `cart_add` | Add item to the current cart (create cart if needed), place a hold. Returns JSON `{count}` for async add, or redirects for "Buy Now". Blocks if item unavailable/held by another cart. |
| POST | `/cart/remove/<item_id>` | `cart_remove` | Remove item; release its hold. |
| GET | `/cart` | `cart_view` | Cart page. |
| POST | `/cart/checkout` | `cart_checkout` | Validate availability, store cart ref in session, redirect to address step. |
| GET/POST | `/checkout/delivery` | `checkout_delivery` (**refactor** — drop `<item_id>`) | Order-level address + geocode + zone. |
| GET | `/checkout/review` | `checkout_review` (**refactor** — drop `<item_id>`) | Order-level breakdown + flexible toggle. |
| POST | `/checkout/review` | `checkout_review` | Recompute, re-validate, create multi-line Stripe session (+coupon), redirect. |
| POST | `/webhook` | `webhook` (existing — modify) | On `checkout.session.completed` for a cart order: create `Order` + `BuyerOrder` lines, mark all items sold, clear cart, email. |

**Refactor note:** the Spec A routes `/checkout/delivery/<item_id>` and `/checkout/review/<item_id>` are replaced by the order-level versions above. The single-item path now goes: "Buy Now" → add to cart (1 item) → `/cart` → checkout. Keep a redirect from the old per-item URLs if any emails/links reference them. **Cart context processor** injects the nav badge count on every page.

---

## Model Changes (migration required — Flask-Migrate, with a data backfill)

### New: `Order` (the order-level parent)
| Field | Type | Notes |
|-------|------|-------|
| `id` | PK | |
| `buyer_id` | FK → User, nullable | Null for guest purchases. |
| `buyer_email`, `buyer_name` | String | Captured from session/Stripe. |
| `delivery_street/city/state/zip` | String | |
| `delivery_lat`, `delivery_lng` | Float, nullable | |
| `distance_miles` | Float, nullable | |
| `delivery_zone` | Integer, nullable | Null when bundle-free and zone irrelevant; still record it for ops if available. |
| `delivery_fee` | Numeric(10,2), default 0 | Zone fee, or 0 when `bundle_free_delivery`. |
| `bundle_free_delivery` | Boolean, default False | True when ≥2 items. |
| `is_flexible_delivery` | Boolean, default False | |
| `flexible_discount` | Numeric(10,2), default 0 | $5 when flexible. |
| `sales_tax` | Numeric(10,2), default 0 | Sum of per-item tax. |
| `items_subtotal` | Numeric(10,2), default 0 | Sum of item prices. |
| `total_paid` | Numeric(10,2), default 0 | `items_subtotal + sales_tax + delivery_fee − flexible_discount`. |
| `stripe_checkout_session_id` | String, nullable | Reconciliation + webhook idempotency. |
| `status` | String, default 'pending' | `pending` → `paid` (set by webhook) → (`cancelled`). |
| `created_at`, `paid_at` | DateTime | UTC. |

### Modify: `BuyerOrder` → becomes the per-item line under an Order
- Add `order_id` (FK → Order, nullable during migration, then expected non-null for new rows).
- Add `item_price_paid` (Numeric(10,2)) — snapshot of the item price at purchase.
- Add `item_sales_tax` (Numeric(10,2)) — per-item tax (so `Order.sales_tax = Σ item_sales_tax`).
- Keep `item_id` (one item sells once — unique).
- The Spec A delivery/address columns on `BuyerOrder` (`delivery_zone`, `delivery_fee`, `is_flexible_delivery`, `flexible_discount`, `sales_tax`, `distance_miles`, `items_subtotal`, `total_paid`, `stripe_checkout_session_id`, address fields) become **legacy** — leave them in place (non-destructive), stop writing them for new orders; `Order` is the source of truth going forward.

### New: `Cart` and `CartItem`
- **`Cart`**: `id`, `user_id` (FK → User, nullable), `session_token` (String, nullable — for guests), `created_at`, `updated_at`. One active cart per user / per guest token.
- **`CartItem`**: `id`, `cart_id` (FK → Cart), `item_id` (FK → InventoryItem), `added_at`. **Unique (`cart_id`, `item_id`).**

### Migration / backfill (non-destructive — use a Flask-Migrate data migration, not raw one-off SQL)
1. Create `order`, `cart`, `cart_item` tables; add `order_id`, `item_price_paid`, `item_sales_tax` to `buyer_order`.
2. **Backfill one `Order` per existing `BuyerOrder`:** copy address/lat/lng/distance/zone/`delivery_fee`/`is_flexible_delivery`/`flexible_discount`/`sales_tax`/`total_paid`/`stripe_checkout_session_id` from the BuyerOrder up to the new Order; set `status='paid'` and `paid_at` from the existing record; set `buyer_id`/email/name from the linked item's buyer if available. For pre-Spec-A legacy orders (free delivery, no tax recorded) set `delivery_fee=0`, `sales_tax=0`, `delivery_zone=NULL`, `bundle_free_delivery=False`.
3. Set `buyer_order.order_id` to the new Order; set `item_price_paid = items_subtotal` (or the item's recorded price) and `item_sales_tax = sales_tax`.
4. Verify counts match before/after; this is reversible (downgrade drops the new tables/columns). Follow the project's diagnose-before-destructive practice — run the backfill against a copy/locally first.

### AppSettings (key/value, fallback defaults in code)
| Key | Default | Meaning |
|-----|---------|---------|
| `cart_hold_minutes` | `30` | How long an item is held by being in an active cart. |
| `bundle_min_items` | `2` | Minimum items for free delivery. |

(Plus all Spec A settings, reused unchanged.)

---

## Template Changes

- **`templates/product.html`** — add "Add to Cart" + "Buy Now" buttons (preserve reserve-only / store-closed gating).
- **`templates/layout.html`** — add the cart icon + count badge to the nav (desktop + mobile). This is the one allowed nav change for this feature.
- **`templates/cart.html`** (**new**) — cart list, subtotal, bundle hint, unavailable-item handling, proceed button, empty state. Mobile-first; reuse `.card`, `.btn-primary`.
- **`templates/checkout_delivery.html`** — refactor to order-level (no single item; may show a compact order summary).
- **`templates/checkout_review.html`** — refactor to list all items, show delivery as fee or "FREE — Bundle & Save," keep the flexible toggle.
- **`templates/item_success.html`** — list all purchased items; standard vs flexible timing copy.
- **Admin** — order views read from `Order` (with its `BuyerOrder` lines): show items, subtotal, tax, delivery fee, bundle flag, flexible flag, total. Update the lifecycle/orders screens accordingly.

---

## Business Logic

### Holds (prevent double-add / double-sale without a cron)
An item is **held** if it appears in a `CartItem` belonging to a cart whose `updated_at` is within `cart_hold_minutes` **and** the item is still `available`. Lazy expiry — no scheduled job; just check the window on read.
- `item_is_held(item, exclude_cart_id=None)` → bool.
- `/cart/add` blocks (with message) if the item is sold or held by a different active cart.
- Touch `cart.updated_at` on add/remove to keep the hold fresh while the buyer is active.
- When an `Order` is paid (webhook), remove those items from **all** carts and mark them sold, so other buyers holding them see "No longer available."

### Bundle & Save + delivery fee
```
item_count = number of cart items
if item_count >= bundle_min_items:
    bundle_free_delivery = True
    delivery_fee = 0
else:
    bundle_free_delivery = False
    delivery_fee = zone_fee            # Spec A calculate_delivery_zone(distance)
```

### Tax
Per-item: `item_sales_tax = round(item.price * sales_tax_rate, 2)`. `Order.sales_tax = Σ item_sales_tax`. Never tax delivery.

### Order total (server-side; client toggle is cosmetic)
```
items_subtotal    = Σ item.price
sales_tax         = Σ item_sales_tax
flexible_discount = flexible_delivery_discount if is_flexible else 0   # $5
total_paid        = items_subtotal + sales_tax + delivery_fee - flexible_discount
total_paid        = max(total_paid, items_subtotal + sales_tax - flexible_discount)   # safety floor; never negative
```
For a single-item order, `delivery_fee` is the zone fee and the coupon takes $5 off → net delivery = fee − 5. For 2+ items, `delivery_fee = 0` and the coupon takes $5 off the total — matching Henry's decision.

### Stripe Checkout Session (multi-line)
- One line item per cart item: `{ name: item.description, unit_amount: to_cents(item.price), quantity: 1 }`.
- One tax line: `{ name: "Sales Tax (7.25%)", unit_amount: to_cents(sales_tax), quantity: 1 }`.
- Delivery line **only if** `delivery_fee > 0`: `{ name: "Delivery Fee — Zone N", unit_amount: to_cents(delivery_fee), quantity: 1 }`.
- If `is_flexible`: `discounts=[{ "coupon": stripe_flexible_coupon_id }]` (Spec A coupon). No negative line items.
- **Metadata:** put the `Order.id` (create the Order as `status='pending'` **before** redirecting) and a compact list of item ids. The webhook looks up the pending Order by id (and/or session id), flips it to `paid`, and creates the `BuyerOrder` lines — cleaner than packing every item into metadata and avoids Stripe's limits. (This differs from Spec A's metadata-only approach; the multi-item order needs a pending record.)
- `success_url` → success page with the order id; `cancel_url` → `/cart`.

> Creating a `pending` Order pre-payment is fine — **items are still only marked sold in the webhook** (project rule #4). If the buyer abandons, the pending Order stays `pending` (harmless; can be swept later).

### Webhook (source of truth)
On `checkout.session.completed`:
1. Find the pending `Order` by id (metadata) / `stripe_checkout_session_id`. **Idempotency:** if already `paid`, no-op.
2. Set `status='paid'`, `paid_at`, `buyer_email`/`buyer_name` from the session.
3. For each item in the order: **double-sale guard** — if `item.status != 'available'`, skip marking it sold, flag it for manual refund (admin-visible), and note it on the Order; otherwise create the `BuyerOrder` line (`order_id`, `item_id`, `item_price_paid`, `item_sales_tax`), mark the item sold (`status='sold'`, `sold_at`).
4. Remove all order items from every cart; touch carts.
5. Send one confirmation email listing all purchased items + delivery timing.

### Guest cart token & merge
Store a signed `cart_token` in the session for guests; `Cart.session_token` matches it. On login, run the merge described in UX Flow. Keep it simple and idempotent.

---

## Constraints (do NOT touch / must preserve)

1. **Stripe webhook is the source of truth.** Items are marked sold only in the webhook — never from success URLs, never at Order-pending creation. (Project rule #4.)
2. **All money computed server-side**; the flexible toggle is cosmetic until the server recomputes.
3. **Tax on item prices only**; delivery never taxed. **Stripe fee absorbed silently.**
4. **Never store computed seller payout** — runtime only via `_get_payout_percentage(item)`. (Project rule #7.)
5. **Migration + non-destructive backfill** via Flask-Migrate; diagnose before any destructive step; never modify the DB directly; keep production and local DBs separate. (Project rule #5 + Henry's standing practice.)
6. **Reuse Spec A** zone/tax/flexible helpers and the Stripe coupon — do not reimplement or fork them.
7. **Bulk SQL DELETE in FK order** if any cleanup of deep chains is needed (project rule #10) — but the backfill itself is additive.
8. **Server-rendered only**, form POST → redirect; vanilla JS for the cart badge, add-to-cart toast, and review toggle. Async "Add to Cart" may use `fetch` returning JSON (allowed exception for non-disruptive actions), but the cart and checkout state still live server-side. CSS variables; extend `layout.html`. (Project rules #1–3.)
9. **Eastern time** for displayed dates; UTC storage. (Project rule #9.)
10. **One `CartItem` per item per cart** (unique constraint); **one `BuyerOrder` per item** (an item sells once).
11. **Preserve** reserve-only mode, store-open gating, teaser mode, and the existing shop visibility gate — none of this should change what's purchasable beyond the new holds.

---

## Testing checklist

- [ ] Add to cart updates the badge and holds the item; a second buyer can't add the held item.
- [ ] Remove releases the hold; hold auto-expires after `cart_hold_minutes` and the item becomes addable again.
- [ ] 1 item → zone delivery fee applies; cart shows "add 1 more for free delivery."
- [ ] 2+ items → delivery free; review shows "FREE — Bundle & Save."
- [ ] Tax = Σ per-item tax; delivery never taxed.
- [ ] Flexible on, single item → coupon −$5 (net delivery = fee−5). Flexible on, 2+ items → −$5 off total (delivery already $0).
- [ ] One Stripe session covers all items + tax + (delivery if >0) + coupon; no negative line items.
- [ ] Webhook creates `Order` (paid) + one `BuyerOrder` per item, marks all sold, clears carts, sends one email; redelivery is idempotent.
- [ ] Double-sale race → only available items sold, conflict flagged, rest of order completes.
- [ ] Item sold elsewhere while in cart → shown unavailable at `/cart`, removed before checkout; never charged.
- [ ] Guest cart persists across pages; merges into the user cart on login.
- [ ] **Migration backfill:** every pre-existing `BuyerOrder` gets exactly one `Order`; counts match; legacy free-delivery orders backfill with fee/tax 0; downgrade cleanly drops new tables/columns.
- [ ] Empty cart can't reach a Stripe session; direct `/checkout/*` with empty cart redirects to `/cart`.
- [ ] Mobile: cart, review, and badge all read cleanly at ~390px; no hardcoded colors.

---

## After the build
Update `CODEBASE.md` (Order/Cart/CartItem models, refactored checkout routes, holds, cart context processor, the `BuyerOrder` line-item change), `HANDOFF.md` (what shipped, the backfill migration + verification, deviations), `DECISIONS.md` (Order-parent model, cart holds via lazy expiry, Bundle & Save = free delivery at ≥2 items, flexible −$5 off total for bundles, pending-Order + webhook pattern superseding Spec A's metadata-only approach), and `website-feature-log.md` (buyer cart/checkout sections). Note every deviation from this spec explicitly.
