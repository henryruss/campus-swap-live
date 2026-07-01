# Feature Spec: Shop Edit Mode (Super Admin Inline Editing)

## Goal

When browsing `/item/<id>` as a super admin, a persistent "Edit Mode" toggle reveals a slide-out panel that allows editing all key listing fields without leaving the product page. Eliminates the friction of context-switching between the shop front and the admin panel during QC and content review sessions.

---

## UX Flow

### Entering Edit Mode

1. Super admin visits any `/item/<id>` page.
2. A fixed **"Edit Mode"** button is visible in the bottom-right corner of the screen (only for `current_user.is_super_admin`). It is always visible, never collapses, and does not interfere with buyer UI.
3. Clicking "Edit Mode" slides in the edit panel from the right side of the screen. The main product page content shifts left (or the panel overlays it on narrower viewports).
4. The button label changes to "Close Edit Mode" while the panel is open.

### Edit Panel Layout

The panel has four sections, stacked vertically and scrollable:

**Section 1: Visibility**
- Toggle: **Pull from Shop / Push to Shop** — shows current state ("Live in shop" or "Hidden from shop"). Toggling sets `ai_approved` True/False. If the item is hidden because `needs_new_photo=True`, the toggle is disabled with a note: "Hidden pending new photo — clear flag first."
- Checkbox: **Flag for new photo** — sets `needs_new_photo=True` AND sets `ai_approved=False`. When checked and saved, the item is immediately pulled from the shop. Unchecking sets `needs_new_photo=False` but does NOT automatically restore `ai_approved` — that must be done via the visibility toggle separately.

**Section 2: Pricing**
- Input: **Price** (numeric, required, min $1)
- Input: **Retail price** (numeric, optional — used for "X% off retail" callout)
- Live preview: as price and retail price are typed, show the savings percentage inline (`~$X retail · Y% off`) exactly as it appears on the product page. Use the same ≥40% floor logic: if the implied savings is <40%, show a warning "Retail price will be auto-adjusted to maintain ≥40% savings callout on save."

**Section 3: Content**
Two-column layout (side by side):
- **Left column header:** "AI Generated" (read-only)
- **Right column header:** "Live" (editable)

Rows:
- Title: AI `ai_description` (left, greyed, non-editable) | Live `description` (right, text input, max 200 chars)
- Description: AI `ai_long_description` (left, greyed textarea, non-editable) | Live `long_description` (right, editable textarea, max 2000 chars)
- Category: Category name (left, read-only) | Category dropdown + subcategory dropdown (right, editable). Subcategories load via existing `GET /api/subcategories/<parent_id>` endpoint.

If `ai_description` or `ai_long_description` are null (item predates AI pipeline), show "No AI version available" in the left column.

**Section 4: Photos**
- Gallery strip: all photos (cover + ItemPhoto gallery) shown as thumbnails in a horizontal scrollable row.
- Cover photo has a "★ Cover" badge.
- Each non-cover photo has two icon buttons: **★ Set as Cover** and **✕ Remove**.
- Removing a photo marks it as `is_hidden=True` on the ItemPhoto record — does NOT delete the file. If the cover photo is removed, the first gallery photo is promoted to cover (same logic as existing `admin_ai_delete_gallery_photo`).
- **Add Photos** button at the end of the gallery strip:
  - On **desktop**: opens a sub-panel with two options:
    - "Upload from this device" — standard file picker (accepts JPEG, PNG, WebP, max 10MB each)
    - "Upload from phone" — triggers the existing QR code upload flow (`POST /api/upload_session/create` → generate QR → poll `/api/upload_session/status`). Show the QR code inline in the panel. Poll every 2 seconds. When a new photo arrives, add it to the gallery strip immediately.
  - On **mobile**: opens the device file picker directly (no QR option — they're already on the phone).
- New photos uploaded via either method are saved immediately to S3 via `photo_storage.save_photo_from_bytes()` and added as `ItemPhoto` records. They are NOT staged — they go live on save.
- Cover photo: when "★ Set as Cover" is clicked, call existing `POST /admin/ai/item/<id>/set-cover-photo` endpoint. Reflect the change immediately in the gallery strip (move ★ badge). This saves immediately — no need to wait for the main Save button.

### Save Behavior

- All changes (visibility, pricing, content, category) are committed by clicking a single **"Save Changes"** button at the bottom of the panel.
- Photos (set cover, remove) save immediately on action — they do not wait for the Save button. This matches existing behavior in the AI review modal.
- On successful save: flash a brief "Saved ✓" inline confirmation at the top of the panel. The product page behind the panel updates immediately to reflect the new title, price, and retail callout without a full page reload (update the relevant DOM elements via JS after the save response).
- On validation error: show inline error messages per field. Panel stays open.
- If the item is pulled from shop on save (either via visibility toggle or flag for photo), flash "Item hidden from shop" in the panel.

### Edge Cases

- If the item is `status='sold'`, the visibility toggle is disabled entirely with a note: "Item is sold — cannot change shop visibility."
- If the panel is open and the user navigates to another item page (e.g. via the "Back to Shop" link), the panel closes. State is not persisted across page navigations.
- Unsaved changes: if the user clicks "Close Edit Mode" with unsaved changes in text/pricing fields, show a browser `confirm()` dialog: "You have unsaved changes. Close anyway?" Photo actions (set cover, remove) are already saved and do not count as unsaved changes.

---

## New Routes

| Method | Path | Function | Auth | Description |
|--------|------|----------|------|-------------|
| `POST` | `/admin/item/<id>/quick-edit` | `admin_item_quick_edit` | `is_super_admin` | Save all panel fields (visibility, pricing, content, category) atomically. Returns JSON `{success, updated_fields, new_price, new_retail_price, new_description, new_long_description, savings_pct}`. |
| `POST` | `/admin/item/<id>/hide-photo` | `admin_item_hide_photo` | `is_super_admin` | Set `ItemPhoto.is_hidden=True` for a gallery photo by photo ID. Promotes next photo to cover if cover is hidden. Returns JSON `{success, new_cover_url}`. |

**Reuse existing routes — do not duplicate:**
- `POST /admin/ai/item/<id>/set-cover-photo` — set cover photo (already exists, already returns JSON)
- `POST /api/upload_session/create` — create QR session
- `GET /api/upload_session/status` — poll for phone uploads
- `POST /admin/item/<id>/replace_photo` — replace cover photo if needed

---

## Model Changes

### ItemPhoto — add `is_hidden` field

```python
is_hidden = db.Column(db.Boolean, default=False, server_default='0', nullable=False)
```

Migration required: `flask db migrate -m "add_itemphtoo_is_hidden"`

The shop visibility gate and gallery rendering in `product.html` must filter out `is_hidden=True` photos. Specifically:
- `item.gallery_photos` relationship or any query that renders gallery thumbs must exclude `is_hidden=True` ItemPhoto records.
- The catalog feed (`/catalog.xml`) must also exclude hidden photos from `g:additional_image_link`.

---

## Template Changes

### `product.html`

1. Add the "Edit Mode" FAB (floating action button) — only rendered when `current_user.is_authenticated and current_user.is_super_admin`. Fixed position, bottom-right, above any other fixed UI. Uses `--primary` color variable.

2. Add the slide-out panel `<div id="shop-edit-panel">` — hidden by default, slides in via CSS transition. Contains all four sections described in UX Flow above. Full panel is inside a `<form>` conceptually but uses JS fetch for submission — do NOT use an HTML `<form>` tag (per project rule: no form submits that cause page navigation from JS-driven panels).

3. Add the panel toggle JS: open/close, unsaved-changes guard, DOM update on save response.

4. Add the QR upload sub-panel JS — reuse the same polling logic from the onboarding flow (`/api/upload_session/status`). Display QR code as an `<img>` using a QR generation library already available in the project, or generate the QR server-side as a data URL.

5. Pass additional context to the template from `product_detail` route:
   - `ai_description` and `ai_long_description` from `item.ai_description` / `item.ai_long_description` (already on the model)
   - `all_categories` — top-level categories for the category dropdown (same query used in `add_item`)
   - All of these should be conditionally passed only when `current_user.is_super_admin` to avoid leaking AI fields to regular users.

### No new template files — all panel HTML lives inside `product.html` in a super-admin-gated block.

---

## Business Logic

### Visibility toggle rules

| Condition | Toggle state | Behavior on toggle ON |
|-----------|-------------|----------------------|
| `needs_new_photo=True` | Disabled | Show message: "Clear 'flag for new photo' first" |
| `status='sold'` | Disabled | Show message: "Item is sold" |
| `ai_approved=False`, no other block | Enabled | Set `ai_approved=True` |
| `ai_approved=True` | Enabled | Set `ai_approved=False` |

### Flag for new photo

When the checkbox is checked and saved:
- `needs_new_photo = True`
- `ai_approved = False`
- Item becomes invisible in shop immediately (both flags gate shop visibility)

When unchecked and saved:
- `needs_new_photo = False`
- `ai_approved` is NOT changed — admin must explicitly re-enable via visibility toggle

### Retail price / savings floor

The ≥40% savings floor is enforced on save in `admin_item_quick_edit`:

```python
if retail_price and retail_price > 0:
    min_retail = price / Decimal('0.60')  # ensures ≥40% savings
    if retail_price < min_retail:
        retail_price = min_retail.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
```

Return the adjusted `retail_price` in the JSON response so the panel can display the corrected value.

### Category change

If category is changed:
- Update `item.category_id`
- If a subcategory is selected, update `item.subcategory_id`
- If no subcategory selected (or new category has none), set `item.subcategory_id = None`

### Photo hide logic

When hiding a photo via `admin_item_hide_photo`:
- If the photo being hidden is NOT the cover: set `ItemPhoto.is_hidden = True`. Done.
- If the photo being hidden IS the cover (`item.photo_url == photo.photo_url`):
  - Find the first non-hidden `ItemPhoto` record for this item
  - Set `item.photo_url` to that photo's URL (promote to cover)
  - Set `is_hidden = True` on the hidden photo
  - If no other photos exist: block the action, return `{success: False, error: "Cannot remove the only photo"}`

---

## Constraints

- **Super admin only** — both the FAB and the panel are completely invisible to all other users including regular admins. Gate with `{% if current_user.is_super_admin %}` in the template and `@require_super_admin` (or equivalent check) on all new routes.
- **No HTML `<form>` tags** — all saves go through `fetch()` POST. Per project pattern.
- **No inline `tojson` in `onclick`** — pass item ID and photo IDs via `data-*` attributes.
- **Do not modify the `product_detail` route's buyer-facing logic** — all super admin context is additive. The route's existing behavior (teaser redirect, reserve-only mode, cart buttons) must remain unchanged.
- **CSS variables only** — no hardcoded colors. Panel uses `--bg-cream`, `--primary`, `--accent`, `--border`, etc.
- **Catalog feed** — `is_hidden=True` photos must be excluded from `g:additional_image_link` in `/catalog.xml`. Update the feed query.
- **No migration for the panel itself** — only the `ItemPhoto.is_hidden` column requires a migration.
- **Use `_email_photo_url()` pattern for photo URLs** in the gallery strip — same absolute URL logic as everywhere else.
- **QR code upload** — reuse existing `UploadSession` / `TempUpload` / `/api/upload_session/create` / `/api/upload_session/status` infrastructure exactly. Do not create new upload endpoints.

---

## Testing Checklist

- [ ] "Edit Mode" button only visible when logged in as super admin — invisible to buyers, regular admins, and logged-out users
- [ ] Panel slides in on click, slides out on "Close Edit Mode" click
- [ ] Unsaved text/price changes trigger confirm dialog on close — photo actions do not
- [ ] Visibility toggle disabled when `needs_new_photo=True`, shows explanation
- [ ] Visibility toggle disabled when `status='sold'`, shows explanation
- [ ] Toggling visibility on/off and saving correctly sets `ai_approved` True/False
- [ ] "Flag for new photo" sets both `needs_new_photo=True` and `ai_approved=False` on save
- [ ] Item flagged for new photo disappears from `/shop` immediately after save
- [ ] Unflagging photo (`needs_new_photo=False`) does NOT automatically restore shop visibility
- [ ] Price save updates the displayed price on the product page without reload
- [ ] Retail price below 40% savings floor is auto-adjusted on save; corrected value shown in panel
- [ ] Title and description save correctly; product page text updates without reload
- [ ] AI-generated fields shown read-only in left column; null AI fields show "No AI version available"
- [ ] Category change saves correctly; subcategory cleared when new category has none
- [ ] Gallery strip shows all non-hidden photos; cover has ★ badge
- [ ] "Set as Cover" button calls existing endpoint, updates ★ badge in gallery immediately
- [ ] "Remove" photo marks `is_hidden=True`; photo disappears from gallery strip
- [ ] Removing cover photo promotes next photo to cover; ★ badge moves
- [ ] Cannot remove last photo — error shown, photo stays in gallery
- [ ] "Add Photos" on desktop shows two options: device upload and QR code
- [ ] QR code option generates a valid QR and polls for uploads; new photo appears in gallery when uploaded from phone
- [ ] "Add Photos" on mobile opens device file picker directly (no QR option)
- [ ] New photos appear in the gallery on the product page (not just in the panel) after save
- [ ] `is_hidden=True` photos do not appear in the buyer-facing gallery
- [ ] `is_hidden=True` photos excluded from `/catalog.xml` `g:additional_image_link`
- [ ] All new routes return 403 for non-super-admin users
- [ ] No JS errors in console during normal panel use

---

## After Building

Cross-reference and update `CODEBASE.md`, `HANDOFF.md`, `DECISIONS.md`, and `website-feature-log.md` to reflect:
- New routes `/admin/item/<id>/quick-edit` and `/admin/item/<id>/hide-photo`
- New `ItemPhoto.is_hidden` field and migration
- Shop edit panel in `product.html` (super admin only)
- Updated gallery query to exclude `is_hidden=True` photos
- Updated catalog feed to exclude hidden photos from `g:additional_image_link`
