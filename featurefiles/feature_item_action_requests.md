# Feature Spec: Item Action Requests ("More Info Needed")

## Goal
Give admins a third option in the item approval queue — beyond Approve and Reject — that puts an item on hold and sends a clear, actionable alert to the seller's dashboard. The seller sees exactly what is needed, takes the action, and the item automatically re-enters the approval queue. This prevents good items from being rejected purely because of a bad photo or missing video.

---

## UX Flow

### Admin Side — Approval Queue (`/admin/approve`)

1. Admin is reviewing an item in the approval queue
2. Alongside the existing "Approve" and "Reject" buttons, a third button appears: **"More Info Needed"**
3. Admin clicks "More Info Needed"
4. A small modal or inline form appears with two parts:
   - **Preset reasons** (checkboxes, can select multiple):
     - "Better photos needed — current photos are unclear or low quality"
     - "Video required — please upload a video showing the item powers on"
     - "Better description needed — please add more detail about the item's condition"
     - "Different angle needed — please photograph [specific part] of the item"
   - **Optional custom note** (textarea, max 500 chars): *"Add a specific note to the seller (optional)"*
5. Admin clicks "Send Request"
6. The item's status changes to a new status: `needs_info`
7. The item disappears from the approval queue (it is no longer pending valuation in the normal sense)
8. The admin sees a success flash: *"Request sent. Item moved to 'Needs Info' status."*
9. A `SellerAlert` record is created and associated with the item and seller (see Model Changes)

### Seller Side — Dashboard (`/dashboard`)

1. Seller logs into their dashboard
2. A prominent alert banner appears at the top of their dashboard, above their item grid, styled in amber (`var(--accent)`) to draw attention:
   - Header: **"Action Needed"**
   - Body: Lists the reason(s) selected by the admin, plus any custom note
   - Example: *"We need a few things before we can approve your Mini Fridge: Better photos needed — current photos are unclear or low quality. Please re-upload and resubmit."*
   - A button: **"Update Item"** — links directly to `/edit_item/<id>`
3. The seller's item tile in "My Shop" also shows a status indicator: *"Action needed — see above"* in amber
4. Seller clicks "Update Item", goes to edit_item, uploads new photos / video / description
5. Seller clicks "Resubmit for Review" (a new button on the edit_item page, only visible when item status is `needs_info`)
6. On resubmit:
   - Item status changes back to `pending_valuation`
   - The `SellerAlert` record for this item is marked resolved (`resolved = True`)
   - The alert banner disappears from the seller's dashboard
   - The item re-enters the admin approval queue as normal
   - Admin sees it in the queue again with a small badge: **"Resubmitted"** so they know it was previously sent back

### Admin Side — Tracking
- In the main admin panel item table, items with status `needs_info` are visible with a distinct status badge: "Awaiting Seller" in amber
- Admin can cancel a "needs info" request at any time, which returns the item to `pending_valuation` and clears the seller's alert

---

## New Routes

| Method | Path | Function | Description |
|--------|------|----------|-------------|
| `POST` | `/admin/item/<id>/request_info` | `admin_request_info` | Admin submits "more info needed" request. Accepts `reasons` (list) and `custom_note`. Creates `SellerAlert`, sets item status to `needs_info`. Admin only. |
| `POST` | `/admin/item/<id>/cancel_request` | `admin_cancel_info_request` | Admin cancels an outstanding info request. Sets item back to `pending_valuation`, marks alert resolved. Admin only. |
| `POST` | `/item/<id>/resubmit` | `resubmit_item` | Seller resubmits item after addressing feedback. Only works if item status is `needs_info` and `current_user` is the item's seller. Sets status to `pending_valuation`, resolves alert. Login required. |

---

## Model Changes

### `InventoryItem.status`
Add `'needs_info'` as a valid status value to the existing status enum/string field. The full status list becomes:
`'pending_valuation'` | `'needs_info'` | `'approved'` | `'available'` | `'sold'` | `'rejected'`

This requires a Flask-Migrate migration to update any CHECK constraint or documentation — the field is a string column so no column type change is needed, but the migration should note the new valid value.

### New Model: `SellerAlert`
```
id                  — integer, primary key
item_id             — integer, FK to InventoryItem, nullable (some future alerts may not be item-specific)
user_id             — integer, FK to User (the seller receiving the alert)
created_by_id       — integer, FK to User (the admin who created it)
alert_type          — string: 'needs_info' | 'pickup_reminder' | 'custom' (extensible for future alert types)
reasons             — text, JSON-encoded list of preset reason strings
custom_note         — text, nullable
resolved            — boolean, default False
resolved_at         — datetime, nullable
created_at          — datetime, default now
```

This model is designed to be reused by the seller profile panel feature (custom messages from admin) and the pickup nudge feature (pickup reminders), so it is built generically from the start.

A Flask-Migrate migration is required to create this table.

---

## Template Changes

### `templates/admin_approve.html`
- Add "More Info Needed" button alongside Approve / Reject for each item
- Keyboard shortcut: `I` (for "info needed") to match existing `A` / `R` shortcuts
- Add a small modal (vanilla JS, no libraries) that appears on click:
  - Checkbox list of preset reasons
  - Optional textarea for custom note
  - "Send Request" and "Cancel" buttons
  - POST to `/admin/item/<id>/request_info` on submit
- Items with status `needs_info` should be filterable / visible in the queue with an "Awaiting Seller" badge

### `templates/admin.html`
- Item lifecycle table: add `needs_info` as a recognized status with an amber "Awaiting Seller" badge
- "Cancel Request" action button for items in `needs_info` status

### `templates/dashboard.html`
- At the top of the page, before the item grid, check for any unresolved `SellerAlert` records for the current user where `resolved = False`
- For each unresolved alert tied to an item:
  - Render an amber alert card with the reasons listed and the custom note (if any)
  - Include an "Update Item" button linking to `/edit_item/<item_id>`
- Item tiles in "My Shop" for items in `needs_info` status:
  - Show amber background (consistent with existing color-coding: red=rejected, green=sold, yellow=in process)
  - Status text: "Action needed — see above"

### `templates/edit_item.html`
- When item status is `needs_info`, show a banner at the top of the edit form reminding the seller what was requested (pull from the unresolved `SellerAlert` for this item)
- Add a "Resubmit for Review" button at the bottom of the form, only visible when `item.status == 'needs_info'`
- This button POSTs to `/item/<id>/resubmit`
- On successful resubmit, redirect to `/dashboard` with a success flash: *"Item resubmitted for review. We'll be in touch soon."*

---

## Business Logic

### Status Transition Rules
- `needs_info` can only be set by an admin (via `/admin/item/<id>/request_info`)
- `needs_info` → `pending_valuation` happens in two ways:
  1. Seller resubmits via `/item/<id>/resubmit`
  2. Admin cancels the request via `/admin/item/<id>/cancel_request`
- An item in `needs_info` status should NOT appear in the standard approval queue count (it is not "new" — the admin has already seen it)
- An item that has been resubmitted SHOULD appear in the approval queue with a "Resubmitted" badge so the admin knows context

### Alert Resolution Logic
- A `SellerAlert` of type `needs_info` is marked `resolved = True` when:
  - The seller resubmits the item (sets `resolved_at` to now)
  - The admin cancels the request (also sets `resolved_at` to now)
- If a seller has multiple unresolved alerts (multiple items needing info), each shows as a separate alert card on the dashboard
- Resolved alerts are not shown on the dashboard but are retained in the database for audit purposes

### Validation
- Admin must select at least one preset reason OR write a custom note — cannot send an empty request
- Custom note max 500 characters
- Only items in `pending_valuation` status can be sent to `needs_info` — cannot use this on already-approved or sold items

### Edge Cases
- **Seller resubmits without actually changing anything:** Allowed — the system does not diff the submission. The admin will see "Resubmitted" badge and can send another info request if needed.
- **Item has been sent back multiple times:** Each send creates a new `SellerAlert` record. The dashboard shows all unresolved alerts. The edit_item banner shows the most recent unresolved alert for that item.
- **Admin approves an item that is in `needs_info`:** Should not be possible from the normal approval queue since the item won't appear there. If an admin navigates directly to the item, the approve action should still work and automatically resolve any outstanding alert.

---

## Constraints
- Do not change the Approve or Reject flows — this is a purely additive third option
- Do not send an email to the seller when a "more info needed" request is created — the dashboard alert is the sole notification mechanism for this feature
- Do not remove items from the database or change `seller_id` or any item metadata when setting `needs_info` status
- The `SellerAlert` model must be built generically enough to support the pickup nudge feature and admin seller profile panel — do not make it specific to photo requests only
