# Hotfix — Pickup Week: Three Weeks + UI Fix

## What This Fixes

1. `PICKUP_WEEKS` and `PICKUP_WEEK_DATE_RANGES` in `constants.py` only have two entries. Add a third week (May 11–17).
2. The pickup week selector UI has bad image cropping. Fix CSS.

No model changes. No migration needed. `User.pickup_week` already stores a string key (`'week1'` / `'week2'`); adding `'week3'` is purely additive — existing records are unaffected.

---

## 1. `constants.py` Changes

Update `PICKUP_WEEKS` and `PICKUP_WEEK_DATE_RANGES` to include `week3`:

```python
PICKUP_WEEKS = [
    ('week1', 'Week 1 — Apr 27 – May 3'),
    ('week2', 'Week 2 — May 4 – May 10'),
    ('week3', 'Week 3 — May 11 – May 17'),
]

PICKUP_WEEK_DATE_RANGES = {
    'week1': ('Apr 27', 'May 3'),
    'week2': ('May 4',  'May 10'),
    'week3': ('May 11', 'May 17'),
}
```

Search the entire codebase for any hardcoded references to `week1`/`week2` outside of `constants.py` and confirm they are either:
- Using the constants (fine), or
- Hardcoded strings that now need `week3` added alongside them.

The `api_set_pickup_week` route in `app.py` validates the submitted value against `PICKUP_WEEKS` — confirm it uses `dict(PICKUP_WEEKS).keys()` or equivalent so `week3` is automatically accepted after the constants update.

---

## 2. UI Fix — Pickup Week Selector

Find the template(s) that render the pickup week selection UI. This appears on:
- The seller dashboard (`dashboard.html`) — pickup week modal or inline selector
- Possibly `onboard.html` if pickup week is still shown there

**Fix the image crop issue:**
- Week option cards likely use a background image or `<img>` tag with fixed dimensions.
- Ensure images use `object-fit: cover` and have a consistent fixed height (e.g. `160px`).
- Use CSS variables for any colors — never hardcode.

Example fix if using `<img>`:
```css
.pickup-week-card img {
    width: 100%;
    height: 160px;
    object-fit: cover;
    object-position: center;
    display: block;
}
```

If using background-image:
```css
.pickup-week-card {
    background-size: cover;
    background-position: center;
    height: 160px;
}
```

**Add the third week card** wherever the two existing week cards are rendered. Follow the exact same markup pattern as the existing two — just add a third with `value="week3"` and the label "Week 3 — May 11–17".

---

## 3. Verification Checklist

- [ ] `PICKUP_WEEKS` has 3 entries
- [ ] `PICKUP_WEEK_DATE_RANGES` has 3 keys
- [ ] `week3` is accepted by `api_set_pickup_week` validation
- [ ] Dashboard pickup week selector shows all three weeks
- [ ] All three week cards have consistent, non-cropped image display
- [ ] Existing sellers with `pickup_week = 'week1'` or `'week2'` are unaffected
- [ ] No hardcoded `week1`/`week2` strings outside constants that need updating

---

## Constraints

- Do not touch `User.pickup_week` model field — no migration needed.
- Do not touch Stripe, webhook, or any payment logic.
- Do not touch `InventoryItem.pickup_week` — that field is deprecated (`dropoff_pod` note in CODEBASE.md confirms pod/week is per-user now).
- All color changes must use CSS variables from `static/style.css`.
