# Claude Code Instructions — Campus Swap

## Before Every Session
Read these files in order before writing any code:
1. `CODEBASE.md` — full route map, models, templates, existing patterns
2. `OPS_SYSTEM.md` — ops platform master reference (glossary, staffing model, roadmap)
3. `HANDOFF.md` — current build state, what's done, what changed from specs
4. The active spec file for this session (told to you at session start)

Never assume a route, model field, or template doesn't exist — check CODEBASE.md first.

---

## Rules That Never Change
- Server-rendered only. No React. Vanilla JS for interactivity. Fetch POST is allowed for in-place saves that would cause disruptive reloads — route still does all DB writes server-side, returns JSON.
- All new templates extend `layout.html` (seller/buyer pages) or `admin_layout.html` (admin pages) or the crew layout (crew pages). Check CODEBASE.md for which to use.
- Never hardcode colors — use CSS variables from `static/style.css`.
- All forms include `{{ csrf_token() }}`.
- Database changes always get a Flask-Migrate migration (`flask db migrate -m "description"` then `flask db upgrade`).
- Never pass structured data to JS via inline `tojson` in `onclick` attributes. Use `data-*` attributes instead.
- Day/time logic uses Eastern time (`_now_eastern()` / `_today_eastern()`). Timestamps stored in UTC.
- Stripe webhook is the only source of truth for payment state. Never mark items sold based on URL params.
- Payout amounts always computed at runtime via `_get_payout_percentage(item)`. Never hardcode tier logic.
- Bulk SQL DELETE for deep FK chains — use `db.session.execute(delete(Model).where(...))` in FK dependency order to avoid StaleDataError.
- Ask before making any decision not covered by the active spec.

---

## Auth Guards — Use the Right One
- `@login_required` — any logged-in user
- `current_user.is_admin` — admin panel access
- `@require_super_admin` — super admin only
- `require_crew()` — approved workers (call inside route, not a decorator)
- `_has_ops_access()` — admins AND campus directors (`is_admin` OR `is_campus_director`). Use this for all ops, scheduling, storage audit, and photo-replace routes.
- Role-specific crew gating checks `ShiftAssignment.role_on_shift` inside the route — never `User.worker_role`.

---

## Database — Postgres Everywhere
Local and production both run PostgreSQL. SQLite is gone.

- Local DB: `campusswap` on `postgresql://henryrussell@localhost:5432/campusswap`
- `DATABASE_URL` in `.env` points to local Postgres
- Never write SQLite-specific migration syntax (`batch_alter_table`, `TINYINT`, string defaults on boolean columns). Write standard Postgres-compatible Alembic migrations.
- `session_options={'expire_on_commit': False}` is set on the SQLAlchemy session — do not remove it.

### Deploying Migrations to Production (Render)
1. Run `flask db migrate -m "description"` locally to generate the migration file
2. Commit and push — Render deploys automatically
3. In the Render shell, run `flask db upgrade`
4. Never run `db.create_all()` in production — it bypasses migration tracking
5. Never modify the production DB directly via psql

---

## Things That Can Work Locally But Fail in Production
Check these whenever something passes locally but errors on Render:

1. **Missing env vars** — check Render → Environment tab. `STRIPE_SECRET_KEY`, `RESEND_API_KEY`, `GOOGLE_CLIENT_ID`, `STRIPE_WEBHOOK_SECRET` etc. must all be present.
2. **File storage paths** — locally photos go to `static/uploads/`. On Render they go to `/var/data/` (persistent disk). Always use `url_for('uploaded_file', filename=...)` to serve photos. Never hardcode paths.
3. **Email sending** — email calls that silently fail locally (no API key) throw in production. Wrap Resend calls in try/except and log failures.
4. **Data edge cases** — production has hundreds of real items with null fields, unusual characters, and states that seed data never creates. Don't assume fields are always populated just because they are in dev.
5. **Alembic out of sync** — if a migration fails on Render with "table already exists" or "column already exists", the fix is `flask db stamp head` in the Render shell (marks DB as current without running migrations), then investigate why the schema drifted.

---

## Current Model Notes (as of May 2026)

### Fields Added Recently — Know These Exist
- `InventoryItem.storage_row` — **6-value enum, not free text**. Valid values: `back_left`, `middle_left`, `front_left`, `back_right`, `middle_right`, `front_right`. Enforced via `_validate_storage_zone(value)` helper in `app.py`. Any write to this field must go through that helper.
- `InventoryItem.placement_status` — `None` | `'placed'` | `'not_picked_up'`. Set by driver placement flow. Never set by admin or seller routes.
- `InventoryItem.needs_photo_refresh` — Boolean, default False. Set to True when crew replaces a photo via the audit tool. Never set by seller upload flow.
- `User.is_campus_director` — Boolean. Campus directors have ops access but are not `is_admin`. Always use `_has_ops_access()` for routes they need.

### Deprecated — Do Not Build On
- **Organizer role** — `role_on_shift == 'organizer'` is not used in active flows. No new routes should gate on it. The organizer intake page (`/crew/intake/<shift_id>`) is deprecated — do not add features to it.
- `User.worker_role` — legacy field, not used for route gating. Role is determined by `ShiftAssignment.role_on_shift`.
- `InventoryItem.collection_method` — retained in DB but does not drive any logic. Never use it for payout math.
- `InventoryItem.dropoff_pod` — deprecated, pod option removed.

---

## Long-Term Vision — Build With This in Mind
Campus Swap is expanding from one school (UNC Chapel Hill) to ~20 schools in the next year, and eventually hundreds. Every architectural decision should avoid making multi-school support harder.

**The multi-school model:**
- Each school is a distinct entity with its own sellers, items, shifts, workers, and campus director
- A campus director manages their school's full operation independently — scheduling, drivers, storage, payouts
- Henry (super admin) can see and manage all schools from one dashboard
- The buyer-facing shop is one combined marketplace (like Facebook Marketplace) where buyers filter by school/location — not separate storefronts per school

**What this means for new code:**
- Never hardcode "UNC" or any school-specific assumption into routes, templates, or business logic
- Any new model that is school-specific should be designed to eventually have a `school_id` foreign key — even if that field doesn't exist yet, don't build in ways that would make adding it impossible
- Admin views that show "all items" or "all sellers" will eventually need school-scoped filtering — build with that in mind
- The super admin layer (Henry's view) and the campus director layer (per-school ops) are distinct permission levels that will diverge further over time

**Planned features (not yet specced — do not build without a spec):**
- Multi-school data model (`School` table, `school_id` on User/Item/Shift)
- Super admin dashboard across all schools
- AI-assisted item processing: auto-pricing, description generation, photo background replacement
- Automated Facebook Marketplace posting
- SMS notifications via Twilio (depends on Spec #6 + #8)
- Seller rescheduling self-serve flow (Spec #8)
- Seller progress tracker (Spec #7)
- Payout reconciliation tool (Spec #5 — spec written, not yet built)
- Crew member onboarding tutorial (spec not yet written)

---

## Ops Spec Status (Quick Reference)
| Spec | Status |
|------|--------|
| #1 Worker Accounts | ✅ Complete |
| #2 Shift Scheduling | ✅ Complete |
| #3 Driver Shift View | ✅ Complete |
| #4 Organizer Intake | ✅ Complete (page deprecated) |
| Referral Program | ✅ Complete |
| Storage Audit Tool | ✅ Complete |
| Driver Placement Flow | ✅ Complete |
| Inventory Photo Refresh | ✅ Complete |
| #5 Payout Reconciliation | 🔲 Spec written, not built |
| #6 Route Planning | ✅ Complete |
| #7 Seller Progress Tracker | ✅ Complete |
| #8 Seller Rescheduling | ✅ Complete |
| #9 SMS Notifications | ✅ Complete |
| Crew Tutorial | 🔲 Not yet specced |
| Multi-School Support | 🔲 Not yet specced (major) |
