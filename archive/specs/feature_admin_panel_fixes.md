# Feature Spec: Admin Panel Fixes

**Status:** Ready for Claude Code
**Applies to:** All admin roles (is_admin, is_super_admin, is_campus_director)
**Estimated complexity:** Medium — no model changes, mostly UI/UX and one JS-heavy interaction

---

## Goal

Clean up the admin panel to reflect how Campus Swap actually operates at current
scale. Four independent fix areas: schedule tab simplification, ops tab shift
ordering, drag-to-reorder stops, and crew tab scroll/navigation UX. All fixes
apply across all permission levels.

---

## Fix 1 — Schedule Tab: Simplify Week Creation

### What's Wrong
The week creation form shows a 7×2 toggle grid asking the admin to configure
which day/slot combinations are active. This is overkill — the real workflow is
"pick a Monday, create the week." The schedule builder also shows worker
assignment dropdowns per shift, but worker assignment has fully moved to the
Crew tab (Crew HQ). These UI elements are outdated and confusing.

### What to Change

**Week creation form** (`admin/schedule_index.html`):
- Remove the 7×2 AM/PM toggle grid entirely
- Keep only: date picker (Monday only, snaps to nearest Monday) + "Create Week"
  button
- On submit: create `ShiftWeek` + all 14 `Shift` records (7 days × AM + PM) as
  before — no change to the data model or backend logic
- Keep the existing week list (showing all weeks, draft/published status)

**Schedule builder** (`admin/schedule_week.html`):
- Remove the worker assignment dropdowns (driver/organizer slot selectors) from
  each shift card entirely
- Remove the "Run Optimizer" button
- Remove the "Publish" / "Unpublish" buttons — these were tied to the optimizer
  workflow which is no longer used
- What remains on each shift card: day label, AM/PM badge, date, truck count
  (keep — still useful context), "View Ops →" link (keep — links to ops page for
  that shift)
- The week header keeps: week title, date range, Delete Week button (draft only,
  unchanged)

**Routes to keep untouched:**
- `POST /admin/schedule/create` — unchanged, still creates ShiftWeek + 14 Shifts
- `GET /admin/schedule/<week_id>` — unchanged route, just simplified template
- `POST /admin/schedule/<week_id>/publish` — keep route in app.py (don't remove),
  just remove the UI button. Some downstream logic may depend on published state.
- `POST /admin/schedule/<week_id>/optimize` — keep route, remove UI button

**Routes to remove UI entry points for (keep in app.py):**
- Optimizer, publish, unpublish, shift update (worker dropdowns)

### Definition of Done
- [ ] Week creation form shows only Monday date picker + Create Week button
- [ ] Creating a week still produces 14 Shift records
- [ ] Schedule builder shows shift cards with day/slot/date/trucks/View Ops only
- [ ] No worker dropdowns on schedule builder
- [ ] No Run Optimizer button
- [ ] No Publish/Unpublish buttons
- [ ] Delete Week button still works (draft weeks only)
- [ ] "View Ops →" link on each shift card still works

---

## Fix 2 — Ops Tab: Default to Current Shift

### What's Wrong
The shift list panel (left column on `/admin/ops`) shows shifts in chronological
order with the oldest at the top. By week 4 of the season, the admin has to
scroll far down to find today's shift.

### What to Change

**Default shift selection** (`admin_ops` route in `app.py`):
- Current behavior: selects "earliest upcoming or most recent past" shift —
  this logic is correct but the *list rendering* starts at the top (oldest first)
- The selected shift is already correct. The fix is purely in how the left panel
  renders and scrolls.

**Shift list panel** (`admin/ops.html`):
- Render order stays chronological (past → future) so scrolling up = past,
  scrolling down = future — this is the natural mental model
- On page load, use JS to scroll the shift list panel so the currently selected
  shift is visible and vertically centered in the panel
- The selected shift element should have a known ID or data attribute
  (`data-shift-id` already exists or add it) so the JS can target it
- Implementation: after DOM ready, call
  `selectedShiftEl.scrollIntoView({ block: 'center', behavior: 'instant' })`
  on the shift list panel's selected item

**No route changes needed.** This is a single JS addition to `admin/ops.html`.

### Definition of Done
- [ ] Loading `/admin/ops` with a current shift selected — the shift list panel
  is scrolled so the selected shift is visible without manual scrolling
- [ ] Past shifts are still accessible by scrolling up in the panel
- [ ] Future shifts are still accessible by scrolling down
- [ ] Clicking a different shift (full page reload to `?shift_id=<id>`) — new
  selected shift is centered in the panel on reload

---

## Fix 3 — Ops Tab: Drag-to-Reorder Stops

### What's Wrong
The "Order Route" button runs a nearest-neighbor algorithm server-side, but the
result is never visibly applied in the UI — stops always appear in assignment
order regardless. The button is misleading. The real need is simple: let the
admin manually drag stops into the order they want.

### What to Change

**Remove auto-ordering:**
- Remove the "Order Route" button from the ops top bar (`admin/ops.html`)
- Keep route `POST /admin/crew/shift/<id>/order` in `app.py` — do not delete —
  but remove all UI entry points
- Stop order = assignment order by default (this is already the de facto behavior)

**New "Reorder" button on each truck card:**
- Small secondary button on the truck card header: "Reorder Stops"
- Only visible when the shift has ≥ 2 stops assigned to that truck
- Links to: `GET /admin/ops/shift/<shift_id>/truck/<truck_number>/reorder`

**New reorder page** (`admin/ops_reorder.html`):
- Extends `admin_layout.html`
- Header: "Reorder Stops — Truck [N] · [Shift label]" + Back to Ops link
  (`/admin/ops?shift_id=<id>`)
- Body: a single draggable list of stops for that truck
- Each stop row shows:
  - Drag handle (⠿ icon, left side)
  - Stop number badge (updates live as user drags)
  - Seller name
  - Address
  - Unit count badge
- "Save Order" button (bottom, `.btn-primary`)
- "Cancel" link back to ops page

**Drag-and-drop implementation:**
- Load SortableJS from cdnjs:
  `https://cdnjs.cloudflare.com/ajax/libs/Sortable/1.15.0/Sortable.min.js`
- Initialize on the stop list `<ul>` with:
  ```javascript
  Sortable.create(el, {
    handle: '.drag-handle',
    animation: 150,
    ghostClass: 'sortable-ghost'   // style with --bg-cream background
  })
  ```
- Stop number badges update live as the user drags (use a MutationObserver or
  reindex in the `onEnd` callback)
- On "Save Order": collect ordered `stop_id` values from DOM, POST as JSON to
  new save route

**New save route:**
- `POST /admin/ops/shift/<shift_id>/truck/<truck_number>/reorder`
- Function: `admin_ops_reorder_stops`
- Body: `{ "stop_ids": [id, id, id] }` — ordered list of ShiftPickup IDs
- Validates: all stop_ids belong to this shift + truck, no extras, no missing
- Writes: `ShiftPickup.stop_order = index + 1` for each stop in the submitted order
- Returns: redirect to `/admin/ops?shift_id=<shift_id>` on success
- Auth: same as other ops routes — `is_admin or is_super_admin or is_campus_director`

**New routes:**

| Method | Path | Function | Description |
|---|---|---|---|
| `GET` | `/admin/ops/shift/<shift_id>/truck/<truck_number>/reorder` | `admin_ops_reorder_page` | Render drag-to-reorder page for one truck's stops |
| `POST` | `/admin/ops/shift/<shift_id>/truck/<truck_number>/reorder` | `admin_ops_reorder_stops` | Save new stop_order values |

### Definition of Done
- [ ] "Order Route" button is gone from ops top bar
- [ ] "Reorder Stops" button appears on truck cards with ≥ 2 stops
- [ ] Clicking "Reorder Stops" loads the reorder page for that truck
- [ ] Stops appear as a draggable list with drag handles
- [ ] Dragging reorders the list; stop number badges update in real time
- [ ] "Save Order" POSTs the new order and redirects back to ops
- [ ] Stops appear in saved order on the truck card after redirect
- [ ] Works correctly on mobile touch (SortableJS handles this)
- [ ] "Cancel" returns to ops without saving
- [ ] Attempting to reorder with invalid stop IDs returns an error

---

## Fix 4 — Crew Tab: Collapsible Workers, Current Week Default, No-Scroll Interactions

### What's Wrong
Three related problems on `/admin/crew`:

1. **Workers section is not collapsible.** The approved workers list can be long.
   To see the shift board, admin has to scroll past all worker cards every time.

2. **Shift board defaults to wrong week.** Week navigation shows the furthest
   future week first. Admin has to click the back arrow (sometimes multiple
   times) to reach the current week.

3. **Week nav and worker assign/remove cause page scroll.** Clicking the week
   arrow reloads the page (plain `<a>` link) and the browser jumps to the top,
   forcing admin to scroll back down past worker cards to the shift board.
   Assigning or removing a worker (form POST → redirect) has the same problem.

### What to Change

#### 4a — Collapsible Workers Section

Wrap the worker cards section in a `<details>`/`<summary>` element:
```html
<details id="workers-section" open>
  <summary>Workers ({{ workers|length }})</summary>
  <!-- worker cards -->
</details>
```
- Default state: `open` (expanded) — no behavior change for existing users
- Collapse state persists in `localStorage` under key `crew_workers_collapsed`
  so it stays collapsed if the admin closed it
- On page load: if `localStorage.getItem('crew_workers_collapsed') === 'true'`,
  remove the `open` attribute
- On toggle: update localStorage
- The `<summary>` bar shows "Workers (N)" with a chevron indicating open/closed
  state. Style with existing `.card` and `--primary` variables.

#### 4b — Shift Board Defaults to Current Week

**Current behavior:** Week navigation uses plain `<a>` links to prev/next week
IDs resolved at render time. The default week shown is whichever week the route
currently defaults to (apparently the furthest future week).

**Fix in `admin_crew_panel` route (`app.py`):**
- The route currently renders with a default week. Change the default week
  selection logic to: current active week (same logic as
  `_get_current_published_week()` — active running week → nearest upcoming →
  most recent past)
- Accept `?week_id=<id>` query param to override (already the pattern for
  week navigation links — confirm this is the case or add it)
- The week displayed on load is now always the current/nearest week

#### 4c — Fetch-Based Week Navigation and Worker Assign/Remove

This is the core of the fix. Replace three interactions with fetch so the page
never reloads and scroll position is preserved.

**Shift board partial** — extract the shift board HTML into a server-rendered
partial that can be returned standalone:
- New route: `GET /admin/crew/shift-board?week_id=<id>` →
  `admin_crew_shift_board_partial`
- Returns HTML partial (no layout) — the shift board for the given week
- Auth: same as `/admin/crew`
- This partial is also what the full page renders initially (included via Jinja
  `{% include %}` or rendered inline — either works)

**Week navigation (prev/next arrows):**
- Change from plain `<a>` links to `<button>` elements with
  `data-week-id="<id>"` attributes
- On click: fetch `GET /admin/crew/shift-board?week_id=<id>`, replace the
  `#shift-board` container innerHTML with the response
- Update the week label in the header (include it in the partial response, or
  return JSON with `{html, week_label}` — HTML-only partial is simpler)
- No page reload, no scroll

**Worker quick-add** (`POST /admin/crew/shift/<id>/quick-add`):
- Currently: form POST → redirect (full page reload)
- Change to: fetch POST from the shift board UI
- On success: re-fetch the shift board partial for the current week and replace
  `#shift-board` innerHTML — refreshes just the board
- On error: show inline error (flash-style message near the shift row, not a
  page-level flash)
- The `admin_crew_quick_add` route should detect `X-Requested-With: fetch`
  header (or `Accept: application/json`) and return JSON
  `{success: true/false, message: "..."}` instead of a redirect when called
  via fetch. Fall back to redirect for non-fetch callers (safety).

**Worker quick-remove** (`POST /admin/crew/shift/<id>/quick-remove`):
- Same pattern as quick-add above
- Return JSON on fetch, redirect on form POST

**Implementation note on scroll preservation:**
Because all three interactions are now fetch-based and only replace the
`#shift-board` div, the page scroll position never changes. The worker cards
above remain wherever they are. No scroll save/restore logic needed.

**New route:**

| Method | Path | Function | Description |
|---|---|---|---|
| `GET` | `/admin/crew/shift-board` | `admin_crew_shift_board_partial` | Returns shift board HTML partial for a given `?week_id=`. No layout. Auth-gated. |

**Modified routes (behavior change, not new routes):**
- `admin_crew_quick_add` — returns JSON when fetch request detected
- `admin_crew_quick_remove` — returns JSON when fetch request detected

### Definition of Done
- [ ] Workers section has a collapsible header showing worker count
- [ ] Collapsing/expanding workers persists across page reloads (localStorage)
- [ ] `/admin/crew` loads with the current week's shift board visible by default
- [ ] Clicking prev/next week arrows updates the shift board in place — no page
  reload, no scroll jump
- [ ] Adding a worker to a shift via the inline dropdown updates the shift board
  in place — no page reload, no scroll jump
- [ ] Removing a worker (× button) updates the shift board in place — no page
  reload, no scroll jump
- [ ] After any of the above interactions, scroll position is exactly preserved
- [ ] Error states (worker not found, shift full) show inline near the action
- [ ] Full page reload of `/admin/crew` still works correctly (fallback)
- [ ] All existing quick-add/quick-remove functionality is preserved

---

## Constraints — Do Not Touch

- No model changes. No migrations.
- `ShiftWeek`, `Shift`, `ShiftAssignment` data model unchanged.
- All existing POST routes for schedule, optimizer, publish/unpublish stay in
  `app.py` — only UI entry points are removed.
- `POST /admin/crew/shift/<id>/order` (nearest-neighbor) stays in `app.py`.
- Stripe, payout, seller, and item routes untouched.
- `layout.html` (public base template) untouched.
- The 30-second auto-refresh on the mover shift view (`/crew/shift/<id>`)
  is untouched.
- SortableJS loaded from cdnjs only — already in the allowed domain list.
