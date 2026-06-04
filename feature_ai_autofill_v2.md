# Feature Spec: AI Autofill v2 — Photo Enhancement + Seller Data Preservation + Auto-Trigger

## Goal

Three interconnected improvements to the existing AI autofill pipeline:

1. **Preserve original seller data.** The current approval flow overwrites `description` and `long_description` with AI-generated content, destroying the seller's original text permanently. Add permanent `seller_description` / `seller_long_description` fields so we always have a fallback.

2. **Photo enhancement.** Before generating text, replace each item's cover photo with a studio-quality version (clean white background, good lighting) using the OpenAI image edit API. The original seller photo is preserved as a gallery photo. This runs as part of the same background job as text generation.

3. **Auto-trigger on item submission.** When a seller completes onboarding and their item is created, fire a background AI generation job immediately so the item arrives in the admin review queue pre-filled — no manual "Run" needed for new items.

---

## Background: Database Reset Required Before Deploy

Before this spec is deployed, the following SQL must be run in the Render psql shell **after** the migration has applied (which adds the `seller_description` / `seller_long_description` columns):

```sql
-- Step 1: Snapshot current live content into seller_description for already-approved items
-- (their original seller text was overwritten; this preserves what's there now as a fallback)
UPDATE inventory_item
SET seller_description = description,
    seller_long_description = long_description
WHERE ai_approved = TRUE AND seller_description IS NULL;

-- Step 2: Reset all AI flags so every item re-runs through the new pipeline
-- Items stay visible in shop (live description/price fields untouched)
UPDATE inventory_item
SET ai_generated_at = NULL,
    ai_review_pending = FALSE,
    ai_approved = FALSE,
    ai_description = NULL,
    ai_long_description = NULL,
    ai_price = NULL,
    ai_retail_price = NULL,
    ai_photo_enhanced = FALSE
WHERE ai_generated_at IS NOT NULL
   OR ai_approved = TRUE
   OR ai_review_pending = TRUE;
```

**Important:** After step 2, `ai_approved=FALSE` means all items are hidden from the shop (gated by `ai_approved=True`). Claude Code must implement a **temporary visibility fallback**: items with existing non-null `description` and `price > 0` that have `ai_approved=FALSE` but also have non-null `seller_description` (indicating they were previously approved) should remain visible until re-approved. See Business Logic section for the exact shop visibility rule change.

---

## Model Changes

### InventoryItem — new fields

```
seller_description (Text, nullable)
  — Original seller-submitted title. Populated at item creation (onboard + add_item routes).
  — Never overwritten after initial write. Used as fallback if AI data is reset.

seller_long_description (Text, nullable)
  — Original seller-submitted long description. Same rules as above.

ai_photo_enhanced (Boolean, default False, server_default='0')
  — Set True after photo enhancement runs successfully for this item.
  — Used to skip re-enhancement on items that already have a studio photo.
  — Reset to False along with other ai_* fields when doing a full reset.
```

**Migration required.** Three new nullable columns on `inventory_item`. No defaults that affect existing rows.

---

## Phase 1: Seller Data Preservation

### Changes to onboarding route (`onboard_submit` or equivalent final onboard step)

When a new `InventoryItem` is created during onboarding, immediately after creation:

```python
item.seller_description = item.description
item.seller_long_description = item.long_description
```

This runs once at creation. Never touch these fields again anywhere in the codebase.

### Changes to `add_item` route

Same treatment — when item is saved via `add_item`, copy description fields to seller_* fields.

### Changes to `edit_item` route

Do NOT update `seller_description` or `seller_long_description` when a seller edits their item. The seller fields capture the original submission only. If the seller edits their title, the live `description` field updates normally, but `seller_description` stays as the original. (This is intentional — we want the original as a permanent record, not a rolling update.)

---

## Phase 2: Photo Enhancement

### New env var required on Render
```
OPENAI_API_KEY  — OpenAI API key for image editing
```

### How photo enhancement works

The OpenAI Images API edit endpoint accepts an image and a prompt, and returns a new image with the background/environment replaced while preserving the subject.

**API call:**
- Endpoint: `POST https://api.openai.com/v1/images/edits`
- Model: `gpt-image-1`
- Input: the item's current cover photo (downloaded from S3/disk)
- Prompt: see below
- Output size: `1024x1024`
- Response format: `b64_json`

**Enhancement prompt (use exactly this):**
```
Professional product photography of this item only. Pure white background, 
white floor seamlessly meeting the wall, soft even studio lighting with no 
harsh shadows. The item should be centered and fill most of the frame. 
Remove any power cords, cables, or background clutter not part of the item itself. 
Do not add any text, watermarks, or props. Neutral, clean, marketplace-ready.
```

### Photo enhancement flow per item

1. Download the item's current `photo_url` from disk (`/var/data/<filename>`) or S3 as applicable — use the existing `photo_storage` module helpers.
2. Call OpenAI image edit API with the prompt above.
3. On success:
   a. Save the original photo as an `ItemPhoto` gallery record (so it's preserved and visible in the gallery carousel).
   b. Decode the base64 response, save as a new file (filename pattern: `ai_enhanced_<item_id>_<timestamp>.jpg`).
   c. Set `item.photo_url` to the new filename.
   d. Set `item.ai_photo_enhanced = True`.
4. On failure (API error, timeout, bad response):
   - Log the error, skip this item's photo enhancement.
   - Proceed with text generation using the original photo (don't block text gen on photo failure).
   - Do NOT set `ai_photo_enhanced = True`.
   - DO set `ai_generated_at` as usual (error sentinel still applies).

### Eligibility for photo enhancement

An item is eligible for photo enhancement if:
- `ai_photo_enhanced = False` (or NULL)
- Has a non-null `photo_url`
- Is not already in the enhancement queue (job is running)

Items with `ai_photo_enhanced = True` skip the photo step and go straight to text generation when re-run.

### File storage

Enhanced photos are stored the same way as all other item photos — via the existing `photo_storage` module. Use `photo_storage.save_photo(filename, data)` or equivalent. Do not introduce new file handling logic.

---

## Phase 3: Updated Text Generation Prompt

### Problems with the current prompt
1. Uses dorm-specific language ("perfect for a dorm room," "college student," etc.)
2. Hallucinates secondary items visible in the background as part of the listing
3. Ignores the seller's title as a grounding input

### Updated generation prompt

The existing generation prompt in `admin_ai_generate_run` (or wherever the Claude API call is constructed) must be updated. Replace the current prompt with:

```
You are writing product listings for a secondhand marketplace. Buyers are general consumers — not specifically college students. Never mention dorms, dorm rooms, college, campus, or students.

You are looking at a photo of a secondhand item being sold. The seller has titled this item: "{seller_description}". Use that title as the authoritative source for what is being sold. Do not add, invent, or describe any other objects visible in the photo that are not the primary item described in the seller's title.

Generate a product listing with:

TITLE: A clean, factual title (max 60 chars). Use the seller's title as your primary input. Include brand name if visible. No punctuation at the end.

DESCRIPTION: 2-3 sentences. Describe the item's key features, condition, and what makes it worth buying. Write for a general buyer. Do not mention dorms, college, or campus. Do not describe objects that are not the item being sold.

PRICE: Suggest a fair secondhand price in USD as a number only (no $ sign). Base it on condition and typical resale value.

RETAIL: Estimate the original retail price as a number only. This should be the typical new retail price for this type of item.

Respond ONLY in this exact format with no other text:
TITLE: ...
DESCRIPTION: ...
PRICE: ...
RETAIL: ...
```

The `{seller_description}` placeholder is filled with `item.seller_description` if set, otherwise `item.description` (fallback for items that pre-date this feature).

### Em-dash stripping

Keep the existing logic that strips em-dashes from all AI output. Extend it to also strip en-dashes used as sentence separators (` – ` → ` `).

---

## Phase 4: Auto-Trigger on Item Submission

### How it works

When a seller completes the onboarding wizard and their item is committed to the database, fire a single-item background AI generation job. This is the same threading pattern used by the batch job, scoped to one item.

### Where to add the trigger

In the final onboarding submission route (wherever `InventoryItem` is created and committed to the DB during onboarding), after `db.session.commit()`, add:

```python
# Fire background AI generation for this item immediately
threading.Thread(
    target=_run_ai_generation_single,
    args=(app._get_current_object(), item.id),
    daemon=True
).start()
```

### New helper function: `_run_ai_generation_single(app, item_id)`

Extract a single-item version of the existing batch generation logic:

```python
def _run_ai_generation_single(app, item_id):
    with app.app_context():
        item = InventoryItem.query.get(item_id)
        if not item or item.ai_generated_at is not None:
            return  # Already processed or doesn't exist
        _process_single_item_ai(item)  # shared logic used by batch job too
```

The actual generation logic (`_process_single_item_ai`) should be refactored out of the batch loop so it's shared between the batch runner and this single-item trigger. No duplication.

### Does this also run photo enhancement?

Yes — the single-item trigger runs the full pipeline: photo enhancement first, then text generation. Same order as the batch job.

### What if the item has no photo yet?

Items created during onboarding always have at least one photo before submission (the wizard enforces this). If `photo_url` is somehow null, skip photo enhancement and proceed with text generation only.

### Also trigger on `add_item` (non-onboarding upload)

The `add_item` route (used by returning sellers adding a second item) should also fire the single-item trigger after item creation. Same pattern.

---

## Changes to the `/admin/ai/generate` Page

### UI additions

The existing generation page at `/admin/ai/generate` needs two additions:

1. **Photo enhancement toggle:** A checkbox (default: checked) labeled "Enhance cover photos (OpenAI)". When unchecked, the batch job skips photo enhancement and only runs text generation. Useful if you want to re-run text only without touching photos.

2. **Updated eligible count:** The stats section already shows "X items eligible." Update the eligibility query to count separately:
   - Items eligible for photo enhancement: `ai_photo_enhanced = False AND photo_url IS NOT NULL AND ai_generated_at IS NULL`
   - Items eligible for text only (already enhanced): `ai_photo_enhanced = True AND ai_generated_at IS NULL`

3. **Progress bar labels:** The existing progress bar shows "X / Y completed." Add a secondary label during the photo step: "Enhancing photos... (X / Y)" before switching to "Generating descriptions... (X / Y)" during text gen. This requires the status polling endpoint to return a `phase` field: `'photo'` | `'text'` | `'done'`.

### Updated status polling response

`GET /admin/ai/generate/status` should add to its JSON response:
```json
{
  "phase": "photo" | "text" | "done",
  ...existing fields...
}
```

---

## Shop Visibility Rule Change

**Current rule:** Item appears in shop if `ai_approved=True AND needs_new_photo=False AND status != 'rejected' AND price > 0`

**Updated rule (temporary, during reset period):**
```python
# Item is visible if:
# (a) ai_approved = True (normal path), OR
# (b) seller_description IS NOT NULL AND price > 0 AND status = 'available'
#     (previously-approved item awaiting re-review after pipeline reset)
```

This ensures the 137 previously-approved items stay visible while they queue up for re-processing. Once an item is re-approved through the new pipeline, condition (a) takes over and condition (b) becomes irrelevant.

**Important:** This fallback only applies to items with `seller_description IS NOT NULL`. Newly submitted items (where `seller_description` was just written at submission time) should NOT be visible until `ai_approved=True`. The distinction: `seller_description` being set before the pipeline reset = previously approved item. `seller_description` being set at submission = brand new item.

This is a subtle but important distinction. Implement it as:

```python
previously_approved_fallback = and_(
    InventoryItem.seller_description.isnot(None),
    InventoryItem.price > 0,
    InventoryItem.status == 'available',
    InventoryItem.ai_approved == False,
    # Only items that had ai_generated_at reset (were previously processed)
    # We can use ai_photo_enhanced=False as a proxy since reset sets it False
    # but seller_description IS NOT NULL distinguishes old vs new
)
```

Actually, the cleanest way: add a one-time boolean flag `was_previously_approved` (Boolean, default False) set by the reset SQL, and use that as the fallback gate. This is unambiguous and doesn't rely on inference.

**Revised approach — add one more migration field:**

```
was_previously_approved (Boolean, default False, server_default='0')
```

In the reset SQL (step 2), add:
```sql
UPDATE inventory_item
SET was_previously_approved = TRUE
WHERE ai_approved = TRUE;  -- run this BEFORE the reset step that sets ai_approved=FALSE
```

Shop visibility query:
```python
visible = or_(
    and_(InventoryItem.ai_approved == True, InventoryItem.needs_new_photo == False),
    and_(InventoryItem.was_previously_approved == True, InventoryItem.price > 0,
         InventoryItem.status == 'available', InventoryItem.needs_new_photo == False)
)
```

Once an item goes through the new pipeline and gets `ai_approved=True`, the first condition takes over. `was_previously_approved` becomes a permanent historical flag (useful for reporting anyway — "was this item approved before the photo enhancement rollout?").

---

## New Routes

| Method | Path | Function | Description |
|--------|------|----------|-------------|
| No new routes required | — | — | All changes are to existing routes + background job logic |

The existing `/admin/ai/generate/run`, `/admin/ai/generate/status`, and `/admin/ai/generate/cancel` routes are modified in place.

---

## Template Changes

### `admin/ai_generate.html`
- Add photo enhancement toggle checkbox above the Run button
- Update progress bar to show phase label ("Enhancing photos..." vs "Generating descriptions...")
- Update eligible count display to show photo-eligible vs text-only counts separately

### `admin/ai_review_detail_partial.html`
- Add a small badge/indicator on the cover photo if `ai_photo_enhanced=True` — e.g., a subtle "✨ Enhanced" chip in the corner of the cover photo thumbnail. Helps admin know which photos have been AI-processed vs are still original seller photos.

No other template changes required.

---

## Business Logic & Edge Cases

### What if OpenAI API key is not set?
If `OPENAI_API_KEY` env var is absent, skip photo enhancement silently and proceed with text generation only. Log a warning. Do not crash the job.

### What if the cover photo is already enhanced (`ai_photo_enhanced=True`)?
Skip photo enhancement, go straight to text generation. This allows re-running text without re-processing photos.

### What if the same photo would be added to gallery twice?
Before adding the original photo as an `ItemPhoto` gallery record, check if an `ItemPhoto` with that `photo_url` already exists for this item. If so, skip adding it (idempotent).

### What about gallery photos (ItemPhoto records) — are those enhanced too?
No. Cover photo only. Gallery photos remain as-is (original seller uploads). This is intentional — gallery photos provide real-world context that buyers value.

### Rate limiting / API failures
Wrap each OpenAI call in a try/except. On any exception (rate limit, timeout, API error), log the error and skip photo enhancement for that item. Continue to text generation. The item's `ai_generated_at` is still set (error sentinel) so it won't infinite-retry on the photo step. To force a photo retry, a super admin can reset `ai_photo_enhanced=False` and `ai_generated_at=NULL` for that specific item via the psql shell.

### Auto-trigger concurrency
If a seller submits an item and the batch job is also running at the same time, the `ai_generated_at IS NOT NULL` guard prevents double-processing. Whichever thread picks up the item first sets `ai_generated_at` immediately as its first DB write, blocking the other.

### Seller_description for quick-capture items
Quick-capture items (`is_quick_capture=True`) are created by drivers, not sellers. Their `description` and `long_description` come from the mover's note. Set `seller_description = item.description` at creation time just like regular items — it's the "original" data regardless of who entered it.

---

## Migration Summary

Four new fields, one migration:

```
inventory_item:
  + seller_description (Text, nullable)
  + seller_long_description (Text, nullable)  
  + ai_photo_enhanced (Boolean, default False, server_default='0')
  + was_previously_approved (Boolean, default False, server_default='0')
```

Migration name suggestion: `add_seller_data_preservation_and_photo_enhancement`

---

## Constraints — Do Not Touch

- Do not modify the `replace_photo` route or the Photo Verification Queue flow — those handle admin-initiated manual photo replacement and are separate from this pipeline.
- Do not modify `admin_ai_approve` — the approval flow that writes staged fields to live fields is unchanged. Only the generation step (what goes into the staged fields) changes.
- Do not modify the existing batch job threading pattern, job_id tracking, or cancel mechanism — extend it, don't replace it.
- Do not change how `retail_price` is floored to ensure ≥40% savings — that logic is correct and stays.
- Do not touch `needs_new_photo` or `needs_photo_verification` flags — those are for the manual warehouse photo replacement workflow and are orthogonal to this feature.
- `seller_description` and `seller_long_description` are write-once at item creation. No route should ever update them after that point.

---

## Reset SQL (Final Version)

Run in Render psql shell after migration deploys:

```sql
-- Step 1: Mark previously approved items for visibility fallback
UPDATE inventory_item
SET was_previously_approved = TRUE
WHERE ai_approved = TRUE;

-- Step 2: Snapshot current live content into seller_description
-- (for the 137 approved items whose original seller text was overwritten)
UPDATE inventory_item
SET seller_description = description,
    seller_long_description = long_description
WHERE was_previously_approved = TRUE AND seller_description IS NULL;

-- Step 3: Reset all AI pipeline state — items stay visible via was_previously_approved
UPDATE inventory_item
SET ai_generated_at = NULL,
    ai_review_pending = FALSE,
    ai_approved = FALSE,
    ai_photo_enhanced = FALSE,
    ai_description = NULL,
    ai_long_description = NULL,
    ai_price = NULL,
    ai_retail_price = NULL
WHERE ai_generated_at IS NOT NULL
   OR ai_approved = TRUE
   OR ai_review_pending = TRUE;
```

Verify counts after running:
```sql
SELECT 
  COUNT(*) FILTER (WHERE was_previously_approved = TRUE) as fallback_visible,
  COUNT(*) FILTER (WHERE ai_generated_at IS NULL) as eligible_for_run,
  COUNT(*) FILTER (WHERE ai_approved = TRUE) as approved
FROM inventory_item;
-- Expected: fallback_visible=137, eligible_for_run=256 (all items), approved=0
```

---

## Deploy Sequence

1. Write and test migration locally against local Postgres snapshot
2. Push to Render → release command runs `flask db upgrade` automatically
3. Confirm migration applied: check Render logs for migration ID
4. Run reset SQL in Render psql shell (3 steps above)
5. Run verify query to confirm counts
6. The new autofill pipeline is live — new item submissions auto-trigger; batch run available for the existing 256 items
