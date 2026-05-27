# Feature Spec: Storage Audit Tool

## Goal

Enable a campus director (or admin) doing a physical walk-through of a storage unit to quickly find any item by ID or name, verify or correct its storage unit and zone, and update the record in-place — all from a phone. Also adds ID-based search to the existing admin items table for desktop use.

Replaces the organizer intake zone assignment (intake page is being deprecated). The zone field (`storage_row`) on `InventoryItem` is repurposed from free-text to a fixed 6-value enum representing physical position within a storage unit.

---

## Storage Zone Enum

Replace the free-text `storage_row` field with one of six fixed values:

```
'back_left' | 'middle_left' | 'front_left' | 'back_right' | 'middle_right' | 'front_right'
```

NULL = not yet assigned. These map to a visual diagram:

```
BACK  [ Back Left  ] | [ Back Right  ]
      [    Mid Left ] | [ Mid Right   ]
FRONT [ Front Left ] | [ Front Right ]
           ← walkway →
```

No migration to the column type — it stays `String(nullable)`. The enum is enforced at the application layer (validated on write, rendered as a diagram in the UI). Existing free-text values in `storage_row` are treated as unassigned (displayed as "—") until updated via this tool or the driver placement flow.

---

## UX Flow

### Entry Point

- Admin nav: link in the Items tab or Storage section — "Storage Audit"
- Direct URL: `/admin/storage/audit`
- Accessible to: `is_admin`, `is_super_admin`, `is_campus_director` (use `_has_ops_access()`)

### Page Layout (mobile-first)

Large search input at top: placeholder "Item ID or title…"

- Typing triggers a debounced fetch (300ms) to `/admin/storage/audit/search?q=<query>`
- Results render below as item cards
- Page has no table — it's purely search → result → edit

### Search Behavior

- **Numeric input** → exact match on `InventoryItem.id`
- **Text input** → ILIKE on `description` + seller `full_name`, max 20 results
- All statuses included (pending, available, sold, etc.)
- `is_tutorial_user` sellers excluded (standard production guard)

### Result Card (collapsed)

Each card shows:
- Item ID badge (e.g. `#142`)
- Title (description)
- Seller name
- Current storage unit name (or amber "No unit assigned")
- Current zone (or amber "No zone assigned")
- Status chip
- "Edit Location" button

### Result Card (expanded — tap "Edit Location")

Card expands in-place (no new page). Shows:

1. **Storage unit dropdown** — active, non-full `StorageLocation` records. Pre-selected to current `storage_location_id` or blank. Includes a "— Clear —" option to null out the field.
2. **Zone diagram** — 6 clickable zones as described above. Currently assigned zone is highlighted. Tap to select/deselect. Includes a "Not placed" option below the diagram to explicitly clear the zone.
3. **Note field** — short optional text (maps to `storage_note`). Pre-filled if one exists.
4. **Save button** → fetch POST to `/admin/item/<id>/set_location` → card updates in-place with green "Saved ✓" indicator. Card stays open (does not collapse).
5. **Cancel** → collapses back to summary view, no save.

---

## New Routes

| Method | Path | Function | Description |
|--------|------|----------|-------------|
| `GET` | `/admin/storage/audit` | `admin_storage_audit` | Audit page — search input, empty results container. Accessible via `_has_ops_access()`. |
| `GET` | `/admin/storage/audit/search` | `admin_storage_audit_search` | Returns HTML partial (`storage_audit_results.html`). Query param `q`. |
| `POST` | `/admin/item/<id>/set_location` | `admin_item_set_location` | Write `storage_location_id`, `storage_row`, `storage_note` to item. Returns JSON. Accessible via `_has_ops_access()`. |

---

## Model Changes

### `InventoryItem.storage_row`

No column type change (stays `String`, nullable). Application layer now validates that any written value is one of:
`'back_left'`, `'middle_left'`, `'front_left'`, `'back_right'`, `'middle_right'`, `'front_right'`, or `None`.

Existing free-text values are not migrated — they render as "—" (unassigned) in all new UI. When a new zone is saved via this tool or the driver placement flow, the old free-text value is overwritten.

**No migration required** — column already exists, type unchanged.

---

## Template Changes

### New: `admin/storage_audit.html`
- Extends `admin_layout.html`
- Mobile-first layout (max-width ~480px centered, readable on phone)
- Large search `<input>` with `id="audit-search"`
- `<div id="audit-results">` — fetch target
- JS: debounced input listener (300ms), fetch GET to `/admin/storage/audit/search?q=<val>`, inject response HTML into `#audit-results`
- JS: event delegation on `#audit-results` for "Edit Location" toggle, zone diagram clicks, Save/Cancel buttons
- Zone diagram: SVG or CSS grid of 6 labeled boxes. Selected zone gets `--accent` background. Clicking a selected zone deselects it (clears to null).

### New: `admin/storage_audit_results.html`
- Partial — no layout wrapper
- List of item cards. Each card has `data-item-id` attribute.
- Collapsed state: summary row with "Edit Location" button
- Expanded state: unit dropdown + zone diagram + note field + Save/Cancel
- Uses `data-*` attributes for all JS-readable state (current zone, current location id). No inline tojson.

### Modified: `admin/items.html`
- Add "Item ID" text input to the existing filter bar (alongside category, seller email, item title)
- Submits as `?item_id=<val>` query param on the existing filter form
- Backend: `admin_items` route adds `filter by id` to its query when `item_id` param present

---

## Business Logic

### `admin_item_set_location`
- Auth: `_has_ops_access()` — admins and campus directors only
- Accepts: `storage_location_id` (int or empty string), `storage_row` (string or empty string), `storage_note` (string, optional)
- If `storage_location_id` is empty string → set to `None` (clear)
- If `storage_location_id` is provided → validate that `StorageLocation` exists and `is_active=True`. Return 400 if not.
- If `storage_row` is provided → validate against the 6-value enum. Return 400 if not a valid value.
- If `storage_row` is empty string → set to `None` (clear)
- Writes directly to `InventoryItem`. Does NOT create an `IntakeRecord`. Does NOT touch `arrived_at_store_at`.
- Returns JSON: `{success: true, location_name: str|null, zone: str|null}`

### `admin_storage_audit_search`
- Auth: `_has_ops_access()`
- `q` param: strip whitespace. If empty, return empty partial (no results, no error).
- If `q` is all digits: query `InventoryItem.id == int(q)`
- Otherwise: ILIKE on `InventoryItem.description` + `User.full_name` (join on seller), limit 20
- Exclude items owned by `is_tutorial_user` sellers
- Return rendered `storage_audit_results.html` partial

### `admin_items` (modified)
- If `item_id` query param present and is a valid integer: add `InventoryItem.id == item_id` to filter
- No other changes to existing filter logic

---

## Constraints — Do Not Touch

- `IntakeRecord` creation logic — this tool bypasses it intentionally
- `arrived_at_store_at` — not written by this tool
- The existing `/admin/storage/<id>` detail page — unchanged
- The existing organizer intake page and routes — left in place for now (deprecation is a separate cleanup task, not this spec)
- `ShiftPickup.storage_location_id` — this is the *planned* destination written by admin; this tool writes to `InventoryItem.storage_location_id` only
- All existing filter behavior on `admin_items` route — new ID filter is additive only

---

## Checklist (for Claude Code verification)

- [ ] `/admin/storage/audit` loads for admin, super admin, campus director
- [ ] `/admin/storage/audit` returns 403 for non-admin, non-CD logged-in users
- [ ] Typing a numeric ID returns the matching item card
- [ ] Typing a name returns matching items (case-insensitive)
- [ ] Empty search returns empty results, no error
- [ ] "Edit Location" expands the card in-place
- [ ] Zone diagram: tapping a zone highlights it; tapping again deselects
- [ ] Saving with a valid unit + zone updates `storage_location_id` and `storage_row` on the item
- [ ] Saving with "— Clear —" unit sets `storage_location_id = None`
- [ ] Saving with "Not placed" zone sets `storage_row = None`
- [ ] Card stays open after save with green confirmation
- [ ] Cancel collapses card without saving
- [ ] Invalid zone value returns 400
- [ ] Inactive storage location returns 400
- [ ] `/admin/items` filter bar accepts `?item_id=` param and filters correctly
- [ ] Tutorial-user items do not appear in audit search results
