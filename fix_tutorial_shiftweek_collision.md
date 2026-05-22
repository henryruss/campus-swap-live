# Patch Spec: Tutorial ShiftWeek Collision Fix

## Problem

`ShiftWeek` has a unique constraint on `week_start` alone. When a campus
director runs the tutorial during an active production week, `admin_schedule_create`
tries to INSERT a `ShiftWeek` with the same `week_start` date that already
exists in production, hitting a `UniqueViolation` and 500ing.

**Root cause from logs:**
```
UniqueViolation: duplicate key value violates unique constraint "shift_week_week_start_key"
Key (week_start)=(2026-05-18) already exists.
INSERT INTO shift_week ... is_tutorial = True
```

A tutorial week and a real week for the same date must be allowed to coexist.

---

## Fix

Replace the unique constraint on `week_start` with a unique constraint on
`(week_start, is_tutorial)`. This allows one real week and one tutorial week
per date, while still preventing duplicate real weeks and duplicate tutorial
weeks.

---

## Migration

**Drop** the existing unique constraint `shift_week_week_start_key`.  
**Add** a new unique constraint on `(week_start, is_tutorial)`.

`is_tutorial` already exists on the `ShiftWeek` model (confirmed by the
failing INSERT). No new columns needed — migration is constraint-only.

Migration name suggestion: `fix_shift_week_unique_constraint`

```python
# In the upgrade() function:
op.drop_constraint('shift_week_week_start_key', 'shift_week', type_='unique')
op.create_unique_constraint(
    'uq_shift_week_week_start_is_tutorial',
    'shift_week',
    ['week_start', 'is_tutorial']
)

# In the downgrade() function:
op.drop_constraint('uq_shift_week_week_start_is_tutorial', 'shift_week', type_='unique')
op.create_unique_constraint('shift_week_week_start_key', 'shift_week', ['week_start'])
```

---

## Model Change

In `models.py`, update the `ShiftWeek` model's `UniqueConstraint`:

```python
# Before
__table_args__ = (UniqueConstraint('week_start'),)

# After
__table_args__ = (UniqueConstraint('week_start', 'is_tutorial'),)
```

---

## Query Audit — Add `is_tutorial=False` Guards

Any query that resolves "the current/active week" by date must now explicitly
exclude tutorial weeks to avoid a tutorial week being surfaced during real ops.
Grep for all `ShiftWeek.query` calls and audit each one.

The following locations are **confirmed candidates** based on existing helpers:

### `_get_current_published_week()`
This is the highest-risk function — it drives what workers and admin see as
"the current week." Add `ShiftWeek.is_tutorial == False` to every branch of
the query chain:

```python
# Add to every ShiftWeek filter in this function:
.filter(ShiftWeek.is_tutorial == False)
```

### `admin_schedule_index`
The schedule list page queries all `ShiftWeek` records. Tutorial weeks should
still appear here (admin needs to see them), but they should be visually
distinguished (e.g. a "Tutorial" badge) and sorted separately or below real
weeks. No filter change needed — just verify tutorial weeks render cleanly
with a badge and don't interfere with real week display.

### `admin_schedule_create` — duplicate check
If a pre-existing duplicate check exists before the INSERT, it must now match
on both `week_start` AND `is_tutorial`. Otherwise a tutorial submission could
be incorrectly blocked by an existing real week (or vice versa).

```python
existing = ShiftWeek.query.filter_by(
    week_start=parsed_week_start,
    is_tutorial=is_tutorial_flag
).first()
```

### Seller reschedule grid (`/seller/reschedule`, `/reschedule/<token>`)
Any query that looks up available shifts by date range must exclude tutorial
shifts. Tutorial `Shift` records (children of a tutorial `ShiftWeek`) should
never appear as reschedule options for real sellers. Filter at the
`ShiftWeek` join level:

```python
.join(ShiftWeek).filter(ShiftWeek.is_tutorial == False)
```

### Worker calendar / crew dashboard
`_get_current_published_week()` already covers most of this, but verify that
the worker-facing schedule partial (`crew_schedule_week`) does not independently
query `ShiftWeek` without an `is_tutorial` guard.

### SMS reminder cron + no-show cron
`cron_sms_reminders` and `cron_no_show_emails` query shifts by date. Confirm
they join through `ShiftWeek` and filter `is_tutorial == False`, or that they
query `ShiftPickup`/`Shift` in a way that can't accidentally hit tutorial data
(tutorial weeks are draft-only, never published, so SMS guards on
`sellers_notified` may already protect these — verify rather than assume).

---

## Routes to Touch

| Location | Change |
|----------|--------|
| `models.py` — `ShiftWeek` | Update `UniqueConstraint` to `('week_start', 'is_tutorial')` |
| New migration | Drop old constraint, add new compound constraint |
| `_get_current_published_week()` | Add `is_tutorial == False` filter to all branches |
| `admin_schedule_create` — duplicate check (if present) | Match on `(week_start, is_tutorial)` not `week_start` alone |
| `seller/reschedule` shift queries | Exclude tutorial weeks via join filter |
| SMS cron / no-show cron | Verify tutorial weeks can't be hit; add filter if needed |

---

## What Not to Touch

- `admin_schedule_delete` — already bulk-deletes by `week_id`; no date-based query; no change needed.
- `admin_schedule_week` — loads by `week_id`; unaffected.
- `admin_shift_ops`, `crew_shift_view`, all shift-level routes — load by `shift_id`; no `week_start` lookup; unaffected.
- The `is_tutorial` field itself — already exists, no change needed.
- Tutorial flow UX — no changes to the tutorial creation or progression logic.

---

## Constraints

- Migration must be safe to run against live production data. Existing rows all
  have `is_tutorial = False` (real weeks), so the new compound constraint is
  automatically satisfied for all existing data — no backfill needed.
- Do not hardcode `is_tutorial=False` in the `ShiftWeek` model definition as a
  default filter — it must remain a queryable field. Filtering is done at the
  call site.
