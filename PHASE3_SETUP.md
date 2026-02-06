# Phase 3 Email Setup Guide

Phase 3.3 email implementation is complete. Here's what was added and how to verify it.

---

## What Was Implemented

### 1. Waitlist Welcome
- **When:** Someone joins the waitlist (index form, new email).
- **Email:** Welcome message with link to dashboard and next steps.

### 2. Account Creation
- **Register (new user):** Welcome email with name, next steps, dashboard link.
- **Register (lead conversion):** "Account Complete" email when existing waitlist user sets a password.
- **Set Password (guest mode):** "Account Secured" email with dashboard link.

### 3. Item Sold Notification
- **When:** Item is marked sold (Stripe webhook or admin "Sold" button).
- **Content:** Sale price, 40% payout amount, Venmo/Zelle handle.

### 4. Item Goes Live
- **When:** Admin approves a pending item (assigns price in bulk update).
- **Content:** Item name, price, link to listing.

---

## Dependencies Added

- `python-dotenv` – Loads `.env` locally so `RESEND_API_KEY` is available without manual export.

Install:

```bash
pip install python-dotenv==1.0.1
```

Or:

```bash
pip install -r requirements.txt
```

---

## Configuration

- **Render:** `RESEND_API_KEY` is already set in Environment.
- **Local:** `.env` with `RESEND_API_KEY=re_...` is loaded on startup.

---

## Resend Limits (Unverified Domain)

Until you verify a domain in Resend, you can only send to your own email. After verifying your domain (e.g. `usecampusswap.com`):

1. In Resend Dashboard: Add domain → verify DNS.
2. In `app.py`: Change `"from": "Campus Swap <onboarding@resend.dev>"` to `"Campus Swap <hello@yourdomain.com>"`.

---

## Quick Verification

1. Join waitlist with a new email → Check inbox for welcome email.
2. Register a new account → Check for welcome email.
3. Set password as guest → Check for "Account Secured" email.
4. Admin approves a pending item → Seller gets "Your item is live!".
5. Item sells (webhook or admin) → Seller gets "Your Item Has Sold!" with 40% payout amount.
