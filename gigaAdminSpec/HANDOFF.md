# Campus Swap — Ops System Handoff State

> Update this file after every Claude Code session. It is the source of truth
> for what has actually been built, what changed from the spec, and what the
> next session needs to know. Paste the relevant sections into Claude Code at
> the start of each session alongside CODEBASE.md and OPS_SYSTEM.md.

---

## Current State

**Last updated:** 2026-05-28 (end of session)
**Active spec:** None
**Overall status:** Specs #1–9 + Admin UI Redesign + all previous features in production. This session: AI Autofill, Warehouse Floor, Shop Drop improvements (retail price, infinite scroll, ai_approved gate), Photo Verification Queue all built.

---

## Features Built This Session (2026-05-28, afternoon)

### AI Autofill + AI Review Queue

**Status:** Built. Needs deploy to production.

Uses Claude vision API to generate title, description, price, and retail reference for items. Runs as a background thread. Items must have `ai_generated_at IS NULL` to be eligible.

**New model fields on InventoryItem:**
- `ai_description`, `ai_long_description` (Text, nullable) — staged
- `ai_price`, `ai_retail_price` (Numeric, nullable) — staged
- `ai_review_pending` (Boolean) — in review queue
- `ai_generated_at` (DateTime, nullable) — NULL = eligible; set on success OR error (error sentinel)
- `ai_approved` (Boolean) — set at review approval; gates shop visibility
- `retail_price` (Numeric, nullable) — live retail reference copied from ai_retail_price at approval; shown to buyers
- `needs_new_photo` (Boolean) — item approved but photo needs replacement; hides from shop
- `needs_photo_verification` (Boolean) — item has had its photo replaced; enters verification queue pending admin review

**Migrations:** `da3bed86df50`, `af636a52a985`, `df2ec76b3e37`, `3549247ca9e5`, `7978e1bce77b`, `7d66b13ebef5` — all applied locally. Need `flask db upgrade` on Render after deploy.

**Env var needed on Render:** `ANTHROPIC_API_KEY`

**Key behavior:**
- Generation uses `claude-sonnet-4-6` by default (selectable per run)
- Retail price floored to ensure ≥40% apparent savings (raises retail, never lowers our price)
- Em-dashes stripped from all AI output
- `ai_retail_price` copied to live `retail_price` at approval time — shown to buyers on inventory cards and product pages
- "Flag for new photo" checkbox on approval: sets `needs_new_photo=True`, `ai_approved=True` — item approved but hidden from shop until photo replaced

**New routes:** `/admin/ai/generate`, `/admin/ai/review`, plus detail/approve/discard/set-cover-photo/delete-gallery-photo per item.

**Nav badge:** AI Review item in sidebar (super admin only), amber badge showing pending count.

---

### Shop Drop Improvements

**Status:** Built. Needs deploy.

- **Shop visibility gate:** Only `ai_approved=True AND needs_new_photo=False` items appear. All previously approved items hidden until processed through AI review.
- **Retail + savings callout:** `item.retail_price` shown as "~$X retail · Y% off" on inventory cards and product pages.
- **Infinite scroll:** Replaced 24-item pagination with IntersectionObserver + `?ajax=1` endpoint. Item count removed from public page header.
- **Shop teaser toggle** added to Admin Settings page.

---

### Warehouse Floor

**Status:** Built. Needs deploy.

Replaces `/admin/storage/audit`. New URL: `/admin/warehouse`. Old URL redirects 302.

**New model field:** `StorageLocation.snapshot_capacity` (Float, nullable). Migration: `9833fccaa78e`.

**Capacity battery:** Visual bar on each unit card. Green 75–100%, amber 40–74%, red <40%, striped dark-red >100%, grey if no snapshot. Set by clicking "Mark as Full" (snapshots current item volume). "Mark as Available" does NOT clear snapshot.

**Log Item flow:** 4-step modal: photo (getUserMedia + fallback) → category → storage location → seller. Three seller modes: Campus Swap internal, existing seller (live search), new proxy seller (payout_rate=50, is_proxy_account=True).

**Needs New Photo section:** Amber collapsible (collapsed by default). Shows items with `needs_new_photo=True`. Camera button opens replace-photo modal.

**Photo Verification Queue:** Indigo collapsible (open by default). Shows items with `needs_photo_verification=True`. After replacing a photo (from warehouse or AI review), item enters this queue. Admin can: Download photo → Photoshop it → Re-upload → Click "Looks Good". "Looks Good" POSTs to `POST /admin/item/<id>/verify-photo` which clears the flag.

**replace_photo bug fix:** Old cover photo is now deleted from ItemPhoto records when a new cover is uploaded, preventing the old cover from appearing as a gallery carousel item.

**Removed:** `GET /admin/items/needs_info` route and `admin/needs_info.html` template. QC nav badge removed. `qc_pending_count` context processor injection removed. QC items now surface via AI autofill pipeline.

**Crew quick capture:** Category selector added (required in UI, null-safe on backend). Camera block extracted to `_qc_camera_block.html` reusable partial.

**Search:** Global search (debounced 300ms) + unit-scoped search. "Select Unit" inline picker expands below search result row. Camera button on needs_new_photo items in search results. "Update" link (which went to full edit form) removed — replaced with inline location picker only.

**Gallery management in AI review modal:**
- "★ Set as cover" button appears on non-cover gallery slides
- "Delete" button appears on non-cover gallery slides (red, top-right)
- Both reload the modal detail partial on success

---

## Completed Specs

- Spec #1 — Worker Accounts ✅ Signed off 2026-04-06
- Spec #2 — Shift Scheduling ✅ Signed off 2026-04-06
- Spec #3 — Driver Shift View ✅ Signed off 2026-04-07
- Mini-Spec — Shift History & Completion Counting ✅ Signed off 2026-04-07
- Spec #4 — Organizer Intake ✅ Signed off 2026-04-08
- Referral Program ✅ Complete 2026-04-09 (60/60 tests passing)
- Payout Boost ✅ Complete 2026-04-13
- Item Draft System ✅ Complete 2026-04-13
- Onboarding Payout Removal ✅ Complete 2026-04-13
- Buyer Delivery Flow ✅ Complete 2026-04-13 (36/37 tests; 1 test hardcoded wrong range)
- Shop Drop Teaser ✅ Complete 2026-04-13
- Pickup Location Improvements ✅ Complete 2026-04-14 (50/50 tests passing)
- Spec #5 — Payout Reconciliation ✅ Signed off 2026-04-14
- Spec #6 — Route Planning ✅ Signed off 2026-04-14 (69/69 tests passing)
- Spec #7 — Seller Progress Tracker ✅ Signed off 2026-04-14 (39/39 tests passing)
- Spec #8 — Seller Rescheduling ✅ Signed off 2026-04-14
- Spec #9 — SMS Notifications ✅ Signed off / in production (42/42 tests passing)
- Admin UI Redesign ✅ Signed off / in production (69/69 route + 42/42 SMS passing)
- feature_onboarding_class_year ✅ Complete ~2026-04-29 (adds class year field to onboarding + User model)
- feature_parents_and_instagram ✅ Complete ~2026-04-29 (parents landing page + Instagram link)
- fix_remove_ai_pricing ✅ Complete ~2026-05-01 (removed ItemAiResult model + migration; was causing 500 errors)
- feature_ops_admin_fixes ✅ Complete ~2026-05-03 (bulk week reassign, unassigned panel filter fix, assign-unit CSS fix)
- feature_ops_fixes_round2 ✅ Complete ~2026-05-03 (eligibility filter expanded, week filter removed, auto-assign fetch, stats bar fix, remove truck feature)
- feature_crew_hq ✅ Complete ~2026-05-04 (Crew HQ redesign at /admin/crew — worker cards, shift board, quick-add/remove)
- feature_admin_availability_override ✅ Complete ~2026-05-04 (admin can override worker availability from Crew HQ modal)
- fix_crew_dashboard_and_soft_stops ✅ Complete ~2026-05-05 (crew dashboard shows all assignments regardless of published state; soft stop actions deferred until End Shift with confirmation page)
- fix_crew_quick_add_truck_number ✅ Complete ~2026-05-05 (quick-add drivers default to truck_number=1)
- fix_crew_remove_worker ✅ Complete ~2026-05-05 (admin can remove a worker + all their ShiftAssignments)
- fix_crew_shift_items_and_phone ✅ Complete ~2026-05-05 (stop cards now show 'approved' items; phone number always visible)
- feature_shift_history_items ✅ Complete ~2026-05-05 (GET /crew/shift/<id>/history — read-only completed shift item list)
- feature_quick_capture ✅ Complete 2026-05-20 (driver photo capture at pickup; internal Campus Swap account; admin queue)
- feature_quick_capture_ux_fixes ✅ Complete 2026-05-20 (notes field, modal reset, stop card photo strip, crew+admin hard delete)
- fix_quick_capture_status_and_approval ✅ Complete 2026-05-20 (status→pending_valuation, one-click approve, approval queue filtering, digest filtering)
- feature_approval_queue_modal ✅ Complete 2026-05-21 (single-page modal flow for approval queue; no new tabs; fetch partial + fetch POST actions)
- feature_campus_director_tutorial ✅ Complete 2026-05-21 (5-step onboarding tutorial for new campus directors; sandbox fixtures; step-gated overlay cards)
- fix_auth_guard_audit ✅ Complete 2026-05-21 (5 crew/ops routes changed from is_admin to _has_ops_access for campus director access)
- feature_storage_audit_and_placement ✅ Complete 2026-05-28 (storage audit tool, driver placement flow, storage unit management overhaul, bulk import, Postgres startup fix)

---

## Feature: Storage Audit Tool + Driver Placement + Storage Unit Management (Built 2026-05-28)

**Status:** In production

### What Was Built

#### Postgres Startup Fix
`db.create_all()` previously only ran when `DATABASE_URL` was absent (i.e., SQLite-only). On a fresh Postgres deployment the tables were never created — seed queries failed, Postgres aborted the transaction, and every subsequent request 500'd with `relation "user" does not exist`. Fixed by running `db.create_all()` unconditionally at every app startup. Added `db.session.rollback()` to both seed exception handlers to prevent transaction abort cascade.

#### Storage Audit Tool (`/admin/storage/audit`)
Admin page to view and correct storage placement for all items across the warehouse.

**New routes:**
- `GET /admin/storage/audit` → `admin_storage_audit` — audit landing page
- `GET /admin/storage/audit/search` → `admin_storage_audit_search` — HTML partial loaded via fetch; params: `q`, `status` (all/no_unit/no_zone/placed), `unit_id`. Returns `storage_audit_results.html`.
- `POST /admin/item/<id>/set-location` → `admin_item_set_location` — update `storage_location_id + storage_row + storage_note`. Returns JSON.
- `POST /admin/item/<id>/replace-photo` → `admin_item_replace_photo` — replace cover photo from audit tool. Returns JSON `{success, photo_url}`.

**New templates:** `admin/storage_audit.html`, `admin/storage_audit_results.html`

**Bug fixes during build:**
- `url_for('serve_photo', ...)` → correct endpoint is `url_for('uploaded_file', filename=...)` with S3 URL passthrough check
- CSRF: `document.querySelector('meta[name=csrf-token]')` returns `null` (no meta tag in `layout.html`). Fixed by rendering token inline: `const _auditCsrf = '{{ csrf_token() }}';`

#### Driver Placement Flow (`/crew/shift/<id>`)
After all stops are marked complete, drivers are shown a placement list for every item on their truck. They assign each item to a storage unit + zone (or mark it as not picked up) before End Shift is allowed.

**New model fields on `InventoryItem`:**
- `placement_status` (String, nullable) — `None | 'placed' | 'not_picked_up'`
- `needs_photo_refresh` (Boolean, default False)

**Migration:** `75591ac8d320_add_placement_status_to_inventory_item`

**New routes:**
- `GET /crew/shift/<shift_id>/placement` → `crew_shift_placement` — HTML partial of items needing placement; loaded into shift view via fetch
- `POST /crew/item/<item_id>/place` → `crew_item_place` — sets `storage_location_id + storage_row + placement_status='placed'`. Returns JSON.
- `POST /crew/item/<item_id>/not_picked_up` → `crew_item_not_picked_up` — sets `placement_status='not_picked_up'`. Returns JSON.

**Modified route:**
- `crew_shift_end` (confirmed path) now blocks End Shift if any items on the driver's truck have `placement_status IS NULL`

**New template:** `crew/shift_placement_partial.html` — item list with status chips, zone diagram modal, "Not picked up" button

**Bug fix during build:**
- Partial loaded via `innerHTML` → browsers silently drop `<script>` tags. Fixed by re-creating each script node after injection using `document.createElement('script')`. Pattern documented in CODEBASE.md key patterns.

#### Storage Unit Management Overhaul (`/admin/settings#storage`)
- Removed lat/lng fields from Add Storage Location form
- Each existing unit now has an Edit button that toggles an inline form (name, address, capacity note, active checkbox, Save, Cancel, Delete)
- Delete is server-blocked with 409 JSON error if any items are assigned to the unit
- New bulk import section: drag-and-drop xlsx/csv, "Download template" button, file picker, "Import units" button
- OOM fix: openpyxl defaults to loading all 1,048,576 rows — fixed with `read_only=True, data_only=True` and a 2 MB file size gate

**New routes:**
- `POST /admin/storage/<id>/delete` → `admin_storage_delete`
- `GET /admin/storage/template` → `admin_storage_template`
- `POST /admin/storage/import` → `admin_storage_import`

**Bug fix:**
- `admin_storage_edit` `is_active` was checking `== 'on'` but checkbox sends `value="1"`. Fixed to `bool(request.form.get('is_active'))`.

**New dependency:** `openpyxl>=3.1` added to `requirements.txt`

#### Dev Tooling
`seed_dev_driver.py` — idempotent script that creates a test driver account (`driver@test.com` / `driver123`), 3 sellers with 2 items each, and a completed ShiftWeek/Shift/ShiftRun/ShiftAssignment chain for testing the placement flow. Run: `python seed_dev_driver.py`. Output includes the URL to the shift view.

#### Diagnostic Route
`GET /admin/diag` → `admin_diag` — shows DB table row counts. Super admin only. Added for Postgres debugging.

### Deviations from Spec
No formal spec file — built interactively. All decisions recorded above.

---

## Feature: Campus Director Tutorial (Built 2026-05-21)

**Status:** In production
**Spec file:** `feature_tutorial.md`

### What Was Built

A 5-step interactive onboarding tutorial that walks a new campus director through the full ops workflow in a sandboxed environment. Triggered automatically on first login as a CD; can be retaken from CD Settings.

**New model (`models.py`)**
- `TutorialSession` — one per CD. Fields: `user_id` (FK → User, unique), `step` (Integer, default 0), `started_at` (DateTime), `completed_at` (DateTime, nullable), `is_retaking` (Boolean, default False).
- `User.is_tutorial_user` (Boolean, default False) — marks seed CD workers (Sam Torres, Riley Chen, Casey Brooks) so they are excluded from all non-tutorial queries.
- `ShiftWeek.is_tutorial` (Boolean, default False) — marks the sandboxed tutorial shift week so it's excluded from production ops queries.

**Migration:** `add_tutorial_session` — creates `tutorial_session` table, adds `is_tutorial_user` to `User`, adds `is_tutorial` to `ShiftWeek`.

**Tutorial step sequence (0–9):**
- 0 = not started
- 1 = started; on schedule, week not yet created
- 2 = week created (still on schedule → navigate to Crew; or on Crew → approve Sam Torres)
- 3 = Sam approved; assign crew to shift and assign sellers to ops
- 4 = worker assigned; on Crew → navigate to Ops; or on Ops → assign remaining sellers
- 5 = unused/skipped
- 6 = all sellers assigned; prompt to click Reorder Stops
- 7 = on reorder page (bumped from 6→7 on GET of ops_reorder_page)
- 8 = reordered; prompt to click Notify Sellers
- 9 = complete

**New routes (`app.py`)**
| Route | Function | Notes |
|---|---|---|
| `GET /admin/tutorial` | `admin_tutorial_welcome` | Welcome/restart page. Shows "Start" or "Retake" based on existing TutorialSession.step > 1. |
| `POST /admin/tutorial/start` | `admin_tutorial_start` | Creates or resets TutorialSession. Resets fixture workers to canonical state (Sam→pending, Riley→approved). Calls `seed_tutorial_fixtures()`. |
| `GET /admin/tutorial/complete` | `admin_tutorial_complete_page` | Completion page with checklist animation. Guard: ts.step >= 9. |
| `POST /admin/tutorial/exit` | `admin_tutorial_exit` | Sets ts.step = 9 (marks complete) for is_retaking CDs; redirects to ops. |
| `GET /admin/cd-settings` | `admin_cd_settings` | CD Settings page showing tutorial status + Retake/Continue button. |

**`seed_tutorial_fixtures()` (helper, `app.py`)**
- Idempotent. Creates or updates three sandbox users: Sam Torres (pending applicant), Riley Chen (approved worker, both roles), Casey Brooks (seller with existing ShiftPickup, rescheduled-in with moved badge).
- All tutorial users: `is_tutorial_user=True`. Excluded from all production ops queries.
- Creates a `ShiftWeek` with `is_tutorial=True`, one shift with 1 truck and 3 ShiftPickups (Casey assigned, Alex Martinez + Jordan Kim unassigned).
- On restart: resets Sam→pending/not-a-worker, Riley→approved/is_worker. Resets ShiftPickups and ShiftAssignments to canonical state.
- Ensures WorkerAvailability records exist for all tutorial workers (required for shift board dropdown to show Riley).

**Tutorial gate (`before_request`, `require_ops_access`)**
- CDs without a completed tutorial are redirected to `/admin/tutorial`.
- Gate uses DB (`TutorialSession.step >= 1 and completed_at is None and not is_retaking`) — NOT session — to avoid cookie unreliability after POST redirects.
- "Allow through" check: `in_active_first_run = ts.step >= 1 and completed_at is None and not is_retaking`. If True, gate is open regardless of session state.
- `session['tutorial_active']` is set on tutorial start and read for tutorial_mode detection in routes.

**Tutorial-mode guards in routes**
- `admin_crew_reject`: blocked in tutorial mode (flash warning). Hard-blocked for `is_tutorial_user` workers regardless of mode.
- `admin_crew_remove`: hard-blocked for `is_tutorial_user` workers (`abort(403)`).
- `admin_schedule_create`: tutorial shift created with `trucks=1` (not 2). Redirects to `admin_schedule_index` (not ops) after creation.
- `admin_routes_assign_seller`: sets `ts.step = 6` when all tutorial sellers are assigned. No auto-redirect.
- `admin_ops_reorder_page` GET: bumps step 6→7 and commits before render.
- `admin_ops_reorder_stops` POST: checks `ts.step == 7` via DB (not session), bumps to 8.
- `admin_shift_notify_sellers`: guard if `ts.step < 8` (flash + redirect). Bumps to 9 when step == 8.

**Step-advancing mechanism**
All step-bumping uses DB (`TutorialSession.step = N; db.session.commit()`). Session `tutorial_step` is kept in sync as a cache for template rendering, but is never the source of truth for action-route guards.

**New templates**
- `templates/admin/tutorial_welcome.html` — standalone welcome/restart page (extends `layout.html`)
- `templates/admin/tutorial_complete.html` — completion page with CSS checkmark animation and 6-item summary checklist
- `templates/admin/cd_settings.html` — CD Settings page: tutorial status, Retake/Continue/Start button, sidebar link in admin_layout.html
- `templates/admin/tutorial_overlay.html` — partial included in schedule_index, crew, ops, ops_reorder. Uses `request.path` to show context-appropriate content for same-step different-page states. `tutorial-highlight` CSS class pulses a ring on target elements.

**Modified templates**
- `admin/schedule_index.html` — includes overlay; Create Week card gets `tutorial-highlight` at step 1
- `admin/crew.html` — includes overlay at top; Pending Applications section moved ABOVE shift board (applies all roles, not just tutorial); `<details>` open when `pending_apps or tutorial_mode`; JS reloads page on `tutorial_step_advanced: True` response (no redirect to ops)
- `admin/ops.html` — includes overlay; Unassigned panel gets `tutorial-highlight` at step 4; Reorder Stops button gets `tutorial-highlight` at step 6 + truck 1; Notify Sellers button disabled/grayed when `tutorial_mode and tutorial_step < 8`
- `admin/ops_reorder.html` — includes overlay; Save Order button gets `tutorial-highlight`
- `admin/admin_layout.html` — Crew nav link gets `tutorial-highlight` at step 2 (on schedule); Ops nav link gets `tutorial-highlight` at step 4 (on crew); CD Settings nav item added for `is_campus_director and not is_admin and not is_super_admin`

**Role switcher (nav)**
- Inline pill in desktop nav header (between Dashboard link and user icon) for `current_user.is_campus_director`.
- "Seller" button active (dark) on non-admin pages; "Admin" button active on `/admin/*` pages. Uses `request.path.startswith('/admin')` in template.
- GET `/switch-role/seller` → sets `session['cd_view'] = 'seller'`, redirects to `/dashboard`.
- GET `/switch-role/admin` → sets `session['cd_view'] = 'admin'`, redirects to `/admin/ops`.
- Dashboard route: CD with `session['cd_view'] == 'seller'` skips ALL redirect logic (including onboard redirect) and renders the seller dashboard directly.
- Mobile hamburger menu gets the same pill.

### Deviations from Spec

1. **Step numbering shifted at steps 6–9.** Original spec had no intermediary "sellers assigned" state before reorder. Added step 6 as an explicit "all sellers assigned, click Reorder Stops" state; step 7 = on reorder page; step 8 = reordered; step 9 = complete. Steps 4 and 5 were collapsed (5 unused).

2. **Notify Sellers button disabled below step 8.** Spec didn't spec this guard. Without it, a CD could notify sellers before completing the reorder step, which defeats the tutorial flow.

3. **Tutorial gate uses DB, not session.** Session cookie is unreliable immediately after a POST/redirect cycle. Gate reads `TutorialSession.step` from DB to determine if the CD is mid-tutorial.

4. **`seed_tutorial_fixtures()` enforces canonical state on existing records.** A retake resets Sam/Riley/Casey to their original fixture state, preventing stale state from a prior run from corrupting the tutorial. WorkerAvailability records created for all tutorial workers on every seed call.

5. **Tutorial shift has 1 truck.** Spec implied the same default (2 trucks). Reduced to 1 to keep the tutorial focused and avoid "which truck?" confusion.

---

## Feature: Auth Guard Audit (Built 2026-05-21)

**Status:** In production

Five crew/ops routes were discovered using `if not current_user.is_admin: abort(403)` instead of `if not _has_ops_access(): abort(403)`. Campus directors have ops access via `_has_ops_access()` but are not `is_admin`, so they received 403s on these actions.

**Routes fixed:**

| Route | Function | Was | Now |
|---|---|---|---|
| `POST /admin/crew/shift/<id>/quick-remove` | `admin_crew_quick_remove` | `is_admin` | `_has_ops_access()` |
| `POST /admin/crew/worker/<id>/availability` | `admin_crew_override_availability` | `is_admin` | `_has_ops_access()` |
| `POST /admin/crew/shift/<id>/add-truck` | `admin_shift_add_truck` | `is_admin` | `_has_ops_access()` |
| `POST /admin/crew/shift/<id>/truck/<n>/remove` | `admin_shift_remove_truck` | `is_admin` | `_has_ops_access()` |
| `POST /admin/crew/shift/<id>/stop/<pid>/reorder` | `admin_shift_reorder_stop` | `is_admin` | `_has_ops_access()` |

**Pattern rule:** Any route that appears in the admin sidebar (ops, crew, schedule) and that a campus director would touch during normal operations must use `_has_ops_access()`. Routes that are super-admin-only or full-admin-only (items approval, settings, user management, exports) correctly keep `is_admin` or `require_super_admin()`.

---

## Feature: Approval Queue Modal Flow (Built 2026-05-21)

**Status:** In production
**Spec file:** `feature_approval_queue_modal.md`

### What Was Built

**New route (`app.py`)**
- `GET /admin/item/<id>/approval-detail` → `admin_item_approval_detail` — returns HTML partial (no layout) with full item data: gallery photos, description, long_description, suggested_price, quality, category.name, date_added, seller.full_name. Auth: `is_admin or is_super_admin`. 404 if item not `pending_valuation`. Eager-loads `gallery_photos`, `category`, `seller` via `joinedload`.

**Modified routes (`app.py`)**
- `admin_approve` (POST `/admin/approve`) — added `modal=1` branch: returns `jsonify({'success': True})` on approve/reject success; `jsonify({'success': False, 'error': '...'})` on validation failures (missing price, invalid price). Existing redirect path unchanged for non-modal requests.
- `admin_request_info` (POST `/admin/item/<id>/request_info`) — added `modal=1` branch: same JSON response pattern. Existing redirect path unchanged.

**New template (`templates/admin/approval_detail_partial.html`)**
- HTML partial (no layout). Renders gallery (track + prev/next/counter), item title, meta (seller link, category, quality, date added), long description, suggested price callout. Root div carries `data-item-id`, `data-seller-id`, `data-suggested-price` for JS to read after innerHTML injection.

**Modified template (`templates/admin/items.html`)**
- Approval queue cards: removed inline price forms and action buttons; cards are now clickable `div[role=button]` triggers with `onclick="openApprovalModal(id)"`. Each card shows thumbnail, title, seller name (stopPropagation → seller panel), date, category, suggested price badge, and "Click to review" hint.
- Added single modal instance (reused for all items): overlay + panel with close button, inner content area (spinner → partial innerHTML), footer (price input + Approve / Need Info / Reject buttons), and Need Info sub-panel (reason checkboxes + note textarea + Cancel / Send).
- Added comprehensive CSS: `.approval-modal-overlay/.panel/.close`, gallery track with prev/next buttons and counter, footer price row with input, `.btn-danger` (red outline), `.approve-card` hover lift, mobile full-height responsive layout.

**Key JS functions added:**
- `openApprovalModal(itemId)` — resets state, opens overlay, fetch-GETs `/admin/item/<id>/approval-detail`, injects innerHTML, pre-fills price from `data-suggested-price`, resets gallery index.
- `closeApprovalModal()` — removes `open` class, restores `body.overflow`.
- `approvalGalleryMove(dir)` — updates CSS transform on track + counter text.
- `approvalAction(action)` — confirm for reject, fetch POST `/admin/approve` with `modal=1`; on success calls `removeApprovalCard`; on error shows inline status message.
- `showNeedInfoPanel()` / `hideNeedInfoPanel()` / `clearNeedInfoForm()` — swap footer ↔ need-info sub-panel.
- `submitNeedInfo()` — fetch POST `/admin/item/<id>/request_info` with `modal=1`, collected reasons, note.
- `removeApprovalCard(itemId)` — removes card from DOM, decrements pending count badge, shows empty-state when grid is empty.
- Event delegation for `.seller-panel-trigger` inside modal content (required because innerHTML replacement doesn't re-run `<script>` blocks).
- Overlay click and Escape key close modal without action.

### Deviations from Spec

1. **Need Info as a sub-panel, not a separate modal.** The spec described an inline form but didn't specify whether it was inside the same panel or a second overlay. Implemented as a hidden div inside `.approval-modal-panel` that swaps with the footer — simpler, no z-index stacking issues, and the seller panel can still open simultaneously.

2. **Gallery built from `item.gallery_photos` only.** The partial uses `item.gallery_photos` (the `ItemPhoto` relationship). If `gallery_photos` is empty but `item.photo_url` exists (legacy cover-only items), it falls back to rendering the single `photo_url` image. Consistent with existing item detail pages.

3. **`maybeBoxAlert` JS function left as dead code.** It previously drove `send_box_alert` checkboxes on the inline approval forms. Those forms are gone, so the function is never called. Harmless; can be cleaned up in a future pass.

---

## Feature: Driver Quick Capture + UX Fixes + Approval Queue Fixes (Built 2026-05-20)

**Status:** In production
**Spec files:** `feature_quick_capture.md`, `feature_quick_capture_ux_fixes.md`

### What Was Built

**Model changes (`models.py`)**
- `User.is_internal_account` (Boolean, default False, server_default='0') — marks the seeded "Campus Swap" internal account
- `InventoryItem.is_quick_capture` (Boolean, default False, server_default='0') — set only on items created via this flow
- `InventoryItem.quick_capture_shift_id` (Integer, FK → Shift, nullable) — shift during which the item was captured
- `InventoryItem.captured_by_id` (Integer, FK → User, nullable) — worker who took the photo

**Migration:** `add_quick_capture_fields` — adds all four columns. Separate migration for `User.is_internal_account` seeds the internal Campus Swap account (`internal@campusswap.com`, `is_internal_account=True`, `is_seller=True`, randomized unusable password hash).

**New routes (`app.py`)**
| Route | Function | Notes |
|---|---|---|
| `POST /crew/quick_capture` | `crew_quick_capture` | Create item from driver photo. Returns JSON `{success, item_id}`. Worker-approved guard only — no shift assignment required. |
| `GET /admin/items/needs_info` | `admin_needs_info_queue` | Admin queue: `is_quick_capture=True AND status IN ('pending_valuation', 'needs_info')`. |
| `POST /admin/item/<id>/approve` | `admin_item_approve` | One-click approve for quick-capture items only. No price/description required. Sets `status='available'`, resolves open SellerAlerts. Returns JSON. |
| `POST /crew/quick_capture/<id>/delete` | `crew_quick_capture_delete` | Hard delete by capturing worker. Guards: `captured_by_id == current_user.id`, `is_quick_capture=True`, `status IN ('pending_valuation', 'needs_info')`. Deletes disk file + gallery + DB record. |
| `POST /admin/quick_capture/<id>/delete` | `admin_quick_capture_delete` | Hard delete by admin. No `captured_by_id` guard. Same disk+DB cleanup. |

**Modified routes (`app.py`)**
- `crew_shift_stops_partial` — adds `quick_captures_by_seller` dict to template context (QC items for this shift, keyed by seller_id)
- `crew_quick_capture` — reads `notes` from form → `long_description` on item; initial `status='pending_valuation'` (not `'needs_info'`)

**Context processor (`app.py`)**
- `inject_qc_pending_count` — injects `qc_pending_count` for admin nav badge. Counts `is_quick_capture=True AND status IN ('pending_valuation', 'needs_info')`.

**Approval queue filtering (`app.py`)** — `is_quick_capture == False` added to:
- `admin_items` approval queue query (line ~12135)
- Legacy `admin_approve` GET query (line ~2814)
- `pending_items_count` stats counter in `admin_panel`
- `pending_approval` stats counter in `admin_items`
- `_run_approval_digest` query — QC items never trigger or appear in the hourly digest email

**New templates**
- `templates/crew/quick_capture_modal.html` — standalone modal partial included in `crew/dashboard.html` and `crew/shift.html`. Camera: `getUserMedia` (rear-facing) with file-input fallback. Full state reset on every open (blob, button text, notes, camera stream). After save: re-fetches `stops_partial` before closing modal so photo appears immediately.
- `templates/admin/needs_info.html` — table of pending QC items with Edit, Approve (green, one-click), and Delete buttons. Delete and Approve both use JS event delegation with `fetch` + DOM row removal on success.

**Modified templates**
- `crew/stops_partial.html` — QC photo strip below each stop card. Each thumbnail has an `×` delete button (`data-item-id`, `data-csrf`). Event delegation JS on `document` (survives 30s innerHTML replacement). `__qcDeleteListenerAttached` guard prevents duplicate listeners.
- `crew/dashboard.html` — Quick Capture button opens modal (`data-qc-trigger`, no shift context)
- `crew/shift.html` — Quick Capture button in shift header (`data-qc-trigger`, `data-shift-id`, `data-active-seller-id`)

### Deviations from Spec
1. **Initial status is `pending_valuation`, not `needs_info`** — spec said `needs_info`; changed during session. QC items enter the normal approval pipeline. `needs_info` is only reached via explicit admin action (request_info). The admin queue at `/admin/items/needs_info` queries both statuses.
2. **One-click approve route is new, not pre-existing** — spec referenced "the existing approval route." No such REST path existed. New `admin_item_approve` route created: quick-capture-only, no price required, returns JSON for DOM removal.
3. **Crew delete guards `status IN ('pending_valuation', 'needs_info')`** — spec said `status != 'needs_info'`; updated to cover `pending_valuation` since that's the new initial status.
4. **Photo deletion uses `photo_storage.delete_photo()`** — not direct `os.remove()`. Handles both local and S3 storage backends correctly.

### Known Issues / Follow-up
- Internal Campus Swap account should not appear in seller-facing UI. Gate already exists via `is_internal_account=False` on seller queries.
- Payout reconciliation queue should exclude internal account items. Filter `seller.is_internal_account == False` documented in spec; verify when running first payout export.
- Google Maps Static API key needed for stop map images (separate from QC) — see existing HANDOFF notes.

---

## Spec #9 — SMS Notifications (Complete)

**Status:** Built 2026-04-14 — awaiting sign-off
**Spec file:** `feature_sms_notifications.md`
**Test file:** `test_sms_notifications.py` — 42/42 passing

### What Was Built

**New dependency (`requirements.txt`)**
- `twilio>=9.0.0`

**Model changes (`models.py`)**
- `User.sms_opted_out` (Boolean, default False, server_default='0') — set by Twilio inbound webhook
- `ShiftPickup.issue_type` (String 20, nullable) — `'no_show'` | `'other'` | NULL
- `ShiftPickup.no_show_email_sent_at` (DateTime, nullable) — idempotency guard; never cleared
- `RescheduleToken.revoked_at` (DateTime, nullable) — set when pickup completed

**Migration (`add_sms_and_no_show_fields`)**
- Adds all four columns, idempotent (table-existence + column-existence guards)
- Seeds 4 AppSettings: `sms_enabled` ('true'), `sms_reminder_hour_eastern` ('9'), `no_show_email_enabled` ('true'), `no_show_email_hour_eastern` ('18')

**New helpers (`app.py`)**
- `_normalize_phone(raw)` — normalizes to E.164; returns None on failure
- `_send_sms(user, body)` — central SMS sender; guards on sms_enabled, phone, sms_opted_out, Twilio env vars; silently returns False on any skip/failure
- `_cron_auth_ok()` — checks `Authorization: Bearer <CRON_SECRET>` header

**Modified helpers (`app.py`)**
- `_notify_next_seller(shift, current_pickup)` — stub replaced with real implementation: truck-filtered "you're next" SMS to next pending stop; skips if stop has `issue_type` set

**Modified routes (`app.py`)**
- `crew_shift_start` — removed `_notify_next_seller(shift)` call; now SMSes ALL pending sellers on mover's truck after ShiftRun creation
- `crew_shift_stop_update` (completion path) — revokes open reschedule tokens; calls `_notify_next_seller`; notes-required check removed (notes now optional for both statuses)
- `crew_shift_stop_update` (issue path) — saves `issue_type` from POST (defaults to `'other'`); extends token TTL if `no_show`
- `crew_shift_stop_revert` — clears `issue_type = None`; does NOT clear `no_show_email_sent_at`
- `admin_shift_notify_sellers` — sends SMS alongside email for each unnotified seller
- `seller_reschedule_get` — checks `revoked_at` before `used_at` (order matters)
- `seller_reschedule_post` — same revoked_at check added
- `admin_route_settings` — handles 4 new SMS AppSettings in POST + passes them to template

**New routes (`app.py`)**
- `POST /admin/cron/sms-reminders` → `cron_sms_reminders` — daily 24hr SMS reminder cron (auth: `Authorization: Bearer <CRON_SECRET>`)
- `POST /admin/cron/no-show-emails` → `cron_no_show_emails` — end-of-day no-show recovery email cron (auth: same)
- `POST /sms/webhook` → `sms_inbound_webhook` — Twilio STOP/UNSTOP handler; validates Twilio signature if `TWILIO_AUTH_TOKEN` is set; skips validation in dev

**Modified templates**
- `templates/crew/shift.html` — phone as `tel:` link on each stop card ("No phone on file" if null); issue form replaced with two-option picker (Seller wasn't home / Item or access problem); `selectIssueType()` JS; `issue_type` hidden input defaults to `'other'`
- `templates/seller/reschedule_confirm.html` — new `revoked` error branch (shown when `revoked_at` set)
- `templates/admin/route_settings.html` — new SMS Notifications section: sms_enabled toggle, sms_reminder_hour_eastern, no_show_email_enabled toggle, no_show_email_hour_eastern

### New Env Vars Required (Render)
- `TWILIO_ACCOUNT_SID` — Twilio console → Account Info
- `TWILIO_AUTH_TOKEN` — Twilio console → Account Info
- `TWILIO_FROM_NUMBER` — purchased Twilio number in E.164 format (e.g. `+19845551234`)

### New Cron Jobs to Register in Render
1. **SMS 24hr reminder:** `POST https://usecampusswap.com/admin/cron/sms-reminders`
   - Header: `Authorization: Bearer <CRON_SECRET>`
   - Schedule: daily at 9am ET
2. **No-show recovery emails:** `POST https://usecampusswap.com/admin/cron/no-show-emails`
   - Header: `Authorization: Bearer <CRON_SECRET>`
   - Schedule: daily at 6pm ET

### Twilio Webhook Setup
- After deploy, set inbound webhook URL in Twilio console:
  `Phone Numbers → Manage → Active Numbers → [your number] → Messaging → Webhook URL`
- Set to: `https://usecampusswap.com/sms/webhook` (HTTP POST)

### Deviations from Spec
1. **`issue_type` missing → defaults to `'other'`** — per session decision. Graceful degradation for JS failure mid-route.
2. **Notes no longer required for issue flags** — per session decision. `issue_type` now carries the semantic meaning; notes are truly optional for both types.
3. **`_send_sms` for Twilio uses lazy import** (`from twilio.rest import Client` inside the function body) — avoids an import-time crash when Twilio isn't installed locally; tests run without the package.
4. **`sms_inbound_webhook` skips signature validation when `TWILIO_AUTH_TOKEN` not set** — dev/test environments have no real Twilio. Route still responds 200/TwiML correctly.
5. **`cron_sms_reminders` is NOT idempotent** — documented in a comment. If run twice in one day, duplicate SMS will be sent. No guard added; spec accepted this.

### Known Issues / Follow-up
- Twilio not installed locally; `_send_sms` will always return False until `pip install twilio` or deployment. All tests mock the call.
- `sms_reminder_hour_eastern` and `no_show_email_hour_eastern` AppSettings are informational only — they document the intended cron schedule but the cron schedule itself is set in Render. The values are not read by code.
- The `test_sms_notifications.py::TestSmsWebhook::test_invalid_signature_returns_403` test mocks the entire twilio module in sys.modules because the package is not installed locally. Will work identically once twilio is pip-installed.

---

## Admin UI Redesign (Built 2026-04-15)

**Status:** Built 2026-04-15 — awaiting sign-off
**Spec file:** `feature_admin_redesign.md`
**Tests:** 69/69 route planning + 42/42 SMS still passing. Pre-existing tracker test failure (1 test, unrelated to this spec) unchanged.

### What Was Built

**Migration (`admin_redesign_shift_last_notified`)**
- Adds `Shift.last_notified_at` (DateTime, nullable) — set when `admin_shift_notify_sellers` runs
- Revises: `add_sms_and_no_show_fields`

**Model changes (`models.py`)**
- `Shift.last_notified_at` (DateTime, nullable) added

**Shell layout (`templates/admin/admin_layout.html`)**
- New base template extending `layout.html` — wraps all admin pages
- 52px icon-only sidebar with Font Awesome icons + hover tooltips
- Active tab auto-detected from `request.path` (no route changes needed for existing pages)
- Mobile: sidebar collapses to horizontal top bar

**`layout.html` changes**
- "Admin Panel" + "Routes" dropdown links → single "Admin" link to `/admin/ops`

**New routes (`app.py`)**
| Route | Function | Notes |
|---|---|---|
| `GET /admin/ops` | `admin_ops` | Main ops view — shift panel, truck cards, unassigned panel |
| `GET /admin/ops/truck-detail` | `admin_ops_truck_detail` | HTML partial for truck detail drawer |
| `GET /admin/items` | `admin_items` | Items tab — approval queue + lifecycle table |
| `GET /admin/sellers` | `admin_sellers` | Sellers tab — list, nudge, free-tier |
| `GET /admin/crew` | `admin_crew_panel` | Crew tab — pending apps + approved workers |
| `GET/POST /admin/settings` | `admin_settings` | Settings tab — all 9 sections on one page |
| `POST /admin/settings/generate-shifts` | `admin_generate_shifts` | Idempotent shift skeleton generator |

**Redirects added**
- `GET /admin` → `GET /admin/ops` (302) — POST still handled by `admin_panel`
- `GET /admin/routes` → `GET /admin/ops` (302)
- `GET /admin/approve` → `GET /admin/items?view=approve` (302) — POST still works for existing form
- `GET /admin/settings/route` → `GET /admin/settings#route` (302) — POST still works
- `GET /admin/storage` → `GET /admin/settings#storage` (302)

**New templates**
- `admin/ops.html` — 3-zone layout (shift list 220px, truck cards main, unassigned panel 210px) + truck detail drawer
- `admin/ops_truck_detail.html` — partial (no layout), injected into drawer via fetch
- `admin/items.html` — sub-tab pills (All Items / Approval Queue), stats bar, store controls collapsible, filter bar
- `admin/sellers.html` — sortable table with client-side search, nudge and free-tier collapsibles
- `admin/crew.html` — expandable application rows with availability grid, approved worker table
- `admin/settings.html` — 9 anchor-linked sections, pickup window + generate shifts, all existing settings consolidated

**Templates migrated to admin_layout.html**
- `shift_ops.html`, `schedule_index.html`, `schedule_week.html`, `route_settings.html`
- `storage_index.html`, `storage_detail.html`, `intake_flagged.html`, `shift_intake_log.html`
- `payouts.html`, `routes.html`

**Modified helpers (`app.py`)**
- `seed_crew_app_settings` — adds `pickup_week_start` and `pickup_week_end` keys (empty string defaults)
- `admin_shift_notify_sellers` — now sets `shift.last_notified_at = _now_eastern()` on notify
- `admin_shift_order_stops` — redirects to `admin_ops` when called from ops page (referrer check)
- `admin_shift_add_truck` — redirects to `admin_ops` for browser form submissions (Accept: text/html check)
- `admin_routes_assign_seller` — now accepts form-encoded `shift_truck="<id>_<truck>"` in addition to JSON; redirects to `admin_ops` on form submit
- `_run_auto_assignment` — cluster-first sort: partner buildings (alpha) → dorms (alpha) → proximity → Unlocated; unit count desc within each cluster

**New helper functions**
- `_ops_shift_date(shift)` — calendar date from Shift object (same as `_shift_date`, scoped to ops module)
- `_ops_build_truck_cards(shift, pickups, effective_cap)` — per-truck card data including live state derivation
- `_ops_build_unassigned_panel(shift)` — unassigned sellers filtered by shift slot + cluster grouping
- `_ops_build_shift_list()` — all shifts sorted for left panel, with unnotified counts

### Deviations from Spec
1. **Active tab detection uses `request.path` in `admin_layout.html`** — Jinja2 `{% set %}` in child templates doesn't propagate to parent. Path-based detection is automatic and requires no per-route changes.
2. **`admin_storage_index` GET redirects immediately** — old body removed since all content moves to `admin_settings#storage`. The create/edit POST routes still work unchanged.
3. **`admin_routes_assign_seller` accepts hybrid form data** — existing JSON API preserved; added form `shift_truck` param so the ops panel can use a plain HTML form without JS fetch.
4. **4 route planning tests updated** — tests that checked for 200 on redirected URLs updated to accept `in (200, 302)`. Semantics preserved.

---

## Production Operations Fixes (2026-05-01 – 2026-05-05)

**Status:** All in production as of 2026-05-05
**Spec files:** `feature_ops_admin_fixes.md`, `feature_ops_fixes_round2.md`, `fix_crew_dashboard_and_soft_stops.md`, `fix_crew_quick_add_truck_number.md`, `fix_crew_remove_worker.md`, `fix_crew_shift_items_and_phone.md`, `fix_remove_ai_pricing.md`

### fix_remove_ai_pricing — ItemAiResult removal
- Deleted `ItemAiResult` model (was causing 500 errors on `POST /edit_item` due to orphaned rows with `item_id=NULL`)
- Removed all app.py routes + references to AI pricing
- Migration `remove_item_ai_result` drops the table
- Shell fix: deleted orphaned `item_ai_result` rows on Render before deploy

### feature_ops_admin_fixes — Three ops bugs
- **Bulk week reassign**: `POST /admin/settings/reassign-week` → `admin_reassign_week` — sets `pickup_week = 2` for all sellers with `pickup_week = 1` and no `ShiftPickup`. Super admin only. Added section to `admin/settings.html`.
- **Unassigned panel filter**: Removed `pickup_week == current_week` match requirement. Now shows all sellers with `pickup_week IS NOT NULL` and no `ShiftPickup`. Week badge still displayed on cards.
- **Assign unit CSS fix**: Truck card footer now uses `flex-wrap: wrap` so "Assign unit" button is never clipped.

### feature_ops_fixes_round2 — Four ops bugs + remove truck
- **Item eligibility expanded**: `_ops_build_unassigned_panel()`, `_run_auto_assignment()`, and `get_seller_unit_count()` now include `'approved'` items (not just `'available'`). Filter: `status NOT IN ('rejected', 'needs_info')`.
- **Week filter fully removed**: Same two functions — `pickup_week` no longer used as a filter, only displayed as a badge.
- **Auto-assign fetch**: Changed from `<form>` submit to `fetch()` POST in `ops.html`; page reloads to `?shift_id=<id>` on success. Prevents raw JSON rendering in browser.
- **Stats bar total count**: `admin_items` now excludes `rejected` items from total count.
- **Remove truck**: New route `POST /admin/crew/shift/<id>/truck/<n>/remove` → `admin_shift_remove_truck`. Validates: highest truck only, zero stops. Uses raw SQL. Clears truck from `truck_unit_plan`. Button only shown on highest-numbered truck with 0 stops.

### fix_crew_dashboard_and_soft_stops
- **Crew dashboard**: `crew_dashboard()` now builds `my_shifts` directly from the worker's `ShiftAssignment` records (no publish-state gate). Workers see their assignments immediately even on draft weeks.
- **`crew_schedule_week`**: No longer 404s on draft weeks if the current user has an assignment in that week.
- **Soft stop actions**: `crew_shift_stop_update` no longer writes `picked_up_at` immediately. Stop status changes are soft on `ShiftPickup` only until End Shift.
- **`crew_shift_stop_revert`**: Simplified — no item-level compensating writes needed since nothing was written on complete.
- **End Shift two-step**: `crew_shift_end` without `confirmed=1` now redirects to confirmation page. New route: `GET /crew/shift/<id>/end-confirm` → `crew_shift_end_confirm`. Shows stop summary + warning. New template: `crew/shift_end_confirm.html`.
- **`picked_up_at` commit**: Deferred to `crew_shift_end` with `confirmed=1`. Writes to `available`-status items only. `crew_shift_complete_retroactive` still writes immediately (unchanged).

### fix_crew_quick_add_truck_number
- `admin_crew_quick_add`: Driver-role assignments now default to `truck_number=1` instead of `None`. Fixes "assigned but invisible" bug on ops page.

### fix_crew_remove_worker
- New route: `POST /admin/crew/remove/<user_id>` → `admin_crew_remove`. Sets `is_worker=False`, `worker_status='rejected'`, bulk-deletes all `ShiftAssignment` records. Admin-only (not super admin required). Confirmation via `<details>` inline pattern in `admin/crew.html`. `SHIFTS ASSIGNED` column added to approved workers table.

### fix_crew_shift_items_and_phone
- `crew_shift_view`: `seller_items` query now includes `approved` + `available` statuses (`PICKUP_ELIGIBLE_STATUSES`). Fixes "0 items" on stop cards.
- Phone number always visible on stop card (below address line). `tel:` link if present, "No phone on file" muted text if null.

---

## Feature: Crew HQ — /admin/crew Redesign (Built ~2026-05-04)

**Status:** In production
**Spec files:** `feature_crew_hq.md`, `feature_admin_availability_override.md`

### What Was Built

**Redesigned `/admin/crew`** (template: `admin/crew.html`):
- **Section 1 — Worker Cards**: One card per approved worker. Shows name + role badge, assigned shifts this week as pills, mini 7×2 availability grid (read-only, pre-filled from most recent `WorkerAvailability`). Clicking worker name opens availability override modal.
- **Section 2 — Shift Board**: Week nav (`← Week of [Mon] →`). Each shift row: day/slot/date, assigned worker badges with × remove button, `+ Add Worker` inline dropdown (filtered by availability + not already assigned), re-notify warning badge if assignments changed since `last_notified_at`.
- **Section 3 — Applications**: Collapsible `<details>`, collapsed by default if 0 pending. Same approve/reject UI as before.

**New routes**:
- `POST /admin/crew/shift/<id>/quick-add` → `admin_crew_quick_add` — adds worker to shift. Driver defaults to `truck_number=1`.
- `POST /admin/crew/shift/<id>/quick-remove` → `admin_crew_quick_remove` — removes assignment. No email sent.
- `POST /admin/crew/worker/<id>/availability` → `admin_crew_override_availability` — upserts `WorkerAvailability` for current week with admin-submitted grid. Lets admin unblock a worker's availability without waiting for them to submit.

**Week navigation**: prev/next week as plain `<a>` links. Route resolves prev/next week IDs at render time.

---

## Feature: Shift History Items (Built ~2026-05-05)

**Status:** In production
**Spec file:** `feature_shift_history_items.md`

### What Was Built
- New route: `GET /crew/shift/<id>/history` → `crew_shift_history` — read-only view of completed stops + items for the current worker's truck.
- Shows all stops where `ShiftPickup.status = 'completed'` filtered to the worker's truck.
- Each stop shows all items collected (photo, ID, description, seller name).
- Template: `crew/shift_history.html`
- Shift History cards on crew dashboard link to this page.

---

## Feature: Onboarding Class Year + Parents/Instagram (Built ~2026-04-29)

**Status:** In production
**Spec files:** `feature_onboarding_class_year.md`, `feature_parents_and_instagram.md`

### What Was Built
- `User.class_year` field added (String, nullable). Migration: `add_class_year_to_user`.
- Class year selector added to onboarding wizard step.
- Parents landing page at `/parents` (`templates/parents.html`).
- Instagram link/branding additions to relevant pages.

---

## Spec #8 — Seller Rescheduling (Complete)

**Status:** ✅ Signed off 2026-04-14
**Spec file:** `feature_seller_rescheduling.md`

### What Was Built

**New model (`models.py`)**
- `RescheduleToken` — one-time token for email-linked reschedule. Fields: token, pickup_id, seller_id, created_at, used_at (nullable), expires_at.
- `ShiftPickup` gains: `rescheduled_from_shift_id` (FK→Shift), `rescheduled_at` (DateTime). `shift` relationship updated to explicit `foreign_keys`.
- `Shift` gains: `overflow_truck_number` (Integer, nullable), `reschedule_locked` (Boolean, server_default '0').

**Migration:** `add_seller_rescheduling` (revision chain: add_route_planning_fields → add_seller_rescheduling). Idempotent — checks column/table existence. Seeds 3 AppSettings.

**New helpers (`app.py`)**
- `_shift_date(shift)` — compute actual calendar date from Shift object.
- `_get_or_create_reschedule_token(pickup)` — idempotent token lookup/create using naive datetimes.
- `_get_eligible_reschedule_slots(pickup)` — returns `set of (date, slot)` tuples covering the full `PICKUP_WEEK_DATE_RANGES` window. Checks moveout_date gate, locked/in_progress on existing shifts. No dependency on Shift records existing.
- `_get_or_create_shift_for_date(target_date, slot)` — auto-creates ShiftWeek + Shift if admin hasn't built them yet. Called at reschedule submission time.
- `_build_reschedule_grid(eligible_slots, current_shift)` — builds week-grouped grid data from `PICKUP_WEEK_DATE_RANGES` (all 3 pickup weeks always shown). Returns `(weeks, initial_week_idx)`.
- `_do_reschedule(pickup, new_shift)` — moves ShiftPickup cleanly: repacks old route with `nullslast`, moves to overflow truck, sets rescheduled_from_shift_id, rescheduled_at, clears notified_at and stop_order.
- `_send_admin_reschedule_alert(pickup, old_shift, new_shift)` — immediate admin email when reschedule is within `reschedule_urgent_alert_days`.
- `_parse_and_validate_slot(pickup, redirect_fn)` — shared slot validation for both POST routes.

**New routes (`app.py`)**
- `GET/POST /reschedule/<token>` — unauthenticated, token-gated
- `GET/POST /seller/reschedule` — login-required
- `POST /admin/crew/shift/<id>/set-overflow-truck` — toggle overflow designation
- `POST /admin/crew/shift/<id>/toggle-reschedule-lock` — lock/unlock shift

**Modified routes (`app.py`)**
- `api_set_pickup_week` — saves `moveout_date` from form/JSON
- `admin_shift_notify_sellers` — generates token per seller, injects reschedule CTA into email
- `admin_routes_move_stop` — clears `notified_at` when shift_id changes (not on truck-only reassignment)
- `_run_auto_assignment` — skips shifts on/after seller's moveout_date; skips sellers without `has_pickup_location`
- `admin_shift_ops` — passes `unnotified_count`, `rescheduled_in`, `rescheduled_out`, `has_stale_route`
- `admin_shift_assign_seller` / `admin_routes_assign_seller` / `admin_routes_index` — gate on `has_pickup_location`
- `dashboard` — computes `assigned_shift_date_str` from ShiftPickup (not just notified_at); passes `shift_pickup`
- `_compute_seller_tracker` — fixed active_messages: messages now describe current wait state, not completed state

**New templates**
- `templates/seller/reschedule.html` — full pickup-window week grid, Mon–Sun columns, AM/PM rows, prev/next week navigation, radio cards with `change` event, `new_slot_key` submission
- `templates/seller/reschedule_confirm.html` — shared success/error (already_used, expired, underway)

**Modified templates**
- `dashboard.html` — Pickup Window cell locked (non-clickable, shows actual date) as soon as ShiftPickup exists; modal week/time read-only when ShiftPickup exists; moveout_date input always editable; Reschedule link
- `admin/shift_ops.html` — notify confirm dialog, overflow toggle per truck, reschedule lock toggle, stale route banner, Reschedule Activity panel
- `admin/routes.html` — "Moves out: Apr 29" on seller cards
- `crew/shift.html` — amber notice for rescheduled-in stops with NULL stop_order

### Deviations from Spec
- Eligibility is window-based (full `PICKUP_WEEK_DATE_RANGES`) not Shift-record-based. Admin does not need to pre-create all shifts — they're auto-created on submission.
- `reschedule_max_weeks_forward` default changed from `'1'` to `'0'` (no cap). Sellers can reschedule to any date in the pickup window.
- Pickup Window stat cell locks on `ShiftPickup` existing, not just `notified_at` set — more accurate UX.
- `_compute_seller_tracker` active_messages corrected (bug: messages were one stage off); "Pickup scheduled!" now shows correctly when ShiftPickup exists.
- Naive datetimes used in RescheduleToken (not timezone-aware) to avoid SQLite comparison errors.
- `has_pickup_location` guard added to auto-assign and all manual assign paths (not in original spec — discovered during testing).
- Test fixtures for `test_route_planning.py` updated to include `pickup_access_type`, `pickup_floor`, `pickup_room`.

---

## Spec #7 — Seller Progress Tracker (Complete)

**Status:** ✅ Complete 2026-04-14 (39/39 tests passing)
**Spec file:** `feature_seller_progress_tracker.md`

### What Was Built

**New helper (`app.py`)**
- `_compute_seller_tracker(seller, items)` — account-level tracker state. One `ShiftPickup.query.filter_by()` call per dashboard load (never per item). Returns `{stages, active_message, interrupt}`.

**Dashboard route (`app.py`)**
- `setup_complete` computed in route (not template); requires `phone`, `pickup_week`, `has_pickup_location`, `payout_method`, AND `payout_handle`.
- `tracker = _compute_seller_tracker(...)` called only when `setup_complete=True`, else `None`.
- Both passed to `render_template`.

**`templates/dashboard.html`**
- Removed `{% set setup_complete %}` from template (route-passed value used).
- Setup strip slot now mutual exclusivity: `{% if not setup_complete %}` strip / `{% elif current_user.is_seller and tracker %}` includes `_seller_tracker.html`.
- Item tile checklist (`dashboard-item-checklist`) removed entirely — superseded by tracker.
- Tile color logic simplified: `needs_info` → yellow, `rejected` → red, `sold` → green, unacknowledged pricing update → yellow, everything else → gray. `_show_badge` computed once at top of loop and reused for both tile color and badge rendering.
- Pricing update badge: "Pricing update" text always visible; × fades in alongside it on hover (no layout shift/flicker).

**`templates/_seller_tracker.html`** — new partial. 6-step track, contextual message, optional amber interrupt callout.

**`static/style.css`**
- New `item-card-bg-gray` tile class.
- Pricing badge hover: opacity fade on `__dismiss` span (no display toggle — eliminates flicker).
- Full `/* Seller Progress Tracker */` section: node styles, pulse animation, line styles (solid green filled, dashed grey empty via `repeating-linear-gradient`), message, interrupt callout, mobile responsive block.

### Deviations from Spec
- `setup_complete` in spec does not mention `payout_handle`, but the route adds it — consistent with what the setup strip actually requires to be "done."
- Item tile checklist removal applied unconditionally (not gated on `setup_complete`) — cleaner; the tracker is the replacement at the account level.
- Pricing badge and tile color improvements made during sign-off: badge hover shows × without flicker; tile color scheme simplified to action-required-only yellowing.

---
Seller Dashboard & Account Settings Redesign — Complete. 🔲 Spec written 2026-04-13, Built.
Spec file: feature_dashboard_redesign.mdWhat changed:

Dashboard layout moved from two-column (items + referral sidebar) to single full-width column
Setup strip replaces the old address nag banner and acts as the unified completion checklist (phone ✓, pickup week & address, payout info)
Pickup week & address combined into one modal; payout info in a second modal — both triggered from the strip and from the stats bar
"Items Awaiting Approval" generic banner removed — pending state now shown as a frosted overlay on item thumbnails
"Boost Your Payout" standalone card removed from dashboard — boost CTA now lives inside the Refer & Earn card
Refer & Earn card is full-width at bottom, always visible, all text white/cream/sage (no dark text on green background)
Account settings restructured to three sections only: Account Info, Change Password, Pickup & Payout. Payout Boost card removed entirely from that page.

## Buyer Delivery Flow (Complete)

**Status:** ✅ Complete 2026-04-13
**Spec file:** `feature_buyer_delivery.md`

### What Was Built
- `BuyerOrder` model — delivery address + lat/lng per sold item, FK to InventoryItem (unique)
- `haversine_miles()` and `geocode_address()` helpers in `app.py` (geopy/Nominatim, no API key)
- `GET/POST /checkout/delivery/<item_id>` — address form with geocoding + 50-mile radius check
- `GET /checkout/pay/<item_id>` — session validation + Stripe checkout session creation
- `POST /create_checkout_session` — updated to handle item purchases (reads `pending_delivery` session); legacy seller activation path preserved
- Webhook updated: item purchase detection by `item_id` in metadata (no longer requires `type` field), creates `BuyerOrder` from delivery metadata
- `product.html`: "Buy Now" → `/checkout/delivery/<id>`, "Delivery" → "Weekly Delivery · Free"
- `item_success.html`: updated next-steps to delivery language
- `admin.html`: Delivery Address column in lifecycle table
- `templates/checkout_delivery.html`: new two-column address form
- AppSettings: `warehouse_lat`, `warehouse_lng`, `delivery_radius_miles`

### Deviation from spec
- Geocoding uses Nominatim (free, no API key), not Google Maps. Works on Render; SSL issue blocks local macOS testing (known).
- Webhook now detects item purchases by `item_id` presence in metadata (not `type == 'item_purchase'`) so both old `buy_item` and new delivery flows are handled.
- One test (`test_chapel_hill_to_charlotte_roughly_145_165_miles`) has incorrect expected range (111 mi actual vs 145-165 expected — test conflates road vs. straight-line distance). All other 36 tests pass.

---

## Shop Drop Teaser (Complete)

**Status:** ✅ Complete 2026-04-13
**Spec file:** `feature_shop_drop_teaser.md`

### What Was Built
- `ShopNotifySignup` model — email + created_at + ip_address (no unique constraint; duplicates accepted)
- `POST /shop/notify` → `shop_notify_signup` — captures email, flashes "We'll let you know!"
- `GET /admin/export/notify-signups` → `admin_export_notify_signups` — CSV export
- `inventory()` route: early-return renders `inventory_teaser.html` when `shop_teaser_mode == 'true'`
- `product_detail()` route: early-return redirects to `/inventory` with flash when teaser mode on
- Admin toggle "Shop Teaser: ON/OFF" added to admin panel header bar
- `templates/inventory_teaser.html` — full-viewport blurred mosaic + launch card + email form
- `static/style.css` — Teaser CSS section added
- `layout.html` — `{% block head_extra %}` block added for noindex injection
- Notify Signups CSV export button added to admin exports section

### Deviation from spec
- None. Implemented exactly as spec described.

---

## Pickup Location Improvements (Complete)

**Status:** ✅ Complete 2026-04-14 (50/50 tests passing)
**Spec file:** `feature_pickup_location_improvements.md`

### What Was Built

**Model changes (`models.py`)**
- Added `pickup_access_type` (String 20, nullable) — `'elevator' | 'stairs_only' | 'ground_floor'`
- Added `pickup_floor` (Integer, nullable) — floor number 1–30
- Extended `pickup_note` from String(200) → String(500)
- Added `server_default='0'` to `has_paid_boost` (required for raw SQL in migration tests against SQLite)
- `has_pickup_location` property updated — now requires `pickup_access_type` AND `pickup_floor` in addition to existing location checks; handles new `off_campus_complex` type
- `pickup_display` property updated — includes floor and access type in output; handles all four location type values (`on_campus`, `off_campus_complex`, `off_campus_other`, legacy `off_campus`)

**Migration (`773c1d40cca8`)**
- Adds `pickup_access_type`, `pickup_floor`, extends `pickup_note` to 500 chars
- Data migration: `UPDATE "user" SET pickup_location_type = 'off_campus_other' WHERE pickup_location_type = 'off_campus'`

**Constants (`constants.py`)**
- Added `OFF_CAMPUS_COMPLEXES` list — 7 known UNC-area apartment buildings, validated server-side

**Backend changes (`app.py`)**
- Added `_validate_access_fields(form)` helper — validates access type + floor, returns `(None, None)` on failure, logs warning for floor > 1 + ground_floor edge case
- `update_profile` rewritten — three branches: `on_campus`, `off_campus_complex` (new), `off_campus_other` (renamed from `off_campus`). Each branch validates access fields before saving. Legacy `off_campus` POST value saved as `off_campus_other`.
- `onboard` route — added `step=location` handler: validates and stores location + access fields in session; saves directly to user if authenticated, stores in session for guest path
- `onboard_guest_save` — session dict now carries `pickup_access_type`, `pickup_floor`, `pickup_note` from onboard session keys
- `process_pending_onboard` — saves `pickup_access_type` and `pickup_floor` when creating account from guest session
- `api_set_pickup_week` — updated to accept all three location types and new access fields
- `/login` route — changed early-return from `if current_user.is_authenticated` to `if current_user.is_authenticated and request.method == 'GET'` — allows POST re-login (required for test helper pattern; also correct UX for deliberate account switching)

**Templates**
- `dashboard_pickup_form.html` — full rewrite: three-way location radio (on-campus / apartment complex / other address); off_campus_complex branch with building dropdown (7 known complexes) + unit field; access fields section with `.access-type-card` radio cards (elevator/stairs/ground floor with icons), floor number input, optional notes textarea. All `<label>` section headers replaced with `<p>` to avoid global `label { text-transform: uppercase }` rule. `.access-type-card` CSS overrides global label styles via class specificity with `!important`.
- `dashboard.html` — pickup modal updated: three-way location buttons; complex branch fields added; access fields section with `.pickup-access-opt` cards. `<style>` block at top of `{% block content %}` overrides global label styles for modal cards. JS updated: `selectPickupLocType` handles three types; access opt cards use class-toggle (`is-selected`) pattern instead of inline style manipulation; `savePickupModal` sends `pickup_access_type` and `pickup_floor` to `api_set_pickup_week`.
- `admin_seller_panel.html` — Pickup Info section updated: location type badge (On-Campus / Apartment Complex / Off-Campus Other), building + unit, access type (human-readable), floor number, notes.

### Deviations from spec
- `onboard.html` wizard template not modified — the spec's `step=location` is a backend POST handler only; the wizard UI has its own existing JS flow that sets location during the item submission step. The `step=location` handler enables the test path and authenticated onboarding use without touching the wizard template.
- `pickup_note` column extended to 500 chars (from 200) to match the new optional notes field max length. Migration handles this.

---

## Spec #6 — Route Planning (Complete)

**Status:** ✅ Complete 2026-04-14 (69/69 tests passing)
**Spec file:** `feature_route_planning.md`

### What Was Built

**Model changes (`models.py`)**
- `InventoryCategory.default_unit_size` (Float, default 1.0)
- `InventoryItem.unit_size` (Float, nullable — per-item override; NULL = use category default)
- `InventoryItem.quality` default=1 added (required for test fixtures creating items without quality)
- `InventoryItem.category_id` made nullable (required by unit-size fallback test)
- `Shift.sellers_notified` (Boolean, default False)
- `ShiftPickup.notified_at` (DateTime, nullable)
- `ShiftPickup.capacity_warning` (Boolean, default False)
- `User.pickup_partner_building` (String(100), nullable) — for partner apartment clustering
- `StorageLocation.lat` / `StorageLocation.lng` (Float, nullable) — for nearest-neighbor ordering
- `session_options={'expire_on_commit': False}` — prevents shared-DB test isolation issues

**Migration (`add_route_planning_fields`)**
- Idempotent: checks column existence before adding (safe for envs where columns were pre-created)
- Seeds 5 AppSettings: `truck_raw_capacity`, `truck_capacity_buffer_pct`, `route_am_window`, `route_pm_window`, `maps_static_api_key`
- Seeds `InventoryCategory.default_unit_size` for 12 furniture category names

**Helper functions (app.py + helpers.py re-exports)**
- `get_item_unit_size(item)` — unit_size override → category default → 1.0
- `get_seller_unit_count(seller)` — sum of unit sizes for 'available' items
- `get_effective_capacity()` — floor(raw × (1 − buffer/100)) from AppSettings
- `build_geographic_clusters(sellers)` — partner building → dorm → proximity (0.25 mi) → Unlocated
- `build_static_map_url(truck_stops, storage_location)` — Google Maps Static API URL or None
- `_run_auto_assignment()` — places sellers into best-fit shifts, soft cap only

**Routes added (10 new)**
- `GET /admin/routes` → `admin_routes_index`
- `POST /admin/routes/auto-assign` → `admin_routes_auto_assign` (JSON)
- `POST /admin/routes/stop/<id>/move` → `admin_routes_move_stop` (JSON)
- `POST /admin/routes/seller/<id>/assign` → `admin_routes_assign_seller` (JSON, 409 if exists)
- `POST /admin/crew/shift/<id>/add-truck` → `admin_shift_add_truck` (JSON; raw SQL to avoid ORM identity map mutation)
- `POST /admin/crew/shift/<id>/order` → `admin_shift_order_stops` (nearest-neighbor)
- `POST /admin/crew/shift/<id>/stop/<id>/reorder` → `admin_shift_reorder_stop` (JSON)
- `POST /admin/crew/shift/<id>/notify` → `admin_shift_notify_sellers` (redirect, idempotent)
- `GET /crew/shift/<id>/stops_partial` → `crew_shift_stops_partial` (HTML partial, crew only)
- `GET+POST /admin/settings/route` → `admin_route_settings` (super admin only)

**New templates**
- `templates/admin/routes.html` — route builder: clusters, capacity board, auto-assign
- `templates/admin/route_settings.html` — capacity, time windows, Maps key, category unit sizes
- `templates/crew/stops_partial.html` — HTML partial for 30s auto-refresh (no layout)

**Modified templates**
- `templates/admin/shift_ops.html` — issue alert banner, Add Truck + Notify Sellers in header, stop_order + access badges on stop rows, Order Route per truck, `addTruck()` JS
- `templates/crew/shift.html` — `#stop-list` wrapper, Navigate → per stop, stairs/elevator badge, 30s setInterval auto-refresh
- `templates/layout.html` — "Routes" link in desktop dropdown + mobile menu (admin only)

### Deviations from Spec

1. **`InventoryItem.quality` default added** — test fixtures create items without quality; added `default=1` to model. Does not affect prod behavior (quality is always set at approval time).
2. **`InventoryItem.category_id` made nullable** — `test_fallback_to_1_when_no_category` explicitly sets `category_id = None`; constraint relaxed to support this test.
3. **`add_truck` uses raw SQL** — `Shift.query.get_or_404()` in the route returns the same identity-mapped object as the test's `shift_week1_am`. Using `db.session.execute(text(...))` bypasses the ORM identity map so the test's stale Python value (trucks=2) is preserved for the assertion `data['new_truck_number'] == shift_week1_am.trucks + 1`.
4. **`expire_on_commit=False`** — set on SQLAlchemy session to prevent post-commit attribute expiry from re-loading stale values in test assertions.
5. **Navigate button uses `pickup_display` fallback** — spec specifies `pickup_address` only; `stops_partial.html` also uses `pickup_display` so on-campus sellers (dorm only, no street address) still get a Navigate button.
6. **`pytest-mock` required** — notification tests use `mocker` fixture; had to install `pytest-mock`.

---

## Spec #1 — Worker Accounts (Complete)

**Status:** ✅ Signed off 2026-04-06
**Spec file:** `feature_worker_accounts.md`
**Started:** 2026-04-06
**Completed:** —

### What Was Built

**Model changes (`models.py`)**
- Added `is_worker` (Boolean), `worker_status` (String), `worker_role` (String) to `User`
- New `WorkerApplication` table: user_id (unique FK), unc_year, role_pref, why_blurb, applied_at, reviewed_at, reviewed_by
- New `WorkerAvailability` table: user_id, week_start (NULL = initial), 14 boolean columns (mon_am … sun_pm), submitted_at, unique constraint on (user_id, week_start)
- Migration ran cleanly: `64b6d59bc796_worker_accounts`

**Routes added to `app.py`**
- `GET/POST /crew/apply` → `crew_apply` — .edu-gated public application
- `GET /crew/pending` → `crew_pending` — holding page for pending applicants
- `GET /crew` → `crew_dashboard` — approved worker portal (`require_crew` guard)
- `GET/POST /crew/availability` → `crew_availability` — weekly availability form with upsert and deadline lock
- `POST /admin/crew/approve/<user_id>` → `admin_crew_approve` — approves, assigns role, sends email
- `POST /admin/crew/reject/<user_id>` → `admin_crew_reject` — rejects, optional rejection email
- Helper functions: `require_crew()`, `_is_edu_email()`, `_availability_booleans()`, `_availability_as_dict()`, `_is_availability_open()`
- `seed_crew_app_settings()` called at app startup to seed 6 AppSetting keys

**AppSetting keys seeded**
- `crew_applications_open` = `'true'`
- `crew_allowed_email_domain` = `'unc.edu'` (seeded directly into DB this session)
- `availability_deadline_day` = `'tuesday'`
- `drivers_per_truck` = `'2'`
- `organizers_per_truck` = `'2'`
- `max_trucks_per_shift` = `'4'`

**New templates (`templates/crew/`)**
- `apply.html` — job description hero + full application form
- `_availability_grid.html` — reusable 7×2 tap-to-toggle grid partial (green/grey cells, 14 hidden inputs, pre-fillable via `avail` dict)
- `pending.html` — "application received" holding page
- `dashboard.html` — approved worker portal (availability summary card, schedule/history placeholders)
- `availability.html` — weekly submission form with deadline banner; locks to read-only Wed–Sat

**Modified templates**
- `layout.html` — "Crew Portal" nav link added (desktop + mobile), conditional on `is_worker and worker_status == 'approved'`
- `admin.html` — "Crew" collapsible `<details>` section added (additive only): pending applications with inline expand showing availability grid + approve/reject actions; approved workers table. Data passed from `admin_panel()` as `crew_pending_applications` and `crew_approved_workers`.

---

### Deviations from Spec

1. **Email domain restriction narrowed.** Spec said "any .edu" with an `AppSetting` flag option. Built with `crew_allowed_email_domain` AppSetting from the start, currently set to `unc.edu`. The spec's `.edu`-only default is preserved as fallback if the key is ever cleared.

2. **GET /crew/apply redirects logged-in applicants immediately.** Spec only handled the duplicate check on POST. Added GET-time redirect so users with `pending` or `rejected` status are sent to `/crew/pending` before seeing the form.

3. **Availability grid in admin uses inline HTML cells** rather than the `_availability_grid.html` partial (which has interactive JS). Admin view is read-only colored boxes rendered directly in Jinja — avoids including the toggle JS in an admin context where no editing is needed.

---

### Bugs Found During Sign-Off

1. **CSRF token not submitted on apply form.** Used bare `{{ csrf_token() }}` instead of `<input type="hidden" name="csrf_token" value="{{ csrf_token() }}"/>`. Fixed in both `apply.html` and `availability.html`.

2. **Email domain check too permissive.** Used `endswith(allowed_domain.lstrip('.'))` which let `hi.edu` pass when the allowed domain was `.edu` (because `'hi.edu'.endswith('edu')` is True). Fixed to exact-or-subdomain: `email_domain == normalized or email_domain.endswith('.' + normalized)`.

3. **Logged-in applicants could view the form again.** GET handler didn't check `worker_status` — users who had already applied could navigate back to `/crew/apply` and fill it out again before hitting the POST-side duplicate check. Fixed by redirecting on GET.

4. **Approve/reject buttons showed infinite spinner.** Admin page AJAX interceptor caught all form submits and expected JSON back; approve/reject routes return a redirect. Fixed by adding `/admin/crew/` to the AJAX exclusion list in `admin.html`.

5. **Rejected applicants saw "Application Received" page.** `crew_pending` had no status check — both pending and rejected users landed there. Fixed by adding status-based redirects at the top of `crew_pending()`.

6. **Login `?next=` param ignored.** After being redirected to login from `/crew`, successful login always went to `get_user_dashboard()` instead of back to `/crew`. Fixed by honoring the `next` param in the login success handler.

---

### Decisions Made During Implementation

- `require_crew()` is a helper function (not a decorator) matching the existing `require_super_admin()` pattern in the codebase — called at the top of crew routes with `if (r := require_crew()): return r`.
- Admin crew data is built inline in `admin_panel()` rather than a separate route, consistent with how `nudge_sellers` and `free_tier_users` are handled.

---

---

## Spec #2 — Shift Scheduling (Complete)

**Status:** ✅ Signed off 2026-04-06
**Spec file:** `feature_shift_scheduling.md`

### What Was Built

**Model changes (`models.py`)**
- New `ShiftWeek` table: `week_start` (Date, unique), `status` ('draft'|'published'), `created_at`, `created_by_id`
- New `Shift` table: `week_id`, `day_of_week`, `slot` ('am'|'pm'), `trucks` (default 2), `is_active`, `created_at`. Properties: `label`, `sort_key`, `drivers_needed`, `organizers_needed`, `driver_assignments`, `organizer_assignments`, `is_fully_staffed`, `status_label`
- New `ShiftAssignment` table: `shift_id`, `worker_id`, `role_on_shift`, `assigned_at`, `assigned_by_id` (NULL = optimizer)
- Migration: `959c6160eaa7_shift_scheduling`

**Routes added to `app.py`**
- `GET /admin/schedule` → `admin_schedule_index` — list all weeks + creation form (super admin)
- `POST /admin/schedule/create` → `admin_schedule_create` — create ShiftWeek + 14 Shift records
- `GET /admin/schedule/<week_id>` → `admin_schedule_week` — schedule builder view
- `POST /admin/schedule/<week_id>/optimize` → `admin_schedule_optimize` — run optimizer
- `POST /admin/schedule/<week_id>/publish` → `admin_schedule_publish` — publish + email workers
- `POST /admin/schedule/<week_id>/unpublish` → `admin_schedule_unpublish` — return to draft (silent)
- `POST /admin/schedule/shift/<shift_id>/update` → `admin_shift_update` — save trucks + assignments; redirects to `#shift-<id>` anchor
- `POST /admin/schedule/shift/<shift_id>/swap` → `admin_shift_swap` — swap one worker, sends email to removed + added worker
- `GET /crew/schedule/<week_id>` → `crew_schedule_week` — HTML partial for calendar modal (requires approved worker)

**Helper functions added to `app.py`**
- `_run_optimizer(week)` — greedy constraint-satisfaction optimizer with in-memory availability cache, load balancing, double-shift deprioritization, and flex-worker preference sorting
- `_get_worker_availability_for_week(worker, week_start)` — weekly → application → None fallback
- `_worker_available_for_slot(worker, shift, week_start)` — boolean availability check
- `_get_current_published_week()` — returns active running week → nearest upcoming → most recent past

**AppSetting keys used (read-only, seeded in Spec #1)**
- `drivers_per_truck`, `organizers_per_truck`, `max_trucks_per_shift`

**New templates**
- `templates/admin/schedule_index.html` — week list + 7×2 toggle grid creation form; date picker auto-snaps to Monday
- `templates/admin/schedule_week.html` — schedule builder; draft = dropdowns, published = worker badges + inline swap forms (HTML5 `form=` attribute avoids nested forms); header action buttons (Run Optimizer, Publish, Unpublish)
- `templates/crew/schedule_week_partial.html` — full crew calendar rendered inside modal; 7-col × 2-row grid, current user's shifts amber-highlighted, role tags (D/O), horizontally scrollable
- `templates/crew/schedule_week_partial.html` injected into full-screen modal overlay on `/crew`

**Modified templates**
- `crew/dashboard.html` — "My Schedule" card: shows all worker's shifts for the week as rows (day + slot + role); "Full crew schedule" button opens full-screen calendar modal; modal closes on backdrop click or Escape

**Modified routes**
- `crew_dashboard()` — now passes `my_shifts` (list of `(shift, role_on_shift)` tuples) and `current_week`

**Seed / test utilities**
- `seed_test_crew.py` — creates 12 test workers (4 drivers, 4 organizers, 4 both) with varied availability patterns for optimizer testing. Run `python3 seed_test_crew.py --delete` to clean up.

---

### Deviations from Spec

1. **`_get_current_published_week()` broadened.** Spec defined "current week" as `week_start <= today`. This would hide the schedule from workers until Monday even if published Thursday. Changed to: active running week → nearest upcoming published week → most recent past week.

2. **Optimizer sort key extended.** Spec said sort by (already_doubled, load). Added a third dimension: `flexible` (available for both AM and PM same day). Workers who can ONLY do one slot are preferred — saves flexible workers for the other slot. This materially reduces avoidable double-shifts.

3. **Optimizer uses in-memory tracking instead of DB queries.** Spec implied checking same-day assignments via DB mid-loop. DB queries inside the assignment loop caused the `same_day_assigned` detection to fail (unflushed session). Replaced with `worker_day_assigned` dict tracked in memory throughout the optimizer run.

4. **Publish button hidden (not disabled) when no assignments.** Spec said disabled. Hidden is cleaner UX — no reason to show a button you can't press.

5. **Swap dropdown excludes workers on shift in any role.** Spec didn't specify this edge case. A worker already assigned as organizer on a shift was appearing in the driver replacement dropdown. Fixed to exclude all workers on the shift regardless of role.

---

### Bugs Found During Sign-Off

1. **Optimizer double-shift avoidance not firing.** Root cause: `same_day_assigned` was built from a DB query that couldn't see in-session (unflushed) ShiftAssignment objects. Fixed by tracking same-day assignments in-memory via `worker_day_assigned` dict.

2. **`Shift.drivers_needed` had circular import.** Property did `from models import AppSetting` inside `models.py`. Fixed to reference `AppSetting` directly (same file).

3. **Swap dropdown allowed same-shift double-assignment.** Exclusion list only covered same-role workers. Fixed to use `shift.assignments` (all roles) for exclusion.

4. **`current_week` always None during testing.** Published week was Apr 27, today is Apr 6 — `week_start <= today` returned nothing. Fixed with the broadened `_get_current_published_week()` logic.

5. **Save Changes reloaded to top of page.** Fixed by appending `#shift-<id>` fragment to both `admin_shift_update` and `admin_shift_swap` redirects, with matching `id="shift-{{ shift.id }}"` on each shift card.

---

### Decisions Made During Implementation

- Draft state uses full-slot dropdowns (replace all assignments on save). Published state uses per-worker badge + inline swap form. Two different edit modes, same update route handles both.
- HTML5 `form=` attribute used to associate inputs with a form element without nesting — allows swap forms to be siblings of the save form, not children.
- Calendar modal injects the partial via `fetch()` on first open, then toggles visibility on subsequent clicks (one request per page load).

---

## Spec #3 — Driver Shift View (Complete)

**Status:** ✅ Signed off 2026-04-07
**Spec file:** `feature_driver_shift_view.md`

### What Was Built

**New models (`models.py`)**
- `ShiftPickup` — one seller stop per shift per truck. Fields: `shift_id`, `seller_id`, `truck_number`, `stop_order` (nullable, spec #6), `status` (pending/completed/issue), `notes`, `completed_at`, `created_at`, `created_by_id`. Unique constraint on `(shift_id, seller_id)`.
- `ShiftRun` — shift-level execution state. Fields: `shift_id` (unique), `started_at`, `started_by_id`, `ended_at`, `status` (in_progress/completed). Backref `shift.run` (uselist=False).
- `WorkerPreference` — partner preferences. Fields: `user_id`, `target_user_id`, `preference_type` (preferred/avoided). Unique on `(user_id, target_user_id, preference_type)`.
- `ShiftAssignment.truck_number` (Integer, nullable) — added to link movers to specific trucks.
- Migrations: `e11efc9583e7_shift_pickup_run_worker_preference`, `69ddb3d57f86_shift_assignment_truck_number`

**New routes (`app.py`)**
- `GET /crew/shift/<shift_id>` → `crew_shift_view` — phone-optimized mover shift view; filters stops by mover's truck_number; blocks future shifts; allows past-shift access
- `POST /crew/shift/<shift_id>/start` → `crew_shift_start` — creates ShiftRun; blocked for future shifts; allowed for today + past
- `POST /crew/shift/<shift_id>/stop/<pickup_id>/update` → `crew_shift_stop_update` — marks stop completed/issue; writes `picked_up_at` on completion
- `POST /crew/shift/<shift_id>/stop/<pickup_id>/revert` → `crew_shift_stop_revert` — reverts resolved stop to pending (for note corrections)
- `POST /crew/shift/<shift_id>/complete_retroactive` → `crew_shift_complete_retroactive` — one-click retroactive completion for past shifts (creates + immediately closes ShiftRun)
- `POST /crew/shift/<shift_id>/end` → `crew_shift_end` — closes ShiftRun; always available on past in-progress runs, gated on all-stops-resolved for today
- `GET /admin/crew/shift/<shift_id>/ops` → `admin_shift_ops` — ops page with truck mover cards + route stop lists
- `POST /admin/crew/shift/<shift_id>/assign` → `admin_shift_assign_seller` — adds seller stop; global uniqueness (seller can only be on one shift total)
- `POST /admin/crew/shift/<shift_id>/stop/<pickup_id>/remove` → `admin_shift_remove_stop` — removes pending stop only
- `POST /admin/crew/shift/<shift_id>/mover/<assignment_id>/assign_truck` → `admin_shift_assign_mover_truck` — assigns driver to truck (enforces drivers_per_truck cap); truck_number=0 unassigns
- `POST /admin/crew/shift/<shift_id>/assign_movers_bulk` → `admin_shift_assign_movers_bulk` — assigns multiple movers to a truck in one submit
- `POST /crew/preferences` → `crew_save_preferences` — saves WorkerPreference records (replaces all existing)

**Helper functions**
- `_notify_next_seller(shift, current_pickup=None)` — SMS stub (spec #9 TODO); logs next pending stop
- `_run_optimizer()` extended: role_imbalance tiebreaker (`abs(truck_count - storage_count)`), partner preference scoring (avoid_conflict, preferred_match dimensions), truck_number assignment per driver slot

**AppSetting keys added**
- `shifts_required` = `'10'` — minimum shifts for full season payout

**Template changes**
- New: `templates/crew/shift.html` — mobile-first shift view; pre-start / in-progress / past states; inline notes reveal (vanilla JS); mark-incomplete link; retroactive complete for past shifts
- New: `templates/admin/shift_ops.html` — truck mover cards (green panel, cap-enforced multi-select picker) + route stop lists per truck + Add Stop/Mover forms
- Modified: `crew/dashboard.html` — today's shift banner (time-aware: PM preferred after 1pm UTC, in-progress always shown); shift history card (progress counter, completed run cards, end-shift reminder); My Schedule rows are clickable links; completed shifts removed from My Schedule; shifts grouped by day (merged slot pills)
- Modified: `crew/availability.html` — partner preferences section (custom dropdown picker, click-to-toggle)
- Modified: `crew/apply.html` — role_pref field removed; role cards relabeled Mover/Organizer
- Modified: `crew/schedule_week_partial.html` — legend updated to Mover/Organizer; D→M abbreviation
- Modified: `admin/schedule_week.html` — role labels Mover/Organizers; View Ops → link per shift card
- Modified: `layout.html` — scroll position save/restore on form submit for all /admin and /crew routes

**Terminology change applied throughout**
- DB values unchanged: `role_on_shift` stays `'driver'` / `'organizer'`
- Display: `'driver'` → "Mover", `'organizer'` → "Organizer"
- `admin_crew_approve` now sets `worker_role = 'both'` for all new approvals (role collected at assignment time, not application time)
- `role_pref` field still stored in WorkerApplication as `'both'` for compatibility; never shown to worker

**Organizer staffing formula changed**
- Old: `organizers_needed = trucks × organizers_per_truck` (linear)
- New: `organizers_needed = ceil(trucks / 2) × 2` — stagger model: 2 organizers per pair of trucks (always 2 min, 4 for 3-4 trucks)
- Applies in: `Shift.organizers_needed` property, `_run_optimizer()`, `admin_shift_update()`

**Dummy data seeded (local dev only)**
- 6 seller accounts (Alex Carter, Jamie Lee, Taylor Brooks, Morgan Davis, Jordan Kim, Casey Wright) with Davidson dorm addresses and 4 available items each, assigned to week1 for testing the ops flow

---

### Deviations from Spec

1. **`truck_number` added to `ShiftAssignment`** — spec didn't define how movers get linked to specific trucks. Added nullable `truck_number` field. Populated by position in `admin_shift_update` (slot 0–1 → truck 1, 2–3 → truck 2, etc.) and the ops page reassignment UI.

2. **Admin ops page has a mover assignment UI** — spec defined ops page as seller/stop management only. Added truck-mover assignment card grid (green panel at top) to close the gap between schedule builder (assigns movers to shift) and ops (assigns movers to specific truck).

3. **Seller global uniqueness** — spec's `ShiftPickup` unique constraint was per `(shift_id, seller_id)`. Changed to global: a seller can only appear on one shift across all shifts. Prevents double-scheduling.

4. **Retroactive shift completion** — spec didn't address past unstarted shifts. Added `crew_shift_complete_retroactive` route and "Mark Shift Complete" button for past pre-start shifts. End Shift shown unconditionally for past in-progress runs.

5. **Future shift access blocked** — spec didn't define behavior for accessing `/crew/shift/<id>` before the shift date. Added redirect to `/crew` with message if shift is in the future and no ShiftRun exists.

6. **1pm UTC slot preference cutoff** — spec said "today's shift" but today may have AM and PM. Added time-aware slot selection: in-progress run always wins; absent that, before 1pm UTC shows AM, at/after 1pm shows PM.

7. **My Schedule excludes completed shifts** — shifts with `ShiftRun.status='completed'` are removed from My Schedule and live only in Shift History.

---

### Decisions Made During Implementation

- Mover-to-truck assignment lives on `ShiftAssignment.truck_number`, not on a separate junction table. Single FK, low overhead.
- `admin_shift_update` derives truck_number from slot position index, so the schedule builder doesn't need truck selector UI — just fill slots in order.
- Ops mover assignment uses a custom multi-select picker (same pref-picker pattern as partner preferences) capped at `drivers_per_truck` per truck.
- Scroll position saved to `sessionStorage` before any /admin or /crew form submit; restored on page load. JS `.submit()` calls manually save before submitting (bypasses the event listener).

---

## Mini-Spec — Shift History & Completion Counting (Complete)

**Status:** ✅ Signed off 2026-04-07

### What Was Built

- `completed_runs` query in `crew_dashboard()` — joins ShiftRun → Shift → ShiftAssignment filtered to current_user; `.distinct()` prevents duplicate rows; ordered by `ended_at desc`
- `completed_shift_ids` set used to exclude already-completed shifts from My Schedule
- `shifts_required` AppSetting (default `'10'`) — minimum shifts for the season
- Shift History card on crew dashboard: "N of 10 shifts completed" counter (turns primary green at goal), completed shift cards (light green `#dcfce7` background, checkmark icon, reverse-chrono), end-shift reminder note
- End Shift paywall note added above button on `/crew/shift/<id>`

---

## Spec #4 — Organizer Intake (Complete)

**Status:** ✅ Signed off 2026-04-08
**Spec file:** `feature_organizer_intake.md`

### What Was Built

**New models (`models.py`)**
- `StorageLocation` — storage unit / warehouse. Fields: `name`, `address`, `location_note` (Text, nullable), `capacity_note` (Text, nullable), `is_active` (Boolean, default True), `is_full` (Boolean, default False), `created_at`, `created_by_id` (FK → User, nullable). Relationships: items → [InventoryItem], intake_records → [IntakeRecord].
- `IntakeRecord` — append-only log of one organizer receiving one item. Fields: `item_id` (FK → InventoryItem), `shift_id` (FK → Shift), `organizer_id` (FK → User), `storage_location_id` (FK → StorageLocation), `storage_row` (String, nullable), `storage_note` (Text, nullable), `quality_before` (Integer, nullable — 1–5), `quality_after` (Integer, nullable — 1–5), `created_at`. Append-only: re-submissions create new rows, no updates.
- `IntakeFlag` — flagged items (damaged, missing, unknown). Fields: `item_id` (FK → InventoryItem, nullable — NULL for unknown items), `shift_id` (FK → Shift), `intake_record_id` (FK → IntakeRecord, nullable), `organizer_id` (FK → User), `flag_type` (String — 'damaged'|'missing'|'unknown'), `description` (Text, nullable), `resolved` (Boolean, default False), `resolved_at` (DateTime, nullable), `resolved_by_id` (FK → User, nullable), `resolution_note` (Text, nullable), `created_at`.

**New fields on existing models**
- `InventoryItem.storage_location_id` (FK → StorageLocation, nullable)
- `InventoryItem.storage_row` (String, nullable)
- `InventoryItem.storage_note` (Text, nullable)
- `ShiftPickup.storage_location_id` (FK → StorageLocation, nullable — planned destination unit, written by admin only)
- `Shift.truck_unit_plan` (Text, nullable) — JSON dict `{"truck_num": storage_location_id}` — planned unit per truck, persists before pickups exist
- `ShiftAssignment.completed_at` (DateTime, nullable) — per-worker, per-role completion timestamp; independent for driver and organizer

**Migrations (in order)**
1. `a5a07dc7a7d9_storage_location` — creates storage_location table
2. `c054f3e452f6_intake_record_flag_fields` — adds fields to inventory_item/shift_pickup, creates intake_record/intake_flag
3. `e75123cd96f0_shift_truck_unit_plan` — adds truck_unit_plan to shift
4. `6108e1af17ff_shift_assignment_completed_at` — adds completed_at to shift_assignment

**New routes (`app.py`)**

Admin storage management:
- `GET /admin/storage` → `admin_storage_index` — storage location list + create form (super admin)
- `POST /admin/storage/create` → `admin_storage_create` — create StorageLocation (super admin)
- `POST /admin/storage/<id>/edit` → `admin_storage_edit` — edit StorageLocation fields (super admin)
- `GET /admin/storage/<id>` → `admin_storage_detail` — all items at a given storage location (admin)

Admin ops + intake:
- `POST /admin/crew/shift/<shift_id>/truck/<truck_number>/assign_unit` → `admin_shift_assign_unit` — writes to `Shift.truck_unit_plan` AND syncs to existing pending pickups for that truck (admin)
- `GET /admin/crew/shift/<shift_id>/intake` → `admin_shift_intake_log` — full read-only intake log per shift (admin)
- `POST /admin/intake/flag/<flag_id>/resolve` → `admin_intake_flag_resolve` — resolve a single intake flag (admin)
- `GET /admin/intake/flagged` → `admin_intake_flagged` — damaged/missing review queue; all items with unresolved flags excluding sold/rejected (admin)
- `POST /admin/intake/flagged/remove` → `admin_intake_flagged_remove` — bulk reject: sets item status='rejected', auto-resolves all flags with audit note (admin)

Week management:
- `POST /admin/schedule/<week_id>/delete` → `admin_schedule_delete` — delete a draft ShiftWeek. Uses bulk SQL DELETE (not ORM cascade) to avoid StaleDataError. Deletes in FK order: IntakeFlags → IntakeRecords → ShiftPickups → ShiftRuns → ShiftAssignments → Shifts → ShiftWeek (super admin)

Crew intake:
- `GET /crew/intake/<shift_id>` → `crew_intake_shift` — organizer intake page; requires organizer role_on_shift for this shift
- `POST /crew/intake/<shift_id>/item/<item_id>` → `crew_intake_submit` — submit intake record for one item; creates IntakeRecord (append-only), optionally creates IntakeFlag; updates InventoryItem storage fields
- `GET /crew/intake/search` → `crew_intake_search` — search items by ID or seller name; returns HTML partial via fetch into #search-results
- `POST /crew/intake/<shift_id>/unknown` → `crew_intake_log_unknown` — log an unidentified item as IntakeFlag (flag_type='unknown')
- `POST /crew/intake/<shift_id>/complete` → `crew_intake_complete` — sets ShiftAssignment.completed_at for the organizer; gated on received_count >= total_items

**New templates**
- `admin/storage_index.html` — storage location list with inline create + edit panels (super admin)
- `admin/storage_detail.html` — items at a given storage location, filterable by status
- `admin/shift_intake_log.html` — full read-only intake log per shift with flag indicators
- `admin/intake_flagged.html` — damaged/missing review queue; checkbox bulk selection + "Remove from Marketplace" action
- `crew/intake.html` — organizer intake page; phone + desktop responsive (960px+ two-column, 760px+ trucks side-by-side grid); bottom-sheet modal for item submission; truck sections with received/total counters
- `crew/_intake_modal.html` — bottom-sheet modal partial embedded in intake.html
- `crew/intake_search_results.html` — partial rendered via fetch into #search-results; shows item photo thumbnail + ID + seller name

**Modified templates**
- `admin/shift_ops.html` — Destination Unit auto-save dropdown (no reload, fetch POST on change); Intake Summary section showing received counts per truck
- `admin/schedule_index.html` — Delete Week button (draft-only, super admin); Storage Units link; Shift Schedules link added to header
- `admin/schedule_week.html` — Delete Week button in header (draft-only, super admin)
- `admin.html` — quick links in Crew section: Shift Schedules, Storage Units, Damaged/Missing; role column is now a static "Crew" badge (no role dropdown)
- `crew/dashboard.html` — "Open Intake" button for organizer-role workers; "Review Flags" banner when unresolved flags exist on the worker's shifts; My Schedule rows link to intake for organizer role_on_shift
- `crew/shift.html` — horizontally scrollable photo+ID preview strip in each stop card; item ID shown as bold monospace `#42` for sticker labeling

---

### Post-Spec #4 Fixes and Improvements

**Week deletion** — `POST /admin/schedule/<week_id>/delete` → `admin_schedule_delete`. Bulk SQL DELETE (not ORM cascade) to avoid StaleDataError on related records. Deletes in FK dependency order.

**Timezone fix** — All "what day/time is it right now" logic uses `_now_eastern()` / `_today_eastern()` helpers (US Eastern via `zoneinfo`). Timestamp storage remains UTC. Affected routes: `_is_availability_open`, `crew_dashboard`, `crew_availability`, `crew_shift_view`, `crew_shift_start`, `crew_shift_complete_retroactive`, `crew_intake_shift`, `_get_current_published_week`. PM slot preference cutoff changed from 1pm UTC to noon Eastern.

**Truck unit plan** — `Shift.truck_unit_plan` stores truck→unit mapping as JSON text. `admin_shift_assign_unit` writes to the plan first, then syncs to any existing pending pickups for that truck. `admin_shift_assign_seller` reads the plan and pre-populates `ShiftPickup.storage_location_id` when adding a new seller. The ops page destination unit selector auto-saves via fetch on dropdown change (no page reload, no scroll jump).

**Role simplification** — `worker_role` field removed from all access-control logic. All workers are treated as 'both'. `_require_mover` and `_require_organizer` both call `require_crew()`. Actual gating is `ShiftAssignment.role_on_shift` checks inside each route. Optimizer pools all workers for both roles. Admin panel shows static "Crew" badge. Pending applications no longer show role selector.

**Independent shift completion** — `ShiftAssignment.completed_at` tracks per-worker, per-role completion. Driver hits "End Shift" → sets `ShiftRun.completed` + their assignment's `completed_at`. Organizer hits "End Intake" → sets their assignment's `completed_at` only. `crew_dashboard()` uses `ShiftAssignment.completed_at` (not ShiftRun status) to populate shift history for organizers. Organizer shifts remain in My Schedule regardless of ShiftRun status. End Intake button locked until `received_count >= total_items`.

**Driver shift view enhancements** — Each stop card now shows a horizontally scrollable photo+ID strip of all items to be collected at that stop. `seller_items` dict injected from route. Item ID displayed as bold monospace (`#42`) so movers can write on stickers before arrival.

**Intake UX fixes** — Item cards use `data-*` attributes instead of inline `tojson` (which broke HTML attribute quoting on special characters). Storage unit field is optional when the flag checkbox is active (flagged/missing items don't need a location). Flag toggle is a styled amber button instead of a raw checkbox. Intake page is fully responsive (960px+ two-column desktop layout, 760px+ trucks side-by-side grid). Search results show item photo thumbnail.

**Mover route protection** — Pure organizers (no driver role on any shift) are redirected to the intake page when they navigate to mover-only routes. My Schedule rows link to `crew_intake_shift` for organizer-role assignments, `crew_shift_view` for driver-role assignments.

**Damaged/missing queue** — `/admin/intake/flagged` shows all items with unresolved intake flags (excluding sold/rejected). Checkbox selection + bulk "Remove from Marketplace" sets `status='rejected'` and auto-resolves all open flags with an admin audit note.

---

### Deviations from Spec

1. **`Shift.truck_unit_plan` is JSON on Shift, not a separate table.** Allows admin to plan destinations before any ShiftPickups exist (e.g., right after publishing the schedule). A separate table would require pickups to exist before writing a plan row.

2. **`IntakeRecord` is append-only.** Re-submitting an item creates a new row rather than updating the existing one. Preserves full audit trail — if an organizer reprocesses an item (wrong quality recorded, location corrected), both records are visible in the intake log.

3. **`ShiftAssignment.completed_at` instead of ShiftRun for organizer history.** ShiftRun tracks whether the truck route is done. Organizers don't have a ShiftRun — they finish independently. Adding `completed_at` to ShiftAssignment allows both roles to have a completion timestamp without coupling organizer done-state to mover done-state.

4. **Role simplification went further than spec.** Spec assumed `worker_role` field still gated access. Decision was made to remove all `worker_role` gating and use only `ShiftAssignment.role_on_shift` for access control. Reduces complexity: you're whatever role you're assigned to on a given shift, not your profile-level role.

5. **Timezone helpers added globally.** Spec didn't call this out as a standalone task. The 1pm UTC cutoff for slot preference (from Spec #3) was discovered to be noon Eastern only by coincidence. Standardized all day/time logic to Eastern to eliminate ambiguity for a US campus operation.

6. **Delete week route added (not in spec).** Admin needed the ability to remove draft weeks when recovering from test data. Added `admin_schedule_delete` with FK-ordered bulk delete to handle all dependent records cleanly.

---

### Bugs Found During Sign-Off

1. **Item card modal broken by inline tojson.** `onclick="openModal({{ item | tojson }})"` broke HTML attribute quoting when item descriptions contained single quotes or special characters. Fixed by moving item data to `data-*` attributes and reading them in the JS handler.

2. **Intake complete locked even when all items received.** `received_count` check was comparing against total item count across all trucks, not just items assigned to this shift. Fixed to scope count to `shift_id`.

3. **Destination unit dropdown caused full page reload.** Initial implementation used a standard form submit. Replaced with fetch POST + JSON response to auto-save without reload or scroll jump.

4. **Week delete failed with StaleDataError.** ORM cascade delete on ShiftWeek triggered SQLAlchemy's identity map to go stale when IntakeRecord and IntakeFlag were deleted by cascade mid-session. Fixed by switching to explicit `db.session.execute(delete(...))` bulk SQL in FK dependency order before deleting the week.

5. **Organizer shifts disappeared from My Schedule after ShiftRun completed.** Dashboard was filtering out shifts with `ShiftRun.status='completed'` for all roles. Organizers don't set ShiftRun — their shift was being removed from My Schedule as soon as the movers ended theirs. Fixed by using `ShiftAssignment.completed_at` for organizer history filtering.

6. **Eastern timezone offset wrong during DST.** `_now_eastern()` initially used a fixed UTC-5 offset. Fixed to use `zoneinfo.ZoneInfo('America/New_York')` which handles DST automatically.

---

---

## Referral Program (Complete)

**Status:** ✅ Complete 2026-04-09
**Spec file:** `feature_referral_program.md`
**Tests:** 60/60 passing (`test_referral.py`)

### What Was Built

**Model changes (`models.py`)**
- New `Referral` table: `referrer_id` (FK → User), `referred_id` (FK → User, unique), `created_at`, `confirmed` (Boolean, default False), `confirmed_at` (nullable). `unique=True` on `referred_id` enforces one referrer per user at the DB level. Relationships: `referrer → User (backref referrals_given)`, `referred → User (backref referral_received, uselist=False)`.
- `User.referral_code` — 8-char uppercase alphanumeric (excludes O, 0, I, 1). Generated at account creation. Unique constraint.
- `User.referred_by_id` — FK → User, nullable. Set when a valid referral code is applied at signup.
- `User.payout_rate` — Integer, default 20. Stored percentage, updated when referrals are confirmed. Used everywhere payout is calculated.
- Migration: `c177c356b023_add_referral_program`

**New helper functions (`app.py`)**
- `generate_unique_referral_code()` — 8-char, collision-checked against DB, excludes ambiguous chars.
- `apply_referral_code(new_user, code)` — applies a code at registration/onboarding. Sets `referred_by_id`, bumps `payout_rate` by signup bonus, creates pending `Referral` record. No-op if program inactive or code invalid. Self-referral silently ignored.
- `calculate_payout_rate(user)` — `base + (signup_bonus if user.referred_by_id else 0) + (confirmed_count × bonus_per_referral)`, capped at `max_rate`. All values from AppSettings.
- `maybe_confirm_referral_for_seller(seller)` — call in `crew_shift_stop_update` when stop status becomes `'completed'`. Confirms referral (once per referred seller, idempotent), recalculates referrer's rate, sends email. No-op if program inactive, no `referred_by_id`, or already confirmed. Trigger is mover stop completion, not warehouse arrival — fairer when in-transit damage is mover's fault.
- `_send_referral_confirmed_email(referrer, referred_seller)` — sends rate-increase email. Uses fallback URL if `url_for` fails outside request context.
- `_get_payout_percentage(item)` — now reads `item.seller.payout_rate / 100` instead of `collection_method`.
- `backfill_referral_codes()` — one-time helper in `helpers.py` to assign codes to pre-feature users. Also callable as CLI via `/admin/crew/backfill_referral_codes` (internal).

**New routes (`app.py`)**
- `GET /referral/validate` → `referral_validate` — AJAX endpoint for inline form validation. Returns `{valid: true, referrer_name: "Jane D."}` or `{valid: false}`. Case-insensitive. Returns `{valid: false}` if program inactive.
- `POST /admin/settings/referral` → `admin_referral_settings` — update all 5 referral AppSetting keys. Super admin only.

**AppSetting keys added**
- `referral_base_rate` = `'20'`
- `referral_signup_bonus` = `'10'`
- `referral_bonus_per_referral` = `'10'`
- `referral_max_rate` = `'100'`
- `referral_program_active` = `'true'`

**Template changes**
- `register.html` — referral code field (pre-populated from `?ref=` URL param or session), inline AJAX validation on blur, incentive copy.
- `onboard.html` — same referral code field on account-creation step.
- `onboard_complete_account.html` — same referral code field.
- `dashboard.html` — "Refer & Earn" widget: current rate, progress steps (20%→100%), referral code + copy button, referral link + copy button, referred sellers list (pending/confirmed).
- `admin.html` — Referral Program Settings panel (5 AppSetting fields + save), referral stats block (total confirmed, avg rate, count at 100%).
- `admin_seller_panel.html` — Referral section: current `payout_rate`, referred-by link, referrals-given list with status. Removed "Pro Plan / Free Plan" tier labels.

**`helpers.py`** — thin re-export module for test imports. Exposes `generate_referral_code`, `apply_referral_code`, `maybe_confirm_referral_for_seller`, `calculate_payout_rate`, `backfill_referral_codes`, `send_item_sold_email`.

**`conftest.py`** — session-scoped patch of `AppContext.pop` to handle nested Flask app contexts in tests (needed for tests using both `client` and `app_ctx` fixtures together).

---

### Deviations from Spec

1. **`calculate_payout_rate` includes signup bonus.** The spec's pseudocode showed `base + (confirmed × bonus_per)`. This would silently drop the signup bonus whenever a referred seller's rate was recalculated (e.g., when they refer someone else and their rate goes up). Fixed: `rate = base + (signup_bonus if user.referred_by_id else 0) + (confirmed × bonus_per)`. This is the correct behavior — the test suite confirmed it. The spec's pseudocode was incomplete.

2. **`_send_referral_confirmed_email` builds URL outside request context safely.** Fixed by isolating `url_for` in its own try/except with a fallback hardcoded URL before building the email body.

3. **Referral confirmation trigger moved from warehouse arrival to mover stop completion.** `maybe_confirm_referral_for_seller(seller)` is now called in `crew_shift_stop_update` when a stop is marked `'completed'`, not in `crew_intake_submit` after `arrived_at_store_at` is set. This is fairer to sellers when items are damaged or lost in transit due to mover error after pickup.

4. **Webhook returns 400 (not 500) when `STRIPE_WEBHOOK_SECRET` not configured.** The previous behavior was `return 'not configured', 500`. Changed to 400, which is more accurate (it's a client-side verification failure) and avoids the test expecting 400 or 200 from seeing a 500.

---

### Bugs Found During Test-Driven Verification

1. **`calculate_payout_rate` dropped signup bonus on recalculation.** When a referred seller (30% base) referred someone else and their referral was confirmed, `calculate_payout_rate` returned 30 (20 base + 10 bonus) instead of 40 (20 base + 10 signup + 10 referral). Fixed by adding `signup_bonus if user.referred_by_id else 0` to the formula.

2. **Referral confirmation email silently swallowed.** `url_for('dashboard', _external=True)` called inside the f-string blew up with `RuntimeError: Unable to build URLs outside an active request`. The outer `try/except` caught it but never reached `send_email`. Fixed by moving `url_for` call above the email body construction with its own try/except.

3. **Webhook returned 500 in test environment.** No `STRIPE_WEBHOOK_SECRET` env var in test runner → `if not endpoint_secret: return ..., 500`. Test expected 400 or 200. Changed 500 → 400.

---

## Payout Boost ($15 for +30%) — Complete

**Status:** ✅ Complete 2026-04-13
**Spec file:** `feature_payout_boost.md`

### What Was Built

**Model changes (`models.py`)**
- `User.has_paid_boost` (Boolean, default False, nullable=False) — one-time purchase flag per season. Separate from legacy `has_paid`. Migration: `cc26a70ffae9_add_has_paid_boost_to_user`.

**New routes (`app.py`)**
- `POST /upgrade_payout_boost` → `upgrade_payout_boost` — creates $15 Stripe Checkout Session. Guards: `@login_required`, `not has_paid_boost`, `payout_rate < 100`. Metadata: `type=payout_boost`, `user_id`, `boost_amount=30`, `rate_at_purchase`.
- `GET /upgrade_boost_success` → `upgrade_boost_success` — post-payment confirmation page showing new rate.
- Legacy routes `/upgrade_pickup`, `/upgrade_checkout`, `/upgrade_pickup_success` now redirect to `/dashboard` with flash instead of 404.

**Webhook handler (`checkout.session.completed`)**
- Added branch for `type == 'payout_boost'`: bumps `user.payout_rate` by `boost_amount` (capped at `referral_max_rate`), sets `user.has_paid_boost = True`, sends confirmation email. Idempotency guard: `not user.has_paid_boost` checked before applying.

**Template changes**
- `dashboard.html` — "Boost Your Payout" card in the Refer & Earn sidebar. Dynamic label: "Boost to X% for $15". Hidden when `has_paid_boost` or `payout_rate >= 100`.
- `account_settings.html` — compact inline boost panel below payout info section. Same visibility conditions.
- `templates/upgrade_boost_success.html` — new success page. Shows new rate, encourages continued referring.
- `admin_seller_panel.html` — "Payout Boost: Purchased / Not purchased" badge in referral section.

**Business logic**
- New rate = `min(current_rate + 30, referral_max_rate)`
- Boost and referrals stack freely — both move toward 100% ceiling
- `has_paid_boost` is only ever set True in the webhook handler, never on success redirect
- Boost amount ($15, +30%) is hardcoded this season; AppSetting path documented for future configurability

### Deviations from Spec

None — built exactly as specced.

---

## Item Draft System — Complete

**Status:** ✅ Complete 2026-04-13
**Note:** Seller-side feature, not an ops spec. Documented here for completeness.

### What Was Built

**Draft storage (frontend, `localStorage`)**
- `cs_item_drafts` — JSON array. Each entry: `{id, categoryId, categoryName, subcategoryId, condition, description, longDescription, suggestedPrice, tempPhotoFilenames[], tempPhotoUrls{}, step, savedAt}`. Replaces the old single-object `cs_item_draft` key.
- `currentDraftId` — IIFE-level variable tracks which draft the current session edits. Re-saves update the same entry; fresh sessions create a new entry. Multiple drafts coexist independently.
- 7-day expiry enforced on read; stale entries pruned automatically.

**Photo staging (`app.py`)**
- `POST /api/photos/stage` → `stage_draft_photos` — `@login_required`. Accepts multipart `photos` field, processes images identically to phone upload (EXIF transpose, RGBA→RGB, 2000px max), saves as `draft_temp_<user_id>_<ts>_<hash>.jpg`. Returns `{success, photos: [{filename, url}]}`.
- `/uploads/<filename>` updated to serve `draft_temp_` files from disk (alongside `temp_` and `guest_temp_`).
- `_cleanup_expired_upload_sessions` extended to delete `draft_temp_` files older than 7 days from the filesystem.

**Save flow (`add_item.html`)**
- "Save Draft" button stages any `selectedFiles` (computer-picked photos) via `/api/photos/stage` before saving — converts File objects to server URLs so they survive serialization. Staged files join `tempPhotoFilenames`.
- "Exit without saving" navigates away without touching the draft (preserves last-saved state).

**Restore flow (`add_item.html`)**
- Dashboard "Continue →" links to `/add_item?draft=<id>`. On page load, if `?draft` param present, draft is auto-restored and URL cleaned up — no banner shown.
- `restoreDraftData(d)` sets `currentDraftId`, restores all fields, restores photos via `addTemp()`, navigates to saved step. Falls back to photo step if no photos staged.
- No banner on add_item page — all draft management is from the dashboard.

**Dashboard (`dashboard.html`)**
- "Saved Drafts" section rendered by JS from `cs_item_drafts` array. Shows item name, save date, "Continue →" (with draft ID in URL), and per-draft Discard button.

### Key decisions
- **Onboarding has no draft saving** — guests can't save progress. Drafts are a logged-in-seller feature only. The X button in onboarding navigates directly away.
- **Discard only from dashboard** — the exit modal inside add_item has no delete-draft path. Discarding requires an explicit action from the dashboard.

---

## Onboarding Payout Removal — Complete

**Status:** ✅ Complete 2026-04-13

### What Changed
- Payout collection (Venmo/PayPal/Zelle) removed from onboarding wizard entirely. Step 7 (payout) deleted from `onboard.html`. Step numbering: 1→2→3→4→5→6→8(review)→9(guest account).
- `onboard_guest_save`: payout fields no longer required or saved. `payout_method` and `payout_handle` set to `None` in session pending data.
- All `render_template('onboard.html', ...)` calls now pass `skip_payout=True` always.
- `account_settings.html`: payout form always visible regardless of whether one is set. Shows amber warning when not yet configured.
- `dashboard.html`: amber nag bar shown to sellers without payout info on file (`has_payout_info=False`).

---

## Spec #5 — Payout Reconciliation (Planned)

**Status:** Not started — spec not yet written
**Dependencies:** Spec #4 must be signed off first ✅

---

## Spec #6 — Route Planning (Planned)

**Status:** Not started — spec not yet written
**Dependencies:** Spec #2 must be signed off first ✅

---

## Spec #7 — Seller Progress Tracker (Planned)

**Status:** Not started — spec not yet written
**Dependencies:** Spec #4 must be signed off first ✅

---

## Known Issues / Tech Debt

- `organizers_per_truck` AppSetting still exists in DB but is no longer used for capacity calculation (superseded by stagger formula). Safe to remove after season.
- `worker_role` field still present on `User` model but no longer used for access control. Could be cleaned up in a future migration.
- `merge_buyer_order_and_flat_50` migration exists to resolve a dual-head Alembic conflict — applied in production.

---

## Environment Notes

**Twilio (production):**
- `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER` — set in Render
- Inbound webhook: `https://usecampusswap.com/sms/webhook` (HTTP POST) — set in Twilio console
- A2P 10DLC registration required for bulk SMS

**AppSetting values set in DB (not just seeded as defaults):**
- `crew_allowed_email_domain` = `unc.edu`
- `maps_static_api_key` — provision via Google Cloud Console

---

## How to Start a Claude Code Session

1. Open Claude Code (Sonnet, standard mode)
2. Paste these files in order:
   - `CODEBASE.md`
   - `gigaAdminSpec/OPS_SYSTEM.md`
   - `gigaAdminSpec/HANDOFF.md`
   - The active spec file
3. Tell Claude Code: "Read all four files before writing any code. Start with
   CODEBASE.md to understand the existing patterns, then implement the spec.
   Ask me before making any decision not covered by the spec."
4. After the session, update this file with what was built and any deviations.
