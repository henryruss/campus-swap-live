# Fix: Mattress Photo Exemption in Seller Onboarding

## Goal

Mattresses are a high-value, high-volume category but sellers won't strip their beds to photograph them. Remove the photo/video step when the selected category is Mattress, and replace it with a mandatory acknowledgment checkbox: the seller confirms they understand that any mattress with stains or defects will be refused at pickup, no exceptions.

This applies to both **`/onboard`** (new seller wizard) and **`/add_item`** (existing seller adding an item).

---

## UX Flow

### Happy path — mattress selected

1. Seller selects "Mattress" on Step 1 (category).
2. Step 3 (normally Photos & Video) is **replaced** by a new "Mattress Condition Agreement" step.
3. The agreement step shows:
   - A single large checkbox (the "mega checkbox" described by product) with label:
     > "I understand that if my mattress has any stains, odors, or visible defects, Campus Swap will not accept it at pickup — no exceptions."
   - A short supporting blurb (muted, smaller text) beneath:
     > "We maintain quality standards for all items. Don't worry about photos — our team will inspect the mattress when we arrive."
   - The "Next" button is **disabled** until the checkbox is checked.
4. On submit, `mattress_condition_acknowledged = True` is stored in the session (onboarding) or passed as a hidden field (add_item).
5. Wizard continues normally to Step 4 (Title), skipping photo entirely.

### Seller goes back and changes category away from Mattress

- If seller navigates back to Step 1 and selects a non-mattress category, the mattress acknowledgment is cleared and Step 3 returns to the normal photo upload step.
- The JS that drives step visibility must re-evaluate `isMattress` on any category change.

### Admin receives a mattress submission with no photos

- This is expected and valid. Admin approval queue must **not** show a "missing photos" warning for mattress items.
- In `admin.html`, wherever a "no photo" fallback is shown, add a condition: if `item.category.name == 'Mattress'` (case-insensitive), show a neutral "No photo — mattress listing" badge instead of an error state.

---

## Template Changes

### `onboard.html` and `add_item.html`

1. **Detect mattress category in JS.** The category step already sets a JS variable (or data attribute) for the selected category name. Add:

   ```javascript
   const isMattress = selectedCategoryName.toLowerCase() === 'mattress';
   ```

2. **Conditional step rendering.** Where Step 3 is rendered:
   - If `isMattress` → hide the photo upload step div, show the mattress acknowledgment step div.
   - If not `isMattress` → show the photo upload step, hide the acknowledgment step.
   - This is a JS-driven show/hide, not a server round-trip.

3. **Mattress acknowledgment step HTML** (new `<div id="step-mattress-ack">` alongside the existing step divs):

   ```html
   <div id="step-mattress-ack" class="onboard-step" style="display:none;">
     <div class="step-header">
       <h2>One thing to know</h2>
       <p class="step-subhead">No photos needed — but please read this carefully.</p>
     </div>

     <label class="mattress-ack-label">
       <input type="checkbox" id="mattress_ack_checkbox" name="mattress_condition_acknowledged" value="1">
       <span class="mattress-ack-text">
         I understand that if my mattress has any stains, odors, or visible defects,
         Campus Swap will <strong>not accept it at pickup</strong> — no exceptions.
       </span>
     </label>

     <p class="mattress-ack-note">
       We maintain quality standards for all items. Don't worry about photos —
       our team will inspect the mattress when we arrive.
     </p>
   </div>
   ```

4. **"Next" button gating.** When the active step is `step-mattress-ack`, the Next button is disabled until `#mattress_ack_checkbox` is checked. Add a `change` listener:

   ```javascript
   document.getElementById('mattress_ack_checkbox').addEventListener('change', function() {
     nextBtn.disabled = !this.checked;
   });
   ```

   Also re-disable the button when navigating back to this step and the checkbox is unchecked.

5. **Photo validation bypass.** The existing "Next" validation on the photo step checks `photos.length >= 1`. Wrap that check:

   ```javascript
   if (!isMattress && photos.length < 1) {
     showError('Please add at least one photo.');
     return;
   }
   ```

6. **Hidden field for form submission.** When the mattress ack step is active, the checkbox value `mattress_condition_acknowledged=1` must be included in the final form POST. Since the checkbox is already in the DOM with `name="mattress_condition_acknowledged"`, this happens automatically if checked. No hidden field needed.

---

## Backend Changes (`app.py`)

### `onboard` route (POST handler)

- Read `mattress_condition_acknowledged = request.form.get('mattress_condition_acknowledged') == '1'`
- **If category is Mattress AND acknowledgment is not present:** return form error "Please confirm the mattress condition policy."
- **Photo requirement bypass:** The existing backend check that rejects submission if no photos are attached must be conditioned on category:
  ```python
  category_name = db.session.get(InventoryCategory, category_id).name
  is_mattress = category_name.lower() == 'mattress'
  
  if not is_mattress and not photos:
      flash('Please upload at least one photo.', 'error')
      return redirect(...)
  ```
- **Video requirement bypass:** Mattress is not in the video-required category list, so no change needed there. But add `'mattress'` to an explicit exclusion if ever needed.
- No new model field needed — acknowledgment is a submission-time validation, not stored state.

### `add_item` route (POST handler)

Same photo-bypass logic as above.

### `admin.html`

In the item approval card and lifecycle table, wherever a "no photos" warning or placeholder is displayed:
- Add condition: `{% if item.category and item.category.name|lower == 'mattress' %}` → show `<span class="badge badge-muted">Mattress — no photo</span>` instead of any error/warning state.

---

## CSS (`static/style.css`)

Add a new block for the mattress acknowledgment UI:

```css
/* Mattress Acknowledgment Step */
.mattress-ack-label {
  display: flex;
  gap: 16px;
  align-items: flex-start;
  background: var(--bg-cream, #F5F0E8);
  border: 1.5px solid var(--accent, #C8832A);
  border-radius: 12px;
  padding: 20px 24px;
  cursor: pointer;
  margin: 24px 0 16px;
}

.mattress-ack-label input[type="checkbox"] {
  width: 22px;
  height: 22px;
  flex-shrink: 0;
  margin-top: 2px;
  accent-color: var(--primary, #1A3D1A);
  cursor: pointer;
}

.mattress-ack-text {
  font-size: 16px;
  line-height: 1.55;
  color: var(--text-primary, #1A3D1A);
}

.mattress-ack-text strong {
  color: var(--accent, #C8832A);
}

.mattress-ack-note {
  font-size: 13px;
  color: var(--text-muted, #6B8F6B);
  line-height: 1.6;
  margin-top: 0;
}
```

---

## Business Logic

- **No `InventoryItem` model changes needed.** The acknowledgment is a gate, not stored state.
- **No migration needed.**
- Category matching is **case-insensitive** (`lower() == 'mattress'`) in both JS and Python, to guard against DB name variations.
- The admin intake / organizer intake flow is **unaffected** — movers physically inspect at pickup and refuse the item on-site if it has stains. That judgment call is theirs; this feature just sets the expectation upfront.
- The `photo_url` field on `InventoryItem` will be `None` for mattress listings. Anywhere in templates that renders `item.photo_url` should already have a fallback image — verify `admin.html`, `dashboard.html`, `inventory.html` all handle `None` photo gracefully (they should from prior work, but Claude Code should confirm).

---

## Constraints

- Do **not** touch the Cropper.js, QR upload, or `TempUpload` logic — just conditionally hide that entire step.
- Do **not** add a new DB column for `mattress_condition_acknowledged`.
- Do **not** change step numbering in any way that breaks the progress bar — the mattress ack step **replaces** Step 3 in place; the total step count stays the same.
- Category detection must use the category **name** (string match), not `category_id`, since IDs are environment-specific.
