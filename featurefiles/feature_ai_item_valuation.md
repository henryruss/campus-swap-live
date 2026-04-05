# Feature Spec: AI Item Valuation

## Goal
When a seller submits an item, automatically run an AI lookup that identifies the product, researches its retail price, factors in condition and visible wear from photos, and stores a suggested resale price and description alongside the item. Admins see this research pre-loaded in the approval queue — no waiting, no manual Googling. If the AI can't confidently identify the product, it says so and stays out of the way.

---

## How It Works — High Level

1. Seller submits item → existing submission logic runs as normal
2. Immediately after the item is saved to the database, a background AI lookup is triggered
3. The lookup sends Claude the item's photos, category, condition, and seller description
4. Claude searches the web, identifies the product if possible, and returns a structured result
5. The result is stored on the item record
6. When the admin opens the approval queue, the AI panel is already populated and ready

The AI result is stored permanently on the item — it does not re-run every time the admin opens the item. A manual re-run button is available in the approval queue for cases where the seller updates their photos.

---

## UX Flow

### Seller Side
No change to the seller experience. The AI lookup happens server-side after submission. The seller sees the same confirmation screen they always have.

### Admin Side — Approval Queue (`/admin/approve`)

Each item in the approval queue gains an **AI Research Panel** displayed alongside the existing approval form. The panel has two states:

**State 1 — Processing**
Shown briefly if the admin opens the item before the AI lookup has completed (should be rare since it runs at submission time):
- A subtle loading indicator: *"AI research in progress..."*
- No other content until complete

**State 2 — Result Found**
Shown when Claude successfully identified the product:

```
┌─────────────────────────────────────────┐
│  AI Research                    [Re-run] │
│─────────────────────────────────────────│
│  Product                                │
│  Frigidaire EFRF696-AMZ Mini Fridge     │
│                                         │
│  Retail Price                           │
│  $129.99 new on Amazon                  │
│  [View on Amazon ↗]                     │
│                                         │
│  Suggested Resale Price                 │
│  $58                                    │
│  "Retails for $130 new. Condition rated │
│   Good — minor scuffs visible on left   │
│   side panel. Suggested at ~45% of      │
│   retail for used condition."           │
│                                         │
│  [Use this price →]                     │
└─────────────────────────────────────────┘
```

- **"Use this price" button:** Fills the price input field in the approval form with the suggested price. Does not auto-save — admin still clicks Approve manually.
- **"View on [retailer]" link:** Opens the source URL in a new tab so admin can verify
- **"Re-run" button:** Triggers a fresh AI lookup for this item (useful if seller uploaded better photos after a "needs info" request). Replaces the existing result on success.

**State 3 — Unknown Item**
Shown when Claude could not confidently identify the product:

```
┌─────────────────────────────────────────┐
│  AI Research                    [Re-run] │
│─────────────────────────────────────────│
│  Could not identify product.            │
│  Price and description not available.   │
└─────────────────────────────────────────┘
```

- Unobtrusive grey styling — does not draw attention or slow the admin down
- "Re-run" button still available

**Description Panel — Side by Side**
Below the AI research panel (or adjacent to the description field in the approval form), show both descriptions:

```
┌──────────────────────┬──────────────────────┐
│  Seller's Description│  AI Description      │
│──────────────────────│──────────────────────│
│  "Good mini fridge,  │  "Frigidaire 3.2 cu  │
│   works great, only  │   ft compact fridge  │
│   used one year"     │   in good condition. │
│                      │   Ideal for dorm or  │
│                      │   office use. Minor  │
│                      │   cosmetic wear."    │
│                      │                      │
│                      │  [Use this ↗]        │
└──────────────────────┴──────────────────────┘
```

- **"Use this" button** on the AI description side: Copies the AI description into the item's `long_description` field (replaces seller's version in the DB on approve)
- If no AI result: only the seller's description column is shown, no AI column

---

## New Routes

| Method | Path | Function | Description |
|--------|------|----------|-------------|
| `POST` | `/admin/item/<id>/ai-lookup` | `admin_trigger_ai_lookup` | Manually re-runs the AI lookup for a specific item. Admin only. Returns JSON with the new result. |
| `GET` | `/admin/item/<id>/ai-result` | `admin_get_ai_result` | Returns the current stored AI result for an item as JSON. Used by the approval queue UI to poll for results if the lookup is still in progress. Admin only. |

---

## Model Changes

### New Model: `ItemAIResult`
Stores the AI lookup result for each item. Kept separate from `InventoryItem` to avoid bloating the main item table and to make it easy to re-run and replace results.

```python
id                  — integer, primary key
item_id             — integer, FK to InventoryItem, unique (one result per item)
status              — string: 'pending' | 'found' | 'unknown' | 'error'
product_name        — string(500), nullable — e.g. "Frigidaire EFRF696-AMZ"
retail_price        — numeric(10,2), nullable — retail price found
retail_price_source — string(500), nullable — URL to the product listing
suggested_price     — numeric(10,2), nullable — AI's recommended resale price
pricing_rationale   — text, nullable — one or two sentence explanation
ai_description      — text, nullable — AI-generated item description
raw_response        — text, nullable — full raw JSON response from Claude (for debugging)
created_at          — datetime, default now
updated_at          — datetime, updated on re-run
```

A Flask-Migrate migration is required to create this table.

### `InventoryItem` — no changes needed
The AI result is stored in `ItemAIResult` and joined where needed. Do not add AI fields directly to `InventoryItem`.

---

## Template Changes

### `templates/admin_approve.html`
This is the primary template to modify.

**AI Research Panel** — add to the right side of the item review layout (or below the photo gallery if layout is single-column):
- Renders `ItemAIResult` data for the current item
- If `status = 'pending'`: show loading state with a JS poll to `/admin/item/<id>/ai-result` every 3 seconds until status changes
- If `status = 'found'`: show full result panel as described in UX Flow
- If `status = 'unknown'` or `'error'`: show minimal "Could not identify" state
- "Use this price" button: vanilla JS that sets the value of the price input field to `suggested_price`
- "Re-run" button: POST to `/admin/item/<id>/ai-lookup`, then refresh the panel content

**Description Side-by-Side** — modify the existing description display area:
- If `ai_description` exists: render two-column layout with seller original and AI version
- "Use this" button on AI side: vanilla JS that sets the `long_description` textarea value to `ai_description`
- If no AI result: render existing single description display unchanged

### CSS additions to `static/style.css`
- `.ai-panel` — panel container, consistent with existing card styling, subtle left border in `var(--sage)` to distinguish it from the main form
- `.ai-panel--unknown` — muted grey styling for unknown state
- `.ai-panel__label` — small uppercase label style (consistent with existing eyebrow labels)
- `.description-columns` — two-column grid for side-by-side description display
- Use CSS variables throughout — no hardcoded colors

---

## Business Logic

### Triggering the AI Lookup
In the item submission route handlers (`/onboard` POST and `/add_item` POST), after the `InventoryItem` record is saved to the database:

1. Create an `ItemAIResult` record with `status = 'pending'` and `item_id` set
2. Trigger the AI lookup function — **this must run asynchronously** so it does not block the seller's form submission and redirect. Options:
   - **Option A (preferred):** Use a background thread (`threading.Thread`) to run the lookup after the response is sent. Simple, no new dependencies.
   - **Option B:** Use a task queue (Celery + Redis) if background threads prove unreliable on Render. More robust but adds infrastructure complexity. Start with Option A.
3. The seller's redirect happens immediately — they never wait for the AI

### The AI Lookup Function
```python
def run_ai_item_lookup(item_id):
    item = InventoryItem.query.get(item_id)
    result = ItemAIResult.query.filter_by(item_id=item_id).first()
    
    # Build the message to send to Claude
    # Include: all item photos (as base64 images), category name,
    # condition (quality rating mapped to label), seller's description
    
    # Call the Anthropic API with:
    # - model: claude-sonnet-4-20250514
    # - web search tool enabled
    # - system prompt (see below)
    # - user message with images + item details
    
    # Parse the structured JSON response
    # Update the ItemAIResult record with the parsed fields
    # Set status to 'found' or 'unknown' depending on result
```

### System Prompt for Claude
The system prompt sent with each lookup request:

```
You are a product research assistant for a college student consignment marketplace. 
You will be shown photos of a used item along with its category, condition rating, 
and the seller's description.

Your job is to:
1. Identify the exact product (brand, model name, model number if visible)
2. Search the web to find its current retail price from a major retailer
3. Suggest a fair resale price based on retail price, condition, and any visible wear in the photos
4. Write a clean, accurate 2-3 sentence product description suitable for a resale listing
5. Provide a brief 1-2 sentence rationale for your suggested price

Respond ONLY with a JSON object in this exact format:
{
  "identified": true,
  "product_name": "Full product name and model",
  "retail_price": 129.99,
  "retail_price_source": "https://www.amazon.com/...",
  "suggested_price": 58.00,
  "pricing_rationale": "Retails for $130 new. Condition rated Good with minor scuffs visible on left panel. Suggested at 45% of retail.",
  "description": "Frigidaire 3.2 cu ft compact refrigerator in good condition. Features a small freezer compartment and adjustable shelving. Minor cosmetic wear on exterior."
}

If you cannot confidently identify the specific product or find a retail listing for it, respond with:
{
  "identified": false
}

Do not guess. Only return identified: true if you are confident in the product match and have a real retail URL to provide.
```

### Parsing the Response
- Parse the JSON response from Claude
- If `identified: true`: populate all fields on `ItemAIResult`, set `status = 'found'`
- If `identified: false`: set `status = 'unknown'`, leave all other fields null
- If the API call fails or returns malformed JSON: set `status = 'error'`, log the raw response to `raw_response` field for debugging
- Wrap everything in try/except — a failed AI lookup must never affect the item submission or cause any visible error to the seller

### Re-Run Logic
When admin clicks "Re-run":
- POST to `/admin/item/<id>/ai-lookup`
- The existing `ItemAIResult` record is updated in place (not deleted and recreated)
- Set `status = 'pending'`, clear existing fields, run lookup again
- Return the new result as JSON so the panel can update without a page reload

### Photo Handling
- Send all photos associated with the item (cover photo + gallery photos via `ItemPhoto`)
- Encode each as base64 with correct media type (`image/jpeg` or `image/png`)
- Cap at 4 photos maximum to control cost — send cover photo first, then up to 3 gallery photos
- If item has no photos yet (edge case): set `status = 'unknown'` immediately, do not call the API

### Pricing Logic — What Claude Considers
The system prompt instructs Claude to factor in:
- Retail price (from web search)
- Condition rating: Like New (~60-70% of retail), Good (~40-50%), Fair (~25-35%)
- Visible wear in photos (scratches, stains, damage visible in images)
- Category (electronics depreciate faster than furniture)

Claude determines the final suggested price — there is no hardcoded formula on the backend. The rationale field explains the reasoning so the admin can evaluate it.

### Edge Cases
- **Item submitted, AI lookup fails silently:** `ItemAIResult` record has `status = 'error'`. Admin sees "Could not identify product" panel. Re-run button available. Item approval is completely unaffected.
- **Seller resubmits after "needs info" request (new photos uploaded):** Admin sees the old AI result with a note: *"Photos updated since last lookup."* Re-run button is prominent. The re-run triggers a fresh lookup with the new photos.
- **Item category is "Other" with no useful photos:** Likely returns `identified: false`. Expected behavior.
- **Multiple items submitted simultaneously:** Each triggers its own background thread with its own `ItemAIResult` record. No shared state.
- **API rate limits:** Anthropic rate limits are generous for this volume. If a rate limit error is returned, set `status = 'error'` and log it. Admin can re-run manually.
- **Cost monitoring:** Each lookup costs approximately $0.02–$0.05. For 2,000 items this is roughly $40–$100 total for a full season. No per-item cost controls are needed at this scale.

---

## Environment Variables
Add to Render environment:
- `ANTHROPIC_API_KEY` — API key for Claude. Required. If not set, the lookup function should fail silently and set `status = 'error'` without crashing the app.

---

## Implementation Notes for Claude Code

1. **Do not block the seller's request.** The AI lookup must run in a background thread after the HTTP response is sent. Use `threading.Thread(target=run_ai_item_lookup, args=(item.id,), daemon=True).start()` after the item is committed to the database.

2. **The `ItemAIResult` record must be created before the thread starts** (with `status = 'pending'`) so the approval queue has something to render immediately even if the lookup hasn't finished.

3. **Use the Anthropic Python SDK** (`anthropic` package — add to `requirements.txt` if not already present). Use `claude-sonnet-4-20250514` as the model. Enable the web search tool by passing it in the `tools` parameter.

4. **JSON parsing:** Strip any markdown code fences (` ```json `) before parsing — Claude sometimes wraps JSON in fences even when instructed not to. Use a try/except around `json.loads()`.

5. **The approval queue poll:** If `status = 'pending'` when the admin loads the item, the JS should poll `/admin/item/<id>/ai-result` every 3 seconds until status is no longer `'pending'`, then render the result. Add a timeout of 60 seconds — if still pending after that, show the unknown state.

6. **Do not modify any existing item submission logic** beyond adding the two lines that create the `ItemAIResult` record and start the background thread. The rest of the submission flow must remain exactly as is.

---

## Constraints
- A failed or slow AI lookup must never affect the seller's submission experience in any way
- The AI suggested price must never be auto-applied to the item — it always requires the admin to click "Use this price"
- The AI description must never replace the seller's description without admin action — both are always shown side by side
- Do not store API keys or raw responses anywhere accessible to non-super-admins
- The `raw_response` field on `ItemAIResult` is for debugging only — it should not be rendered in any template
