# Feature Spec — Shop The Drop Redesign (Direction B)

> **Read `CODEBASE.md` before starting.** Do not assume any route, model field, template, or CSS variable exists — verify against the codebase. This spec modifies the existing `/inventory` shop front. It is a **visual + UX redesign with new filtering**, not a rebuild of the data layer.

---

## Goal

The current shop front uses oversized "Shop by Category" buttons that dominate the viewport and push real inventory below the fold. We are replacing it with an AptDeco-inspired marketplace layout: a slim category tab bar, a persistent left filter sidebar on desktop (condition, price, subcategory) that becomes a bottom sheet on mobile, a sort control, and a cleaner, denser item-card grid.

This must look and feel great on **both mobile and desktop** — a large share of traffic will arrive from Facebook Marketplace / Meta ads and could land on any device. Mobile is a first-class target, not an afterthought.

**Out of scope (do not build):**
- Save/favorite/heart feature (requires login plumbing — deferred).
- Multi-location store switching (the nav location selector already exists; do not touch it). However, **design the item query so a future `location` filter slots in cleanly** — see Business Logic § Forward-compatibility.
- Discount filter (intentionally cut — see Business Logic § Sort).

---

## UX Flow

### Desktop (≥ 900px)

1. Buyer lands on `/inventory`. Page header shows the store indicator ("Showing items from UNC Chapel Hill") and the existing store-open / reserve-only banners if active.
2. A horizontal **category tab bar** sits below the toolbar: `All`, `Furniture`, `Bedroom`, `Kitchen & Appliances`, `Electronics`, `Rugs`, `Bikes & Scooters`, `Climate & Comfort`, `Other`. It scrolls horizontally if it overflows (no wrap). Active tab is underlined in `--accent`.
3. A **toolbar** holds the search input (left, flex-grow) and the **Sort** select (right).
4. A **persistent left sidebar** (~210px) holds filter groups: Condition, Price, and — only when a category is selected — Subcategory.
5. The **item grid** fills the remaining width.
6. Changing any sidebar filter or the sort select **immediately re-queries** (auto-submit) and reloads with updated results from the top. Active filters appear as **removable chips** above the grid, with a "Clear all" link.
7. Scrolling toward the bottom triggers infinite-scroll loading of the next page (existing mechanism, preserved — must carry all active filter params).

### Mobile (< 900px)

1. Same header/banners.
2. Category tab bar remains a horizontally-scrollable strip.
3. Toolbar: full-width search input on top; a row below with a **"Filters"** button (left) and the **Sort** select (right).
4. Tapping **"Filters"** opens a **bottom sheet** sliding up from the bottom, containing the same filter groups as the desktop sidebar. Body scroll locks while open. A backdrop dims the page.
5. On mobile, changing a filter does **not** auto-submit. Selections are staged. The sheet has a sticky footer with a **"Show results"** primary button and a **"Clear all"** text button. Tapping "Show results" submits and closes the sheet.
6. Grid is 2 columns (Facebook-Marketplace-style two-up). Cards stay compact.
7. Infinite scroll behaves identically to desktop.

### Edge cases (all viewports)

- **No items match the active filters** → friendly empty state inside the grid area ("No items match these filters") + a "Clear all filters" button. Do not show an empty void.
- **Teaser mode** (`shop_teaser_mode == 'true'`) → unchanged. Still renders `inventory_teaser.html`. None of this redesign applies in teaser mode.
- **Store not yet open / reserve-only mode** → preserve existing banner behavior; the grid still renders normally (buy/reserve gating lives on the product page, not the grid).
- **Sold / reserved items** → preserve existing behavior: available items always sort first; sold/reserved sort last and show a `SOLD` / `RESERVED` overlay badge on the card.
- **Item with no `retail_price`** → no strikethrough and no "% off" badge on that card; it is simply omitted, not faked.
- **Item with no photo** → existing placeholder behavior.
- **Switching category** → resets the subcategory selection (subcategories are category-specific).
- **Category with no subcategories** → the Subcategory filter group is hidden entirely.
- **JavaScript disabled** → desktop auto-submit and the mobile sheet are progressive enhancements. The form must still be submittable without JS via a visible **"Apply filters"** submit button inside the filter form (see Business Logic § Form architecture). Filtering must never be JS-only.

---

## New Routes

**No new routes.** This redesign modifies the existing `inventory` view function and its `?ajax=1` infinite-scroll branch. The only changes are: (a) additional query-string parameters parsed and applied to the item query, and (b) the template(s) rendered.

| Method | Path | Function | Change |
|---|---|---|---|
| GET | `/inventory` | `inventory` | Parse new filter/sort params; pass filter state + result count + subcategories to template. Render the redesigned `inventory.html`. |
| GET | `/inventory?ajax=1` | `inventory` (existing ajax branch) | Must apply the **same** filter/sort params as the full-page request when returning the next page of card HTML. |

> The existing `/api/subcategories/<parent_id>` endpoint is **not** used by the shop redesign (subcategories are rendered server-side here — see below). Leave that endpoint alone; the onboarding wizard still uses it.

---

## Model Changes

**None. No migration required.**

Every filter maps to a column that already exists:

| Filter | Backing column | Notes |
|---|---|---|
| Condition | `InventoryItem.quality` (int 1–5) | `5 = Like New`, `4 = Good`, `3 = Fair`. |
| Price buckets | `InventoryItem.price` | Numeric. |
| Best-deal sort | `InventoryItem.retail_price` (nullable) | Discount % = `(retail_price − price) / retail_price`. NULL → treat as 0% and sort last. |
| Category / Subcategory | existing category relationship | Verify the actual subcategory mechanism in `models.py` (parent/child on `InventoryCategory`, and `InventoryItem`'s category/subcategory fields). Do **not** assume schema — read it. |

If, while reading the models, you find the subcategory relationship is structured differently than expected, adapt the query accordingly and note it in your deviations — but **do not add columns or a migration**; everything needed is already there.

---

## Template Changes

### Modify: `templates/inventory.html`
The main rework. Replace the big category-button grid with the new layout. Suggested structure (extends `layout.html`):

```
{% block content %}
  <header> store indicator + store-open/reserve banners (preserve existing) </header>

  <div class="shop-toolbar">  search input + sort select (+ mobile "Filters" button) </div>

  <nav class="shop-cat-tabs"> horizontal category tab bar </nav>

  <div class="shop-body">
    <aside class="shop-sidebar"> filter form: Condition, Price, Subcategory </aside>
    <main class="shop-main">
      <div class="shop-active-filters"> removable filter chips + Clear all + result count </div>
      <div class="shop-grid" id="shop-grid"> {% include '_item_card.html' %} per item </div>
      <div id="scroll-sentinel"></div>
    </main>
  </div>

  <div class="shop-filter-sheet" id="filter-sheet"> mobile bottom sheet (same form, sticky footer) </div>
{% endblock %}
```

The desktop sidebar and the mobile sheet should render **the same filter form** so there is one source of truth for filter state (see Business Logic § Form architecture for how one form serves both).

### Create: `templates/_item_card.html`
Extract the single item card into a partial so the full-page render and the `?ajax=1` infinite-scroll fragment render **identical** markup. The ajax branch should loop this partial. Card anatomy:

- Square image wrapper (`aspect-ratio: 1 / 1`), `object-fit: cover`, links to `/item/<id>`.
- Image overlays: **condition badge** bottom-left (Like New / Good / Fair); **video badge** (camera/play icon) bottom-right if the item has a video; **status overlay** (`SOLD` / `RESERVED`) only for non-available items.
- Body: title (2-line clamp, `-webkit-line-clamp: 2`); price (bold, `--primary`); if `retail_price` present, a line with strikethrough retail + a "% off" pill in `--accent`.
- Whole card is a single link/clickable region to the product page. Use `data-*` attributes if any JS needs item data — **never** inline `tojson` in `onclick`.

### Stop using: `templates/_category_grid.html`
Remove its include from `inventory.html`. The new `.shop-cat-tabs` bar replaces it. **Before deleting the file, grep for other references** — if nothing else includes it, delete it; otherwise leave it and just stop using it in the shop.

### Add CSS to: `static/style.css`
All new styles go here. **Use the existing CSS variables — never hardcode colors.** Reuse `.card`, `.btn-primary`, `.btn-outline` where appropriate. Suggested new class prefixes: `.shop-*`, `.filter-*`, `.item-card-*`. Add responsive rules per the breakpoints in Business Logic § Responsive.

### Do NOT modify: `templates/product.html`, `templates/inventory_teaser.html`, `templates/layout.html`
Product page, teaser page, and the nav/location selector are out of scope.

---

## Business Logic

### Form architecture (one form, GET, serves desktop + mobile)

- All filter controls — search input, sort select, condition checkboxes, price-bucket checkboxes, subcategory checkboxes — live inside **one `<form method="GET" action="{{ url_for('inventory') }}">`**.
- **Filtering uses GET, not POST.** This is read-only browsing/navigation, not a state mutation. The "form POST → redirect" rule applies to data changes; it does **not** apply to search/filter. GET is required so URLs are shareable, the back button works, and the infinite-scroll ajax call can read the active params from the query string.
- The desktop sidebar and the mobile sheet render the *same* form. Easiest robust approach: render the filter form once in a partial and place it inside both the `.shop-sidebar` and the sheet — or render a single form whose CSS position changes by breakpoint. Pick whichever is cleaner in this codebase, but there must be exactly one set of inputs submitting one query string (avoid duplicate inputs that double-submit).
- **Always include a visible `<button type="submit">Apply filters</button>`** inside the form. This is the no-JS fallback and the mobile sheet's "Show results" button.

**Progressive enhancement (JS):**
- **Desktop (≥ 900px):** on `change` of any filter control or the sort select, auto-submit the form. The "Apply filters" button may be visually hidden at this breakpoint (it still works without JS).
- **Mobile (< 900px):** filters do **not** auto-submit. The "Filters" button opens the sheet; the sheet's sticky footer "Show results" button submits the form. The Sort select may auto-submit on mobile too (it lives in the toolbar, not the sheet).
- Use vanilla JS only. Escape key and backdrop click close the sheet. Lock `body` scroll while the sheet is open; restore on close.

### Category tabs
Render each tab as an `<a>` link whose href preserves the current query string but overrides `category` (and **drops** `subcategory`, since it's category-specific). Build hrefs server-side by merging `request.args`. The `All` tab links to `/inventory` with category removed (other filters preserved). Without JS these links must work as plain navigation.

### Subcategory group (server-rendered)
When a category is active, the `inventory` view fetches that category's subcategories and passes them to the template, which renders them as checkboxes in the filter form. No AJAX. When no category is active, or the category has no children, the group is omitted.

### Filter parameter contract
All params optional. Multi-select params repeat the key (standard `request.args.getlist`).

| Param | Type | Values | Query effect |
|---|---|---|---|
| `q` | string | free text | **Preserve the existing search behavior and param name** (verify in code — it searches title + long description). If the existing param is named differently, keep that name. |
| `category` | string | category identifier as used today (verify: name vs id — `CODEBASE.md` notes case-insensitive matching by name) | Filter to that category. |
| `subcategory` | string (multi) | subcategory identifiers | OR within subcategories; AND with category. |
| `condition` | string (multi) | `like_new` \| `good` \| `fair` | Map to `quality` `5` \| `4` \| `3`; OR the selected values. |
| `price` | string (multi) | `under_25` \| `25_50` \| `50_100` \| `100_200` \| `over_200` | OR the selected ranges (a union of price ranges). |
| `sort` | string | `newest` \| `price_asc` \| `price_desc` \| `best_deal` | See Sort below. Default `newest`. |
| `page` / cursor | — | existing | **Preserve the existing infinite-scroll pagination mechanism.** |
| `ajax` | `1` | existing | Existing fragment branch. |

**Price bucket boundaries** (a checked bucket contributes its range; multiple checked = union):
- `under_25` → `price < 25`
- `25_50` → `25 <= price < 50`
- `50_100` → `50 <= price < 100`
- `100_200` → `100 <= price < 200`
- `over_200` → `price >= 200`

### Sort
Apply **available-first ordering as the primary sort key in every case** (preserve current behavior): `status == 'available'` ranks before reserved/sold. Then the secondary key:

- `newest` (default): `created_at` descending.
- `price_asc`: `price` ascending.
- `price_desc`: `price` descending.
- `best_deal`: discount percentage `(retail_price − price) / retail_price` descending. Items with NULL `retail_price` get an effective 0% and sort last within their availability group.

> The discount **filter** was intentionally cut: the AI floors `retail_price` so every shown item is already ≥ 40% off, which would make a "40%+" filter match everything and "60/70%+" buckets noisy. Deals are surfaced via the `best_deal` **sort** instead.

### Result count
Compute and display a count of items matching the active filters (before pagination) — e.g. "247 items" or, when filtered, "23 results". This is a cheap COUNT on the filtered query. (Note: a prior change removed the count from the public header for infinite scroll; we are **deliberately bringing it back** because it is genuinely useful once filters exist — especially to confirm a filter narrowed results. Place it in the `.shop-active-filters` row, not the page title.)

### Active filter chips
Above the grid, render one removable chip per active filter value (e.g. "Like New ✕", "Under $25 ✕", a subcategory name ✕). Each chip's remove control is an `<a>` to the current URL **with that one value removed** (server-rendered href). Show a "Clear all" link that points to `/inventory` with all filter params dropped (keep nothing — back to the full unfiltered shop). Search term, if present, also appears as a removable chip.

### Infinite scroll
Preserve the existing IntersectionObserver + sentinel + `?ajax=1` approach. The critical requirement: **the sentinel's fetch URL must include the full current query string** (all active filters + sort + next page marker) so subsequent pages stay consistent with the active filters. The ajax branch must apply the identical filter/sort logic and render `_item_card.html` for each item.

### Forward-compatibility (multi-location — design only, do not build)
Structure the base item query so a `location` / `store` constraint can be added as one more `.filter(...)` clause without restructuring. Add a brief code comment at the point where such a clause would go (e.g. right after the `ai_approved` / `needs_new_photo` visibility filters). Do not add the param, the column, or the UI now.

---

## Constraints (do NOT touch)

1. **Server-rendered only.** No React/Vue. Filtering is GET-based navigation; the ajax branch returns rendered HTML fragments, not JSON. Vanilla JS for the sheet/auto-submit enhancement only.
2. **Never hardcode colors.** Use the CSS variables in `static/style.css` (`--primary`, `--accent`, `--bg-cream`, `--text-muted`, `--rule`, `--sage`, etc.). All new CSS lives in `static/style.css`.
3. **Preserve the shop visibility gate** exactly: items appear only when `ai_approved == True` AND `needs_new_photo == False` AND `status != 'rejected'` AND `price > 0`. Do not loosen or change this.
4. **Preserve teaser mode** (`shop_teaser_mode == 'true'` → `inventory_teaser.html`). The redesign must not run in teaser mode.
5. **Preserve** the store indicator, `store_open_date` banner, and reserve-only-mode behavior.
6. **Do not change** what data is exposed to buyers. Seller info, suggested price, quality **number**, collection method, and pickup logistics must remain hidden. Condition is shown only as the label (Like New / Good / Fair), never the raw integer.
7. **Do not modify** `product.html`, `inventory_teaser.html`, or `layout.html` (including the nav location selector).
8. **No migration / no model changes.** Everything needed already exists.
9. **No `tojson` in `onclick`.** Use `data-*` attributes for any JS-consumed item data.
10. **Preserve the existing search param name and behavior** — verify before renaming anything.
11. **Preserve the existing infinite-scroll pagination mechanism** — extend it to pass filter params, don't replace it.

---

## Responsive specification (build to these exactly)

**Sidebar vs. sheet boundary: 900px.**
- `≥ 900px`: persistent left sidebar (~210px) visible; "Filters" button hidden; filters auto-submit on change.
- `< 900px`: sidebar hidden; "Filters" button visible; filters open the bottom sheet and submit via "Show results".

**Item grid columns:**
- `≥ 1280px`: 4 columns
- `1024–1279px`: 3 columns
- `900–1023px`: 2 columns (sidebar still present)
- `600–899px`: 2 columns (sheet mode)
- `< 600px`: 2 columns, compact (reduced padding, smaller title/price type)

Use a 12–16px grid gap; tighten to ~8–10px below 600px. Cards must never overflow their column — clamp titles and constrain images to the square ratio.

**Category tab bar:** single row, horizontally scrollable (`overflow-x: auto`, hidden scrollbar), never wraps, at all breakpoints.

**Mobile sheet:** slides up from bottom, max-height ~85vh, internal scroll for filter groups, sticky footer ("Clear all" text button + "Show results" primary button). Backdrop behind it. Never use `position: fixed` in a way that breaks if the codebase already manages overlays — match existing modal/overlay patterns in this app (check how the approval modal / pickup modal handle this) for consistency.

---

## Testing checklist (verify before sign-off)

- [ ] Desktop: sidebar visible; changing a condition checkbox reloads with filtered results from the top; active-filter chips appear; "Clear all" resets.
- [ ] Desktop: sort select changes order; `best_deal` puts highest-% -off items first (within available group); NULL-retail items sort last.
- [ ] Mobile (≤ 600px and ~390px): "Filters" opens the sheet; selecting filters does not reload until "Show results"; sheet closes on apply, backdrop, and Escape; body scroll locks while open.
- [ ] Mobile grid is 2 columns and cards don't overflow at 390px.
- [ ] Category tab switch resets subcategory; subcategory group hidden when category has no children.
- [ ] Price buckets union correctly (e.g. `under_25` + `50_100` returns both ranges, nothing in `25_50`).
- [ ] Infinite scroll loads the next page **with active filters preserved** (network request includes all params).
- [ ] Result count reflects active filters.
- [ ] No-JS: form still submits via "Apply filters"; category tabs navigate; results filter correctly.
- [ ] Teaser mode still renders the teaser page untouched.
- [ ] Reserve-only mode and store-open banner still render; sold/reserved items show overlay and sort last.
- [ ] Full-page cards and `?ajax=1` cards render identical markup (same `_item_card.html`).
- [ ] No hardcoded colors introduced; all new CSS uses variables and lives in `static/style.css`.

---

## After the build

Cross-reference the entire codebase against the project reference docs and update them to reflect the new state: `CODEBASE.md` (route notes for `/inventory` params, new `_item_card.html` partial, deprecated `_category_grid.html`), `HANDOFF.md` (what shipped + any deviations), `DECISIONS.md` (record: discount filter cut, count re-added, GET-based filtering rationale, 900px sidebar/sheet boundary), and `website-feature-log.md` (update the Shop Front section to the new layout and filter set). Note any deviations from this spec explicitly.
