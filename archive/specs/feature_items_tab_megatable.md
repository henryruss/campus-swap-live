# Feature Spec: Items Tab — Item Detail Modal + Unified Search + Sellers Tab Consolidation

## Goal

Make the All Items table the primary admin view for everything item- and
seller-related. Three improvements:

1. **Item detail modal** — clicking an item title opens a rich detail modal
   (similar to the approval queue modal) instead of navigating away to the
   edit page.
2. **Unified search bar** — replace three separate filter fields (category,
   seller email, item title) with a single smart search that handles any
   combination of item ID, item title, seller name, and seller email, plus
   explicit category + subcategory dropdowns as separate controls.
3. **Sellers tab consolidation** — absorb the Sellers tab's pickup nudge
   section into Items tab; remove the Sellers tab from the sidebar. Seller
   profile panel access is unchanged — clicking any seller name throughout
   the admin opens the panel as before.

---

## UX Flow

### Unified Search

A single text input replaces the three existing filter fields (category
dropdown, seller email, item title).

Typing into the field matches against any of:
- Item title (substring, case-insensitive)
- Item ID (exact integer match if input is all digits)
- Seller full name (substring)
- Seller email (substring)

Matching logic: if the input is all digits → filter by `item.id = value`.
Otherwise → `OR` match across title, seller name, seller email.

Category and subcategory remain as **explicit dropdowns** (not part of the
text field). They combine with the text search as `AND` — you can search for
"Bridget" and then filter to "Bedroom" to see only Bridget's bedroom items.

The "NEEDS PHOTO REFRESH" checkbox (already built) stays as a separate toggle
alongside the category dropdowns.

Filtering is server-side (form submit / query params), not client-side JS.
Existing `?q=`, `?category_id=`, `?subcategory_id=` query param pattern.
"Clear" link resets all params.

**Subcategory dropdown:** populated dynamically based on selected category.
If no category is selected, the subcategory dropdown is hidden or disabled.
When category changes, subcategory resets. Server-side: `InventoryItem` has a
`subcategory` field (string) — the subcategory dropdown is populated from
distinct `subcategory` values for the selected `category_id`. If no
`subcategory` values exist for a category, the dropdown stays hidden.

### Item Detail Modal

Clicking any item's title text in the All Items table opens a right-side
slide-in modal panel — same visual pattern as the approval queue modal.

**Trigger:** `<button class="item-title-trigger" data-item-id="{{ item.id }}">
{{ item.description }}</button>` — event delegation on `document` for
`.item-title-trigger` clicks, fires `loadItemDetail(itemId)`.

**Content (fetched on demand):** `GET /admin/item/<id>/detail` returns an
HTML partial (no layout). Content:

- **Gallery carousel** — cover photo + all ItemPhoto gallery images. Same
  carousel pattern as `ai_review_detail_partial.html`. No set-as-cover or
  delete buttons here — this is a read view; editing still uses Edit button →
  edit page.
- **Item metadata block:**
  - Title, description, long description
  - Category + subcategory
  - Condition (1–5)
  - Price + retail price (if set) + savings callout
  - Status pill
  - Date added
  - AI approval status (`ai_approved`, `ai_review_pending`)
  - `needs_new_photo`, `needs_photo_verification` flags (shown as badges if
    set)
  - Storage location + storage row (if set)
  - `picked_up_at`, `arrived_at_store_at` timestamps (if set)
- **Seller summary row** — seller name (`.seller-panel-trigger` class →
  opens seller panel on click), email, payout rate, plan badge
- **Payout info** — payout amount (computed at runtime from
  `_get_payout_percentage(item)`), `payout_sent` indicator
- **Action buttons** (same row at bottom):
  - "Edit" → links to `/edit_item/<id>` (navigates away, closes modal)
  - "Mark Sold" → POST to existing mark-sold route, `modal=1` branch returns
    JSON success, row updates status pill in table + modal closes
  - "Delete" → confirmation dialog, POST to delete route, row removed from
    table

**Modal behaviour:** right-side 480px slide-in panel. Close: X button,
Escape key, overlay click. Seller panel can open simultaneously (same
z-index pattern as approval queue modal — seller panel appears layered on
top).

### Sellers Tab Consolidation

The Sellers tab contains two distinct things today:

1. **Seller table with search** — fully replaced by clicking seller names in
   the Items table (opens panel) or by searching in the unified search
2. **Pickup nudge section** — operational action; moves to Items tab as a
   collapsible section (collapsed by default) labelled "Pickup Nudge"

The section lives below the filter bar and above the table in the All Items
view only (not shown when on Approval Queue / AI Review / Photo Verification
tabs).

The Sellers tab sidebar icon is removed. `GET /admin/sellers` becomes a 302
redirect to `/admin/items` so any bookmarks or external links don't 404.

---

## New Routes

| Method | Path | Function | Notes |
|--------|------|----------|-------|
| `GET` | `/admin/item/<id>/detail` | `admin_item_detail` | HTML partial. Full item detail for slide-in modal. Auth: `is_admin`. 404 if item not found. Eager-loads `gallery_photos`, `category`, `seller`. |
| `POST` | `/admin/item/<id>/mark-sold` | `admin_item_mark_sold` | Mark item sold. Accepts `modal=1` → returns JSON `{success}`. Falls back to redirect for non-modal. Auth: `is_admin`. |
| `GET` | `/admin/sellers` | `admin_sellers` | **Changed:** 302 → `/admin/items`. Was the sellers tab page. |

All existing routes unchanged: seller panel (`GET /admin/seller/<id>/panel`),
pickup nudge (`POST /admin/pickup-nudge/send`), item delete, item edit.

---

## Model Changes

None. No new fields. No migration.

`InventoryItem.subcategory` already exists as a string field — used for the
subcategory dropdown. The dropdown is populated by querying
`db.session.query(InventoryItem.subcategory).filter_by(category_id=cat_id)
.distinct()` at page load (or via a small JSON endpoint if subcategory is
populated dynamically on category change).

---

## Template Changes

### `admin/items.html`

1. **Filter bar replacement:**
   - Remove: category dropdown, seller email input, item title input (three
     separate fields)
   - Add: single `<input type="text" name="q" placeholder="Search by item,
     seller name, email, or ID…">` 
   - Keep: category dropdown (now labelled "Category") and add subcategory
     dropdown (labelled "Subcategory", hidden when no category selected)
   - Keep: "NEEDS PHOTO REFRESH" checkbox
   - Keep: "Filter" submit button + "Clear" link

2. **Item title cell:** wrap `{{ item.description }}` in a button element
   with `class="item-title-trigger"` and `data-item-id="{{ item.id }}"`.
   Style as a plain text link (no button chrome).

3. **Item detail modal markup:** new `<div id="item-detail-modal"
   class="side-panel">` added at bottom of template. Same structure as the
   approval modal: overlay div, panel div, close button, content div
   (`#item-detail-content`). Hidden by default.

4. **Item detail JS:** `loadItemDetail(itemId)` function — fetch
   `/admin/item/<id>/detail`, inject into `#item-detail-content`, open panel.
   Event delegation on `document` for `.item-title-trigger`. Close handlers
   (X, Escape, overlay). "Mark Sold" button in partial fires fetch POST to
   `/admin/item/<id>/mark-sold?modal=1`, on success updates the status pill
   in the table row (by `data-item-id` on the `<tr>`) and closes modal.

5. **Pickup nudge section:** move from `admin/sellers.html` into
   `admin/items.html`. Collapsible (collapsed by default). Only shown when
   `view` param is absent or `'all'`. Checkbox table, "Remind Selected" +
   "Remind All" form buttons unchanged — POST to existing
   `/admin/pickup-nudge/send`.

6. **Subcategory JS:** small `<script>` — on category dropdown `change`,
   fetch `/admin/items/subcategories?category_id=<id>` (see new route below),
   populate subcategory dropdown options, show/hide the subcategory dropdown.
   On clear, hide subcategory dropdown.

### New route for subcategory population

| Method | Path | Function | Notes |
|--------|------|----------|-------|
| `GET` | `/admin/items/subcategories` | `admin_items_subcategories` | Param: `category_id`. Returns JSON `{subcategories: ["Desk", "Dresser", ...]}` — distinct non-null subcategory values for that category, sorted alpha. Auth: `is_admin`. |

### New template: `admin/item_detail_partial.html`

HTML partial (no layout). Fetched on demand by `loadItemDetail()`.

Structure:
- **Gallery track** — same carousel markup as `approval_detail_partial.html`.
  `<div class="gallery-track">` with img slides. No set-as-cover / delete
  buttons.
- **Two-column body** (or single column, matching existing modal style):
  - Left/top: gallery
  - Right/bottom: metadata + seller row + actions
- **Metadata fields** (all read-only display, not inputs):
  - Title (`item.description`)
  - Long description (`item.long_description` — shown if set)
  - Category / subcategory
  - Condition stars or numeric
  - Price + retail price + savings callout (if `retail_price` set)
  - Status pill
  - Date added
  - Operational badges: `needs_new_photo` (amber), `needs_photo_verification`
    (indigo), `ai_review_pending` (amber), `ai_approved` (green)
  - Storage: location name + row (if set)
  - `picked_up_at` timestamp (if set)
  - `arrived_at_store_at` timestamp (if set)
- **Seller row:**
  - `<a class="seller-panel-trigger" data-user-id="{{ item.seller.id }}">
    {{ item.seller.full_name }}</a>` — opens seller panel via existing
    delegation
  - Seller email (small, muted)
  - Payout rate badge
- **Payout row:** computed payout amount + payout sent indicator
- **Footer actions:**
  - "Edit" button → href `/edit_item/{{ item.id }}`
  - "Mark Sold" button — `class="mark-sold-btn"`, `data-item-id="{{ item.id
    }}"`. Shown only if `item.status != 'sold'`.
  - "Delete" button — `class="delete-item-btn"`, `data-item-id="{{ item.id
    }}"`. Opens confirmation, then POST.

### `admin/admin_layout.html` (sidebar)

Remove the Sellers tab icon and nav link. No other changes — active tab
detection is path-based, so removing the nav item is sufficient.

### `admin/sellers.html`

No longer rendered (route redirects). Can be kept as dead template or deleted
— recommend keeping until the redirect has been in production for a cycle.

---

## Business Logic

### Unified search query

```python
q = request.args.get('q', '').strip()
category_id = request.args.get('category_id', type=int)
subcategory = request.args.get('subcategory', '').strip()

query = InventoryItem.query.join(InventoryItem.seller)

if q:
    if q.isdigit():
        query = query.filter(InventoryItem.id == int(q))
    else:
        like = f'%{q}%'
        query = query.filter(
            db.or_(
                InventoryItem.description.ilike(like),
                User.full_name.ilike(like),
                User.email.ilike(like),
            )
        )

if category_id:
    query = query.filter(InventoryItem.category_id == category_id)

if subcategory:
    query = query.filter(InventoryItem.subcategory == subcategory)
```

Existing `needs_photo_refresh` boolean filter applied on top if checkbox is
checked.

### Mark Sold route

The existing table already has a "Mark Sold" button per row that POSTs
somewhere (or navigates to edit). If that route already exists and returns a
redirect, add `modal=1` branch that returns JSON `{success: true}` instead.
If no standalone mark-sold route exists today, create `admin_item_mark_sold`
as a thin wrapper: sets `item.status = 'sold'`, commits, returns JSON or
redirect depending on `modal` param.

### Sellers tab redirect

`GET /admin/sellers` → `admin_sellers` function body becomes:
`return redirect(url_for('admin_items'), 302)`

The pickup nudge POST route (`/admin/pickup-nudge/send`) is not touched —
it keeps its URL and function unchanged.

---

## Constraints

- **Seller panel** (`GET /admin/seller/<id>/panel`) is completely unchanged.
  All `.seller-panel-trigger` links throughout admin continue to work via
  existing event delegation.
- **Pickup nudge POST route** keeps its current URL. Only the collapsible UI
  section moves — the form `action` attribute is unchanged.
- **Edit page** (`/edit_item/<id>`) is not replaced. The detail modal is
  read-only; the Edit button navigates to the full edit page as before.
- **Approval queue modal** (`admin/approval_detail_partial.html`) is not
  modified — it serves `pending_valuation` items with edit controls and is a
  different workflow from this read-only detail view.
- **AI review modal** (`admin/ai_review_detail_partial.html`) is not
  modified.
- **`needs_photo_refresh` checkbox** already built — preserved as-is in the
  new filter bar layout.
- **CSV export** (`GET /admin/export/items`) is not modified. The export
  should apply the same unified search filters if `q`, `category_id`,
  `subcategory` params are present — or can stay as a full export for now.
