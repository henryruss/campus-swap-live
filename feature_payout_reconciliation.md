# Spec #5 — Payout Reconciliation

## Goal

Replace the existing per-item payout tracking scattered across the main admin
panel with a dedicated `/admin/payouts` page that gives admins a clear,
seller-grouped queue of what's owed, to whom, and how to pay them. The new page
consolidates seller payout handles, unpaid item totals, intake and flag warnings,
and one-click per-item mark-paid into a single workflow. It also triggers a
payout confirmation email to the seller when each item is marked paid. The old
payout section on `admin.html` is removed and replaced with a link to this page.

---

## UX Flow

### Admin lands on `/admin/payouts`

The page has two tabs/sections:

**Unpaid** — sellers with at least one sold, unpaid item.
**Paid** — historical log of all paid items, reverse-chronological.

---

### Unpaid Queue

Sellers are listed as cards, sorted by **total unpaid amount descending** (largest
balance at the top — most urgency to pay).

Each seller card shows:

- Seller name + email
- Current payout rate (e.g. "40%") — pulled from `seller.payout_rate`
- Payout method badge (Venmo / PayPal / Zelle) + handle, styled as a copyable
  chip. Clicking the handle copies it to clipboard.
- Total unpaid amount (sum of payout amounts across all unpaid sold items)
- A row per unpaid sold item:
  - Item thumbnail (small)
  - Item title and item ID
  - Sale price → payout amount (e.g. "$80.00 → $32.00" for a 40% rate)
  - `sold_at` date
  - **Intake warning badge** (amber): shown if the item has no `IntakeRecord`.
    Label: "No intake record". Admin can still mark paid.
  - **Flag warning badge** (amber): shown if the item has an unresolved
    `IntakeFlag`. Label: "Flagged: [damaged|missing]". Links to
    `/admin/intake/flagged`. Admin can still mark paid.
  - "Mark Paid" button — per item. Requires confirmation (inline confirmation
    state: button changes to "Confirm?" with a checkmark + cancel X, no modal).

### Mark Paid — what happens

1. POST `/admin/payouts/item/<item_id>/mark_paid`
2. Sets `InventoryItem.payout_sent = True` and `InventoryItem.payout_sent_at`
   (new field — see Model Changes).
3. Sends payout confirmation email to seller (see Email section).
4. Page reloads. If that was the seller's last unpaid item, their card disappears
   from Unpaid. If they still have unpaid items, the card stays and that item row
   is gone.
5. PostHog event: `payout_marked_sent` (already exists — no change needed).

### Edge cases — Unpaid Queue

- **Seller has no payout handle**: card shows an amber warning banner: "Missing
  payout handle — ask seller to update their account." Mark Paid is still
  allowed (admin may have paid out of band).
- **Item is sold but not marked `status='sold'` in DB**: shouldn't be reachable
  via normal flows, but the query guards against it (see Business Logic).
- **Seller card with only flagged/intake-warning items**: card appears normally
  with warning badges. No blocking.

---

### Paid History Tab

Flat list of all paid items, reverse-chronological by `payout_sent_at`.

Columns: item thumbnail, item title, seller name (links to seller panel), sale
price, payout rate (%), payout amount, payout method + handle, `payout_sent_at`
date, "View Item" link to admin item edit page.

Paginated at 50 items per page.

---

### CSV Export

"Export Payouts CSV" button at top of page (visible on both tabs). Downloads all
sold items (paid and unpaid) with columns:

`item_id, item_title, seller_name, seller_email, payout_method, payout_handle,
sale_price, payout_rate, payout_amount, sold_at, payout_sent,
payout_sent_at, has_intake_record, has_unresolved_flag`

This replaces the existing `/admin/export/sales` CSV, which stays in place but
can be deprecated later.

---

## New Routes

| Method | Path | Function | Description |
|--------|------|----------|-------------|
| `GET` | `/admin/payouts` | `admin_payouts` | Main payout reconciliation page — unpaid queue + paid history |
| `POST` | `/admin/payouts/item/<item_id>/mark_paid` | `admin_payout_mark_paid` | Mark one item's payout as sent; triggers confirmation email |
| `GET` | `/admin/payouts/export` | `admin_payouts_export` | CSV export of all sold items with payout data |

All three routes require `is_admin`. No super admin restriction — any admin
should be able to process payouts.

---

## Model Changes

### New field on `InventoryItem`

```
payout_sent_at (DateTime, nullable)
```

Set to `_now_eastern()` (stored as UTC) when `payout_sent` is flipped to `True`
via the new mark-paid route. Existing items that were already marked paid before
this spec will have `payout_sent_at = NULL` — that's fine; they'll show in the
Paid tab without a timestamp (display as "—").

**Migration required.** One migration:
- Add `payout_sent_at` (DateTime, nullable) to `inventory_item`.

No other model changes. `payout_sent` (bool) already exists and remains the
source of truth. `payout_sent_at` is additive metadata.

---

## Template Changes

### New template: `admin/payouts.html`

Extends `layout.html`. Admin-only page.

Layout:

```
[Page header: "Payouts"]
[Export CSV button — top right]

[Tab bar: Unpaid (N) | Paid]

--- Unpaid tab ---
[Sorted seller cards]
  [Card header: name, email, payout rate badge, payout chip, total unpaid amount]
  [Item rows: thumbnail, title, price→payout amount, date, warning badges, Mark Paid button]

--- Paid tab ---
[Flat table: item, seller, sale price, rate %, payout amount, method+handle, date, link]
[Pagination]
```

CSS notes:
- Use `.card` class for seller cards.
- Warning badges use `--warning` or amber equivalent from the design system.
- Payout method chip: pill-shaped, copyable. JS copies `payout_handle` to
  clipboard on click, briefly shows "Copied!" tooltip.
- Mark Paid inline confirmation: button click → JS swaps button inner HTML to
  "Confirm? ✓ ✗". Confirm submits the form. ✗ reverts. No page reload until
  confirmed. This prevents accidental double-pays.

### Modified template: `admin/admin.html`

Remove the existing payout tracking section (item-level `payout_sent` rows and
"Mark Paid" buttons). Replace with a card or banner:

```
Payouts
X items awaiting payout · $Y total owed
→ Go to Payout Dashboard
```

Link goes to `/admin/payouts`. The count and total are injected by the existing
`admin_panel` route context (add two new variables: `unpaid_items_count`,
`unpaid_total`).

### No other template changes.

The seller profile panel (`admin/seller_panel.html`) already shows `payout_rate`
and item payout status per the referral program spec. It does not need a
"Mark Paid" button — that workflow lives on `/admin/payouts`.

---

## Business Logic

### Query for unpaid queue

```python
unpaid_items = (
    InventoryItem.query
    .filter_by(is_sold=True, payout_sent=False)
    .filter(InventoryItem.status == 'sold')
    .order_by(InventoryItem.sold_at.asc())
    .all()
)
```

Group by `seller_id` in Python. Sort seller groups by sum of payout amounts
descending.

### Payout amount calculation

Use the existing `_get_payout_percentage(item)` helper, which reads
`item.seller.payout_rate / 100`. Do not use `collection_method` — that field
no longer drives payout calculations.

```python
payout_amount = round(item.price * _get_payout_percentage(item), 2)
payout_rate_pct = item.seller.payout_rate  # integer, e.g. 30
```

Never store the computed payout amount — always compute at render/export time.
This ensures the displayed amount is always consistent with what the seller sees
on their dashboard.

### Intake warning logic

For each unpaid sold item, check:

```python
has_intake = db.session.query(
    IntakeRecord.query.filter_by(item_id=item.id).exists()
).scalar()
```

Show amber "No intake record" badge if `has_intake` is False.

Batch this across all unpaid items in one query to avoid N+1:

```python
intake_item_ids = {
    r.item_id for r in
    IntakeRecord.query
    .filter(IntakeRecord.item_id.in_(unpaid_item_ids))
    .with_entities(IntakeRecord.item_id)
    .all()
}
```

### Flag warning logic

Similarly batch:

```python
flagged_item_ids = {
    f.item_id for f in
    IntakeFlag.query
    .filter(
        IntakeFlag.item_id.in_(unpaid_item_ids),
        IntakeFlag.resolved == False,
        IntakeFlag.item_id != None
    )
    .with_entities(IntakeFlag.item_id, IntakeFlag.flag_type)
    .all()
}
```

Pass both sets to the template as context. Template checks membership, not DB.

### Mark paid — guard rails

Before setting `payout_sent = True`, the route must confirm:
1. `item.is_sold == True` and `item.status == 'sold'`
2. `item.payout_sent == False` (idempotency guard — double POST returns a flash
   "Already marked paid" and redirects, no error)

No other blocking conditions. Warnings (no intake, unresolved flag) are
display-only and do not block the POST.

### CSV export columns and computation

`payout_rate`: `item.seller.payout_rate` (integer — e.g. 20, 30, 40).
`payout_amount`: `round(item.price * _get_payout_percentage(item), 2)`.
`has_intake_record`: boolean — True if any `IntakeRecord` exists for item.
`has_unresolved_flag`: boolean — True if any unresolved `IntakeFlag` for item.
`payout_sent_at`: ISO format if set, else empty string.

---

## Email — Payout Confirmation

Sent to seller when any item is marked paid via `admin_payout_mark_paid`.

**Subject:** `You've been paid for your Campus Swap item!`

**Body** (uses `wrap_email_template()`):

```
Hi [first name],

Great news — we've sent your payout for the following item sold through
Campus Swap:

[Item thumbnail]
[Item title]
Sale price: $[price]
Your payout ([payout_rate]%): $[payout_amount]
Sent to: [payout_method] — [payout_handle]

Thanks for selling with Campus Swap. We'll be in touch if anything else sells!

— The Campus Swap Team
```

`payout_rate` is `item.seller.payout_rate` (integer). `payout_amount` is
computed via `_get_payout_percentage(item)` at send time.

Per-item emails fire individually as each item is marked paid. If a seller has
three sold items and admin marks them paid one at a time, they receive three
separate emails.

**Edge case:** If `payout_handle` is null/empty, send the email anyway but omit
the "Sent to" line. Admin may have paid through an alternative channel.

---

## Constraints

- Do not touch the Stripe webhook handler. `payout_sent` is set only by admin
  action, never by Stripe.
- Do not remove any existing admin item routes. Only remove the payout UI
  section from `admin.html`.
- Do not remove `/admin/export/sales`. The new `/admin/payouts/export` is
  additive. Sales CSV can be deprecated in a future cleanup pass.
- `payout_sent` remains the source of truth for paid/unpaid state.
  `payout_sent_at` is supplementary metadata only.
- All payout amounts are computed at render/export time using
  `_get_payout_percentage(item)`. Do not add a `payout_amount` column to
  `InventoryItem`. Do not use `collection_method` for payout math — it no
  longer drives payout calculations. Use `item.seller.payout_rate` exclusively.
- The seller profile panel slide-out is not modified by this spec.
- No changes to the Stripe integration, webhook, referral program logic, or any
  buyer-facing routes.
- Do not call `calculate_payout_rate()` or `maybe_confirm_referral()` from
  any route in this spec — payout reconciliation is read-only with respect to
  the referral system.
