# Feature Spec: Campus Director Tutorial

**Status:** Ready for Claude Code
**Depends on:** feature_campus_director_role.md (complete), feature_admin_panel_fixes.md (complete)
**Applies to:** is_campus_director only (tutorial system), is_super_admin (completion tracking in Settings)
**Estimated complexity:** Large — migration, seeded dummy data, tutorial session model, overlay system, CD settings page

---

## Goal

Give each campus director a mandatory, self-serve walkthrough of the three admin
panel areas they own: Schedule, Crew, and Ops. The tutorial uses a fully isolated
sandbox — dummy sellers, dummy workers, and a tutorial-scoped shift week — so the
campus director performs every real action against realistic data without touching
production. Completion is tracked per user and visible to super admins.

---

## Model Changes

### New model: `TutorialSession`

```python
class TutorialSession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), unique=True, nullable=False)
    step = db.Column(db.Integer, default=0, nullable=False)
        # 0 = not started
        # 1 = started (welcome shown, on schedule tab)
        # 2 = week created (on crew tab — approve worker)
        # 3 = worker approved (on crew tab — assign to shift)
        # 4 = worker assigned (on ops tab — assign sellers)
        # 5 = sellers assigned (on ops tab — reorder stops)
        # 6 = stops reordered (on ops tab — notify sellers)
        # 7 = complete
    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    tutorial_week_id = db.Column(db.Integer, db.ForeignKey('shift_week.id'), nullable=True)

    user = db.relationship('User', backref=db.backref('tutorial_session', uselist=False))
    tutorial_week = db.relationship('ShiftWeek')
```

### Existing model changes

**`User`** — add two fields:
```python
is_tutorial_user = db.Column(db.Boolean, default=False, server_default='0', nullable=False)
# Marks dummy sellers and dummy workers seeded for the tutorial.
# These users are permanent fixture accounts, never shown outside tutorial mode.
```

**`ShiftWeek`** — add one field:
```python
is_tutorial = db.Column(db.Boolean, default=False, server_default='0', nullable=False)
# Set True on ShiftWeeks created during a tutorial session.
# Tutorial weeks are invisible outside tutorial mode and deleted on completion.
```

**Migration name:** `add_tutorial_system`

---

## Dummy Data — Seeded Once, Permanent Fixtures

Seeded via a migration data seed or a `seed_tutorial_fixtures()` function called
at app startup (idempotent — checks for existence before creating). These records
live in the DB permanently, gated by `is_tutorial_user=True`.

### Dummy Sellers (3 accounts)

All three have `is_tutorial_user=True`, `is_seller=True`, `pickup_week='week1'`,
`pickup_location_type='on_campus'`, approved items in inventory.

| Name | Address | Items |
|---|---|---|
| Alex Martinez | 210 Pittsboro St, Chapel Hill NC | Desk lamp, Mini-fridge (2 items) |
| Jordan Kim | 404 W Franklin St, Chapel Hill NC | Couch, Bookshelf (2 items) |
| Casey Brooks | 108 South Rd, Chapel Hill NC | Coffee table, Desk chair (2 items) |

Each seller's items: `status='available'`, realistic prices ($25–$120),
`is_tutorial_user` on the seller account gates them out of all non-tutorial queries.

**Pre-assigned seller (the "moved" stop):**
Casey Brooks has `rescheduled_at` set (non-null) on their `ShiftPickup` during
tutorial seeding. When the tutorial shift is created at step 1, Casey Brooks is
pre-assigned to truck 1 with `rescheduled_at = datetime.utcnow()` — this gives
them the blue "moved" badge. `stop_order = 1` is set so they appear as stop #1.
Alex Martinez and Jordan Kim remain in the unassigned panel for the campus director
to assign manually.

### Dummy Workers (2 accounts)

| Name | Status | Role |
|---|---|---|
| Sam Torres | `worker_status='pending'` | Has a pending WorkerApplication with realistic availability |
| Riley Chen | `worker_status='approved'`, `worker_role='both'` | Already approved, appears in the approved workers list |

Sam Torres's `WorkerApplication`: filled-in `why_blurb` ("I'm looking for
flexible work during move-out season"), availability set for Mon–Fri AM+PM.

---

## Tutorial Data Isolation

When a campus director has an active tutorial session (`session['tutorial_active']
= True`), every admin query in the three tutorial-relevant areas filters to
tutorial data only. This is implemented by passing a `tutorial_mode` boolean into
the relevant route context and branching queries.

### Affected queries (tutorial_mode=True replaces normal queries):

**Schedule tab (`admin_schedule_index`, `admin_schedule_week`):**
- `ShiftWeek` query: `ShiftWeek.is_tutorial == True` only
- Result: no real weeks shown; only the week the campus director creates

**Crew tab (`admin_crew_panel`, shift board partial):**
- Pending applications: `User.is_tutorial_user == True` only
- Approved workers: `User.is_tutorial_user == True` only
- Shift board weeks: `ShiftWeek.is_tutorial == True` only

**Ops tab (`admin_ops`, truck detail, assign seller, reorder, notify):**
- Shift list: `ShiftWeek.is_tutorial == True` only
- Unassigned sellers: `User.is_tutorial_user == True` only
- All ShiftPickup operations scoped to the tutorial shift

**All other tabs (Items, Sellers, Payouts, Settings):** campus directors cannot
reach these — no change needed.

### Tutorial mode activation:

```python
# Set on tutorial start (POST /admin/tutorial/start)
session['tutorial_active'] = True
session['tutorial_step'] = 1

# Cleared on completion (POST /admin/tutorial/complete)
session.pop('tutorial_active', None)
session.pop('tutorial_step', None)
```

Every admin route that participates in the tutorial checks:
```python
tutorial_mode = (
    current_user.is_campus_director and
    session.get('tutorial_active', False)
)
```

### Concurrent tutorials:

Each campus director creates their own `ShiftWeek` (tagged `is_tutorial=True`)
and their own `ShiftPickup` records. Dummy sellers and workers are shared
read-only fixtures. Two concurrent tutorials do not collide.

---

## Tutorial Flow — Step by Step

### Step 0 — Tutorial Gate (before first login to admin)

When a campus director logs in and has no `TutorialSession` record (or
`TutorialSession.completed_at IS NULL` and `step == 0`), they are redirected
from any `/admin/*` route to `/admin/tutorial` instead. They cannot access any
admin panel page until tutorial is complete.

The redirect check is added to the `require_ops_access` decorator:
```python
if current_user.is_campus_director:
    ts = current_user.tutorial_session
    if ts is None or ts.completed_at is None:
        return redirect(url_for('admin_tutorial'))
```

Exception: `/admin/tutorial` itself and `/admin/tutorial/start` are exempt
from this redirect.

### Step 1 — Welcome Page (`GET /admin/tutorial`)

A standalone full-page welcome screen. Does not use `admin_layout.html` —
uses `layout.html` (or a dedicated minimal layout). Clean, focused.

**Content:**
- Campus Swap logo / wordmark
- Heading: "Welcome to the Campus Swap Admin Panel"
- Subheading: "[First name], before you get started, let's walk through
  a simulated pickup day."
- Three-item summary of what they'll do:
  - 📅 Create a pickup week
  - 👥 Staff your crew
  - 🚛 Build and send a route
- Estimated time: "About 5 minutes"
- Single CTA button: "Start Tutorial →"
- No skip button. No back button.

**On "Start Tutorial →" click:**
- `POST /admin/tutorial/start`
- Creates `TutorialSession(user_id=..., step=1, started_at=now())`
- Seeds the tutorial shift: creates one `Shift` record on the tutorial week
  (tutorial week doesn't exist yet — skip this; the shift is created after
  the campus director creates the week in step 2). Actually: pre-create a
  `ShiftWeek` skeleton? No — the point of step 2 is that THEY create the week.
  Casey Brooks's pre-assignment happens in the `admin_schedule_create` handler
  when `is_tutorial=True` (see Step 2).
- Sets `session['tutorial_active'] = True`
- Redirects to `/admin/schedule`

### Step 2 — Create a Week (`GET /admin/schedule`, overlay step 1)

Campus director lands on the Schedule tab. Tutorial overlay appears.

**Overlay card:**
- Position: bottom-right corner (desktop), bottom of screen (mobile)
- Step indicator: "Step 1 of 5"
- Title: "Create your first pickup week"
- Body: "Every pickup starts with a week. Pick any Monday and hit Create Week
  — this tells the system what dates your crew will be running."
- Action indicator: "👆 Pick a Monday below and create the week"
- No "Got it" button — this step requires the action

**Target highlight:** pulsing ring on the week creation form

**On week creation POST (`admin_schedule_create`):**
- Normal week creation runs
- If `tutorial_mode`: set `ShiftWeek.is_tutorial = True` on the new week
- Auto-create one `Shift` on the first day of the new week (AM slot)
- Pre-assign Casey Brooks to that shift: create `ShiftPickup` with
  `seller_id = casey_brooks.id`, `truck_number = 1`, `stop_order = 1`,
  `rescheduled_at = datetime.utcnow()` (triggers "moved" badge),
  `created_by_id = current_user.id`
- Store `TutorialSession.tutorial_week_id = new_week.id`
- Bump `TutorialSession.step = 2`
- Redirect to `/admin/crew` (not back to schedule)

### Step 3a — Approve a Worker (`GET /admin/crew`, overlay step 2)

**Overlay card:**
- Step indicator: "Step 2 of 5"
- Title: "Approve your first crew member"
- Body: "Sam Torres has applied to join your crew. Review their application
  and approve them."
- Action indicator: "👆 Approve Sam Torres below"
- Highlight: pulsing ring on Sam Torres's pending application row

**On approve POST (`admin_crew_approve`):**
- Normal approval runs (sets `worker_status='approved'`, `worker_role='both'`)
- If `tutorial_mode`: bump `TutorialSession.step = 3`
- Stay on `/admin/crew` — step 3b overlay appears on reload

### Step 3b — Assign Worker to Shift (`GET /admin/crew`, overlay step 3)

**Overlay card:**
- Step indicator: "Step 3 of 5"
- Title: "Assign your crew to a shift"
- Body: "Now assign a worker to the shift you just created. Find your week
  in the shift board and add Riley Chen or Sam Torres."
- Action indicator: "👆 Add a worker to your shift below"
- Highlight: pulsing ring on the shift board section

**On worker quick-add fetch (`admin_crew_quick_add`):**
- Normal quick-add runs
- If `tutorial_mode` and the target shift is `is_tutorial`: bump
  `TutorialSession.step = 4`
- Shift board partial re-renders as normal (fetch-based, no reload)
- Client JS detects step advancement in the JSON response
  (`{success: true, tutorial_step_advanced: true}`) and redirects to
  `/admin/ops`

### Step 4a — Assign Sellers (`GET /admin/ops`, overlay step 4)

**Overlay card:**
- Step indicator: "Step 4 of 5"
- Title: "Build your route"
- Body: "Casey Brooks has already added themselves to the route — you'll
  see them on the truck with a 'moved' badge. Now assign Alex Martinez
  and Jordan Kim from the unassigned panel."
- Action indicator: "👆 Assign the remaining sellers on the right"
- Highlight: pulsing ring on the unassigned panel

**Advancement logic:**
- After each assign POST, check: are all 3 tutorial sellers assigned to
  the tutorial shift?
- If yes: bump `TutorialSession.step = 5`, redirect to
  `/admin/ops/shift/<tutorial_shift_id>/truck/1/reorder`

### Step 5 — Reorder Stops (reorder page, overlay step 5... wait, this
  counts as part of step 4 in the UX — renumber as needed)

Actually renumbering overlay steps to match UX steps cleanly:

| Overlay "Step X of 5" | TutorialSession.step | Action |
|---|---|---|
| Step 1 of 5 | 1 | Create a week |
| Step 2 of 5 | 2 | Approve Sam Torres |
| Step 3 of 5 | 3 | Assign worker to shift |
| Step 4 of 5 | 4 | Assign sellers + reorder |
| Step 5 of 5 | 6 | Notify sellers |

Steps 4 and 5 (assign + reorder) are combined as "Step 4 of 5" — the
reorder page is a natural continuation of building the route, not a
separate conceptual step.

**On the reorder page:**
No new overlay card needed — the page itself is self-explanatory (drag
handles, "Save Order" button). Add a single contextual banner at the top
of the reorder page when `tutorial_mode`:

```
"Drag the stops into the order that makes the most sense for your route.
 Casey Brooks has already moved into the route — make sure the order
 works around them."
```

**On save order POST (`admin_ops_reorder_stops`):**
- Normal stop reorder runs
- If `tutorial_mode`: bump `TutorialSession.step = 6`
- Redirect to `/admin/ops?shift_id=<tutorial_shift_id>`

### Step 6 — Notify Sellers (`GET /admin/ops`, overlay step 5)

**Overlay card:**
- Step indicator: "Step 5 of 5"
- Title: "Notify your sellers"
- Body: "Your route is set. Hit 'Notify Sellers' to send pickup confirmations
  to all three sellers. In real life, this sends them an email (and SMS if
  set up) with their pickup window."
- Action indicator: "👆 Click Notify Sellers above"
- Highlight: pulsing ring on the Notify Sellers button

**On notify POST (`admin_shift_notify_sellers`):**
- If `tutorial_mode`: DO NOT send real emails or SMS. Skip the Resend/Twilio
  calls entirely for tutorial sellers. Add guard:
  ```python
  if not seller.is_tutorial_user:
      # send real email/SMS
  ```
- Bump `TutorialSession.step = 7`
- Redirect to `/admin/tutorial/complete`

### Step 7 — Completion (`GET /admin/tutorial/complete`)

A standalone full-page completion screen (same minimal layout as welcome).

**Content:**
- ✅ checkmark animation (CSS, no library)
- Heading: "You're ready."
- Body: "You just walked through a full Campus Swap pickup day. Here's what
  you did:"
- Summary list:
  - ✅ Created a pickup week
  - ✅ Approved a crew member
  - ✅ Assigned workers to a shift
  - ✅ Built a route with 3 sellers
  - ✅ Reordered your stops
  - ✅ Notified your sellers
- CTA button: "Go to the Admin Panel →" → `/admin/ops`

**On page load:**
- `POST /admin/tutorial/complete` fires automatically (or on button click)
- Sets `TutorialSession.completed_at = now()`
- Clears `session['tutorial_active']`, `session['tutorial_step']`
- Deletes tutorial ShiftWeek cascade: ShiftPickups → Shifts → ShiftWeek
  (use bulk DELETE in FK order per Critical Rule #10)
- Does NOT delete dummy User accounts (they persist for future tutorials)

---

## Browser Close / Restart Behavior

If the campus director closes their browser mid-tutorial:
- `session['tutorial_active']` is lost (Flask session, cookie-based)
- `TutorialSession.step` persists in DB
- On next visit to any `/admin/*` route: the gate redirect sends them to
  `/admin/tutorial`
- `/admin/tutorial` detects existing incomplete `TutorialSession` and shows
  a restart page instead of the welcome page:

**Restart state of `/admin/tutorial`:**
- Heading: "Let's try that again."
- Body: "It looks like your tutorial was interrupted. Let's start fresh."
- Button: "Restart Tutorial →" → `POST /admin/tutorial/start`
- `POST /admin/tutorial/start` when a `TutorialSession` already exists:
  - Resets `step = 1`, `started_at = now()`, `completed_at = None`
  - Deletes any existing tutorial ShiftWeek (and cascade) from previous attempt
  - Sets `session['tutorial_active'] = True`
  - Redirects to `/admin/schedule`

---

## Overlay System

### Rendering

Overlay cards are rendered server-side into the template, not fetched after
load. Each admin template that participates in the tutorial checks
`tutorial_mode` and `tutorial_step` (passed as template context vars) and
conditionally renders the overlay HTML inline.

```jinja2
{% if tutorial_mode %}
  {% include 'admin/tutorial_overlay.html' %}
{% endif %}
```

`tutorial_overlay.html` receives `tutorial_step` and renders the correct card
content via `{% if tutorial_step == 1 %}...{% elif tutorial_step == 2 %}` etc.

### Overlay card structure

```html
<div class="tutorial-overlay-card">
  <div class="tutorial-step-indicator">Step {{ display_step }} of 5</div>
  <h3 class="tutorial-overlay-title">...</h3>
  <p class="tutorial-overlay-body">...</p>
  <div class="tutorial-overlay-action">
    <span class="tutorial-action-arrow">👆</span>
    <span class="tutorial-action-text">...</span>
  </div>
</div>
```

### Positioning and styling

```css
.tutorial-overlay-card {
  position: fixed;
  bottom: 24px;
  right: 24px;
  width: 320px;
  background: white;
  border: 2px solid var(--primary);
  border-radius: 12px;
  padding: 20px;
  box-shadow: 0 8px 32px rgba(0,0,0,0.15);
  z-index: 1000;
}

/* Mobile */
@media (max-width: 768px) {
  .tutorial-overlay-card {
    bottom: 0;
    right: 0;
    left: 0;
    width: 100%;
    border-radius: 12px 12px 0 0;
    border-bottom: none;
  }
}

.tutorial-step-indicator {
  font-size: 0.75rem;
  color: var(--muted);
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-bottom: 8px;
}

.tutorial-highlight {
  box-shadow: 0 0 0 3px var(--primary), 0 0 0 6px rgba(var(--primary-rgb), 0.2);
  border-radius: 6px;
  animation: tutorial-pulse 2s ease-in-out infinite;
}

@keyframes tutorial-pulse {
  0%, 100% { box-shadow: 0 0 0 3px var(--primary), 0 0 0 6px rgba(var(--primary-rgb), 0.2); }
  50% { box-shadow: 0 0 0 3px var(--primary), 0 0 0 10px rgba(var(--primary-rgb), 0.1); }
}
```

The `tutorial-highlight` class is added directly in the template to the
target element when `tutorial_mode` is active. No JS needed for the highlight
— it's a CSS class applied server-side.

---

## Repeat Tutorial — Campus Director Settings Page

### New page: `GET /admin/cd-settings`

A minimal settings page visible only to `is_campus_director` users. Added as
a sidebar nav item for campus directors only (below Schedule in the sidebar).

**Sidebar entry:**
```
⚙ Settings   →  /admin/cd-settings   (visible: is_campus_director only)
```

Note: super admins already have `/admin/settings` — this page is entirely
separate and does not conflict.

**Page content (`admin/cd_settings.html`):**
- Page title: "Campus Director Settings"
- One section: "Tutorial"
  - Description: "Walk through the admin tutorial again to refresh your
    knowledge of the system."
  - Button: "Retake Tutorial" → `POST /admin/tutorial/restart`
  - If tutorial was never completed: button is grayed out with tooltip
    "Complete the tutorial first to unlock this."

**`POST /admin/tutorial/restart`:**
- Only callable if `TutorialSession.completed_at IS NOT NULL` (already completed)
- Resets `TutorialSession.step = 0`, `completed_at = None`, `started_at = None`
- Does NOT clear `completed_at` from the tracking perspective — actually, we
  do want to allow retaking without losing the completion record. Add a separate
  field: `last_retake_at` (DateTime, nullable). On restart: set `last_retake_at
  = now()`, reset `step = 1`, leave `completed_at` as-is.
- Wait — if `completed_at` is set, the tutorial gate won't fire. The retake
  should set a separate `is_retaking` flag.

**Revised `TutorialSession` additions:**
```python
last_retake_at = db.Column(db.DateTime, nullable=True)
is_retaking = db.Column(db.Boolean, default=False, server_default='0')
```

**Tutorial gate logic (revised):**
```python
if current_user.is_campus_director:
    ts = current_user.tutorial_session
    needs_tutorial = (
        ts is None or
        ts.completed_at is None or
        ts.is_retaking
    )
    if needs_tutorial:
        return redirect(url_for('admin_tutorial'))
```

**On retake start (`POST /admin/tutorial/restart` → `POST /admin/tutorial/start`):**
- Sets `is_retaking = True`, resets `step = 1`, `started_at = now()`
- Retake allows exit: the overlay card shows a small "Exit Tutorial" link
  in the bottom-left corner of the card — only during retake (`is_retaking=True`)
- Exit: `POST /admin/tutorial/exit` → sets `is_retaking = False`, step = 7
  (or whatever complete state), clears session flags, redirects to `/admin/ops`
- Completion of retake: same completion flow as first run, but does NOT
  delete tutorial week / cleanup (already done). Sets `is_retaking = False`.

---

## Completion Tracking — Super Admin Settings Page

Add a "Campus Directors" section to `/admin/settings` (it may already exist
from the campus director role spec — if so, extend it).

**New subsection: "Tutorial Completion"**

Table columns: Name | School | Tutorial Status | Completed

```
Jordan Smith    UNC Chapel Hill    ✅ Complete      May 21, 2026
Casey Lee       Duke               ⬜ Not Started   —
```

Status is binary: complete (green ✅ with date) or not started (gray ⬜).
"In progress" is not shown — a campus director is either done or not.

Query: `User.query.filter_by(is_campus_director=True).all()` + join
`TutorialSession`. Users with no `TutorialSession` or `completed_at IS NULL`
and `is_retaking=False` show as "Not Started."

---

## New Routes

| Method | Path | Function | Description |
|---|---|---|---|
| `GET` | `/admin/tutorial` | `admin_tutorial_welcome` | Welcome page (or restart page if prior session exists). Campus director only. |
| `POST` | `/admin/tutorial/start` | `admin_tutorial_start` | Create/reset TutorialSession, set session flags, redirect to /admin/schedule. |
| `POST` | `/admin/tutorial/complete` | `admin_tutorial_complete` | Mark completed, clean up tutorial week, clear session flags. |
| `POST` | `/admin/tutorial/exit` | `admin_tutorial_exit` | Exit retake mode only (not first run). Sets is_retaking=False, redirects to /admin/ops. |
| `POST` | `/admin/tutorial/restart` | `admin_tutorial_restart` | Available post-completion via CD settings. Sets is_retaking=True, resets step. |
| `GET` | `/admin/tutorial/complete` | `admin_tutorial_complete_page` | Completion screen shown after tutorial finishes. |
| `GET` | `/admin/cd-settings` | `admin_cd_settings` | Campus director settings page. is_campus_director only. |

---

## Template Changes

| Template | Change |
|---|---|
| `admin/tutorial_welcome.html` | New. Full-page welcome / restart screen. Uses layout.html. |
| `admin/tutorial_complete.html` | New. Full-page completion screen. Uses layout.html. |
| `admin/tutorial_overlay.html` | New. Overlay card partial, included conditionally in tutorial-aware templates. |
| `admin/cd_settings.html` | New. CD settings page with retake tutorial section. |
| `admin/schedule_index.html` | Add `tutorial-highlight` class to week creation form when `tutorial_mode`. Pass `tutorial_mode` from route. |
| `admin/crew.html` | Add overlay include + `tutorial-highlight` on pending apps section and shift board when `tutorial_mode`. |
| `admin/ops.html` | Add overlay include + `tutorial-highlight` on unassigned panel (step 4) and Notify Sellers button (step 6). |
| `admin/ops_reorder.html` | Add tutorial context banner when `tutorial_mode`. No overlay card needed. |
| `admin_layout.html` | Add "Settings" sidebar link for `is_campus_director` pointing to `/admin/cd-settings`. |
| `admin/settings.html` | Extend campus directors section with tutorial completion table. |

---

## Business Logic & Edge Cases

**Tutorial sellers never appear in production queries.** Every query touching
sellers, ShiftPickups, or the unassigned panel must filter
`User.is_tutorial_user == False` when NOT in tutorial mode. Add this guard to:
- `admin_ops` unassigned panel query
- `admin_shift_assign_seller`
- Any seller search or listing query

**Tutorial weeks never appear in production ops.** Add `ShiftWeek.is_tutorial
== False` to the default shift list query in `admin_ops`.

**Notify Sellers skips tutorial users.** In `admin_shift_notify_sellers`: skip
Resend email and Twilio SMS for any seller where
`seller.is_tutorial_user == True`. This is a hard guard — tutorial must never
send real communications.

**Cleanup on completion uses bulk DELETE.** Per Critical Rule #10, delete in FK
order:
1. `ShiftPickup` where `shift_id IN (SELECT id FROM shift WHERE shift_week_id = ?)`
2. `ShiftAssignment` same pattern
3. `Shift` where `shift_week_id = ?`
4. `ShiftWeek` where `id = ?`
Do NOT use ORM cascade — use `db.session.execute(delete(Model).where(...))`.

**Tutorial step gate is in `require_ops_access` decorator.** The gate fires on
every admin route. Exception list: `/admin/tutorial`, `/admin/tutorial/start`,
`/admin/tutorial/complete` (GET), `/admin/cd-settings`.

**Step idempotency.** Step bumps only advance forward — never decrement. If a
campus director somehow POSTs the same action twice (browser back + resubmit),
the step guard `if ts.step == expected_step: ts.step += 1` prevents double-
advancing.

**Super admins and is_admin users are never gated.** The tutorial gate only
fires for `current_user.is_campus_director == True and not current_user.is_admin
and not current_user.is_super_admin`.

---

## Definition of Done

### Sandbox isolation
- [ ] Campus director in tutorial mode sees zero real ShiftWeeks on Schedule tab
- [ ] Campus director in tutorial mode sees only Sam Torres and Riley Chen on Crew tab
- [ ] Campus director in tutorial mode sees only Alex, Jordan, Casey in unassigned panel
- [ ] Real admin (is_admin) sees zero tutorial weeks, sellers, workers at all times
- [ ] Two campus directors running tutorial simultaneously do not see each other's data

### Tutorial gate
- [ ] New campus director visiting `/admin/ops` is redirected to `/admin/tutorial`
- [ ] Campus director with completed tutorial visits `/admin/ops` — no redirect
- [ ] Super admin visiting `/admin/tutorial` — no gate, page loads normally

### Step 1 — Welcome
- [ ] Welcome page renders with campus director's first name
- [ ] "Start Tutorial" POST creates TutorialSession, sets session flag, redirects to /admin/schedule
- [ ] No skip button present
- [ ] Second visit (after browser close) shows restart page, not welcome page

### Step 2 — Create Week
- [ ] Overlay card renders on /admin/schedule with step "1 of 5"
- [ ] Week creation form has tutorial-highlight pulsing ring
- [ ] Creating a week sets is_tutorial=True on the ShiftWeek
- [ ] Casey Brooks is pre-assigned to first shift with rescheduled_at set (moved badge)
- [ ] TutorialSession.tutorial_week_id is set
- [ ] After creation, redirect goes to /admin/crew (not /admin/schedule)

### Step 3a — Approve Worker
- [ ] Overlay card renders on /admin/crew with step "2 of 5"
- [ ] Sam Torres pending application visible with tutorial-highlight
- [ ] Approving Sam Torres bumps TutorialSession.step to 3

### Step 3b — Assign Worker
- [ ] Overlay card renders on /admin/crew with step "3 of 5"
- [ ] Shift board shows tutorial week's shift with tutorial-highlight
- [ ] Adding worker via quick-add fetch bumps step to 4 and redirects to /admin/ops

### Step 4 — Assign Sellers
- [ ] Overlay card renders on /admin/ops with step "4 of 5"
- [ ] Casey Brooks visible on truck card with blue "moved" badge
- [ ] Alex Martinez and Jordan Kim visible in unassigned panel
- [ ] Assigning both remaining sellers advances to reorder page automatically

### Reorder (part of step 4)
- [ ] Tutorial context banner visible on reorder page
- [ ] Drag-to-reorder works normally (SortableJS)
- [ ] Saving order bumps TutorialSession.step to 6, redirects to /admin/ops

### Step 6 — Notify
- [ ] Overlay card renders on /admin/ops with step "5 of 5"
- [ ] Notify Sellers button has tutorial-highlight
- [ ] Clicking Notify Sellers does NOT send real emails to tutorial sellers
- [ ] After notify, redirect goes to /admin/tutorial/complete

### Completion
- [ ] Completion page renders with full summary checklist
- [ ] TutorialSession.completed_at is set in DB
- [ ] Tutorial ShiftWeek and its Shifts + ShiftPickups are deleted
- [ ] session['tutorial_active'] is cleared
- [ ] "Go to Admin Panel" lands on /admin/ops showing real production data
- [ ] Super admin Settings page shows this campus director as "✅ Complete"

### CD Settings / Retake
- [ ] /admin/cd-settings accessible to is_campus_director, 403 for others
- [ ] "Retake Tutorial" button only active after completion
- [ ] Retaking sets is_retaking=True and gates admin panel again
- [ ] Retake shows "Exit Tutorial" link in overlay card
- [ ] Exiting retake clears is_retaking, lands on /admin/ops
- [ ] Completing retake sets is_retaking=False, does not change completed_at

### Guards
- [ ] Notify Sellers never sends email/SMS to is_tutorial_user sellers
- [ ] Tutorial weeks never appear in production shift list
- [ ] Tutorial sellers never appear in production unassigned panel
