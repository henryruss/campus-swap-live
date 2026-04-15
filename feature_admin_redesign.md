# Spec: Admin UI Redesign

**Status:** Ready for build  
**Dependencies:** All specs #1–#9 signed off  
**Concurrent admin operations note:** Auto-assign and route ordering are single-admin operations. The DB unique constraint on `(shift_id, seller_id)` protects against double-assignment, but route ordering is last-write-wins. Establish role separation: one admin owns the Ops tab during pickup week.

---

## Goal

Replace the current monolithic `/admin` page and the fragmented ops flow (`/admin/routes` → `/admin/crew/shift/<id>/ops` with back arrows) with a unified, sidebar-navigated admin shell. The new shell is modeled on Homebase: a persistent left sidebar for section switching, a shift-list panel for temporal navigation, and a main content area that never requires leaving the page to complete a routing task. All existing functionality is preserved — this is a layout and navigation redesign, not a feature rebuild.

---

## URL Structure

| Old URL | New URL | Notes |
|---|---|---|
| `GET /admin` | `GET /admin/ops` | Old `/admin` redirects 302 to `/admin/ops` |
| `GET /admin/routes` | removed | Absorbed into `/admin/ops` |
| `GET /admin/crew/shift/<id>/ops` | removed | Absorbed into `/admin/ops?shift_id=<id>` |
| `GET /admin/approve` | `GET /admin/items` | Old URL redirects to new |
| `GET /admin/payouts` | `GET /admin/payouts` | Already exists (spec #5), no change |
| `GET /admin/sellers` | `GET /admin/sellers` | New consolidated seller view |
| `GET /admin/crew` | `GET /admin/crew` | New crew management view |
| `GET /admin/settings` | `GET /admin/settings` | New consolidated settings view |
| `GET /admin/schedule` | `GET /admin/schedule` | Unchanged — schedule builder stays |
| All POST routes | Unchanged | No POST URLs change |

`/admin` → 302 redirect to `/admin/ops` (the new default landing page for all admins).

---

## The Admin Shell

All admin pages share a new shell layout defined in `admin_layout.html` (a new base template that extends `layout.html`). This replaces the current `admin_sidebar.html` partial approach.

### Shell Structure

```
┌─────────────────────────────────────────────────────────┐
│  [sidebar 52px] │  [page content — full remaining width] │
└─────────────────────────────────────────────────────────┘
```

The sidebar is 52px wide, icon-only, with tooltips on hover. It is present on every admin page. On mobile (≤768px) the sidebar collapses to a top icon bar.

### Sidebar Icons (top to bottom)

| Icon | Label | URL | Access |
|---|---|---|---|
| Grid/route icon | Ops | `/admin/ops` | is_admin |
| Checkmark | Items | `/admin/items` | is_admin |
| Dollar sign | Payouts | `/admin/payouts` | is_admin |
| Person | Sellers | `/admin/sellers` | is_admin |
| People group | Crew | `/admin/crew` | is_admin |
| Gear | Settings | `/admin/settings` | is_super_admin |
| Calendar | Schedule | `/admin/schedule` | is_super_admin |

Active tab: icon background uses `--sage` tint. Inactive: `--text-muted`. Use existing CSS variable system — no hardcoded colors.

`admin_layout.html` passes `active_tab` context variable (e.g. `'ops'`, `'items'`) from each route so the sidebar can highlight the correct icon.

---

## Tab 1: Ops (`/admin/ops`)

This is the most complex view and the primary focus of this spec. It is a four-zone layout on a single page.

### URL Behavior

`GET /admin/ops` — loads with the first upcoming or active shift selected by default (earliest shift whose date >= today, or the most recent past shift if pickup week has ended).  
`GET /admin/ops?shift_id=<id>` — loads with the specified shift selected. This is a full page reload — no JS routing.

Clicking a shift in the left panel navigates to `?shift_id=<id>`. The browser back button works correctly.

### Zone 1: Shift List Panel (left, 220px wide)

Persistent left panel showing all shifts grouped by week with week navigation arrows.

**Header:** "Pickup shifts" title + current month label.

**Week navigation:** Previous/next arrows step through ShiftWeeks. Defaults to the week containing the selected shift. The week label shows "Week of [Month Day]".

**Shift rows:** One row per Shift, sorted ascending by date then slot (AM before PM). Each row shows:
- Date label: "Mon May 4"
- Slot badge: amber `AM` or blue `PM`
- Status indicator (one of):
  - Green badge "Notified" — `shift.sellers_notified = True` and no unnotified stops
  - Amber badge "X new" — `unnotified_count > 0` (sellers added since last notify)
  - Muted text "X trucks · Y stops" — default state
  - Empty label — no stops assigned yet

Active shift row: highlighted with `--sage` background tint.

**Week overview link** at bottom of panel: links to `/admin/schedule/<week_id>` (the existing schedule builder for that week).

**Shift auto-generation** (see Model Changes below): If no ShiftWeeks exist for the configured pickup window, the panel shows an "Generate shifts →" prompt that links to the Settings tab.

### Zone 2: Main Content — Truck Cards

Top bar:
- Shift label: "Tue May 5 — AM shift" (h2, left)
- Action buttons (right): `+ Add Truck`, `Order Routes`, `Notify Sellers`

**Alert bar** (shown when `unnotified_count > 0`):
- Amber background, full width below top bar
- Text: "X sellers added since last notification · Route order may be stale"
- Right-aligned link: "Re-order & notify" — triggers route order then notify in sequence (two separate fetches, page reload after both complete)

**Truck cards:** One card per truck on the selected shift, in truck number order.

Truck card header (light gray background):
- Truck label: "Truck 1"
- Storage location chip: green dot + location name if assigned ("Hinton James"), amber "No unit assigned" if not
- Capacity bar: 80px wide, color-coded (green ≤75%, amber 75–100%, red >100% of effective capacity)
- Unit count: "13/18u" (loaded units / effective capacity)

**Live state (when `ShiftRun` exists for this shift):**

The truck card header gains a status pill:
- Blue "In progress" — ShiftRun exists, status='in_progress'
- Green "Complete" — ShiftRun status='completed'
- No pill — shift not started

The truck card body shows a compact live summary row:
- Stops done counter (green number)
- Total stops counter
- Total items on truck
- Current stop: seller name + address + item count

If any stop on this truck has `status='issue'`: an amber alert bar appears at the bottom of the card reading "⚠ Issue flagged at stop X — tap to view". Clicking anywhere on the card opens the truck detail modal (see below).

If no ShiftRun exists, the truck card body shows the stop list directly (pre-shift planning view).

**Pre-shift stop list** (shown when not live):

Each stop row:
- Stop number circle (sequential by `stop_order`, null-order stops show "–")
- Seller name
- Address / location display
- Item count (unit size total)
- Badges: "new" (amber, `created_at > shift.last_notified_at`) or "moved" (blue, `rescheduled_from_shift_id IS NOT NULL`)
- Drag handle (for manual reorder — see Business Logic)

Truck card footer:
- "Re-order route" button → POST `/admin/crew/shift/<id>/order` (fetch, page reload)
- "View map" button → opens static map in new tab (existing `build_static_map_url` helper)
- If no storage location assigned: "Assign unit" button → opens inline dropdown to select from active, non-full StorageLocation records (fetch POST to existing `/admin/crew/shift/<id>/assign-unit` equivalent)

**Add Truck button:** POST to existing `/admin/crew/shift/<id>/add-truck` (fetch, page reload).

**Order Routes button:** POST to existing `/admin/crew/shift/<id>/order` for each truck (fetch, page reload). Shows spinner during ordering.

**Notify Sellers button:** POST to existing `/admin/crew/shift/<id>/notify`. Requires confirmation dialog: "Send pickup confirmation to X unnotified sellers?" Yes/Cancel. Full page reload after success.

### Zone 3: Unassigned Panel (right, 210px wide)

Always visible when on the Ops tab. Shows sellers in the "ready to assign" pool for the selected shift's week and slot.

**Header:** "Unassigned" title + count badge (red if >0).  
**Sub-label:** "Drag to assign or use auto-assign"

Sellers grouped by cluster label (using existing `build_geographic_clusters` output). Cluster headers in small uppercase muted text.

Each seller card:
- Orange dot if `created_at > 24 hours ago` (newly eligible)
- Seller name
- Cluster / building label
- Unit count + week + AM/PM preference badge

**Auto-Assign button** at top of panel: POST to existing `/admin/routes/auto-assign` (fetch, page reload on success). Shows spinner. Note in spec: single-admin operation — do not run concurrently.

**Manual assign:** Clicking a seller card in the unassigned panel opens a small inline dropdown to pick truck number, then POST to existing `/admin/routes/seller/<id>/assign`. Page reload on success.

**Eligibility for unassigned pool:** Seller has at least one `available` item AND `pickup_week` is set AND `has_pickup_location = True` AND no existing `ShiftPickup` across any shift. (This is the existing logic — no change.)

### Zone 4: Truck Detail Modal

Triggered by clicking a truck card while a ShiftRun exists (live state). Also accessible via a "View stops" link on each truck card at all times.

Modal is a right-side drawer (480px, same pattern as existing seller profile panel). Fetched as HTML partial via `GET /admin/ops/truck-detail?shift_id=<id>&truck=<n>`.

Modal content:
- Truck header: "Truck 1 · Tue May 5 AM" + status pill + storage location
- Capacity bar + unit count
- Assigned movers (from ShiftAssignment records for this truck)
- Full stop list with per-stop status:
  - Gray circle = pending
  - Green circle = completed (shows `completed_at` timestamp)
  - Red circle = issue (shows `issue_type` + notes)
- Per-stop actions (pre-shift only, not during live run):
  - Drag handle for reorder
  - Remove stop button (pending only) → POST to existing `/admin/crew/shift/<id>/stop/<pickup_id>/remove`
  - Move to different shift/truck → uses existing `/admin/routes/stop/<id>/move`
- Close: X button, Escape key, click-outside

**New route required:**  
`GET /admin/ops/truck-detail` → `admin_ops_truck_detail`  
Returns HTML partial. Params: `shift_id`, `truck`. Requires `is_admin`. No login redirect — returns 403 if not admin.

---

## Tab 2: Items (`/admin/items`)

Consolidates the current `/admin` item lifecycle table and `/admin/approve` approval queue into a single page with two sub-views selectable via tab pills at the top.

**Sub-tab A: Approval queue** — the existing `admin_approve` view, rendered inline. No functional changes.

**Sub-tab B: All items** — the existing item lifecycle table from `admin_panel`, including:
- Filterable by category, seller email, item title
- Per-item actions (mark sold, mark payout sent, edit, delete, undo, cancel info request)
- Bulk actions
- Seller name → opens existing slide-out seller profile panel

**Store controls** (collapsible section, collapsed by default):
- Pickup period toggle
- Reserve-only toggle
- Store open date input
- Shop teaser mode toggle

These were previously at the top of `/admin`. They move here since they relate to item/store state.

**Stats bar** (4 metric cards at top):
- Total items, Pending approval, Available, Sold

**Route:** `GET /admin/items` → `admin_items` (new function). Renders `admin/items.html` (new template). All existing POST routes for item actions remain unchanged.

The old `GET /admin` and `GET /admin/approve` redirect to `GET /admin/items`.

---

## Tab 3: Payouts (`/admin/payouts`)

No functional changes. The existing payout reconciliation view (Spec #5) is re-rendered inside the new admin shell at this URL. Route `admin_payouts` already exists — just ensure it passes `active_tab='payouts'` to the template.

Template change: `admin/payouts.html` (or equivalent) should extend `admin_layout.html` instead of `layout.html`.

---

## Tab 4: Sellers (`/admin/sellers`)

Consolidates seller management currently scattered across `/admin`.

**Top section: Seller list**
- Search bar (filter by name or email, client-side)
- Table: name, email, phone, tier, pickup week, item count, payout rate, days since approval
- Seller name → opens existing slide-out seller profile panel (no change to panel itself)

**Pickup nudge section** (collapsible):
- Exact same UI as current pickup nudge section on `/admin`
- Sellers without a pickup week selected, with approved items
- "Remind All" and "Remind Selected" buttons
- All existing routes unchanged

**Free-tier queue** (collapsible):
- Exact same UI as current free-tier management section on `/admin`
- All existing routes unchanged

**Route:** `GET /admin/sellers` → `admin_sellers` (new function). Renders `admin/sellers.html` (new template).

---

## Tab 5: Crew (`/admin/crew`)

Consolidates crew management currently inside the collapsible section on `/admin`.

**Pending applications section:**
- Table: name, email, applied_at, availability grid summary
- Expand row → shows full availability grid + why_blurb
- Approve / Reject buttons → existing POST routes unchanged

**Approved workers section:**
- Table: name, email, worker_role, total shifts completed
- No edit actions needed here

**Route:** `GET /admin/crew` → `admin_crew_panel` (new function, distinct from existing `admin_crew_approve/reject` POST routes). Renders `admin/crew.html` (new template).

---

## Tab 6: Settings (`/admin/settings`)

Super admin only (`@require_super_admin`). Consolidates all configuration pages into one page with anchor-linked sections.

**Sections (all on one scrollable page):**

1. **Pickup window** — new section (see Model Changes). Fields: `pickup_week_start` (date), `pickup_week_end` (date), "Generate shifts" button. Generates AM + PM Shift records for each date in range if no ShiftWeek exists for that date.

2. **Route & capacity** — existing content from `/admin/settings/route`. Truck raw capacity, buffer %, AM/PM time windows, Maps API key, per-category unit sizes.

3. **Storage locations** — existing content from `/admin/storage`. Active location list with inline create/edit (super admin only).

4. **Referral program** — existing content from referral settings. Toggle on/off, base rate, bonus values.

5. **SMS notifications** — existing kill switches and cron hour settings from route settings page.

6. **User management** — grant/revoke admin by email. Existing POST routes unchanged.

7. **Data exports** — links to existing CSV export routes (users, items, sales). Data preview links.

8. **Mass email** — existing mass email form.

9. **Database reset** — existing reset form (requires typing "reset database").

**Route:** `GET/POST /admin/settings` → `admin_settings` (new function). Renders `admin/settings.html` (new template). All existing sub-route POSTs (`/admin/settings/route`, `/admin/settings/referral`, etc.) remain unchanged.

The old `/admin/settings/route` and `/admin/storage` GET routes redirect to `/admin/settings#route` and `/admin/settings#storage` respectively.

---

## Shift Auto-Generation

### New AppSettings

| Key | Default | Description |
|---|---|---|
| `pickup_week_start` | `''` | ISO date string, e.g. `'2026-05-04'` |
| `pickup_week_end` | `''` | ISO date string, e.g. `'2026-05-08'` |

### New Route

`POST /admin/settings/generate-shifts` → `admin_generate_shifts`  
Super admin only.

**Logic:**
1. Read `pickup_week_start` and `pickup_week_end` from AppSettings. Validate both are set and end >= start.
2. For each date in range (inclusive):
   - Find or create a `ShiftWeek` record whose week contains that date.
   - For `'am'` and `'pm'` slots: check if a `Shift` with that date and slot already exists. If not, create it with `trucks=1`, `status='draft'`.
3. Flash success: "Generated X shifts for May 4–8." Redirect to `/admin/settings#pickup-window`.

**Idempotent:** Re-running never duplicates. Only creates shifts that don't already exist.

**Does not assign workers.** Worker assignment to shifts remains in the schedule builder (`/admin/schedule`). This only creates the Shift skeleton.

---

## Auto-Assignment: Cluster-First Priority (Logic Change)

The existing `_run_auto_assignment()` function currently sorts sellers by unit count descending before placement. Change the sort order to:

1. **Primary: cluster label** — group sellers by `build_geographic_clusters()` output. Process clusters in this order: partner buildings first (alphabetical), then dorms (alphabetical), then proximity clusters, then Unlocated.
2. **Secondary: unit count descending** — within each cluster, largest sellers first (fills trucks efficiently).
3. **Tertiary: existing logic** — best-fit shift by pickup_week + time_preference, soft cap.

**Effect:** Sellers from Granville are assigned to the same truck(s). When route ordering runs afterward, the nearest-neighbor algorithm tightens the geographic loop within each truck naturally. No model changes required.

**New AppSetting (optional, for future use):** No new settings needed. Cluster ordering is hardcoded in priority order above.

---

## New Pool Logic: "Ready to Assign"

Currently, sellers appear in the unassigned panel only on `/admin/routes`. In the new design, the unassigned panel is always present on the Ops tab.

**Eligibility check** (no change to logic, just clarifying the definition):
A seller is "ready to assign" when all of the following are true:
- Has at least one item with `status='available'`
- `user.pickup_week` is set
- `user.has_pickup_location = True`
- No `ShiftPickup` record exists for this user (across all shifts — globally unique)

The panel on the Ops tab filters the pool by the selected shift's `pickup_week` and `slot` (AM/PM preference match) to show only sellers relevant to the current shift. A "Show all unassigned" toggle reveals sellers whose preference doesn't match the current slot.

---

## Live State Derivation

The truck cards switch to live view when `ShiftRun` exists for the selected shift. All data is computed server-side on page load — no polling on the admin side (unlike the crew mover view which polls every 30s).

Admin refreshes the page manually to see updated progress. A soft "Refresh" button in the top bar reloads `?shift_id=<id>`.

**Live data computed per truck in the route:**
```python
truck_live = {
    'truck_number': n,
    'status': 'in_progress' | 'complete' | 'not_started',
    'stops_total': count of ShiftPickups for this truck,
    'stops_done': count where status='completed',
    'stops_issue': count where status='issue',
    'items_total': sum of unit sizes across all stops on this truck,
    'current_stop': ShiftPickup with lowest stop_order where status='pending' (None if all done),
    'has_issue': bool
}
```

`current_stop` is the first pending stop by stop_order. If all stops are resolved, `current_stop = None` and the truck shows "All stops resolved."

---

## Model Changes

### No new model fields required.

All data needed for the new views exists on current models. Summary:
- Live state: `ShiftRun`, `ShiftPickup.status`, `ShiftPickup.stop_order`, `ShiftPickup.completed_at`
- New/moved badges: `ShiftPickup.created_at` vs `Shift.sellers_notified` timestamp
- Cluster grouping: existing `build_geographic_clusters()`
- Capacity: existing `get_effective_capacity()`, `get_seller_unit_count()`

### AppSettings additions (no migration needed — key-value store)

- `pickup_week_start` — ISO date string
- `pickup_week_end` — ISO date string

Seed these two keys in the existing `seed_*_app_settings()` startup call with empty string defaults.

---

## New Routes

| Method | Path | Function | Description |
|---|---|---|---|
| `GET` | `/admin/ops` | `admin_ops` | Main ops view. Selects default shift if no `shift_id` param. Passes all four zones' data. |
| `GET` | `/admin/ops/truck-detail` | `admin_ops_truck_detail` | HTML partial for truck detail modal. Params: `shift_id`, `truck`. |
| `GET` | `/admin/items` | `admin_items` | Items tab — approval queue + lifecycle table. Sub-tab via `?view=approve\|all`. |
| `GET` | `/admin/sellers` | `admin_sellers` | Sellers tab — list, nudge, free-tier. |
| `GET` | `/admin/crew` | `admin_crew_panel` | Crew tab — pending applications + approved workers. |
| `GET/POST` | `/admin/settings` | `admin_settings` | Settings tab — all config sections. Super admin only. |
| `POST` | `/admin/settings/generate-shifts` | `admin_generate_shifts` | Generate AM+PM shifts for pickup date range. Super admin only. |

### Redirects to add

| From | To |
|---|---|
| `GET /admin` | `GET /admin/ops` (302) |
| `GET /admin/routes` | `GET /admin/ops` (302) |
| `GET /admin/approve` | `GET /admin/items?view=approve` (302) |
| `GET /admin/settings/route` | `GET /admin/settings#route` (302) |
| `GET /admin/storage` | `GET /admin/settings#storage` (302) |

---

## Templates

### New templates

| Template | Extends | Description |
|---|---|---|
| `admin/admin_layout.html` | `layout.html` | Shell: sidebar + `{% block admin_content %}`. Accepts `active_tab` context var. |
| `admin/ops.html` | `admin_layout.html` | Four-zone ops view. All zones rendered server-side. Modal partial loaded via fetch. |
| `admin/ops_truck_detail.html` | *(no layout — partial)* | Truck detail modal inner HTML. |
| `admin/items.html` | `admin_layout.html` | Items tab with sub-tab pills. Inlines approval queue and lifecycle table. |
| `admin/sellers.html` | `admin_layout.html` | Sellers tab. |
| `admin/crew.html` | `admin_layout.html` | Crew tab. |
| `admin/settings.html` | `admin_layout.html` | Settings tab — all sections in one page. |

### Modified templates

| Template | Change |
|---|---|
| `admin/shift_ops.html` | Add `extends admin_layout.html`, pass `active_tab='ops'`. Keep existing content — this template is still used for direct `/admin/crew/shift/<id>/ops` access from the schedule builder "View Ops →" link. It does not need to be removed. |
| `admin/routes.html` | Add redirect notice at top: "Route builder has moved to the Ops tab." Keep template for safety but it will not be linked anywhere new. |
| `admin/schedule_index.html` | Extend `admin_layout.html`, pass `active_tab='schedule'`. |
| `admin/schedule_week.html` | Extend `admin_layout.html`, pass `active_tab='schedule'`. |
| `admin/route_settings.html` | Extend `admin_layout.html`, pass `active_tab='settings'`. |
| `admin/storage_index.html` | Extend `admin_layout.html`, pass `active_tab='settings'`. |
| `admin/storage_detail.html` | Extend `admin_layout.html`, pass `active_tab='settings'`. |
| `admin/intake_flagged.html` | Extend `admin_layout.html`, pass `active_tab='items'`. |
| `admin/shift_intake_log.html` | Extend `admin_layout.html`, pass `active_tab='ops'`. |
| `layout.html` | Remove "Admin Panel" link from desktop dropdown and mobile menu (sidebar replaces it). Add single "Admin" link pointing to `/admin/ops` for admins. |

---

## Business Logic

### Default shift selection on `/admin/ops`

```python
# In admin_ops():
if shift_id param:
    shift = Shift.query.get_or_404(shift_id)
else:
    today = _today_eastern()
    # Find earliest shift today or in future
    shift = (Shift.query
        .filter(Shift.date >= today)
        .order_by(Shift.date.asc(), Shift.slot.asc())
        .first())
    if not shift:
        # Fall back to most recent past shift
        shift = (Shift.query
            .order_by(Shift.date.desc(), Shift.slot.desc())
            .first())
    if not shift:
        # No shifts exist at all — render empty state with generate-shifts CTA
        return render_template('admin/ops.html', shift=None, ...)
```

### "New" badge logic

A stop is "new" (shows amber "new" badge) when:
```python
shift.sellers_notified == False
OR
pickup.created_at > shift.last_notified_at
```

Add `Shift.last_notified_at` (DateTime, nullable) — set when `admin_shift_notify_sellers` runs. This is a new field (requires migration). On notify: set `shift.last_notified_at = _now_eastern()` alongside existing `shift.sellers_notified = True`.

Stops created after `last_notified_at` are "new." Stops created before are not, even if the seller was added before the first notification on a shift that has `sellers_notified=False` — in that case all stops get "new" treatment (the `sellers_notified==False` branch).

### Unassigned panel slot filtering

The panel shows sellers whose `pickup_week` matches the selected shift's week AND whose `pickup_time_preference` matches the shift's slot ('morning' → 'am', 'afternoon' → 'pm'). Sellers with `pickup_time_preference = None` appear in both AM and PM panels.

A "Show all unassigned" checkbox at the bottom of the panel removes the slot filter and shows the full eligible pool, dimming sellers whose preference doesn't match.

### Shift generation idempotency

`admin_generate_shifts` checks for existing Shifts before creating:
```python
existing = Shift.query.filter_by(date=day, slot=slot).first()
if not existing:
    # create
```

ShiftWeek lookup: find a ShiftWeek whose date range contains `day`. If none, create one. Use `week_start = day - timedelta(days=day.weekday())` (Monday of that week).

### Auto-assign cluster sort

Modify `_run_auto_assignment()`:
```python
# Build clusters first
clusters = build_geographic_clusters(eligible_sellers)
# Flatten in priority order: partner_buildings → dorms → proximity → unlocated
ordered_sellers = []
for cluster_label in sorted_cluster_keys(clusters):
    cluster_sellers = sorted(clusters[cluster_label], 
                             key=lambda s: get_seller_unit_count(s), 
                             reverse=True)
    ordered_sellers.extend(cluster_sellers)
# Then run existing placement loop on ordered_sellers
```

`sorted_cluster_keys` orders: partner buildings first (alphabetical), then dorms (alphabetical), then proximity labels, then 'Unlocated' last.

---

## New Migration Required

One new field on `Shift`:
- `last_notified_at` (DateTime, nullable) — set when sellers are notified for this shift

Migration name: `admin_redesign_shift_last_notified`

```python
# In migration upgrade():
op.add_column('shift', sa.Column('last_notified_at', sa.DateTime(), nullable=True))

# In admin_shift_notify_sellers() route, add after existing logic:
shift.last_notified_at = _now_eastern()
db.session.commit()
```

---

## Constraints

- All existing POST route URLs must remain unchanged. Zero seller-facing or crew-facing routes are modified.
- `crew/shift.html`, `crew/intake.html`, and all crew templates are untouched.
- The seller profile panel (`admin/admin_seller_panel.html`) is untouched — it works via fetch and renders inside the new shell without changes.
- The schedule builder (`/admin/schedule`, `/admin/schedule/<week_id>`) retains full functionality. Worker assignment to shifts is not automated — that stays manual.
- `admin/shift_ops.html` is kept and still works at its existing URL for "View Ops →" links from the schedule builder.
- Never hardcode colors. Use existing CSS variables: `--primary`, `--accent`, `--bg-cream`, `--sage`, `--text-muted`, `--card-border`, etc.
- All new templates extend `admin_layout.html` which extends `layout.html`. Flash messages, analytics, and nav are inherited.
- All forms include `{{ csrf_token() }}`.
- The truck detail modal follows the exact same fetch+drawer pattern as the existing seller profile panel: `GET` returns an HTML partial, JS inserts it into a fixed right-side drawer div, close on X/Escape/overlay-click.
- `data-*` attributes for any JS that needs structured data (never inline `tojson` in `onclick`).

---

## Edge Cases

**No shifts exist:** `/admin/ops` renders an empty state: "No pickup shifts yet. Generate shifts in Settings →" with a link to `/admin/settings#pickup-window`.

**Shift with no trucks assigned:** Truck area shows "No trucks on this shift yet" with an Add Truck button.

**Shift with no stops:** Each truck card shows "No stops assigned" with a note to use auto-assign or drag from the unassigned panel.

**Unassigned panel empty:** Shows "All eligible sellers are assigned" with a green checkmark.

**ShiftRun exists but all stops resolved:** Truck card shows "All stops resolved" in the current-stop area. Status pill is "Complete" once ShiftRun.status='completed'.

**Seller in pool whose preference doesn't match current shift slot:** Dimmed in the unassigned panel by default. Shown fully when "Show all unassigned" toggle is on.

**`pickup_week_start` or `pickup_week_end` not set in Settings:** Generate shifts button is disabled with tooltip "Set pickup dates in Settings first." The shift list panel renders normally from existing Shift records if any exist.

**Admin navigates to `/admin/routes` or `/admin/approve`:** 302 redirect fires immediately. No content is shown at the old URL.
