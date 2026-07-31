# Feature Spec — Facebook Marketplace Export

**Status:** ✅ BUILT 2026-07-31 — 59/59 tests passing. Migration `480cd6c9c8ba` applied locally
(both `campusswap` and `campusswap_prod`); needs `flask db upgrade` on Render.
**Date:** 2026-07-31
**Goal:** Give a data-entry worker everything needed to manually recreate every live shop
listing on Facebook Marketplace — copy-paste text fields, FB-ready price, and downloadable
photo bundles — with server-side progress tracking so nothing is double-posted or skipped.

---

## Context

Facebook Marketplace has no bulk import for local (non-shipped) listings. Catalog upload
exists only in Commerce Manager for shipped inventory. So every listing is manual entry, and
the thing to optimize is **clicks-per-listing for the worker**, not completeness of an export file.

A spreadsheet fails specifically on photos: FB's uploader needs real files on the worker's
machine, so a cell containing a URL means 3–5 manual right-click-saves per item.

**Scale at time of writing:** 287 shop-eligible items (an earlier 305 estimate omitted the
`_rephotographed_clause()` / `_matched_or_kept_clause()` gates; 287 is the true shop-ready count). At 2–3 min/listing that is 10–15 hours
of work spanning many sessions, which is why progress tracking is in scope.

---

## Non-Goals (explicitly deferred)

- **Takedown flow** when an item sells on the site. The migration below adds the fields that
  make this a trivial follow-up (`status='sold' AND fb_posted_at IS NOT NULL` = takedown queue),
  but no takedown UI is built here.
- **"Mark sold for pickup"** — when the worker closes a deal *on Facebook* and needs to mark the
  item sold on our side without a Stripe payment. This is a genuinely new flow (no payment, no
  BuyerOrder, payout still owed to seller) and needs its own spec.
- Any automated posting to Facebook.

---

## 1. Migration

Two nullable columns on `InventoryItem`:

```python
fb_posted_at   = db.Column(db.DateTime, nullable=True)     # UTC; set when worker checks "Posted"
fb_listing_url = db.Column(db.String(300), nullable=True)  # optional, pasted by worker
```

Standard Postgres-compatible Alembic migration. No backfill. `flask db upgrade` on Render after deploy.

---

## 2. Pricing

FB price is **always computed at runtime** — never stored.

```
tier add:  price <  50  ->  +$5
           price <  100 ->  +$10
           price >= 100 ->  +$15

fb_price = ceil((price + tier_add) * markup)      # markup = 1.1, whole-dollar round UP
```

Verified against real inventory:

| site price | add | FB price |
|---|---|---|
| $16 | +$5 | $24 |
| $35 | +$5 | $44 |
| $79 | +$10 | $98 |
| $108 | +$15 | $136 |
| $200 | +$15 | $237 |
| $287 | +$15 | $333 |

**Rationale for tiers over a flat +$15:** median price is $55 and 47% of inventory (142 items)
is under $50. A flat $15 add is 94% of a $16 lamp but 5% of a $287 couch — it punishes cheap
items hardest and barely touches the ones with real margin. Tiering flattens the markup to a
consistent ~25–30% across the catalog.

**Implementation:** `FB_SHIPPING_TIERS` in `constants.py` (rarely changes), markup as AppSetting
`fb_price_markup` default `'1.1'` (tunable without deploy). Helper `_fb_price(item)` in `app.py`.

---

## 3. Condition — fixed value

**Every item maps to `Used - Good`.** No dropdown, no worker judgment.

Reasoning: `quality` defaults to `1` and 233 of 305 shop-visible items sit at that default,
with **zero** rows at quality 2 — so quality=1 means "never assessed," not "poor." But
`quality_to_label()` (`app.py:1215`) collapses 1/2/3 → "Fair", which would tag 76% of a
professionally rephotographed catalog as "Used - Fair" on Facebook. Nothing in the inventory is
new, and nothing is bad. `Used - Good` is the honest single answer.

Stored as AppSetting `fb_condition_label` default `'Used - Good'` so it can change without a deploy.

> **Separate issue, not fixed here:** this same quality=1 default is making the *live shop*
> display "Fair" on 233 items. Worth its own small fix.

---

## 4. Description template

No emojis (they render inconsistently in FB descriptions). Assembled server-side.

```
{long_description or description}

Dimensions: 30"W x 18"D x 34"H          <- omitted entirely if no dimensions
Size: Queen                              <- mattress items only

Delivery and discounts available through our website:
https://usecampusswap.com/shop

Hundreds more dorm and apartment items listed there, with full photos, sizes,
and delivery pricing on every listing.
```

CTA block stored as AppSetting `fb_cta_text` so it is editable in one place and every card
updates. Dimensions line uses the existing `dim` Jinja filter formatting (no trailing `.0`).

---

## 5. Photos — two buckets

Three variants exist in storage. Only two go to the worker.

| Variant | Identified by | Use |
|---|---|---|
| `ai_enhanced_*` | filename prefix | **Excluded** — synthetic OpenAI background |
| `<stem>_nobg.jpg` | `ItemPhoto.photo_url` | **`listing/`** — what goes into the FB post |
| seller original photos | see below | **`originals/`** — send to buyers who ask for more |

### The `originals/` bucket has two sources

**Case A — item was matched to a seller listing (128 of 305 items).**
The original seller row still exists, hidden from the shop, and points *forward* at the shop item:

```python
original = InventoryItem.query.filter_by(replaced_by_item_id=item.id).first()
```

Note the direction: `replaced_by_item_id` lives on the **original**, not the shop item. Use that
original's `photo_url` + `gallery_photos` (excluding any `ai_enhanced_*`). These are genuinely
different photos of the item in the seller's room — the most useful thing to send an interested buyer.

Edge case confirmed in data: at least one matched original has a NULL `photo_url` but a populated
gallery. Do not assume the cover exists.

**Case B — no matched original (177 of 305 items).**
Warehouse-kept items that never had a seller listing. Fall back to the pre-background-removal raw
captures, derived by dropping the `_nobg` suffix (same derivation already used in the bg-removal
review view, `app.py:~18700`):

```python
stem, dot, ext = url.rpartition('.')
if dot and stem.endswith('_nobg'):
    original = stem[:-len('_nobg')] + '.' + ext
```

These are derived filenames, **not DB rows**, so existence is not guaranteed. Probe
`photo_storage.exists(key)` and skip misses silently. For legacy photos never bg-removed, the
photo *is* the original — no separate file, so the bucket is simply empty for that photo.

`is_hidden` photos are excluded from both buckets (an admin deliberately hid them).

---

## 6. Routes

All under the same auth guard — **see Open Question below.**

### `GET /admin/fb-export`
Focus mode: one item per screen.

- Item set = same eligibility as `/shop`: `ai_approved`, `status='available'`,
  `needs_new_photo=False`, `price > 0`, `storage_location_id IS NOT NULL`,
  `rephoto_disposition IS DISTINCT FROM 'discarded'`, plus `_rephotographed_clause()` and
  `_matched_or_kept_clause()`. Reuse the existing helpers — do not re-derive the filter.
- Stable ordering by `id` so position is reproducible across sessions.
- `?unposted=1` (**default**) hides items with `fb_posted_at` set.
- `?i=<n>` position index. Prev / Next navigation. Header shows `Item 34 of 305` and
  `142 of 305 posted`.
- Extends `admin_layout.html`.

**Card contents, top to bottom:**

| Field | Behavior |
|---|---|
| Title | `item.description`, copy button |
| FB price | computed per §2, copy button |
| FB category | mapped per §7, copy button |
| Condition | `Used - Good`, static text |
| `listing/` thumbnails | rendered inline via `url_for('uploaded_file', ...)` |
| `originals/` thumbnails | rendered inline, labeled "Seller's original photos" or "Warehouse originals" |
| Download photos (.zip) | per-item ZIP |
| Description | full assembled text in a `<textarea>`, copy button |
| Posted to Facebook | checkbox + optional FB URL text input |

Thumbnails matter: the worker must be able to eyeball that the files they downloaded match the
item they are posting.

### `GET /admin/fb-export/<int:item_id>/photos.zip`
Per-item ZIP, built in-memory with `zipfile` + `io.BytesIO`, streamed via `send_file`.

```
item-1043-desk-chair/
  listing/    01-front.jpg  02-side.jpg  03-back.jpg
  originals/  01.jpg  02.jpg
```

Filenames numbered by `(sort_order, id)`, view name appended when `ItemPhoto.view` is set.
Slug from `item.description`, ASCII-only, truncated. Bytes via `photo_storage.get_photo_bytes(key)`;
skip any that return `None`.

### `GET /admin/fb-export/photos.zip`
Bulk ZIP, all eligible items, same folder structure one level deeper. Respects `?unposted=1`.

**Size warning:** ~1,450 photos in scope → likely 500 MB–1 GB. Build with
`zipfile.ZIP_STORED` (JPEGs do not recompress meaningfully and STORED is far cheaper on CPU).
Consider a `?limit=` / `?offset=` chunking param so the worker can pull it in batches rather
than one fragile giant download. **Do not** hold the whole archive in memory if it can be
avoided — write to a temp file under the OS temp dir and stream it.

### `POST /admin/fb-export/<int:item_id>/posted`
Fetch POST, returns JSON, no page reload (matches existing in-place-save pattern).
Body: `{posted: bool, fb_listing_url: str|null}`. Sets/clears `fb_posted_at` (UTC).
Includes `{{ csrf_token() }}`.

---

## 7. FB category map

`FB_CATEGORY_MAP` in `constants.py`, keyed by `"Parent > Subcategory"`, value = the FB leaf
category name the worker types into FB's search-as-you-type category picker. Draft below —
**Henry to review; FB's taxonomy shifts and the worker should verify the first few live and
report corrections.** Unmapped keys fall back to showing the raw Campus Swap category with a
visible "verify on FB" note rather than guessing.

| Campus Swap | Facebook |
|---|---|
| Bedroom > Mattress | Beds & Mattresses |
| Bedroom > Headboard | Beds & Mattresses |
| Bedroom > Other Bedroom | Bedroom Furniture |
| Furniture > Couch / Sofa | Sofas |
| Furniture > Futon | Sofas |
| Furniture > Armchair / Accent Chair | Chairs |
| Furniture > Desk Chair | Office Chairs |
| Furniture > Gaming Chair | Office Chairs |
| Furniture > Desk | Desks |
| Furniture > Dresser | Dressers & Armoires |
| Furniture > Bookshelf / Shelving | Bookcases & Shelving |
| Furniture > Coffee Table | Coffee Tables |
| Furniture > Side Table | End & Side Tables |
| Furniture > TV Stand / Media Console | TV Stands & Entertainment Centers |
| Furniture > Storage Ottoman | Ottomans & Benches |
| Furniture > Other Furniture | Furniture |
| Kitchen & Appliances > Mini Fridge | Refrigerators |
| Kitchen & Appliances > Microwave | Microwaves |
| Kitchen & Appliances > Air Fryer | Small Kitchen Appliances |
| Kitchen & Appliances > Toaster Oven | Small Kitchen Appliances |
| Kitchen & Appliances > Coffee Maker / Espresso Machine | Small Kitchen Appliances |
| Kitchen & Appliances > Blender | Small Kitchen Appliances |
| Kitchen & Appliances > Instant Pot / Rice Cooker | Small Kitchen Appliances |
| Kitchen & Appliances > Knife Set | Kitchen & Dining |
| Kitchen & Appliances > Other Kitchen | Kitchen & Dining |
| Climate & Comfort > Portable AC Unit | Heating & Cooling |
| Climate & Comfort > Space Heater | Heating & Cooling |
| Climate & Comfort > Tower Fan | Heating & Cooling |
| Climate & Comfort > Humidifier / Dehumidifier | Heating & Cooling |
| Climate & Comfort > Other Climate | Heating & Cooling |
| Electronics > TV | TVs |
| Electronics > Monitor | Computer Monitors |
| Electronics > Laptop | Laptops |
| Electronics > Keyboard / Mouse | Computer Accessories |
| Electronics > Printer / Scanner | Printers & Scanners |
| Electronics > Speakers / Soundbar | Audio Equipment |
| Electronics > Headphones | Headphones |
| Electronics > Gaming Console | Video Game Consoles |
| Electronics > Other Electronics | Electronics |
| Rugs > Area Rug | Rugs |
| Bikes & Scooters > Bike | Bicycles |
| Bikes & Scooters > Electric Scooter | Scooters |

---

## 8. AppSettings

| Key | Default | Purpose |
|---|---|---|
| `fb_price_markup` | `'1.1'` | Multiplier applied after tier add |
| `fb_condition_label` | `'Used - Good'` | Condition string shown for every item |
| `fb_cta_text` | see §4 | Delivery/discount CTA block |
| `fb_export_enabled` | `'true'` | Kill switch to hide the nav entry |

All with hardcoded fallback defaults in code (existing pattern).

---

## 9. Multi-school note

Nothing here hardcodes UNC. The item query derives from existing shop helpers, so when
`school_id` lands the filter inherits it automatically. `fb_posted_at` is per-item, which stays
correct per school.

---

## Auth — dedicated narrow flag (DECIDED 2026-07-31)

The data-entry worker is not an admin and must not touch ops. **Neither `_has_ops_access()` nor
`require_crew()` is right:**

- `_has_ops_access()` would require `is_campus_director=True` — grants scheduling, payouts, storage.
- `require_crew()` is a single global check (`is_worker AND worker_status=='approved'`) with no
  granularity, so it grants all 8 crew pages. Most are harmless without shift assignments (the
  placement routes 403 unless a `ShiftPickup` exists on a shift the worker is assigned to —
  verified at `app.py:10086`), **but `/crew/availability` would put a data-entry temp into the
  auto-assignment staffing pool.** That is the ops surface they explicitly should not touch.

### Decision: `User.is_marketplace_poster`

Add to the migration in §1:

```python
is_marketplace_poster = db.Column(db.Boolean, default=False, nullable=False, server_default='false')
```

New guard in `app.py`, alongside `_has_ops_access()`:

```python
def _has_marketplace_access():
    """Marketplace posters + anyone with ops access. Data-entry-only permission:
    view the FB export page, mark listed, and (later) mark sold-for-pickup / undo.
    Deliberately NOT tied to is_worker — posters stay out of the staffing pool."""
    return current_user.is_authenticated and (
        current_user.is_marketplace_poster or _has_ops_access()
    )
```

- Leave `is_worker` **False** on these accounts. `is_marketplace_poster` and `is_worker` are
  independent, so a poster can later join real crew shifts without affecting FB access, and vice versa.
- Gates **only** the FB export routes in §6, plus the future sold-for-pickup / undo-sold actions.
  No second migration needed when that flow is built.
- Grant/revoke by email from `/admin/settings#marketplace-posters`, super admin only, mirroring
  `admin_grant_campus_director` (`app.py:17703`) exactly — including the "user must sign up first"
  and "already has full admin access" guards.

### Permission surface — complete and final

| Allowed | Not allowed |
|---|---|
| View `/admin/fb-export`, copy all fields | Scheduling, availability, shift assignment |
| Download per-item and bulk photo ZIPs | Payouts, payout reconciliation |
| Check / uncheck "Posted to Facebook" | Storage audit, item placement |
| *(later)* mark sold-for-pickup, undo it | Seller data, approval queue, pricing edits |

---

## Test plan

New tests in project root, `test_fb_export.py`:

- `_fb_price()` at every tier boundary ($49/$50/$99/$100) and the round-up edge (`x.01` → next dollar)
- Description assembly with/without dimensions, with/without mattress size, null `long_description`
- `originals/` resolution: Case A matched original, Case A with NULL cover, Case B `_nobg` derivation,
  Case B where the derived original does not exist in storage
- `ai_enhanced_*` and `is_hidden` photos excluded from both buckets
- Item set matches `/shop` eligibility exactly (same count)
- Per-item ZIP structure and folder names; missing-file skip does not 500
- `posted` POST sets and clears `fb_posted_at`; `?unposted=1` filter reflects it
- Auth: unauthorized user gets redirected/403
