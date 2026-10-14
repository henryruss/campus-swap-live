# Feature Spec: Reservation System

## Goal

Build a reservation system that lets buyers browse real inventory before the store opens, then lock in items once it does — without payments or deposits. The system creates hype during the pre-launch inventory-building period, converts browsers into committed buyers on opening day, and gives staff a clear picture of what's spoken for in the store.

This spec also includes a bug fix for duplicate reservations on the same item across multiple accounts.

---

## AppSettings Used

All configurable behavior is driven by existing `AppSetting` key-value flags. Two new keys are added:

| Key | Type | Example | Purpose |
|---|---|---|---|
| `store_open_date` | string (ISO date) | `2025-06-01` | Date reservations go live and countdown disappears |
| `reserve_only_mode` | string boolean | `'true'` / `'false'` | Already exists — keep using to hide buy buttons |

Helper to add in `app.py` or a utils file:

```python
from datetime import date

def store_is_open():
    val = AppSetting.get('store_open_date', '2025-06-01')
    return date.today() >= date.fromisoformat(val)

def store_open_date():
    return AppSetting.get('store_open_date', '2025-06-01')
```

---

## Model Changes

### `ItemReservation` — add two fields

```python
expires_at   = db.Column(db.DateTime, nullable=False)  # set at creation
cancelled_at = db.Column(db.DateTime, nullable=True)    # set on user cancellation
```

**Migration required.** `created_at` already exists. No other model changes needed.

**Expiry logic (set at reservation creation):**

```python
from datetime import datetime, timedelta

RESERVATION_HOLD_DAYS = 3

def compute_expiry():
    store_open = datetime.fromisoformat(AppSetting.get('store_open_date', '2025-06-01'))
    now = datetime.utcnow()
    start = max(now, store_open)
    return start + timedelta(days=RESERVATION_HOLD_DAYS)
```

Before the store opens, `max(now, store_open)` returns `store_open`, so all reservations made in May expire on June 4. After June 1, `max(now, store_open)` returns `now`, giving a rolling 3-day window from the moment of reservation.

**Active reservation helper (lazy expiry):**

```python
def get_active_reservation(item_id):
    return ItemReservation.query.filter_by(item_id=item_id).filter(
        ItemReservation.expires_at > datetime.utcnow(),
        ItemReservation.cancelled_at == None
    ).first()
```

Call this everywhere instead of querying `ItemReservation` directly. No background job needed — expiry is checked at read time.

---

## UX Flow

### Before store opens (before `store_open_date`)

- Inventory page shows all available items, browsable as normal
- A countdown banner appears at the top of `/inventory` and `/item/<id>` pages:
  > **Reservations open June 1** — Browse what's coming and be ready to grab your item the moment we open.
- No reserve button appears anywhere. Items are browse-only.
- Banner disappears automatically once `store_is_open()` returns True

### On and after store opens

- Countdown banner is gone
- Reserve button appears on item cards and product pages for all `available` items with no active reservation
- Items with an active reservation show a **"Reserved"** badge — no reserve button

### Reserving an item

1. User clicks "Reserve" on an item card or product page
2. If not logged in → redirect to `/login?next=/item/<id>` → after login, redirect back to product page
3. If logged in, check:
   - Item already has an active reservation → flash error "This item is already reserved" → redirect back
   - User already has 3 active reservations → flash error "You can only reserve 3 items at a time" → redirect back
   - User already has an active reservation on this specific item → flash error "You've already reserved this item" → redirect back
4. All checks pass → create `ItemReservation` with `expires_at = compute_expiry()` → flash success "Item reserved! It's yours until [date]." → redirect back to product page

### Cancelling a reservation

1. On the product page, if the current user holds the active reservation, show a "Cancel reservation" link below the reserved badge
2. POST to `/cancel_reservation/<item_id>`
3. Set `cancelled_at = datetime.utcnow()` on the reservation (soft delete — don't hard delete for admin audit purposes)
4. Flash "Reservation cancelled. The item is now available again." → redirect to `/inventory`

### Reservation expiry (lazy)

- Every time `get_active_reservation(item_id)` is called and returns None (because `expires_at` is in the past), the item is automatically back to available — no admin action needed
- An expiry email is sent to the reserver (see Emails section below)
- Expiry email is triggered at the moment expiry is first detected (on next page load after expiry), not by a scheduled job

### Reservation limit enforcement

- Before creating a reservation, count the user's currently active reservations:
  ```python
  active_count = ItemReservation.query.filter_by(user_id=current_user.id).filter(
      ItemReservation.expires_at > datetime.utcnow(),
      ItemReservation.cancelled_at == None
  ).count()
  ```
- If `active_count >= 3`, block with flash error

---

## New Routes

| Method | Path | Function | Description |
|---|---|---|---|
| `POST` | `/reserve_item/<id>` | `reserve_item` | Create a reservation (replaces existing stub) |
| `POST` | `/cancel_reservation/<id>` | `cancel_reservation` | Cancel user's own reservation |

Both require `@login_required`. The existing `GET /reserve_item/<id>` should be converted to `POST` or kept as a redirect-to-login flow — confirm which pattern exists and match it.

---

## Template Changes

### `inventory.html`

- Add countdown banner at top (conditionally rendered):
  ```jinja
  {% if not store_is_open() %}
  <div class="reservation-countdown-banner">
    Reservations open {{ store_open_date() }} — browse what's coming.
  </div>
  {% endif %}
  ```
- On each item card, conditionally show:
  - If `store_is_open()` is False → no action button, browse only
  - If item has active reservation → "Reserved" badge (no button)
  - If item available and store open → "Reserve" button (POST form)
- Pass `active_reservations` dict (keyed by item_id) from the route to avoid N+1 queries — compute once in the view function

### `product.html`

- Same countdown banner logic as inventory
- If store not open → no reserve button, show "Reservations open [date]"
- If item reserved by current user → show "Reserved by you until [date]" + "Cancel reservation" link
- If item reserved by someone else → show "Reserved" badge, no button
- If item available and store open → "Reserve" button

### `admin.html`

- In the item list/table, add a "Reservation" column showing:
  - If active reservation: **Reserved** — [User full name] until [expires_at date]
  - If no reservation: —
- This gives staff a clear view of what's spoken for in the store
- No admin action needed to manage reservations — display only

---

## Emails

### Reservation confirmation (send on creation)

**To:** reserver  
**Subject:** "You reserved [item description] — Campus Swap"  
**Body:** Confirm the item, show the expiry date, include a link to the product page and a way to cancel if they change their mind.

### Reservation expired (send on first detection of expiry)

**To:** reserver  
**Subject:** "Your reservation for [item description] expired"  
**Body:** Let them know the item is back to available and they can reserve it again if they want. Include a link back to the item.

Use a flag to avoid sending the expiry email multiple times. Options:
- Add an `expiry_email_sent` boolean to `ItemReservation` (cleanest, requires migration field)
- Or check `cancelled_at IS NULL AND expires_at < now` and send only once by setting `cancelled_at` to expiry time when detected (reuses existing field, slightly hacky)

**Recommendation:** Add `expiry_email_sent = db.Column(db.Boolean, default=False)` to the model — include in the same migration as `expires_at` and `cancelled_at`.

---

## Business Logic & Edge Cases

**Item sold while reserved:** If admin marks an item sold, the reservation becomes moot. No special handling needed — the item just won't show up as available. Admin should be aware (via the reservation column) that a reserved item being sold means the reserver should be notified manually for now.

**User deletes account:** Reservation orphans. Not a concern at current scale — cascade delete handles it at the DB level if FK is set with `ondelete='CASCADE'`.

**Same user, two accounts, same item:** The per-item active reservation check (`get_active_reservation`) blocks the second reservation regardless of which account is trying. This is the bug fix — it's handled by checking item-level reservation existence, not user-level uniqueness.

**Store open date changes:** If you move the date earlier, reservations made before the change keep their original `expires_at`. That's fine — they were computed correctly at creation time.

**Item status vs reservation:** Item stays in `available` status while reserved. The reservation is a separate layer on top of status. Don't add a `reserved` status to `InventoryItem` — it adds complexity without benefit since reservations expire automatically.

---

## Constraints — Do Not Touch

- Existing Stripe checkout and webhook logic
- `reserve_only_mode` AppSetting — keep using it to control buy button visibility separately from reservation logic
- `picked_up_at` and `arrived_at_store_at` fields — not used as triggers in this feature
- Item status lifecycle (`pending_valuation → approved → available → sold`) — unchanged
- Existing image upload logic in `add_item.html`
