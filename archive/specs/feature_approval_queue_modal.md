# Feature Spec: Approval Queue Modal

**Status:** Ready for Claude Code
**Applies to:** is_admin, is_super_admin (approval queue is already gated to these roles)
**Estimated complexity:** Small-Medium — no model changes, one new partial route, JS modal

---

## Goal

The current approval queue (`/admin/items?view=approve`) shows a card grid of
pending items. Each card has a price input and action buttons, but the seller's
uploaded photos, long description, and suggested price are not visible — the
reviewer has to click "View Full Item" which opens a new tab, then scroll down
to approve/reject there. After five items, five tabs are open.

Replace this with a single-page modal flow: clicking any item card opens a
full-detail modal with photos, all item info, price input, and action buttons
inline. No new tabs. No page navigation. One page, one workflow.

---

## UX Flow

1. Admin visits `/admin/items?view=approve`
2. Sees the existing card grid of pending items (cards remain, but are now
   clickable triggers rather than self-contained action forms)
3. Clicks any card → modal slides up / fades in over the page
4. Modal shows: full photo gallery, item title, long description, category,
   suggested price, seller name (→ existing seller panel), date submitted, and
   quality rating
5. Admin sets the price in the price input (pre-filled with `suggested_price`
   if present)
6. Clicks Approve, Reject, or Need Info
7. Action fires via fetch POST to existing routes
8. On success: modal closes, the card for that item is removed from the grid
   (DOM removal, no page reload), next item is ready to click
9. Keyboard shortcut: Escape closes the modal without action

---

## What Changes

### `admin/items.html` — approval queue card grid

**Card changes:**
- Remove the inline price input form and action buttons from each card
- Make the entire card a clickable trigger: `data-item-id="<id>"` attribute
- Card still shows: cover photo thumbnail, item title, seller name, category,
  date submitted, suggested price (as a read-only badge — not an input)
- Add a subtle "click to review" affordance (e.g. a small arrow icon or hover
  state that lifts the card)
- Keep the existing "Approval Queue" sub-tab pill and stats bar unchanged

**Modal (injected into the page, one instance reused for all items):**

```html
<div id="approval-modal" class="approval-modal-overlay" hidden>
  <div class="approval-modal-panel">
    <button class="approval-modal-close">×</button>

    <!-- Photo gallery -->
    <div class="approval-modal-gallery">
      <!-- Cover photo + gallery thumbnails, same pattern as existing item gallery -->
    </div>

    <!-- Item info -->
    <div class="approval-modal-info">
      <h2 class="approval-modal-title"></h2>
      <div class="approval-modal-meta">
        <!-- Seller name (→ panel), category, quality stars, date submitted -->
      </div>
      <p class="approval-modal-description"></p>

      <!-- Suggested price callout (if present) -->
      <div class="approval-modal-suggested-price">
        Seller suggested: $<span class="suggested-value"></span>
      </div>

      <!-- Price input -->
      <label>Set listing price</label>
      <input type="number" id="approval-price-input" step="0.01" min="0"
             placeholder="e.g. 45.00">

      <!-- Actions -->
      <div class="approval-modal-actions">
        <button id="btn-approve" class="btn-primary">Approve</button>
        <button id="btn-need-info" class="btn-outline">Need Info</button>
        <button id="btn-reject" class="btn-outline btn-danger">Reject</button>
      </div>

      <!-- Inline error/status message area -->
      <p id="approval-modal-status" hidden></p>
    </div>
  </div>
</div>
```

**Modal behavior:**
- Modal content is populated from a fetch call when a card is clicked (see new
  route below) — do not embed all item data in the card's `data-*` attributes,
  as long descriptions and gallery arrays are too large
- While loading: show a spinner inside the modal panel
- Overlay click or Escape key closes the modal (same pattern as existing seller
  profile panel)
- Modal is not scrollable on the overlay — only the panel interior scrolls
- On mobile: modal takes full viewport height, gallery stacks above info

**Approve action:**
- Fetch `POST /admin/approve` with `item_id`, `price`, `action=approve`
  (existing route, existing payload format — confirm exact field names in
  `app.py` before implementing)
- On success: close modal, remove card from grid DOM, decrement pending count
  badge
- On error (e.g. missing price): show inline error in `#approval-modal-status`,
  do not close modal

**Reject action:**
- Fetch `POST /admin/approve` with `item_id`, `action=reject`
- On success: close modal, remove card from grid DOM

**Need Info action:**
- Fetch `POST /admin/item/<id>/request_info` (existing route)
- On success: close modal, remove card from grid DOM (item leaves the approval
  queue since it's now `needs_info`)

**After all cards are removed:**
- Show the existing empty-queue state ("No items pending approval" or equivalent)

### New partial route

**`GET /admin/item/<id>/approval-detail`** → `admin_item_approval_detail`

Returns an HTML partial (no layout) with all item data needed to populate the
modal:
- All gallery photos (cover + `ItemPhoto` records)
- `description`, `long_description`, `suggested_price`, `quality`
- `category.name`
- `date_added`
- `seller.full_name`, `seller.id` (for the seller panel link)

Auth: `is_admin or is_super_admin` (same as the approval queue page).
Only callable for items with `status='pending_valuation'` — return 404 for
anything else (prevents approving already-actioned items via stale modal).

Returns HTML partial that Claude Code renders into the modal panel via
`innerHTML` replacement (same pattern as `admin_ops_truck_detail`).

### Styling

Use existing CSS variables throughout. New classes needed:

```css
.approval-modal-overlay   /* fixed, full viewport, semi-transparent bg */
.approval-modal-panel     /* centered card, max-width ~800px, scrollable interior */
.approval-modal-gallery   /* horizontal scroll or grid of photos */
.approval-modal-close     /* top-right × button */
.approval-modal-actions   /* button row, space-between */
.btn-danger               /* red-tinted outline variant for Reject */
```

The modal panel should feel like the existing seller profile panel (same
card shadow, border radius, white background). The gallery should use the
same photo rendering pattern as the public item pages.

---

## New Routes

| Method | Path | Function | Description |
|---|---|---|---|
| `GET` | `/admin/item/<id>/approval-detail` | `admin_item_approval_detail` | Returns HTML partial with full item data for modal population. Auth: is_admin or is_super_admin. 404 if item not pending_valuation. |

**Existing routes used (unchanged):**
- `POST /admin/approve` — Approve and Reject actions (confirm exact payload)
- `POST /admin/item/<id>/request_info` — Need Info action

---

## Model Changes

None. No migrations needed.

---

## Constraints — Do Not Touch

- The existing approval POST routes (`admin_approve`, `admin_request_info`) are
  unchanged — only called via fetch instead of form submit
- The "All Items" sub-tab on `/admin/items` is completely unchanged
- The quick-captures queue at `/admin/items/needs_info` is completely unchanged
- The seller profile panel (slide-out drawer) still works when seller name is
  clicked inside the modal — both can be open simultaneously
- Stats bar counts unchanged
- `layout.html` and `admin_layout.html` untouched (modal lives in the items
  template, not the layout)

---

## Definition of Done

- [ ] Approval queue cards are clickable and no longer contain inline forms
- [ ] Clicking a card opens the modal with a loading spinner, then full item detail
- [ ] Modal shows all gallery photos, description, suggested price, category, seller
- [ ] Price input is pre-filled with `suggested_price` if present
- [ ] Approve fires fetch POST, closes modal, removes card from grid
- [ ] Reject fires fetch POST, closes modal, removes card from grid
- [ ] Need Info fires fetch POST, closes modal, removes card from grid
- [ ] Missing price on Approve shows inline error, modal stays open
- [ ] Escape key and overlay click close modal without action
- [ ] After last card is removed, empty-queue state is shown
- [ ] Seller name in modal opens the existing seller profile panel
- [ ] Works correctly on mobile (full-height modal, stacked layout)
- [ ] No new tabs opened at any point in the flow
- [ ] Existing "All Items" tab behavior completely unchanged
