# Spec #4 — Organizer Intake

## Goal

Give organizers a phone-optimized interface to receive items at the storage unit,
physically verify them against the expected manifest, record their exact storage
location, adjust condition if needed, and flag any problems. This is the last
quality checkpoint before an item is considered ready to sell. It also lays the
data foundation for future delivery drivers to retrieve items by exact location.

Two parallel additions:
1. A `StorageLocation` management system for admin (CRUD + truck assignment).
2. An organizer intake flow (shift-scoped checklist + item-ID search fallback).

---

## New Terminology (add to OPS_SYSTEM.md glossary)

| Term | Definition |
|------|------------|
| **StorageLocation** | A physical storage unit Campus Swap controls — has an address and internal row structure |
| **Intake** | The act of an organizer receiving an item, verifying it, and recording its exact storage location |
| **Intake record** | The `IntakeRecord` DB row created when an organizer completes intake on one item |
| **Planned unit** | The `StorageLocation` pre-assigned to a `ShiftPickup` by admin before the shift |
| **Actual unit** | The `StorageLocation` recorded on `InventoryItem` by the organizer at intake — the delivery source of truth |

---

## UX Flow

### A. Admin — Storage Location Management (`/admin/storage`)

**Creating a storage location:**

1. Super admin navigates to `/admin/storage`.
2. Sees a list of all storage locations — name, address, status badges (Active / Full / Inactive), item count, and a link to view items stored there.
3. Clicks "Add Storage Location." A form appears with: name (e.g. "Unit A"), street address, location note (gate code, landmark, unit number within a complex), and capacity note (free text, e.g. "fits ~40 large items").
4. Saves. Location is created with `is_active=True`, `is_full=False`.
5. Admin can edit any location inline — toggle `is_active` and `is_full`, update address or notes.
6. Admin cannot delete a location that has items tagged to it. Edit only.

**Assigning trucks to storage locations (pre-shift):**

1. On the existing `/admin/crew/shift/<shift_id>/ops` page, each truck card gains a "Destination Unit" selector — a dropdown of active, non-full `StorageLocation` records.
2. Admin selects a unit per truck before the shift begins. This writes `ShiftPickup.storage_location_id` for all pickups on that truck.
3. If admin needs to reassign mid-shift (unit filled unexpectedly), they return to the ops page and change the dropdown. This updates the `ShiftPickup` records for any *pending* stops on that truck. Already-completed stops retain their original assignment as the audit record.
4. If no unit is assigned to a truck, intake for those stops is still possible — the organizer must manually select the unit during intake. The organizer view will show a warning: "No unit pre-assigned for Truck N."

**Marking a unit full:**

Admin toggles `is_full=True` on the storage location detail. This unit no longer appears in the truck assignment dropdown for future shifts. Items already tagged to it are unaffected.

---

### B. Organizer — Shift-Scoped Intake (`/crew/intake/<shift_id>`)

This is a phone-first page. The organizer opens it at the start of their shift and works through it as trucks arrive.

**Page structure:**

- Header: shift label (e.g. "Tuesday AM"), a live count "X of Y items received," and a search bar (see fallback flow below).
- Below: trucks grouped as collapsible sections. Each truck section shows:
  - Truck number and assigned storage unit name (or "No unit assigned" warning in amber).
  - List of expected items — one card per `InventoryItem` for every `ShiftPickup` on that truck.
  - Each item card shows: item ID badge, description, seller name, current condition (quality), and status chip (Pending / Received / Flagged).

**Receiving an item (primary flow):**

1. A truck arrives and starts unloading. The organizer opens that truck's section.
2. Organizer taps an item card. A bottom-sheet modal slides up (vanilla JS) with the intake form for that item:
   - **Storage unit** — pre-populated from the truck's planned unit, but editable dropdown (all active units). Required.
   - **Row** — short free-text field (e.g. "Row 1", "Row B"). Optional for now.
   - **Storage note** — free text for anything unusual (e.g. "behind the couch stack"). Optional.
   - **Condition** — quality selector (1–5 scale, labelled: 1=Poor, 2=Fair, 3=Good, 4=Very Good, 5=Like New). Pre-populated with the item's current `quality` value. Organizer adjusts down if the item arrived worse than listed.
   - **Flag issue** — checkbox. If checked, reveals a text field for the issue description (e.g. "item not on truck", "damaged in transit", "wrong item", "extra unlisted item"). Required if box is checked.
   - **Confirm** button.
3. Organizer taps Confirm. The system:
   - Sets `InventoryItem.arrived_at_store_at` = now (if not already set).
   - Sets `InventoryItem.storage_location_id`, `storage_row`, `storage_note`.
   - Updates `InventoryItem.quality` if organizer changed it.
   - Creates an `IntakeRecord` (see model section).
   - If a flag was raised: creates an `IntakeFlag` record. Item card turns amber with a flag icon.
   - If no flag: item card turns green with a checkmark.
4. The live count increments. The organizer moves to the next item.

**Editing a completed intake:**

If the organizer made a mistake (wrong unit, wrong row), they can tap the green item card again to reopen the modal. All fields are pre-populated with the saved values. They edit and re-confirm. A new `IntakeRecord` is created (history is preserved — never overwrite, always append).

**Edge case — item on truck but not on manifest:**

The organizer notices a physical item that has no card in the list. They use the search bar (see below) to look it up by ID. If found, they complete intake normally. If not found in the system at all, they flag it using a "Log Unknown Item" form that creates an `IntakeFlag` with type `unknown_item` and a free-text description. No `InventoryItem` record is created — that's an admin problem to resolve.

---

### C. Organizer — Item Search Fallback (`/crew/intake/search`)

Accessible from the search bar on any intake page and as a standalone route.

1. Organizer types an item ID (or partial seller name as a secondary lookup).
2. Results appear immediately on submit — item ID, description, seller name, current intake status.
3. Tapping a result opens the same bottom-sheet intake modal described above. No shift-scoping — organizer can intake any item they can find.
4. This route is only accessible to approved workers with organizer role (`worker_role` in `['organizer', 'both']`).

---

### D. Admin — Intake Overview (additions to existing ops page)

On `/admin/crew/shift/<shift_id>/ops`, below the existing mover assignment panel, add an **Intake Summary** section:

- Per-truck: "X of Y items received" progress bar, list of flagged items with flag descriptions.
- A "View Full Intake" link → `/admin/crew/shift/<shift_id>/intake` — full read-only table of all intake records for the shift: item ID, description, seller, received at, unit, row, organizer who logged it, condition before/after, flags.
- Admins can resolve flags from this view — mark as resolved with a note. Resolved flags are visually distinguished but not deleted.

---

## New Routes

| Method | Path | Function | Description |
|--------|------|----------|-------------|
| `GET` | `/admin/storage` | `admin_storage_index` | List all storage locations. Super admin only. |
| `POST` | `/admin/storage/create` | `admin_storage_create` | Create a new storage location. Super admin only. |
| `POST` | `/admin/storage/<loc_id>/edit` | `admin_storage_edit` | Edit name, address, notes, is_active, is_full. Super admin only. |
| `GET` | `/admin/storage/<loc_id>` | `admin_storage_detail` | View all items currently tagged to this location. Admin. |
| `POST` | `/admin/crew/shift/<shift_id>/truck/<truck_number>/assign_unit` | `admin_shift_assign_unit` | Set storage_location_id on all pending ShiftPickups for this truck on this shift. Admin. |
| `GET` | `/crew/intake/<shift_id>` | `crew_intake_shift` | Organizer shift-scoped intake page. Requires organizer role. |
| `POST` | `/crew/intake/<shift_id>/item/<item_id>` | `crew_intake_submit` | Submit intake for one item. Creates IntakeRecord. |
| `GET` | `/crew/intake/search` | `crew_intake_search` | Search items by ID or seller name. Returns rendered results partial. |
| `GET` | `/admin/crew/shift/<shift_id>/intake` | `admin_shift_intake_log` | Full read-only intake log for a shift. Admin. |
| `POST` | `/admin/intake/flag/<flag_id>/resolve` | `admin_intake_flag_resolve` | Mark an IntakeFlag as resolved with a note. Admin. |

---

## Model Changes

### New: `StorageLocation`

```
id
name              (String, e.g. "Unit A", "Chapel Hill #3") — required, unique
address           (String) — street address for navigation
location_note     (Text, nullable) — gate code, landmark, directions within a complex
capacity_note     (Text, nullable) — free text, e.g. "fits ~40 large items"
is_active         (Boolean, default True) — False = retired, excluded from all dropdowns
is_full           (Boolean, default False) — True = excluded from truck assignment dropdown
created_at        (DateTime, default utcnow)
created_by_id     (FK → User, nullable)

Relationships:
  items → [InventoryItem] (backref: storage_location)
  shift_pickups → [ShiftPickup] (backref: planned_storage_location)
  intake_records → [IntakeRecord]
```

### New: `IntakeRecord`

```
id
item_id           (FK → InventoryItem) — required
shift_id          (FK → Shift) — required (which shift this intake happened during)
organizer_id      (FK → User) — worker who logged it
storage_location_id (FK → StorageLocation) — where item was physically placed
storage_row       (String, nullable) — e.g. "Row 1", "Row B"
storage_note      (Text, nullable) — free text for anything unusual
quality_before    (Integer) — quality value on the item at time of intake (snapshot)
quality_after     (Integer) — quality value recorded by organizer (may equal quality_before)
created_at        (DateTime, default utcnow)

Notes:
  - Never overwritten. If organizer re-submits, a new record is appended.
  - Most recent record per item_id is the canonical intake state.
  - quality_before snapshot enables audit of organizer condition changes.
```

### New: `IntakeFlag`

```
id
item_id           (FK → InventoryItem, nullable) — null for unknown_item flags
shift_id          (FK → Shift)
intake_record_id  (FK → IntakeRecord, nullable) — null for unknown_item flags
organizer_id      (FK → User)
flag_type         (String) — 'missing' | 'damaged' | 'wrong_item' | 'extra_item' | 'unknown_item' | 'other'
description       (Text) — required — organizer's note
resolved          (Boolean, default False)
resolved_at       (DateTime, nullable)
resolved_by_id    (FK → User, nullable)
resolution_note   (Text, nullable)
created_at        (DateTime, default utcnow)

Relationships:
  item → InventoryItem (backref: intake_flags)
  shift → Shift
  intake_record → IntakeRecord
  organizer → User
  resolved_by → User
```

### Modified: `InventoryItem`

Add three new fields:

```
storage_location_id   (FK → StorageLocation, nullable) — set at intake, delivery source of truth
storage_row           (String, nullable) — e.g. "Row 1", "Row B"
storage_note          (Text, nullable) — e.g. "behind the couch stack"
```

These fields are written by the organizer during intake and read by delivery drivers in the future. They represent where the item *actually* is, not where it was planned to go.

### Modified: `ShiftPickup`

Add one new field:

```
storage_location_id   (FK → StorageLocation, nullable) — planned destination, set by admin pre-shift
```

This is the *intended* unit for this truck's items. Used as the pre-populated default in the intake form. Does not change when the organizer selects a different unit — the divergence is intentional audit data.

**Migration note:** Two migrations needed — one for `StorageLocation` (must come first, since other tables FK into it), one for the fields on `InventoryItem` and `ShiftPickup` plus the new `IntakeRecord` and `IntakeFlag` tables.

---

## Template Changes

### New templates

**`admin/storage_index.html`**
- Extends `layout.html`.
- List of all `StorageLocation` records, sorted by `is_active` desc, then name.
- Each row: name, address, item count (live query), status badges (Active/Full/Inactive), Edit button.
- Inline edit form (vanilla JS toggle) per row: name, address, location_note, capacity_note, is_active checkbox, is_full checkbox. Submit → POST `/admin/storage/<id>/edit`.
- "Add Storage Location" form at top. Submit → POST `/admin/storage/create`.
- Super admin only — show 403 flash and redirect if `not current_user.is_super_admin`.

**`admin/storage_detail.html`**
- Extends `layout.html`.
- Header: location name, address, notes, status badges, item count.
- Table of all `InventoryItem` records with `storage_location_id` = this location.
- Columns: item ID, description, seller name, storage row, storage note, item status, intake date.
- Useful for admin to audit what's in a given unit and plan consolidation later.

**`admin/shift_intake_log.html`**
- Extends `layout.html`.
- Read-only table of all `IntakeRecord` rows for the shift, grouped by truck.
- Columns: item ID, description, seller, received at, unit, row, organizer, condition before → after (show change in amber if different).
- Flagged items section: flag type badge, description, organizer, created at, resolved status. Inline resolve form (POST `/admin/intake/flag/<id>/resolve`) with resolution note textarea.

**`crew/intake.html`**
- Extends `layout.html`.
- Phone-optimized (max-width ~480px, large tap targets).
- Header: shift label, live "X of Y items received" counter.
- Search bar at top → GET `/crew/intake/search?q=<query>` — submits on enter, results replace a `#search-results` div via fetch (vanilla JS).
- Truck sections as `<details>` elements (native collapsible, no JS required). Each open by default.
- Inside each truck section: planned unit name or amber warning if none assigned.
- Item cards: item ID badge, description, seller name, condition stars, status chip.
  - Pending: white card, default border.
  - Received: light green background (`#dcfce7`), checkmark icon.
  - Flagged: amber background, flag icon.
- Tapping any card opens the intake modal (see below).

**`crew/_intake_modal.html`** (partial, injected into `crew/intake.html`)
- Bottom-sheet modal (fixed position, slides up on tap, vanilla JS).
- Form fields: storage unit dropdown, row text input, storage note textarea, condition selector (1–5 radio buttons with labels), flag checkbox + conditional flag description textarea.
- Confirm button → POST `/crew/intake/<shift_id>/item/<item_id>`.
- Cancel link closes the modal without submitting.
- On successful POST: server redirects back to `/crew/intake/<shift_id>` — page reloads, updated card states are rendered server-side.

**`crew/intake_search_results.html`** (partial, no layout — rendered into `#search-results` div)
- List of matching items: item ID, description, seller name, current intake status badge.
- Each result is a button that opens the intake modal for that item.
- If no results: "No items found for '#51'" message.

### Modified templates

**`admin/shift_ops.html`**
- Add "Destination Unit" dropdown per truck card (above the mover list).
- Dropdown options: active, non-full `StorageLocation` records + "— Not assigned —" option.
- Submit → POST `/admin/crew/shift/<shift_id>/truck/<truck_number>/assign_unit`.
- If unit is assigned, show name in green chip. If not assigned, show amber "No unit assigned" chip.
- Below existing mover assignment panel: add "Intake Summary" section.
  - Per-truck: progress bar "X of Y items received."
  - List of open (unresolved) flags for this shift, with description and item ID.
  - "View Full Intake Log →" link to `/admin/crew/shift/<shift_id>/intake`.

**`crew/dashboard.html`**
- On the today's shift banner (for organizer-role workers): add "Open Intake →" button linking to `/crew/intake/<shift_id>` when a shift is in progress (`ShiftRun.status = 'in_progress'`).
- Show the same button for past shifts that have unresolved flags (amber, "Review Flags →").

---

## Business Logic

### Who can access intake

Only approved workers with `worker_role` in `['organizer', 'both']`. Use the existing `require_crew()` pattern plus a role check. Return 403 if a mover (role = 'driver') tries to access intake routes. Admins can access all `/admin/` intake routes regardless of worker role.

### Intake and item status

Intake does **not** change `InventoryItem.status`. Status is managed by the existing admin approval workflow. Intake writes operational timestamps and location fields only. The status lifecycle remains:

```
pending_valuation → approved → available → sold
```

`arrived_at_store_at` is set by intake. It is a milestone, not a status transition.

### Quality changes at intake

If the organizer sets a different `quality` value than what's on the item:
- `InventoryItem.quality` is updated to the organizer's value.
- `IntakeRecord.quality_before` captures the old value.
- `IntakeRecord.quality_after` captures the new value.
- If `quality_after < quality_before`, and the item's `price` was set by admin based on the original quality, no automatic price change occurs. This is flagged implicitly via the `IntakeRecord` — admin can see condition changes in the intake log and adjust price manually if needed. Do not add price auto-adjustment logic in this spec.

### Idempotency — re-intake

If `arrived_at_store_at` is already set on an item and the organizer re-submits intake:
- Do **not** overwrite `arrived_at_store_at`. Timestamp of first receipt is preserved.
- Do update `storage_location_id`, `storage_row`, `storage_note`, and `quality` with the new values.
- Always append a new `IntakeRecord` — never update the old one.

### Planned vs. actual unit divergence

No validation error if the organizer selects a different unit than the planned one. The divergence is intentional — it's the audit trail. Admin can see it on the intake log: planned unit (from `ShiftPickup.storage_location_id`) vs. actual unit (from `IntakeRecord.storage_location_id`). No automated alert is required in this spec.

### Truck unit assignment — scope of update

When admin POSTs to `/admin/crew/shift/<shift_id>/truck/<truck_number>/assign_unit`:
- Only update `ShiftPickup.storage_location_id` for stops where `status = 'pending'` on that truck.
- Do not update completed stops. Their `ShiftPickup.storage_location_id` value at time of completion is the audit record of the planned destination.

### Unknown items (no DB record)

If an organizer uses the search and finds no matching item, they can submit a free-text "Log Unknown Item" form. This creates an `IntakeFlag` with `flag_type='unknown_item'`, `item_id=NULL`, and the organizer's description. Admin must resolve it — either by creating the item manually in the system or determining it was a mistake.

### Full storage units

`is_full=True` on a `StorageLocation` removes it from the truck assignment dropdown on the ops page. It does **not** prevent an organizer from selecting it in the intake form. Organizers work with physical reality — if items are going into a unit the system thinks is full, that should be recordable. Admin should update `is_full` to reflect reality.

### Item count per unit

`admin_storage_detail` computes item count as a live query:
```python
count = InventoryItem.query.filter_by(storage_location_id=loc.id).count()
```
No denormalized counter field. This is correct for now — the query is trivial and avoids sync bugs.

### Shift access for intake

Organizers can access the intake page for:
- Any shift where they have a `ShiftAssignment` with `role_on_shift='organizer'`.
- Any shift that is today or in the past (same time-awareness logic as `crew_shift_view`).

Organizers cannot access intake for future shifts. The route should return a flash error and redirect to `/crew` if the shift is in the future.

---

## Constraints — Do Not Touch

- `InventoryItem.status` lifecycle is managed by the existing admin approval flow. Intake does not change status.
- The Stripe webhook remains the sole source of truth for payment state. Do not add any payment logic here.
- `ShiftPickup.status` (pending/completed/issue) is managed by movers via `crew_shift_stop_update`. Intake does not write to this field.
- `picked_up_at` on `InventoryItem` is written by the mover flow (Spec #3) when a stop is marked completed. Do not write it in the intake flow.
- The existing admin panel routes (`/admin`, `/admin/approve`, etc.) are not touched.
- `require_crew()` helper function — use as-is, add role check on top, do not modify the helper itself.
- All CSS uses variables from `static/style.css`. No hardcoded colors. Light green receipts use `#dcfce7` (same as shift history cards established in Spec #3).

---

## Open Items (Deferred to Later Specs)

- **Delivery driver retrieval** — future spec will read `InventoryItem.storage_location_id + storage_row + storage_note` to generate a retrieval address. No changes needed here; the fields are being laid correctly.
- **Category consolidation** — admin bulk-reassigning items to a different storage unit is a future admin workflow, not part of intake.
- **Capacity-aware route optimization** — Spec #6 can read `StorageLocation.is_full` and `is_active` when planning which trucks go where. No optimizer changes in this spec.
- **Automatic price adjustment on condition downgrade** — intentionally deferred. Admin reviews intake log manually.
- **`storage_row` as a structured field** — currently free text. Once physical layout is finalized, this can become a managed enum or a row selector on the `StorageLocation` model. Free text is the right call for now.
