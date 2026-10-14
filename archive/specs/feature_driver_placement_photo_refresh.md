# Feature Spec: Driver Item Placement + Inventory Photo Refresh

Two related features built together because they share the same surfaces (driver shift view, admin items table) and both need to happen during the same physical inventory audit session.

---

## Part 1: Driver Item Placement Flow

### Goal

After completing all stops on a shift, drivers must assign every collected item to a storage unit and zone before they can end their shift. Items that were not actually picked up (partial handoffs, no-shows) can be marked "Not picked up" instead, which exempts them from the zone requirement. End Shift is blocked until every item is in one of these two states.

This replaces the organizer intake flow for storage location assignment. Drivers are the ones physically placing items in the unit — they should be the ones recording where they went.

---

### Context: What Already Exists

- `/crew/shift/<shift_id>` — phone-optimized driver shift view. Shows stops in `stop_order`. Each stop can be marked completed or flagged with an issue type.
- `ShiftRun` — created when driver taps Start Shift. `ended_at` set when driver taps End Shift.
- `InventoryItem.storage_location_id`, `storage_row`, `storage_note` — already exist on the model.
- `ShiftPickup.storage_location_id` — the *planned* destination unit written by admin. Used as the pre-fill default for the unit dropdown.
- `InventoryItem.picked_up_at` — set when a stop is marked completed.

---

### UX Flow

#### Step 1 — Complete All Stops (existing behavior, unchanged)

Driver works through stops as today. Each stop is marked completed or flagged with an issue type. No changes to this step.

#### Step 2 — Place Items (new step, appears after all stops are done)

When all stops have a non-pending status (`completed` or `issue`), the shift view transitions to a "Place Items" step. This replaces the current End Shift button with a placement checklist.

**Page state:** The stops list collapses or scrolls out of focus. A new section appears: "Place your items" with a subtitle like "Mark where you put each item, or flag it as not picked up."

**Item list:** One row per `InventoryItem` belonging to sellers on this shift whose stop was marked `completed`. Items from `issue`-flagged stops are also included (driver may have still collected some items despite a partial issue).

Each item row shows:
- Item ID badge
- Item title (description)
- Seller name
- Status chip: `Placed` (green) | `Not picked up` (gray) | `Needs location` (amber, default)
- "Assign" button (or "Edit" if already placed)

#### Step 3 — Assign Location Modal

Tapping "Assign" on an item opens a bottom-sheet modal (consistent with existing intake modal style):

1. **Storage unit dropdown** — pre-filled from the stop's `ShiftPickup.storage_location_id` (the admin-planned unit for this truck). Driver can change it if they ended up using a different unit. Shows only active, non-full `StorageLocation` records.
2. **Zone diagram** — 6 clickable zones:
   ```
   BACK  [ Back Left  ] | [ Back Right  ]
         [ Mid Left   ] | [ Mid Right   ]
   FRONT [ Front Left ] | [ Front Right ]
              ← walkway →
   ```
   Tap to select. Tap again to deselect.
3. **"Not picked up" button** — below the diagram. Tapping this marks the item as not collected (sets `placement_status = 'not_picked_up'` — see model changes). Closes modal immediately.
4. **Save button** — requires a unit and a zone. On save: writes to `InventoryItem.storage_location_id`, `storage_row`. Item row updates to green "Placed" chip. Modal closes.

**Re-entry:** If driver closes the app mid-placement and returns, previously saved placements persist. Their rows show "Placed" or "Not picked up" on load. Driver only needs to handle remaining "Needs location" rows.

#### Step 4 — End Shift Unlocks

"End Shift" button appears (and is enabled) only when every item in the list is either `Placed` or `Not picked up`. No items in `Needs location` state remain.

Tapping End Shift sets `ShiftAssignment.completed_at` and `ShiftRun.ended_at` as today.

---

### New Routes

| Method | Path | Function | Description |
|--------|------|----------|-------------|
| `GET` | `/crew/shift/<shift_id>/placement` | `crew_shift_placement` | Returns HTML partial: item placement list for this shift. Called via fetch after all stops done. |
| `POST` | `/crew/item/<item_id>/place` | `crew_item_place` | Write storage_location_id + storage_row to item. Returns JSON. |
| `POST` | `/crew/item/<item_id>/not_picked_up` | `crew_item_not_picked_up` | Set placement_status = 'not_picked_up'. Returns JSON. |

The existing `POST /crew/shift/<shift_id>/complete` (End Shift) route gains a guard: checks that all items on completed stops have `placement_status IN ('placed', 'not_picked_up')`. Returns 400 with an error message if not.

---

### Model Changes

#### New field: `InventoryItem.placement_status`

```
String, nullable, default None
Values: None | 'placed' | 'not_picked_up'
```

- `None` — default; item hasn't been through the placement step yet
- `'placed'` — driver confirmed storage unit + zone
- `'not_picked_up'` — driver marked as not collected

This field is set by the driver placement flow. It is separate from `picked_up_at` (which tracks whether the stop was completed). An item can have `picked_up_at` set (stop marked complete) but `placement_status = 'not_picked_up'` (partial handoff — seller only gave some items).

**Migration required:** `flask db migrate -m "add_placement_status_to_inventory_item"`

#### `InventoryItem.storage_row` (existing field, repurposed)

As described in the Storage Audit spec: no column type change, but application layer enforces the 6-value enum on all writes from this flow.

---

### Template Changes

#### Modified: `crew/shift.html`

- After all stops are non-pending, show the "Place Items" section instead of the End Shift button
- "Place Items" section fetches `/crew/shift/<shift_id>/placement` partial into a `<div id="placement-list">`
- End Shift button rendered disabled with a note ("Assign a location to all items first") until placement is complete
- Once all items are placed/marked, End Shift button becomes active
- JS tracks placement completion client-side (count of unresolved rows) and toggles button state; server also enforces via guard on the complete route

#### New: `crew/shift_placement_partial.html`

- No layout wrapper — injected into shift.html
- List of item rows with `data-item-id`, `data-placement-status` attributes
- Each row: ID badge, title, seller name, status chip, Assign/Edit button
- Zone diagram modal (bottom-sheet, same CSS pattern as intake modal)
- Unit dropdown + zone SVG/grid + "Not picked up" button + Save button
- All data via `data-*` attributes, no inline tojson
- JS handles modal open/close, zone selection, fetch POSTs, row status update on success

---

### Business Logic

#### `crew_shift_placement`
- Auth: `require_crew()` — worker must be assigned to this shift as driver
- Returns all `InventoryItem` records where `seller_id` is in the shift's `ShiftPickup` sellers AND the stop status is `completed` or `issue`
- Items pre-loaded with current `placement_status`, `storage_location_id`, `storage_row`
- Storage locations passed: active, non-full only (for dropdown)
- Default unit: from `ShiftPickup.storage_location_id` for this driver's truck number

#### `crew_item_place`
- Auth: `require_crew()` — worker must be assigned to the shift that collected this item (via `ShiftPickup`)
- Validates `storage_location_id` exists and is active
- Validates `storage_row` is one of the 6 enum values
- Writes `InventoryItem.storage_location_id`, `storage_row`, `placement_status = 'placed'`
- Does NOT set `arrived_at_store_at` — that field belongs to the intake flow
- Returns JSON `{success: true}`

#### `crew_item_not_picked_up`
- Auth: same as above
- Sets `InventoryItem.placement_status = 'not_picked_up'`
- Clears `storage_location_id` and `storage_row` if they were previously set by this flow (don't clear if set by admin/audit tool — check: only clear if `arrived_at_store_at` is NULL, meaning intake never confirmed it)
- Returns JSON `{success: true}`

#### End Shift guard (existing `crew_shift_complete` route, modified)
- Query: any `InventoryItem` on this shift's completed stops where `placement_status IS NULL`
- If any found: return 400, `{error: "X items still need a location assigned"}`
- If all placed or not_picked_up: proceed with existing completion logic (set `completed_at`, `ended_at`)

---

### Constraints — Do Not Touch

- Existing stop-level completion flow — no changes to how stops are marked complete/issue
- `ShiftRun` creation logic (Start Shift) — unchanged
- `picked_up_at` field — not written by this flow
- `arrived_at_store_at` — not written by this flow
- Organizer intake page and routes — left in place (separate deprecation task)
- `ShiftPickup.storage_location_id` — read-only from this flow (used as default, not written)
- QC (quick capture) items on this shift — should also appear in the placement list if their stop was completed. They already have `storage_location_id` on the model. Apply the same placement logic.

---

### Checklist (for Claude Code verification)

- [ ] After all stops are non-pending, placement section appears on shift view
- [ ] Placement list shows only items from completed/issue stops (not pending stops)
- [ ] Items from partial handoff stops appear (driver can mark individual items as not picked up)
- [ ] Zone diagram: tap selects zone; tap again deselects
- [ ] Unit dropdown pre-fills from the truck's planned unit
- [ ] Driver can change the unit in the modal
- [ ] Save writes `storage_location_id` and `storage_row` to item, sets `placement_status = 'placed'`
- [ ] "Not picked up" sets `placement_status = 'not_picked_up'`, closes modal
- [ ] Item row status chip updates after save without page reload
- [ ] End Shift button is disabled while any item is in "Needs location" state
- [ ] End Shift button becomes active when all items are placed or not_picked_up
- [ ] Attempting End Shift via direct POST with unplaced items returns 400
- [ ] Re-entering the shift view after partial placement shows correct per-item state
- [ ] QC items on the shift appear in the placement list

---

---

## Part 2: Inventory Photo Refresh

### Goal

During a physical storage audit, a campus director or admin may find items with bad or missing photos. This feature allows them to:

1. Attach a new replacement photo to any existing item (fully replaces the current `photo_url`)
2. Flag the item as having a crew-taken photo that needs AI background replacement later
3. Filter the admin items table by this flag to batch-process them later

This is the "capture now, clean up later" step. AI background replacement and auto-pricing are separate features — this spec only ensures the flag and photo exist when that work begins.

---

### UX Flow

#### Entry Point 1 — Storage Audit Tool

On the expanded item card in `/admin/storage/audit`, below the zone diagram, add a **"Replace Photo"** section:

- If the item has a photo: small thumbnail of current photo + "Replace" button
- If no photo: "Add Photo" button
- Tapping opens a native file picker (`<input type="file" accept="image/*" capture="environment">`) — this triggers the camera on mobile or file browser on desktop
- After selecting a photo: preview appears inline, "Save Photo" button appears
- Saving: POST to `/admin/item/<id>/replace_photo` — replaces `photo_url`, sets `needs_photo_refresh = True`, deletes old photo file from disk
- Confirmation: thumbnail updates inline, small green "Photo saved" badge

#### Entry Point 2 — Admin Items Table

On each item row in `/admin/items`, the Edit button already exists. No changes needed there — the existing edit flow can handle photo replacement. The new thing here is the **filter**.

Add a "Needs photo refresh" checkbox filter to the existing filter bar on `/admin/items`. When checked, filters to items where `needs_photo_refresh = True`. This is how you find all items photographed during the audit for batch background replacement later.

---

### New Routes

| Method | Path | Function | Description |
|--------|------|----------|-------------|
| `POST` | `/admin/item/<id>/replace_photo` | `admin_item_replace_photo` | Replace `photo_url`, set `needs_photo_refresh = True`. Admin + CD access. |

---

### Model Changes

#### New field: `InventoryItem.needs_photo_refresh`

```
Boolean, default False, server_default='0'
```

Set to `True` when a crew member replaces a photo via this tool. Cleared manually by admin (or by a future AI processing step) once the background has been replaced. Not set by the normal seller upload flow — only by this tool.

**Migration required:** `flask db migrate -m "add_needs_photo_refresh_to_inventory_item"`

---

### Template Changes

#### Modified: `admin/storage_audit_results.html`

- Add "Replace Photo" section to the expanded card (below zone diagram)
- Current photo thumbnail (or "No photo" placeholder)
- File input (`accept="image/*" capture="environment"`) hidden behind a styled button
- Preview div that shows selected image before upload
- "Save Photo" button: triggers fetch POST to `/admin/item/<id>/replace_photo` with `FormData`
- On success: thumbnail updates, green badge appears, `needs_photo_refresh` data attribute on card updates

#### Modified: `admin/items.html`

- Add "Needs photo refresh" checkbox to the filter bar
- Submits as `?needs_refresh=1` query param
- Backend: `admin_items` route adds `InventoryItem.needs_photo_refresh == True` filter when param present

---

### Business Logic

#### `admin_item_replace_photo`
- Auth: `_has_ops_access()` — admins and campus directors
- Validates file upload via existing `validate_file_upload()` helper
- Saves new photo to `/var/data/` (Render) using existing photo storage pattern
- Deletes old `photo_url` file from disk if it exists and is not a placeholder/CDN URL (check: path starts with `/var/data/` or `static/uploads/`)
- Updates `InventoryItem.photo_url` to new filename
- Sets `InventoryItem.needs_photo_refresh = True`
- Does NOT clear `gallery_photos` (ItemPhoto records) — only replaces the cover `photo_url`
- Returns JSON `{success: true, photo_url: <new_url>}`

#### `admin_items` (modified)
- If `?needs_refresh=1` present: add `InventoryItem.needs_photo_refresh == True` to filter chain
- Additive with existing filters (can combine with category, seller, title, ID filters)

---

### Constraints — Do Not Touch

- Seller-facing photo upload flow (onboarding wizard, item edit) — unchanged, does not set `needs_photo_refresh`
- `gallery_photos` / `ItemPhoto` records — not modified by this flow
- QC item photo replacement — QC items can also get `needs_photo_refresh = True` via this tool (no special casing needed)
- Existing Edit item flow — unchanged

---

### Checklist (for Claude Code verification)

- [ ] "Replace Photo" / "Add Photo" section appears on expanded audit card
- [ ] File picker opens on tap; shows preview before saving
- [ ] Saving replaces `photo_url` on the item in DB
- [ ] Old photo file deleted from disk on replacement (if local path)
- [ ] `needs_photo_refresh = True` set after replacement
- [ ] Thumbnail updates inline after save, no page reload
- [ ] `/admin/items?needs_refresh=1` returns only items with `needs_photo_refresh = True`
- [ ] `needs_photo_refresh` filter combines correctly with other filters
- [ ] Campus director can replace photos (not just admins)
- [ ] Non-admin, non-CD users cannot POST to `/admin/item/<id>/replace_photo` (403)
