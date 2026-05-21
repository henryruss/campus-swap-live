# Mini-Spec: Campus Director Role Switcher

**Status:** Ready for Claude Code
**Depends on:** feature_campus_director_role.md (complete)
**Estimated complexity:** Small — one route change, one nav component, no model changes

---

## Goal

Campus directors who are also sellers need a way to access both the seller
dashboard and the admin panel. Currently `/dashboard` is seller-only with no
awareness of the campus director role. This adds a role switcher to the nav
and fixes the dashboard redirect logic.

---

## Dashboard Redirect Logic

Modify the `dashboard` route (`GET /dashboard`) to detect campus directors
and default them to the right context on first load:

```python
if current_user.is_campus_director and not current_user.is_seller:
    # CD with no items — send straight to admin
    return redirect(url_for('admin_ops'))

if current_user.is_campus_director and current_user.is_seller:
    # CD who is also a seller — check for explicit preference in session
    if session.get('cd_view') == 'seller':
        pass  # fall through to normal dashboard render
    else:
        return redirect(url_for('admin_ops'))
```

`current_user.is_seller` is already a field on `User`. A campus director with
no items and `is_seller=False` goes straight to admin. A campus director who
is also a seller defaults to admin unless they've explicitly switched to seller
view (stored in `session['cd_view']`).

**Note:** The tutorial gate in `require_ops_access` still fires before any of
this logic for campus directors who haven't completed the tutorial. No change
needed there.

---

## Role Switcher — Nav Component

Add a role switcher pill to `layout.html`, visible only when
`current_user.is_campus_director and current_user.is_seller` (both must be
true — no point showing a switcher if they only have one relevant role).

### Placement

Desktop: in the header, to the left of the user icon dropdown. Same row as
the main nav links.

Mobile: inside the slide-in hamburger menu, below the Dashboard link and
above Account Settings.

### Appearance

```html
<!-- Rendered only when: current_user.is_campus_director and current_user.is_seller -->
<div class="role-switcher">
  <a href="/switch-role/seller"
     class="role-switcher-btn {% if not in_admin_context %}active{% endif %}">
    👤 Seller
  </a>
  <a href="/switch-role/admin"
     class="role-switcher-btn {% if in_admin_context %}active{% endif %}">
    ⚙ Admin
  </a>
</div>
```

`in_admin_context` is a template variable injected by a context processor:
```python
@app.context_processor
def inject_admin_context():
    in_admin = (
        request.path.startswith('/admin') or
        request.path.startswith('/crew')
    )
    return {'in_admin_context': in_admin}
```

### Styling

```css
.role-switcher {
  display: inline-flex;
  border: 1.5px solid var(--primary);
  border-radius: 20px;
  overflow: hidden;
  font-size: 0.8rem;
}

.role-switcher-btn {
  padding: 4px 12px;
  color: var(--primary);
  text-decoration: none;
  transition: background 0.15s;
}

.role-switcher-btn.active {
  background: var(--primary);
  color: white;
}

.role-switcher-btn:hover:not(.active) {
  background: var(--bg-cream);
}
```

---

## Switch Routes

Two lightweight routes that set the session flag and redirect:

| Method | Path | Function | Description |
|---|---|---|---|
| `GET` | `/switch-role/seller` | `switch_role_seller` | Sets `session['cd_view'] = 'seller'`, redirects to `/dashboard` |
| `GET` | `/switch-role/admin` | `switch_role_admin` | Sets `session['cd_view'] = 'admin'`, redirects to `/admin/ops` |

Both routes: `@login_required`. If called by a non-campus-director, redirect
to `/dashboard` silently (no error needed — they'd never see the switcher UI).

---

## Template Changes

| Template | Change |
|---|---|
| `layout.html` | Add role switcher pill in desktop nav and mobile menu. Conditionally rendered for `is_campus_director and is_seller` only. |

No other template changes. The admin panel templates are unchanged — the
switcher in `layout.html` is present on all pages that extend it, which
includes both `/dashboard` and all `/admin/*` pages.

---

## Model Changes

None. No migration needed. `session['cd_view']` is Flask session only.

---

## Constraints — Do Not Touch

- Seller dashboard template and logic unchanged
- Admin panel templates unchanged
- Tutorial gate logic unchanged
- `is_admin` and `is_super_admin` nav behavior unchanged — they already have
  the "Admin" link in the user dropdown and don't need the role switcher

---

## Definition of Done

- [ ] Campus director with `is_seller=False` visiting `/dashboard` is redirected
  to `/admin/ops`
- [ ] Campus director with `is_seller=True` visiting `/dashboard` is redirected
  to `/admin/ops` by default
- [ ] Campus director with `is_seller=True` who clicks "Seller" in the switcher
  lands on `/dashboard` and stays there
- [ ] Role switcher pill visible in desktop nav for campus directors who are
  also sellers
- [ ] Role switcher pill visible in mobile menu for campus directors who are
  also sellers
- [ ] Active state highlights the correct side based on current URL context
- [ ] "Admin" side of switcher takes user to `/admin/ops`
- [ ] "Seller" side of switcher takes user to `/dashboard`
- [ ] Non-campus-directors see no role switcher at all
- [ ] Campus directors who are not sellers see no role switcher
  (straight redirect to admin, no toggle needed)
- [ ] Existing admin (`is_admin`) nav behavior completely unchanged
