# Bug Fix: Crew Shift View — Remove Auto-Refresh + Stale Stop Protection

**Type:** Bug Fix  
**Priority:** High (blocking live shift ops)  
**Status:** Ready to build  
**Scope:** Frontend + one backend guard — no model changes, no migration

---

## Goal

Two related fixes shipped together:

1. **Remove auto-refresh.** The 30-second `setInterval` polling loop on `/crew/shift/<id>` is silently wiping stop cards on mobile due to network blips on cellular. Replace it with a manual "↻ Sync" button drivers tap intentionally.

2. **Stale stop protection.** Without auto-refresh, two movers on the same truck may act on a stop that their partner already resolved. Add a backend conflict check to `crew_shift_stop_update` that rejects a write if the stop is already resolved, and surface a clear inline message so the driver knows to sync.

---

## Change 1 — Remove Auto-Refresh (`templates/crew/shift.html`)

**Remove entirely:**
- The `setInterval` block that fetches `/crew/shift/<id>/stops_partial` every 30 seconds and replaces `#stop-list` innerHTML.
- Any related variables (`refreshInterval`, `REFRESH_MS`, etc.).

**Add a "↻ Sync" button** in the in-progress state header, near the progress indicator ("X of Y stops done"). Only shown when the shift is in-progress (ShiftRun exists, `status != 'completed'`). Not shown in pre-start or past-shift states.

Button behavior:
- On tap: fetch `GET /crew/shift/<id>/stops_partial`, replace `#stop-list` innerHTML on success, do nothing on failure.
- While fetching: button shows "Syncing…" and is disabled to prevent double-taps.
- On success: button returns to normal — the updated list is the feedback, no toast needed.
- On failure (network error or non-OK response): button returns to normal, `#stop-list` is untouched.

```js
const syncBtn = document.getElementById('sync-stops-btn');

syncBtn.addEventListener('click', () => {
  syncBtn.disabled = true;
  syncBtn.textContent = 'Syncing…';

  fetch('/crew/shift/{{ shift.id }}/stops_partial')
    .then(r => {
      if (!r.ok) throw new Error('non-ok');
      return r.text();
    })
    .then(html => {
      if (html.trim().length > 0) {
        document.getElementById('stop-list').innerHTML = html;
      }
    })
    .catch(() => {
      // Do nothing — keep existing stop list intact
    })
    .finally(() => {
      syncBtn.disabled = false;
      syncBtn.textContent = '↻ Sync';
    });
});
```

**Button placement:** In the in-progress header bar, right-aligned or below the "X of Y stops done" progress line. Visually secondary — small outline style using `--text-muted`. Not a primary CTA.

---

## Change 2 — Stale Stop Protection (`app.py` + `templates/crew/shift.html`)

### Backend: `crew_shift_stop_update`

At the top of the route, before any writes, check whether the stop is already resolved:

```python
if pickup.status in ('completed', 'issue'):
    return jsonify({
        'error': 'already_resolved',
        'current_status': pickup.status
    }), 409
```

This must be the **first check** in the route, before status writes, `picked_up_at`, SMS hooks, token revocation, and no-show logic. A 409 Conflict — the request is valid but conflicts with current DB state. Nothing is written.

The existing revert route (`crew_shift_stop_revert`) is unaffected — reverting a resolved stop back to pending is an intentional action, not a conflict.

### Frontend: stop card conflict handling (`templates/crew/shift.html`)

The stop card JS currently POSTs to `crew_shift_stop_update` and handles success by updating the card UI or reloading. It needs to handle a 409 response distinctly from other errors.

When a 409 is received:

1. **Do not show a generic error.** Show an inline message directly on the affected stop card:
   - If `current_status` is `'completed'`: *"Already marked complete by your partner — tap ↻ Sync to update."*
   - If `current_status` is `'issue'`: *"Already flagged by your partner — tap ↻ Sync to update."*

2. **Visually dim or disable the action buttons** on that stop card (Complete / Flag Issue) so the driver can't re-submit while stale. The message and disabled state persist until the driver taps Sync, at which point the refreshed partial replaces the card with its true current state.

3. **Do not modify any other stop cards.** Only the card that got the 409 is affected.

```js
// Pattern to follow — inside the existing stop update fetch handler
.then(r => {
  if (r.status === 409) {
    return r.json().then(data => {
      const label = data.current_status === 'completed'
        ? 'Already marked complete by your partner'
        : 'Already flagged by your partner';
      showStopConflict(pickupId, label); // updates that card's UI
      throw new Error('conflict'); // skip success path
    });
  }
  if (!r.ok) throw new Error('non-ok');
  return r.json();
})
```

`showStopConflict(pickupId, label)` should:
- Find the stop card by `data-pickup-id` attribute.
- Inject the conflict message below the stop address in muted amber text (use `--warning` or `--accent` CSS variable).
- Disable the Complete and Flag Issue buttons on that card.
- Add a note: *"↻ Sync to update"* as a small tap target that fires the same sync fetch as the Sync button.

---

## What Is NOT Changing

- `GET /crew/shift/<id>/stops_partial` route and `crew/stops_partial.html` template — kept as-is.
- `crew_shift_stop_revert` — intentional revert of a resolved stop, no conflict check needed.
- Pre-start state, past-shift state — no Sync button, no conflict handling needed there.
- End Shift flow — untouched.
- No model changes, no migration.

---

## Verification

### Auto-Refresh Removal
- [ ] Open shift view in-progress on mobile — no auto-refresh occurs (watch network tab for 30s, confirm no periodic requests to `stops_partial`).
- [ ] "↻ Sync" button visible in in-progress state.
- [ ] Tap Sync — stop list reloads with fresh data.
- [ ] With airplane mode on, tap Sync — button shows "Syncing…" then returns to normal, stop list unchanged.
- [ ] Pre-start state — no Sync button visible.
- [ ] Past-shift state — no Sync button visible.
- [ ] Two movers on same truck: Mover A completes a stop, Mover B taps Sync — stop appears completed on B's view.

### Stale Stop Protection
- [ ] Mover A completes stop 2. Mover B (stale view) taps Complete on stop 2 — POST returns 409, inline conflict message appears on that card, buttons disabled. No DB change.
- [ ] Mover A flags stop 2 as issue. Mover B taps Complete on stop 2 — 409, message reads "Already flagged by your partner".
- [ ] Mover A completes stop 2. Mover B taps Flag Issue on stop 2 — 409, message reads "Already marked complete by your partner". No no-show email queued, no token extended.
- [ ] After conflict message appears, Mover B taps "↻ Sync to update" on the card — stop card updates to show resolved state, conflict message clears.
- [ ] Mover A completes stop 2. Mover B taps Revert on stop 2 (if they somehow see it) — revert succeeds as normal (no 409 on revert).
- [ ] Normal single-mover flow unaffected: complete, flag, revert all work as before.
