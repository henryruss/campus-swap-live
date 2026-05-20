# Feature Spec: Quick Capture UX Fixes

## Goal

Fix four issues with the existing quick capture flow and add two new capabilities:

1. **Photos don't appear after save** — driver has no confirmation the capture worked
2. **Modal state doesn't reset** — "Saving..." persists between modal opens
3. **No delete for accidental captures** — crew and admin both need hard delete
4. **No notes field** — driver can't add context like price estimate or condition note

---

## What Changes

### 1 — Captured Items Appear on Stop Cards (Shift View)

After a successful quick capture, the driver closes the modal and sees the shift route. Under the seller's name on their stop card, any quick-capture items taken for that seller during this shift should appear as a small photo strip — same visual pattern as the existing item photo strip on stop cards.

**How it works:**

The shift view already auto-refreshes `#stop-list` every 30 seconds via `crew/stops_partial.html`. Quick-capture items just need to be included in that partial's data.

In `crew_shift_stops_partial` (the route serving `stops_partial.html`), add a query for quick-capture items per seller on this truck:

```python
# For each stop, attach quick captures made for that seller during this shift
quick_captures_by_seller = {}
qc_items = InventoryItem.query.filter(
    InventoryItem.is_quick_capture == True,
    InventoryItem.quick_capture_shift_id == shift.id,
    InventoryItem.seller_id.in_([p.seller_id for p in pickups])
).order_by(InventoryItem.date_added.asc()).all()

for item in qc_items:
    quick_captures_by_seller.setdefault(item.seller_id, []).append(item)
```

Pass `quick_captures_by_seller` into the partial context.

In `crew/stops_partial.html`, below the existing item photo strip on each stop card, add a "Quick Captures" row:

```
{% set captures = quick_captures_by_seller.get(stop.seller_id, []) %}
{% if captures %}
  <div class="qc-photo-strip">
    {% for item in captures %}
      <div class="qc-photo-wrap" data-item-id="{{ item.id }}">
        <img src="{{ url_for('uploaded_file', filename=item.photo_url) }}"
             class="qc-thumb" alt="Capture #{{ item.id }}">
        <span class="qc-id-badge">#{{ item.id }}</span>
        <button class="qc-delete-btn"
                data-item-id="{{ item.id }}"
                data-csrf="{{ csrf_token() }}">✕</button>
      </div>
    {% endfor %}
  </div>
{% endif %}
```

The delete button is wired via JS in `stops_partial.html` (see Section 3 below).

**Immediate feedback after save (no waiting for 30s refresh):**

In `quick_capture_modal.html`, after a successful save response, before closing the modal, trigger a manual refresh of `#stop-list`:

```javascript
// After data.success === true, before closeModal():
var stopList = document.getElementById('stop-list');
if (stopList) {
  fetch(window.location.pathname + '/stops_partial')
    .then(function(r){ return r.text(); })
    .then(function(html){ stopList.innerHTML = html; });
}
closeModal();
```

This way the photo appears on the stop card the moment the modal closes, without waiting for the next auto-refresh cycle.

---

### 2 — Modal State Resets on Every Open

The modal's JS state (capturedBlob, button text, error messages) must fully reset each time the modal opens. Currently if a save is in-progress or completed, reopening the modal inherits the previous state.

In `quick_capture_modal.html`, in the function that opens the modal, add a full reset:

```javascript
function openModal(triggerBtn) {
  // Reset all state
  capturedBlob = null;
  saveBtn.disabled = true;
  saveBtn.innerHTML = 'Save Item &rarr;';
  photoPreview.style.display = 'none';
  photoPreview.src = '';
  retakeBtn.style.display = 'none';
  captureBtn.style.display = 'block';
  errorDiv.textContent = '';
  errorDiv.style.display = 'none';
  notesInput.value = '';

  // ... existing seller/shift context setup ...
  // ... existing camera start ...
}
```

Also ensure the camera stream is fully stopped and restarted on each open — do not reuse a stale stream from a previous session.

---

### 3 — Crew Delete (Hard Delete from Stop Card)

The small ✕ button on each quick-capture photo in the stop card strip calls a new delete route. This must be a hard delete — removes the DB record and the photo file from disk.

**New route:**

```
POST /crew/quick_capture/<item_id>/delete
Function: crew_quick_capture_delete
Auth: @login_required, is_worker, worker_status='approved'
```

Logic:
```python
@login_required
def crew_quick_capture_delete(item_id):
    item = InventoryItem.query.get_or_404(item_id)

    # Guard: only the capturing worker can delete
    if item.captured_by_id != current_user.id:
        return jsonify({'success': False, 'error': 'Not authorized'}), 403

    # Guard: only quick-capture items, only needs_info status
    if not item.is_quick_capture or item.status != 'needs_info':
        return jsonify({'success': False, 'error': 'Cannot delete this item'}), 400

    # Delete photo from disk
    photo_path = os.path.join(app.config['UPLOAD_FOLDER'], item.photo_url)
    if os.path.exists(photo_path):
        os.remove(photo_path)

    # Delete gallery photos if any (shouldn't exist for QC items but be safe)
    for photo in item.gallery_photos:
        p = os.path.join(app.config['UPLOAD_FOLDER'], photo.photo_url)
        if os.path.exists(p):
            os.remove(p)
        db.session.delete(photo)

    db.session.delete(item)
    db.session.commit()
    return jsonify({'success': True})
```

**JS in `stops_partial.html`:**

Wire the ✕ button via event delegation on the stop list container (not inline onclick — per project rule #8):

```javascript
document.addEventListener('click', function(e) {
  var btn = e.target.closest('.qc-delete-btn');
  if (!btn) return;
  if (!confirm('Delete this capture? This cannot be undone.')) return;

  var itemId = btn.dataset.itemId;
  var csrf = btn.dataset.csrf;
  var wrap = btn.closest('.qc-photo-wrap');

  fetch('/crew/quick_capture/' + itemId + '/delete', {
    method: 'POST',
    headers: { 'X-CSRFToken': csrf, 'Content-Type': 'application/x-www-form-urlencoded' },
    body: 'csrf_token=' + encodeURIComponent(csrf)
  })
  .then(function(r){ return r.json(); })
  .then(function(data){
    if (data.success) {
      wrap.remove();
    } else {
      alert(data.error || 'Could not delete. Try again.');
    }
  })
  .catch(function(){ alert('Network error. Try again.'); });
});
```

Because `stops_partial.html` is injected as innerHTML by the auto-refresh, event listeners attached to its elements are wiped on each refresh cycle. Use event delegation on `document` or on a stable outer container that persists across refreshes (e.g. the `<main>` tag or `#shift-page-wrap` if one exists).

---

### 4 — Admin Hard Delete

Add a delete button to each row in `admin/needs_info.html` (the Quick Captures admin queue).

**New route:**

```
POST /admin/quick_capture/<item_id>/delete
Function: admin_quick_capture_delete
Auth: @login_required, is_admin
```

Logic — identical to crew delete but without the `captured_by_id` guard (admin can delete any quick-capture item):

```python
@login_required
def admin_quick_capture_delete(item_id):
    if not current_user.is_admin:
        abort(403)

    item = InventoryItem.query.get_or_404(item_id)

    if not item.is_quick_capture:
        return jsonify({'success': False, 'error': 'Not a quick capture item'}), 400

    photo_path = os.path.join(app.config['UPLOAD_FOLDER'], item.photo_url)
    if os.path.exists(photo_path):
        os.remove(photo_path)

    for photo in item.gallery_photos:
        p = os.path.join(app.config['UPLOAD_FOLDER'], photo.photo_url)
        if os.path.exists(p):
            os.remove(p)
        db.session.delete(photo)

    db.session.delete(item)
    db.session.commit()
    return jsonify({'success': True})
```

In `admin/needs_info.html`, add a delete button to each row. On click, confirm → POST → remove the row from the DOM on success. No page reload needed.

---

### 5 — Notes Field in Modal

Add an optional textarea to `quick_capture_modal.html` below the photo preview area:

```html
<div id="qc-notes-wrap" style="display:none;">
  <label for="qc-notes">Notes (optional)</label>
  <textarea id="qc-notes"
            name="notes"
            placeholder="e.g. $50, small stain on backside, missing remote..."
            rows="2"
            maxlength="500"></textarea>
</div>
```

Show `#qc-notes-wrap` when a photo has been taken (same moment the thumbnail appears). Hide and clear it when the modal resets.

In the fetch POST, append the notes value:

```javascript
fd.append('notes', document.getElementById('qc-notes').value.trim());
```

In `crew_quick_capture` route (`app.py`), read and save to `long_description`:

```python
notes = request.form.get('notes', '').strip()
# In InventoryItem constructor:
long_description = notes if notes else None,
```

No model changes. No migration. `long_description` is already a nullable Text field.

---

## New Routes Summary

| Method | Path | Function | Auth |
|--------|------|----------|------|
| `POST` | `/crew/quick_capture/<item_id>/delete` | `crew_quick_capture_delete` | Worker approved |
| `POST` | `/admin/quick_capture/<item_id>/delete` | `admin_quick_capture_delete` | Admin |

---

## Model Changes

None. All fields already exist.

---

## Template Changes

| Template | Change |
|----------|--------|
| `crew/stops_partial.html` | Add QC photo strip per stop card; event-delegated delete JS |
| `crew/quick_capture_modal.html` | Full state reset on open; trigger stops_partial refresh after save; notes textarea |
| `admin/needs_info.html` | Delete button per row with confirm + DOM removal on success |

---

## Route Changes (Existing)

| Route | Change |
|-------|--------|
| `crew_shift_stops_partial` | Add `quick_captures_by_seller` dict to template context |
| `crew_quick_capture` | Read `notes` from form, pass as `long_description` to item constructor |

---

## Constraints

- Do not touch `crew_shift_view` — the stop list rendering goes through `stops_partial.html` only.
- Do not touch any seller-facing routes, Stripe, or payout logic.
- Event listeners in `stops_partial.html` must use event delegation on a stable ancestor — the partial's own elements are replaced on each auto-refresh cycle.
- Photo deletion must use `app.config['UPLOAD_FOLDER']` to resolve the path — never hardcode `/var/data/` or `static/uploads/`.
- Hard delete only — no `status='rejected'` soft delete path for quick-capture items.
- The crew delete route must verify `captured_by_id == current_user.id` before deleting. A worker cannot delete another worker's captures.
- All new JS uses `data-*` attributes for item IDs and CSRF tokens — no inline `tojson` in event handlers.
- No hardcoded colors. CSS variables only.
