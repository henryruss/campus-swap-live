# Feature Spec: Pickup Week Updates

## Goal
Expand the pickup scheduling step to collect three pieces of information instead of one: which week, preferred time of day, and actual move-out date. This gives the Campus Swap team enough data to cluster pickups by neighborhood and time window, reducing the number of trips and giving sellers more predictable pickup windows.

---

## Current State
The confirm_pickup flow currently collects:
- Pickup week: `'week1'` or `'week2'` (stored in `User.pickup_week`)
- Address/phone (if not already on file)
- Payment ($15 for Pro sellers)

The pickup week dates in the current codebase are April 26–May 2 and May 3–May 9. **These dates are being updated as part of this spec.**

---

## New Data to Collect

### 1. Pickup Week (updated date ranges)
- **Week 1:** April 27 – May 3
- **Week 2:** May 4 – May 10
- Stored in existing `User.pickup_week` field as `'week1'` or `'week2'` (no change to field name or values — just the display dates change everywhere they are shown)

### 2. Preferred Time of Day (new)
Three options, radio buttons:
- **Morning** — 9am to 1pm
- **Afternoon** — 1pm to 5pm
- **Evening** — 5pm to 9pm

Stored in new field `User.pickup_time_preference` (string: `'morning'` | `'afternoon'` | `'evening'`).

This is a preference, not a guarantee — the UI should make this clear: *"We'll do our best to accommodate your preference, but we can't guarantee an exact time."*

### 3. Move-Out Date (new, optional)
A date picker asking: *"Do you know your exact move-out date? (Optional)"*
- Shows a calendar date picker constrained to the date range of whichever pickup week they selected (Week 1: April 27–May 3, Week 2: May 4–May 10)
- If they don't know, they can leave it blank
- Stored in new field `User.moveout_date` (Date field, nullable)

---

## UX Flow

### Confirm Pickup Flow (`/confirm_pickup`) — Updated Step 1

The existing Step 1 collects only the pickup week via two radio buttons. The updated Step 1 collects all three new fields on the same screen (or as an expanded step — implementation can keep it as one screen since the fields are related).

**Updated Step 1 layout:**

**Pickup Week** (required)
```
○ Week 1: April 27 – May 3
○ Week 2: May 4 – May 10
```

**Preferred Time of Day** (required)
```
○ Morning  — 9am to 1pm
○ Afternoon — 1pm to 5pm
○ Evening  — 5pm to 9pm
```
*Subtext: "We'll do our best to match your preference."*

**Move-Out Date** (optional)
```
[ Date picker — calendar ]
"If you know your exact move-out date, enter it here. Leave blank if you're not sure."
```
- Date picker should only show dates within the selected pickup week range
- If the seller changes their week selection, the date picker resets and updates its allowed range
- If left blank, that is fine — `moveout_date` will be null

The rest of the confirm_pickup flow (Step 2: Address & Phone, Step 3: Review & Pay) remains unchanged.

### Upgrade Pickup Flow (`/upgrade_pickup`)
Same change — if this flow also has a week selection step, add the time-of-day and move-out date fields there as well.

### Dashboard Display
In the seller's dashboard stats bar, the "Pickup Window" stat currently shows the selected week or "pending." Update it to show:
- If pickup week + time preference selected: *"Week 1 · Morning"* (abbreviated)
- If only week selected (legacy data): *"Week 1"*
- If neither selected: *"Not scheduled"* (amber)

### Admin Visibility
- In the seller profile panel (`feature_admin_seller_profile.md`), the Pickup Info section already specifies showing `pickup_time_preference` and `moveout_date`
- In the admin panel item lifecycle table, no changes needed — week-level granularity is sufficient there
- In the CSV export for users (`/admin/export/users`), add the two new fields: `pickup_time_preference` and `moveout_date`
- In the pickup nudge section (`feature_pickup_nudge.md`), a seller is considered "missing pickup week" if `pickup_week` is null — the time preference and moveout date are not required to be considered "scheduled"

---

## New Routes
None. The existing `/confirm_pickup` POST handler is updated to accept and save the new fields.

---

## Model Changes

### `User` — two new fields
```python
pickup_time_preference = db.Column(db.String(20), nullable=True)
# Values: 'morning' | 'afternoon' | 'evening' | None

moveout_date = db.Column(db.Date, nullable=True)
# Nullable — seller may not know their exact date
```

A Flask-Migrate migration is required:
```
flask db migrate -m "add pickup_time_preference and moveout_date to user"
```

Migration should add both columns as nullable with no default. Existing rows will have NULL for both fields — this is correct and expected.

---

## Template Changes

### `templates/confirm_pickup.html` — Step 1
- Add time-of-day radio button group below the existing week selection
- Add optional date picker below time-of-day
- Date picker behavior: constrain visible dates to the selected week's range using JavaScript
  - Week 1 selected → only show April 27–May 3 as selectable
  - Week 2 selected → only show May 4–May 10 as selectable
  - Week changes → reset date picker value
- Use a standard HTML `<input type="date">` with `min` and `max` attributes set dynamically via JS
- Include helpful subtext under each new field as described above
- Both new fields must be included in the form POST (time preference as required, moveout_date as optional/nullable)

### `templates/upgrade_pickup.html`
- Same additions as confirm_pickup.html if this template has a week selection step

### `templates/dashboard.html`
- Update the "Pickup Window" stat cell to show week + time preference if both are set
- Format: *"Wk 1 · Morning"* or *"Wk 2 · Afternoon"* — keep it short to fit the stat bar
- If `pickup_time_preference` is null but `pickup_week` is set (legacy seller): just show *"Week 1"* as before

---

## Business Logic

### Validation (server-side, in `/confirm_pickup` POST handler)
- `pickup_week`: required, must be `'week1'` or `'week2'`
- `pickup_time_preference`: required, must be `'morning'`, `'afternoon'`, or `'evening'`
- `moveout_date`: optional. If provided, must be a valid date within the range of the selected pickup week:
  - Week 1: April 27, 2026 – May 3, 2026
  - Week 2: May 4, 2026 – May 10, 2026
  - If a date is provided outside the selected week's range, return a validation error: *"Move-out date must fall within your selected pickup week."*

### Date Storage
- Store `moveout_date` as a Python `datetime.date` object in the database (SQLAlchemy `db.Column(db.Date)`)
- When displaying, format as *"Mon, Apr 28"* — do not include the year (it's always 2026 in context)

### Backward Compatibility
- Existing sellers who already selected a pickup week before this feature is deployed will have `pickup_time_preference = None` and `moveout_date = None`
- These sellers should NOT be prompted to re-complete the pickup step — their `pickup_week` is already set and that is sufficient for them to be considered "scheduled"
- The dashboard stat for these legacy sellers shows their week only (no time preference)
- If an admin wants to know their time preference, the seller can update it from Account Settings (see below)

### Account Settings Update
- In `templates/account_settings.html`, if a seller has already selected a pickup week, show a read-only display of their pickup week + time preference + move-out date
- Allow them to update `pickup_time_preference` and `moveout_date` (but NOT `pickup_week` — that is locked once set, as per existing logic)
- This requires a small update to the `POST /update_profile` handler to accept and save these two fields

---

## Constraints
- Do not change `User.pickup_week` field name or its values (`'week1'`/`'week2'`) — only update the display dates wherever they are shown in templates
- Do not make `moveout_date` required — it is explicitly optional and null is a valid permanent state
- Do not change the payment flow or the Stripe checkout steps — this spec only changes what data is collected before/during the pickup scheduling step
- Do not change pickup week selection for free-tier sellers — their flow goes through admin confirmation, but once they reach the pickup scheduling step, the same new fields apply
- Update all hardcoded references to the old pickup week date ranges (April 26–May 2, May 3–May 9) across all templates and any Python constants to the new ranges (April 27–May 3, May 4–May 10)
