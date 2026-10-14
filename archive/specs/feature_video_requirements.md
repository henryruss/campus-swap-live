# Feature Spec: Expanded Video Requirements

## Goal
Expand the list of categories that require a video at item submission. Currently only electronics-type categories require a video. This spec adds all categories where demonstrating that the item powers on is essential to buyer confidence and admin valuation. Enforcement is hard — sellers cannot submit without a video if their category is on the required list.

---

## Required Video Categories (Complete List)

The following categories require a video at submission. This replaces the existing partial list:

| Category / Subcategory Keywords | Reason |
|---|---|
| Mini Fridge | Must power on and cool |
| Microwave | Must power on |
| TV / Television | Must power on and display |
| Gaming / Console | Must power on |
| Heater / AC | Must power on and run |
| Blender | Must power on |
| Electric Scooter | Must power on and move |
| Air Fryer | Must power on |
| Printer | Must power on |
| Electronic (catch-all) | Must power on |

Categories that do NOT require a video: Couch/Futon, Mattress, Rug, Headboard/Bed Frame, Other.

### How Category Matching Works
The existing codebase matches video requirements against category names using a keyword list. The new keyword list should include (case-insensitive matching):
`['tv', 'television', 'gaming', 'console', 'printer', 'electronic', 'mini fridge', 'fridge', 'microwave', 'heater', 'ac', 'air conditioner', 'blender', 'scooter', 'air fryer']`

This list is defined in one place in `app.py` (currently used in the onboarding photo step) and must be updated there. Do not hardcode it in multiple locations — reference the same constant wherever video requirement is checked.

---

## UX Flow

### Onboarding Wizard (`/onboard`) — Step 3: Photos & Video
1. Seller selects their category in Step 1
2. When they reach Step 3 (Photos & Video), the UI checks whether their selected category requires a video
3. **If video is required:**
   - A clear banner appears at the top of the step: *"A short video is required for this item. Show it powering on — this helps buyers feel confident and helps us price it accurately."*
   - The video upload area is visually prominent and marked as required (e.g. asterisk or "Required" label)
   - The "Continue" / "Next" button is disabled until a video has been uploaded
   - If the seller tries to proceed without a video, show an inline error: *"Please upload a video before continuing. Show the item powering on."*
4. **If video is not required:**
   - Video upload area remains available but is labeled "Optional"
   - No banner shown
   - Seller can proceed without uploading a video

### Add Item Flow (`/add_item`) — Same enforcement
- The same video requirement logic applies when an existing seller adds an additional item
- Same UI treatment: banner, required label, disabled next button until video uploaded

### Edit Item Flow (`/edit_item/<id>`)
- If an item was submitted before this feature was deployed and has no video, but its category now requires one, do NOT retroactively block the seller from editing other fields
- However, if the seller is on the photo/video step of an edit and their category requires a video, surface the same banner as a soft reminder (not a hard block on save, since the item is already submitted)

---

## New Routes
None. The video upload already uses existing routes (`/api/upload_session/create`, `/upload_from_phone`, `/upload_video_from_phone`).

---

## Model Changes
None. `InventoryItem.video_url` already exists.

---

## Template Changes

### `templates/onboard.html` — Step 3 (Photos & Video)
- Add a conditional banner block that renders when the selected category is in the required video list
- Banner uses `var(--accent)` left border or background tint to draw attention without being alarming
- Add `required` visual indicator to the video upload zone when applicable
- Add JavaScript check: before allowing progression to Step 4, verify `video_url` is set if category requires it
- Pass `video_required` boolean from the backend into the template context for this step

### `templates/add_item.html` — Photo/Video step
- Same conditional banner and JS enforcement as onboard.html
- Pass `video_required` boolean from backend

### `templates/edit_item.html`
- Add soft reminder banner (no hard enforcement on save)
- Banner copy: *"Items in this category typically require a video showing it powers on. Consider adding one to help buyers."*

---

## Business Logic

### Backend Enforcement
- In the route handler for item submission (both `/onboard` POST and `/add_item` POST), add a server-side check:
  - If `item.category` is in the required video list AND `video_url` is None or empty → return a validation error with message: *"A video is required for this item category."*
  - This is a safety net for cases where JS validation is bypassed — the frontend check is the primary UX, but the backend must also enforce it

### Defining the Required List
- Define a single constant in `app.py`, e.g.:
  ```python
  VIDEO_REQUIRED_CATEGORY_KEYWORDS = [
      'tv', 'television', 'gaming', 'console', 'printer', 'electronic',
      'mini fridge', 'fridge', 'microwave', 'heater', 'ac', 'air conditioner',
      'blender', 'scooter', 'air fryer'
  ]
  ```
- A helper function `category_requires_video(category_name)` does a case-insensitive substring match against this list
- This function is used in: route handlers (backend enforcement), template context (passing `video_required` boolean), and any future places that need to know

### Edge Cases
- **Subcategory matching:** If the seller selects a subcategory (e.g. "Window AC" under "Heater/AC"), match against both the parent category name and the subcategory name
- **"Other" category:** Does not require a video. If a seller puts a blender under "Other" instead of "Blender," that is their choice — we do not attempt to infer category from description
- **Category changed after submission:** If an admin changes a category during approval to one that requires a video and none exists, the admin should see a note in the approval UI: *"This category typically requires a video — none was uploaded."* This is advisory only; admin can still approve

---

## Constraints
- Do not touch the existing QR code phone upload flow or the `TempUpload` / `UploadSession` models
- Do not change video file size limits (50MB max) or format restrictions (MP4, MOV, WebM) — these remain the same
- Do not change the behavior for categories that are already on the required list — this spec only expands the list, it does not change the mechanism
