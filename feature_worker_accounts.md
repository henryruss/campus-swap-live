# Feature Spec: Worker Accounts & Application Flow
*Final — 7-day grid, AM/PM per cell, no day-blackout shortcut*

## Goal

Enable Campus Swap to hire a seasonal workforce (drivers and organizers) through
a UNC-email-gated application flow built into the existing Flask app. Workers
apply at a public URL restricted to .edu email addresses, submit granular
availability via a tap-to-blackout 7×2 grid (days × AM/PM), and get approved
by admins. Admins then run a constraint-satisfaction optimizer in spec #2 to
auto-generate a proposed schedule. This spec covers identity, application, and
availability collection only.

---

## Background & Constraints

- Any .edu email can apply. Domain check only — no external service.
- Workers may already have Campus Swap accounts. Apply flow upgrades existing
  accounts, never creates duplicates.
- Two roles: driver and organizer. Identical pay ($130/shift) and process.
  Role affects assignment in spec #2.
- Availability is strictly honored — the optimizer never schedules a worker
  into a blacked-out slot. No exceptions.
- Shifts run 7 days a week across the ~3-week season. Grid always shows all
  7 days. Admin configures which specific dates actually have shifts in spec #2.
- Staffing ratios (enforced in spec #2, seeded here):
  - 1 truck = 2 drivers + 2 organizers
  - Up to 4 trucks per shift on busy days → max 8 drivers + 8 organizers per shift
  - Admin sets trucks-per-shift when building the schedule

---

## UX Flow

### Applicant Path

1. Worker visits `/crew/apply` — publicly discoverable, no token required.

2. Page shows a short intro: what the job is, $130/shift, ~3 weeks, both roles
   explained plainly (drivers pick up items in the field; organizers receive
   and tag items at the storage unit).

3. **Email validation:**
   - Must be `.edu`. Client-side warning on blur. Server-side hard rejection:
     "Applications are open to students with a .edu email address."
   - No email confirmation link in v1.

4. **If not logged in:** Full form. Fields: full name, email (.edu), phone,
   UNC year (Freshman / Sophomore / Junior / Senior / Graduate), role
   preference (Driver / Organizer / Both), availability grid, optional blurb
   (max 500 chars). Google OAuth option available.

5. **If logged in with .edu email:** Name, email, phone pre-filled and
   read-only. Worker fills in year, role preference, grid, blurb.

6. **If logged in with non-.edu email:** Notice with sign-out link.
   No auto account creation.

7. On submit: `WorkerApplication` + initial `WorkerAvailability` record
   created. Confirmation: "Application received — we'll be in touch within
   a few days."

8. Re-applying: flash error "You've already applied. We'll reach out soon."

### Availability Grid UI

A 7-row × 2-column grid. Clean, minimal, works on mobile.

```
           [ AM ]  [ PM ]
Monday     [    ]  [    ]
Tuesday    [    ]  [    ]
Wednesday  [    ]  [    ]
Thursday   [    ]  [    ]
Friday     [    ]  [    ]
Saturday   [    ]  [    ]
Sunday     [    ]  [    ]
```

**Default state:** All 14 cells are green — fully available. Workers only
interact with slots they need to black out.

**Interaction:** Tap/click any cell to toggle it between available (green)
and unavailable (grey/muted). That's it — no other controls needed. Blacking
out both AM and PM for a row is a full-day blackout.

**Output:** 14 hidden form inputs (`mon_am`, `mon_pm`, `tue_am`, ... `sun_pm`),
each `true` or `false`. JS updates these on every toggle. Server reads them
directly on POST.

**Mobile:** Cells are minimum 44px tap targets. Day labels truncate to 3-letter
abbreviations on narrow screens (Mon, Tue, etc.).

### Weekly Availability Update

After approval, workers update availability each week from their crew dashboard.
A banner shows Sunday–Tuesday: "Submit your availability for [week dates] by
Tuesday at midnight." Same grid, pre-filled from their previous submission —
they only change what's different.

After the Tuesday deadline the form locks with: "Availability submitted —
your schedule will be posted by Thursday."

### Admin Approval Path

1. "Crew" collapsible section added to admin panel. Amber badge on pending count.

2. Applications table: Name, Email, Phone, Year, Role Pref, Applied, Status, Actions.

3. Per-applicant actions:
   - **Approve** → inline modal to confirm assigned role (Driver / Organizer /
     Both). Sets `is_worker=True`, `worker_status='approved'`, `worker_role`.
     Sends approval email. Immediate `/crew` access.
   - **Reject** → confirm step with optional rejection email toggle.
   - **View** → expands inline to show availability grid and optional blurb.

4. Approved workers sub-table: Name, Role, Shifts Assigned (0 until spec #2),
   compact availability summary.

---

## New Routes

| Method | Path | Function | Description |
|--------|------|----------|-------------|
| GET | `/crew/apply` | `crew_apply` | Application page. Public. |
| POST | `/crew/apply` | `crew_apply_post` | Validates .edu, creates records. |
| GET | `/crew` | `crew_dashboard` | Worker portal. Requires approved worker. |
| GET | `/crew/pending` | `crew_pending` | Holding page for pending applicants. |
| GET | `/crew/availability` | `crew_availability` | Weekly availability form. |
| POST | `/crew/availability` | `crew_availability_post` | Upserts weekly availability. |
| POST | `/admin/crew/approve/<user_id>` | `admin_crew_approve` | Approve + assign role. |
| POST | `/admin/crew/reject/<user_id>` | `admin_crew_reject` | Reject application. |

**Route guards:**
- `/crew` and `/crew/availability`: `@require_crew` —
  `current_user.is_authenticated and current_user.is_worker
  and current_user.worker_status == 'approved'`
- `/crew/pending`: login required only.
- `/crew/apply`: public, .edu enforced on POST.
- `/admin/crew/*`: existing `@require_admin` pattern.

---

## Model Changes

### Changes to `User` model

```python
is_worker     = db.Column(db.Boolean, default=False)
worker_status = db.Column(db.String(20), nullable=True)
# None | 'pending' | 'approved' | 'rejected'
worker_role   = db.Column(db.String(20), nullable=True)
# None | 'driver' | 'organizer' | 'both'
```

**Migration required.** Three new nullable columns, no backfill.

### New model: `WorkerApplication`

```python
class WorkerApplication(db.Model):
    id          = db.Column(db.Integer, primary_key=True)
    user_id     = db.Column(db.Integer, db.ForeignKey('user.id'), unique=True)
    unc_year    = db.Column(db.String(20))
    role_pref   = db.Column(db.String(20))       # driver | organizer | both
    why_blurb   = db.Column(db.Text, nullable=True)
    applied_at  = db.Column(db.DateTime, default=datetime.utcnow)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    reviewed_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

    user        = db.relationship('User', foreign_keys=[user_id],
                                  backref='worker_application')
    reviewer    = db.relationship('User', foreign_keys=[reviewed_by])
```

### New model: `WorkerAvailability`

One record per worker per week. `week_start=None` for the initial application
submission. Weekly updates upsert by `(user_id, week_start)`.

```python
class WorkerAvailability(db.Model):
    id           = db.Column(db.Integer, primary_key=True)
    user_id      = db.Column(db.Integer, db.ForeignKey('user.id'))
    week_start   = db.Column(db.Date, nullable=True)
    # NULL = initial application | Monday date = weekly update

    # 14 boolean columns — True = available, False = blacked out
    mon_am = db.Column(db.Boolean, default=True)
    mon_pm = db.Column(db.Boolean, default=True)
    tue_am = db.Column(db.Boolean, default=True)
    tue_pm = db.Column(db.Boolean, default=True)
    wed_am = db.Column(db.Boolean, default=True)
    wed_pm = db.Column(db.Boolean, default=True)
    thu_am = db.Column(db.Boolean, default=True)
    thu_pm = db.Column(db.Boolean, default=True)
    fri_am = db.Column(db.Boolean, default=True)
    fri_pm = db.Column(db.Boolean, default=True)
    sat_am = db.Column(db.Boolean, default=True)
    sat_pm = db.Column(db.Boolean, default=True)
    sun_am = db.Column(db.Boolean, default=True)
    sun_pm = db.Column(db.Boolean, default=True)

    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)
    user         = db.relationship('User', backref='availabilities')

    __table_args__ = (
        db.UniqueConstraint('user_id', 'week_start',
                            name='uq_worker_avail_user_week'),
    )
```

14 explicit boolean columns so the spec #2 optimizer can query directly in SQL
(`WHERE mon_am = True`) without deserializing anything.

**Migration required.** New table.

### AppSetting seeds (no migration — key/value store)

Seed these on first run so spec #2 can read them without additional setup:

| Key | Default | Notes |
|-----|---------|-------|
| `crew_applications_open` | `'true'` | Pause applications toggle |
| `availability_deadline_day` | `'tuesday'` | Weekly submission deadline |
| `drivers_per_truck` | `'2'` | Always 2 |
| `organizers_per_truck` | `'2'` | Always 2 |
| `max_trucks_per_shift` | `'4'` | Optimizer upper bound |

---

## Template Changes

### New templates

**`templates/crew/apply.html`** — extends `layout.html`
- Job description hero: role, pay, timeframe, driver vs. organizer explained
- Application form with .edu client-side validation
- Includes `_availability_grid.html` partial
- Google OAuth option
- "Already have an account? Sign in first" link preserving redirect back

**`templates/crew/_availability_grid.html`** — partial, no layout
- 7×2 grid component, reused on apply and weekly update pages
- All cells default green on load
- Vanilla JS: click toggles cell class and updates corresponding hidden input
- Outputs 14 hidden inputs named `mon_am`, `mon_pm`, etc.
- Pre-fillable via Jinja2: partial accepts a dict of 14 booleans to set
  initial state (used for weekly update pre-fill)
- Mobile: 3-letter day abbreviations on narrow screens, 44px min tap targets

**`templates/crew/pending.html`** — extends `layout.html`
- "Application received" + what happens next

**`templates/crew/dashboard.html`** — extends `layout.html`
- Worker name, role badge, approval date
- Availability status card: current week's grid (read-only) or prompt to submit
- Placeholder sections for schedule and shift history (specs #2, #3)

**`templates/crew/availability.html`** — extends `layout.html`
- Deadline banner (Sunday–Tuesday) or locked message (Wednesday+)
- Includes `_availability_grid.html` pre-filled from last submission

### Modified templates

**`templates/admin.html`**
- "Crew" collapsible section (additive only)
- Pending applications table with expand + approve/reject
- Approve modal: role selector + confirm
- Approved workers sub-table

**`templates/layout.html`**
- Conditionally show "Crew Portal" nav link:
  `{% if current_user.is_worker and current_user.worker_status == 'approved' %}`

---

## Emails

### Approval email
- **Subject:** "You're on the Campus Swap Crew — here's what's next"
- **Content:** Role confirmed, link to `/crew`, submit availability by Tuesday
  each week, schedule posted by Thursday, $130/shift.
- Uses existing `wrap_email_template()` and `send_email()`.

### Rejection email (optional — admin toggles on reject dialog)
- **Subject:** "Campus Swap Crew — Application Update"
- **Content:** Brief, kind decline.

### Weekly reminder (spec #2)
- Cron Sunday evening to workers who haven't submitted for the upcoming week.

---

## Business Logic & Edge Cases

**.edu check:**
```python
email.strip().split('@')[-1].lower().endswith('.edu')
```
No dependencies. Accepts all .edu domains. `unc.edu`-only option behind
`AppSetting` flag if needed later — not built now.

**Duplicate application:**
- `unique=True` on `WorkerApplication.user_id` at DB level.
- Pre-check in route: pending → flash and redirect; approved → redirect to
  `/crew`; rejected → "applications closed for this account."

**Availability upsert:**
```python
existing = WorkerAvailability.query.filter_by(
    user_id=current_user.id, week_start=week_start
).first()
if existing:
    existing.mon_am = form_data['mon_am']
    # ... update all 14 fields
else:
    db.session.add(WorkerAvailability(...))
db.session.commit()
```
After deadline: POST returns 400, flash "Availability window is closed
for this week."

**Grid pre-fill:**
```python
last = WorkerAvailability.query.filter_by(user_id=current_user.id)\
    .order_by(WorkerAvailability.submitted_at.desc()).first()
# Pass as dict to template: {'mon_am': last.mon_am, ...}
```

**Non-.edu existing account:** Worker signs out, creates new .edu account,
applies. Old account history unaffected. Acceptable for v1.

**Worker who is also a seller/buyer:** Fully additive. All existing flows
unchanged. Nav shows Crew Portal link additively.

---

## Constraints — Do Not Touch

- Existing `User` model fields beyond the three new columns.
- Existing auth flows — apply form reuses them.
- Existing admin panel — Crew section is additive only.
- No new pip dependencies.

---

## Definition of Done

- [ ] `/crew/apply` loads publicly without login
- [ ] Non-.edu email rejected with clear field error
- [ ] Existing account holders apply without creating a duplicate user
- [ ] Grid defaults to all 14 cells green (fully available)
- [ ] Tapping a cell toggles between green and grey, updates hidden input
- [ ] Form POST correctly reads all 14 boolean fields
- [ ] `WorkerApplication` and initial `WorkerAvailability` records created
- [ ] Admin sees applications with availability grid on expand
- [ ] Approve modal sets `is_worker`, `worker_status`, `worker_role` correctly
- [ ] Approved worker receives email and can access `/crew`
- [ ] Pending applicant hitting `/crew` sees pending page
- [ ] Weekly form pre-fills from last submission
- [ ] Re-submission before deadline upserts, no duplicate record created
- [ ] Form locks after Tuesday deadline
- [ ] AppSetting keys for staffing ratios seeded
- [ ] Both migrations run cleanly
- [ ] All forms include `{{ csrf_token() }}`
- [ ] No hardcoded colors — CSS variables only
