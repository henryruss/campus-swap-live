# feature_onboarding_class_year.md

## Goal

Collect seller class year during onboarding so Campus Swap can understand which student segments are using the platform. Stored on the user record and visible in the admin seller panel.

---

## UX Flow

A new step is added to the onboarding wizard as the **last step before Review & Submit** (currently step 7 for logged-in sellers, step 8 for guests before account creation).

**Step UI:**
- Heading: "What's your class year?"
- Subheading: "This helps us understand who we're serving. Takes one second."
- Five large radio cards, one per option:
  - Freshman
  - Sophomore
  - Junior
  - Senior
  - Grad Student
- Back/Continue buttons follow existing wizard pattern.

**Step is required.** The Continue button is disabled until a selection is made. No skip option.

**Guest path:** Class year is saved in the onboarding session dict (same as `pickup_week`, `pickup_time_preference`) and written to the user record when the guest account is created via `onboard_guest_save` → `process_pending_onboard`.

---

## Model Changes

Add one field to `User`:

```python
class_year = db.Column(db.String(20), nullable=True)
# Values: 'freshman' | 'sophomore' | 'junior' | 'senior' | 'grad'
# NULL = not provided
```

**Migration required.** New nullable column, no default needed.

---

## New Routes

None. The existing `POST /onboard` handler processes all wizard steps via `step=` param. Add a new `step=class_year` branch.

---

## Backend Changes (`app.py`)

**In the `onboard` route**, add a `step=class_year` branch:

```python
# GET: render the class year step
# POST:
class_year = request.form.get('class_year')
valid_values = {'freshman', 'sophomore', 'junior', 'senior', 'grad'}

if not class_year or class_year not in valid_values:
    flash("Please select your class year to continue.")
    return redirect back to class_year step

# Save to session (same pattern as pickup_week)
session['onboard_class_year'] = class_year

# If logged-in seller: write directly to User
if current_user.is_authenticated:
    current_user.class_year = class_year
    db.session.commit()

# Advance to review step
```

**In `onboard_guest_save`**: include `class_year` in the pending session data dict.

**In `process_pending_onboard`**: write `class_year` from session to the newly created user record.

---

## Template Changes

**`onboard.html`:** Add the class year step HTML block inside the existing wizard step structure. Follow the exact same radio card pattern used for the condition step (step 2) — large clickable cards, one selection, `name="class_year"`, values `freshman / sophomore / junior / senior / grad`. No skip link. The Continue button should remain disabled until a card is selected (same JS pattern used for other required radio steps).

Step numbering: insert before the review step. Update any hardcoded step counters (e.g. "Step 6 of 8") if present — check `onboard.html` for these and increment accordingly.

**`templates/admin/admin_seller_panel.html`:** Add "Class Year" to the seller profile section alongside existing account fields. Display as a human-readable label (e.g. "Senior", "Grad Student"). Show "—" if null.

---

## Constraints

- Field is required. Block form submission if class year is not set. Re-render the step with a flash error.
- Do not add class year to the `add_item` flow — that wizard skips personal info steps entirely.
- Do not display class year anywhere on the seller-facing dashboard — it's internal data only.
- Use existing CSS radio card pattern — do not introduce new component styles.
- No change to payout logic, referral logic, or any other user field.

---

## Migration

New migration: `add_class_year_to_user`
- `ALTER TABLE user ADD COLUMN class_year VARCHAR(20)`
- Nullable, no default, no backfill needed.

---

## Files To Change

| File | Change |
|------|--------|
| `models.py` | Add `User.class_year` field |
| `app.py` | Add `step=class_year` branch in `onboard` route; update `onboard_guest_save` and `process_pending_onboard` |
| `onboard.html` | Add class year step UI block; update step counters if present |
| `templates/admin/admin_seller_panel.html` | Add Class Year field to seller profile section |
| New migration file | `add_class_year_to_user` |
