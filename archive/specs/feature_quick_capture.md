# Feature Spec: Driver Quick Capture

## Goal

Drivers frequently encounter items at pickup stops — or between stops — that sellers want to donate or consign on the spot. These items have no listing, no title, no price. The driver needs to photograph the item, assign it to a seller or to Campus Swap, and move on in under 10 seconds. The item enters the system with a photo and an ID; admin fills in title, description, and price later before it goes live.

---

## Internal Account: "Campus Swap"

A seeded internal `User` account acts as the seller for all donated/freebie items. This avoids making `seller_id` nullable on `InventoryItem` and keeps all existing admin payout/listing logic working unchanged.

**Seed this account once (migration or seed script):**

```
email:     internal@campusswap.com
full_name: Campus Swap
is_seller: True
is_worker: False
is_admin:  False
password_hash: unusable (random 60-char hex, never used for login)
```

Add a new boolean to `User`:

```
is_internal_account (Boolean, default False, server_default='0')
```

The seed script sets `is_internal_account=True` on this user. One migration required.

**Admin payout behavior:** The payout reconciliation queue already filters by seller. Items owned by the internal account will naturally appear under "Campus Swap" and can be skipped or handled separately. No payout logic changes needed.

---

## UX Flow

### Entry Point A: Crew Dashboard (`/crew`)

- A camera icon button labeled **"Quick Capture"** sits prominently on the crew dashboard — visible to all approved workers, not shift-gated.
- Tapping it opens the Quick Capture modal with the camera already activating.
- Seller dropdown defaults to **"Campus Swap"** (no active stop to infer from).

### Entry Point B: Active Shift View (`/crew/shift/<shift_id>`)

- A camera icon button **"Quick Capture"** appears in the shift page header, alongside the existing End Shift / shift controls.
- Tapping it opens the same modal.
- Seller dropdown auto-populates based on the **current active stop** (the most recent stop with `status='pending'` in `stop_order` sequence for this driver's truck). If no stop is active, defaults to Campus Swap.

### The Modal

Single screen. No steps. No navigation.

```
┌─────────────────────────────────┐
│  📷  Quick Capture              │
│─────────────────────────────────│
│  ┌───────────────────────────┐  │
│  │                           │  │
│  │   [live camera preview]   │  │
│  │                           │  │
│  │      [ 📷 Take Photo ]    │  │
│  └───────────────────────────┘  │
│                                 │
│  After photo is taken:          │
│  ┌───────────────────────────┐  │
│  │  [photo thumbnail]        │  │
│  │  [ Retake ]               │  │
│  └───────────────────────────┘  │
│                                 │
│  Seller                         │
│  ┌───────────────────────────┐  │
│  │ ▼  [Current Seller Name]  │  │
│  └───────────────────────────┘  │
│                                 │
│  [ Cancel ]   [ Save Item → ]   │
└─────────────────────────────────┘
```

**Seller dropdown order:**
1. Current stop's seller (if an active stop exists) — pre-selected
2. Campus Swap — pre-selected if no active stop
3. All other sellers on this shift's route, in `stop_order` sequence
4. If accessed from the crew dashboard (no shift context): only Campus Swap in the list

**Camera behavior:**
- Uses `getUserMedia({ video: { facingMode: 'environment' } })` — rear camera on mobile.
- Live preview streams into a `<video>` element inside the modal.
- "Take Photo" captures a frame to a `<canvas>`, converts to JPEG blob, displays thumbnail.
- "Retake" clears the canvas and resumes the live stream.
- Camera stream is stopped (`track.stop()`) when modal closes.

**Save Item behavior:**
- Disabled until a photo has been taken.
- On tap: JS POSTs `multipart/form-data` to `POST /crew/quick_capture` with:
  - `photo` — JPEG blob from canvas
  - `seller_id` — from dropdown
  - `shift_id` — from context (null if dashboard entry point)
- On success: modal closes, brief flash "Item #XXXX captured" replaces the button label for 2 seconds, resets.
- On error: inline error message inside modal, does not close.

---

## New Routes

| Method | Path | Function | Description |
|--------|------|----------|-------------|
| `POST` | `/crew/quick_capture` | `crew_quick_capture` | Create quick-capture item. Returns JSON `{success, item_id}`. |
| `GET` | `/admin/items/needs_info` | `admin_needs_info_queue` | Admin queue for items with `is_quick_capture=True` and `status='needs_info'`. |

---

## Model Changes

### `User`

Add one field:

```
is_internal_account (Boolean, default False, server_default='0')
```

Migration required. No other User logic changes.

### `InventoryItem`

Add two fields:

```
is_quick_capture (Boolean, default False, server_default='0')
  — True on all items created via this flow. Never set elsewhere.

quick_capture_shift_id (Integer, FK → Shift, nullable)
  — Shift during which the item was captured. NULL if captured from crew dashboard.
```

Migration required.

**Field values on creation:**

| Field | Value |
|-------|-------|
| `description` | `''` (empty string) |
| `long_description` | `None` |
| `price` | `0` (or `None` if column is nullable — check current schema) |
| `status` | `'needs_info'` |
| `category_id` | `None` (already nullable per HANDOFF.md) |
| `seller_id` | Selected seller's id (or internal account id) |
| `photo_url` | Saved filename |
| `picked_up_at` | `_now_eastern()` — item is physically in the truck |
| `is_quick_capture` | `True` |
| `quick_capture_shift_id` | `shift_id` from POST body, or `None` |
| `collection_method` | `'free'` |
| `date_added` | `_now_eastern()` |

---

## Backend Logic: `crew_quick_capture`

```
@login_required
requires: current_user.is_worker and current_user.worker_status == 'approved'

1. Validate: photo file present in request.files
2. Validate: seller_id present and user exists (is_seller=True or is_internal_account=True)
3. If shift_id provided: verify shift exists and current_user is assigned to it
4. Process photo:
   - EXIF transpose (reuse existing helper)
   - RGBA → RGB
   - Resize to 2000px max (reuse existing helper)
   - Save as `qc_<timestamp>_<uuid4_hex[:8]>.jpg` to /var/data/
5. Create InventoryItem with fields as above
6. db.session.commit()
7. Return JSON {success: True, item_id: item.id}
```

No email sent. No approval queue. No Stripe. No seller notification.

---

## Admin Queue: `admin_needs_info_queue`

Route: `GET /admin/items/needs_info`

Renders a simple table of all items where `is_quick_capture=True` AND `status='needs_info'`, ordered by `date_added DESC`.

Columns: Item ID badge | Photo thumbnail | Seller name | Captured on shift (date + slot, or "No shift") | Date captured | Edit link → existing `/admin/edit_item/<id>` or equivalent.

Add a **"Quick Captures"** link in the admin nav (admin items section / ops tab). Show a count badge when queue is non-empty.

**Admin edit flow:** Admin clicks the edit link, fills in description, category, price, quality, then sets `status='available'`. No new route needed — this is the existing item edit flow. The `is_quick_capture` flag is informational only and never needs to change.

---

## Template Changes

### `crew/dashboard.html`

- Add a **"Quick Capture"** camera icon button near the top of the page (below the shift banner, above schedule).
- Button opens `#quick-capture-modal` via JS.
- No shift context available here — modal initializes with `shift_id=null`.

### `crew/shift.html`

- Add a camera icon button in the shift header area (top of page, near the shift title/status).
- Button opens `#quick-capture-modal` via JS, passing `shift_id` and the current active stop's `seller_id` via `data-*` attributes on the button.

### `crew/quick_capture_modal.html` (new partial)

Standalone modal partial. Included via `{% include %}` in both `crew/dashboard.html` and `crew/shift.html`.

Contains:
- `<video>` element for camera preview
- `<canvas>` (hidden) for frame capture
- `<img>` thumbnail (hidden until photo taken)
- Seller `<select>` dropdown (populated server-side, controlled by `data-*` on the trigger button)
- "Take Photo" / "Retake" / "Cancel" / "Save Item →" buttons
- Inline error div
- All JS inline in the partial (camera lifecycle, capture, POST, response handling)

The partial is inert until the modal is opened. Camera only activates on modal open.

### `admin/` (nav or items tab)

- Add "Quick Captures" link pointing to `/admin/items/needs_info`.
- Count badge showing number of pending quick-capture items (pass in context from relevant admin base view, or fetch via a small template macro).

---

## Business Logic & Edge Cases

**Seller dropdown when shift context exists but no active stop:**
Current active stop = first `ShiftPickup` with `status='pending'` for this driver's truck, ordered by `stop_order ASC`. If all stops are completed or no stops exist, no seller is "current" — default to Campus Swap.

**Seller dropdown contents when shift context exists:**
Pull all `ShiftPickup` records for this shift + this driver's `truck_number`. Deduplicate. Order by `stop_order ASC`. Prepend Campus Swap. This means a driver can assign a bonus item to any seller on their route that day, not just the current stop.

**Multiple photos:** Out of scope for V1. One photo per capture. Gallery can be added via the normal edit flow after the fact.

**Item visibility:** `status='needs_info'` means the item does NOT appear on the public shop (`/inventory` only shows `available`). It is invisible to buyers until admin completes the listing.

**Payout for Campus Swap items:** Items owned by `is_internal_account=True` users should be excluded from payout reconciliation display and CSV exports. Add a filter in the payout queue route: `seller.is_internal_account == False`.

**Worker role gating:** `crew_quick_capture` POST requires `is_worker=True` and `worker_status='approved'`. No shift assignment check — drivers can capture outside of shifts.

**`price` nullability:** If `price` is currently non-nullable with no default, the migration adding `is_quick_capture` should also add `server_default='0'` to `price` or the route must explicitly pass `price=0`. Confirm against current schema before implementing.

---

## Constraints

- Do not touch the normal seller onboarding flow, `add_item`, or `edit_item` routes.
- Do not modify the Stripe webhook handler or any payment logic.
- Do not change `status` progression logic — `needs_info` is already a valid status; quick-capture items just start there instead of being pushed there by admin.
- Do not make `seller_id` nullable on `InventoryItem`.
- The internal Campus Swap account must never appear in seller-facing UI (dashboard, onboarding, referral flows). Gate all seller-facing queries with `is_internal_account=False` where needed.
- Photo processing must reuse existing EXIF/resize helpers — do not write a second image pipeline.
- All JS in the modal must use `data-*` attributes for passing seller/shift context — no inline `tojson` in event handlers (per project rule #8).
