# Feature: Route Photo Report

## Goal

Henry needs to visually scan every item that went out on a given route (truck/shift) at a glance — a single scrollable page of photos, not a list he has to click through item-by-item. Today the only way to see "everything on this route" is the Warehouse > Browse by Route text/table view, which is accurate but slow to visually audit against a truck's contents.

This feature adds a **Route Photo Report**: a standalone, printable HTML page showing every item picked up on a route, grouped by stop in route order, with a large photo, item ID, title, and seller name under each one.

This is a read-only reporting view. No new business logic, no state changes, no model changes.

---

## UX Flow

1. Henry is on `/admin/warehouse`, "Browse by Route" tab, and has clicked a shift chip (existing behavior — loads `admin/warehouse_route_results.html` into `#warehouse-search-results`).
2. At the top of that results partial, a new **"📋 Photo Report"** button/link appears (only in route mode, since it needs a `shift_id`).
3. Clicking it opens `/admin/warehouse/routes/<shift_id>/photo-report` in a new tab (`target="_blank"`).
4. The report page shows:
   - A header: route label (`shift.label`), item count, generated timestamp, a "Print" button, and a "← Back" link (closes tab or links back to `/admin/warehouse`).
   - The route's stops in `stop_order` sequence. Each stop is a section with a small header: stop number, seller name, item count for that stop.
   - Under each stop header, a responsive grid of item cards. Each card = photo (or placeholder if missing) + `#<item.id>` + title + seller name.
5. Henry scrolls the page to visually check every item against the physical truck contents. If he wants a hardcopy, he hits Print (browser print dialog, print-optimized CSS kicks in).

### Edge cases

- **Shift has no `ShiftPickup` rows at all** → page shows an empty state: "No sellers assigned to this route yet." with a back link. (Shouldn't be reachable in practice since the route chip list already omits shifts with zero items, but guard it anyway.)
- **Seller has zero items** (e.g. all items rejected/deleted after pickup) → seller's stop section is simply omitted from the report (don't show an empty section). This mirrors existing Route Browse behavior, which is item-driven.
- **`stop_order` is NULL for some or all stops** (route hasn't been ordered yet via "Order Route") → stops with NULL `stop_order` are grouped at the end under a subheader **"Unordered stops"**, sorted alphabetically by seller name within that group. A small amber notice appears at the top of the page: "Route order not finalized — some stops are shown unordered." This reuses the same nulls-last convention already used elsewhere (e.g. driver shift view).
- **Item has no `photo_url`** → render a gray placeholder box (same aspect ratio as photo cards) with the item ID visible, so it's obviously present-but-unphotographed rather than silently missing.
- **Very long item title** → truncate with CSS (`-webkit-line-clamp` or similar), 2 lines max, so grid rows stay even.
- **Shift not found** (bad/stale ID) → 404.
- **Non-ops-access user hits the URL directly** → same guard as the rest of warehouse tooling (`_has_ops_access()`), redirect/403 per existing convention.

---

## New Routes

| Method | Path | Function | Description |
|--------|------|----------|--------------|
| GET | `/admin/warehouse/routes/<int:shift_id>/photo-report` | `admin_warehouse_route_photo_report` | Standalone printable HTML page. Guard: `_has_ops_access()`. 404 if shift doesn't exist. |

No other routes change. No JSON endpoints needed — this is a single server-rendered page.

---

## Model Changes

**None.** This feature is read-only and uses existing fields:
- `Shift.label`, `Shift.id`
- `ShiftPickup.shift_id`, `ShiftPickup.seller_id`, `ShiftPickup.stop_order` (nulls-last ordering)
- `InventoryItem.id`, `.description` (used as title, consistent with how titles are shown elsewhere), `.photo_url`, `.seller_id`
- `User.full_name` (seller display name)

No migration required.

---

## Template Changes

### New: `templates/admin/warehouse_route_photo_report.html`
Standalone page — **does not extend `admin_layout.html`**. This is deliberately a minimal, print-focused page (no admin sidebar/nav chrome to strip out at print time). It should still:
- Use CSS variables from `static/style.css` for colors/fonts (never hardcode) so it stays on-brand.
- Include a small inline `<style>` block for the report-specific grid/print rules (self-contained, since it's not going through `layout.html`).

Structure:
```html
<header> route label, item count, generated-at timestamp, Print button, Back link </header>
[amber notice if any stop_order is NULL]

<section per stop, in order>
  <h2>Stop N — {seller.full_name} ({item_count} items)</h2>
  <div class="photo-grid">
    <div class="photo-card" data-item-id="{{ item.id }}">
      <img loading="lazy" src="{{ url_for('uploaded_file', filename=item.photo_url) }}">
      <!-- OR a placeholder div if photo_url is null -->
      <p class="item-id">#{{ item.id }}</p>
      <p class="item-title">{{ item.description }}</p>
      <p class="item-seller">{{ seller.full_name }}</p>
    </div>
    ... repeated
  </div>
</section>

<section class="unordered-stops"> ... same structure, if any ... </section>
```

Grid: CSS Grid, `grid-template-columns: repeat(auto-fill, minmax(170px, 1fr))`, gap ~12px. Cards ~170–200px wide, photo as a square/near-square crop (`object-fit: cover`) so the grid stays even regardless of source image aspect ratio.

**Print stylesheet** (`@media print`):
- Hide the Print/Back buttons.
- Force a denser grid (e.g. `repeat(5, 1fr)` or similar fixed column count — more predictable for paper than `auto-fill`).
- `break-inside: avoid` on `.photo-card` so cards don't split across a page boundary.
- Stop section headers (`h2`) get `break-after: avoid` so a header doesn't strand at the bottom of a page.

**IMPORTANT:** Use `url_for('uploaded_file', filename=item.photo_url)` for every image — never `url_for('static', filename='uploads/' + ...)`. This is a known footgun in this codebase (404s on Render).

### Modified: `templates/admin/warehouse_route_results.html`
Add a "📋 Photo Report" link/button near the top of the partial, only rendered when in route mode (this template is already the route-mode-only partial, so no conditional needed beyond that). Link target:
```html
<a href="{{ url_for('admin_warehouse_route_photo_report', shift_id=shift_id) }}" target="_blank" class="btn ...">📋 Photo Report</a>
```
Confirm `shift_id` is already available in this template's render context (it's passed in for the "no status filter" query today) — reuse it, don't re-derive.

---

## Business Logic

**Query, in `admin_warehouse_route_photo_report`:**

1. Load `shift = Shift.query.get_or_404(shift_id)`.
2. Load all `ShiftPickup` rows for this shift: `ShiftPickup.query.filter_by(shift_id=shift_id).all()`.
3. If none → render empty state.
4. Split into two groups: `ordered = [p for p in pickups if p.stop_order is not None]` sorted by `stop_order`; `unordered = [p for p in pickups if p.stop_order is None]` sorted by `p.seller.full_name`.
5. For each pickup (in either group), load that seller's items with **no status filter** (matches existing Route Browse behavior — approved, pending, sold, everything): `InventoryItem.query.filter_by(seller_id=pickup.seller_id).order_by(InventoryItem.id).all()`.
6. Skip rendering a stop section if that seller has zero items.
7. Pass `ordered_stops`, `unordered_stops` (each a list of `(pickup, seller, items)` tuples) to the template, plus `shift`, `total_item_count`, `has_unordered` flag for the amber notice.

**No writes.** This route is GET-only, no side effects, no need for CSRF token.

**Performance note:** With ~200 items max, this is a handful of queries (one per pickup for its items) — fine at this scale. Not worth optimizing into a single join given the low item ceiling Henry described; keep it simple and readable.

---

## Constraints

- Do not touch `admin_warehouse_search`, `admin_warehouse_routes`, or any existing Route Browse behavior — this is purely additive.
- Do not add a status filter — matches existing Route Browse convention of showing all items regardless of status.
- Do not build a PDF generation pipeline — HTML + browser print is sufficient per Henry's decision.
- Do not create new image assets/thumbnails — reuse `item.photo_url` (cover photo) as-is; no image processing.
- Must use `url_for('uploaded_file', filename=...)` for all image sources (see CONTEXT.md footgun note).
- Must use `_has_ops_access()` guard, consistent with all other warehouse/ops routes — not `is_admin` alone, not `is_super_admin`.
- No new model fields, no migration.

---

## Testing Checklist

- [ ] `/admin/warehouse/routes/<id>/photo-report` loads for a shift with multiple stops and items
- [ ] Stops render in `stop_order` sequence
- [ ] Stops with NULL `stop_order` render after ordered stops, alphabetically by seller name, under "Unordered stops"
- [ ] Amber notice appears only when at least one stop has NULL `stop_order`
- [ ] Amber notice does NOT appear when all stops are ordered
- [ ] Each item card shows photo (or placeholder), `#id`, title, seller name
- [ ] Item with `photo_url = None` renders a placeholder box, not a broken image
- [ ] Seller with zero items on this shift produces no empty section
- [ ] Items include all statuses (pending, approved, available, sold, rejected) — no filtering
- [ ] Shift with zero `ShiftPickup` rows shows the empty state, not an error
- [ ] Invalid/nonexistent `shift_id` → 404
- [ ] Non-ops-access user (regular seller/buyer) → redirected/blocked, consistent with other warehouse routes
- [ ] "📋 Photo Report" button appears in Route Browse results and opens the report in a new tab with the correct `shift_id`
- [ ] Print preview: buttons hidden, grid reflows to fixed columns, no card splits across a page break
- [ ] Page performs acceptably with ~200 items (spot-check load time)

---

## Post-Build

Cross-reference the entire codebase with the files in `@gigaAdminSpec/` and update `CODEBASE.md`, `HANDOFF.md`, `DECISIONS.md`, and `website-feature-log.md` to reflect the current state when finished with this spec.
