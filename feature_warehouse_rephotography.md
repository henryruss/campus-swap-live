# feature_warehouse_rephotography.md

**Owner:** Campus directors (ops)
**Auth:** `_has_ops_access()` throughout (admin OR campus director)
**Namespace:** `/admin/warehouse/rephoto/*`
**Status:** Spec — ready to build

---

## Goal

We are physically walking the UNC warehouse and re-photographing **every item** with three clean shots (front, side, back). Two problems make the current tooling unfit for this:

1. **Storage-unit data is stale.** The crew reorganized every unit (now grouped by category), so the warehouse tab's unit→item mapping no longer matches reality. Browsing by unit is useless for finding the item you're standing in front of.
2. **The current capture path is slow and finicky.** Edit → scroll → add photo → take picture is one photo at a time, over flaky warehouse wifi, with no compression — so it feels junky and throws network/serving errors.

This feature delivers a **search-first, guided three-shot capture flow** for campus directors: search the item you're holding, confirm it by its current cover thumbnail, tap once to go straight to camera, shoot front/side/back with per-photo compression and resilient upload, done. Items that were never logged can be added on the spot from the same screen.

Photos captured here are **dated** (`captured_at`) so a later post-process pass (background removal + hiding pre-campaign photos + promoting a front shot to cover) can act on exactly this batch. **That post-process pass is out of scope here** — this spec only appends new dated photos and stands up the schema for it.

### Non-goals (explicit)
- No background removal in this spec.
- No hiding of old photos and no gallery-display filtering yet (the `is_hidden` column is added but not consumed).
- No cover (`item.photo_url`) changes.
- No changes to the existing `needs_new_photo` / `needs_photo_verification` queues or `replace_photo` route — those serve AI-flagged single replacements and stay as-is.
- No AI text regeneration; appending photos must **not** reset `ai_generated_at` on existing items.

---

## UX Flow

### Entry
Warehouse Floor (`/admin/warehouse`) gets a prominent **"Re-Photograph Items"** button in the header. It links to `GET /admin/warehouse/rephoto`.

The rephoto page shows: a campaign banner ("Re-photography campaign — started Jul 8, 2026. Items re-shot today show a ✓."), a large debounced search box (autofocus), an empty results area, and an **"+ Add an item that isn't listed"** button.

### Path A — Reshoot an existing item (the common case)
1. Director types what they're holding ("couch", "mini fridge", "desk lamp"). Search is debounced 300ms and synonym-expanded (couch → sofa/futon/loveseat/sectional, etc.).
2. Results render as rows: **current cover thumbnail** (so they can eyeball-match a lookalike mini-fridge), short description, category, a ✓ **"Re-shot today"** badge if the item already has a photo from this campaign, and a **Reshoot** button.
3. Director confirms the thumbnail matches the physical item, taps **Reshoot** → full-screen capture modal opens **immediately on the rear camera**, with the item's existing cover thumbnail + description pinned in the header ("Reshooting: Blue mini fridge — not this one? ✕ back to search").
4. Guided capture: prompt **FRONT** → shoot → thumbnail appears with a status dot, auto-advance to **SIDE** → **BACK**. Each shot uploads the instant it's taken (compressed client-side). Any slot can be retaken individually.
5. **Done** appends the photos to the item and returns to the search screen (search box refocused, previous query preserved) so they can immediately find the next item. The reshot item's row now shows the ✓ badge.

### Path B — Add a missing item (never logged)
1. Search returns nothing (or director knows it's not in the system). They tap **"+ Add an item that isn't listed"** (also surfaced inline in the empty-results state as "Don't see it? Add it").
2. This creates a **stub item** immediately (see `create_stub` route) and opens the same capture modal. Order matches the reshoot flow: **capture 3 → then details.**
3. After the three shots, the modal advances to a **details step**: a category grid (required) and a seller picker with the same three modes as Log Item — **Campus Swap internal** (default) / **existing seller** (live search) / **new proxy seller** (name + contact, created at `payout_rate=50`).
4. **Save** writes category + seller and returns to search. The stub is now a normal `pending_valuation` item with photos; **AI autofill will fill title/description/price later** (it is eligible because `ai_generated_at IS NULL`).

### Edge cases
- **Camera denied / non-HTTPS / unsupported:** fall back to a file input with `capture="environment"` (mirrors `_qc_camera_block.html`). The guided front/side/back sequence still applies; each pick uploads immediately.
- **HEIC (iOS):** the client draws the captured/selected image onto a canvas and re-encodes to JPEG, so HEIC is normalized on the way out. Server also validates MIME via `validate_file_upload()`.
- **Upload failure:** each photo retries automatically up to 3× with backoff (0.5s, 1.5s, 3s). On final failure the dot turns red and is tap-to-retry. **Done is blocked** while any photo is in `uploading` or `failed`; a failed photo must succeed or be removed first.
- **Finishing with fewer than 3:** allowed, but Done shows a nudge ("Only 2 of 3 — front / side / back recommended. Save anyway?"). Saving with 0 photos is not allowed (Done disabled until ≥1 success).
- **Wrong lookalike item:** the cover thumbnail is shown in both the result row and the capture header; a "✕ back to search" control abandons without saving.
- **Duplicate reshoot by two directors:** no hard lock; the ✓ badge is the coordination mechanism. Accepted.
- **Add-path abandonment** (stub created, director backs out): the stub remains, owned by the internal Campus Swap account, `pending_valuation`, and flows through AI autofill like any other. Accepted; note in DECISIONS.md.
- **Item with no existing cover** (`photo_url` null): show a neutral placeholder tile in results.

---

## New Routes

All use `_has_ops_access()`. All POSTs include `{{ csrf_token() }}`.

| Method | Path | Function | Description |
|---|---|---|---|
| GET | `/admin/warehouse/rephoto` | `admin_rephoto_page` | Main re-photography page. Search box, results container, Add-item button, campaign banner. Extends `admin_layout.html`. |
| GET | `/admin/warehouse/rephoto/search` | `admin_rephoto_search` | HTML partial (no layout). Param `q`. Synonym-expanded search across short description, long description, and category name. Excludes `status='sold'`. Returns result rows with cover thumbnail, ✓ badge, Reshoot button. Empty state includes the Add-item affordance. |
| POST | `/admin/warehouse/rephoto/add-item` | `admin_rephoto_create_stub` | Create a stub `InventoryItem` for the add path. Returns JSON `{success, item_id}`. |
| POST | `/admin/warehouse/rephoto/<int:item_id>/photo` | `admin_rephoto_add_photo` | Accept ONE compressed photo. Form fields: `photo` (file), `view` (`front`/`side`/`back`), plus CSRF. Creates one `ItemPhoto` with `captured_at`, `view`, computed `sort_order`, `is_hidden=False`. Returns JSON `{success, photo_id, photo_url}`. Shared by both paths. |
| POST | `/admin/warehouse/rephoto/<int:item_id>/details` | `admin_rephoto_set_details` | Add-path only. Set `category_id` (required) and seller (three modes; proxy created at `payout_rate=50`). Returns JSON `{success}`. |
| POST | `/admin/warehouse/rephoto/photo/<int:photo_id>/delete` | `admin_rephoto_delete_photo` | Remove a just-captured photo (used by per-slot "remove" during the session, e.g. to clear a failed/blurry shot). Deletes the file via `photo_storage.delete_photo()` and the row. Returns JSON `{success}`. |

**Reuse, do not recreate:** the existing seller live-search endpoint and the new-proxy-seller creation logic already used by the Log Item modal (`admin/warehouse_log_modal.html`). Reference them; do not fork new copies.

---

## Model Changes

### `ItemPhoto` — add four columns (one migration)

Current model is `id, item_id, photo_url`. Add:

| Column | Type | Notes |
|---|---|---|
| `captured_at` | `DateTime`, nullable | UTC. Set to `datetime.utcnow()` at creation for photos taken through this flow. **Left NULL for all pre-existing rows** — NULL is defined as "legacy / pre-campaign." |
| `sort_order` | `Integer`, `server_default='0'` | Gallery ordering. Existing rows default 0. Gallery renders by `(sort_order, id)`. |
| `view` | `String(10)`, nullable | `'front'` / `'side'` / `'back'` / NULL. NULL for legacy rows. Lets the later post-process pass pick the front deterministically. |
| `is_hidden` | `Boolean`, `server_default=sa.false()`, `default=False` | **Added now, not consumed yet.** The post-process spec will use it to hide pre-campaign photos. Nothing in this spec reads it. |

**Migration notes:**
- Standard Postgres Alembic (no `batch_alter_table`, no SQLite syntax — per CLAUDE.md).
- Chain `down_revision` onto the **current migration head** (verify with `flask db heads`; do not assume `c3d4e5f6a7b8` is still latest).
- **No data backfill.** Do not UPDATE existing rows — leave `captured_at` NULL and `sort_order` at its server_default. Backfilling thousands of production rows is unnecessary because NULL `captured_at` already reads as "pre-campaign" everywhere it matters.
- Update the `ItemPhoto` model in `models.py` to declare all four columns.

### No changes to `InventoryItem`
The add path reuses existing fields only (`is_quick_capture`, `captured_by_id`, `category_id`, `seller_id`, `status`).

### AppSetting
`rephoto_campaign_start` — string `'2026-07-08'`. Read via `AppSetting.get('rephoto_campaign_start', '2026-07-08')`. Used for the ✓ badge boundary. Fixed for this campaign; adjustable later without a deploy. No migration needed (AppSetting is a runtime key-value store).

---

## Template Changes

### New
- **`templates/admin/rephoto.html`** — extends `admin_layout.html`. Campaign banner, autofocused debounced (300ms) search box posting `q` to `/admin/warehouse/rephoto/search` and injecting the partial into a results div, and the "+ Add an item that isn't listed" button (triggers `create_stub` → opens capture modal in add mode). Includes the capture modal partial. Uses CSS variables only.
- **`templates/admin/rephoto_search_results.html`** — partial (no layout). Result rows: cover thumbnail via `url_for('uploaded_file', filename=item.photo_url)` (placeholder if null), short description, category name, ✓ "Re-shot today" badge when the item has a photo with `captured_at >= campaign_start`, and a **Reshoot** button carrying `data-item-id`, `data-item-label`, `data-cover-url`. Empty-results state shows "Don't see it? Add it" wired to the same add-item action.
- **`templates/admin/rephoto_capture_modal.html`** — full-screen guided capture modal (no layout; included by `rephoto.html`). Owns the front/side/back state machine, per-photo status dots, per-slot retake/remove, the Done nudge, and — for the add path — the trailing details step (category grid + three-mode seller picker). All camera logic lives here (see Business Logic for the exact contract). Do **not** overload the shared `_qc_camera_block.html`; this is a separate, purpose-built component so existing QC / Log Item / replace-photo usages are untouched.

### Modified
- **`templates/admin/warehouse.html`** — add the "Re-Photograph Items" button to the header, linking to `/admin/warehouse/rephoto`. No other changes.

---

## Business Logic

### Synonym-expanded search (`admin_rephoto_search`)
- Tokenize `q`, lowercase. For each token, expand via a module-level `REPHOTO_SYNONYMS` dict into an OR-group. Match case-insensitively (`ILIKE '%term%'`) against `InventoryItem.description`, `InventoryItem.long_description`, and `InventoryCategory.name` (joined).
- Exclude `status == 'sold'`. Include all other statuses (`pending_valuation`, `needs_info`, `available`, `rejected`) — Henry confirmed all items, including ones not tied to a live listing.
- Order: items **without** a campaign photo first (so un-done items surface above ✓ ones), then by most recent `date_added`. Cap at ~40 rows; no pagination (matches existing warehouse search behavior).

Seed `REPHOTO_SYNONYMS` from the standard categories (director-expandable later):
```python
REPHOTO_SYNONYMS = {
    "couch": ["couch", "sofa", "futon", "loveseat", "sectional", "settee"],
    "sofa": ["couch", "sofa", "futon", "loveseat", "sectional"],
    "fridge": ["fridge", "mini fridge", "minifridge", "refrigerator", "cooler"],
    "refrigerator": ["fridge", "mini fridge", "refrigerator"],
    "microwave": ["microwave", "micro"],
    "rug": ["rug", "carpet", "mat", "runner"],
    "headboard": ["headboard", "bed frame", "bedframe", "footboard"],
    "mattress": ["mattress", "bed", "topper", "futon"],
    "tv": ["tv", "television", "monitor", "screen"],
    "heater": ["heater", "space heater", "radiator"],
    "ac": ["ac", "a/c", "air conditioner", "fan", "cooling"],
    "lamp": ["lamp", "light", "lighting", "floor lamp", "desk lamp"],
    "desk": ["desk", "table", "workstation"],
    "chair": ["chair", "stool", "seat", "recliner"],
    "shelf": ["shelf", "shelving", "bookcase", "bookshelf", "storage"],
    "dresser": ["dresser", "drawers", "chest", "nightstand", "bureau"],
}
```
If a token isn't a key, search it literally. Expansion is one level (no recursion).

### Stub creation (`admin_rephoto_create_stub`)
- Create `InventoryItem`: `status='pending_valuation'`, `is_quick_capture=True`, `captured_by_id=current_user.id`, `seller_id=<internal Campus Swap account id>` (`internal@campusswap.com`, `is_internal_account=True`), `category_id=NULL`, `date_added=utcnow`.
- Leave `ai_generated_at` NULL so AI autofill picks it up.
- Return `{success: true, item_id}`.

### Photo add (`admin_rephoto_add_photo`) — the reliability core
Server side:
1. Validate via `validate_file_upload()` (type/size gate; the existing 413 path still applies as a backstop).
2. Save through `photo_storage` (the `S3Storage` class, which applies the `uploads/` key prefix — do not bypass it). Filename convention: `rephoto_<item_id>_<view>_<uuid8>.jpg`. This convention lets the later background-removal backfill identify this batch by filename.
3. Create `ItemPhoto`: `item_id`, `photo_url=<saved filename>`, `captured_at=datetime.utcnow()`, `view=<front|side|back>`, `is_hidden=False`, `sort_order = (max existing sort_order for this item, default -1) + 1` so new photos append at the end of the gallery (front/side/back get consecutive increasing values in capture order).
4. **Do not** touch `item.photo_url` (cover), `item.status`, or `item.ai_generated_at`.
5. Defense-in-depth downscale: before saving, run the incoming file through a server-side `_downscale_image()` helper (Pillow: if longest edge > 1600px, resize preserving aspect; re-encode JPEG quality 85; strip EXIF). The client already compresses; this bounds the rare case where the fallback file input sends a full-res original.
6. Return `{success: true, photo_id, photo_url: url_for('uploaded_file', filename=...)}`.

Client side (in `rephoto_capture_modal.html`):
- Capture to a `<canvas>`, downscale to **max 1600px longest edge**, export **JPEG quality 0.82** as a Blob.
- Upload each photo the **instant it is taken**, as its own `multipart/form-data` POST (fields: `photo`, `view`, CSRF) — never batch all three.
- **Retry** up to 3× with backoff 0.5s / 1.5s / 3s on network error or non-2xx.
- **Per-photo status dot:** grey `pending` → pulsing `uploading` → green `done` → red `failed` (tap to retry).
- **Done** enabled once ≥1 photo is `done`; blocked while any is `uploading`/`failed`; nudge if `done` count < 3.

### Details (add path only, `admin_rephoto_set_details`)
- Require `category_id` (reject with 400 JSON if missing).
- Seller modes reuse Log Item logic exactly: internal (no change needed), existing (seller-search endpoint), new proxy (`payout_rate=50`, `is_proxy_account=True`).
- Do not set storage (`storage_location_id` stays NULL — units are being batch-reorganized by category separately).
- Return `{success: true}`.

### ✓ "Re-shot today" badge
An item shows the badge when it has at least one `ItemPhoto` with `captured_at >= campaign_start` (parse `rephoto_campaign_start` as a date; compare against UTC `captured_at`). Compute once per search result set (single query — e.g. a subquery/exists per item, or prefetch item_ids with a campaign photo). This is the multi-person coordination signal.

---

## Constraints — do NOT touch

- **Server-rendered only.** The rephoto page is a normal page; capture/upload/search use `fetch` for the JSON/partial exchanges (consistent with the existing warehouse auto-save pattern). No SPA framework.
- **Never hardcode colors** — CSS variables from `static/style.css` only.
- **Do not modify** `_qc_camera_block.html`, `crew_quick_capture`, `admin_item_replace_photo`, or the `needs_new_photo` / `needs_photo_verification` queues.
- **Do not change** `item.photo_url` (cover) anywhere in this feature.
- **Do not reset** `ai_generated_at` when appending photos to an existing item.
- **Do not read/consume** `is_hidden` for display yet — it is scaffolding for the post-process spec.
- **Do not backfill** existing `ItemPhoto` rows in the migration.
- **Do not bypass** `photo_storage`'s `S3Storage` (the `uploads/` prefix must be applied by that class).
- **Photo serving** stays `url_for('uploaded_file', filename=...)` — never a static path.
- **Timestamps** stored UTC; the campaign-start comparison and any display use Eastern (`_now_eastern()`).
- **All new schema** via a single Flask-Migrate migration chained onto the current head. No direct DB edits.
- Keep additions grouped with related warehouse routes/templates; no unrelated refactors of the upload system beyond the scoped `_downscale_image()` helper (see optional item below).

### Optional, same session (only if low-risk): general upload hardening
Wiring `_downscale_image()` into the shared save path used by `add_item` / onboarding so *all* uploads get bounded would help sitewide mobile performance. Treat as a clearly separated, second commit — do not entangle it with the rephoto routes, and do not change any upload's external behavior beyond size/quality. Skip if it can't be done without touching the core upload contract.

---

## Testing Checklist

### Migration & model
- [ ] `flask db upgrade` applies cleanly on a copy of prod; `ItemPhoto` has `captured_at`, `sort_order`, `view`, `is_hidden`.
- [ ] Existing `ItemPhoto` rows have `captured_at IS NULL`, `sort_order = 0`, `view IS NULL`, `is_hidden = false`.
- [ ] `flask db downgrade` cleanly drops the four columns.

### Entry & search
- [ ] "Re-Photograph Items" button on `/admin/warehouse` links to `/admin/warehouse/rephoto`.
- [ ] Page loads for a campus director (not just super admin); blocked for a plain worker/seller.
- [ ] Search "couch" returns items whose description/category mention sofa, futon, loveseat, or sectional.
- [ ] Search "fridge" returns mini fridge / refrigerator items.
- [ ] `sold` items never appear in results.
- [ ] Each result row shows a cover thumbnail (or placeholder if `photo_url` null), description, and category.
- [ ] Debounce works (no request per keystroke).

### Reshoot flow
- [ ] Tapping Reshoot opens the camera immediately (rear camera on HTTPS mobile), with the item's cover + label pinned in the header.
- [ ] Prompts advance Front → Side → Back; each shot uploads immediately.
- [ ] A photo appears in DB as `ItemPhoto` with correct `view`, `captured_at ≈ now`, `is_hidden=false`, and `sort_order` greater than any pre-existing photo on that item.
- [ ] `item.photo_url` (cover) is unchanged after reshoot.
- [ ] `item.ai_generated_at` is unchanged after reshoot.
- [ ] Per-slot retake replaces only that slot (old blob removed, new uploaded).
- [ ] "✕ back to search" abandons with no new photos saved.
- [ ] Done returns to search with the query preserved; the item now shows the ✓ badge.
- [ ] Finishing with 2 photos shows the nudge; confirming saves 2; Done is disabled at 0.

### Reliability
- [ ] Captured photos are compressed client-side (verify uploaded file is ~200–500KB, longest edge ≤1600px, not multi-MB).
- [ ] Simulated network drop on one photo: it retries, dot goes red on final failure, Done is blocked until it succeeds or is removed.
- [ ] File-input fallback appears when camera is denied / on non-HTTPS; the guided sequence still works.
- [ ] An iOS HEIC capture is stored as a valid JPEG.
- [ ] Server `_downscale_image()` bounds an oversized fallback-input file even without client compression.

### Add-missing-item flow
- [ ] "+ Add an item that isn't listed" (and the empty-state variant) creates a stub and opens the camera.
- [ ] Stub is `pending_valuation`, `is_quick_capture=True`, `captured_by_id=current director`, seller = internal Campus Swap, `category_id` NULL, `ai_generated_at` NULL.
- [ ] After 3 shots, details step requires a category; saving without one is rejected.
- [ ] Existing-seller live search and new-proxy (payout_rate=50) both attach correctly.
- [ ] `storage_location_id` remains NULL.
- [ ] The new item is eligible for and picked up by AI autofill.
- [ ] Abandoning after stub creation leaves an internal-owned pending item (no crash, no orphaned-file leak beyond the item itself).

### Badge / multi-person
- [ ] ✓ badge appears only for items with a photo `captured_at >= 2026-07-08`.
- [ ] Legacy-only items (all photos `captured_at` NULL) show no badge.
- [ ] Two directors reshooting different items both see live ✓ updates on refresh.

### Regression
- [ ] `_qc_camera_block.html`-based flows (crew quick capture, Log Item, replace-photo) still work.
- [ ] `replace_photo` and the `needs_new_photo` / `needs_photo_verification` queues are unchanged.
- [ ] Product pages / galleries still render (new columns don't break existing ordering; `(sort_order, id)` keeps legacy order stable).

---

## Cross-reference update (do this when the build is complete)

Cross-reference the entire codebase against the `gigaAdminSpec/` docs and update them to reflect the shipped state:
- **CODEBASE.md** — add the six `/admin/warehouse/rephoto/*` routes, the four new `ItemPhoto` columns, the three new templates, the `warehouse.html` modification, `REPHOTO_SYNONYMS`, and `_downscale_image()`.
- **HANDOFF.md** — new "Warehouse Re-Photography" section: what shipped, migration revision id, any deviations from this spec, and the `rephoto_campaign_start` AppSetting.
- **DECISIONS.md** — record: search-first over unit-first (stale unit data), `captured_at` NULL = legacy (no backfill), `is_hidden` added-but-not-consumed (deferred to post-process), client + server dual compression, add-path stub defaults to internal account, proxy at 50%.
- **website-feature-log.md** — one-line entry with the route list and date.
