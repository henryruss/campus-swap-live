# Bug Fix: Mattress Category — Photo Not Required

**Type:** Bug Fix  
**Priority:** High (blocking seller submissions right now)  
**Status:** Ready to build

---

## Problem Statement

A seller emailed to report they could not submit a mattress listing because the site requires at least one photo, but the Mattress category intentionally has no photo upload UI. They worked around it by submitting under the Furniture category instead.

The photo requirement was deliberately removed from the mattress flow (mattresses are a commodity — condition is graded at intake, not by seller photo). However, the **backend validation still enforces at least one photo for all categories**, and the **`/add_item` flow likely still enforces this client-side too**. Both need to be updated.

---

## Root Cause

Two places enforce the photo requirement:

1. **Backend (`app.py`)** — the `onboard` and/or `add_item` POST handler checks `if not photos` (or similar) and returns an error. This check does not currently have a category exemption for Mattress.

2. **Frontend (`onboard.html` / `add_item.html`)** — the "Next" button on the photo step is likely gated on `photoFiles.length > 0` in JS. If the user selected Mattress and the photo step is shown but the upload UI is hidden, the step cannot be advanced without a photo.

---

## Affected Flows

Both flows share the same photo step logic:
- **`/onboard`** — new seller onboarding wizard
- **`/add_item`** — returning seller adding an item

---

## Fix

### 1. Backend — Exempt Mattress from photo requirement

In `app.py`, find the photo validation inside the `onboard` and `add_item` POST handlers. The check looks something like:

```python
if not uploaded_photos and not existing_photos:
    flash("Please upload at least one photo.", "error")
    return redirect(...)
```

Change it to:

```python
category = InventoryCategory.query.get(category_id)
mattress_exempt = category and 'mattress' in category.name.lower()

if not mattress_exempt and not uploaded_photos and not existing_photos:
    flash("Please upload at least one photo.", "error")
    return redirect(...)
```

Do this for **both** the `onboard` and `add_item` handlers. Use `category.name.lower()` string matching (consistent with how video-required categories are checked elsewhere in the codebase).

### 2. Frontend — Allow advancing past photo step with zero photos for Mattress

In `onboard.html` and `add_item.html`, find the JS that gates the "Next" button on the photo step. It will look something like:

```js
if (currentStep === PHOTO_STEP && photoFiles.length === 0) {
  showError("Please add at least one photo.");
  return;
}
```

Wrap this with a mattress check:

```js
const selectedCategoryName = document.querySelector('[data-category-name]')?.dataset.categoryName || '';
const isMattress = selectedCategoryName.toLowerCase().includes('mattress');

if (currentStep === PHOTO_STEP && photoFiles.length === 0 && !isMattress) {
  showError("Please add at least one photo.");
  return;
}
```

The category name should already be available in a `data-*` attribute somewhere on the page (since it's used to show/hide the video-required banner). If not, add a hidden `data-category-name="{{ selected_category.name }}"` attribute to the photo step container, populated from session/form state.

### 3. UX — Photo step for Mattress

Confirm that when a user selects Mattress:
- The photo upload UI is already hidden (per the original decision to remove it).
- The step either skips entirely OR shows a clean informational message like: *"No photos needed for mattresses — we'll inspect the condition when we pick it up."*
- The "Next" button is enabled and not blocked.

If the photo step is still shown for mattresses (just with the upload UI hidden), it would be cleaner to skip the step entirely via the step-navigation logic. However, if that's a larger change, the minimal fix is just ensuring the "Next" button isn't blocked — the hidden upload UI already prevents accidental uploads.

---

## New Routes

None. This is a validation change only.

---

## Model Changes

None. No migration needed.

---

## Template Changes

| Template | Change |
|----------|--------|
| `onboard.html` | Add mattress check to JS photo step gating |
| `add_item.html` | Same JS change as above |

---

## Business Logic

- Only "Mattress" (case-insensitive substring match on `InventoryCategory.name`) is exempt.
- All other categories continue to require at least one photo.
- The mattress exemption applies to both `onboard` and `add_item`.
- `edit_item` does not need a change — editing an existing item that was submitted without photos already works (existing items have `photo_url` as nullable).

---

## Constraints

- Do not change the photo upload UI or logic for any other category.
- Do not hardcode a category ID — use name-based matching.
- Do not touch Stripe, payout, or item status logic.
- Both the frontend gate and the backend check must be updated — fixing only one would still leave sellers stuck (frontend fixed but backend rejects) or insecure (backend fixed but UI doesn't allow advancing).

---

## Verification Steps

1. Start a new onboarding session, select Mattress as category.
2. On the photo step: confirm the "Next" button is not blocked. Advance without uploading any photos.
3. Complete the rest of onboarding and submit.
4. Confirm no flash error about missing photos.
5. Confirm item is created in DB with `photo_url = None` (or empty) and `status = 'pending_valuation'`.
6. Repeat steps 1–5 using `/add_item` as a returning seller.
7. Regression: select Furniture/Couch and confirm that submitting without a photo still shows the error.
