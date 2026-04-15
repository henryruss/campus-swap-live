# Fix: Shop Teaser Background — Per-Card Blur

## Problem

The current `inventory_teaser.html` mosaic uses `<img>` tags inside tile `<div>`s with a global CSS blur applied to the wrapper or image elements. Because there are only a handful of distinct approved photos in the DB at teaser time, the same images repeat visibly — making the "blurred mystery" effect feel broken and obvious.

## Goal

Replace the repeating-image tile approach with a CSS `background-image` approach where each tile independently shows one photo as its background, cropped/covered to the card. Blur is applied per-tile via `filter: blur()` on the tile itself. Cards retain their shape and spacing, so the visual reads as a grid of blurred item cards rather than a smeared photo collage.

## UX Before / After

**Before:** `<img src="photo.jpg">` repeated 4 times, visibly tiled.

**After:** Each tile is a `<div>` with `background-image: url(...)` + `background-size: cover` + `filter: blur(8px)` + slight dark overlay via `::after` pseudo-element. Photos still repeat if there are fewer than 16, but because each is rendered as a distinct card with its own rounded corners and shadow, the repetition is much less noticeable — they look like separate items rather than a wallpaper.

## Template Changes

**`templates/inventory_teaser.html`** — change the mosaic tile rendering:

### Current (broken) pattern
```html
<div class="teaser-tile">
  <img src="{{ url_for('uploaded_file', filename=photo) }}" alt="">
</div>
```
with CSS blur on `.teaser-tile img`.

### New pattern
Pass photo URLs to the template as a flat list (already done via `photos` context variable). In the template, render each tile as:

```html
<div class="teaser-tile"
     style="background-image: url('{{ url_for('uploaded_file', filename=tile_photo) }}')">
</div>
```

The tile list should be built with `cycle` logic in Jinja so that if there are fewer than 16 photos, they wrap (using `photos[(loop.index0 % photos|length)]`).

### CSS changes (`static/style.css` — Teaser section)

Replace current `.teaser-tile img` rules with:

```css
.teaser-tile {
  background-size: cover;
  background-position: center;
  filter: blur(8px);
  transform: scale(1.04); /* hides blur edge artifacts */
  border-radius: 8px;
  overflow: hidden;
  position: relative;
}

.teaser-tile::after {
  content: '';
  position: absolute;
  inset: 0;
  background: rgba(0, 0, 0, 0.15);
  border-radius: inherit;
}
```

Remove any `<img>` tags from the tile markup entirely. The tile `<div>` itself IS the image now.

### Route changes (`app.py` — `inventory()`)

No route changes needed. The existing logic that queries up to 16 approved item `photo_url` values and passes them as `photos` to the template is correct. The only change is in how the template renders them.

## Constraints

- Do not change the overlay card, email form, or `ShopNotifySignup` logic.
- Do not change the `shop_teaser_mode` AppSetting check.
- The `noindex` meta tag injection in `{% block head_extra %}` stays.
- Photo URL must still use `url_for('uploaded_file', filename=...)` — never `/static/uploads/`.
- If `photos` list is empty (no approved items yet), the mosaic should fall back gracefully — render tiles with a neutral `--bg-cream` background color, no broken image state.
