# Feature Spec: CSV Export Button on Admin Items Page

## Goal

Admins currently have to navigate to a hidden export URL (`/admin/export/items`) or
find the button buried in the Settings tab to download item data. This adds a visible
"Export CSV" button directly on the `/admin/items` page so it's one click away from
where admins are already looking at item data.

No new routes, no model changes, no migration. This is purely a template change that
surfaces the already-existing `admin_export_items` route.

---

## UX Flow

1. Admin visits `/admin/items` (either the All Items view or the Approval Queue view).
2. A small "Export CSV" button is visible in the stats bar row (top of the items tab,
   right-aligned), alongside the Total / Pending / Available / Sold counts.
3. Admin clicks the button. The browser immediately downloads the CSV via
   `GET /admin/export/items` — no confirmation dialog, no page reload.
4. Done.

**Edge cases:**
- The button is always visible regardless of which sub-tab (All Items vs. Approval Queue)
  is active — the export covers all items regardless of the current filter view.
- The export is the full all-items CSV (existing behavior of `admin_export_items`).
  The current filter state (category, seller email, title search) is **not** applied to
  the export — the export is always the full dataset. This matches the pattern used by
  the existing payouts and sales exports, and avoids adding query-param plumbing.
- The button is visible to all admins (not super-admin-only), consistent with the
  existing route's auth guard.

---

## New Routes

None. The export is handled by the existing route:

| Method | Path | Function | Description |
|--------|------|----------|-------------|
| `GET` | `/admin/export/items` | `admin_export_items` | Already exists. CSV of all items. |

---

## Model Changes

None. No migration needed.

---

## Template Changes

### `templates/admin/items.html`

**One change only:** add an "Export CSV" anchor link in the stats bar row.

The stats bar currently renders Total / Pending / Available / Sold count chips.
Add a right-aligned `<a>` tag after the stat chips that links to
`/admin/export/items`. Style it as a secondary button using the existing
`.btn-secondary` or `.btn-outline` class from `style.css` (whichever renders as
a small outlined button — check `static/style.css` to confirm the correct class).

Placement: The stats bar is a flex row. Wrap the existing stat chips in a
`<div class="stats-left">` and add a `<div class="stats-right">` containing the
export link on the opposite end. Alternatively, add `margin-left: auto` directly
on the export link if the flex container already stretches.

Exact markup target (adapt to actual template structure after reading the file):

```html
<a href="{{ url_for('admin_export_items') }}"
   class="btn btn-sm btn-outline"
   title="Download all items as CSV">
  <i class="fas fa-download"></i> Export CSV
</a>
```

Use `url_for('admin_export_items')` — never hardcode the path.

**Do not** add a second export button in the filter bar or table footer.
One button in the stats bar is sufficient.

---

## Business Logic

No logic changes. `admin_export_items` already:
- Queries all `InventoryItem` rows joined with `User` (seller) and `InventoryCategory`
- Streams a CSV response with `Content-Disposition: attachment`
- Requires `is_admin` (auth guard already in place)

The export columns are whatever `admin_export_items` already produces — this spec does
not change the export format.

---

## Constraints

- Do **not** modify `app.py` — no route changes.
- Do **not** modify `models.py`.
- Do **not** add filter-aware export behavior (no query params passed to the export URL).
- Do **not** move or restructure the stats bar layout beyond adding the button.
- The existing `GET /admin/export/items` button in the Settings tab data-exports section
  must remain — do not remove it.
- All color/style must use existing CSS variables and component classes — no new CSS
  for this feature.
