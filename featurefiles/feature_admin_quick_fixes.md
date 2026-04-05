# Feature Spec: Admin Quick Fixes

## Goal
Three small independent changes: (1) surface seller phone numbers in the admin user table, (2) remove the item ID badge from Shop the Drop product cards, and (3) add a minimum item value notice on the homepage so prospective sellers know upfront what kinds of items we accept.

---

## Fix 1 — Phone Number in Admin User Table

### UX Flow
- Admin navigates to `/admin`
- The existing user table gains a "Phone" column
- Phone numbers display exactly as stored (already formatted `(XXX) XXX-XXXX` at input time)
- If no phone number on file for a user, display `—`
- The column should sit between "Full Name" and "Date Joined" to keep contact info grouped together

### New Routes
None.

### Model Changes
None. `User.phone` already exists.

### Template Changes
**`templates/admin.html`** — user table section:
- Add `<th>Phone</th>` header cell in the correct column position
- Add `<td>{{ user.phone or '—' }}</td>` in the corresponding row cell for each user

### Business Logic
- Read-only display only. No editing from this view.
- No formatting transformation needed — phone is already stored formatted.

### Constraints
- Do not change any other columns in the user table.
- Do not add phone to any CSV export as part of this fix (that is a separate decision).

---

## Fix 2 — Remove Item ID from Shop the Drop Product Cards

### UX Flow
- Buyer navigates to `/inventory`
- Product cards no longer show the item ID badge (e.g. "#123")
- Everything else on the card remains identical: thumbnail, price, status badge, description, video badge if applicable

### New Routes
None.

### Model Changes
None.

### Template Changes
**`templates/inventory.html`** — product card loop:
- Locate the element rendering the item ID (likely something like `<span>#{{ item.id }}</span>` or similar with a badge class)
- Remove it entirely
- Do not remove the item ID from any admin-facing views — only the public inventory page

### Business Logic
None. Pure UI removal.

### Constraints
- Do not remove item ID from `templates/admin.html`, `templates/admin_approve.html`, `templates/dashboard.html`, or `templates/product.html` (the detail page). The ID is still useful in those contexts.
- Do not change any other element on the inventory card.

---

## Fix 3 — Minimum Item Value Notice on Homepage

### UX Flow
- A prospective seller lands on the homepage `/`
- Somewhere in the seller-facing section of the page (near the "Start Selling" CTA or just above/below the value proposition cards), they see a brief notice communicating the minimum item value threshold
- The notice should feel informative, not punitive — the goal is to set expectations before someone goes through onboarding with a $3 desk lamp
- Suggested copy (fill in the dollar amount): *"We accept items valued at $[X] or more. Think furniture, appliances, and electronics — not small accessories or décor."*
- The notice does not need to be a modal or a blocking element. A small callout card or inline text near the CTA is sufficient.

### New Routes
None.

### Model Changes
None.

### Template Changes
**`templates/index.html`** — seller CTA section:
- Add a small informational callout near the "Start Selling" / "Become a Seller" CTA
- Use `var(--bg-cream)` background with `var(--card-border)` border, consistent with existing card styling
- Use `var(--text-muted)` color so it reads as secondary info, not a warning
- Do not use red or error styling — this is guidance, not a rejection

### Business Logic
- **The actual dollar threshold amount is a placeholder — the team must fill this in before deploying.**
- This is static copy only. There is no enforcement logic tied to this notice (item value validation at submission is a separate feature if desired).

### Constraints
- Do not alter the hero section, the animated ticker, or the testimonials section.
- Keep the notice visually lightweight — it should not dominate the page or distract from the primary CTA.
