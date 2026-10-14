# Feature Spec: Add Pickup Weeks 4 & 5

**Status:** Ready for Claude Code
**Scope:** Small — constants + templates only. No migration, no new routes, no model changes.

---

## Goal

Sellers can currently select Week 1 (Apr 27–May 3), Week 2 (May 4–May 10), or Week 3 (May 11–May 17) as their pickup week preference. Admin has already extended the pickup date range and generated shifts for Weeks 4 and 5. This spec makes those weeks selectable by sellers across all pickup week UI surfaces.

---

## UX Flow

No new flow — existing modal and onboarding step simply gain two more week cards. Seller selects a week card, picks a time preference, saves. Behavior is identical to the existing three weeks.

The pickup week modal already scrolls or wraps cards on narrow viewports; the extra two cards follow the same pattern.

---

## New Routes

None.

---

## Model Changes

None. `User.pickup_week` is a `String` column (not a Postgres ENUM), so `'week4'` and `'week5'` are valid values without a migration.

`InventoryItem.pickup_week` is also a plain String — no migration needed there either.

---

## Constants Changes (`constants.py`)

This is the only source of truth for week labels and date ranges. All templates and route logic read from here.

### `PICKUP_WEEKS`
Add two entries:
```python
PICKUP_WEEKS = [
    ('week1', 'Week 1', 'April 27 – May 3'),
    ('week2', 'Week 2', 'May 4 – May 10'),
    ('week3', 'Week 3', 'May 11 – May 17'),
    ('week4', 'Week 4', 'May 18 – May 24'),   # ADD
    ('week5', 'Week 5', 'May 25 – May 31'),   # ADD
]
```

### `PICKUP_WEEK_DATE_RANGES`
Add two entries (date objects, Monday–Sunday of each week):
```python
PICKUP_WEEK_DATE_RANGES = {
    'week1': (date(2026, 4, 27), date(2026, 5, 3)),
    'week2': (date(2026, 5, 4),  date(2026, 5, 10)),
    'week3': (date(2026, 5, 11), date(2026, 5, 17)),
    'week4': (date(2026, 5, 18), date(2026, 5, 24)),  # ADD
    'week5': (date(2026, 5, 25), date(2026, 5, 31)),  # ADD
}
```

If a `PICKUP_WEEK_LABELS` dict exists separately in `constants.py`, add the two entries there as well:
```python
'week4': 'Week 4 (May 18–May 24)',
'week5': 'Week 5 (May 25–May 31)',
```

---

## Template Changes

All pickup week UI is driven by iterating `PICKUP_WEEKS` (passed into templates via context processor or route). If templates already loop over `PICKUP_WEEKS` to render cards, **no template changes are needed** — the new constants entries will render automatically.

Verify and update if any of the following templates hardcode week values instead of looping:

| Template | Surface | Action |
|---|---|---|
| `dashboard.html` | Pickup week modal (Step 1 of 3) | Confirm cards are rendered via loop over `PICKUP_WEEKS`; if hardcoded, replace with loop |
| `onboard.html` | Step 7 — pickup week selection | Same check |
| `account_settings.html` | Card 4 — Pickup Preferences (read-only display) | Confirm `pickup_week` → label lookup uses `PICKUP_WEEK_DATE_RANGES` or `PICKUP_WEEKS`, not a hardcoded dict |
| `seller/reschedule.html` | Full pickup-window grid | Grid is built from `PICKUP_WEEK_DATE_RANGES` in `_build_reschedule_grid()` — no template change needed, but confirm the grid builder iterates all keys |
| `admin/seller_panel.html` | Seller pickup info display | Confirm label lookup handles `week4`/`week5` without falling back to a raw key |
| `upgrade_pickup.html` | Week selection on upgrade flow | Same check — loop or hardcoded? |

---

## Business Logic

### `api_set_pickup_week` (`POST /api/user/set_pickup_week`)
The endpoint validates that the submitted `pickup_week` value is in the allowed set. Confirm the validation reads from `PICKUP_WEEKS` (or `PICKUP_WEEK_DATE_RANGES.keys()`) rather than a hardcoded list. If it's hardcoded:

```python
# Replace any hardcoded validation like:
if pickup_week not in ['week1', 'week2', 'week3']:

# With:
if pickup_week not in PICKUP_WEEK_DATE_RANGES:
```

### `_get_eligible_reschedule_slots` / `_build_reschedule_grid`
These helpers iterate `PICKUP_WEEK_DATE_RANGES` to build the reschedule grid. Since Week 4 and Week 5 are now in that dict and admin has already generated shifts for those dates, they will automatically appear as eligible slots — no code change needed.

### `admin_reassign_week` (`POST /admin/settings/reassign-week`)
This bulk-reassign tool currently moves `pickup_week = 'week1'` → `'week2'`. It doesn't need changes, but confirm it isn't hardcoded to a specific target week in a way that would break with 5 weeks present.

### Dashboard stats bar label
The "Wk 1 · Morning" format is derived from `pickup_week` → short label mapping. Confirm the mapping covers `week4` and `week5` (e.g. "Wk 4 · Morning"). If there's a `WK_SHORT_LABELS` dict or equivalent, add entries.

---

## Constraints

- Do not touch Stripe, payout, or item status logic — none of those are week-aware.
- Do not change the `ShiftWeek` model or shift generation logic — admin has already generated the shifts.
- Do not add any gating on week selection — all sellers should be able to choose any week freely, same as weeks 1–3.
- The `InventoryItem.pickup_week` field (used for per-item admin override) should also accept `week4`/`week5` if any admin UI validates against a hardcoded list — check and update if so.
- `moveout_date` gating in the reschedule flow (`_get_eligible_reschedule_slots`) already uses date math against `PICKUP_WEEK_DATE_RANGES` — no change needed there.
