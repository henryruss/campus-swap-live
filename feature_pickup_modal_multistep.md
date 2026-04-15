# Feature Spec: Pickup Modal — Multi-Step Redesign

**Status:** Ready for implementation
**Scope:** UI-only refactor. No new routes, no new model fields, no migration required (one minor model change: relax `has_pickup_location` floor requirement).

---

## Goal

The current pickup week & address modal is a single tall scroll that's hard to navigate on mobile. Convert it to a 3-screen card wizard matching the onboarding/add-item step pattern — same visual language, same JS step-advance pattern already in the codebase. Reduce cognitive load and viewport overflow without losing any data.

---

## UX Flow

The modal opens as today (triggered by clicking the Pickup Window stats cell or "Set now →"). Instead of one tall form, it renders a card with a step indicator and Back/Next buttons.

### Screen 1 — When

**Header:** "When should we pick up?"
**Subheader:** "We'll route around your week and text you a specific window."

Week selector — three equal cards side by side (or stacked on very narrow mobile):
- **Week 1** — Apr 27 – May 3
- **Week 2** — May 4 – May 10
- **Week 3** — May 11 – May 17

Selecting a week reveals the time preference row below (same reveal behavior as today):
- **Morning** (9am–1pm)
- **Afternoon** (1pm–5pm)

Week card uses the existing `.pickup-week-opt` selected state. Time preference uses the existing `.pickup-time-opt` pattern.

Validation: if a week is selected, time preference is required before advancing. Week selection itself is optional (seller can skip the whole modal with no changes — just close it).

**Next →** advances to Screen 2. If returning to edit an existing value, pre-select the current `pickup_week` and `pickup_time_preference`.

---

### Screen 2 — Where & How to Reach You

**Header:** "Where are you located?"
**Subheader:** "Helps our movers find you quickly."

Location type — three full-width buttons (existing `.pickup-loc-type-btn` pattern):
- 🏫 On campus (UNC dorm)
- 🏢 Off-campus apartment complex
- 🏠 Other address

Branch fields appear below based on selection, identical to current modal:
- **On campus:** dorm dropdown + room number input
- **Off-campus complex:** building dropdown (OFF_CAMPUS_COMPLEXES) + unit number input
- **Other address:** Google Maps autocomplete (existing behavior)

**Access type — three equal side-by-side cards (new layout):**

```
[ 🛗 Elevator ]  [ 🪜 Stairs only ]  [ ↓ Ground floor ]
```

These replace the current vertical `.access-type-card` stack. Use the same `.access-type-card` class and `is-selected` toggle pattern — just lay them out in a CSS grid: `grid-template-columns: 1fr 1fr 1fr`. On mobile (≤400px), allow them to stack 1-per-row if they don't fit.

**No floor number input.** Remove the floor field entirely from this screen. Room number already encodes floor for on-campus; movers don't need an explicit floor field.

**Notes** (optional) — same textarea as today, placeholder: "e.g. building code is 1234#, park in lot B"

Validation: location type required. If on-campus or off-campus complex, dorm/building + room/unit required. Access type required. Notes optional.

**← Back** returns to Screen 1. **Next →** advances to Screen 3.

Pre-fill all fields from current user values on open.

---

### Screen 3 — Move-Out Date (Optional)

**Header:** "When do you move out?"
**Subheader:** "Optional — helps us schedule your pickup before you leave."

Single date picker field: `moveout_date` (maps to `User.moveout_date`, already exists).

Helper text below: "Enter your last day in your room. We'll do our best to pick up before then."

**← Back** returns to Screen 2. **✓ Save** submits all data to `/api/user/set_pickup_week` and closes the modal.

The Save button should be visually prominent (existing `.btn-primary` style). Below it: "We'll text you a specific pickup window once routes are set." (same footer note as today).

---

## Step Indicator

Small dot or text indicator at the top of the modal card: "Step 1 of 3" / "Step 2 of 3" / "Step 3 of 3". Matches the onboarding wizard pattern. Keep it minimal — dots are fine.

---

## New Routes

None. All submission still goes to the existing `POST /api/user/set_pickup_week` endpoint.

---

## Model Changes

**One change required — no migration needed:**

In `models.py`, update the `has_pickup_location` property to remove the `pickup_floor` requirement. The new condition should be:

```python
# Before
return (... and self.pickup_access_type is not None and self.pickup_floor is not None)

# After
return (... and self.pickup_access_type is not None)
```

`pickup_floor` column stays in DB — no migration, no data loss. Existing values are retained. We just stop requiring it and stop collecting it in the UI.

**Week 3 backend check:**

Verify that `api_set_pickup_week` in `app.py` accepts `'week3'` as a valid value for `User.pickup_week`. The current validation likely allows only `'week1'` and `'week2'`. Add `'week3'` to the allowed set. Dates for Week 3 are May 11–17 — confirm this is also updated anywhere week labels are rendered server-side (admin seller panel, `pickup_display` property, stats bar display logic).

---

## Template Changes

### `dashboard_pickup_form.html` — Full rewrite

This partial is already isolated from the main dashboard template, which makes this clean.

Replace the current single-form layout with a three-step card structure. All existing CSS classes and JS patterns from the current modal should be reused — the goal is a structural rearrangement, not a visual redesign.

Key structural changes:
- Wrap content in three `<div class="pickup-step" data-step="1/2/3">` containers, only one visible at a time
- Add step indicator at top (e.g., `<p class="step-indicator">Step 1 of 3</p>`)
- Back/Next buttons replace the single Save button on screens 1–2; Save button on screen 3 only
- Access type cards moved to a `display: grid; grid-template-columns: 1fr 1fr 1fr` container
- Floor number input and its label removed entirely
- Move-out date picker moved to its own screen (screen 3)

JS changes (all within the existing `<script>` block in `dashboard.html` or the partial):
- `currentPickupStep` variable (1–3)
- `advancePickupStep()` — validates current step, increments step, shows/hides correct div
- `retreatPickupStep()` — decrements step, shows/hides correct div
- `savePickupModal()` — unchanged logic, just no longer sends `pickup_floor`; add `moveout_date` to the payload

### `dashboard.html`

No structural changes. The `<style>` block override for modal label styles stays. Add CSS for the three-column access card grid:

```css
.pickup-access-grid {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 8px;
}
@media (max-width: 400px) {
  .pickup-access-grid {
    grid-template-columns: 1fr;
  }
}
```

### `admin_seller_panel.html`

Remove the floor number display line from the Pickup Info section. Everything else stays.

---

## Business Logic

- All three screens are part of one modal session — no partial saves until the final Save on screen 3.
- Closing the modal (×) at any step discards unsaved changes, same as today.
- If a seller already has values set, all fields pre-populate on open so they can jump straight to Save if nothing changed.
- `moveout_date` is truly optional — Screen 3 can be submitted empty. The existing `api_set_pickup_week` endpoint should accept `moveout_date` as an optional field and save it to `User.moveout_date` (it may already do this — verify).
- Week selection on Screen 1 is also optional (seller can skip). If no week is selected, don't require time preference. Submit with `pickup_week=null` to clear, or don't submit the week fields at all if untouched.

---

## Constraints

- Do not touch the Stripe webhook, item status logic, or any payout logic.
- Do not touch the admin `/admin/routes` route planning views.
- Do not change the `api_set_pickup_week` endpoint signature beyond adding `week3` support and `moveout_date` acceptance — both of which should be additive/backward-compatible.
- Do not change how the stats bar updates after save (existing inline DOM update on success stays).
- The bottom-sheet mobile behavior (≤540px) should be preserved.
- All CSS must use existing CSS variables — no hardcoded colors.
- The payout modal is a separate modal that lives alongside this one — do not touch it.
