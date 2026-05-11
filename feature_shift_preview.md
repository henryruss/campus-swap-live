# Mini-Spec: Worker Shift Preview (Read-Only)

**Status:** Ready for implementation
**Dependency:** Spec #3 (complete)

---

## Goal

Workers are currently redirected away from `/crew/shift/<id>` if the shift date is in the future and no `ShiftRun` exists. This means they can't see who they're working with, how many stops are assigned, or any other shift context until the morning of. Allowing a read-only preview ahead of time reduces day-of confusion and helps workers mentally prepare.

---

## UX Flow

1. Worker taps a future shift from My Schedule on `/crew` → navigates to `/crew/shift/<id>`.
2. Route detects: shift is in the future, no `ShiftRun` exists → renders the page in **preview mode** instead of redirecting.
3. Preview mode shows:
   - Shift header: day, date, slot (AM/PM), truck number, co-worker name(s) on the same truck.
   - A prominent info banner: **"Preview — shift is on [Weekday, Month D]. Actions are disabled until the day of."**
   - Stop list (if stops have been assigned): seller name, address, item count, access type badge (stairs/elevator). Photo strip omitted — not relevant pre-shift.
   - If no stops yet: "Stops haven't been assigned yet — check back closer to your shift date."
   - **All action buttons hidden:** no Start Shift, no Completed/Issue buttons, no End Shift.
4. Auto-refresh (`setInterval`) is disabled in preview mode — no need to poll for updates on a future shift.
5. On the day of the shift, the page transitions to normal pre-start or in-progress behavior (no change to existing logic).

### Edge Cases

- **Worker not assigned to shift** → existing 403, unchanged.
- **Past shift** → existing behavior (retroactive complete, etc.), unchanged.
- **Shift is today but ShiftRun doesn't exist yet** → existing pre-start state, unchanged.
- **Shift is today and ShiftRun exists** → existing in-progress state, unchanged.
- **No stops assigned on a future shift** → show "check back" message (same copy as today's pre-start "no stops" state).
- **Organizer-role assignment on a future shift** → same preview treatment. Organizers currently link to `crew_intake_shift`; their My Schedule links don't point here. This path is mover-only, no change needed for organizers.

---

## New Routes

None. This is a behavior change inside the existing `GET /crew/shift/<shift_id>` → `crew_shift_view` route.

---

## Model Changes

None. No migration needed.

---

## Template Changes

### `templates/crew/shift.html`

Add a new top-level conditional state: `is_preview`.

**Route passes** `is_preview=True` when `shift_date > today_eastern` and `shift.run is None`.

**Changes to the template:**

1. **Preview banner** — render above the stop list when `is_preview`:
   ```
   [info icon]  Preview — your shift is on [Weekday, Month D].
   Actions are available on the day of the shift.
   ```
   Style with `--bg-cream` background, `--primary` border-left, same pattern as the existing "not today" warning banner.

2. **Start Shift button** — already conditionally rendered (`if not shift.run and stops`). In preview mode, hide it entirely (wrap the existing condition to also exclude `is_preview`).

3. **Stop cards** — render in preview mode (same layout as pre-start: name, address, item count, access badge). The Completed/Issue action buttons are already absent in pre-start state — this is the same state, so no additional hiding needed. Confirm that action buttons are gated on `shift.run` existing, which preview mode satisfies.

4. **Auto-refresh script** — the `setInterval` that polls `/crew/shift/<id>/stops_partial` should be suppressed when `is_preview`. Wrap the JS block in `{% if not is_preview %}`.

5. **Photo strip** — if currently shown in pre-start state, suppress in preview mode via `{% if not is_preview %}`. (Check current template — if it's already gated on `shift.run`, no change needed.)

---

## Business Logic

- `is_preview` is `True` when **all three** conditions hold:
  - `shift_date > _today_eastern()` (strictly future — not today)
  - `shift.run is None` (no ShiftRun started)
  - Worker is assigned to this shift (existing 403 check runs first, unchanged)
- The `is_preview` flag is computed in `crew_shift_view` and passed to the template. No DB writes occur on this path.
- The existing redirect (`return redirect(url_for('crew_dashboard'))`) that fires for future shifts is **removed** and replaced with the `is_preview=True` render path.

---

## Constraints

- Do not touch `crew_shift_start`, `crew_shift_end`, `crew_shift_stop_update`, or any POST routes — they already block future shifts independently.
- Do not change behavior for today's shifts or past shifts.
- Do not change the 403 for workers not assigned to the shift.
- The existing "not today" warning banner (shown when `shift_date != today` but shift is accessible) can be **removed** — it was there to warn about accidental early access, which preview mode handles more explicitly. Confirm in template before removing; if removal feels risky, suppressing it when `is_preview` is also acceptable.
- No new routes, no DB changes, no migration.
