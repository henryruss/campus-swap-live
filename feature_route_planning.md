# Spec #6 — Route Planning

**Status:** Draft — awaiting sign-off  
**Depends on:** Spec #2 (Shift Scheduling) ✅  
**Unlocks:** Spec #8 (Seller Rescheduling), Spec #9 (SMS Notifications)  
**Last updated:** 2026-04-13

---

## Goal

Close the gap between "sellers have a pickup week preference" and "trucks have ordered stop lists with real addresses." Right now, sellers are manually added to shifts one by one on the ops page with no capacity awareness and no routing logic. This spec adds:

1. **Item unit sizing** — categories get configurable unit values so the system knows how much physical space a seller's items consume in a truck. Admin can override per item at approval time.
2. **Truck capacity management** — configurable raw capacity + buffer %, with a live load gauge per truck.
3. **Auto-assignment** — admin clicks "Run Auto-Assignment" to populate shifts based on seller week preference, AM/PM time preference, geographic clustering, and truck capacity. Admin reviews and corrects the result inline.
4. **Truck creation on the fly** — admin can add a new truck to any shift at any time (including mid-shift), with a "workers TBD" state and manual stop rebalancing.
5. **Geographic clustering** — sellers at the same building (dorm name first, lat/lng fallback) are surfaced together so admin can spot groupings and keep nearby stops on the same truck.
6. **Stop ordering** — system auto-orders stops using nearest-neighbor from the storage unit; admin can reorder. Each shift gets a static Google Maps image showing all stops.
7. **Seller notification** — admin triggers a pickup confirmation email per shift once the route is finalized. Surfaced in Spec #7 progress tracker.
8. **Mover upgrades** — stops appear in order with a "Navigate →" button per stop; stop list auto-refreshes in real time so last-minute additions appear within 30 seconds.
9. **Real-time issue alerts** — when a mover flags a stop, admin sees an alert on the ops page on next refresh.

---

## The Capacity Philosophy

There is no hard block anywhere in this system. Customer satisfaction is the priority — if a route fills up, the answer is to add a truck, not to turn away a seller. The soft cap exists to surface awareness, not to enforce limits. Admin always has the final say.

---

## UX Flow

### Admin: Route Builder (`/admin/routes`)

**Starting state:** The board is empty. Sellers are not auto-assigned in the background. Admin explicitly triggers assignment when ready.

1. Admin opens `/admin/routes` for a given week.
2. Page shows:
   - **Summary bar:** total sellers with items ready, total assigned, total unassigned, total TBD.
   - **Unassigned sellers panel:** all sellers with `available` items and no `ShiftPickup`, grouped by geographic cluster (building name or coordinate proximity). Each seller card shows name, cluster label, item count, unit count, time preference badge (AM/PM), pickup week.
   - **Shift capacity board:** all shifts for the selected week. Each shift shows its trucks with a capacity gauge (units used / effective capacity). Trucks with no workers show "Workers TBD" badge.
3. Admin clicks **"Run Auto-Assignment"** — system places all eligible unassigned sellers into shifts (algorithm below). Page reloads showing the board populated.
4. Admin reviews: any seller the system couldn't place appears in a **TBD section** at the top with a reason ("No AM shifts in Week 1").
5. To correct a misplaced stop: admin clicks the stop → inline panel shows current assignment + a "Move to..." dropdown listing all trucks across all shifts for that week with their current load. Admin picks a new truck → stop moves immediately via fetch POST, no full reload.
6. To handle a TBD seller: same "Assign to..." inline dropdown. Admin can also click **"Add Truck"** on any shift to create a new truck slot first.
7. Once a shift looks right, admin clicks **"Order Route"** → system runs nearest-neighbor ordering and renders the static stop map.
8. Admin clicks **"Notify Sellers"** → sends pickup confirmation email to all unnotified sellers on that shift.

### Admin: Adding a Truck

**"Add Truck" is available on any shift at any time — including during an active ShiftRun.**

1. Admin clicks "Add Truck" on a shift card (route builder or ops page).
2. System increments `Shift.trucks` by 1. New truck appears immediately with "Workers TBD" badge and empty stop list. New truck number = `max(existing truck numbers) + 1` for that shift.
3. Admin moves stops from over-loaded trucks onto the new truck via the "Move →" inline reassignment panel.
4. Admin assigns workers to the new truck via existing mover assignment UI on the ops page.
5. Workers assigned to the new truck see it on their crew dashboard immediately and can tap "Start Shift" to begin — independent of any existing ShiftRun on other trucks.

No worker assignment is required before stops can be moved to a new truck.

### Admin: Ops Page (existing `/admin/crew/shift/<id>/ops`)

Existing page retains mover assignment and destination unit UI. This spec adds:

- Ordered stop list per truck (by `stop_order`, ascending, nulls last).
- Each stop card: stop number badge, seller name, address + cluster label, unit count, status badge, **stairs/elevator badge** (🪜 Stairs or 🛗 Elevator, based on seller's access type), "Move →" reassignment button, up/down reorder arrows (pending stops only).
- Static map image per truck (Google Maps Static API `<img>`, text fallback if no API key).
- Capacity gauge above each truck's stop list.
- **"Add Emergency Stop"** per truck — visible anytime including during active shift. Soft cap warning if over effective capacity; admin confirms to proceed.
- **"Add Truck"** button in shift header.
- **"Order Route"** button per truck.
- **Issue alert banner** at page top: red card listing all `status='issue'` stops with seller name + mover's note. Updates on page refresh.
- **"Notify Sellers"** button in shift header. Shows "Notified ✓ [date]" once sent.

### Mover: Shift View (existing `/crew/shift/<shift_id>`)

- Stops in `stop_order` sequence (ascending, nulls last).
- **"Navigate →"** button per stop: opens `https://maps.google.com/?q=<encoded_address>` in a new tab.
- `<div id="stop-list">` wraps the stop list for targeted DOM replacement.
- **Auto-refresh:** `setInterval` every 30 seconds fetches `/crew/shift/<shift_id>/stops_partial` and replaces `#stop-list` innerHTML on success. Silent fail on error — no disruption if briefly offline. Emergency stops added by admin appear within 30 seconds.

### Seller

No new UI in this spec. Seller receives a pickup confirmation email when admin clicks "Notify Sellers." Spec #7 (Progress Tracker) will surface the assigned day on the seller dashboard.

---

## New Routes

| Method | Path | Function | Description |
|--------|------|----------|-------------|
| `GET` | `/admin/routes` | `admin_routes_index` | Route builder — unassigned sellers + shift capacity board. Admin only. |
| `POST` | `/admin/routes/auto-assign` | `admin_routes_auto_assign` | Run auto-assignment for all unassigned sellers. Returns JSON `{assigned, tbd, over_cap_warnings}`. Admin only. |
| `POST` | `/admin/routes/stop/<pickup_id>/move` | `admin_routes_move_stop` | Move a ShiftPickup to a different shift + truck. Returns JSON. Admin only. |
| `POST` | `/admin/routes/seller/<user_id>/assign` | `admin_routes_assign_seller` | Manually assign a single unassigned seller to a shift + truck. Returns JSON. Admin only. |
| `POST` | `/admin/crew/shift/<shift_id>/add-truck` | `admin_shift_add_truck` | Increment `Shift.trucks` by 1. Returns JSON `{new_truck_number}`. Admin only. |
| `POST` | `/admin/crew/shift/<shift_id>/order` | `admin_shift_order_stops` | Run nearest-neighbor ordering; writes `stop_order` to all ShiftPickups for the shift. Admin only. |
| `POST` | `/admin/crew/shift/<shift_id>/stop/<pickup_id>/reorder` | `admin_shift_reorder_stop` | Set a specific `stop_order` value. Returns JSON. Admin only. |
| `POST` | `/admin/crew/shift/<shift_id>/notify` | `admin_shift_notify_sellers` | Send pickup confirmation email to all unnotified sellers. Idempotent per seller. Admin only. |
| `GET` | `/crew/shift/<shift_id>/stops_partial` | `crew_shift_stops_partial` | HTML partial of stops for current mover's truck. Used by 30-second auto-refresh. Crew only. |
| `POST` | `/admin/settings/route` | `admin_route_settings` | Update route AppSettings + per-category unit sizes. Super admin only. |

---

## Model Changes

### New field: `InventoryCategory.default_unit_size` (Float, default 1.0)

```
InventoryCategory.default_unit_size  Float, default 1.0
```

### New field: `InventoryItem.unit_size` (Float, nullable)

Admin override. `NULL` = use category default.

```
InventoryItem.unit_size  Float, nullable, default None
```

Exposed in the admin item approval panel as an optional "Unit size override" field.

### New field: `Shift.sellers_notified` (Boolean, default False)

```
Shift.sellers_notified  Boolean, default False
```

### New field: `ShiftPickup.notified_at` (DateTime, nullable)

Per-seller notification timestamp for idempotent email sends.

```
ShiftPickup.notified_at  DateTime, nullable
```

### New field: `ShiftPickup.capacity_warning` (Boolean, default False)

Set True when auto-assignment places a seller on an over-capacity truck. Displayed as amber badge on the stop card. Cleared if the stop is moved to a truck under cap.

```
ShiftPickup.capacity_warning  Boolean, default False
```

### `Shift.trucks` — behavior change, no schema change

Already an Integer on the model. This spec allows it to be incremented at any time via `admin_shift_add_truck`. The ops page and route builder must read `Shift.trucks` dynamically.

**Migration required:** One migration covering all five new fields above. `ShiftPickup.stop_order` already exists — do not re-add.

---

## AppSetting Keys (New)

| Key | Default | Description |
|-----|---------|-------------|
| `truck_raw_capacity` | `'18'` | Maximum unit load a truck can hold |
| `truck_capacity_buffer_pct` | `'10'` | Buffer %. Effective = `floor(raw × (1 − buffer/100))` |
| `route_am_window` | `'9am–1pm'` | Display string in seller pickup emails |
| `route_pm_window` | `'1pm–5pm'` | Display string in seller pickup emails |
| `maps_static_api_key` | `''` | Google Maps Static API key. Empty = disable map images, show text fallback. |

---

## Business Logic

### Item Unit Size Resolution

```python
def get_item_unit_size(item):
    if item.unit_size is not None:
        return item.unit_size
    if item.category and item.category.default_unit_size is not None:
        return item.category.default_unit_size
    return 1.0
```

### Seller Unit Count

Sum of `get_item_unit_size(item)` across all `available` items for that seller. Computed at display time — never stored.

### Effective Truck Capacity

```python
def get_effective_capacity():
    raw = float(AppSetting.get('truck_raw_capacity', '18'))
    buffer = float(AppSetting.get('truck_capacity_buffer_pct', '10'))
    return math.floor(raw * (1 - buffer / 100))
```

### Capacity Gauge Colors

- Green: load ≤ 75% of effective capacity
- Yellow: 75%–100%
- Red: over effective capacity (soft cap exceeded — still valid)

### Auto-Assignment Algorithm

Processes all sellers with `available` items, no existing `ShiftPickup`, and `pickup_week IS NOT NULL`. Sellers without a pickup week set are excluded entirely — they don't appear in TBD, they just aren't processed. Largest unit counts placed first to reduce fragmentation.

```
Sort eligible sellers by unit_count DESC.

For each seller:
  1. Candidate shifts = Shift records where week matches seller.pickup_week
     AND slot matches seller.pickup_time_preference.
  2. If no candidate shifts exist → add to tbd_list with reason. Stop.
  3. For each candidate shift, find the truck with the lowest current load.
  4. Pick the candidate shift whose best truck has the most remaining capacity.
  5. Assign seller to that truck regardless of whether it exceeds effective cap
     (soft cap — no hard block).
  6. If (load + seller_unit_count) > effective_capacity → set capacity_warning=True
     on the new ShiftPickup.

Return: { assigned: [seller_ids], tbd: [{seller_id, reason}], over_cap_warnings: [pickup_ids] }
```

TBD only occurs when no matching shift exists at all for that week + slot combination. Over-capacity is not a TBD condition — it's an assignment with a warning.

Auto-assignment is safe to re-run: skips sellers who already have a ShiftPickup.

### Geographic Clustering (Display Only)

Used to group sellers visually on the route builder. Not used by the auto-assignment algorithm.

1. **On-campus:** sellers sharing the same `pickup_dorm` → same cluster, labeled with the dorm name.
2. **Partner apartment:** sellers who selected a partner apartment building → same cluster, labeled with the building name. Treated identically to `pickup_dorm` — exact name match, no coordinate fallback needed.
3. **Off-campus (other):** sellers with a manually entered off-campus address, within 0.25 miles of each other (haversine) → grouped, labeled with the first seller's street.
4. **Unlocated:** no lat/lng, no dorm, no partner building → "Unlocated" group at the bottom.

Clustering priority: named building (dorm or partner apartment) takes precedence over coordinate proximity. A seller with a partner apartment name is never grouped by lat/lng — their building name is the cluster.

Computed at page load in `admin_routes_index()`.

### Nearest-Neighbor Stop Ordering

```
Origin: storage unit coordinates (from Shift.truck_unit_plan → StorageLocation)
Unvisited: all ShiftPickup records for this shift that have seller lat/lng

Repeat until all visited:
  - Find unvisited stop with smallest haversine distance from current position
  - Assign next stop_order integer
  - Advance current position to that stop

Stops with no lat/lng → appended at end in insertion order
Bulk-update all stop_order values in one db.session.execute()
```

If storage unit has no coordinates → fall back to insertion order, flash warning.

`stop_order` is unique within a shift (not per-truck) — mover view filters by `truck_number`.

### Static Stop Map

Built per-truck as a Google Maps Static API URL, rendered as an `<img>` tag.

```
https://maps.googleapis.com/maps/api/staticmap
  ?size=600x300
  &markers=label:S|<storage_lat>,<storage_lng>
  &markers=label:1|<stop1_lat>,<stop1_lng>
  &markers=label:2|<stop2_lat>,<stop2_lng>
  ...
  &key=<maps_static_api_key>
```

Helper: `_build_static_map_url(truck_stops, storage_location)` → returns URL string or `None` if API key unset. Template renders `<img>` if URL present, text address list if not. URL never stored.

### Seller Notification Email

Triggered by `admin_shift_notify_sellers`. Only sends to sellers where `ShiftPickup.notified_at IS NULL`.

- Subject: `"Your Campus Swap pickup is [Day], [Month Date]"`
- Body: seller name, day + date, time window (from AppSetting), brief instructions, contact info.
- Uses existing `send_email()` helper.
- Sets `ShiftPickup.notified_at = _now_eastern()` per seller after sending.
- Sets `Shift.sellers_notified = True` on the shift.

---

## Template Changes

### New: `templates/admin/routes.html`

Top to bottom:

- **Page header:** "Route Planner — Week of [date]." Week selector if multiple weeks exist.
- **Summary bar:** sellers ready / assigned / unassigned / TBD counts. "Run Auto-Assignment" button (fetch POST, inline spinner, page reload on success).
- **TBD section** (amber card, hidden when empty): one row per TBD seller — name, week, time preference, unit count, reason, "Assign to..." dropdown + button.
- **Over-cap warnings section** (shown when `capacity_warning` stops exist): lists affected stops, suggests adding a truck.
- **Shift capacity board:** one card per shift showing date, slot, per-truck capacity gauges + expandable stop lists. Each stop: seller name, cluster label, unit count, stairs/elevator badge, "Move →" button. "Add Truck" button per shift card. "Order Route" and "Notify Sellers" buttons per shift.

### New: `templates/admin/route_settings.html`

Super admin only:

- **Truck Capacity:** raw capacity + buffer % inputs. Live preview: "Effective capacity: X units."
- **Time Windows:** AM and PM window strings.
- **Category Unit Sizes:** table, one editable float per category. Single "Save All" submit.
- **Maps API Key:** text input for `maps_static_api_key`.

### Modified: `templates/admin/shift_ops.html`

- Issue alert banner at top (red, server-rendered, lists flagged stops with seller name + note).
- Stops in `stop_order` sequence.
- Per stop: stop number, seller name, address + cluster label, unit count, **stairs/elevator badge**, status, "Move →" button, up/down arrows (pending only).
- Static map image per truck (or text fallback).
- Capacity gauge per truck.
- "Add Emergency Stop" per truck (soft cap warning, confirm to override).
- "Add Truck" button in shift header.
- "Order Route" per truck.
- "Notify Sellers" in shift header with "Notified ✓" badge.

### Modified: `templates/crew/shift.html`

- Stops in `stop_order` order, nulls last.
- Each stop card shows: stop number, seller name, address, **stairs/elevator badge** (🪜 Stairs or 🛗 Elevator), item count, status.
- "Navigate →" per stop: `<a href="https://maps.google.com/?q={{ stop.seller.pickup_address|urlencode }}" target="_blank" class="btn-outline">Navigate →</a>`
- `<div id="stop-list">` wraps stop list.
- Auto-refresh script (30s interval, fetch stops_partial, replace #stop-list innerHTML, silent fail).

### Modified: Admin item approval panel

- "Unit size override" float input per item at approval time. Placeholder shows category default. Empty = NULL (use category default).

### Modified: `layout.html` (admin nav)

- "Routes" link → `/admin/routes`, near Schedule and Ops.

---

## Constraints

- No hard capacity blocks anywhere. Soft cap + warning only.
- Do not modify `_get_payout_percentage(item)`.
- Do not change `ShiftPickup` global uniqueness constraint.
- `stop_order` already exists — do not re-add in migration.
- Use existing `geocode_address()` / `haversine_miles()` helpers. Do not re-implement.
- Stripe webhook untouched.
- Admin role gating: all route routes = `is_admin`. Route settings = `is_super_admin`.
- Notification is always an explicit admin action. Never automatic.
- `Shift.trucks` increment = only data change from "Add Truck." New truck number = `max(existing) + 1`.

---

## Edge Cases

| Seller has no pickup week set | Excluded from route builder and auto-assignment entirely. Admin resolves upstream via pickup nudge tool. |
|----------|----------|
| Seller has no address or lat/lng | Auto-assigned normally; placed at end of route order; shown in "Unlocated" cluster |
| No shifts exist for seller's week + time preference | Goes to TBD queue with reason "No [AM/PM] shifts in Week [N]" |
| All shifts for seller's week + slot are over effective cap | Still assigned to least-loaded truck; `capacity_warning=True`; shown in over-cap warnings |
| Admin removes a stop after ordering | `stop_order` gaps are fine — remaining stops still sort correctly |
| "Notify Sellers" clicked, new stop added later | New seller's `notified_at` is NULL; re-clicking sends only to them |
| Storage unit has no coordinates | "Order Route" falls back to insertion order; flash warning shown |
| Seller's items sold before pickup day | Unit count recalculates to 0 at display time; ShiftPickup record remains; admin removes manually |
| New truck added mid-shift, workers assigned | Workers see shift on crew dashboard; tap "Start Shift" creates their own ShiftRun independent of other trucks |
| Auto-assignment re-run after corrections | Skips sellers with existing ShiftPickup; only processes unassigned sellers |
| `maps_static_api_key` not configured | Map image omitted; text address list shown; no errors |
| Stop moved to new truck that brings old truck under cap | `capacity_warning` on remaining stops on old truck should be cleared if old truck is now under cap |

---

## Open Questions for Sign-Off

1. **Category unit size defaults** — locked in. These seed `InventoryCategory.default_unit_size` in the migration. Every category ships with a pre-set default; admin can override per item at approval time.

| Category | `default_unit_size` |
|----------|---------------------|
| Couch / Sofa | 3.0 |
| Mattress (Full/Queen) | 2.0 |
| Mattress (Twin) | 1.5 |
| Dresser | 2.0 |
| Desk | 1.5 |
| Mini Fridge | 1.0 |
| Microwave | 0.5 |
| Chair | 1.0 |
| Bookshelf | 1.5 |
| TV | 0.5 |
| Lamp | 0.5 |
| Miscellaneous | 0.5 |
| Everything else (fallback, no category) | 1.0 |

2. **Raw truck capacity starting value** — seed at `18`. Adjustable at any time via the route settings page in the admin dashboard (`/admin/settings/route`).

3. **Google Maps Static API key** — needs to be provisioned and added to Render env vars before stop maps render. Spec degrades gracefully without it (text address list shown instead). Does not block the build.

4. **Notification email copy** — spec defines structure; final wording to be reviewed before handoff to Claude Code.

5. **Sellers with no pickup week set** — excluded from the route builder entirely. They do not appear in the TBD queue. Admin resolves this upstream by nudging sellers to set their week via the existing pickup nudge tool.
