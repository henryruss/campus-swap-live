# Feature Spec: Campus Director Role

**Status:** Ready for Claude Code
**Depends on:** Admin UI Redesign (signed off 2026-04-15)
**Estimated complexity:** Small — model change + permission gates + minor UI removals

---

## Goal

Introduce a `is_campus_director` role that gives a trusted per-school operator access to exactly the admin features they need to run daily pickup operations — and nothing more. This is the foundation for the upcoming tutorial system, and the first step in scaling the admin panel from a founder-only tool to a multi-school platform.

Simultaneously, remove two vestigial UI elements (Auto-Assign button, Add Truck button) that are unused or broken at current operating scale.

---

## Model Changes

### `User` — add two fields

```python
is_campus_director = db.Column(db.Boolean, default=False, server_default='0', nullable=False)
campus_director_school = db.Column(db.String(100), nullable=True)
```

`campus_director_school` is set by the super admin at grant time (required — see Settings section). Nullable so the column addition doesn't require backfilling existing rows.

**Migration name:** `add_campus_director_role`

No other model changes. `is_admin` and `is_super_admin` are untouched.

### Role hierarchy (for reference — not a DB change)

| Flag | Who has it | What it means |
|---|---|---|
| `is_super_admin` | Founders only | Full access — Settings, user management, DB reset, mass email |
| `is_admin` | Co-founder, ops leads | Inventory approvals, payouts, seller management, full ops |
| `is_campus_director` | Per-school campus directors | Ops, Schedule, Crew only — no financial, no seller browsing, no settings |

These flags are independent booleans. A super admin does not also need `is_campus_director`. Access checks work as described in the Auth Guards section below.

---

## Auth Guards

### New decorator / helper

Add a `require_ops_access` decorator (or inline check) used on routes that campus directors are allowed to access. Logic:

```python
def require_ops_access(f):
    # Passes if: is_super_admin OR is_admin OR is_campus_director
    # Fails → 403 (not redirect, consistent with existing partial-route behavior)
```

Routes that are **already** gated by `is_admin` or `is_super_admin` do not change their existing decorators. The campus director gates are additive — applied to routes currently inaccessible to campus directors.

### Route access matrix

| Route | Current gate | Campus director access |
|---|---|---|
| `GET /admin/ops` | `is_admin` | ✅ Yes — extend check |
| `GET /admin/ops/truck-detail` | `is_admin` | ✅ Yes — extend check |
| `POST /admin/routes/seller/<id>/assign` | `is_admin` | ✅ Yes — extend check |
| `POST /admin/crew/shift/<id>/order` | `is_admin` | ✅ Yes — extend check |
| `POST /admin/crew/shift/<id>/notify` | `is_admin` | ✅ Yes — extend check |
| `GET /admin/schedule` | `is_super_admin` | ✅ Yes — extend check |
| `GET /admin/schedule/<week_id>` | `is_super_admin` | ✅ Yes — extend check |
| `POST /admin/settings/generate-shifts` | `is_super_admin` | ✅ Yes — extend check |
| `GET /admin/crew` | `is_admin` | ✅ Yes — extend check |
| `POST /admin/crew/approve/<user_id>` | `is_admin` | ✅ Yes — extend check |
| `POST /admin/crew/reject/<user_id>` | `is_admin` | ✅ Yes — extend check |
| `GET /admin/crew/shift/<id>/ops` | `is_admin` | ✅ Yes — extend check |
| `GET /admin/items` | `is_admin` | ❌ No |
| `GET /admin/sellers` | `is_admin` | ❌ No |
| `GET /admin/payouts` | `is_admin` | ❌ No |
| `GET /admin/settings` | `is_super_admin` | ❌ No |
| All mass email, user management, DB reset routes | `is_super_admin` | ❌ No |

**Implementation note:** For each ✅ route, the auth check becomes:
```python
if not (current_user.is_admin or current_user.is_super_admin or current_user.is_campus_director):
    abort(403)
```
Routes currently using `@require_super_admin` decorator (Schedule, generate-shifts) get an additional campus-director pass-through at the start of the function body, since modifying the decorator itself would broaden its meaning globally.

---

## Template Changes

### `admin/admin_layout.html` — sidebar visibility

The sidebar currently renders all tabs for any admin. Update tab rendering to conditionally hide tabs a campus director cannot access:

```
Ops tab      → visible to: is_admin, is_super_admin, is_campus_director
Items tab    → visible to: is_admin, is_super_admin only
Payouts tab  → visible to: is_admin, is_super_admin only
Sellers tab  → visible to: is_admin, is_super_admin only
Crew tab     → visible to: is_admin, is_super_admin, is_campus_director
Schedule tab → visible to: is_super_admin, is_campus_director
Settings tab → visible to: is_super_admin only
```

Pass a context variable `sidebar_role` (or use `current_user` directly in the template via `flask_login`'s `current_user` — already available) to drive `{% if %}` conditions on each tab `<li>`.

### `admin/ops.html` — hide Auto-Assign button

Add `style="display: none"` to the Auto-Assign button in the unassigned panel. The button, its form, and the associated JS fetch call all remain in the template — just hidden. Route `POST /admin/routes/auto-assign` is untouched.

### `admin/ops.html` — hide Add Truck button

Add `style="display: none"` to the Add Truck button in the ops top bar. Button and form remain in the template. Route `POST /admin/crew/shift/<id>/add-truck` is untouched.

### `admin/settings.html` — grant/revoke campus director

Add a new collapsible section to the Settings page (super admin only, consistent with the rest of the page) titled **"Campus Directors"**.

**Section contents:**
- Table of current campus directors: name, email, school, date granted, Revoke button
- "Grant access" form: email input + school name input (required) → lookup existing user → grant role
- If email not found: flash error "No account with that email exists. The user must sign up first."
- If user is already `is_admin` or `is_super_admin`: flash error "This user already has full admin access."

**Grant flow:**
- `POST /admin/user/grant-campus-director` — looks up user by email, sets `is_campus_director=True` and `campus_director_school` from form input, flashes success, redirects to `#campus-directors` anchor
- `POST /admin/user/revoke-campus-director` — sets `is_campus_director=False`, clears `campus_director_school=None`, flashes success, redirects back

Both routes: super admin only.

---

## New Routes

| Method | Path | Function | Description |
|---|---|---|---|
| `POST` | `/admin/user/grant-campus-director` | `admin_grant_campus_director` | Set `is_campus_director=True` by email lookup. Super admin only. |
| `POST` | `/admin/user/revoke-campus-director` | `admin_revoke_campus_director` | Set `is_campus_director=False` by user ID. Super admin only. |

---

## Business Logic & Edge Cases

**Campus director cannot elevate themselves.** The grant/revoke routes are super-admin-only. A campus director cannot grant campus director access to anyone else.

**Granting to a non-existent user.** Flash error, no DB write. The user must create their account first; this avoids orphaned grants.

**Revoking from someone with `is_admin`.** Not possible via these routes — `is_admin` users never appear in the campus director table. The admin user management section (existing) handles full admin roles.

**Login redirect.** `@login_required` remains as the outermost guard on all admin routes. Campus directors who are not logged in hit the normal login flow.

**Campus director landing page.** A campus director navigating to `/admin` gets the standard `GET /admin` → `302 /admin/ops` redirect (already in place). Their first page is Ops, which is correct.

**`admin_layout.html` base template access.** Any route that renders `admin_layout.html` must pass the check above or the user gets a 403 before the template renders. The sidebar visibility is cosmetic reinforcement, not the security boundary — the route-level check is the real gate.

---

## Constraints — Do Not Touch

- `is_admin` and `is_super_admin` checks on all existing routes remain exactly as-is. This spec only adds a third pass-through; it never removes existing gates.
- `@require_super_admin` decorator definition is unchanged.
- Auto-assign button and route are both preserved — button is CSS-hidden only.
- Add Truck button and route are both preserved — button is CSS-hidden only.
- All Stripe, payout, and seller-financial routes are untouched.
- No changes to `layout.html` (the public-facing base template).

---

## Definition of Done

- [ ] Migration `add_campus_director_role` applies cleanly
- [ ] `User.is_campus_director` column exists, defaults False
- [ ] `User.campus_director_school` column exists, nullable
- [ ] A campus director account can log in and reach `/admin/ops`
- [ ] A campus director sees only: Ops, Crew, Schedule in the sidebar
- [ ] Items, Sellers, Payouts tabs are absent from sidebar for campus director
- [ ] Settings tab is absent from sidebar for campus director
- [ ] Auto-Assign button is hidden (display:none) on ops page for all roles
- [ ] Add Truck button is hidden (display:none) on ops page for all roles
- [ ] Campus director can assign a seller to a route
- [ ] Campus director can order a route
- [ ] Campus director can notify sellers
- [ ] Campus director can view the Schedule tab and generate shifts
- [ ] Campus director can view Crew tab and approve/reject applications
- [ ] Campus director attempting to visit `/admin/items` gets 403
- [ ] Campus director attempting to visit `/admin/sellers` gets 403
- [ ] Campus director attempting to visit `/admin/settings` gets 403
- [ ] Super admin can grant campus director access with school name via Settings page
- [ ] Campus directors table in Settings shows name, email, school, date granted
- [ ] Super admin can revoke campus director access (clears school field)
- [ ] Granting to nonexistent email shows error flash, no DB write
- [ ] Existing `is_admin` / `is_super_admin` access is completely unchanged
