# Phase 2 Security Setup Guide

Phase 2 security hardening is implemented. Follow these steps to finish setup.

---

## What Was Implemented

- **Stripe webhook** – Already in place. Payment verification happens in the webhook (not the success URL).
- **CSRF protection** – All forms now include CSRF tokens via Flask-WTF.
- **Admin access** – Uses the `is_admin` flag on the User model instead of user ID 1.
- **Admin nav link** – "Admin" appears in the header for admin users.

---

## Steps You Must Do

### 1. Install the new dependency

```bash
# Activate your venv first if you use one
source venv/bin/activate   # Mac/Linux
# or: venv\Scripts\activate   # Windows

pip install Flask-WTF==1.2.1
```

Or:

```bash
pip install -r requirements.txt
```

---

### 2. Set up the Stripe webhook (for production)

1. In **Stripe Dashboard** → Developers → Webhooks → Add endpoint.
2. Endpoint URL: `https://your-domain.com/webhook`
3. Events: `checkout.session.completed`
4. Copy the **Signing secret** (starts with `whsec_`).
5. In Render → your Web Service → Environment:
   - Add `STRIPE_WEBHOOK_SECRET` = the signing secret.

**Local development:** Use Stripe CLI to forward webhooks:

```bash
stripe listen --forward-to localhost:4242/webhook
```

Use the `whsec_...` secret it prints in `.env` or export `STRIPE_WEBHOOK_SECRET`.

---

### 3. Make yourself admin

After your first user exists (via registration or waitlist):

```bash
FLASK_APP=app python set_admin.py your@email.com
```

Example:

```bash
FLASK_APP=app python set_admin.py henry@campusswap.com
```

---

### 4. Run migrations (if not done yet)

If you added `is_admin` after your last migration:

```bash
FLASK_APP=app flask db upgrade
```

---

## Quick verification checklist

- [ ] `pip install Flask-WTF` completed
- [ ] App runs without import errors
- [ ] Forms submit (login, register, add item, etc.)
- [ ] Stripe webhook URL configured in production
- [ ] `STRIPE_WEBHOOK_SECRET` set in Render
- [ ] Your account set as admin via `set_admin.py`
- [ ] Admin link appears when logged in as admin

---

## Troubleshooting

**"Bad Request / CSRF token missing"**  
→ CSRF token not rendered. Check that `{{ csrf_token() }}` is inside each `<form>`.

**"STRIPE_WEBHOOK_SECRET not configured"**  
→ Set `STRIPE_WEBHOOK_SECRET` in Render (or `.env` locally).

**Admin link not showing**  
→ Run `python set_admin.py your@email.com` for your account.
