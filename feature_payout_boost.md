# Feature Spec: Payout Boost Upgrade ($15 for +30%)

## Goal

Give sellers a paid shortcut to a higher payout rate. Instead of waiting to
refer three friends, a seller can pay $15 once to instantly add +30% to their
current payout rate. This coexists with the referral program — both paths move
toward the same 100% ceiling and stack freely with each other.

This is a one-time purchase per seller per season. A Fall cleanup script will
reset `has_paid_boost` before relaunch next year (no seasonal logic in app code).

---

## UX Flow

### Entry Points

The upgrade offer appears in two places:

1. **Seller dashboard** (`/dashboard`) — a card in the "Refer & Earn" section,
   shown below the referral widget. Visible only if the seller has not yet
   purchased the boost AND their current `payout_rate` is below 100%.

2. **Account settings** (`/account_settings`) — a smaller inline panel in the
   payout section, same visibility conditions.

The upgrade option is **never shown in the onboarding wizard**. Sellers discover
it after they're in the product.

### Dashboard Card — "Boost Your Payout"

When eligible (not yet paid, rate < 100%), the dashboard shows a card:

```
┌─────────────────────────────────────────────────────┐
│  ⚡ Boost Your Payout                                │
│                                                     │
│  Pay $15 once and add +30% to your current rate.   │
│  You're at 20% — this takes you to 50%.            │
│  (Or keep referring friends — it's free.)           │
│                                                     │
│  [ Boost to 50% for $15 ]                          │
└─────────────────────────────────────────────────────┘
```

The "takes you to X%" line is computed dynamically: `min(current_rate + 30, 100)`.
The button label also reflects this: "Boost to 50% for $15", "Boost to 70% for $15", etc.

If the seller is at 80%, the card reads: "This takes you to 100%." Same $15.

### After Clicking the Button

1. POST to `/upgrade_payout_boost` — creates a Stripe Checkout Session with:
   - Amount: $15
   - Metadata: `type=payout_boost`, `user_id=<id>`, `boost_amount=30`,
     `rate_at_purchase=<current payout_rate>`
   - Success URL: `/upgrade_boost_success`
   - Cancel URL: back to `/dashboard`

2. Seller is redirected to Stripe hosted checkout.

3. On success, Stripe fires webhook → `checkout.session.completed` handler reads
   metadata, confirms `type=payout_boost`, then:
   - Adds `boost_amount` (30) to `user.payout_rate`, capped at `referral_max_rate`
     AppSetting (default 100)
   - Sets `user.has_paid_boost = True`
   - Sends confirmation email

4. Seller lands on `/upgrade_boost_success` — a simple success page confirming
   their new rate.

### Hiding the Upgrade Option

The boost card/panel is hidden (not rendered) when either:
- `current_user.has_paid_boost is True` — already purchased this season
- `current_user.payout_rate >= 100` — already at the ceiling

No partial states. If both conditions are false, it shows.

### Referrals After Payment

Referrals continue to stack normally. If a seller pays to go from 20% → 50%,
then gets 3 referrals confirmed, they go to 80%. The boost purchase has no
effect on referral behavior — it just moved the starting point.

---

## New Routes

| Method | Path | Function | Description |
|--------|------|----------|-------------|
| `POST` | `/upgrade_payout_boost` | `upgrade_payout_boost` | Creates Stripe Checkout Session for the $15 boost. Requires login. Guards: `has_paid_boost` must be False, `payout_rate` must be < 100. Returns redirect to Stripe. |
| `GET` | `/upgrade_boost_success` | `upgrade_boost_success` | Post-payment success page. Shows new payout rate. Requires login. |

### Reuse / Retire Existing Routes

- `/upgrade_pickup` and `/upgrade_checkout` — these were the old Pro tier
  upgrade routes. They should now redirect to `/dashboard` with a flash message
  rather than 404. Do not delete them — old email links may still point here.
- `/upgrade_pickup_success` — same treatment, redirect to `/dashboard`.

The new boost routes are distinct from the old Pro routes. Do not repurpose the
old route functions — create new ones to avoid any entanglement with the old
`has_paid` flag logic.

---

## Model Changes

### New Field on `User`

```python
has_paid_boost = db.Column(db.Boolean, default=False, nullable=False)
```

This is separate from the existing `has_paid` field. `has_paid` tracked the old
$15 Pro tier fee and may still be set on legacy users. Do not repurpose it.
`has_paid_boost` is the clean new flag for this feature.

**Migration required:** `flask db migrate -m "add has_paid_boost to user"`

### No Other Model Changes

Payout rate is already stored on `User.payout_rate` (added in the referral
program spec). The boost simply adds 30 to that field inside the webhook handler.

---

## AppSetting Keys

No new AppSettings are strictly required. The boost amount ($15, +30%) is
intentionally hardcoded in this iteration — it's a product decision, not a
runtime config. If you want to make it configurable in the future, add
`payout_boost_amount_cents` (default `'1500'`) and `payout_boost_percentage`
(default `'30'`) as AppSettings at that point.

The existing `referral_max_rate` AppSetting (default `'100'`) is used to cap
the post-boost payout rate, same as referral confirmations.

---

## Stripe Integration

### Checkout Session Creation (`upgrade_payout_boost`)

```python
session = stripe.checkout.Session.create(
    payment_method_types=['card'],
    line_items=[{
        'price_data': {
            'currency': 'usd',
            'unit_amount': 1500,  # $15.00
            'product_data': {
                'name': 'Payout Boost',
                'description': '+30% added to your Campus Swap payout rate',
            },
        },
        'quantity': 1,
    }],
    mode='payment',
    metadata={
        'type': 'payout_boost',
        'user_id': str(current_user.id),
        'boost_amount': '30',
        'rate_at_purchase': str(current_user.payout_rate),
    },
    success_url=url_for('upgrade_boost_success', _external=True),
    cancel_url=url_for('dashboard', _external=True),
)
```

### Webhook Handler (`checkout.session.completed`)

Inside the existing webhook handler, add a branch for `type == 'payout_boost'`:

```python
if metadata.get('type') == 'payout_boost':
    user = User.query.get(int(metadata['user_id']))
    if user and not user.has_paid_boost:
        boost = int(metadata.get('boost_amount', 30))
        max_rate = int(AppSetting.get('referral_max_rate', '100'))
        user.payout_rate = min(user.payout_rate + boost, max_rate)
        user.has_paid_boost = True
        db.session.commit()
        send_boost_confirmation_email(user)
```

**Critical:** check `not user.has_paid_boost` before applying — Stripe can
deliver webhooks more than once. The guard prevents double-application.

`rate_at_purchase` in metadata is stored for audit purposes only — it is not
used in the calculation. The webhook always adds `boost_amount` to whatever
`user.payout_rate` currently is at webhook time. This is intentional: if a
referral is confirmed between checkout creation and webhook delivery, the seller
gets the benefit of both.

---

## Template Changes

### `dashboard.html`

Add a **"Boost Your Payout"** card inside the existing "Refer & Earn" section,
rendered conditionally:

```jinja
{% if not current_user.has_paid_boost and current_user.payout_rate < 100 %}
  {# Boost card here #}
{% endif %}
```

Card contents:
- Headline: "⚡ Boost Your Payout"
- Body: "Pay $15 once and instantly add +30% to your current rate."
- Dynamic line: "You're at {{ current_user.payout_rate }}% — this takes you
  to {{ [current_user.payout_rate + 30, 100] | min }}%."
- Subtext (smaller, muted): "Or keep referring friends — it's free."
- CTA button (`.btn-primary`): "Boost to {{ [current_user.payout_rate + 30, 100] | min }}% for $15"
- Button POSTs to `/upgrade_payout_boost` with a CSRF token

**Visual design notes:**
- The boost card should feel like a secondary offer, not the primary one.
  The referral widget above it is the hero. The boost card is the "or, skip
  ahead" option.
- Use `--bg-cream` background, `--accent` for the button, a subtle
  `--card-border` border. No aggressive upsell styling.
- Once paid, the card disappears entirely — no "you've upgraded" badge needed
  here since the rate itself shows the change.

### `account_settings.html`

Add a compact inline panel in the payout/earnings section:

```jinja
{% if not current_user.has_paid_boost and current_user.payout_rate < 100 %}
<div class="boost-inline-panel">
  <p>Want a faster path to a higher rate? Pay $15 once for an instant +30% boost.</p>
  <form method="POST" action="/upgrade_payout_boost">
    {{ csrf_token() }}
    <button type="submit" class="btn-outline">Boost my payout (+30% for $15)</button>
  </form>
</div>
{% endif %}
```

Smaller and less prominent than the dashboard card — this is for sellers who
are already in settings mode, not the main discovery surface.

### New Template: `upgrade_boost_success.html`

Extends `layout.html`. Simple confirmation page:

- Heading: "You're boosted. 🎉"
- Body: "Your payout rate is now **X%**." (read from `current_user.payout_rate`)
- Subtext: "Keep referring friends to earn even more — every confirmed referral
  adds another 10%."
- CTA: "Back to dashboard" → `/dashboard`

No confetti, no over-celebration. Clean and on-brand.

### `admin_seller_panel.html`

In the Referral section (added by the referral program spec), add a single line:

```
Payout Boost: Purchased  /  Not purchased
```

Shown as a small badge. Admins can see at a glance whether a seller has paid.

---

## Business Logic

### Guard Rails on the Route

`upgrade_payout_boost` (POST) must validate before creating a Stripe session:

1. User is logged in (`@login_required`)
2. `current_user.has_paid_boost` is False — if True, flash "You've already
   purchased the payout boost" and redirect to `/dashboard`
3. `current_user.payout_rate < 100` — if already at 100%, flash "You're
   already at 100% — nothing to boost!" and redirect to `/dashboard`

Both guards must be checked on the POST, not just hidden in the template.
Someone could hit the route directly.

### Payout Rate After Boost

```
new_rate = min(current_rate + 30, referral_max_rate)
```

Applied in the webhook. `referral_max_rate` defaults to 100 from AppSettings.

### Existing `has_paid` Flag

Leave completely untouched. It tracked the old Pro $15 fee. Some legacy users
may have `has_paid=True`. It has no effect on the new boost system. Do not read
it, write it, or display it anywhere new.

### Season Reset (Fall Script)

At the end of the season, run a one-time script before relaunch:

```python
# reset_season.py — run once in Fall before relaunch
User.query.update({
    'has_paid_boost': False,
    'payout_rate': 20,
    'referred_by_id': None,
})
Referral.query.delete()
db.session.commit()
```

This is out of scope for this spec. Document it in `DECISIONS.md` as a known
operational task.

---

## Constraints

- **Do not touch the referral confirmation logic** — `maybe_confirm_referral`
  and `calculate_payout_rate` are unchanged. The boost is applied independently
  in the webhook.
- **Do not modify `has_paid`** — existing field, leave alone.
- **Webhook is the only place `has_paid_boost` is set to True** — never set it
  on the success URL redirect or in the POST handler.
- **Do not add boost logic to the onboarding wizard** — not offered there.
- **`/upgrade_pickup` and `/upgrade_checkout`** — redirect to `/dashboard`,
  do not delete.
- **Stripe metadata locks in the boost amount at checkout time** — do not
  recalculate in the webhook. Use `metadata['boost_amount']`.
- **All new templates extend `layout.html`** and use CSS variables only.
- **No hardcoded colors.**
