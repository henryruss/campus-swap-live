# Feature Spec: Warehouse Floor

**Status:** Ready for implementation  
**Replaces:** `/admin/storage/audit` (renamed + redesigned)  
**Auth:** Admin (all routes). Super admin required only where noted.

---

## Goal

Give the campus director a single, canonical tool for walking the physical warehouse and ensuring every item is logged, located, and ready for AI autofill. The page replaces the old storage audit search tool with a visual unit-card grid, per-unit item modals, capacity tracking, and an on-the-spot item logging flow (photo + category + seller assignment).

---

## UX Flow

### Landing page — `/admin/warehouse`

The page shows a **card grid of all active storage units**. Each card displays:

- Unit name
- Item count (non-rejected, non-sold items assigned to this unit)
- Capacity battery bar (see Capacity Logic below)
- "Full" badge when `is_full=True`
- A **"Log Item"** button (global, top of page, always visible)

Cards are sorted: units with items first, then empty units. Full units shown with a distinct visual treatment (grey out or strikethrough) but still accessible.

A **global search bar** sits at the top of the page, always visible. Typing filters items across all units in real time (debounced fetch, 300ms). Search results appear below the unit grid as a flat list of item cards — same as today's audit search results.

Clicking a unit card opens the **unit modal**.

---

### Unit modal

A slide-in panel (same pattern as seller profile panel — no new page). Contains:

**Header:**
- Unit name + address
- Item count + capacity battery (same as card)
- "Mark as Full / Mark as Available" toggle button (admin only)
- "Log Item Here" button (pre-populates this unit in the log flow)

**Body:**
- Search bar scoped to this unit (autosaves location on assignment — see below)
- Item list: all non-rejected items in this unit, sorted by storage row then date added
- Each item row shows: thumbnail, item ID badge, title (or "Untitled" if blank), category, condition, status pill, storage row (editable inline — autosaves on change), and an "Edit" link to the standard admin edit page

**Autosave on location change:**  
When admin changes the storage row field on any item row, it auto-POSTs to the existing `POST /admin/item/<id>/set-location` route (no Save button needed). Matches the pattern already used on the current audit page.

**Item search within modal:**  
Typing in the unit-scoped search bar fetches matching items via `GET /admin/warehouse/search` (same backend as global search but filtered by `unit_id`). Selecting a search result that belongs to a *different* unit re-assigns it to this unit (with a confirmation prompt: "Move item #42 from Unit B to Unit A?"). Selecting a result already in this unit scrolls to it.

---

### Log Item flow (unknown item capture)

Triggered by either the global "Log Item" button or the per-unit "Log Item Here" button. Opens a **capture modal** on top of the unit modal (or standalone if triggered globally).

**Step 1 — Photo**  
Camera interface. Identical to the existing crew quick capture modal. Rear-facing camera, file-input fallback. Photo is required before proceeding.

**Step 2 — Category**  
Category picker (grid of category cards, same visual as onboarding step 1). Required. Subcategory optional (loads via existing AJAX endpoint).

**Step 3 — Storage location**  
- If opened from a unit card: pre-populated with that unit, storage row field editable
- If opened from global button: unit dropdown (all active non-full units) + storage row field
- Both fields optional but encouraged

**Step 4 — Seller assignment**  
Three radio options:

**Option A — Campus Swap owns it**  
Default selection. Assigns to `is_internal_account=True` user. `payout_rate` irrelevant (no payout owed).

**Option B — Existing seller**  
Live search by name or email (debounced, fetches from `GET /admin/warehouse/seller-search`). Selecting a result shows their name, email, item count, and payout rate. Assigns item to that seller at their existing `payout_rate`.

**Option C — New word-of-mouth seller**  
Form fields:
- Full name (required)
- Email (required if no phone) 
- Phone (required if no email)
- At least one of email or phone must be provided — validated server-side

On save: creates a new `User` record via the existing proxy account creation flow. Sets `payout_rate=50`, `is_seller=True`, `is_proxy_account=True` (this flag already exists and drives the proxy banner in the sellers tab). Randomized unusable password. No welcome email sent at capture time — admin contacts them manually later, same as existing proxy flow.

**Save button** creates the `InventoryItem`:
- `is_quick_capture=True`
- `status='pending_valuation'`
- `category_id` from step 2
- `storage_location_id` + `storage_row` from step 3
- `seller_id` from step 4
- `picked_up_at = utcnow()`
- `photo_url` saved to disk (same upload logic as existing quick capture)

After save: item appears immediately in the unit modal's item list (if unit was selected). Flash: "Item #382 logged — ready for AI autofill."

---

## Capacity Logic

### How capacity is tracked

`StorageLocation` already has `is_full` (Boolean). Two new fields are added:

```
StorageLocation.snapshot_capacity   (Float, nullable)
```

When admin clicks **"Mark as Full"**:
1. Compute `total = sum(item.unit_size or category.default_unit_size for all non-sold, non-rejected items in this unit)`
2. Store that value as `snapshot_capacity`
3. Set `is_full = True`

**Battery % calculation (at render time):**
```python
if location.snapshot_capacity and location.snapshot_capacity > 0:
    current = sum(item.unit_size or item.category.default_unit_size or 1.0
                  for item in location.items
                  if item.status not in ('sold', 'rejected'))
    pct = round((current / location.snapshot_capacity) * 100)
else:
    pct = None  # show "—" if never been marked full
```

As items sell or are rejected, `current` naturally decreases and the battery drains. As new items are added, it increases (can exceed 100% if overfilled).

**"Mark as Available"** (un-full): sets `is_full = False`. Does NOT clear `snapshot_capacity` — preserves the baseline for future reference. The battery bar continues to display based on the snapshot.

**Battery visual:**
- 75–100%: green
- 40–74%: amber  
- Under 40%: red (selling down, nearly empty)
- Over 100%: a distinct "over capacity" indicator (dark red / striped)
- No snapshot yet: grey bar with "Capacity not set"

---

## Removing the Admin Quick Capture Queue

The existing route `GET /admin/items/needs_info` (`admin_needs_info_queue`) and its template `admin/needs_info.html` are **removed**. The nav badge and `qc_pending_count` context processor injection are also removed.

**What happens to existing QC items in that queue?**  
Items with `is_quick_capture=True` and `status='pending_valuation'` are already eligible for AI autofill (the eligibility query in `feature_ai_autofill.md` includes them). They will appear in the AI review queue after the next generation run. No data migration needed.

**The `is_quick_capture` flag is NOT removed** — it remains on the model and is still set on items created through the log flow. It continues to be excluded from the standard approval queue and approval digest. The only thing removed is the dedicated admin viewing page for it.

---

## Adding Category to Crew Quick Capture

The existing crew quick capture modal (`templates/crew/quick_capture_modal.html`) gets a category selection step added between the photo step and the notes step.

- Same category card grid as onboarding step 1
- Required before Save is enabled
- `category_id` added to the `POST /crew/quick_capture` form submission
- Backend writes `item.category_id` on creation
- If somehow submitted without category (direct POST): category defaults to null (existing behavior) — no hard block server-side, but UI enforces it

This is a **one-place fix** since the modal is a standalone partial included in both `crew/dashboard.html` and `crew/shift.html`.

---

## New Routes

| Method | Path | Function | Auth | Description |
|--------|------|----------|------|-------------|
| `GET` | `/admin/warehouse` | `admin_warehouse` | Admin | Main page — unit card grid + global search bar |
| `GET` | `/admin/warehouse/unit/<id>` | `admin_warehouse_unit` | Admin | HTML partial (no layout) for unit modal content. Returns item list + header data. |
| `POST` | `/admin/warehouse/unit/<id>/toggle-full` | `admin_warehouse_toggle_full` | Admin | Toggle `is_full`. On marking full: computes + stores `snapshot_capacity`. Returns JSON `{is_full, snapshot_capacity, battery_pct}`. |
| `GET` | `/admin/warehouse/search` | `admin_warehouse_search` | Admin | HTML partial. Params: `q` (text), `unit_id` (optional — scopes to unit). Returns item rows. |
| `GET` | `/admin/warehouse/seller-search` | `admin_warehouse_seller_search` | Admin | JSON. Param: `q`. Returns `[{id, name, email, item_count, payout_rate}]` for live seller search in log modal. |
| `POST` | `/admin/warehouse/log-item` | `admin_warehouse_log_item` | Admin | Create QC item from warehouse floor. Handles new seller creation inline. Returns JSON `{success, item_id, unit_id}`. |
| `POST` | `/admin/warehouse/seller/create` | `admin_warehouse_create_seller` | Admin | Create proxy seller (name + email/phone). Returns JSON `{success, user_id, name}`. Called from log modal step 4. |

**Redirects:**
- `GET /admin/storage/audit` → 302 to `/admin/warehouse` (preserves any existing bookmarks)
- `GET /admin/storage/audit/search` → 302 to `/admin/warehouse/search` (in case anything links to it)

**Existing routes that remain unchanged:**
- `POST /admin/item/<id>/set-location` — still used for autosave within unit modal
- `POST /admin/item/<id>/replace-photo` — still accessible from item edit, not from warehouse floor
- `GET /admin/storage/<id>` — still exists as a detail page (linked from settings)

---

## Model Changes

One new field on `StorageLocation`. One migration required.

```
StorageLocation.snapshot_capacity   (Float, nullable, default None)
```

**Migration name:** `add_warehouse_floor_fields`

No changes to `InventoryItem`. No new tables. The `is_quick_capture`, `category_id`, `storage_location_id`, `storage_row` fields already exist.

---

## Template Changes

### New templates

**`templates/admin/warehouse.html`** — extends `admin_layout.html`
- Page header: "Warehouse Floor" + "Log Item" button (primary, top right)
- Global search bar (always visible, debounced 300ms → fetches `admin_warehouse_search` partial)
- Search results area (hidden when search is empty, shown below unit grid when active)
- Unit card grid (CSS grid, responsive — 3 columns desktop, 2 tablet, 1 mobile)
- Unit card component: name, item count, battery bar, "Full" badge if applicable
- Empty state: "No active storage units — create one in Settings"

**`templates/admin/warehouse_unit_partial.html`** — no layout (partial)
- Unit header: name, address, item count, battery bar, toggle-full button, "Log Item Here" button
- Scoped search bar (fetches `admin_warehouse_search?unit_id=<id>`)
- Item list table: thumbnail, ID badge, title, category, condition, status pill, storage row input (autosave), Edit link
- Empty state: "No items in this unit yet"

**`templates/admin/warehouse_log_modal.html`** — no layout (partial, rendered into modal)
- Step 1: Camera interface (reuse `quick_capture_modal.html` camera block — extract as a sub-partial or duplicate and reference)
- Step 2: Category grid (same card grid as onboarding — can reference `_category_grid.html` pattern)
- Step 3: Storage location (unit dropdown + row input, or pre-populated)
- Step 4: Seller assignment (three radio options, conditional form fields)
- Footer: Save button (disabled until photo + category selected), Cancel

**`templates/admin/warehouse_search_results.html`** — no layout (partial)
- Flat list of item rows matching search. Each row: thumbnail, ID, title, category, unit name, storage row, status pill, Edit link, "Move to [unit]" button if viewing from within a unit modal.

### Modified templates

**`templates/admin/admin_layout.html`** (or wherever the sidebar nav lives)
- Replace "Storage Audit" nav item with "Warehouse" (warehouse/forklift icon)
- Remove the QC pending count badge (the `qc_pending_count` badge tied to `admin/items/needs_info`)
- Active tab detection: `/admin/warehouse` paths

**`templates/crew/quick_capture_modal.html`**
- Add category selection step between photo capture and notes
- Save button stays disabled until both photo and category are selected
- `category_id` included in form POST data

### Deleted templates

- `templates/admin/needs_info.html` — the old QC admin queue page (removed entirely)

---

## Business Logic & Constraints

### Seller assignment — new proxy seller
- Uses existing proxy account creation pattern from `admin_seller_panel` / sellers page
- `payout_rate = 50` (word-of-mouth sellers get 50%)
- `is_proxy_account = True` — this drives the existing proxy banner in the sellers tab so admin can identify who needs to be contacted
- `is_seller = True`
- Randomized unusable password (same as existing proxy flow)
- No welcome email at creation — admin reaches out manually
- Validation: name required, at least one of email or phone required. Email uniqueness checked — if email already exists, return error: "An account with this email already exists. Search for them in 'Existing Seller' instead."

### Seller assignment — existing seller
- Item assigned at their current `payout_rate` (no change to rate)
- No notification sent to seller at log time

### Seller assignment — Campus Swap
- Assigns to the `is_internal_account=True` user (already seeded)
- `payout_rate` on that account is irrelevant — `is_internal_account` items are excluded from payout exports

### Capacity snapshot
- `snapshot_capacity` is only written when "Mark as Full" is clicked — not on every item change
- If items are added to a unit after it's marked full, capacity % can exceed 100% — this is expected and shown visually
- "Mark as Available" does not clear `snapshot_capacity`
- A unit with `snapshot_capacity = None` shows a grey battery with "Set capacity by marking unit full"

### `is_quick_capture` items and AI autofill
- All items created via `admin_warehouse_log_item` are `is_quick_capture=True`
- They are eligible for AI autofill (status not `rejected` or `sold`, `ai_generated_at IS NULL`)
- They are excluded from the standard approval queue (existing behavior, unchanged)
- The removed `admin_needs_info_queue` route means there is no dedicated admin view for QC items — they exist in the DB and surface via the AI review queue after generation runs

### Search behavior
- Global search: queries `description`, `long_description`, item ID (exact match on `#N` format)
- Unit-scoped search: same query + `storage_location_id = unit_id` filter
- Minimum 2 characters before fetch fires
- Results exclude `rejected` items

### Autosave storage row
- Uses existing `POST /admin/item/<id>/set-location` — no new route needed
- Fires on `change` event (when field loses focus after edit), not on every keystroke
- Shows a brief "Saved ✓" inline confirmation (CSS transition, fades after 1.5s)
- On error: shows "Save failed" in red, field value reverts

---

## Constraints (What Must Not Be Touched)

- `GET /admin/storage/<id>` (storage detail page) — still exists, still works, not part of this spec
- `POST /admin/storage/create`, `edit`, `delete` routes — unchanged (still live in Settings)
- Standard approval queue (`/admin/items?view=approve`) — unaffected
- AI autofill routes — unaffected
- Crew shift view and crew quick capture flow — only change is adding category field to the modal
- `POST /crew/quick_capture` backend route — add `category_id` field handling; all other behavior unchanged
- Organizer intake flow — unaffected
- `is_quick_capture` flag semantics — unchanged; items still excluded from standard approval queue and digest

---

## Edge Cases

| Scenario | Behavior |
|----------|----------|
| Unit has no `snapshot_capacity` set | Battery shows grey with "Mark as full to track capacity" |
| Unit is marked full but then items sell down to 0 | Battery shows 0%, not hidden. Unit card still visible. |
| Admin logs item globally (no unit selected) | Item created with `storage_location_id = None`. Appears in global search results but not in any unit modal. |
| New seller email already exists in DB | Return error: "Account exists — search in Existing Seller" |
| Camera not available on device | File-input fallback (same as crew quick capture) |
| Item in unit modal belongs to a different unit after search + move | Confirmation dialog before reassigning. Unit modal item list refreshes after move. |
| Crew submits quick capture without category (direct POST bypass) | `category_id` written as null — item still created, still eligible for AI autofill which will determine category from photo |
| QC items currently in `admin/items/needs_info` queue | They remain in DB with `is_quick_capture=True`, `status='pending_valuation'`. Eligible for AI autofill. No data migration needed. |

---

## Addendum: Unit Efficiency, Cost Tracking & Consolidation

### Goal

As items sell, Campus Swap needs to consolidate inventory into fewer storage units so that underutilized units can be cancelled. This addendum adds cost/size tracking to storage units, a priority ranking system visible to the campus director, full financials visible to super admins only, and a bulk item move tool inside the unit modal for consolidation work.

---

### New Model Fields on `StorageLocation`

```
StorageLocation.size_sqft      (Float, nullable)      — parsed from Size string at import (e.g. "10x30" → 300.0)
StorageLocation.monthly_cost   (Numeric 8,2, nullable) — monthly rental cost in USD
```

**`cost_per_sqft`** is always derived at runtime: `monthly_cost / size_sqft`. Never stored.

**Migration name:** `add_storage_cost_fields` — add to the existing `add_warehouse_floor_fields` migration if not yet run, or as a separate migration if it has already been applied.

---

### Spreadsheet Import Changes

The existing import route (`POST /admin/storage/import`) and downloadable template (`GET /admin/storage/template`) are updated to support two new columns.

**Updated template columns (in order):**

| Column | Type | Notes |
|--------|------|-------|
| `Unit #` | String | Required. Used as `name`. |
| `Location` | String | Required. Used as `address`. |
| `Size` | String | Required. Format: `WxD` e.g. `10x30`. Parsed to `size_sqft = W × D`. |
| `Monthly Rate` | Number | Optional. Dollar amount e.g. `180` or `180.00`. Written to `monthly_cost`. |

**Parsing rules:**
- `Size`: split on `x` (case-insensitive), multiply the two integers → `size_sqft`. If unparseable, set `size_sqft = None` and continue (don't fail the row).
- `Monthly Rate`: parse as float. If blank or unparseable, set `monthly_cost = None` and continue.
- Existing rows in the import that already exist in the DB (matched by name): update `size_sqft` and `monthly_cost` if the columns are present. Do not overwrite existing values with null if the column is absent from the sheet.

**Template download:** The `GET /admin/storage/template` route returns an updated `.xlsx` with the new `Monthly Rate` column header included. Existing importers who don't fill it in will get `None` for cost, which is fine.

---

### Priority Ranking Logic

Computed at page-load time in the `admin_warehouse` route. Only units with both `size_sqft > 0` and `monthly_cost > 0` are ranked. Units missing either field are unranked.

```python
def _compute_unit_priority(locations):
    rankable = [l for l in locations if l.size_sqft and l.monthly_cost]
    if len(rankable) < 3:
        # Too few units to divide into thirds — mark all rankable as Best Value
        for l in rankable:
            l._priority = 'best'
        for l in locations:
            if not (l.size_sqft and l.monthly_cost):
                l._priority = None
        return

    ranked = sorted(rankable, key=lambda l: l.monthly_cost / l.size_sqft)
    third = len(ranked) // 3

    for i, l in enumerate(ranked):
        if i < third:
            l._priority = 'best'       # lowest cost/sqft
        elif i < third * 2:
            l._priority = 'standard'
        else:
            l._priority = 'expensive'  # highest cost/sqft

    for l in locations:
        if not (l.size_sqft and l.monthly_cost):
            l._priority = None
```

`_priority` is a transient Python attribute set at render time — not stored on the model.

**Card sort order (replaces the current "units with items first" sort):**
1. `best` priority units (sorted by item count desc within tier)
2. `standard` priority units (sorted by item count desc)
3. `expensive` priority units (sorted by item count desc)
4. Unranked units (no cost data — sorted by item count desc)
5. Empty units last within each tier

---

### Unit Card Display Changes

**All users (admin + campus director):**
- Priority badge on card: `Best Value` (green), `Standard` (grey, no badge — just no label), `Expensive` (amber)
- Unit size label: e.g. `10×30` (derived from `size_sqft` display — store the raw string or re-derive from sqft)
- No dollar figures shown

**Super admin only (conditionally rendered with `{% if current_user.is_super_admin %}`):**
- `$X.XX/sqft` label on the card
- `$XXX/mo` label on the card

Both labels hidden entirely for non-super-admin users — no placeholder, no blurred value, just absent.

---

### Unit Modal Display Changes

**All users:**
- Priority badge (same as card)
- Size label

**Super admin only:**
- `$X.XX/sqft · $XXX/mo` line in the modal header, below the unit name
- These fields are editable inline by super admin (same autosave pattern as storage row): fetch-POST to `POST /admin/storage/<id>/edit` on change (this route already exists)

---

### Bulk Move (Consolidation Tool)

The unit modal gets a **"Move Items" toggle button** in the header, next to "Log Item Here".

**When toggled on:**
- Each item row in the unit modal gains a checkbox on the left
- A sticky footer appears at the bottom of the modal: "X items selected → Move to: [unit dropdown] [Move button]"
- The unit dropdown shows all active units except the current one, sorted by priority (best first)
- "Move" button is disabled until at least one item is checked and a destination unit is selected

**Move action:**
- `POST /admin/warehouse/bulk-move` — accepts `item_ids[]` (list) and `destination_unit_id`
- Updates `storage_location_id` on each item to the destination unit
- Clears `storage_row` on moved items (they'll need to be re-rowed in the new unit)
- Returns JSON `{success, moved_count}`
- On success: modal item list refreshes (re-fetches the unit partial), footer hides, toggle resets, flash: "X items moved to Unit 214"

**New route:**

| Method | Path | Function | Auth | Description |
|--------|------|----------|------|-------------|
| `POST` | `/admin/warehouse/bulk-move` | `admin_warehouse_bulk_move` | Admin | Move multiple items to a destination unit. Accepts `item_ids[]` + `destination_unit_id`. Clears `storage_row` on moved items. Returns JSON `{success, moved_count}`. |

**Edge cases:**
- If destination unit is full (`is_full=True`): warn but allow ("Unit 214 is marked full — move anyway?")
- If any item_id doesn't exist or belongs to a different unit than expected: skip silently, report count of actually moved items
- Empty selection: Move button disabled, POST blocked server-side with 400

---

### Settings Tab Changes (Super Admin)

The storage location edit form in `admin/settings.html` (the inline edit panel for each storage unit) gets two new fields:

- **Size** — text input, format hint `10x30`. Writes to `size_sqft` via parsing on save (same parse logic as import).
- **Monthly Rate** — number input, dollar amount. Writes to `monthly_cost`.

These fields are super admin only (same access as the rest of the storage settings section). They appear in the existing edit panel — no new page or route needed since `POST /admin/storage/<id>/edit` already accepts arbitrary fields and can be extended.

---

### Constraints

- Dollar figures (`monthly_cost`, `cost_per_sqft`) are **never** rendered for non-super-admin users anywhere — not in templates, not in JSON API responses used by the warehouse page
- The `admin_warehouse_seller_search` JSON response must not include cost fields
- `admin_warehouse_unit` partial must check `current_user.is_super_admin` before including any cost data
- The bulk move route clears `storage_row` on moved items — it does NOT clear `storage_location_id` on the source unit (that would be wrong; it writes the new destination)
- Existing `POST /admin/storage/<id>/edit` route is extended to accept `size_sqft` and `monthly_cost` — the route already exists, just add the new fields to its handler. Super admin only (already gated).

---

### Edge Cases

| Scenario | Behavior |
|----------|----------|
| Unit has `size_sqft` but no `monthly_cost` | Unranked — no priority badge, no cost display |
| Size string is malformed (e.g. `large`) | `size_sqft = None`, row still imports, no priority badge |
| All units have identical cost/sqft | All fall in "best" tier (len < 3 branch handles this) |
| Super admin edits monthly cost to 0 | Treat as null — 0 cost/sqft would distort rankings. Validate: must be > 0 or blank. |
| Moving items to a full unit | Confirmation dialog, allow if confirmed. `snapshot_capacity` not recalculated — admin re-marks full when ready. |
| Unit is cancelled (set inactive) after cost data entered | `is_active=False` units hidden from warehouse floor cards. Cost data preserved for history. |
