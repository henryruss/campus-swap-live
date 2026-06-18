# Feature Spec — Payment & Checkout Test Suite

> Companion to `feature_delivery_fees.md` (Spec A) and `feature_cart_bundle.md` (Spec B). This adds automated tests for everything that touches money. **Build the tests for Spec A alongside Spec A, and the tests for Spec B alongside Spec B.**

> **Before writing a single test, read `tests/conftest.py` and `tests/test_account_deletion.py`.** Match their conventions exactly: class-grouped tests (`class TestX:`), descriptive `test_*` methods, the existing fixtures (`client`, `admin_client`, `seller_client`, app context, `db.session`), and the existing test-DB setup. Do not invent a new harness.

---

## Goal

This logic charges real customers real money and includes a migration that rewrites existing order records. A wrong rounding direction, an off-by-one zone boundary, or a botched backfill is a billing dispute, not a cosmetic bug. These tests pin down the exact financial behavior and the migration's correctness so regressions surface before deploy.

**Two files:**
- `tests/test_delivery_fees.py` — Spec A (zone, tax, single-item totals, checkout routes, webhook).
- `tests/test_cart_bundle.py` — Spec B (cart, holds, bundle math, multi-item totals + tax, multi-line Stripe session, webhook, backfill).

**The expected values in this document are authoritative.** If the implementation produces a different number, the implementation is wrong — fix it to match these values (the rounding rules below are deliberate).

---

## Two canary tests (these justify the whole suite)

1. **Tax rounding must be round-half-up, not banker's rounding.** A `$2.00` item taxed at 7.25% is `0.1450`. Python's built-in `round()` uses banker's rounding (round-half-to-even) and returns `0.14`; sales tax must round half **up** to `0.15`. The implementation must compute tax as `(Decimal(price) * Decimal(str(rate))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)` — Decimals from the string setting, never floats. The `$2.00 → $0.15` test fails on any naive `round()` implementation. **This is the single most important test in the suite.**

2. **Multi-item tax is per-item-rounded-then-summed, not summed-then-taxed.** Two items at `$50` and `$30`: per-item tax is `3.63 + 2.18 = 5.81`. Taxing the `$80` subtotal directly gives `5.80`. These differ by a cent; the suite locks in `5.81`.

---

## Mocking strategy (no live network, no live Stripe)

- **Zone logic:** test `calculate_delivery_zone(distance)` directly with literal distances — it's a pure function, no mocking needed.
- **Geocoding:** for route-level tests, monkeypatch `geocode_address` to return a fixed `(lat, lng)` and `haversine_miles` to return a chosen distance. Never hit Nominatim in tests.
- **Stripe session creation:** monkeypatch `stripe.checkout.Session.create` with a mock that returns an object exposing `.id` and `.url`, and **capture the kwargs it was called with** so tests can assert on `line_items` and `discounts`.
- **Stripe webhook:** monkeypatch `stripe.Webhook.construct_event` to return a crafted event dict (skips signature verification), then POST to `/webhook` (or call the handler directly, matching however the existing webhook is structured).
- **Email:** monkeypatch `send_email` to record calls; assert it fired once with the right recipient, never actually send.

Add these as fixtures/helpers in `conftest.py` if they'll be reused (e.g. a `mock_stripe` fixture, a `make_item(price=..., status='available')` factory if one doesn't already exist). Reuse existing item/seller factories if they're already there.

---

## File: `tests/test_delivery_fees.py` (Spec A)

### `class TestZoneCalculation`
Drive `calculate_delivery_zone(distance_miles)` directly. Upper bounds are inclusive.

| distance (mi) | expected zone | expected fee |
|---|---|---|
| 0 | 1 | 15 |
| 3.2 | 1 | 15 |
| 5.0 | 1 | 15 |
| 5.01 | 2 | 20 |
| 10.0 | 2 | 20 |
| 10.01 | 3 | 25 |
| 15.0 | 3 | 25 |
| 15.01 | 4 | 30 |
| 20.0 | 4 | 30 |
| 20.01 | `None` (rejected) | — |
| 50 | `None` (rejected) | — |

Methods: `test_zone_1_lower_bound`, `test_zone_1_inclusive_upper`, `test_zone_2_just_over_boundary`, … `test_exactly_20_miles_is_zone_4`, `test_just_over_20_miles_rejected`, `test_far_distance_rejected`. Also `test_zone_config_read_from_appsettings` (override the AppSetting and confirm fees change) and `test_zone_falls_back_to_defaults_when_setting_absent`.

### `class TestSalesTax`
Drive `compute_sales_tax(price)`. Rate 0.0725, **ROUND_HALF_UP**.

| price | expected tax |
|---|---|
| 85.00 | 6.16 |
| 2.00 | **0.15** ← canary |
| 50.00 | 3.63 |
| 30.00 | 2.18 |
| 20.00 | 1.45 |
| 33.00 | 2.39 |
| 7.00 | 0.51 |
| 200.00 | 14.50 |
| 0.00 | 0.00 |

Methods include `test_tax_two_dollar_item_rounds_half_up` (the canary), `test_tax_eighty_five_dollar_item`, `test_tax_never_applied_to_delivery_fee` (assert delivery fee is not in the taxable base — verify via the total math, below), and `test_tax_rate_read_from_appsettings`.

### `class TestSingleItemTotal`
Drive the server-side total computation used at `POST /checkout/review`.

| item | zone (fee) | flexible | subtotal | tax | delivery | discount | **total** |
|---|---|---|---|---|---|---|---|
| 85 | 1 ($15) | no | 85.00 | 6.16 | 15.00 | 0 | **106.16** |
| 85 | 1 ($15) | yes | 85.00 | 6.16 | 15.00 | 5.00 | **101.16** |
| 200 | 4 ($30) | no | 200.00 | 14.50 | 30.00 | 0 | **244.50** |
| 200 | 4 ($30) | yes | 200.00 | 14.50 | 30.00 | 5.00 | **239.50** |

`test_total_excludes_delivery_from_tax` should assert that for the `$85 / Zone 1` case, tax is exactly `6.16` (tax on `85`, not on `100`).

### `class TestCheckoutRoutes`
Use `client` / `seller_client`, monkeypatch geocoding.
- `test_address_in_range_redirects_to_review` — geocode → distance 3 mi → redirect to review; session holds pending context.
- `test_address_out_of_range_rejected` — distance 25 mi → re-renders address form with the out-of-area message, no redirect, no Stripe call.
- `test_geocode_failure_rejected` — geocode returns `None` → handled gracefully, no charge.
- `test_review_without_session_redirects_to_address` — GET review with no pending session → redirect.
- `test_review_post_creates_stripe_session_with_correct_line_items` — assert captured `line_items` are `[item, tax, delivery]` with the cents above, and **no negative `unit_amount`**.
- `test_flexible_attaches_coupon` — with `is_flexible=True`, captured kwargs include `discounts=[{'coupon': <id>}]`; line items unchanged (full delivery line).
- `test_flexible_hidden_when_coupon_unset` — clear `stripe_flexible_coupon_id`; the review page does not offer the toggle and a posted `is_flexible` is ignored.
- `test_item_sold_between_review_and_pay_is_blocked` — mark the item sold, POST review → bounced, no Stripe session created.

### `class TestWebhook`
Monkeypatch `stripe.Webhook.construct_event` and `send_email`.
- `test_checkout_completed_creates_buyer_order` — `BuyerOrder` created with all fields (zone, fee, tax, flexible, discount, distance, total, session id); item `status == 'sold'`; email sent once.
- `test_webhook_is_idempotent` — same event twice → exactly one `BuyerOrder`, item sold once, one email.
- `test_webhook_double_sale_guard` — item already `sold` before the event → no duplicate `BuyerOrder`, an admin-visible flag/alert is created, no second sold-marking.
- `test_item_marked_sold_only_via_webhook` — hitting the success URL alone never marks an item sold.

---

## File: `tests/test_cart_bundle.py` (Spec B)

### `class TestCartOperations`
- `test_add_item_creates_cart_and_holds_item`
- `test_add_same_item_twice_is_noop` (unique constraint respected)
- `test_remove_item_releases_hold`
- `test_cart_badge_count_reflects_items`
- `test_guest_cart_persists_then_merges_on_login`

### `class TestItemHolds`
- `test_held_item_cannot_be_added_by_another_cart` — cart A holds item; cart B add is blocked.
- `test_hold_expires_after_window` — backdate cart A's `updated_at` beyond `cart_hold_minutes`; cart B can now add.
- `test_sold_item_removed_from_other_carts` — completing an order removes the item from any other cart and shows unavailable.

### `class TestBundleAndTotals`
Distance places the order in Zone 2 ($20) — but bundles override to free delivery.

| cart | subtotal | tax (per-item sum) | bundle? | delivery | flexible | discount | **total** |
|---|---|---|---|---|---|---|---|
| 1 × $50 | 50.00 | 3.63 | no | 20.00 (Zone 2) | no | 0 | **73.63** |
| 1 × $50 | 50.00 | 3.63 | no | 20.00 | yes | 5.00 | **68.63** |
| $50 + $30 | 80.00 | **5.81** ← canary | yes | 0.00 (free) | no | 0 | **85.81** |
| $50 + $30 | 80.00 | 5.81 | yes | 0.00 | yes | 5.00 | **80.81** |
| $50 + $30 + $20 | 100.00 | 7.26 | yes | 0.00 | no | 0 | **107.26** |

- `test_single_item_pays_zone_delivery`
- `test_two_items_get_free_delivery`
- `test_three_items_still_free_delivery`
- `test_multi_item_tax_is_per_item_then_summed` (the `5.81` canary — assert it is **not** `5.80`)
- `test_flexible_discount_comes_off_delivery_for_single_item`
- `test_flexible_discount_comes_off_total_for_bundle` (delivery already `$0`; total drops `$5`)
- `test_removing_item_from_bundle_restores_delivery_fee` (2 → 1 item recomputes the fee)

### `class TestMultiLineStripeSession`
Assert on captured `stripe.checkout.Session.create` kwargs.
- `test_one_line_item_per_cart_item`
- `test_tax_line_present`
- `test_delivery_line_present_for_single_item`
- `test_delivery_line_omitted_for_bundle` (fee `$0` → no delivery line)
- `test_coupon_attached_when_flexible`
- `test_no_negative_line_items` (across every scenario)
- `test_line_items_plus_discount_equal_total_paid`
- `test_pending_order_created_before_redirect` (status `pending`, not `paid`)

### `class TestMultiItemWebhook`
- `test_order_marked_paid_and_lines_created` — `Order.status == 'paid'`; one `BuyerOrder` line per item with `item_price_paid` / `item_sales_tax`; all items `sold`; cart cleared; one email listing all items.
- `test_webhook_idempotent_for_multi_item`
- `test_partial_double_sale_guard` — one item pre-sold; only the available items get sold + lined, the conflict is flagged, the Order still completes for the rest.
- `test_empty_cart_never_creates_session`

### `class TestBackfillMigration`
> Recommend the implementation extracts the backfill into a callable (e.g. `backfill_orders_from_buyer_orders()`) that the Alembic migration calls **and** the test calls — so the data logic is testable without running migrations.
- `test_one_order_created_per_legacy_buyer_order` — create N legacy `BuyerOrder` rows (no `order_id`), run the backfill, assert exactly N `Order` rows, each linked.
- `test_counts_match_before_and_after`
- `test_legacy_free_delivery_orders_backfill_with_zero_fee_and_tax`
- `test_spec_a_orders_promote_fields_to_order` — a Spec-A `BuyerOrder` (with fee/tax/zone) backfills an `Order` carrying those values up.
- `test_backfill_is_idempotent` — running it twice doesn't create duplicate Orders.

---

## What NOT to test
- Live Stripe API calls or real coupon creation (mock the session + webhook).
- Real geocoding / Nominatim (mock it).
- Stripe's own fee math (it's absorbed, never computed by us).
- UI rendering details beyond "the flexible toggle is/isn't present."

## Running
```
pytest tests/test_delivery_fees.py -v
pytest tests/test_cart_bundle.py -v
```
Run against the test DB only — never the local-dev or production database. Use the existing test-DB fixture setup from `conftest.py`; if the cart/order tests need new tables, ensure the test DB is created/migrated by the existing harness.

## After the build
Note in `HANDOFF.md` that the payment suite exists, how to run it, and the two canary cases. If any expected value here conflicts with what the implementation produced, the value here wins — fix the implementation, not the test.
