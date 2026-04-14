# Feature Spec: Pickup Location Improvements

## Goal

Two improvements to how sellers enter their pickup location:

1. **Off-campus apartment buildings** — sellers at one of 7 known UNC-area complexes should pick their building from a dropdown (just like on-campus dorms) and enter a unit number, rather than navigating Google Maps autocomplete. Reduces friction for the most common off-campus case.

2. **Structured access fields** — replace the optional freeform notes box with required, structured fields that give movers the operational info they actually need before arriving (access type, floor number), plus an optional catch-all note for anything else.

---

## UX Flow

### Location Type Selection (unchanged)
User picks one of three options:
- On-campus (UNC dorm)
- Off-campus apartment complex *(new option, replaces the single "off-campus" toggle)*
- Off-campus other address

---

### Branch A: On-Campus (UNC Dorm)

**Fields (same as today):**
- Dorm building (dropdown, grouped by area — existing list)
- Room number (text, required)

**New fields (added below):**
- Access type (radio, required) — see Access Fields section
- Floor number (number input, required)
- Additional notes (textarea, optional)

---

### Branch B: Off-Campus Apartment Complex *(new)*

Replaces the current single "off-campus" path for sellers at known buildings. Displayed when user selects the new "Off-campus apartment complex" option.

**Fields:**
- Building (dropdown, required):
  - Granville Towers
  - Lark Chapel Hill Apartments
  - The Warehouse
  - The Edition on Rosemary
  - Shortbread Lofts
  - Union Chapel Hill
  - Carolina Square
- Unit number (text, required) — label: "Unit / Apartment #", placeholder: "e.g. 4B, 312"

**New fields (added below):**
- Access type (radio, required)
- Floor number (number input, required)
- Additional notes (textarea, optional)

**Data storage:** `pickup_location_type = 'off_campus_complex'` (new enum value). Building name stored in `pickup_dorm` (reuses existing column — semantically "building" for this branch). Unit number stored in `pickup_room` (reuses existing column). `pickup_address`, `pickup_lat`, `pickup_lng` are `None`/null.

---

### Branch C: Off-Campus Other Address (existing, minor change)

User is not at one of the 7 known complexes.

**Fields (same as today):**
- Address (Google Maps autocomplete, required) → writes `pickup_address`, `pickup_lat`, `pickup_lng`

**New fields (added below):**
- Access type (radio, required)
- Floor number (number input, required)
- Additional notes (textarea, optional)

---

### Access Fields (shared across all three branches)

These appear below the branch-specific fields in all cases.

**Access type** (radio cards, required):

| Value | Label | Description shown |
|-------|-------|-------------------|
| `elevator` | Elevator access | Building has an elevator I can use |
| `stairs_only` | Stairs only | No elevator — movers will need to carry items up/down stairs |
| `ground_floor` | Ground floor | Item is on the ground floor — no stairs involved |

**Floor number** (integer input, required in all cases):
- Label: "What floor is your room/unit on?"
- Min: 1. Max: 30. Integer only.
- Helper text: "Enter 1 if you're on the ground floor."
- Always shown and always required (even for ground floor — confirms the mover's expectation).

**Additional notes** (textarea, optional):
- Label: "Anything else movers should know?"
- Placeholder: "e.g. building code is 1234#, long hallway from elevator, park in lot B, item is in a storage room"
- Max 500 chars.
- This replaces the current `pickup_note` field. Data maps to the same column.

---

### Admin Display

The seller profile panel in admin (pickup info section) should display:
- Location type (badge: On-Campus / Off-Campus Complex / Off-Campus Other)
- Building/dorm + room/unit
- Access type (plain text: "Elevator access", "Stairs only", "Ground floor")
- Floor number
- Notes (if set)

The mover shift view (`/crew/shift/<id>`) seller stop cards already pull from `user.pickup_display` property. This property must be updated to include access type and floor in its output.

---

## Model Changes

### New field on `User`:

```
pickup_access_type: String(20), nullable — 'elevator' | 'stairs_only' | 'ground_floor'
pickup_floor: Integer, nullable
```

### Modified enum values for `pickup_location_type`:

Current: `'on_campus' | 'off_campus'`
New: `'on_campus' | 'off_campus_complex' | 'off_campus_other'`

**Migration strategy:** Existing `'off_campus'` rows should be migrated to `'off_campus_other'` in the migration script (simple `UPDATE` statement). The old `'off_campus'` value will no longer be written by the app after this change, but the migration ensures no stale rows remain.

**`pickup_display` property** on `User` — update to include access type and floor in its formatted output. Affects: admin panel, mover shift view, any template reading `user.pickup_display`.

### Migration required: Yes

1. Add `pickup_access_type` (String 20, nullable) to `User`
2. Add `pickup_floor` (Integer, nullable) to `User`
3. Data migration: `UPDATE "user" SET pickup_location_type = 'off_campus_other' WHERE pickup_location_type = 'off_campus'`

---

## Routes Affected

No new routes needed. Changes are to existing form-handling routes:

| Route | Function | Change |
|-------|----------|--------|
| `POST /update_profile` | `update_profile` | Accept new fields: `pickup_access_type`, `pickup_floor`; accept `pickup_location_type = 'off_campus_complex'`; validate all required access fields |
| `POST /onboard` (location step) | `onboard` | Same field additions + validation. Session data must carry `pickup_access_type` and `pickup_floor`. |
| `GET /account_settings` | `account_settings` | Pass new field values to template for pre-population |
| `GET /dashboard` (pickup modal) | `dashboard` | Pass new field values to template for pre-population in the dashboard modal |

---

## Template Changes

### `onboard.html` — Location step

Replace current off-campus branch (single toggle → Google Maps) with three-way radio selection:
- On-campus dorm
- Off-campus apartment complex *(new)*
- Other address

Add Branch B UI (building dropdown + unit number field), shown when "off-campus apartment complex" is selected.

Add access fields section (access type radio cards + floor number input + optional notes textarea) shown at the bottom of the location step for all three branches. JS shows/hides this section after a branch is selected.

Remove the current freeform optional "notes" field — replaced by the structured access section + the new optional notes field at the bottom of that section.

### `account_settings.html` — Pickup Location card (Card 3)

Same three-way radio restructure. Pre-populate all new fields from `current_user`. Access fields section always visible once a branch is selected.

### `dashboard.html` — Pickup week & address modal

Same changes as account_settings location form. The modal's location sub-form must reflect the three-branch structure and include the access fields.

### `admin/seller_profile_panel` (or equivalent partial)

Update the Pickup Info section to display: location type badge, building + unit, access type, floor number, notes.

### Mover shift view (`crew/shift_view.html` or equivalent)

Seller stop cards — if currently showing `pickup_display`, no template change needed if `pickup_display` property is updated. Verify this and update the property rather than the template.

---

## Business Logic & Validation

### Backend validation in `update_profile` and `onboard`:

**All branches:**
- `pickup_access_type` required — reject if missing or not one of the three valid values
- `pickup_floor` required — must be integer 1–30

**Branch B (off-campus complex):**
- `pickup_dorm` (building) required — must be one of the 7 known values (validated server-side, not just client-side)
- `pickup_room` (unit number) required — non-empty string, max 20 chars
- `pickup_address`, `pickup_lat`, `pickup_lng` should be set to `None`

**Branch C (off-campus other):**
- `pickup_address` required (non-empty)
- `pickup_lat`, `pickup_lng` required (non-zero floats — use existing Google Maps validation)
- `pickup_dorm`, `pickup_room` should be set to `None`

**On-campus:**
- `pickup_dorm` required — must be in the existing dorms list (already validated)
- `pickup_room` required — non-empty, max 20 chars

### `has_pickup_location` property on `User`:

Update to require `pickup_access_type` and `pickup_floor` in addition to existing checks. A seller who set their location before this change will still show the setup strip chip until they update their location (acceptable — prompts the new required info).

Existing sellers with no `pickup_access_type` set: treat as incomplete location. Setup strip will show the chip. No back-fill needed.

---

## Edge Cases

**Existing sellers with `pickup_location_type = 'off_campus'`** — after migration, they become `'off_campus_other'`. Their `pickup_access_type` and `pickup_floor` will be null (new fields). `has_pickup_location` will return False for them, prompting re-entry. This is correct — we want this info.

**Guest session during onboarding** — `pickup_access_type` and `pickup_floor` must be stored in the onboarding session dict (same as other location fields) and saved in `onboard_guest_save`. Check this path explicitly.

**Floor 1 + "Stairs only"** — technically valid (e.g. a sunken unit below street grade). Don't reject this combination.

**Floor > 1 + "Ground floor"** — should be blocked client-side with a JS warning ("Ground floor is for floor 1 only — did you mean elevator or stairs?"), but not a hard server-side reject in case of legitimate edge cases (e.g. buildings built into a hill). Server logs a warning.

**Building dropdown vs. free text** — server-side, `pickup_dorm` for Branch B must be validated against the known list. Don't trust the client-only dropdown.

---

## Constraints

- Do not touch the Google Maps autocomplete JS for Branch C — it is working correctly.
- Do not change `pickup_dorm` or `pickup_room` column names — reuse them for the apartment complex branch.
- The `pickup_note` column is reused for the new optional notes field — do not rename or drop it.
- Existing on-campus dorm list and groupings are unchanged.
- Admin payout reconciliation (Spec #5) reads `pickup_display` — confirm the property update doesn't break that rendering.
- The `pickup_display` property change must handle all four states gracefully: `on_campus`, `off_campus_complex`, `off_campus_other`, and legacy `off_campus` (shouldn't exist post-migration, but defensive handling is cheap).
