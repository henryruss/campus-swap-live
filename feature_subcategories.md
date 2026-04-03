# Feature Spec: Category & Subcategory System

## Goal

Replace the current flat category structure with a two-level parent/subcategory
hierarchy. This improves item discoverability on the buyer side, gives sellers a
more guided listing experience, and sets up clean filtering as inventory grows
across campuses.

---

## Taxonomy (source of truth — seed this exactly)

| Parent Category | FA Icon | Subcategories |
|---|---|---|
| Furniture | fa-couch | Couch / Sofa, Futon, Armchair / Accent Chair, Desk, Desk Chair, Gaming Chair, Bookshelf / Shelving, Dresser, Coffee Table, Side Table, TV Stand / Media Console, Storage Ottoman, Other Furniture |
| Bedroom | fa-bed | Mattress, Headboard, Other Bedroom |
| Kitchen & Appliances | fa-blender | Mini Fridge, Microwave, Coffee Maker / Espresso Machine, Air Fryer, Blender, Toaster Oven, Knife Set, Instant Pot / Rice Cooker, Other Kitchen |
| Electronics | fa-tv | TV, Monitor, Laptop, Gaming Console, Speakers / Soundbar, Headphones, Keyboard / Mouse, Other Electronics |
| Climate & Comfort | fa-fan | Portable AC Unit, Space Heater, Tower Fan, Humidifier / Dehumidifier, Other Climate |
| Rugs | fa-rug | Area Rug |
| Bikes & Scooters | fa-bicycle | Bike, Electric Scooter |
| Other | fa-box-open | *(no subcategories — skip subcategory step)* |

**Categories that skip the subcategory step entirely:** Rugs, Other.
These go straight from top-level selection to the next onboarding step.
The item's `subcategory_id` is left null for these.

---

## Model Changes

### `InventoryCategory` — add `parent_id` and `icon`

```python
parent_id = db.Column(db.Integer, db.ForeignKey('inventory_category.id'), nullable=True)
icon = db.Column(db.String(64), nullable=True)  # e.g. 'fa-couch'

# Relationships
parent = db.relationship('InventoryCategory', remote_side=[id], backref='subcategories')
```

- `parent_id = NULL` → top-level category
- `parent_id = <id>` → subcategory belonging to that parent
- `icon` replaces `image_url` for top-level categories. Keep `image_url` column
  in place (don't drop it) to avoid a destructive migration — just stop using it
  for new categories.

### `InventoryItem` — add `subcategory_id`

```python
subcategory_id = db.Column(db.Integer, db.ForeignKey('inventory_category.id'), nullable=True)
subcategory = db.relationship('InventoryCategory', foreign_keys=[subcategory_id])
```

- `category_id` stays and continues to store the **parent** category id.
- `subcategory_id` stores the child. Nullable — existing items and items in
  Rugs/Other will have null here.
- Do NOT remove or rename `category_id`. All existing filter/query logic
  references it.

### Migration

```
flask db migrate -m "add subcategory support to categories and items"
flask db upgrade
```

After migrating, run a one-time seed script (see below) to populate the new
taxonomy. Do not drop old categories until old items have been manually
re-assigned by the operator (there are only 4 live items).

---

## Seed Script

Create `seed_categories.py` in the project root. Running it should be idempotent
(safe to run multiple times). It should:

1. Delete all existing `InventoryCategory` rows (after confirming no items depend
   on them, or nulling out `category_id` / `subcategory_id` on existing items
   first).
2. Insert the 8 parent categories with correct `icon` values and `parent_id = None`.
3. Insert all subcategories with `parent_id` pointing to the correct parent.
4. Print a summary of what was created.

**Operator note:** Before running the seed, manually update the 4 existing live
items in the admin panel to point to the correct new categories. Then run the
seed. This is a one-time manual step given the low item count.

---

## New Routes

| Method | Path | Function | Description |
|---|---|---|---|
| `GET` | `/api/subcategories/<parent_id>` | `api_subcategories` | Returns JSON list of subcategories for a given parent. Used by onboarding JS. |
| `POST` | `/admin/category/add-subcategory` | `admin_add_subcategory` | Admin: add a new subcategory under a parent. |
| `POST` | `/admin/category/edit-subcategory/<id>` | `admin_edit_subcategory` | Admin: rename a subcategory. |
| `POST` | `/admin/category/delete-subcategory/<id>` | `admin_delete_subcategory` | Admin: delete subcategory if no items reference it. |

The existing category routes (`/admin/category/add`, `/admin/category/edit/<id>`,
`/admin/category/bulk-update`, `/admin/category/delete/<id>`) continue to handle
**parent categories only** — do not modify their function signatures.

### `/api/subcategories/<parent_id>` response format

```json
{
  "subcategories": [
    { "id": 12, "name": "Couch / Sofa" },
    { "id": 13, "name": "Futon" },
    ...
    { "id": 24, "name": "Other Furniture" }
  ],
  "skip_subcategory": false
}
```

`skip_subcategory: true` when the parent has 0 subcategories (Rugs has 1 but
it's auto-selected; Other has 0). Logic: if `len(subcategories) == 0`, set
`skip_subcategory: true`. Rugs (Area Rug only) should also set
`skip_subcategory: true` and auto-select the single subcategory silently.

---

## UX Flow — Seller Onboarding (Step 1: Category)

This is the most important surface. It must feel polished.

### Step 1a — Top-level category grid (current behaviour, updated content)

- Display 8 cards in a responsive grid (3 across on desktop, 2 on mobile)
- Each card: FontAwesome icon (large, `--primary` green) + category name
- No item counts shown at this stage (counts are buyer-facing, not needed here)
- Selected card gets a highlighted border (`--primary`) and a checkmark badge
- Clicking a card triggers the subcategory reveal (Step 1b) via JS — no page reload

### Step 1b — Subcategory selection (new, inline reveal)

- After a top-level card is clicked, the subcategory row animates in below the
  grid (smooth CSS transition, ~200ms)
- Subcategories render as a **wrapping row of pill buttons** — text only, no icons
- Pills use `--bg-cream` background, `--primary` text, `--rule` border by default
- Selected pill: `--primary` background, white text
- The last pill in every list is always **"Other [Category Name]"** — this is the
  escape hatch so the step is never a dead end
- If `skip_subcategory` is true (Rugs, Other): subcategory row does not appear,
  flow proceeds immediately when top-level card is clicked
- A "Next" button below the pills becomes active once a subcategory is selected
  (or immediately for skip categories)
- Changing the top-level selection swaps the pill set via JS (re-fetch from
  `/api/subcategories/<parent_id>`) and clears the subcategory selection

### Hidden form fields

The onboarding form must submit both values:

```html
<input type="hidden" name="category_id" id="selected_category_id">
<input type="hidden" name="subcategory_id" id="selected_subcategory_id">
```

`subcategory_id` may be empty for Rugs and Other — that is valid.

### Validation (backend, in `onboard` route)

- `category_id` is required. Reject if missing or not a valid parent category id.
- `subcategory_id` is optional. If provided, verify it is a child of the
  submitted `category_id`. Reject if the relationship doesn't match.
- On save, write both `category_id` and `subcategory_id` to the `InventoryItem`.

---

## UX Flow — Add Item (`/add_item`)

The `add_item` page has its own category selector. Apply the same two-step
pattern here:

- Replace the current category `<select>` dropdown with the same card grid +
  pill pattern used in onboarding.
- Reuse the same JS logic (can be extracted to a shared partial or inline script).
- Same hidden fields: `category_id`, `subcategory_id`.
- Same backend validation rules.

---

## UX Flow — Edit Item (`/edit_item/<id>`)

- Show the current parent category pre-selected (highlighted card)
- Show the current subcategory pre-selected (highlighted pill)
- Allow changing both
- On save, update both `category_id` and `subcategory_id` on the item

---

## UX Flow — Inventory / Shop Page (`/inventory`)

The existing horizontal scrolling category card row stays as-is visually.
Two changes:

### 1. Update category cards to use new parent categories

- 8 cards instead of 5 (plus "View All")
- Use `icon` field instead of `image_url` for the FontAwesome icon
- Item count on each card = count of available items where
  `category_id = parent.id` (includes all subcategories under that parent)

### 2. Add subcategory pill filter row

- When a top-level category card is clicked (and it has subcategories), a second
  row of text pills appears below the category cards
- Pills list all subcategories for that parent, plus an "All [Category]" pill
  (selected by default)
- Clicking a subcategory pill filters the grid to items where
  `subcategory_id = pill.id`
- Clicking "View All" or a different top-level card hides the pill row
- This is Vanilla JS — the inventory grid re-renders via existing filter logic,
  extended to accept an optional `subcategory` query param
- URL should be bookmarkable: `/inventory?category=3&subcategory=12`

### Backend change to `/inventory` route

Extend the existing `inventory` function to accept `subcategory` as an optional
query param. When present, add `.filter(InventoryItem.subcategory_id == subcategory)`
to the query. When absent, filter by parent `category_id` only (existing behaviour).

---

## Admin Panel Changes

Keep the existing Category Management UI structure. Extend it to show subcategories.

### Category Management section (in `admin.html`)

**Parent categories table** — unchanged except:
- Add `icon` column (editable text input, same as current name/icon fields)
- Remove `image_url` column from the edit UI (keep the DB column, just stop
  showing it)

**Subcategory management — new section below existing table**

For each parent category, show a collapsible sub-table listing its subcategories:

```
▼ Furniture (12 subcategories)
   | NAME              | ITEMS | ACTIONS        |
   | Couch / Sofa      | 2     | Rename | Delete |
   | Futon             | 0     | Rename | Delete |
   ...
   [ + Add subcategory to Furniture ]
```

- Rename: inline text input, saves on blur or Enter
- Delete: only shown if `item count = 0`, triggers `POST /admin/category/delete-subcategory/<id>`
- Add: small inline form, `POST /admin/category/add-subcategory`

This does not need to be beautiful — functional and consistent with the existing
admin table styling is sufficient.

### Item approval queue (`admin_approve.html`)

- Show subcategory name alongside category name in the item row
- Add a subcategory dropdown to the approval form so admin can correct
  miscategorization at approval time (fetch subcategories for the item's parent
  via the existing JS API endpoint)

### Bulk edit / inventory table (`admin.html`)

- Add a "Subcategory" column to the inventory table (read-only display, not
  inline-editable — changing category on a live item is an edge case, handle
  via edit_item page)

---

## CSS Changes (`static/style.css`)

Add the following new component styles. Use existing CSS variables only.

```css
/* Subcategory pill row */
.subcategory-pills {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 16px;
  padding: 16px 0;
  border-top: 1px solid var(--rule);
  animation: fadeSlideIn 200ms ease;
}

.subcategory-pill {
  padding: 6px 16px;
  border-radius: 999px;
  border: 1px solid var(--rule);
  background: var(--bg-cream);
  color: var(--text-main);
  font-size: 14px;
  cursor: pointer;
  transition: all 150ms ease;
}

.subcategory-pill:hover {
  border-color: var(--primary);
  color: var(--primary);
}

.subcategory-pill.selected {
  background: var(--primary);
  color: var(--text-light);
  border-color: var(--primary);
}

@keyframes fadeSlideIn {
  from { opacity: 0; transform: translateY(-6px); }
  to   { opacity: 1; transform: translateY(0); }
}
```

---

## Constraints — Do Not Touch

- **`category_id` on `InventoryItem`** — do not rename or remove. All existing
  filter queries use it. New `subcategory_id` is additive only.
- **Existing category admin routes** (`/admin/category/add`, `/admin/category/edit/<id>`,
  `/admin/category/bulk-update`, `/admin/category/delete/<id>`) — do not change
  their signatures or behaviour. They continue to manage parent categories.
- **`count_in_stock` field on `InventoryCategory`** — this is manually managed
  via the admin "Essentials Stock Counts" UI. Leave that UI and field untouched.
  The buyer-facing category cards should derive counts from live item queries,
  not this field (that's already the correct pattern per the existing codebase).
- **Image upload logic** (`handleImageUpload`, `handleCoverPhotoSelection`) in
  `add_item.html` — do not touch. The category selector change is purely a UI
  swap of the category input section.
- **Stripe webhook handler** — no changes.
- **`_category_grid.html` partial** — update this to reflect new parent
  categories, but do not change the data contract it expects from the route.
  If the partial is too tightly coupled, inline the updated version into
  `inventory.html` rather than breaking the partial interface.
