# Feature Spec: AI Auto-Fill — Title, Description & Price Generation

**Status:** Ready for implementation  
**Depends on:** No spec dependencies. Requires `ANTHROPIC_API_KEY` env var on Render.  
**Scope:** Super admin only. All non-rejected, non-sold items are eligible.

---

## Goal

Sellers submitted items with just enough detail for a pickup — not for selling. Every item needs a compelling buyer-facing title, description, and a correctly-set price before the shop opens. This feature uses Claude vision to generate all three fields in bulk, stages them for admin review, and provides a fast click-through review queue before anything goes live.

---

## UX Flow

### Generation (the batch job)

1. Super admin navigates to **`/admin/ai/generate`** — the AI Autofill control page.
2. Page shows:
   - Count of eligible items (not yet generated: `ai_review_pending = False` AND `ai_generated_at IS NULL`, status not `rejected`)
   - Count of items pending review (`ai_review_pending = True`)
   - "Run Generation" button with a `limit` input (default 5 for test runs, blank = all)
   - Log of previous runs (timestamp, how many items processed, how many errors)
3. Admin clicks **Run Generation**. Page transitions to a live progress view:
   - Progress bar: "X of Y complete"
   - Live item feed: as each item finishes, a card appears showing the photo thumbnail, the generated title, and the price — fading in one at a time
   - Any errors shown inline (e.g. "Item #42 — photo not found, skipped")
4. When the job finishes: "Done — X items ready for review" with a link to the review queue.
5. On subsequent runs (new items arriving daily): the job skips any item that already has `ai_generated_at` set, so re-running is safe and idempotent.

**Progress polling:** The frontend polls `GET /admin/ai/generate/status` every 2 seconds. The job writes progress to a simple in-memory dict keyed by a `job_id` returned when the job starts. The job runs in a background thread (Python `threading.Thread`). This is sufficient for a single-instance Render deployment.

### Review (the approval queue)

1. Super admin navigates to **`/admin/ai/review`** — the AI Review queue.
2. Page shows a card grid of all items with `ai_review_pending = True`, sorted oldest-generated first.
3. Each card shows: item thumbnail, AI-generated title, AI-suggested price, original seller-suggested price (for context), category, condition badge.
4. Admin clicks a card → **review modal opens** (same slide-in panel pattern as the existing approval modal):
   - Photo gallery (cover + gallery photos, same track/prev/next UI as `approval_detail_partial.html`)
   - **Editable title field** (pre-filled with `ai_description`)
   - **Editable long description textarea** (pre-filled with `ai_long_description`)
   - **Editable price field** (pre-filled with the computed final price — `max(ai_price, suggested_price)`)
   - Read-only callout: "Seller suggested: $X" (if `suggested_price` exists)
   - Read-only callout: "AI suggested: $Y" (always shown for context)
   - Three footer buttons: **Approve**, **Skip**, **Discard AI**
5. Admin edits inline if needed, then:
   - **Approve** → writes edited title/description/price to live fields (`description`, `long_description`, `price`), sets `ai_review_pending = False`, removes card from queue. Does NOT change `status` — item stays in whatever status it was in.
   - **Skip** → closes modal, leaves item in queue untouched (come back to it later)
   - **Discard AI** → clears all `ai_*` staging fields, sets `ai_review_pending = False`, item drops from queue. Existing live fields are untouched.
6. After Approve/Discard: card animates out, pending count badge decrements. Queue shows empty state when all done.

**Keyboard shortcut:** Pressing `Enter` while the modal is open triggers Approve (with a 300ms debounce to prevent accidental double-fire). Pressing `Escape` skips.

---

## New Routes

| Method | Path | Function | Auth | Description |
|--------|------|----------|------|-------------|
| `GET` | `/admin/ai/generate` | `admin_ai_generate_page` | Super admin | Control page — counts, run button, run history |
| `POST` | `/admin/ai/generate/run` | `admin_ai_generate_run` | Super admin | Kick off background generation job. Body: `limit` (int, optional). Returns `{job_id, total}`. |
| `GET` | `/admin/ai/generate/status` | `admin_ai_generate_status` | Super admin | Poll job progress. Params: `job_id`. Returns `{done, total, completed, errors: [{item_id, reason}], results: [{item_id, photo_url, ai_description, ai_price}]}`. |
| `GET` | `/admin/ai/review` | `admin_ai_review_queue` | Super admin | Review queue page — card grid of `ai_review_pending=True` items |
| `GET` | `/admin/ai/item/<id>/detail` | `admin_ai_review_detail` | Super admin | HTML partial (no layout) for review modal content. Returns gallery + staged fields. |
| `POST` | `/admin/ai/item/<id>/approve` | `admin_ai_approve` | Super admin | Write staged → live fields. Applies `max(ai_price, suggested_price)` pricing rule. Sets `ai_review_pending=False`. Returns JSON `{success}`. |
| `POST` | `/admin/ai/item/<id>/discard` | `admin_ai_discard` | Super admin | Clear staged fields, set `ai_review_pending=False`. Returns JSON `{success}`. |

---

## Model Changes

All new fields on `InventoryItem`. One migration required.

```
# New fields on InventoryItem

ai_description        (Text, nullable)     — staged title (max 200 chars, enforced in generation)
ai_long_description   (Text, nullable)     — staged body copy (max 2000 chars)
ai_price              (Numeric 10,2, nullable) — raw AI-suggested price (before max() rule)
ai_review_pending     (Boolean, default False, server_default='0') — True = in review queue
ai_generated_at       (DateTime, nullable) — UTC timestamp of when generation ran for this item
```

**Migration name:** `add_ai_autofill_fields`

No new tables. No changes to existing fields. No FK relationships.

**Eligibility query** (used by the generation job):

```python
eligible = InventoryItem.query.filter(
    InventoryItem.status.notin_(['rejected', 'sold']),
    InventoryItem.ai_generated_at.is_(None),
    InventoryItem.photo_url.isnot(None)
).all()
```

Re-running the job is safe: `ai_generated_at IS NULL` means already-generated items are always skipped.

---

## Generation Job Logic

The job runs per-item in a background thread. For each item:

### 1. Collect photos

```python
photos = []
# Cover photo first
if item.photo_url:
    photos.append(item.photo_url)
# Then gallery photos
for gp in item.gallery_photos:
    if gp.photo_url != item.photo_url:
        photos.append(gp.photo_url)
# Cap at 4 photos to control token cost
photos = photos[:4]
```

Each photo filename is read from disk (`/var/data/<filename>` in production, `static/uploads/<filename>` locally), base64-encoded, and sent as an `image` content block with `media_type` inferred from the file extension (jpeg/png/webp).

If the file is not found on disk: log error, mark item as skipped, continue to next item. Do not crash the job.

### 2. Build the prompt

```python
seller_note = ""
if item.description or item.long_description:
    parts = []
    if item.description:
        parts.append(item.description.strip())
    if item.long_description:
        parts.append(item.long_description.strip())
    combined = " — ".join(parts)
    seller_note = f'The seller described it as: "{combined}". Preserve any specific details they mentioned (dimensions, damage, accessories, etc.) in your description.'

quality_map = {5: "Like New", 4: "Good", 3: "Fair", 2: "Poor", 1: "Very Poor"}
condition_label = quality_map.get(item.quality, "Used")
category_name = item.category.name if item.category else "Item"

prompt = f"""You are writing marketplace listings for Campus Swap, a college student consignment shop at UNC Chapel Hill.

Item details:
- Category: {category_name}
- Condition: {condition_label}
{seller_note}

Looking at the photo(s), write a listing with three parts. Respond ONLY with valid JSON, no markdown, no extra text:

{{
  "title": "Short, specific, buyer-facing title. Max 80 characters. Lead with the item type and one key selling detail. Examples: 'Black Mini Fridge — Perfect Dorm Size', 'Grey IKEA Couch — Great Condition'. Do not start with 'I' or 'This'.",
  "description": "2-3 sentences. Highlight the best visual features, condition, and why a student would want it. Mention any notable details from the seller if provided. Do not mention price.",
  "price": A number (no dollar sign, no quotes). Fair resale price in USD for a used college dorm item in this condition. Be realistic — students are price-sensitive. Return only the number.
}}"""
```

### 3. Call the Anthropic API

```python
import anthropic, base64, json

client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env

content = []
for photo_path in resolved_photo_paths:
    with open(photo_path, "rb") as f:
        data = base64.b64encode(f.read()).decode("utf-8")
    ext = photo_path.rsplit(".", 1)[-1].lower()
    media_map = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}
    content.append({
        "type": "image",
        "source": {"type": "base64", "media_type": media_map.get(ext, "image/jpeg"), "data": data}
    })
content.append({"type": "text", "text": prompt})

response = client.messages.create(
    model="claude-opus-4-5",   # Use Sonnet for cost efficiency on bulk runs
    max_tokens=500,
    messages=[{"role": "user", "content": content}]
)
```

Use `claude-sonnet-4-5` (model string: `claude-sonnet-4-5-20251001`) for the bulk job. This is the cost-efficient model — Opus is unnecessary for structured listing generation.

> **Note for Claude Code:** Check `CODEBASE.md` and the `product-self-knowledge` skill for the correct current model string before hardcoding. The model string above is a placeholder based on planning-time knowledge.

### 4. Parse response and write staging fields

```python
raw = response.content[0].text.strip()
# Strip any accidental markdown fences
if raw.startswith("```"):
    raw = raw.split("```")[1]
    if raw.startswith("json"):
        raw = raw[4:]
raw = raw.strip().rstrip("```").strip()

parsed = json.loads(raw)

item.ai_description = str(parsed["title"])[:200]
item.ai_long_description = str(parsed["description"])[:2000]
item.ai_price = round(float(parsed["price"]), 2)
item.ai_generated_at = datetime.utcnow()
item.ai_review_pending = True
db.session.commit()
```

If `json.loads` fails or required keys are missing: log error with item ID and raw response, set `ai_generated_at = utcnow()` (to prevent infinite retry), leave `ai_review_pending = False`. The item will not appear in the review queue but won't block future runs either.

### 5. Progress tracking

The background thread updates a module-level dict:

```python
_AI_JOBS = {}  # job_id → {total, completed, errors, results, done}
```

Each completed item appends to `results` (for the live feed) and increments `completed`. The polling endpoint reads from this dict. Job IDs are `uuid4()` strings. Jobs older than 1 hour are pruned on each new job start to prevent memory growth.

---

## Approve Action Logic

The `admin_ai_approve` handler applies pricing and copies staged → live:

```python
# Pricing rule: respect seller if they priced higher
ai_price = item.ai_price or 0
seller_price = float(item.suggested_price) if item.suggested_price else 0
final_price = max(ai_price, seller_price)
if final_price <= 0:
    return jsonify({"success": False, "error": "Price must be greater than zero"}), 400

# Read editable fields from POST body (admin may have tweaked inline)
title = request.form.get("description", item.ai_description or "").strip()[:200]
body = request.form.get("long_description", item.ai_long_description or "").strip()[:2000]
price_override = request.form.get("price")
if price_override:
    try:
        final_price = round(float(price_override), 2)
    except ValueError:
        return jsonify({"success": False, "error": "Invalid price"}), 400

item.description = title
item.long_description = body
item.price = final_price
item.ai_review_pending = False
# Leave ai_* staging fields in place as an audit trail
db.session.commit()
```

The inline edits from the modal override the staged values. The `ai_*` fields are **not cleared on approve** — they serve as a permanent audit trail showing what AI originally suggested vs. what was published.

---

## Template Changes

### New templates

**`templates/admin/ai_generate.html`** — extends `layout.html`
- Header: "AI Autofill" title + subtitle explaining what this does
- Stats row: "X items eligible", "Y items pending review"
- Run form: `limit` number input (placeholder "Leave blank for all") + "Run Generation" button
- Progress section (hidden until job starts): progress bar (`<progress>` element), live item feed (cards fade in as results arrive via polling), error list
- "Go to Review Queue →" link/button (shown when `ai_review_pending` count > 0)
- Run history table: timestamp, items processed, errors (stored in AppSetting as JSON, key `ai_autofill_run_log`, capped at last 10 runs)

**`templates/admin/ai_review.html`** — extends `layout.html`
- Same card grid layout as `admin/items.html` approval queue
- Each card: thumbnail, AI title, final price (after max rule), original suggested price (small grey text), category pill, condition badge, "Click to review" hint
- Empty state: "All caught up — no items pending AI review"
- Pending count shown in page header
- Reuses/mirrors existing `.approve-card` CSS class behavior

**`templates/admin/ai_review_detail_partial.html`** — no layout (partial, fetched via AJAX)
- Root `div` with `data-item-id`, `data-ai-price`, `data-suggested-price`
- Photo gallery: same track + prev/next + counter pattern as `approval_detail_partial.html`
- Editable fields (all `<input>`/`<textarea>`, NOT readonly):
  - Title: `<input type="text" name="description" maxlength="200">`
  - Description: `<textarea name="long_description" maxlength="2000">`
  - Price: `<input type="number" name="price" step="0.01" min="0.01">`
- Read-only context row: "AI suggested $X · Seller suggested $Y" (show "—" if no seller price)
- Character counters for title and description fields

### Modified templates

**`templates/layout.html`** — add AI review badge to admin nav
- Add a new nav link "AI Review" with a count badge (similar to `qc_pending_count`)
- Badge shows `ai_review_pending_count` injected by a new context processor
- Only visible to `current_user.is_super_admin`

**`templates/admin/items.html`** — no changes required (AI queue is a separate page)

---

## Business Logic & Constraints

### Pricing rule (applied at approve time, not generation time)
```
final_price = max(ai_price, suggested_price or 0)
```
The admin can override this in the modal before approving. Whatever is in the price field when Approve is clicked is what gets written to `item.price`.

### Eligibility for generation
- Status must NOT be `rejected` or `sold`
- `photo_url` must not be null (can't generate without a photo)
- `ai_generated_at` must be null (not previously run)
- `is_internal_account` sellers are included (QC items should get listings too)

### Re-running for new items
Re-run the job at any time. Items with `ai_generated_at` set are always skipped. New items added after the initial run will have `ai_generated_at = NULL` and will be picked up automatically.

### Status is never touched
The generation job and approve/discard handlers never modify `item.status`. A `pending_valuation` item stays `pending_valuation`. An `available` item stays `available`. AI autofill is purely a content editing operation.

### Generation job is single-instance
Only one job should run at a time. On `POST /admin/ai/generate/run`, if a job with `done=False` already exists in `_AI_JOBS`, return a 409 with `{"error": "A job is already running"}`. The frontend should show this gracefully and offer a refresh.

### API key missing
If `ANTHROPIC_API_KEY` is not set, the generate page should show a prominent warning banner and disable the Run button. Check `os.environ.get('ANTHROPIC_API_KEY')` at page load and return a flash error from the run endpoint.

### Error tolerance
Individual item failures (file not found, API error, JSON parse failure) must not abort the whole job. Log the error, record it in the job's `errors` list, and continue to the next item. The run history entry should record the error count.

### The `ai_generated_at` field as error sentinel
Even on failure, set `ai_generated_at = utcnow()` so the item is not retried in future runs. If you need to force a retry on a specific item, a super admin would need to null this field manually via the DB or a future utility route. This is intentional — prevents a bad photo from burning API credits on every run.

### Concurrency: background thread vs. request context
The background thread does not have Flask's application context by default. Use `app.app_context()` in the thread:
```python
def run_job(app, job_id, item_ids):
    with app.app_context():
        for item_id in item_ids:
            # ... db queries and commits work here
```
Pass `current_app._get_current_object()` as `app` when starting the thread.

---

## Constraints (What Must Not Be Touched)

- The existing approval queue (`/admin/items?view=approve`) is completely unchanged. AI review is a separate queue at a separate URL.
- `item.status` is never modified by any route in this spec.
- The `admin_ai_approve` handler writes to `item.description`, `item.long_description`, and `item.price` — the same fields the standard approval flow writes to. No new live fields.
- The quick-capture queue (`/admin/items/needs_info`) is unaffected.
- Seller-facing dashboard is unaffected — `ai_*` fields are never exposed to sellers.
- The `price_changed_acknowledged` / `price_updated_at` fields: do not set these when AI approve writes `item.price`. These are for the seller price-change notification flow, not admin edits.

---

## Environment Variables

| Variable | Required | Notes |
|----------|----------|-------|
| `ANTHROPIC_API_KEY` | Yes | Standard Anthropic API key. Add to Render environment. |

---

## Run History (AppSetting storage)

Each completed job appends a record to `AppSetting` key `ai_autofill_run_log` (JSON-encoded list, capped at 10 entries):

```json
[
  {
    "started_at": "2026-05-28T14:32:00Z",
    "completed_at": "2026-05-28T14:36:12Z",
    "total": 47,
    "succeeded": 44,
    "errors": 3
  }
]
```

The generate page reads and displays this log in a table below the run form.

---

## Edge Cases

| Scenario | Behavior |
|----------|----------|
| Item has no photos on disk (file missing) | Skip item, log error with item ID, continue job |
| API call times out | Retry once with 5s delay; on second failure, log error and continue |
| JSON response unparseable | Log raw response + item ID, set `ai_generated_at` to prevent retry, skip |
| Admin edits title to empty string and clicks Approve | Validate: title must not be blank. Show inline error, do not submit. |
| Admin edits price to 0 or negative | Validate client-side and server-side. Must be > 0. |
| Item already has `ai_review_pending=True` and job runs again | Eligibility query filters `ai_generated_at IS NULL` — already-generated items are skipped regardless of review status |
| Two admins open the same review modal simultaneously | Last write wins on Approve. Acceptable — this is a single-operator tool. |
| Item is sold between generation and review | Approve handler should check `item.status != 'sold'` and return a 400 if so, with message "Item has been sold — no changes made." |
