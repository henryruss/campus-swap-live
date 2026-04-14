# Spec #7 — Seller Progress Tracker

**Depends on:** Spec #4 (Organizer Intake) ✅ signed off 2026-04-08

---

## Goal

Sellers have no visibility into what happens to their items after submission. The existing status checklist (Approved / Pickup confirmed / Awaiting pickup / In store) is functional but small and buried inside each item tile.

This spec adds a Domino's-style linear progress tracker — a prominent account-level pipeline — that lives in the setup strip area of the dashboard and shows the seller exactly where they are in the Campus Swap journey. It covers the logistics half of the lifecycle (submission through shop launch), which is the part sellers are most anxious about and the part where all items move together. Per-item sale/payout state is already handled adequately by tile colors and the stats bar.

---

## Pipeline Stages

Six stages, all account-level (not per-item). Evaluated in order; the active stage is the first one whose condition is not yet met.

| # | Label | Condition (true = stage complete) |
|---|---|---|
| 1 | **Submitted** | Seller has at least one non-rejected item |
| 2 | **Approved** | At least one item with `status` not in `('pending_valuation', 'needs_info', 'rejected')` |
| 3 | **Scheduled** | A `ShiftPickup` exists for this seller with `status != 'issue'` |
| 4 | **Picked Up** | At least one of the seller's items has `picked_up_at` set |
| 5 | **At Campus Swap** | At least one of the seller's items has `arrived_at_store_at` set (written by organizer at intake) |
| 6 | **In the Shop** | `shop_teaser_mode` AppSetting is not `'true'` AND at least one item is `available` or `sold` |

**Stage 6 is the terminal state.** Once reached, the tracker stays visible permanently as a satisfying confirmation. It does not disappear.

### Active stage definition

Walk stages left to right. The first stage whose condition is `False` is the **active** stage. All stages before it are **completed**. All stages after are **upcoming**.

If all six conditions are `True`, all stages show completed — no active stage. Tracker remains visible.

### Interrupted states

Two conditions can interrupt the pipeline without advancing it. These are displayed as an amber callout beneath the tracker track — they don't change stage states.

| Condition | Interrupt |
|---|---|
| Any item has `status == 'needs_info'` | "One of your items needs attention." — links to that item's edit page |
| Seller's `ShiftPickup.status == 'issue'` | "There was an issue with your pickup. We'll be in touch." — no link |

Per-item issues (damaged flag, individual `needs_info` on one of many items) surface on the item tile itself, not on the tracker.

---

## UX Flow

### Placement

The tracker lives in the **setup strip slot** — the container currently rendered above the stats bar showing the Phone / Pickup week & address / Payout info chips.

**Visibility rules:**
- Setup strip incomplete (any chip still amber) → show setup strip only, tracker hidden
- Setup strip fully complete → setup strip disappears, tracker appears in its place

The tracker is wrapped in a `.card` matching the setup strip's container style. The two are mutually exclusive — never shown simultaneously.

### Visual design

A horizontal step track with 6 nodes:

```
  ●————●————●————◉ · · · · · ○ · · · · · ○
Submitted Approved Scheduled  Picked Up  At Campus  In the Shop
                    (active)              Swap
```

- **Completed node** — filled `--primary` (forest green), checkmark icon
- **Active node** — filled `--accent` (amber), subtle pulsing ring animation
- **Upcoming node** — grey stroke only, no fill
- **Connecting line** — solid green between completed nodes, dashed grey from active node onward
- **Labels** — short text below each node; muted for upcoming, full color for completed/active

### Contextual message

A single line of copy below the track describing the active stage:

| Active Stage | Message |
|---|---|
| Submitted | "We're reviewing your items — approval usually takes 1–2 days." |
| Approved | "Items approved! We'll add you to a pickup route soon." |
| Scheduled | "Pickup scheduled. We'll text you when the driver is on the way." |
| Picked Up | "Driver has your items — they're headed to our storage facility." |
| At Campus Swap | "Your items are in storage and will go live when the shop opens." |
| In the Shop | "Your items are live! Buyers can shop them now." |
| All complete | "Your items are in the shop. Good luck! 🎉" |

If an interrupt is active, the amber callout appears below this message line.

### Mobile

Same layout, smaller nodes. Labels hidden on all nodes except the active one (shown below track only). Track has `min-width: 360px` and the card clips with `overflow-x: auto` on very small screens.

---

## New Routes

None. All state is computed in the existing `dashboard` route and passed to the template.

---

## Model Changes

**No new models. No migration required.**

All data needed is already present:
- `InventoryItem.status`, `picked_up_at`, `arrived_at_store_at` — existing fields
- `ShiftPickup` with `seller_id` and `status` — exists from Spec #3
- `AppSetting('shop_teaser_mode')` — existing key

---

## Template Changes

### `dashboard.html` — modify

**1. Setup strip / tracker slot**

Wrap the setup strip and tracker in a mutual exclusivity condition:

```jinja2
{% if not setup_complete %}
  {# existing setup strip markup — unchanged #}
{% else %}
  {% include '_seller_tracker.html' %}
{% endif %}
```

`setup_complete` is a boolean passed from the route — `True` when phone, pickup week + address, and payout info are all set.

**2. Item tile checklist**

Remove the existing 4-item status checklist (Approved / Pickup confirmed / Awaiting pickup / In store) from item tiles. It is fully superseded by the tracker. Keep:
- Tile color-coded backgrounds (red/green/yellow/amber)
- "Pricing update" badge on the price row

**3. New template context variables**

```python
setup_complete  # bool
tracker         # dict from _compute_seller_tracker(), or None if setup_complete is False
```

### `_seller_tracker.html` — new partial

```html
<div class="seller-tracker card">
  <div class="seller-tracker__track">
    {% for stage in tracker.stages %}
      <div class="seller-tracker__step seller-tracker__step--{{ stage.state }}">
        <div class="seller-tracker__node">
          {% if stage.state == 'completed' %}<i class="fa fa-check"></i>{% endif %}
        </div>
        <span class="seller-tracker__label">{{ stage.label }}</span>
      </div>
      {% if not loop.last %}
        <div class="seller-tracker__line seller-tracker__line--{{ 'filled' if stage.state == 'completed' else 'empty' }}"></div>
      {% endif %}
    {% endfor %}
  </div>

  {% if tracker.active_message %}
    <p class="seller-tracker__message">{{ tracker.active_message }}</p>
  {% endif %}

  {% if tracker.interrupt %}
    <div class="seller-tracker__interrupt">
      <span>⚠</span>
      {{ tracker.interrupt.message }}
      {% if tracker.interrupt.link %}
        <a href="{{ tracker.interrupt.link }}">View item →</a>
      {% endif %}
    </div>
  {% endif %}
</div>
```

### `static/style.css` — additions

New classes (CSS variables only):

```css
/* Seller progress tracker */
.seller-tracker { padding: 1.25rem 1.5rem; }

.seller-tracker__track {
  display: flex;
  align-items: center;
  margin-bottom: 0.75rem;
}

.seller-tracker__step {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.4rem;
  flex-shrink: 0;
}

.seller-tracker__node {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.7rem;
  border: 2px solid var(--rule);
  background: var(--bg-body);
  color: var(--bg-body);
}

.seller-tracker__step--completed .seller-tracker__node {
  background: var(--primary);
  border-color: var(--primary);
}

.seller-tracker__step--active .seller-tracker__node {
  background: var(--accent);
  border-color: var(--accent);
  animation: tracker-pulse 2s infinite;
}

.seller-tracker__step--upcoming .seller-tracker__node {
  background: var(--bg-body);
  border-color: var(--rule);
}

@keyframes tracker-pulse {
  0%, 100% { box-shadow: 0 0 0 4px rgba(200, 131, 42, 0.2); }
  50%       { box-shadow: 0 0 0 7px rgba(200, 131, 42, 0.08); }
}

.seller-tracker__label {
  font-size: 0.65rem;
  color: var(--text-muted);
  white-space: nowrap;
}

.seller-tracker__step--completed .seller-tracker__label,
.seller-tracker__step--active .seller-tracker__label {
  color: var(--text-main);
  font-weight: 500;
}

.seller-tracker__line {
  flex: 1;
  height: 2px;
  margin-bottom: 1.1rem;
}

.seller-tracker__line--filled { background: var(--primary); }
.seller-tracker__line--empty  { background: var(--rule); }

.seller-tracker__message {
  font-size: 0.8rem;
  color: var(--text-muted);
  margin: 0.25rem 0 0;
}

.seller-tracker__interrupt {
  margin-top: 0.6rem;
  padding: 0.5rem 0.75rem;
  background: #FFF8EE;
  border-left: 3px solid var(--accent);
  border-radius: 4px;
  font-size: 0.8rem;
  color: var(--text-main);
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.seller-tracker__interrupt a {
  color: var(--accent);
  text-decoration: none;
  margin-left: auto;
  white-space: nowrap;
}

/* Mobile */
@media (max-width: 600px) {
  .seller-tracker { overflow-x: auto; }
  .seller-tracker__track { min-width: 360px; }
  .seller-tracker__label { display: none; }
  .seller-tracker__step--active .seller-tracker__label { display: block; }
  .seller-tracker__node { width: 24px; height: 24px; }
}
```

---

## Business Logic

### `_compute_seller_tracker(seller, items)` — new helper in `app.py`

```python
def _compute_seller_tracker(seller, items):
    """
    Computes account-level tracker state for the seller dashboard.
    seller: User (current_user)
    items:  list of InventoryItem for this seller (all statuses)
    Returns dict for template context key `tracker`.
    """
    seller_pickup = ShiftPickup.query.filter_by(seller_id=seller.id).first()

    active_items = [i for i in items if i.status != 'rejected']

    conds = {
        'submitted':      len(active_items) > 0,
        'approved':       any(i.status not in ('pending_valuation', 'needs_info', 'rejected')
                              for i in active_items),
        'scheduled':      (seller_pickup is not None and seller_pickup.status != 'issue'),
        'picked_up':      any(i.picked_up_at for i in active_items),
        'at_campus_swap': any(i.arrived_at_store_at for i in active_items),
        'in_the_shop':    (AppSetting.get('shop_teaser_mode', 'false') != 'true'
                           and any(i.status in ('available', 'sold') for i in active_items)),
    }

    stage_defs = [
        ('submitted',      'Submitted'),
        ('approved',       'Approved'),
        ('scheduled',      'Scheduled'),
        ('picked_up',      'Picked Up'),
        ('at_campus_swap', 'At Campus Swap'),
        ('in_the_shop',    'In the Shop'),
    ]

    active_messages = {
        'submitted':      "We're reviewing your items — approval usually takes 1–2 days.",
        'approved':       "Items approved! We'll add you to a pickup route soon.",
        'scheduled':      "Pickup scheduled. We'll text you when the driver is on the way.",
        'picked_up':      "Driver has your items — they're headed to our storage facility.",
        'at_campus_swap': "Your items are in storage and will go live when the shop opens.",
        'in_the_shop':    "Your items are live! Buyers can shop them now.",
    }

    stages = []
    found_active = False
    for key, label in stage_defs:
        if not found_active and not conds[key]:
            state = 'active'
            found_active = True
        elif conds[key]:
            state = 'completed'
        else:
            state = 'upcoming'
        stages.append({'key': key, 'label': label, 'state': state})

    active_key = next((s['key'] for s in stages if s['state'] == 'active'), None)
    message = active_messages.get(active_key, "Your items are in the shop. Good luck! 🎉")

    # Interrupts — checked independently of stage states
    interrupt = None
    needs_info_item = next((i for i in active_items if i.status == 'needs_info'), None)
    if needs_info_item:
        interrupt = {
            'message': "One of your items needs attention.",
            'link': f'/edit_item/{needs_info_item.id}'
        }
    elif seller_pickup and seller_pickup.status == 'issue':
        interrupt = {
            'message': "There was an issue with your pickup. We'll be in touch.",
            'link': None
        }

    return {
        'stages':         stages,
        'active_message': message,
        'interrupt':      interrupt,
    }
```

### Dashboard route additions

```python
# Determine setup strip vs. tracker
setup_complete = bool(
    current_user.phone and
    current_user.pickup_week and
    current_user.has_pickup_location and
    current_user.payout_method and
    current_user.payout_handle
)

tracker = _compute_seller_tracker(current_user, items) if setup_complete else None

return render_template('dashboard.html',
    ...,
    setup_complete=setup_complete,
    tracker=tracker,
)
```

---

## Edge Cases

| Scenario | Handling |
|---|---|
| Seller has only rejected items | `active_items` empty → Stage 1 active. Tracker shows them at the start. |
| All items are `needs_info` | Stage 2 upcoming (condition False). Interrupt fires. Seller sees both. |
| `ShiftPickup` exists but `status == 'issue'` | Stage 3 condition False (issue excluded) → Stage 3 stays active. Interrupt fires. |
| Pickup issue resolved (stop re-completed by mover) | `status` → `'completed'` → Stage 3 condition True → tracker advances on next page load. |
| `shop_teaser_mode` absent from AppSetting | `AppSetting.get('shop_teaser_mode', 'false')` returns `'false'` → Stage 6 evaluates normally. |
| Setup strip not complete | `tracker=None`, tracker block not rendered. No `ShiftPickup` query needed. |
| `shop_teaser_mode` flipped back to `'true'` after Stage 6 was reached | Stage 6 drops to upcoming. Unlikely ops scenario but handled correctly on each page load. |
| Seller with one item sold and one available | Stage 6 `any(status in ('available', 'sold'))` → True. Both count. |
| `needs_info` AND pickup issue simultaneously | `needs_info` interrupt takes priority (checked first). Only one interrupt shown at a time. |

---

## Constraints

- **No migration.** Confirm before touching any model file.
- **No new routes.**
- **Do not modify** `picked_up_at` write logic in `crew_shift_stop_update`.
- **Do not modify** `arrived_at_store_at` write logic in `crew_intake_submit`.
- **Do not modify** `ShiftPickup` model.
- **Do not touch the admin panel.**
- `ShiftPickup` query lives inside `_compute_seller_tracker` — called once per dashboard load, never inside a Jinja loop.
- Tracker is only rendered when `current_user.is_seller` is True and `setup_complete` is True. Guard both in the template.
- Setup strip and tracker are **mutually exclusive** — never rendered simultaneously.
