# feature_ops_layout_and_photo_preview

## Goal

Three focused fixes to the admin ops page (`/admin/ops`) that remove daily friction:

1. **Scroll isolation** — the shift list, center truck cards, and unassigned panel each scroll independently; the page body never scrolls.
2. **Sticky icon sidebar** — the 52px admin icon sidebar stays fixed on screen at all times; it does not scroll with the page and does not get "stuck" mid-scroll.
3. **Item photo previews** — clicking a seller name in the unassigned panel, or in an assigned truck stop list, opens a lightweight modal showing that seller's item photos (cover + gallery).

No new routes. No model changes. No migrations.

---

## UX Flow

### Fix 1 — Scroll Isolation

**Current behavior:** Scrolling the shift list column scrolls the entire page. The center and right panels don't stay in view.

**Target behavior:**
- The outer ops wrapper fills the viewport below the nav bar (`height: calc(100vh - <nav height>)`), with `overflow: hidden`.
- The shift list column (left, 220px) has `overflow-y: auto` and scrolls independently.
- The truck cards column (center, `flex: 1`) has `overflow-y: auto` and scrolls independently.
- The unassigned panel (right, 210px) has `overflow-y: auto` and scrolls independently.
- None of these panels bleed scroll to `<body>` or `<html>`.

### Fix 2 — Sticky Icon Sidebar

**Current behavior:** The 52px icon sidebar (`admin_layout.html`) is either `position: sticky` or flows with the page, causing it to scroll down with content and then "stick" in a bad position.

**Target behavior:**
- The sidebar is `position: fixed; top: 0; left: 0; height: 100vh; z-index: 100`.
- The main content area has a left margin/padding equal to the sidebar width (52px) so nothing is obscured.
- This is a global fix — applies to all admin pages, not just ops.

**Mobile (≤768px):** Sidebar is already a horizontal top bar on mobile. That behavior is unchanged. The fixed positioning only applies at `> 768px`.

### Fix 3 — Item Photo Previews

**Trigger points:**
1. **Unassigned panel** — seller name/card is clickable; currently expands an inline assign form. The photo preview is a separate affordance: a small camera icon (🖼 or a camera SVG) next to the seller's name. Clicking the icon opens the photo modal. Clicking the name still opens the assign form as before.
2. **Truck stop list** — each stop row shows the seller name + address. Add the same camera icon after the name. Clicking it opens the photo modal.

**Photo modal behavior:**
- Full-page overlay (`position: fixed`, semi-transparent dark backdrop).
- Modal card: seller name as heading, horizontal scrollable photo strip (cover photo first, then gallery photos in order).
- Each photo is a thumbnail (~140px tall, auto width). Clicking a thumbnail opens it full-size in a new browser tab (`window.open`).
- Below the photo strip: a compact item list — one row per item showing `description`, `status` badge (color-coded: amber=pending/needs_info, green=approved/available, muted=sold), and unit size.
- Close button (×) in top-right corner. Also closes on backdrop click or `Escape` key.
- If a seller has no photos on any item, show a muted "No photos uploaded yet" message instead of the photo strip.

**Data approach:**
- `_ops_build_unassigned_panel()` already loads sellers and their items. Extend the data passed to the template to include, per seller, a list of `{item_id, description, status, unit_size, cover_photo, gallery_photos}`.
- Same extension for `_ops_build_truck_cards()` — stops already reference sellers; add item photo data.
- All photo URLs rendered into `data-*` attributes on the camera icon element (JSON-encoded list of filenames). Vanilla JS reads these and builds the modal DOM on click. No fetch call needed.
- Photo URLs use `url_for('uploaded_file', filename=photo_url)` — rendered server-side into the `data-*` attribute at template render time.

**Important:** Per rule #8, photo data must be in `data-*` attributes, not inline `tojson` in `onclick`.

---

## New Routes

None.

---

## Model Changes

None.

---

## Template Changes

### `admin/admin_layout.html`

- Change sidebar `position` to `fixed; top: 0; left: 0; height: 100vh; z-index: 100`.
- Add `padding-left: 52px` (or `margin-left: 52px`) to the main content wrapper so page content is not hidden behind the sidebar.
- Apply only at `> 768px` (below that, the existing horizontal top bar behavior is unchanged).

### `admin/ops.html`

**Outer wrapper:**
```css
.ops-shell {
  display: flex;
  height: calc(100vh - 60px); /* adjust 60px to match actual nav height */
  overflow: hidden;
}
```

**Each column:**
```css
.ops-shift-list   { width: 220px; flex-shrink: 0; overflow-y: auto; }
.ops-main         { flex: 1; overflow-y: auto; padding: 1.5rem; }
.ops-unassigned   { width: 210px; flex-shrink: 0; overflow-y: auto; }
```

**Photo preview trigger (camera icon):**
- Add after each seller name in the unassigned panel seller cards and in the truck stop rows.
- Element: `<button class="ops-photo-btn" data-seller-name="..." data-items='[...]' aria-label="View photos">` with an SVG camera icon (or `📷` emoji fallback).
- `data-items` is a JSON array rendered by Jinja2: each entry `{description, status, cover_photo_url, gallery_photo_urls}` where URLs are already resolved via `url_for`.

**Photo modal (injected once into DOM, reused):**
```html
<div id="ops-photo-modal" class="ops-modal-backdrop" hidden>
  <div class="ops-modal-card">
    <button class="ops-modal-close" aria-label="Close">×</button>
    <h3 id="ops-modal-seller-name"></h3>
    <div id="ops-modal-photos" class="ops-modal-photo-strip"></div>
    <div id="ops-modal-items" class="ops-modal-item-list"></div>
  </div>
</div>
```

**JS behavior (vanilla, in `ops.html` `<script>` block):**
```javascript
// On camera icon click: parse data-items, populate modal, show it.
// On backdrop click or Escape: hide modal.
// On thumbnail click: window.open(url, '_blank').
```

### `static/style.css`

Add a `/* Ops Photo Modal */` section:
- `.ops-modal-backdrop` — fixed full-screen overlay, `background: rgba(0,0,0,0.55)`, `z-index: 200`, flex center.
- `.ops-modal-card` — white card, `max-width: 540px`, `border-radius: 12px`, `padding: 1.5rem`, relative positioning.
- `.ops-modal-close` — absolute top-right, no background, large ×.
- `.ops-modal-photo-strip` — `display: flex; gap: 8px; overflow-x: auto; padding-bottom: 8px`.
- `.ops-modal-photo-strip img` — `height: 140px; width: auto; border-radius: 6px; cursor: pointer; flex-shrink: 0`.
- `.ops-modal-item-list` — simple rows, `border-top: var(--rule); margin-top: 1rem; padding-top: 0.75rem`.
- Status badges reuse existing `.badge` classes where possible.

---

## Business Logic

- Photo preview is read-only. No state changes.
- Items included in the preview: all non-rejected items for the seller (`status NOT IN ('rejected')`), consistent with how unit counts are computed elsewhere.
- If a seller has items but none have photos, show "No photos yet" rather than an empty strip.
- Gallery photos render after cover photo; order within gallery follows `ItemPhoto.id` ascending.

---

## Constraints

- Do not touch any POST routes, payout logic, or the Stripe webhook handler.
- Do not alter how clicking a seller name in the unassigned panel expands the assign form — the camera icon is an additional affordance, not a replacement.
- Do not use `tojson` in `onclick` attributes (rule #8). All item data goes in `data-items` on the button.
- The fixed sidebar change must not break the mobile horizontal top bar (keep the `≤768px` media query behavior intact).
- No new Python dependencies.
- Nav height assumption (used in `calc(100vh - Xpx)`) should be derived from a CSS variable or comment clearly so it's easy to adjust if nav height changes.
