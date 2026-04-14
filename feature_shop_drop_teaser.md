# Feature Spec: Shop Drop Pre-Launch Teaser

## Goal

Between now and June 1, the `/inventory` page should show a locked, blurred teaser
instead of a browsable shop. Buyers see real approved item photos — blurred — behind
a card announcing the launch date. This builds anticipation with real inventory and
avoids the shop feeling empty. On June 1 (or whenever the flag is flipped), the shop
opens normally with no other changes.

---

## UX Flow

### State A — Pre-launch (`shop_teaser_mode = 'true'`)

1. Buyer navigates to `/inventory`.
2. Page renders `inventory_teaser.html` instead of `inventory.html`.
3. Background: a mosaic grid of real approved item photos, blurred with a CSS
   `filter: blur(12px)` + semi-transparent overlay. Photos pulled from the same
   approved item query used by the live shop (up to ~12–16 thumbnails, no order
   preference needed). If fewer than 6 approved items exist, use placeholder
   colored tiles so the layout doesn't look broken.
4. On top of the blurred grid: a centered card with:
   - Campus Swap logo/wordmark (already in layout assets)
   - Headline: **"Shop Drop — Coming June 1st"**
   - Subheadline: e.g. "Items are filling up. Get notified the moment we open."
   - Email notification capture form (email input + submit button)
   - On submit: stores email to `ShopNotifySignup` table (new model, see below),
     flashes "We'll let you know!" success message, redirects back to `/inventory`.
     Duplicate email submissions are silently accepted (no error shown to user).
5. Category filter, search bar, and item count are **not rendered** in teaser state.
6. `/item/<id>` (product detail) redirects to `/inventory` with a flash:
   "Items go on sale June 1st — sign up to get notified." This prevents direct
   linking into item pages before launch.

### State B — Live (`shop_teaser_mode = 'false'` or key absent)

- `/inventory` renders exactly as today. No changes to existing behavior.
- `/item/<id>` works normally.
- Notification signup list is available to admin for export (see Admin section).

### Edge Cases

- **Fewer than 6 approved items:** render colored placeholder tiles (use
  `--bg-cream`, `--primary`, `--accent` CSS variables) so the blurred background
  grid always looks full. Minimum 12 tiles total — mix real photos with placeholders
  to fill.
- **Admin users:** teaser mode applies to everyone including admins. Admins can
  still reach `/admin` directly; no carve-out needed.
- **SEO:** teaser page should include a `<meta name="robots" content="noindex">`
  so Google doesn't index a blank shop. Remove this when shop opens.
- **Direct item URL while in teaser mode:** redirect to `/inventory` as described
  above.
- **Email already subscribed:** insert silently (or ignore duplicate — no
  `UNIQUE` constraint needed; duplicates are harmless and avoiding them keeps the
  UX clean).

---

## New Routes

| Method | Path | Function | Description |
|--------|------|----------|-------------|
| `POST /shop/notify` | `shop_notify_signup` | Public | Accepts email, saves `ShopNotifySignup`, redirects to `/inventory` with flash |

No changes to `GET /inventory` route signature — the route function reads the
`shop_teaser_mode` flag and branches to the correct template internally.

---

## Model Changes

### New: `ShopNotifySignup`

```
id          — Integer PK
email       — String(120), not nullable, not unique (duplicates silently accepted)
created_at  — DateTime, default utcnow
ip_address  — String(45), nullable (log for spam review; not displayed anywhere)
```

Migration required: `flask db migrate -m "add shop_notify_signup table"`

### AppSetting — new key

| Key | Values | Effect |
|-----|--------|--------|
| `shop_teaser_mode` | `'true'` / `'false'` | `'true'` → show teaser; anything else → normal shop |

Add to the AppSetting key reference comment in `app.py`.

---

## Template Changes

### New: `inventory_teaser.html`

Extends `layout.html`. Full-viewport layout.

**Structure:**
```
<body>
  <!-- Blurred background layer -->
  <div class="teaser-bg-grid">
    {% for item in preview_items %}
      <div class="teaser-tile">
        <img src="{{ url_for('uploaded_file', filename=item.thumbnail_filename) }}"
             alt="">
      </div>
    {% endfor %}
    {% for _ in placeholder_range %}
      <div class="teaser-tile teaser-tile--placeholder"></div>
    {% endfor %}
  </div>
  <div class="teaser-overlay"></div>

  <!-- Centered launch card -->
  <div class="teaser-card">
    <p class="teaser-eyebrow">Campus Swap — UNC Chapel Hill</p>
    <h1 class="teaser-headline">Shop Drop</h1>
    <p class="teaser-date">Opens June 1st</p>
    <p class="teaser-sub">Items are filling up. Be first in line.</p>
    <form method="POST" action="{{ url_for('shop_notify_signup') }}" class="teaser-form">
      <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
      <input type="email" name="email" placeholder="your@email.com" required
             class="teaser-input">
      <button type="submit" class="btn-primary">Notify Me</button>
    </form>
  </div>
</body>
```

**CSS (add to `style.css` under a `/* Teaser */` section):**

```css
/* Teaser */
.teaser-bg-grid {
  position: fixed;
  inset: 0;
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 4px;
  filter: blur(12px);
  transform: scale(1.05); /* eliminates blur edge artifacts */
  z-index: 0;
}
.teaser-tile {
  overflow: hidden;
  background: var(--bg-cream);
}
.teaser-tile img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.teaser-tile--placeholder {
  background: var(--primary);
  opacity: 0.15;
}
.teaser-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.55);
  z-index: 1;
}
.teaser-card {
  position: relative;
  z-index: 2;
  max-width: 420px;
  margin: 0 auto;
  padding: 48px 40px;
  background: var(--bg-cream);
  border-radius: 12px;
  text-align: center;
  /* vertically center in viewport */
  position: fixed;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
}
.teaser-eyebrow {
  font-size: 0.75rem;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--text-muted);
  margin-bottom: 8px;
}
.teaser-headline {
  font-size: 2.5rem;
  color: var(--primary);
  margin-bottom: 4px;
}
.teaser-date {
  font-size: 1.25rem;
  font-weight: 600;
  color: var(--accent);
  margin-bottom: 12px;
}
.teaser-sub {
  color: var(--text-muted);
  margin-bottom: 24px;
}
.teaser-form {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.teaser-input {
  padding: 10px 14px;
  border: 1px solid var(--border);
  border-radius: 6px;
  font-size: 1rem;
  width: 100%;
  box-sizing: border-box;
  background: #fff;
}

@media (max-width: 500px) {
  .teaser-card {
    width: calc(100vw - 32px);
    padding: 32px 24px;
  }
  .teaser-bg-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}
```

### Modified: `inventory` route function in `app.py`

At the top of the `inventory()` function, add:

```python
if AppSetting.get('shop_teaser_mode', 'false') == 'true':
    # Pull up to 16 approved item thumbnails for the blurred background
    preview_items = InventoryItem.query.filter_by(
        status='available'
    ).order_by(func.random()).limit(16).all()
    # Pad to minimum 12 tiles with placeholders
    placeholder_count = max(0, 12 - len(preview_items))
    return render_template(
        'inventory_teaser.html',
        preview_items=preview_items,
        placeholder_range=range(placeholder_count)
    )
# ... existing inventory logic continues unchanged below
```

### Modified: `product_detail` route function in `app.py`

At the top of the `product_detail()` function, add:

```python
if AppSetting.get('shop_teaser_mode', 'false') == 'true':
    flash('Items go on sale June 1st — sign up to be notified.', 'info')
    return redirect(url_for('inventory'))
```

### Modified: `admin.html` (or wherever AppSettings are managed)

Add `shop_teaser_mode` toggle alongside the existing `reserve_only_mode` and
`pickup_period_active` toggles in the admin dashboard. Label it:
**"Shop Teaser Mode"** — ENABLED / DISABLED. Same pattern as existing toggles.

---

## Business Logic

- The flag is the single source of truth. Flipping `shop_teaser_mode` to `'false'`
  (or deleting the key) opens the shop with zero code changes.
- `ShopNotifySignup` emails are for admin export only — no automated email is
  sent at this stage. When the shop opens, admin can export the list and send a
  one-time announcement via the existing mass email tool.
- No rate limiting required on `/shop/notify` beyond what Cloudflare/Render
  provide at the edge. If spam becomes a problem, add Turnstile (same pattern as
  the homepage waitlist form) — out of scope for this spec.
- `ip_address` column is stored for spam review, never displayed to users.

---

## Admin Export (lightweight, no new route needed)

Notify signups can be exported via a short addition to the existing CSV export
logic in `app.py`. Add a `ShopNotifySignup` export button to the admin panel
alongside the existing seller/item exports. Each row: email, created_at.
This is a one-liner query — no pagination needed.

---

## Constraints

- Do not modify the existing `inventory()` route logic below the new early-return.
  The live shop behavior must remain byte-for-byte identical when flag is off.
- Do not add `shop_teaser_mode` to the list of flags that affect `_category_grid.html`
  or any partial — the early-return handles it fully at the route level.
- Use `func.random()` (SQLAlchemy) for photo randomization — do not sort by
  `created_at` or any business field; order doesn't matter here and random keeps
  the background feeling fresh on reload.
- The `inventory_teaser.html` template must extend `layout.html` so nav, flash
  messages, and analytics fire normally.
- CSS must use only existing CSS variables. No new color values.

---

## Launch Checklist (for human sign-off)

- [ ] `ShopNotifySignup` migration written and run
- [ ] `shop_teaser_mode` AppSetting documented in `app.py` comment block
- [ ] `inventory_teaser.html` created
- [ ] Teaser early-return added to `inventory()` route
- [ ] Product detail redirect added to `product_detail()` route
- [ ] Admin toggle added for `shop_teaser_mode`
- [ ] CSV export addition for notify signups
- [ ] Flag flipped to `'true'` in production AppSettings
- [ ] Verified: flipping flag to `'false'` restores normal shop with no side effects
