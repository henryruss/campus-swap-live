# Feature Spec A — Delivery Fees, Sales Tax & Flexible Delivery (Single-Item Checkout)

> **Read `CODEBASE.md` before starting.** Verify every route, model field, helper, and AppSetting referenced here against the actual code — do not assume. This spec **modifies the existing single-item delivery checkout**. It does **not** add a cart (that is Spec B, `feature_cart_bundle.md`). Ship this first; it works for single-item purchases on its own.

> **Relationship to Spec B:** Spec B introduces an `Order` parent model and a multi-item cart, and will refactor the checkout routes built here to operate at the order level. To keep the two consistent, this spec uses the **same flexible-delivery discount mechanism Spec B will use** (a Stripe coupon — see Business Logic § Flexible discount). Build it that way now so Spec B is purely additive.

---

## Goal

Today delivery is flat "Weekly Delivery · Free." We are introducing **zone-based delivery pricing** computed automatically from the buyer's address, plus **sales tax**, an optional **Flexible Delivery** discount, and correct charging through Stripe. Deliveries beyond the furthest zone (20 miles) are rejected.

Buyer-facing money must be exact and computed **server-side** (never trust the client). Stripe's webhook remains the source of truth for marking an item sold.

**Pricing model (all values configurable via AppSettings — see below):**

| Zone | Distance from warehouse | Fee |
|------|------------------------|-----|
| 1 | 0–5 miles | $15 |
| 2 | >5–10 miles | $20 |
| 3 | >10–15 miles | $25 |
| 4 | >15–20 miles | $30 |
| — | >20 miles | **Rejected** ("outside our delivery area") |

- **Sales tax:** 7.25% applied to the **item price only** — never to the delivery fee. Round to 2 decimals.
- **Flexible Delivery:** buyer opts in for a **$5 discount** in exchange for a 1–3 week delivery window (vs. standard next Friday/Saturday). For a single item, the $5 comes off the order total (effectively off the delivery fee).
- **Stripe processing fee (2.9% + $0.30):** absorbed by Campus Swap, **never displayed or added as a line item.**

> **Tax note (flag for Henry, not a build item):** This spec implements the rate and base from Ben's doc (7.25%, item-only). Worth confirming with an accountant whether NC treats delivery charges as taxable and whether marketplace-facilitator rules apply — it's wired to be configurable so the rate/base can change without a deploy.

---

## UX Flow

1. **Product page** — "Buy Now" links to `GET /checkout/delivery/<item_id>` (existing). Update the static "Weekly Delivery · Free" line to "Delivery calculated at checkout."
2. **Address step** (`GET /checkout/delivery/<item_id>`) — existing address form (street / city / state / zip). Buyer submits.
3. **POST** geocodes the address (existing Nominatim helper), computes straight-line distance from the warehouse (existing haversine helper), and determines the zone:
   - **Out of range (>20 mi or geocode fails):** re-render the address form with an inline error — "Sorry, we currently only deliver within 20 miles of campus." No charge, no redirect.
   - **In range:** store the pending delivery context in the session (address, lat/lng, distance, zone, zone fee, item price, computed tax) and redirect to the review step.
4. **Review step** (`GET /checkout/review/<item_id>`) — server-rendered breakdown:
   - Item title + price
   - Sales tax (7.25%)
   - Delivery fee (with zone label, e.g. "Delivery — Zone 2")
   - A **Flexible Delivery** toggle: "Save $5 — flexible delivery (1–3 weeks)." When toggled, JS updates the displayed total for UX only.
   - Order total
   - "Proceed to Payment" button.
5. **POST `/checkout/review/<item_id>`** — reads the `is_flexible` flag, **recomputes all amounts server-side**, creates a Stripe Checkout Session with line items (item, sales tax, delivery fee) and — if flexible — the $5 coupon, then redirects to Stripe.
6. **Stripe Checkout** — buyer pays. Campus Swap absorbs Stripe's fee silently.
7. **Webhook** (`checkout.session.completed`) — source of truth. Re-validates the item is still available, creates the `BuyerOrder` with all fee/tax/zone/flexible data from metadata, marks the item sold, sends the confirmation email.
8. **Success page** (`/item_success`) — copy reflects the chosen delivery speed: standard → "Expected next Friday/Saturday (batched weekly; may shift if volume is low)"; flexible → "Estimated 1–3 weeks; we'll give you a heads up before delivery."

### Edge cases

- **Geocode failure / ambiguous address** → treat as out of range with a "we couldn't verify that address" message; do not proceed to payment.
- **Exactly on a zone boundary** (e.g. 5.00 mi) → the lower zone's fee (upper bounds are inclusive: `distance <= boundary`).
- **Item sold between review and payment** → the webhook guard catches it (see Business Logic § Double-sale guard). The buyer should also be re-validated at `POST /checkout/review` (if `item.status != 'available'`, bounce to the product page with "This item is no longer available").
- **Session expired / user navigates directly to `/checkout/review/<id>` without a pending session** → redirect back to `GET /checkout/delivery/<id>`.
- **Reserve-only mode or store not open** → preserve existing gating on the product page; these states should not reach the fee flow.
- **`stripe_flexible_coupon_id` not configured** → hide the Flexible Delivery toggle entirely (fail-safe; never silently mischarge).

---

## New Routes

| Method | Path | Function | Description |
|--------|------|----------|-------------|
| GET | `/checkout/delivery/<item_id>` | `checkout_delivery` (existing — modify) | Address form. Unchanged structure; updated out-of-area error copy. |
| POST | `/checkout/delivery/<item_id>` | `checkout_delivery` (existing — modify) | Geocode + distance + zone. Reject if >20 mi or geocode fails (re-render with error). Else store pending context in session, redirect to review. |
| GET | `/checkout/review/<item_id>` | `checkout_review` (**new**) | Render the cost breakdown + Flexible Delivery toggle from session context. Redirect to delivery step if no pending session. |
| POST | `/checkout/review/<item_id>` | `checkout_review` (**new**) | Read `is_flexible`, recompute amounts server-side, re-validate item availability, create Stripe Checkout Session (+coupon if flexible), redirect to Stripe. |
| POST | `/webhook` | `webhook` (existing — modify) | On `checkout.session.completed` for an item purchase: re-validate availability, create `BuyerOrder` with new fields, mark sold, email. |

**Legacy route:** the existing `GET /checkout/pay/<item_id>` (`checkout_pay`) is superseded — session creation now happens in `POST /checkout/review`. Grep for references (templates, emails); update them to the new flow, and either delete `checkout_pay` or leave it as a redirect to `/checkout/delivery/<item_id>`. Do not leave two live session-creation paths.

---

## Model Changes

**Add the following fields to the existing `BuyerOrder` model. Migration required (`flask db migrate`).**

| Field | Type | Notes |
|-------|------|-------|
| `delivery_zone` | Integer, nullable | 1–4. |
| `delivery_fee` | Numeric(10,2), default 0 | The zone fee charged (the delivery line-item amount). |
| `is_flexible_delivery` | Boolean, default False, server_default '0' | |
| `flexible_discount` | Numeric(10,2), default 0 | $5 when flexible, else 0. |
| `sales_tax` | Numeric(10,2), default 0 | Tax on item price only. |
| `distance_miles` | Float, nullable | Straight-line distance recorded for ops. |
| `items_subtotal` | Numeric(10,2), default 0 | = item price (single item). |
| `total_paid` | Numeric(10,2), default 0 | `items_subtotal + sales_tax + delivery_fee − flexible_discount`. |
| `stripe_checkout_session_id` | String, nullable | For reconciliation + webhook idempotency. |

> **Do not store seller payout.** Payout stays computed at runtime via `_get_payout_percentage(item)` × sale price. Never persist a computed payout amount (per project rule #7).

> **Spec B note:** Spec B promotes the order-level fields above (zone, delivery_fee, is_flexible, flexible_discount, sales_tax, distance, total, session id, address) to a new `Order` parent and leaves these `BuyerOrder` columns as legacy via a backfill. Do not pre-build that here.

### AppSettings (no migration — key/value rows; provide hardcoded fallback defaults in code)

Use the existing AppSetting accessor (verify its exact name in `app.py`). Every read must fall back to a hardcoded default if the row is absent, so a missing row never breaks checkout (known prior failure mode).

| Key | Default | Meaning |
|-----|---------|---------|
| `sales_tax_rate` | `0.0725` | Decimal rate applied to item price. |
| `delivery_zone_boundaries` | `5,10,15,20` | Comma-separated upper-bound miles (inclusive). |
| `delivery_zone_fees` | `15,20,25,30` | Comma-separated fees aligned to boundaries. |
| `flexible_delivery_discount` | `5` | Dollar discount for flexible delivery. |
| `stripe_flexible_coupon_id` | (none) | Stripe Coupon id for the $5 flexible discount. If absent, Flexible toggle is hidden. |

Existing `warehouse_lat` / `warehouse_lng` are reused. The old `delivery_radius_miles` (default 50) is **replaced in effect** by the furthest zone boundary (20). Either set `delivery_radius_miles` to the last boundary or drive the cutoff directly from `delivery_zone_boundaries[-1]` — pick one and be consistent.

### One-time Stripe setup (document in the spec output / HANDOFF)
Create a Stripe Coupon: **$5.00 off, `amount_off=500`, `currency=usd`, `duration=once`**, name "Flexible Delivery." Put its id in the `stripe_flexible_coupon_id` AppSetting (and Render env if you mirror settings there). Provide a short snippet or `flask` shell command in the build notes so it's reproducible.

---

## Template Changes

- **`templates/checkout_delivery.html`** (existing) — update out-of-area / geocode-failure error messaging; otherwise structure unchanged.
- **`templates/checkout_review.html`** (**new**) — the cost-breakdown page. Extends `layout.html`. Shows item, sales tax, delivery fee (with zone), Flexible Delivery toggle (only if coupon configured), total, "Proceed to Payment." Vanilla JS updates the displayed total when the toggle changes (cosmetic only; the charge is recomputed server-side). Use CSS variables; reuse `.card`, `.btn-primary`. Render as a clean two-column or single-column summary; bottom-sheet-friendly on mobile.
- **`templates/item_success.html`** (existing) — branch the delivery-timing copy on `is_flexible`.
- **`templates/product.html`** (existing) — replace "Weekly Delivery · Free" with "Delivery calculated at checkout." Do not add fee math to the product page.
- **Admin** — on the admin order/lifecycle view, surface `delivery_zone`, `delivery_fee`, `sales_tax`, `is_flexible_delivery`, and `total_paid` for each sold item so ops can see what was charged.

---

## Business Logic

### Zone + fee helper
`calculate_delivery_zone(distance_miles)` → returns `(zone_number, Decimal fee)` or `None` if beyond the last boundary. Reads `delivery_zone_boundaries` and `delivery_zone_fees` from AppSettings (fallback defaults). Upper bounds inclusive (`distance <= boundary`). Reuse existing `geocode_address()` and `haversine_miles()`.

### Sales tax helper
`compute_sales_tax(item_price)` → `round(Decimal(item_price) * Decimal(sales_tax_rate), 2)`. Applied to item price only. Never include the delivery fee in the taxable base.

### Money math (compute server-side at `POST /checkout/review`; never trust client)
```
items_subtotal   = item.price
sales_tax        = compute_sales_tax(item.price)
delivery_fee     = zone_fee                      # from calculate_delivery_zone
flexible_discount = flexible_delivery_discount if is_flexible else 0
total_paid       = items_subtotal + sales_tax + delivery_fee - flexible_discount
```
Use `Decimal` throughout; convert to integer cents only when building Stripe line items: `to_cents(d) = int((Decimal(d) * 100).quantize(0, ROUND_HALF_UP))`.

### Stripe Checkout Session
Line items (no negative amounts — Stripe disallows them in Checkout):
1. `{ name: item.description, unit_amount: to_cents(item.price), quantity: 1 }`
2. `{ name: "Sales Tax (7.25%)", unit_amount: to_cents(sales_tax), quantity: 1 }`
3. `{ name: "Delivery Fee — Zone N", unit_amount: to_cents(delivery_fee), quantity: 1 }`

If `is_flexible`, attach the coupon: `discounts=[{ "coupon": stripe_flexible_coupon_id }]` (this is how the $5 is represented — it shows as "-$5.00" on Stripe and keeps line items non-negative). Do **not** also reduce the delivery line; the coupon is the single source of the discount.

**Metadata** (so the webhook can reconstruct the `BuyerOrder` — matches the existing metadata-driven pattern): `item_id`, `delivery_zone`, `delivery_fee`, `sales_tax`, `is_flexible_delivery`, `flexible_discount`, `distance_miles`, `items_subtotal`, `total_paid`, and the address fields (street, city, state, zip, lat, lng). All values stringified; well within Stripe's 50-key / 500-char limits.

`success_url` → `/item_success`, `cancel_url` → product page. Set `customer_email` if known.

### Webhook (source of truth — do not mark sold anywhere else)
On `checkout.session.completed` where metadata contains `item_id`:
1. **Idempotency:** if a `BuyerOrder` already exists for this `stripe_checkout_session_id`, no-op (Stripe redelivers).
2. **Double-sale guard:** reload the item; if `item.status != 'available'`, do **not** silently double-sell. Log it, create an admin-visible flag/alert ("paid order for already-sold item — manual refund needed"), and skip marking sold. Still record the payment attempt if useful. (Spec B adds cart holds that largely prevent this; the guard stays as a backstop.)
3. Create the `BuyerOrder` from metadata (all new fields). Mark the item sold (`status='sold'`, `sold_at`, existing fields). Send the existing buyer confirmation email with delivery-timing copy.

### Delivery window display
Use `_today_eastern()` for any date shown. Standard copy: "Expected next Friday/Saturday — deliveries are batched weekly and may shift to the following weekend if volume is low." Flexible copy: "Estimated 1–3 weeks; we'll give you a heads up before your delivery date." Plain text is fine; computing the literal next Fri/Sat date is a nice-to-have, not required.

---

## Constraints (do NOT touch / must preserve)

1. **Stripe webhook is the source of truth.** Never mark an item sold or record an order from the success URL or any client signal. (Project rule #4.)
2. **All money computed server-side.** The client's toggle is cosmetic; recompute fee/tax/total from server state before creating the session.
3. **Tax base is item price only** — never tax the delivery fee.
4. **Stripe's processing fee is absorbed silently** — never a line item, never displayed.
5. **Never store computed seller payout** — payout stays runtime via `_get_payout_percentage(item)`. (Project rule #7.)
6. **Migration required** for the `BuyerOrder` fields (Flask-Migrate). Never modify the DB directly. (Project rule #5.)
7. **Server-rendered only**, form POST → redirect, vanilla JS for the toggle only. CSS variables, extend `layout.html`. (Project rules #1–3.)
8. **AppSetting reads must have hardcoded fallback defaults** so a missing row can't break checkout.
9. **Eastern time** for any displayed date (`_now_eastern` / `_today_eastern`); timestamps stored UTC. (Project rule #9.)
10. **Do not build a cart, the `Order` model, or Bundle & Save here** — that is Spec B.
11. **Reuse** the existing `geocode_address()` / `haversine_miles()` helpers and the existing Stripe session + webhook plumbing; extend, don't duplicate.

---

## Testing checklist

- [ ] Address in each zone returns the correct fee ($15/$20/$25/$30); boundary distances (5.0/10.0/15.0/20.0) land in the lower zone.
- [ ] Address >20 mi (and a garbage address) → out-of-area error, no Stripe redirect, no order.
- [ ] Review page shows item + tax + delivery + total; total math is correct (e.g. $85 item, Zone 1 → $85 + $6.16 + $15 = $106.16).
- [ ] Tax is on item price only — delivery fee excluded from tax.
- [ ] Flexible toggle on → Stripe shows "-$5.00", total drops by $5; toggle off → full fee.
- [ ] `stripe_flexible_coupon_id` unset → Flexible toggle hidden; no flexible path reachable.
- [ ] Webhook creates `BuyerOrder` with all fields populated; item marked sold; email sent; redelivery is idempotent.
- [ ] Item sold between review and payment → webhook guard prevents double-sell and raises an admin flag.
- [ ] Direct hit to `/checkout/review/<id>` with no session → redirected to address step.
- [ ] Missing AppSetting rows → defaults apply, nothing breaks.
- [ ] No hardcoded colors; new template extends `layout.html`; mobile review page reads cleanly at ~390px.

---

## After the build
Update the reference docs to match: `CODEBASE.md` (new routes, `BuyerOrder` fields, AppSettings, helpers, the superseded `checkout_pay`), `HANDOFF.md` (what shipped, the Stripe coupon setup step, any deviations), `DECISIONS.md` (zone pricing, item-only tax, coupon-based flexible discount, 20-mile cutoff replacing the 50-mile radius), and `website-feature-log.md` (buyer delivery/checkout section). Note any deviations explicitly.
