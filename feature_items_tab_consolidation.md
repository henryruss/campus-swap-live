# Feature Spec: Items Tab Consolidation

## Goal

Three admin workflows for item photo lifecycle — initial approval, AI review, and photo
verification — currently live in three different parts of the admin panel. This creates
cognitive overhead and makes it hard to see where a given item sits in the pipeline.

This spec consolidates all three into the existing Items tab (`/admin/items`) as explicit
sub-tabs, and moves the AI generation trigger (currently a standalone page at
`/admin/ai/generate`) into a modal accessible from the Items tab header. The standalone
AI generate page is removed.

---

## UX Flow

### Items Tab Header

The Items tab top bar gains an **"AI Autofill ✦"** button (super admin only, right side of
header). Clicking opens the AI Autofill modal (see below). The existing stats bar (Total,
Pending, Available, Sold) stays unchanged.

### Sub-tab Pills

Current pills: `All Items` | `Approval Queue`

New pills:
```
All Items | Approval Queue (N) | AI Review (N) | Photo Verification (N)
```

- Count badges on Approval Queue, AI Review, and Photo Verification reflect live pending
  counts — same values already computed for nav badges and sidebar.
- AI Review and Photo Verification pills are **super admin only** (hidden for `is_admin`
  without `is_super_admin`, matching existing access on those routes).
- Active tab is driven by `?view=` query param, same pattern as existing `?view=approve`.
- Default (no `?view=` param) → All Items tab active.

### Tab: All Items
No change from current behavior.

### Tab: Approval Queue (`?view=approve`)
No change from current behavior. Existing modal flow, card grid, Approve/Reject/Need Info
all unchanged.

### Tab: AI Review (`?view=ai_review`)
Pulls content from the existing `admin/ai_review.html` card grid. Card grid, slide-in
detail modal, approve/discard/set-cover/delete-gallery actions all **unchanged** — this is
a straight relocation of the existing page into a sub-tab of `/admin/items`.

Page renders inline inside `admin/items.html` (via Jinja `{% include %}` or `{% block %}`
pattern) rather than as its own full page. The `GET /admin/ai/review` route becomes a 302
redirect to `/admin/items?view=ai_review`.

### Tab: Photo Verification (`?view=photo_verification`)
Pulls the Photo Verification Queue content currently embedded in `admin/warehouse.html`.
The indigo collapsible section on the Warehouse page is **removed**; that content now lives
exclusively here.

Shows items with `needs_photo_verification=True`. Same card/list UI pattern. "Looks Good"
button POSTs to existing `POST /admin/item/<id>/verify-photo` (unchanged). Download +
re-upload flow unchanged. The `needs_new_photo` / Needs New Photo section stays in the
Warehouse page — it is a warehouse-floor operational task (take a new photo), not an admin
review task.

### AI Autofill Modal

Triggered by the "AI Autofill ✦" button in the Items tab header. Super admin only.

**Modal content** (everything currently on `admin/ai_generate.html`):
- Stats row: Eligible items count, last run timestamp, last run error count
- Model selector dropdown (default `claude-sonnet-4-6`)
- Batch size input
- **Run** button → `POST /admin/ai/generate/run` (unchanged, returns `{job_id}`)
- Live progress bar (polls `GET /admin/ai/generate/status` at existing interval)
- Results table: item title, price, retail, status (success/error) — populated after run
- **Cancel** button (visible while job running) → `POST /admin/ai/generate/cancel`
  (unchanged)
- Close button dismisses modal; if a job is running, confirm dialog: "A job is in
  progress. Close anyway?" — closing does not cancel the job.

Modal opens over the Items tab. No page navigation. Same polling logic as existing
`admin/ai_generate.html` JS, lifted into the modal.

---

## New Routes

| Method | Path | Function | Notes |
|--------|------|----------|-------|
| `GET` | `/admin/ai/generate` | `admin_ai_generate_page` | **Changed:** 302 → `/admin/items?view=ai_review`. Was standalone page. |
| `GET` | `/admin/ai/review` | `admin_ai_review_queue` | **Changed:** 302 → `/admin/items?view=ai_review`. Was standalone page. |

All other routes (`POST /admin/ai/generate/run`, `POST /admin/ai/generate/cancel`,
`GET /admin/ai/generate/status`, `POST /admin/ai/item/<id>/approve`, etc.) are
**unchanged** — same URL, same function, same logic.

---

## Model Changes

None. No new fields, no migration needed.

---

## Template Changes

### `admin/items.html` — Primary change surface

1. **Sub-tab pills:** Add `AI Review` and `Photo Verification` pills (super admin only).
   Active state driven by `?view=` param.

2. **Tab content blocks:** Add two new conditional blocks:
   - `{% if view == 'ai_review' %}` — includes/inlines existing AI review card grid +
     slide-in modal markup (moved from `admin/ai_review.html`).
   - `{% if view == 'photo_verification' %}` — new card/list rendering items where
     `needs_photo_verification=True`, with Download + Re-upload + "Looks Good" actions
     (moved from `admin/warehouse.html`).

3. **AI Autofill modal:** New `<div id="ai-autofill-modal">` added to the page. Hidden by
   default. Contains all content from `admin/ai_generate.html` (stats, model selector,
   batch size, run button, progress bar, results table, cancel button). "AI Autofill ✦"
   button in the header opens it.

4. **AI Autofill JS:** The polling logic from `admin/ai_generate.html` moves into a
   `<script>` block in `admin/items.html`, scoped to fire only when the modal is open.

### `admin/ai_generate.html`

**Deleted.** Route now redirects; content lives in the Items tab modal.

### `admin/ai_review.html` and `admin/ai_review_detail_partial.html`

**`ai_review.html` — deleted** (content absorbed into `admin/items.html`).
**`ai_review_detail_partial.html` — kept.** Still fetched on demand by the slide-in
modal via `GET /admin/ai/item/<id>/detail`. No changes to this partial.

### `admin/warehouse.html`

Remove the Photo Verification Queue section (the indigo collapsible). The "Needs New
Photo" amber section **stays** — it is warehouse-floor work, not admin review. No other
changes to warehouse.

### `admin/admin_layout.html` (sidebar)

Remove the standalone **AI Review** sidebar nav item and its amber badge. The three queues
are now sub-tabs inside the Items icon — the sidebar Items badge should reflect the sum of
all three pending counts: `pending_valuation` + `ai_review_pending` + 
`needs_photo_verification`. (If the current Items badge only counts `pending_valuation`,
update the context processor that computes it.)

---

## Business Logic

### Tab access gating

| Tab | Access |
|-----|--------|
| All Items | `is_admin` |
| Approval Queue | `is_admin` |
| AI Review | `is_super_admin` only |
| Photo Verification | `is_super_admin` only |

If a non-super-admin hits `?view=ai_review` or `?view=photo_verification` directly, return
403. (Match existing behavior of the standalone routes.)

### Sidebar badge

The Items sidebar badge currently reflects pending approval count. Update to:
```
pending_valuation_count + ai_review_pending_count + needs_photo_verification_count
```
So admins see the full pending work at a glance. Each individual sub-tab pill carries its
own count for breakdown.

### Photo Verification Queue in warehouse

The `needs_photo_verification` items currently surface in two places once this is built:
the warehouse search results (camera button) and the warehouse Photo Verification Queue
section. After this spec, they surface only in the Items tab. The camera button in
warehouse search results (for `needs_new_photo` items) is unrelated and stays. 

### Modal close-while-running guard

If the admin closes the AI Autofill modal while a job is in progress (job is polling),
show a browser confirm: "AI generation is still running. Close the modal? The job will
continue in the background." Close or navigate away does not cancel the job — cancellation
is explicit via the Cancel button only.

---

## Constraints

- **No route logic changes** to any POST action routes (approve, discard, set-cover, 
  verify-photo, delete-gallery, generate/run, generate/cancel). URLs, function names,
  and response shapes all stay the same.
- **`admin/ai_review_detail_partial.html`** is not modified — it is fetched on demand,
  unchanged.
- **Warehouse page** loses only the Photo Verification Queue collapsible. Everything else
  on the warehouse page (unit grid, Needs New Photo section, Log Item modal, search)
  is untouched.
- **`GET /admin/approve` → `/admin/items?view=approve`** redirect stays in place.
- **Seller profile panel** (`admin/seller_panel.html`) opens from item cards in all tabs
  via the existing `loadSellerPanel(userId)` delegation pattern — no changes needed.
- **Admin-only (non-super) users** see Items tab with All Items + Approval Queue only.
  AI Review and Photo Verification tabs are invisible to them.
