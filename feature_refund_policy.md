# Feature Spec: Refund Policy Page + Buyer Email Footer

## Goal

Two related changes:

1. **Refund policy page** — populate the existing `/refund-policy` template with the full policy. The route and function already exist; the page is already linked in the footer.
2. **Buyer order confirmation email footer** — add a short refund policy notice to the bottom of the existing `_send_buyer_order_confirmation` email, with a link to the policy page and the team contact address.

No routes, no model changes, no migrations needed.

---

## Policy

Campus Swap's refund policy has two distinct scenarios:

**Before delivery:** Full refund, no questions asked. If a buyer changes their mind before their delivery day, they can email us and we'll cancel and refund.

**After delivery:** No refunds except where the item is damaged, broken, or materially different from the original seller photo as shown on the website listing. The AI-enhanced cover image is not the basis for comparison — only the original seller-uploaded photo counts. Minor cosmetic wear consistent with a used item does not qualify.

In both cases, the buyer initiates by emailing team@usecampusswap.com. There is no self-serve cancellation or refund flow. All refund decisions after delivery are at Campus Swap's sole discretion.

---

## Part 1 — Refund Policy Page

### Template: `templates/refund_policy.html`

Replace existing content. Match the visual structure of `privacy_policy.html` and `terms_and_conditions.html` exactly — same layout wrapper, same section heading style, same typography.

**Full page copy to implement verbatim:**

---

**Page title:** Refund Policy  
**Subtitle:** Last updated June 2026

---

**Our Policy**

Campus Swap is a student-to-student consignment marketplace. All items are pre-owned and priced to reflect that. Because of the nature of secondhand goods, all sales are generally final — but we want to be fair, and our policy reflects that.

---

**Changed Your Mind? We Get It.**

If you'd like to cancel your order before your delivery day, just email us at [team@usecampusswap.com](mailto:team@usecampusswap.com) and we'll take care of it. We'll issue a full refund, no questions asked, as long as your delivery hasn't already gone out.

---

**After Delivery**

Once an item has been delivered, we don't offer refunds except in the following circumstances:

- The item arrives damaged or broken in a way that was not visible or disclosed in the listing, or
- The item you received is materially different from what was shown in the seller's original listing photo.

To be clear: refund eligibility is based on the **original photo submitted by the seller** — not the AI-enhanced version shown as the cover image. We enhance photos for presentation, but the seller's actual photo is the record of what was listed.

**What qualifies:**
- Furniture arrives with structural damage not visible in the listing photo
- An appliance is non-functional and was listed as working
- The item delivered is not the item that was purchased

**What doesn't qualify:**
- Normal wear and tear on a used item
- Slight color or texture differences due to photo lighting
- Change of mind after delivery
- Dissatisfaction with size (we're always happy to answer sizing questions before you buy — just email us)

---

**How to Request a Refund**

Email [team@usecampusswap.com](mailto:team@usecampusswap.com) within 48 hours of delivery. Please include:

- Your order confirmation email
- Photos clearly showing the issue
- A brief description of how the item differs from the listing

We'll review and get back to you within 2 business days. All post-delivery refund decisions are at the sole discretion of Campus Swap.

---

**Questions?**

Reach us anytime at [team@usecampusswap.com](mailto:team@usecampusswap.com) or use our [contact form](/contact).

---

### Template Implementation Notes

- All `mailto:team@usecampusswap.com` links should use `<a href="mailto:team@usecampusswap.com">team@usecampusswap.com</a>`
- `/contact` link should use `<a href="{{ url_for('contact') }}">contact form</a>`
- `/refund-policy` link (used in the email footer) should use `url_for('refund_policy')` wherever referenced from Jinja templates
- No JavaScript needed
- No hardcoded colors — CSS variables only
- Must extend `layout.html`

---

## Part 2 — Buyer Confirmation Email Footer

### Location in code

The buyer order confirmation email is sent by `_send_buyer_order_confirmation` in `app.py`. It is called from the Stripe webhook handler (`checkout.session.completed`, CASE 0 / `type='cart_order'`). The email is already built and sent — this change adds a footer block to the existing HTML.

### What to add

At the bottom of the email, after the existing content and before the closing `</body>` tag (or before `wrap_email_template` wraps it, wherever the HTML is assembled), add a footer section with this content:

---

**Refund Policy**

Changed your mind? Email us before your delivery day and we'll refund you in full — no questions asked.

After delivery, refunds are issued only if an item is damaged or materially different from its listing. [View our full refund policy](https://usecampusswap.com/refund-policy).

Questions? Reply to this email or contact us at [team@usecampusswap.com](mailto:team@usecampusswap.com).

---

### Implementation notes

- Use the same visual style as other footer sections in `wrap_email_template` — muted text, smaller font size, a top border or divider to separate from the order details
- The refund policy URL should be absolute (`https://usecampusswap.com/refund-policy`) since this is an email — `url_for` with `_external=True` is not reliable here; hardcode the production URL or build it from `BASE_URL` / `APP_BASE_URL` the same way the logo URL is built
- Do not change any other part of the email — only append this footer block

---

## Constraints

- Do not touch any routes, models, or migrations
- Do not change the structure or content of the existing buyer email — only append the footer
- The 48-hour post-delivery window and "sole discretion" language are intentional — do not soften
- Match `privacy_policy.html` / `terms_and_conditions.html` layout exactly for the page

---

## Testing Checklist

### Refund Policy Page
- [ ] `GET /refund-policy` returns 200, no Jinja errors
- [ ] Nav and footer present (layout.html extended correctly)
- [ ] Footer "Refund Policy" link resolves to this page
- [ ] `mailto:team@usecampusswap.com` links are correct
- [ ] `/contact` link resolves correctly
- [ ] Page title tag reads "Refund Policy — Campus Swap"
- [ ] Visual style matches `privacy_policy.html`
- [ ] No hardcoded colors
- [ ] Renders correctly on mobile (375px)

### Buyer Email Footer
- [ ] Trigger a test purchase through the local dev environment and confirm the buyer confirmation email includes the refund policy footer
- [ ] Refund policy URL in email is absolute (starts with `https://`)
- [ ] `team@usecampusswap.com` mailto link is present
- [ ] No visual regression on the rest of the email (item thumbnails, order summary, delivery info all intact)

---

## Cross-Reference Instructions

When complete, update:

- **`CODEBASE.md`** — Static / Legal Pages table: note that `refund_policy.html` now contains full policy content. Email section: note that `_send_buyer_order_confirmation` now includes a refund policy footer.
- **`website-feature-log.md`** — Update Static / Legal Pages entry for Refund Policy. Update Emails Sent table for the buyer order confirmation email (add "refund policy footer" to key content).
- **`HANDOFF.md`** — Add completed entry: "Refund Policy page + buyer email footer added per `feature_refund_policy.md`."
- **`DECISIONS.md`** — Add entry: "Refund policy: pre-delivery full refund (email request); post-delivery refund only for damage or deviation from original seller photo (not AI-enhanced cover); 48-hour post-delivery claim window; all claims via team@usecampusswap.com; no self-serve flow."
