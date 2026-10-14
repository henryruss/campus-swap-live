# Fix Spec: Remove Worker — Admin Crew Panel

## Goal

Allow admin to revoke a worker's crew status from the Crew HQ panel.
Keeps the user account intact. Automatically removes all their
`ShiftAssignment` records. Requires a confirmation dialog before executing.

---

## New Route

| Method | Path | Function | Description |
|--------|------|----------|-------------|
| `POST /admin/crew/remove/<user_id>` | `admin_crew_remove` | Revoke worker status + delete all ShiftAssignments |

### Logic

```python
@app.route('/admin/crew/remove/<int:user_id>', methods=['POST'])
@login_required
def admin_crew_remove(user_id):
    if not current_user.is_admin:
        abort(403)

    worker = User.query.get_or_404(user_id)

    # Guard: must be an approved worker
    if not worker.is_worker or worker.worker_status != 'approved':
        flash('User is not an active worker.', 'warning')
        return redirect(url_for('admin_crew_panel'))

    # Delete all ShiftAssignments in FK-safe order
    # (ShiftAssignment has no child FKs, so direct delete is safe)
    db.session.execute(
        delete(ShiftAssignment).where(ShiftAssignment.worker_id == worker.id)
    )

    # Revoke worker status (keep user account)
    worker.is_worker = False
    worker.worker_status = 'rejected'  # prevents re-appearing in pending queue
    worker.worker_role = None

    db.session.commit()

    flash(f'{worker.full_name} has been removed from the crew.', 'success')
    return redirect(url_for('admin_crew_panel'))
```

**Notes:**
- `worker_status = 'rejected'` is intentional — it prevents the account
  from showing up in the pending applications queue if the same email
  ever hits `/crew/apply` again. If you want to re-hire them later,
  approve them again via the normal flow.
- Uses bulk SQL DELETE (`delete(ShiftAssignment).where(...)`) per the
  project rule on bulk deletes — avoids `StaleDataError` on FK chains.
- No email sent on removal.

---

## Template Change: `admin/crew.html`

Add a "Remove" button to each row in the **Approved Workers** table.

The confirmation dialog is a native `<details>`/`<summary>` inline
confirmation — no JS modal needed. Pattern:

```html
<!-- In each approved worker row -->
<td>
  <details class="inline-confirm">
    <summary class="btn btn-danger-outline btn-sm">Remove</summary>
    <div class="inline-confirm-body">
      <p>Remove <strong>{{ worker.full_name }}</strong> from the crew?
         This will unassign them from all shifts.</p>
      <form method="POST"
            action="{{ url_for('admin_crew_remove', user_id=worker.id) }}">
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
        <button type="submit" class="btn btn-danger btn-sm">
          Yes, remove
        </button>
        <span class="btn-link" onclick="this.closest('details').removeAttribute('open')">
          Cancel
        </span>
      </form>
    </div>
  </details>
</td>
```

Add a new `SHIFTS ASSIGNED` column to the approved workers table so admin
can see at a glance how many assignments will be removed:

```python
# In admin_crew_panel route, for each worker:
worker._assignment_count = ShiftAssignment.query.filter_by(
    worker_id=worker.id
).count()
```

Display as e.g. `3 shifts` in muted text. If 0, show `—`.

---

## CSS (add to `static/style.css`)

```css
.inline-confirm {
  display: inline-block;
  position: relative;
}

.inline-confirm[open] summary {
  opacity: 0.5;
  pointer-events: none;
}

.inline-confirm-body {
  position: absolute;
  right: 0;
  top: 100%;
  z-index: 10;
  background: var(--bg-white, #fff);
  border: 1px solid var(--border-color, #e0e0e0);
  border-radius: 8px;
  padding: 12px 16px;
  min-width: 260px;
  box-shadow: 0 4px 12px rgba(0,0,0,0.12);
  margin-top: 4px;
}

.inline-confirm-body p {
  margin: 0 0 10px;
  font-size: 14px;
  color: var(--text-main);
}
```

---

## Constraints

- Do not touch `admin_crew_approve` or `admin_crew_reject`.
- Do not delete the `User` record or any `WorkerApplication` record.
- Do not delete `WorkerAvailability` records — they're harmless to keep
  and useful if the worker is ever re-hired.
- No migration needed.
- `is_super_admin` not required — any admin can remove a worker.
