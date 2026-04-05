# Feature Spec: Pickup Nudge — Missing Pickup Week View

## Goal
Give admins a fast way to see every seller who has approved items but hasn't completed pickup scheduling, and send them a reminder — either to all of them at once or to selected individuals. This prevents sellers from falling through the cracks during the critical pickup window.

---

## Who Needs a Nudge — Definition

A seller appears on this list if ALL of the following are true:
1. They have at least one item with status `approved` or `available` (i.e. past the pending/needs_info stage)
2. They have NOT selected a pickup week (i.e. `User.pickup_week` is null or empty)
3. They are a Pro seller (`collection_method = 'online'`) OR a Free seller who has been confirmed by admin (`is confirmed free tier`)
4. They have not been rejected from the free tier

A seller does NOT appear on this list if:
- All their items are still `pending_valuation`, `needs_info`, or `rejected` — they can't schedule yet
- They have already selected a pickup week
- Their free-tier application was rejected

---

## UX Flow

### Location
A dedicated section on the existing admin panel (`/admin`), placed after the main item lifecycle table and before or within the free-tier management section. It is collapsible (collapsed by default to avoid cluttering the page) with a header showing the count: **"Pickup Week Not Selected (X sellers)"** — the count is in amber if X > 0, grey if X = 0.

### The List
When expanded, the section shows a table with one row per seller:

| Column | Content |
|--------|---------|
| Seller name | Clickable — opens seller profile panel (from `feature_admin_seller_profile.md`) |
| Email | Plain text |
| Phone | Plain text or "—" |
| Service tier | Free / Pro badge |
| Approved items | Count of items in `approved` or `available` status |
| Days since approval | How many days since their first item was approved — highlights urgency |
| Last nudged | Date of last pickup reminder alert sent, or "Never" |
| Select | Checkbox for individual selection |

### Actions
Two buttons above the table:

1. **"Remind All"** — sends a pickup reminder alert to every seller currently shown in the list (all, not just checked ones). Requires a confirmation dialog: *"Send pickup week reminder to all X sellers who haven't selected a week? This will appear on their dashboards."* → Confirm / Cancel.

2. **"Remind Selected"** — only active when at least one checkbox is checked. Sends reminder to checked sellers only. No confirmation dialog needed for individual sends.

### After Sending
- The "Last nudged" column updates immediately to today's date for sellers who were just reminded
- A flash message: *"Reminder sent to X seller(s)."*
- Sellers who receive the nudge do NOT disappear from the list until they actually select a pickup week — the list reflects current state, not whether they've been nudged

---

## New Routes

| Method | Path | Function | Description |
|--------|------|----------|-------------|
| `POST` | `/admin/pickup-nudge/send` | `admin_send_pickup_nudge` | Sends pickup reminder alerts. Accepts `user_ids` (list) — if empty or `'all'`, sends to all eligible sellers. Creates `SellerAlert` records. Admin only. |

---

## Model Changes

### `SellerAlert` (from `feature_item_action_requests.md`)
Uses the existing model with `alert_type = 'pickup_reminder'`. No additional fields needed.

The `item_id` field is left null for pickup reminder alerts since the reminder is about the seller's account status, not a specific item.

**Dependency:** `feature_item_action_requests.md` must be implemented first, or simultaneously, since this feature depends on the `SellerAlert` model.

### No changes to `User` model needed
`User.pickup_week` already exists. The query to find sellers without a pickup week is:
```python
sellers_without_pickup = User.query.filter(
    User.is_seller == True,
    User.pickup_week == None,  # or empty string
    User.items.any(InventoryItem.status.in_(['approved', 'available']))
).all()
```
Filter out rejected free-tier sellers as described in the definition above.

---

## Template Changes

### `templates/admin.html`
Add a new collapsible section after the item lifecycle table:

```html
<div class="admin-section" id="pickup-nudge-section">
  <div class="admin-section__header" onclick="toggleSection('pickup-nudge')">
    <h3>Pickup Week Not Selected
      <span class="badge {% if count > 0 %}badge--amber{% else %}badge--muted{% endif %}">
        {{ count }}
      </span>
    </h3>
    <span class="toggle-icon">▼</span>
  </div>
  <div class="admin-section__body" id="pickup-nudge-body">
    <!-- table + action buttons -->
  </div>
</div>
```

The section body contains:
- "Remind All" and "Remind Selected" buttons (described above)
- The seller table with checkboxes
- "Select All" / "Deselect All" checkbox in the table header

JavaScript:
- Toggle collapse/expand behavior for the section
- Checkbox select/deselect all
- "Remind Selected" button enables/disables based on whether any checkboxes are checked
- Both action buttons POST to `/admin/pickup-nudge/send` with the appropriate `user_ids` payload
- On success response, update the "Last nudged" column for affected rows without full page reload (fetch + partial update)

### `templates/dashboard.html` — Seller Side
When a seller has an unresolved `SellerAlert` with `alert_type = 'pickup_reminder'`:
- Show an alert card in the existing alert banner area (same area used by `feature_item_action_requests.md`)
- Alert card copy: **"Action needed: Please select your pickup week."**
- Body: *"Your items are approved and ready to go — we just need to know when to pick them up. Select your pickup week to lock in your spot."*
- Button: **"Select Pickup Week"** → links to `/confirm_pickup`
- Alert resolves automatically (mark `resolved = True`) when the seller successfully completes `/confirm_pickup` and a `pickup_week` value is saved to their account

### Alert Auto-Resolution Logic
In the `/confirm_pickup` POST handler (or the Stripe webhook that finalizes Pro seller activation):
- After saving `user.pickup_week`, query for any unresolved `SellerAlert` records for this user with `alert_type = 'pickup_reminder'`
- Set `resolved = True` and `resolved_at = datetime.utcnow()` for all of them
- This ensures the dashboard banner disappears as soon as they've completed the action

---

## Business Logic

### Deduplication — Don't Spam Sellers
- Before sending a nudge to a seller, check if they already have an unresolved `SellerAlert` of type `pickup_reminder`
- If yes: do not create a duplicate. Skip that seller silently and don't count them in the success flash count.
- The "Last nudged" column in the admin table reflects the most recent alert sent, resolved or not, so the admin can see if they've already been contacted recently

### "Remind All" Scope
- "Remind All" only sends to sellers currently visible in the list — i.e. sellers who still haven't selected a pickup week at the moment the button is clicked
- It does not send to sellers who selected a pickup week between when the page loaded and when the button was clicked — the backend re-queries at send time, it does not use a cached list from page load

### Ordering
- Default sort: most urgent first — sellers with the most days since approval at the top
- Secondary sort: alphabetical by name

### Edge Cases
- **Admin clicks "Remind All" when list is empty:** Button should be disabled (greyed out) when count = 0
- **Seller selects pickup week while admin is looking at the list:** On next page load or section refresh, that seller disappears from the list. If admin sends a nudge before refreshing, the backend skips them (deduplication logic above)
- **Seller is on free tier but not yet confirmed:** They should NOT appear on this list — they can't select a pickup week until admin confirms them
- **Seller has a mix of approved and pending items:** They still appear on the list as long as at least one item is approved — the nudge is about the account-level pickup week, not per item

---

## Constraints
- Do not send emails for pickup nudges — dashboard alerts only (consistent with the rest of the alert system)
- Do not remove sellers from the list just because they've been nudged — only remove them when they actually select a pickup week
- Do not build a separate page for this feature — it lives in the existing admin panel as a collapsible section
- The `SellerAlert` model must be shared with `feature_item_action_requests.md` and `feature_admin_seller_profile.md` — do not create a separate model for pickup reminders
