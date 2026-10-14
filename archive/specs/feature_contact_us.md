# Feature Spec: Contact Us Page

## Goal

Right now there is no way for users (buyers or sellers) to reach Campus Swap if something goes wrong. This adds a `/contact` page with a simple form (name, subject, message), a visible phone number for urgent issues, and a footer link in `layout.html` to surface it everywhere on the site. Submissions are sent via Resend to `Ben@UseCampusSwap.com`, `Henry@UseCampusSwap.com`, and `Jack@UseCampusSwap.com`.

---

## UX Flow

1. User notices "Contact Us" link in the site footer (added to `layout.html`)
2. Clicks it → navigates to `/contact`
3. Sees a clean page with:
   - A short intro line ("We're here to help — usually respond within a few hours")
   - Phone number callout for urgent issues ("For urgent help, call or text us at [NUMBER]")
   - Form with three fields: Name, Subject (dropdown or free text), Message
   - Submit button
4. User fills form and submits
5. Backend sends email to both addresses via Resend
6. Flash message: "Message sent — we'll be in touch soon." → redirect back to `/contact`
7. On error: flash "Something went wrong — please email us directly at ben@usecampusswap.com." → render form again with their input preserved

**Edge cases:**
- All three fields are required; validate server-side, flash error if missing
- Basic length validation: name ≤ 100 chars, subject ≤ 200 chars, message ≤ 5000 chars
- No auth required — logged-in users get their email pre-filled in the email body automatically; guests do not need to log in to contact support
- If Resend call fails, log the error and show the fallback flash message with the direct email address
- CSRF token required (standard `{{ csrf_token() }}` inside the form)

---

## New Routes

| Method | Path | Function | Description |
|--------|------|----------|-------------|
| `GET` | `/contact` | `contact` | Render the contact page |
| `POST` | `/contact` | `contact` | Process form, send email via Resend, redirect |

Both handled in the same function with `if request.method == 'POST':` branching — standard Flask pattern used throughout the codebase.

---

## Model Changes

None. No database storage needed for contact submissions. Email is the record.

---

## Template Changes

### New template: `templates/contact.html`

Extends `layout.html`. Structure:

```
Page header: "Get in touch" (DM Serif Display, --primary)
Subhead: "We're here to help — usually respond within a few hours."

[ Urgent contact callout card ]
  Phone icon + "For urgent help, call or text:"
  [GOOGLE PHONE NUMBER] — displayed large, tel: link for mobile tap-to-call
  Note: "Available during business hours"

[ Contact form card ]
  Name (text input, required)
  Subject (text input, required) — free text; don't restrict to dropdown
  Message (textarea, required, ~6 rows)
  Submit button: "Send Message" (btn-primary / --accent amber)

Footer note: "Or email us directly:
  ben@usecampusswap.com · henry@usecampusswap.com · jack@usecampusswap.com"
```

Use `.card` class for both the callout and the form. Use CSS variables throughout — `--primary`, `--accent`, `--bg-cream`, `--card-border`, etc. No hardcoded colors.

### Modified template: `templates/layout.html`

Add "Contact Us" link to the footer. Find the existing footer link group and add:

```html
<a href="/contact">Contact Us</a>
```

Position: alongside other footer links (Privacy Policy, Terms, Refund Policy, etc.). Exact placement depends on the current footer HTML — add it logically near the end of that link group. Do not restructure the footer.

---

## Business Logic

### Email sent on form submission

- **To:** `Ben@UseCampusSwap.com`, `Henry@UseCampusSwap.com`, and `Jack@UseCampusSwap.com` (send to all three in a single Resend call using the `to` list, or three separate calls — whichever the existing `send_email()` helper supports)
- **Subject:** `[Campus Swap Contact] {subject field value}`
- **Body:** Use `wrap_email_template()` for consistent styling. Include:
  - From name
  - From email (if user is logged in, pull `current_user.email`; otherwise include a line "No account — guest submission")
  - Subject
  - Message body
  - Timestamp

### Reply-to header

Set `reply-to` to the sender's email if logged in, so Ben, Henry, or Jack can reply directly from their inbox without copy-pasting. Check if the existing `send_email()` helper supports a `reply_to` parameter — if not, include the user's email prominently in the body instead.

### Validation (server-side)

```python
name = request.form.get('name', '').strip()
subject = request.form.get('subject', '').strip()
message = request.form.get('message', '').strip()

if not name or not subject or not message:
    flash('Please fill in all fields.', 'error')
    return render_template('contact.html', ...)

if len(name) > 100 or len(subject) > 200 or len(message) > 5000:
    flash('One of your fields is too long — please shorten it.', 'error')
    return render_template('contact.html', ...)
```

Pass the form values back into `render_template` on error so the user doesn't lose their typed message.

---

## Phone Number

The Google Voice number needs to be filled in before deployment. Placeholder in the template:

```html
<a href="tel:+19195781764">(919) 578-1764</a>
```

---

## Constraints

- Do NOT touch existing email helper functions (`send_email`, `wrap_email_template`) — use them as-is
- Do NOT require login to access `/contact` — this needs to be reachable by anyone including buyers who may not have accounts
- Do NOT add a database model or store submissions — email is sufficient
- Do NOT restructure the footer — only add the single link
- CSRF token must be included in the form per standard site pattern
- No new npm packages, no new Python dependencies — Resend is already installed

---

## Implementation Notes for Claude Code

1. Add the two routes to `app.py` near the other public utility routes (Privacy Policy, Terms, etc.)
2. The `contact` function needs: `from flask_login import current_user` (already imported), `flash`, `render_template`, `request`, `redirect`, `url_for` — all already imported
3. Use the existing `send_email(to, subject, html)` function. If it only accepts a single `to` string, call it three times (once per address: ben@, henry@, jack@)
4. The template should be styled to match the existing site aesthetic — DM Serif Display heading, `.card` wrappers, `--accent` amber for the CTA button, `--bg-cream` page background section
5. Add CSRF: `{{ csrf_token() }}` inside the `<form>` tag
