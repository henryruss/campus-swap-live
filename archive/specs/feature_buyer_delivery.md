# Feature Spec: Buyer Delivery Flow

## Goal

Campus Swap no longer offers in-person pickup for buyers. All sold items are
delivered once per week to addresses within a 50-mile straight-line radius of
the warehouse. This spec replaces the existing "Buy Now" direct-to-Stripe path
with a delivery interstitial that collects the buyer's address, validates they
are in range, stores the address against the order, and then proceeds to Stripe.
It also updates all post-purchase copy (success page, confirmation email) to
reflect delivery instead of warehouse pickup.

---

## UX Flow

### Full happy path

1. Buyer views a product page (`/item/<id>`). The delivery method line currently
   reads "In-Store Pickup" — this changes to "Weekly Delivery · Free" (see
   Template Changes).

2. Buyer clicks "Buy Now" → redirected to `GET /checkout/delivery/<item_id>`.

3. Delivery page shows:
   - Item summary card (thumbnail, title, price) — confirms what they're buying
   - Headline: "Where should we deliver this?"
   - Subhead: "We deliver once per week to addresses within 50 miles of Chapel Hill."
   - Address form: Street address, City, State (pre-filled "NC"), ZIP
   - "Continue to Payment" button (submits form)

4. Buyer submits form → `POST /checkout/delivery/<item_id>`.

5. Server geocodes the address via `geopy` (Nominatim, free, no API key needed).
   Computes Haversine distance from warehouse lat/lng (stored in AppSettings).
   - **In range (≤ 50 miles):** Store address string + lat/lng + item_id in Flask
     session as `pending_delivery`. Redirect to `POST /create_checkout_session`
     (existing Stripe route) which now reads the session to attach delivery
     metadata to the Checkout Session.
   - **Out of range:** Re-render the delivery page with an inline error:
     "Sorry, [City] is outside our delivery area. We currently deliver within
     50 miles of Chapel Hill, NC."
   - **Geocode failure** (address not found): Re-render with error:
     "We couldn't find that address — please double-check and try again."

6. Buyer completes Stripe checkout → webhook fires (`checkout.session.completed`)
   → delivery address written from Stripe metadata to `BuyerOrder` record (new
   model — see below) → item marked sold as today.

7. Buyer lands on `/item_success` — copy updated to show delivery confirmation
   instead of warehouse pickup instructions (see Template Changes).

8. Confirmation email updated to reflect delivery (see Business Logic).

### Edge cases

- **Item sold between delivery page load and Stripe completion:** The existing
  webhook already handles this — item status check happens before marking sold.
  No new handling needed.
- **Item reserved by someone else while buyer is on delivery page:** Same as
  above — Stripe will still charge but the webhook will find the item already
  sold and should handle gracefully (existing behavior; do not modify).
- **Buyer navigates back from Stripe to delivery page:** Stripe abandonment is
  normal. Session key `pending_delivery` persists until cleared at purchase or
  session expiry — buyer can re-submit the delivery form and proceed again.
- **Buyer tries to access `/checkout/delivery/<id>` for an already-sold item:**
  Flash "That item has already been sold." and redirect to `/inventory`.
- **Buyer tries to access `/checkout/delivery/<id>` for a non-available item
  (pending, rejected, etc.):** Flash "That item isn't available." and redirect
  to `/item/<id>`.
- **`reserve_only_mode` is ON:** The "Buy Now" button is already hidden in this
  mode; the delivery route should also guard against direct access — redirect
  to `/item/<id>` with flash "Purchases aren't open yet."
- **Session lost before Stripe redirect** (rare): `create_checkout_session`
  should check for `pending_delivery` in session; if missing, redirect back to
  `/checkout/delivery/<item_id>` with flash "Please confirm your delivery
  address to continue."
- **Geocoding rate limit (Nominatim):** Nominatim's free tier allows 1 req/sec.
  Wrap in try/except; on exception treat as geocode failure (show address error
  to user, log the exception). Do not let a geocoding outage block all
  purchases — see Constraints for fallback note.

---

## New Routes

| Method | Path | Function | Description |
|--------|------|----------|-------------|
| `GET` | `/checkout/delivery/<item_id>` | `checkout_delivery` | Render delivery address form. Guards: item must be `available`; `reserve_only_mode` must be off. No login required. |
| `POST` | `/checkout/delivery/<item_id>` | `checkout_delivery_post` | Geocode + range check submitted address. On success: write to session, redirect to `create_checkout_session`. On failure: re-render form with error. |

### Modification to existing route: `create_checkout_session`

This route currently accepts a form POST with `item_id`. Add the following at
the start of the route body:

```python
# Check delivery session is present
delivery = session.get('pending_delivery')
if not delivery or delivery.get('item_id') != item_id:
    flash('Please confirm your delivery address to continue.', 'info')
    return redirect(url_for('checkout_delivery', item_id=item_id))
```

Pass delivery address into Stripe Checkout Session metadata:

```python
metadata={
    'item_id': item.id,
    'delivery_address': delivery['address_string'],
    'delivery_lat': delivery['lat'],
    'delivery_lng': delivery['lng'],
}
```

### Modification to existing route: `webhook` (`checkout.session.completed` handler)

After marking item sold, create a `BuyerOrder` record:

```python
meta = session_obj.get('metadata', {})
if meta.get('delivery_address'):
    order = BuyerOrder(
        item_id=item.id,
        buyer_email=session_obj.get('customer_details', {}).get('email', ''),
        delivery_address=meta['delivery_address'],
        delivery_lat=float(meta['delivery_lat']) if meta.get('delivery_lat') else None,
        delivery_lng=float(meta['delivery_lng']) if meta.get('delivery_lng') else None,
        stripe_session_id=session_obj['id'],
    )
    db.session.add(order)
    db.session.commit()
```

Then clear the delivery session key (cannot do this in webhook — it runs
server-side without a user session). The session key will naturally expire or
be overwritten on the next purchase attempt.

---

## Model Changes

### New: `BuyerOrder`

```
Stores delivery details for each completed item purchase.
One record per sold item (items are unique, one buyer per item).

id                  — Integer PK
item_id             — FK → InventoryItem, nullable=False, unique=True
buyer_email         — String(120), nullable=False
  (from Stripe customer_details.email — no User FK needed since buyers
   don't have to be logged in)
delivery_address    — String(300), nullable=False — full formatted string
delivery_lat        — Float, nullable=True
delivery_lng        — Float, nullable=True
stripe_session_id   — String(120), nullable=True — for audit/lookup
created_at          — DateTime, default utcnow

Relationships: item → InventoryItem (backref buyer_order, uselist=False)
```

**Migration required:**
```
flask db migrate -m "add buyer_order table"
```

### New AppSetting keys

| Key | Example value | Purpose |
|-----|--------------|---------|
| `warehouse_lat` | `'35.9132'` | Warehouse latitude for range check |
| `warehouse_lng` | `'-79.0558'` | Warehouse longitude for range check |
| `delivery_radius_miles` | `'50'` | Max delivery distance; default 50 |

These are set once by super admin in the admin panel. If `warehouse_lat` /
`warehouse_lng` are absent, the range check should **fail open** (allow all
addresses) and log a warning — this prevents a misconfiguration from silently
blocking all purchases. Add a visible warning in the admin panel if these
settings are missing.

---

## Template Changes

### New: `checkout_delivery.html`

Extends `layout.html`.

**Layout:**
```
<div class="delivery-page">

  <!-- Left / top: item summary card -->
  <div class="card delivery-item-summary">
    <img src="{{ item thumbnail }}" alt="">
    <div>
      <p class="delivery-item-title">{{ item.description }}</p>
      <p class="delivery-item-price">${{ item.price }}</p>
    </div>
  </div>

  <!-- Right / bottom: address form -->
  <div class="card delivery-form-card">
    <h1>Where should we deliver this?</h1>
    <p class="text-muted">
      We deliver once per week to addresses within
      {{ radius }} miles of Chapel Hill, NC. Delivery is free.
    </p>

    {% if error %}
      <div class="alert alert-error">{{ error }}</div>
    {% endif %}

    <form method="POST">
      <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
      <div class="form-group">
        <label for="street">Street Address</label>
        <input type="text" id="street" name="street" required
               value="{{ form.street or '' }}" placeholder="123 Main St">
      </div>
      <div class="form-row">
        <div class="form-group">
          <label for="city">City</label>
          <input type="text" id="city" name="city" required
                 value="{{ form.city or '' }}">
        </div>
        <div class="form-group form-group--sm">
          <label for="state">State</label>
          <input type="text" id="state" name="state" required
                 value="{{ form.state or 'NC' }}" maxlength="2">
        </div>
        <div class="form-group form-group--sm">
          <label for="zip">ZIP</label>
          <input type="text" id="zip" name="zip" required
                 value="{{ form.zip or '' }}" maxlength="10">
        </div>
      </div>
      <button type="submit" class="btn-primary btn--full">
        Continue to Payment →
      </button>
    </form>

    <p class="delivery-fine-print">
      Your address is only used to schedule your delivery.
      It is never shared or sold.
    </p>
  </div>

</div>
```

On mobile (`< 640px`): stack vertically, item summary on top, form below.
On desktop: two-column side-by-side layout.

Re-populate all form fields on error (pass `form` dict back from route) so the
buyer doesn't have to retype their address.

### Modified: `product.html`

Change the delivery method line from:

```
Delivery method: "In-Store Pickup"
```

to:

```
Delivery method: "Weekly Delivery · Free"
```

The "Buy Now" button's `href` / form action changes from pointing directly to
`/create_checkout_session` to pointing to `/checkout/delivery/<item.id>` as a
GET link (not a form POST — just a standard anchor redirect into the
interstitial page).

```html
<!-- Before -->
<form method="POST" action="/create_checkout_session">
  <input type="hidden" name="item_id" value="{{ item.id }}">
  <button class="btn-primary">Buy Now</button>
</form>

<!-- After -->
<a href="{{ url_for('checkout_delivery', item_id=item.id) }}"
   class="btn-primary">Buy Now</a>
```

### Modified: `item_success.html` (post-purchase success page)

Replace the existing "next steps" copy:

**Before:**
> 1. Check email for receipt and pickup instructions
> 2. Visit Campus Swap Warehouse during store hours
> 3. Show email receipt to claim item

**After:**
> 1. Check your email — we've sent a confirmation with your delivery details.
> 2. We deliver once per week. You'll get a heads-up before your delivery day.
> 3. Questions? Reply to your confirmation email and we'll sort it out.

### Modified: Admin panel — `BuyerOrder` visibility

Add a "Delivery Address" column to the item lifecycle table in `admin.html`
for sold items. Pull from `item.buyer_order.delivery_address` if it exists,
otherwise show "—". This is read-only; admin needs this to actually schedule
deliveries.

Optionally (can be done in a follow-up): add a CSV export of all `BuyerOrder`
records (email, address, item description, sold_at) from the admin panel for
use in delivery route planning.

---

## Business Logic

### Haversine distance calculation

Add a helper function to `app.py` (or a helpers module):

```python
import math

def haversine_miles(lat1, lng1, lat2, lng2):
    R = 3958.8  # Earth radius in miles
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return R * 2 * math.asin(math.sqrt(a))
```

### Geocoding

Use `geopy` (already a common Flask dependency; add to `requirements.txt` if
not present). Use the Nominatim geocoder with a descriptive `user_agent` string
(Nominatim requires this):

```python
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError

geolocator = Nominatim(user_agent="campus-swap-delivery/1.0")

def geocode_address(street, city, state, zip_code):
    query = f"{street}, {city}, {state} {zip_code}, USA"
    try:
        location = geolocator.geocode(query, timeout=5)
        if location:
            return location.latitude, location.longitude
        return None, None
    except (GeocoderTimedOut, GeocoderServiceError) as e:
        app.logger.error(f"Geocoding error: {e}")
        return None, None
```

Return `(None, None)` on any failure — the route treats this as "couldn't find
address" and shows the user-friendly error.

### Session key structure

```python
session['pending_delivery'] = {
    'item_id': item.id,
    'address_string': f"{street}, {city}, {state} {zip_code}",
    'lat': lat,
    'lng': lng,
}
```

Clear this key after successful purchase by adding
`session.pop('pending_delivery', None)` in the `item_sold_success` route.

### Confirmation email

The existing post-purchase email (sent from the webhook handler after
`checkout.session.completed`) currently tells buyers to come pick up their
item. Update the email body to:

- Remove warehouse address / store hours
- Add: "Your item will be delivered to: [delivery_address]"
- Add: "We'll send you a heads-up before your delivery day."

Pass `delivery_address` from `BuyerOrder` into the email template. If
`BuyerOrder` doesn't exist yet when the email sends (shouldn't happen since
it's created in the same webhook handler before the email), fall back to
"Delivery details will follow in a separate email."

---

## Dependencies

`geopy` must be added to `requirements.txt` if not already present:
```
geopy>=2.4.0
```

---

## Constraints

- Do **not** modify the Stripe webhook's item-sold logic beyond adding the
  `BuyerOrder` creation block. The webhook is the source of truth for payment
  state — no other changes.
- Do **not** add `@login_required` to the delivery route. Buyers don't need
  accounts. The item_id in the URL + the session key are sufficient to tie the
  address to the purchase.
- The `reserve_only_mode` guard on the delivery route must mirror the existing
  guard on `buy_item` — check the same AppSetting, same redirect behavior.
- The product page "Buy Now" button change (anchor vs. form POST) must not
  affect the "Reserve Item" button — those are separate elements.
- Do **not** touch `ItemReservation` logic. Reservations are unaffected by this
  change.
- If `warehouse_lat` / `warehouse_lng` AppSettings are missing, **fail open**
  (allow the purchase to proceed) and log a warning. A misconfigured warehouse
  coordinate should never silently block all sales.
- All form field values must be re-populated on validation error. Never make
  the buyer retype their address.

---

## Admin Setup Checklist (before going live)

- [ ] Set `warehouse_lat` AppSetting (Campus Swap warehouse latitude)
- [ ] Set `warehouse_lng` AppSetting (Campus Swap warehouse longitude)
- [ ] Optionally adjust `delivery_radius_miles` (default: 50)
- [ ] Verify `geopy` is in `requirements.txt` and deployed
- [ ] Run migration: `flask db migrate -m "add buyer_order table"`

---

## Launch Checklist (for human sign-off)

- [ ] `BuyerOrder` model + migration written and run
- [ ] AppSettings for warehouse lat/lng/radius documented and set
- [ ] `haversine_miles` + `geocode_address` helpers written and tested
- [ ] `GET /checkout/delivery/<item_id>` renders correctly
- [ ] `POST /checkout/delivery/<item_id>` validates in-range and out-of-range addresses
- [ ] Session key written on success, read correctly in `create_checkout_session`
- [ ] `create_checkout_session` passes delivery metadata to Stripe
- [ ] Webhook creates `BuyerOrder` from Stripe metadata
- [ ] `product.html` delivery method line updated
- [ ] `product.html` Buy Now changed to anchor → delivery interstitial
- [ ] `item_success.html` copy updated to delivery language
- [ ] Post-purchase email updated to show delivery address
- [ ] Admin item table shows delivery address for sold items
- [ ] Geocode failure (bad address) shows user-friendly error and repopulates form
- [ ] Out-of-range address shows user-friendly error and repopulates form
- [ ] `reserve_only_mode=true` blocks direct access to delivery route
- [ ] Already-sold item redirects cleanly from delivery route
