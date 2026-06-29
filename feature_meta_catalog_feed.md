# Feature Spec: Meta Product Catalog Feed

## Goal

Expose Campus Swap's live inventory as a Meta-compatible product catalog feed so that Advantage+ catalog campaigns in Meta Ads Manager can serve dynamic product ads — one ad per item, each linking directly to that item's product page on the site. Without this feed, Meta ads can only run generic brand creatives; with it, Meta automatically generates and optimizes individual item ads from the catalog.

---

## UX Flow

This is a machine-readable endpoint, not a user-facing page. The flow is:

1. Meta Commerce Manager is configured to fetch `GET /catalog.xml` on a daily schedule.
2. On each fetch, the route queries all currently shoppable items and returns them as an RSS 2.0 feed in Meta's required format.
3. Meta ingests the feed, creates/updates/removes product entries in the catalog, and makes them available for dynamic ad campaigns.
4. When a user clicks a catalog ad, they land on `/item/<id>?utm_source=facebook&utm_medium=cpc&utm_campaign=catalog` — the specific item page, not the generic shop.

Admin-only preview route: `GET /admin/catalog/preview` — renders the first 10 items as a readable HTML table so Henry can verify the feed looks correct before connecting it to Meta. No template needed — just a simple inline HTML response.

---

## New Routes

| Method | Path | Function | Auth | Description |
|--------|------|----------|------|-------------|
| `GET` | `/catalog.xml` | `meta_catalog_feed` | None (public) | Returns RSS 2.0 XML product feed for Meta Commerce Manager |
| `GET` | `/admin/catalog/preview` | `admin_catalog_preview` | `is_super_admin` | HTML table preview of the first 10 catalog items for verification |

---

## Model Changes

**No new models. No migration required.**

The feed reads from existing `InventoryItem` fields only.

---

## Template Changes

**No new templates.**

`/catalog.xml` returns a raw XML response (not a Jinja template — use `Response(xml_string, mimetype='application/xml')`).

`/admin/catalog/preview` returns a simple inline HTML string — no template file needed, no layout extension. Just enough to verify the data.

---

## Business Logic

### Item eligibility filter

An item appears in the catalog if and only if ALL of the following are true:

```python
item.status == 'available'
item.ai_approved == True
item.needs_new_photo == False
item.price is not None and item.price > 0
item.photo_url is not None
item.storage_location_id is not None
```

This mirrors exactly the shop visibility gate used by the `/shop` route — if an item shows in the shop, it shows in the catalog. If it's hidden from the shop for any reason, it's hidden from the catalog too.

### Feed format

Meta requires RSS 2.0 with `g:` namespace fields. The feed must include these fields per item:

| XML field | Source | Notes |
|-----------|--------|-------|
| `g:id` | `str(item.id)` | Must be stable — never changes for the same item |
| `g:title` | `item.description` | Item title (AI-generated, already approved) |
| `g:description` | `item.long_description or item.description` | Fall back to title if no long description |
| `g:link` | `https://usecampusswap.com/item/<id>?utm_source=facebook&utm_medium=cpc&utm_campaign=catalog` | Deep link to item page with UTMs baked in |
| `g:image_link` | Absolute photo URL (see Photo URL logic below) | Must be absolute HTTPS URL |
| `g:price` | `f"{item.price:.2f} USD"` | e.g. `"45.00 USD"` |
| `g:availability` | `"in stock"` | Always "in stock" — items are removed from feed when sold |
| `g:condition` | `"used"` | All Campus Swap items are used/secondhand |
| `g:brand` | `"Campus Swap"` | Required by Meta even for resellers |
| `g:google_product_category` | See category mapping below | Meta uses Google's taxonomy |

Optional but recommended (include when available):

| XML field | Source |
|-----------|--------|
| `g:sale_price` | Omit — we don't have sale prices |
| `g:item_group_id` | Omit |
| `g:additional_image_link` | First gallery photo from `item.gallery_photos` if any exist, else omit |

### Photo URL logic

Photo URLs in the feed **must be absolute HTTPS URLs** — Meta will reject relative paths. Use the same `_email_photo_url()` helper that already exists in `app.py` for email thumbnails (it prefers a direct S3/CDN URL, then falls back to `BASE_URL + /uploads/` + filename). This helper already handles the S3 passthrough case.

If `_email_photo_url()` returns a relative URL for any reason, prepend `https://usecampusswap.com`. Never output a relative path in the feed.

### Category mapping

Map `item.category.name` to Google's product taxonomy ID. Use this mapping — default to `"Furniture"` for anything not explicitly mapped:

```python
CATALOG_CATEGORY_MAP = {
    "Couch": "Furniture > Sofas & Loveseats",
    "Sofa": "Furniture > Sofas & Loveseats",
    "Futon": "Furniture > Sofas & Loveseats",
    "Mattress": "Furniture > Beds & Accessories > Mattresses",
    "Bed Frame": "Furniture > Beds & Accessories > Bed Frames",
    "Headboard": "Furniture > Beds & Accessories > Headboards",
    "Desk": "Furniture > Desks",
    "Chair": "Furniture > Chairs",
    "Dresser": "Furniture > Dressers & Chests of Drawers",
    "Bookshelf": "Furniture > Bookcases & Shelving",
    "Rug": "Home & Garden > Rugs",
    "TV": "Electronics > Video > Televisions",
    "Television": "Electronics > Video > Televisions",
    "Mini Fridge": "Appliances > Kitchen Appliances > Refrigerators",
    "Fridge": "Appliances > Kitchen Appliances > Refrigerators",
    "Microwave": "Appliances > Kitchen Appliances > Microwaves",
    "AC": "Appliances > Climate Control > Air Conditioners",
    "Air Conditioner": "Appliances > Climate Control > Air Conditioners",
    "Heater": "Appliances > Climate Control > Space Heaters",
    "Gaming": "Electronics > Video Game Consoles & Accessories",
    "Console": "Electronics > Video Game Consoles & Accessories",
    "Printer": "Electronics > Print, Copy, Scan & Fax > Printers",
    "Lamp": "Home & Garden > Lighting",
}
```

If `item.category` is None, use `"Home & Garden"` as the fallback.

### Feed XML structure

```xml
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:g="http://base.google.com/ns/1.0">
  <channel>
    <title>Campus Swap — UNC Chapel Hill</title>
    <link>https://usecampusswap.com/shop</link>
    <description>Dorm furniture and appliances, delivered across Chapel Hill.</description>
    <item>
      <g:id>123</g:id>
      <g:title>Gray Sectional Couch</g:title>
      ...
    </item>
    ...
  </channel>
</rss>
```

### Caching

The feed query can be expensive on large catalogs. Add a simple module-level cache:

```python
_catalog_cache = {"xml": None, "built_at": None}
CATALOG_CACHE_TTL = 3600  # 1 hour in seconds
```

On each request: if `_catalog_cache["xml"]` is set and `(now - built_at).seconds < CATALOG_CACHE_TTL`, return the cached XML. Otherwise rebuild, store in cache, return fresh. This prevents Meta's hourly fetches from hammering the DB.

Cache is invalidated automatically after 1 hour. No manual invalidation needed — items that sell will drop off the next rebuild.

### Admin preview route

`GET /admin/catalog/preview` — super admin only. Runs the same query and eligibility filter but returns an HTML table with columns: ID, Title, Price, Category, Image (thumbnail), Link. First 10 items only. Inline HTML, no layout template — just enough to verify the data before connecting to Meta.

---

## Constraints

- **No auth on `/catalog.xml`** — Meta's crawler has no way to authenticate. The feed is public by design. It only exposes data that's already public on the shop page.
- **Never expose `sold` items** — the eligibility filter already prevents this via `status == 'available'`, but double-check: if an item sells between cache builds, it will remain in the feed for up to 1 hour. This is acceptable — Meta marks items unavailable on the next fetch cycle.
- **Absolute URLs only** — all `g:link` and `g:image_link` values must be full `https://` URLs. Relative paths will cause Meta to reject the entire feed.
- **Use `Response(xml, mimetype='application/xml')`** — do not render this through a Jinja template. Build the XML string directly in the route using Python string formatting or ElementTree. This avoids Jinja escaping issues with `&` characters in URLs.
- **`g:id` must be stable** — use `item.id` (the integer PK). Never use a slug or description-derived value that could change.
- **Do not touch the shop visibility logic** — the eligibility filter mirrors it but is independent. Do not refactor the shop query. Copy the conditions explicitly.
- **XML-escape all text fields** — descriptions may contain `&`, `<`, `>`. Use `html.escape()` on `title`, `description`, and any freetext fields before inserting into XML.

---

## Testing Checklist

- [ ] `GET /catalog.xml` returns HTTP 200 with `Content-Type: application/xml`
- [ ] Feed contains only items where `status='available'`, `ai_approved=True`, `needs_new_photo=False`, `price > 0`, `photo_url` not null, `storage_location_id` not null
- [ ] Sold items do not appear in the feed
- [ ] Items with `needs_new_photo=True` do not appear
- [ ] Items with `ai_approved=False` do not appear
- [ ] All `g:image_link` values are absolute `https://` URLs
- [ ] All `g:link` values include UTM params (`utm_source=facebook&utm_medium=cpc&utm_campaign=catalog`)
- [ ] `g:price` is formatted as `"45.00 USD"` (two decimal places, space before USD)
- [ ] Descriptions with `&` characters are properly XML-escaped (e.g. `&amp;`)
- [ ] Feed renders valid XML (no parse errors)
- [ ] Cache returns the same response on second request within TTL
- [ ] `GET /admin/catalog/preview` requires super admin — returns 403 for non-super-admin
- [ ] Admin preview shows a readable HTML table with correct data for first 10 items
- [ ] Feed response time is under 500ms on second request (cache hit)

---
Mini-prompt: GA4 Conversion Events
In layout.html, inside the existing {% block head_extra %} block (or after the GA4 script tag if that block isn't available on all pages), add inline <script> snippets that fire GA4 conversion events on the three key pages:
/item_success  → gtag('event', 'purchase', { ... })
/checkout/delivery  → gtag('event', 'begin_checkout')
/cart  → gtag('event', 'view_cart')
For the purchase event on /item_success, pass the order value. The route already receives ?order_id= — use the Order object that's passed to the template (check what context variables item_sold_success sends to item_success.html) to populate value and currency: 'USD'.
Fire these conditionally based on request.path — do not fire on every page. Use {% if request.path == '/item_success' %} style Jinja guards.
Do not remove or modify the existing GA4 pageview tag. These are additive events alongside it.
After building, update website-feature-log.md Analytics section to document the three new GA4 events.

## After Building

Cross-reference and update `CODEBASE.md`, `HANDOFF.md`, `DECISIONS.md`, and `website-feature-log.md` to reflect:
- New routes `/catalog.xml` and `/admin/catalog/preview`
- Catalog cache pattern (`_catalog_cache`, `CATALOG_CACHE_TTL`)
- `CATALOG_CATEGORY_MAP` constant
- Note that `/catalog.xml` is intentionally public (no auth)
