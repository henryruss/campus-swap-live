# feature_homepage_redesign.md

> **Status:** Draft — pending Henry sign-off (SPEC_CHECKLIST gate).
> **Ambiguity to resolve during build:** the room's current location is unclear — `CODEBASE.md` lists the interactive room under `index.html`, but Henry believes it lives on `become_a_seller.html`. **Claude Code must first verify where the room actually is in the code, then ensure it ends up on `become-a-seller` and is gone from the new homepage.** Reconcile `CODEBASE.md` to match reality as part of the cross-reference step.

---

## Goal

The current homepage (`index.html`) is a pre-launch artifact: a hero, a **waitlist signup form**, and an interactive room. The shop is now live, so the page undersells us — it captures emails for a launch that already happened instead of driving the two things that matter now: **shopping the live inventory** and **listing items for pickup**.

This redesign turns `/` into a lightweight, season-aware marketplace front page that:

1. Shows both a **Buy** and a **Sell** entry point in a compact "two-door" hero, rendered as **frosted-glass panels over a tiled photo background built from real inventory** (smaller-but-visible buttons).
2. Drops the visitor straight into a **dense grid of curated listings** immediately below the hero, so a cold visitor (general public — *not* only incoming students) instantly understands this is a **used-consignment marketplace** without clicking through.
3. Surfaces **category chips** that deep-link into the existing shop (`/inventory`) filters.
4. **Adapts by season** off two existing AppSetting flags — no new toggles — so the same page is correct whether we're selling, taking pickups, both, or neither.

Removed in this pass: the waitlist signup form (UNC focus, no expansion capture for now) and the `$65 average payout` claim. The interactive room is **kept** and lives on `become-a-seller` (verify its current location first — see the ambiguity note at the top).

---

## Season state machine

Two existing AppSetting flags drive everything. No new flags.

| Flag | Meaning |
|---|---|
| `pickup_period_active` (`'true'`/`'false'`) | Sellers can schedule pickups. |
| `shop_teaser_mode` (`'true'`/`'false'`) | When `'true'`, `/inventory` renders the teaser, i.e. the shop is **not** live-selling. |

Derive two booleans in the `index` view via a small helper `_homepage_state()`:

```
pickups_on = AppSetting.get('pickup_period_active') == 'true'
shop_live  = AppSetting.get('shop_teaser_mode') != 'true'
```

(Note: `reserve_only_mode` is **independent** — it hides buy buttons on product pages but items are still browseable. The homepage grid still renders in reserve-only mode; cards link to the product page as normal, which handles reserve-vs-buy itself.)

| `pickups_on` | `shop_live` | Homepage mode | What renders |
|:---:|:---:|---|---|
| ✅ | ✅ | **Dual** *(current state)* | Two-door hero (Buy + Sell) → curated grid → chips |
| ❌ | ✅ | **Buyer-only** | Single full-width Buy hero → curated grid → chips. **Seller door removed entirely.** Nav "Sell" → `become-a-seller` out-of-season message. |
| ✅ | ❌ | **Seller-only / pre-open** | Single Sell hero. Buy side shows a "Shop opens soon" tile linking to `/inventory` (teaser). Curated grid hidden. |
| ❌ | ❌ | **Off-season fallback** | Evergreen brand hero + short "how it works" + "Campus Swap runs during spring move-out and summer move-in — check back in the spring." No grid, no live CTAs. |

---

## UX Flow

### Dual mode (pickups on + shop live) — the primary target

1. Visitor lands on `/`.
2. **Nav** (in `layout.html`): logo + wordmark, links `Shop` / `Sell` / `Log in`.
3. **Compact two-door hero** — frosted-glass panels over a tiled inventory-photo background (see "Hero background" below). Panels stack on mobile, sit side by side on desktop:
   - **Buy door** — frosted panel tinted forest-green. Eyebrow `Shop`, heading (placeholder) "Good stuff, secondhand prices", one-line sub aimed at the **general public** (not dorm-specific), small cream button `Browse the shop →` linking to `/inventory`.
   - **Sell door** — frosted panel tinted cream with sage border. Eyebrow `Moving out?`, heading "Sell your stuff", one-line sub "We pick it up, sell it, and pay you. Free pickup, $0 upfront." (no `$65` line), small green button `Start listing →` linking to `become-a-seller`.
   - Buttons are intentionally smaller than the route-A preview but still high-contrast and obviously tappable.
4. **Category chips row** — horizontal, scrollable on mobile. One chip per top-level `InventoryCategory`, each linking into `/inventory` with that category preselected (see Routes). Optional leading `All` chip → `/inventory`.
5. **Curated grid** — dense responsive grid (`repeat(auto-fit, minmax(...))`, target 4-up desktop / 2-up mobile) of `HOMEPAGE_FEATURED_LIMIT` (default **8**) items, auto-selected with category spread from the eligibility pool, pins first (see "Selection logic"). Each card reuses the existing inventory item-card markup. A `See all →` link sits in the section header → `/inventory`.
6. Any card click → `/item/<id>` (existing product page).

### Buyer-only mode (pickups off + shop live)

- Hero collapses to a **single full-width Buy** frosted panel over the inventory mosaic. The Sell door is **not rendered at all**.
- Chips + grid render normally.
- Nav still shows `Sell`, but `become-a-seller` shows the out-of-season state (below).

### Seller-only / pre-open mode (pickups on + shop not live)

- Hero is a **single Sell** band on a **solid brand background** (no mosaic — there are no eligible items yet). The Buy side renders as a muted "Shop opens soon" tile that links to `/inventory` (which is itself in teaser mode).
- Grid is **hidden** (nothing is available to buy yet).

### Off-season fallback (both off)

- Evergreen hero: brand lockup + 2–3 line "how it works" + line: "Campus Swap runs during spring move-out and summer move-in — check back in the spring."
- No grid. CTAs, if any, point to informational pages (`/about`), not the shop or wizard.

### Seller-page seasonal gating (edge case Henry called out)

- **`become-a-seller`**: keeps the interactive room in **all** states.
  - `pickups_on` → normal: room + active `Start listing →` CTA into the wizard.
  - `pickups_on == false` → show an out-of-season banner above the room: "Pickups run during move-out in the spring." The `Start listing` CTA is replaced with an informational/disabled state. Room stays visible.
- **Seller listing wizard routes**: add a guard so that if a user reaches any listing/scheduling step while `pickup_period_active == false`, they're redirected to `become-a-seller` showing "come back in the spring." ("If somehow they do get to a selling page, it should say come back in the spring.")

---

## New / Modified Routes

| Method | Path | Function | Change |
|---|---|---|---|
| `GET` | `/` | `index` | **Modified.** Compute `_homepage_state()`, query curated items, render new `index.html`. Remove waitlist form handling. Ensure no interactive-room block remains on the homepage. |
| `GET` | `/become-a-seller` | `become_a_seller` | **Modified.** Add interactive room (relocated from `index.html`). Add seasonal banner + conditional CTA based on `pickup_period_active`. |
| `POST` | `/admin/item/<id>/toggle-featured` | `admin_item_toggle_featured` | **New.** Toggle `Item.is_featured`. Returns JSON `{success, is_featured}`. Admin-only (`is_admin`). |
| — | seller wizard routes | (existing) | **Modified.** Add `pickup_period_active` guard → redirect to `become-a-seller` when off. (Claude Code: locate the wizard entry/step routes in `app.py` and add the guard at the top of each, or a shared `@before` check.) |
| — | `/inventory` | `inventory` | **No change.** Category chips deep-link using the **existing** filter param. Claude Code: confirm the real param name in `inventory()` (likely `category` or `category_id`) and build chip `href`s accordingly. |

Featured toggle should **also** be wired into the existing admin bulk-edit flow (`admin.html`) as a "Featured" column/checkbox, in addition to the per-item JSON toggle.

---

## Model Changes

| Model | Field | Type | Notes |
|---|---|---|---|
| `Item` (`InventoryItem`) | `is_featured` | `Boolean`, `default=False`, `server_default='0'` | **Pin** flag — admin-pinned items are guaranteed a homepage slot; the rest auto-fills. Not the sole selector (see Selection logic). |

**Migration required** (Flask-Migrate). Non-destructive add with server default; no data backfill needed.

No other model changes. Seasonal logic reads existing `AppSetting` rows. Payout logic, status lifecycle, and Stripe state are untouched.

---

## Template Changes

| Template | Change |
|---|---|
| `index.html` | **Full rewrite.** New season-aware homepage: frosted two-door hero over an inventory-photo mosaic, category chips, curated grid. Extends `layout.html`. Remove waitlist form. Ensure the interactive room is **not** on the new homepage (it belongs on `become-a-seller`). All four season modes branched via the `_homepage_state()` values passed from the view. |
| `become_a_seller.html` | Ensure the **interactive room** lives here (verify current location first — see ambiguity note). Add `pickup_period_active`-conditional banner + CTA state. |
| `_listing_card.html` (new partial) | Extract the existing inventory item-card markup into a shared partial **if one doesn't already exist**, so the homepage grid and `/inventory` render identical cards. If `inventory.html` already uses a card partial, reuse it as-is — do **not** duplicate markup. |
| `layout.html` | Minimal: ensure the nav `Sell` link is always present (its destination handles the season). No structural nav change required. |
| `admin.html` | Add a "Pin to homepage" toggle (star) per item and in bulk edit, wired to `admin_item_toggle_featured` / bulk update. |

**Hero styling:** the photo mosaic + `backdrop-filter` frosted panels + scrim + the solid-band fallback are new CSS — add to `static/style.css` using existing CSS variables for all tints (green/cream/sage), no hardcoded colors. Provide the `@supports not (backdrop-filter: blur(1px))` fallback and a mobile treatment per Business Logic.

**Styling:** Use CSS variables from `static/style.css` only (`--primary`, `--accent`, `--bg-cream`, etc.) — no hardcoded colors. Photos via `url_for('uploaded_file', filename=...)`, never `url_for('static', ...)`. Inline data passed to JS (e.g. toggle target) via `data-*` attributes, never `tojson` in `onclick`.

---

## Business Logic

**`_homepage_state()` helper** (in `app.py`): returns the mode + the two booleans so the template can branch. Derivations as in the state-machine table above.

### Eligibility pool (shared by hero tiles + grid)

Both the hero photo tiles and the foreground grid draw from one pool of items that look clean and are buyable:

```
eligible = (InventoryItem.query.filter_by(
        status='available',
        ai_approved=True,            # required for shop visibility
        ai_photo_enhanced=True,      # has a KEPT AI studio background
        needs_new_photo=False,       # not hidden pending a reshoot
        needs_photo_verification=False,
    ))
```

Rationale: `ai_photo_enhanced` is set `True` when the OpenAI background replacement succeeds and is **cleared back to `False`** when an admin deletes a bad-looking AI cover (via `admin_ai_delete_gallery_photo`). So items whose enhanced backgrounds were removed for looking bad self-exclude — no manual blocklist needed. The uniform white studio background is also what makes the tiled hero read as a cohesive gallery wall under the frosted panels.

### Selection logic — auto + optional pin

`is_featured` is a **pin**, not the sole selector. Selection order:

1. **Pins first:** any eligible item with `is_featured=True`, capped at the limit.
2. **Auto-fill with category spread:** fill remaining slots from the eligible pool using **round-robin across distinct `category_id`** — take the top-ranked item from each category, then loop again for a second per category, until the limit is reached. This guarantees variety (never 8 of the same category) and refills automatically as items sell, so no babysitting.

**Foreground grid ranking** (the 8 shop-preview cards): rank the eligible pool by a **blend of highest value and best savings** — compute, across the pool, a normalized value score from `retail_price` and a normalized savings score from `retail_price - price` (guard nulls/zero retail), and rank by their sum. Then apply the round-robin category spread. Limit `HOMEPAGE_FEATURED_LIMIT` (in `constants.py`, default `8`). Grid only queried/rendered when `shop_live` is true.

**Empty/low pool:** if the eligible pool is smaller than the limit, render what exists; if it's empty, hide the grid section entirely (no broken/empty cards).

### Hero background (frosted-glass over inventory tiles)

- **Tiles:** rendered only when `shop_live` is true. Pull cover photos (`photo_url`, served via `url_for('uploaded_file', ...)`) from the **same eligible pool**, ranked by **highest value (`retail_price` desc)** with category spread (round-robin), limited to `HOMEPAGE_HERO_TILE_LIMIT` (in `constants.py`, default `12`; render fewer on mobile). Pins do not apply to the hero — it's purely top-value-by-category. Overlap with the grid items is acceptable (background vs. foreground).
- **Layout:** a CSS-grid mosaic of the tile images filling the hero band, with a subtle dark/green **scrim** over the photos so the frosted panels stay legible.
- **Frosted panels:** the Buy/Sell doors sit on top as `backdrop-filter: blur(...)` panels with a **semi-opaque brand tint** (green for Buy, cream for Sell) — never plain white, never fully transparent (brand rule: text/logo must sit on a solid-ish color block, not raw photography). The wordmark stays in the solid nav bar above the image, not on the photo.
- **Fallbacks (required):**
  - If the eligible pool is empty or `shop_live` is false, the hero falls back to a **solid brand-color band** (no mosaic) — this is the hero used in seller-only and off-season modes too.
  - `backdrop-filter` is inconsistent across browsers and costly on mobile: ship a graceful degradation where unsupported (solid tinted panel at higher opacity), and consider disabling the live blur on small viewports in favor of a pre-dimmed static treatment.
- **Seasonal:** mosaic hero in dual + buyer-only modes; solid brand hero in seller-only + off-season modes.

**Category chips:** query top-level `InventoryCategory` rows (`parent_id IS NULL`). Each chip links into `/inventory` with the category preselected using the existing filter param.

**Seasonal guards:**
- `index` branches output by mode; never renders the Sell door when `pickups_on` is false.
- `become_a_seller` renders the out-of-season banner + disabled CTA when `pickups_on` is false.
- Seller wizard routes redirect to `become-a-seller` when `pickups_on` is false.

**Admin pin toggle:** `admin_item_toggle_featured` flips `is_featured`, commits, returns JSON. No effect on status, payout, or any Stripe state.

---

## Constraints — do NOT touch

1. **Stripe webhook remains the sole source of truth** for payment/sold state. Nothing here marks items sold or changes payment status.
2. **Payout math unchanged.** Do not reference, store, or display computed payouts on the homepage. No `_get_payout_percentage` changes. The `$65 average payout` line is **removed**, not relocated.
3. **Item status lifecycle unchanged.** `is_featured` is orthogonal to `status`; only items in the eligibility pool (`status='available'` + `ai_approved` + `ai_photo_enhanced` + not `needs_new_photo`) appear, regardless of pin.
4. **Server-rendered only.** Hero/grid/chips are server-rendered; vanilla JS only for the admin pin-toggle fetch and any chip scroll behavior. No React/Vue.
5. **No new AppSetting flags.** Reuse `pickup_period_active` and `shop_teaser_mode` exactly as they exist.
6. **Admin two-tier respected.** Pin toggle gated on `is_admin` (panel access); no super-admin requirement unless that conflicts with the existing item-edit gate, in which case match the existing item-edit gate.
7. **Do not remove or alter the interactive room's behavior** — it must end up intact on `become-a-seller` (verify its current location first).
8. **`/inventory` shop logic untouched** — chips only link in; no change to `inventory()` filtering.
9. **Do not write to `ai_photo_enhanced` or any `ai_*` field** — selection only *reads* it. The AI/photo pipeline owns those fields.

---

## Testing checklist

- [ ] Migration adds `is_featured` with `server_default='0'`; existing rows default to `False`.
- [ ] **Dual mode** (`pickup_period_active=true`, `shop_teaser_mode=false`): both frosted doors render over the mosaic; grid shows selected items; chips link into `/inventory` with correct param.
- [ ] **Buyer-only** (`pickup_period_active=false`, `shop_teaser_mode=false`): Sell door absent; Buy hero full-width over mosaic; grid + chips present.
- [ ] **Seller-only / pre-open** (`pickup_period_active=true`, `shop_teaser_mode=true`): Sell hero on solid band; "Shop opens soon" tile; grid hidden.
- [ ] **Off-season** (both false): evergreen solid-band fallback; no grid; "check back in the spring" copy.
- [ ] Eligibility pool excludes items with `ai_photo_enhanced=False` (e.g. ones whose AI cover was deleted), `needs_new_photo=True`, or not `ai_approved`.
- [ ] Selection: pinned (`is_featured`) eligible items always appear; remaining slots auto-fill with category spread (no single category dominates 8 slots).
- [ ] Grid ranking favors a blend of high `retail_price` and high savings; hero tiles favor highest `retail_price` across categories.
- [ ] When a selected item sells, the slot auto-refills on next load (no empty cards, no babysitting).
- [ ] Empty pool: grid section hidden; hero falls back to solid brand band.
- [ ] `backdrop-filter` fallback verified (unsupported browser → solid tinted panels still legible); mobile treatment acceptable.
- [ ] `become-a-seller` shows the interactive room in all four states.
- [ ] `become-a-seller` shows out-of-season banner + disabled CTA when `pickup_period_active=false`; normal CTA when true.
- [ ] Hitting a seller wizard route with `pickup_period_active=false` redirects to `become-a-seller` out-of-season state.
- [ ] Admin pin toggle (per-item + bulk) flips `is_featured` and reflects on the homepage; no change to status/payout/Stripe; no `ai_*` field is written.
- [ ] `reserve_only_mode=true`: homepage grid still renders; cards link to product page; buy-vs-reserve handled by product page.
- [ ] Waitlist form fully removed; no dead routes/handlers left behind.
- [ ] No hardcoded colors; photos served via `uploaded_file`; no `tojson`-in-`onclick`.
- [ ] Card markup is shared between homepage and `/inventory` (single partial, no duplication).

---

## Cross-reference (do this when the spec is built)

Cross-reference the entire codebase against the files in `@gigaAdminSpec/` and update them to reflect the new state once this spec is complete:
- **CODEBASE.md** — update the `/` (`index`) and `become-a-seller` route notes; the `index.html` / `become_a_seller.html` template descriptions (waitlist removed, room on become-a-seller, season-aware homepage with photo-mosaic frosted hero); add `Item.is_featured`; add `admin_item_toggle_featured`; note the new `_listing_card.html` partial and `_homepage_state()` helper; add `HOMEPAGE_FEATURED_LIMIT` and `HOMEPAGE_HERO_TILE_LIMIT` to the constants reference.
- **HANDOFF.md** — record what was built vs. spec, and any deviations.
- **DECISIONS.md** — log: homepage is a season-driven state machine off `pickup_period_active` + `shop_teaser_mode`; waitlist retired; `$65` claim dropped; buyer audience is general public (not dorm-only); interactive room confirmed to live on `become-a-seller` (reconcile the prior `CODEBASE.md` claim that it was on `index.html`); frosted-glass hero over a tiled mosaic of `ai_photo_enhanced` cover photos; selection = auto + optional pin from the `ai_photo_enhanced` eligibility pool with category round-robin; grid ranked by blended value+savings, hero tiles by highest value.
- **website-feature-log.md** — add the homepage redesign entry.
