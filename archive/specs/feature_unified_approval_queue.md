# Feature Spec: Unified AI-First Approval Queue

**Spec file:** `feature_unified_approval_queue.md`
**Status:** Ready for Claude Code

---

## Goal

Fix the broken AI autofill pipeline so that:

1. Every item submission (seller or quick-capture) automatically triggers AI autofill + photo enhancement in the background — no browser session required, no manual sweep needed
2. The regular admin approval queue shows AI-generated fields alongside original seller fields side-by-side, so admin approval is a single step
3. Items only appear in the shop when they are both AI-approved AND have a storage unit assigned
4. The manual AI generate page (`/admin/ai/generate`) still works for backlog processing but runs via a persistent queue worker instead of spawning per-item threads (fixes OOM crashes and browser-dependency)

---

## Background: What Is Broken

- The auto-trigger that should fire AI generation on item submission is broken (regression from a prior threading fix session)
- The current architecture spawns a raw `threading.Thread` per item — on Render's 512MB instance, processing multiple image-heavy items concurrently causes OOM crashes
- The `/admin/ai/generate` page polls for progress over HTTP — if the browser is closed or the request times out, the job stops
- Items that go through the old approval queue (`POST /admin/approve`) never get `ai_approved=True`, so they are invisible to buyers even after admin approves them
- The shop visibility filter does not check `storage_location_id`

---

## Architecture: Persistent Queue Worker

Replace all per-item thread spawning with a **single persistent daemon thread** running a `queue.Queue` worker. This worker:

- Starts once at app startup (guarded by a flag so it only starts once even under Gusto/reloader)
- Blocks on `ai_queue.get()` waiting for item IDs
- Processes items serially: AI text generation → photo enhancement → DB write → set `ai_review_pending=True`
- After each item: explicitly `del` large byte buffers to release memory before the next item
- Never crashes the app — exceptions per item are caught, logged, and `ai_generated_at` is stamped as the error sentinel

This is the architecture already designed in the project's memory. Claude Code should implement it.

**Global queue object** (top of `app.py` or a dedicated `ai_worker.py` module):
```python
import queue, threading
ai_queue = queue.Queue()
_ai_worker_started = False
```

**Worker function:**
```python
def _ai_queue_worker():
    while True:
        item_id = ai_queue.get()
        try:
            _process_single_item_ai(item_id)  # existing generation logic, extracted
        except Exception as e:
            app.logger.error(f"AI worker error for item {item_id}: {e}")
        finally:
            ai_queue.task_done()
```

**Start at app startup** (in `create_app()` or equivalent startup block):
```python
global _ai_worker_started
if not _ai_worker_started:
    _ai_worker_started = True
    t = threading.Thread(target=_ai_queue_worker, daemon=True)
    t.start()
```

---

## Change 1: Auto-Trigger on Item Submission

**Where to add:** Any route that creates a new `InventoryItem` with `status='pending_valuation'`. Based on codebase review this includes:
- `add_item` (seller onboarding wizard final step)
- `seller_dashboard` item add flow
- `crew_quick_capture` (already eligible — just not being triggered)
- The import script items are already in prod with `ai_generated_at=NULL` — they will be picked up by the backlog sweep, not this trigger

**What to add** (after the item is committed to DB):
```python
ai_queue.put(item.id)
```

That's it. The worker picks it up immediately and processes it in the background.

**Do not** add the trigger to admin-created items via the quick-add/proxy seller flow — those should also get it. Add to any route that commits a new InventoryItem.

---

## Change 2: Approval Queue Shows AI Fields Side-by-Side

The existing approval queue at `/admin/items?view=approve` shows cards with a price input and approve/reject/need-info buttons. This needs to be updated so that when an item has AI data (`ai_description IS NOT NULL`), the modal shows a two-column layout:

**Left column — Seller Original:**
- `seller_description` (original title)
- `seller_long_description` (original description)
- `suggested_price` (seller's price suggestion)
- Original cover photo (`item.photo_url` before enhancement — see note below)

**Right column — AI Generated:**
- `ai_description` (AI title)
- `ai_long_description` (AI description)
- `ai_price` (AI suggested price)
- `ai_retail_price` (retail reference)
- Enhanced photo (if `ai_photo_enhanced=True`, the current `item.photo_url` is already the enhanced version)

**Price input:** Pre-fill with `ai_price` if set, else `suggested_price`. Admin can edit before approving.

**Approve button behavior** (modify `admin_approve` route or create a new unified approve route):
When admin clicks Approve:
- Write `ai_description → description`, `ai_long_description → long_description`, `ai_price → price`, `ai_retail_price → retail_price` (same as current `admin_ai_approve` does)
- Set `ai_approved=True`
- Set `status='available'`
- Set `ai_review_pending=False`
- Send the existing approval email to seller

**If item has NO AI data yet** (AI hasn't run yet — edge case for fast submitters):
- Show the standard single-column card as today, with a "AI processing..." badge
- Admin should not approve items without AI data — disable the Approve button and show "Waiting for AI" state
- This should be rare since the queue worker processes immediately after submission

**Note on original photo:** When photo enhancement runs, it overwrites `item.photo_url` with the enhanced version. The original photo URL is not currently preserved. Claude Code should check whether `seller_description` / `seller_long_description` exist and use those for the left column. Do not change the photo enhancement behavior — just show the enhanced photo in both columns if the original is no longer available. This is a known limitation, not a bug to fix in this spec.

---

## Change 3: Shop Visibility — Require Storage Unit

**File:** `app.py`, the `/inventory` route and `?ajax=1` infinite scroll endpoint.

**Current filter:**
```python
.filter(InventoryItem.ai_approved == True)
.filter(InventoryItem.needs_new_photo == False)
.filter(InventoryItem.status != 'rejected')
.filter(InventoryItem.price > 0)
```

**Add one line:**
```python
.filter(InventoryItem.storage_location_id != None)
```

Also add to CODEBASE.md's Shop / Inventory Visibility section.

---

## Change 4: Manual Backlog Sweep (Browser-Independent)

The `/admin/ai/generate` page currently starts a background thread and polls for progress. Since the worker is now a persistent queue, the generate page should instead **enqueue all eligible items** and return immediately.

**Modified behavior of `POST /admin/ai/generate/run`:**
- Query all items where `ai_generated_at IS NULL`
- Put each `item.id` into `ai_queue`
- Return JSON `{enqueued: N}` — how many items were queued
- The existing progress-polling UI can be simplified or left as-is (it won't get live updates anymore, but that's acceptable — Henry will just check the AI review queue after waiting)

**Simplified UI on `/admin/ai/generate`:**
- Show eligible item count
- "Queue All for AI Processing" button
- On click: POST → show "Queued N items. Check the approval queue in a few minutes."
- Remove the live progress bar (it no longer has a job to poll)
- Keep the cancel route as a no-op or remove it

This means Henry can click the button, close his browser, and come back to find items processed.

---

## Change 5: Unified Approve Route

Currently there are two approval paths:
- `POST /admin/approve` — old path, sets `status='available'` but NOT `ai_approved`
- `POST /admin/ai/item/<id>/approve` — AI review path, sets `ai_approved=True` but the item may already be `available`

These need to be merged into one. The approval queue modal should POST to a single route that does both in one transaction:

**New/modified route:** `POST /admin/item/<id>/approve-unified`
- Requires `is_super_admin` (same as AI approve)
- Writes AI staged fields to live fields (if present)
- Sets `ai_approved=True`, `status='available'`, `ai_review_pending=False`
- Sends approval email to seller (existing email #4)
- Returns JSON `{success: true}`

The old `POST /admin/approve` route should be left in place but can be deprecated — do not delete it in this spec, just stop using it from the approval queue UI.

---

## Model Changes

**No new fields required.** All necessary fields already exist:
- `ai_description`, `ai_long_description`, `ai_price`, `ai_retail_price` — staged AI fields
- `ai_approved`, `ai_review_pending`, `ai_generated_at` — AI state flags
- `seller_description`, `seller_long_description` — original seller text (already preserved)
- `storage_location_id` — already on model

**No migration needed.**

---

## Template Changes

### `templates/admin/items.html` (approval queue tab)
- Card click opens modal (already exists via `feature_approval_queue_modal.md` pattern)
- Modal content: two-column layout when AI data present (left = seller original, right = AI generated)
- Approve button POSTs to new unified approve route
- "Waiting for AI" disabled state when `ai_generated_at IS NULL`

### `templates/admin/ai_generate.html`
- Remove live progress bar and polling JS
- Replace with simple "Queue N items" button + confirmation message
- Keep page structure, remove job_id / status polling

### `templates/admin/ai_review.html` and `templates/admin/ai_review_detail_partial.html`
- **Do not delete these yet** — they may still have items from the old pipeline in the review queue
- Add a banner: "Items now flow through the main approval queue. This queue will be empty going forward."
- Leave functional for draining any existing `ai_review_pending=True` items

---

## Business Logic & Edge Cases

**Item submitted before worker starts:** The daemon thread starts at app startup. On Render, the worker will be running before any request is handled. Not a real risk.

**Item submitted while worker is busy:** `queue.Queue` is unbounded — items pile up and are processed in order. No items are lost.

**AI generation fails:** Existing behavior preserved — `ai_generated_at` is stamped as error sentinel, item does not enter approval queue. Admin can clear `ai_generated_at` manually to retry.

**Duplicate enqueue:** If an item ID is enqueued twice (e.g., admin clicks generate twice), the worker checks `ai_generated_at IS NULL` at the start of `_process_single_item_ai` and skips items already processed. Add this guard if not already present.

**Admin approves item with no storage unit:** Approval itself is not blocked — but the item will not appear in the shop until a storage unit is assigned. This is intentional. Admin can approve the listing quality now; the item goes live automatically once the organizer assigns a unit.

**Internal Campus Swap items (unlisted items from import script):** These have `is_quick_capture=True` and `ai_generated_at=NULL`. The backlog sweep will enqueue them. They flow through the same approval queue as seller items. No special handling needed.

**The old `admin_ai_review` queue:** Items currently sitting in the AI review queue with `ai_review_pending=True` should continue to be approvable via the existing `/admin/ai/item/<id>/approve` route. Do not break this. The queue just won't receive new items going forward.

---

## Constraints — Do Not Touch

- Do not modify the Stripe webhook handler
- Do not modify `payout_rate` logic or `_get_payout_percentage()`
- Do not modify the organizer intake flow
- Do not modify the seller onboarding wizard UI — only add `ai_queue.put(item.id)` after commit
- Do not delete `POST /admin/approve` (old approval route) — deprecate only
- Do not delete the AI review queue templates or routes — leave functional for draining existing items
- Do not change how `ai_generated_at` works as an error sentinel
- Do not change photo enhancement behavior or `ai_photo_enhanced` flag logic
- The `needs_info` status and `SellerAlert` system are unchanged
- The digest email exclusion for `is_quick_capture` items is unchanged

---

## Test Plan (Henry will verify manually)

1. Create a new seller account (non-admin), submit an item through the onboarding wizard
2. Without touching `/admin/ai/generate`, wait ~1-2 minutes, then check `/admin/items?view=approve`
3. The submitted item should appear in the approval queue with AI fields already populated and the two-column layout visible
4. Approve the item → verify `ai_approved=True`, `status='available'` in DB
5. Item should NOT appear in `/inventory` yet (no storage unit assigned)
6. Assign a storage unit to the item via the warehouse tab → verify item now appears in `/inventory`
7. Go to `/admin/ai/generate`, queue all eligible items (the 75 unlisted items), close the browser
8. Return after a few minutes → check approval queue for new items with AI data populated
