# Feature Spec: Global Image Lightbox

## Goal

Thumbnail images appear in many places across the app — the admin items table,
the seller dashboard, the approval queue cards, the QC photo strip on stop cards,
the storage audit, the payouts page, and more. There's currently no way to expand
them. This adds a single sitewide lightbox so any thumbnail can be clicked to view
full size.

---

## UX Flow

1. User sees a small thumbnail image anywhere on the site.
2. Thumbnail has a subtle cursor:pointer + a slight hover effect (dim + magnify icon).
3. User clicks the thumbnail.
4. A full-screen overlay fades in with the image centered and scaled to fit the
   viewport (max ~90vw × 90vh, preserving aspect ratio).
5. User dismisses by: clicking the overlay background, pressing Escape, or clicking
   an ×  close button in the top-right corner.
6. Overlay fades out. No page navigation, no reload.

**Edge cases:**
- If the full-size URL differs from the thumbnail URL (e.g. a `w=80` query param was
  used for the thumb), the lightbox should use the `data-lightbox-src` attribute if
  present; otherwise fall back to the `src` attribute on the `<img>`.
- On mobile, the image fills the screen width with height auto.
- If the image fails to load (404, broken), the lightbox still opens but shows a
  gray placeholder — don't crash.

---

## New Routes

None.

---

## Model Changes

None. No migration needed.

---

## Template Changes

### `templates/layout.html`

Two additions only:

**1. Lightbox HTML** — inject once, just before `</body>`:

```html
<!-- Global image lightbox -->
<div id="img-lightbox" aria-modal="true" role="dialog" aria-label="Image preview">
  <button id="img-lightbox-close" aria-label="Close">&times;</button>
  <img id="img-lightbox-img" src="" alt="Full size preview">
</div>
```

**2. Lightbox CSS** — in the `<style>` block or via a `{% block head_extra %}` include.
Use CSS variables only — no hardcoded colors. Key rules:

```css
#img-lightbox {
  display: none;
  position: fixed;
  inset: 0;
  z-index: 9000;           /* above approval modal (z ~1000), seller panel (~800) */
  background: rgba(0,0,0,0.85);
  align-items: center;
  justify-content: center;
  cursor: zoom-out;
}
#img-lightbox.open {
  display: flex;
}
#img-lightbox-img {
  max-width: 90vw;
  max-height: 90vh;
  object-fit: contain;
  border-radius: 4px;
  box-shadow: 0 8px 40px rgba(0,0,0,0.6);
  cursor: default;         /* don't let clicks on the image itself bubble to close */
}
#img-lightbox-close {
  position: absolute;
  top: 1rem;
  right: 1.25rem;
  font-size: 2rem;
  line-height: 1;
  background: none;
  border: none;
  color: #fff;
  cursor: pointer;
  opacity: 0.8;
}
#img-lightbox-close:hover { opacity: 1; }

/* Hover affordance on any lightbox-enabled thumbnail */
img.lightbox-trigger {
  cursor: zoom-in;
  transition: opacity 0.15s;
}
img.lightbox-trigger:hover {
  opacity: 0.8;
}
```

**3. Lightbox JS** — a small `<script>` block just before `</body>`, after the
lightbox HTML:

```javascript
(function () {
  const lb   = document.getElementById('img-lightbox');
  const img  = document.getElementById('img-lightbox-img');
  const btn  = document.getElementById('img-lightbox-close');

  function openLightbox(src) {
    img.src = src;
    lb.classList.add('open');
    document.body.style.overflow = 'hidden';
  }

  function closeLightbox() {
    lb.classList.remove('open');
    document.body.style.overflow = '';
    img.src = '';
  }

  // Event delegation — works even for thumbnails added after DOMContentLoaded
  // (approval modal innerHTML injection, QC stop card 30s refresh, etc.)
  document.addEventListener('click', function (e) {
    const el = e.target.closest('img.lightbox-trigger');
    if (el) {
      e.stopPropagation();
      const src = el.dataset.lightboxSrc || el.src;
      openLightbox(src);
    }
  });

  btn.addEventListener('click', closeLightbox);

  lb.addEventListener('click', function (e) {
    if (e.target === lb) closeLightbox();   // only close on backdrop click, not image click
  });

  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && lb.classList.contains('open')) closeLightbox();
  });
})();
```

**Why event delegation:** Several thumbnail locations are injected via
`innerHTML` at runtime (approval modal partial, QC stop card 30s refresh,
storage audit results partial). Direct `addEventListener` on `.lightbox-trigger`
elements at page load would miss these. Delegation on `document` handles all
of them automatically.

---

### Templates — add `.lightbox-trigger` class to thumbnail `<img>` tags

Add `class="lightbox-trigger"` (or append it to existing class lists) on every
thumbnail `<img>` that should be expandable. Read CODEBASE.md and the actual
template files to locate all instances. Known locations:

| Template | Context |
|---|---|
| `admin/items.html` | Lifecycle table thumbnail column |
| `admin/items.html` | Approval queue card thumbnails |
| `admin/payouts.html` | Paid history row thumbnails |
| `admin/needs_info.html` | QC queue table thumbnails |
| `admin/storage_detail.html` | Item list thumbnails |
| `admin/storage_audit_results.html` | Audit result card thumbnails |
| `admin/shift_intake_log.html` | Intake log item thumbnails |
| `admin/intake_flagged.html` | Flagged item thumbnails |
| `crew/stops_partial.html` | QC photo strip thumbnails |
| `templates/dashboard.html` | Seller dashboard item card thumbnails |

**Important:** Claude Code must read each template file before editing to confirm
thumbnail `<img>` tags exist and identify their exact class/structure. Do not
assume — the list above is based on CODEBASE.md descriptions, not a direct file
audit.

For thumbnails where the displayed `src` is already the full-size URL (most
cases, since `uploaded_file` serves the original), no `data-lightbox-src`
attribute is needed. Only add `data-lightbox-src` if the `src` is a resized or
cropped variant.

---

## Business Logic

No business logic. Pure front-end progressive enhancement — clicking a thumbnail
never triggers a server request.

---

## Constraints

- No new routes, no model changes, no migration.
- All CSS must use CSS variables where applicable (`var(--primary)`, etc.) —
  but the overlay background and close button color can use literal
  `rgba(0,0,0,...)` / `#fff` since they are intentionally outside the design
  system (dark overlay is universal regardless of brand color).
- The lightbox `z-index: 9000` must be higher than the approval modal and seller
  panel drawers (which are in the ~800–1000 range). Claude Code should confirm
  the actual z-index values in `style.css` and set `z-index` accordingly.
- Do **not** add `.lightbox-trigger` to the main product gallery on `product.html`
  — that page already has its own lightbox/zoom behavior.
- Do **not** add `.lightbox-trigger` to the approval modal gallery
  (`approval_detail_partial.html`) — that gallery already has its own nav/zoom.
- Do **not** break the QC stop card's `×` delete button. The delegation handler
  uses `e.target.closest('img.lightbox-trigger')` — clicking the `×` button
  (which is not an `<img>`) will not trigger the lightbox.
- The 30-second auto-refresh on `crew/shift.html` replaces the stop list via
  `innerHTML`. The event delegation pattern handles this automatically — no
  special refresh handling needed.
