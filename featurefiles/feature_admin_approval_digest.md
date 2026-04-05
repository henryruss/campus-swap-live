# Feature Spec: Admin Approval Digest Email

## Goal
Send all admins a single hourly email summarizing how many new items are waiting for review in the approval queue. Eliminates the need for admins to manually check the queue — if there's anything to review, the email arrives and links directly to the queue. If nothing new came in during the hour, no email is sent.

---

## UX Flow

### Admin Experience
1. A new item is submitted by a seller
2. Up to one hour later, the admin receives a digest email (if they haven't received one in the past hour)
3. Email subject: *"[X] items waiting for approval — Campus Swap"*
4. Email body:
   - Header: *"Items Pending Approval"*
   - Summary line: *"You have X items waiting for review in the approval queue."*
   - Breakdown by category (e.g. "2 × Mini Fridge, 1 × Rug, 1 × TV") — gives admin a sense of what's there before they click
   - A single CTA button: **"Review Items"** → links to `https://usecampusswap.com/admin/approve`
   - Footer: standard Campus Swap email footer (via `wrap_email_template()`)
5. Admin clicks the link, goes straight to the approval queue
6. If NO new items were submitted in the past hour, no email is sent

### What Counts as "New"
- An item counts as "new" for digest purposes if:
  - Its status is `pending_valuation`
  - It was submitted (created) after the last digest email was sent
- Items in `needs_info` status do NOT appear in the digest — the admin has already seen those
- Items that were previously sent back and resubmitted DO appear (they re-enter `pending_valuation`)

---

## New Routes

| Method | Path | Function | Description |
|--------|------|----------|-------------|
| `POST` | `/admin/digest/send` | `send_approval_digest` | Internal endpoint that triggers the digest manually. Super admin only. Useful for testing. Not linked in the UI — accessed directly. |

The main digest trigger is a scheduled job, not a user-facing route. See Business Logic below.

---

## Model Changes

### New Model: `DigestLog`
Tracks when the last digest was sent so the job knows whether new items have arrived since then.

```
id              — integer, primary key
sent_at         — datetime, default now
item_count      — integer (how many items were in the digest)
recipient_count — integer (how many admins received it)
```

A Flask-Migrate migration is required to create this table.

This is a simple append-only log. The job queries `DigestLog` for the most recent record to determine the cutoff time for "new" items.

---

## Template Changes

### No page template changes needed
The digest is email-only. It uses the existing `wrap_email_template()` helper for consistent styling.

### Email template (inline HTML string or new file `templates/email_approval_digest.html`)
Structure:
```
[Campus Swap logo]

Items Pending Approval

You have X items waiting for review.

Category breakdown:
  • 2 × Mini Fridge
  • 1 × Rug
  • 1 × TV / Electronics

[Review Items →]  ← amber CTA button, links to /admin/approve

---
You're receiving this because you're an admin at Campus Swap.
[Unsubscribe link is NOT included — this is an operational email, not marketing]
```

---

## Business Logic

### Scheduling
Flask does not have a built-in task scheduler. On Render, the recommended approach is to use a **Render Cron Job** — a separate cron service that POSTs to an internal endpoint on a schedule.

Implementation options (in order of preference):

**Option A — Render Cron Job (preferred):**
- Create a new Render Cron Job service that hits `POST /admin/digest/trigger` every hour
- The `/admin/digest/trigger` endpoint is protected by a secret token (passed as a header or query param, stored as an environment variable `DIGEST_CRON_SECRET`) — not by admin login, since the request comes from Render's infrastructure, not a browser
- The endpoint runs the digest logic and returns a JSON response

**Option B — APScheduler (fallback if Render Cron is not available):**
- Add `APScheduler` to `requirements.txt`
- Initialize a background scheduler in `app.py` that runs the digest function every 60 minutes
- Be aware this runs in-process and may have issues with multiple Render workers — use Render Cron if possible

### Digest Logic (runs every hour)
```
1. Query DigestLog for the most recent record → get last_sent_at
   - If no record exists, use (now - 1 hour) as the cutoff
2. Query InventoryItem for items where:
   - status = 'pending_valuation'
   - date_added > last_sent_at
3. If count == 0: do nothing, exit
4. If count > 0:
   a. Query all users where is_admin = True OR is_super_admin = True
   b. Filter out any admins who have unsubscribed (user.unsubscribed = True)
   c. Build category breakdown: group items by category name, count each
   d. Send digest email to each admin via send_email()
   e. Insert new DigestLog record with sent_at=now, item_count=count, recipient_count=len(admins)
5. Log success or failure
```

### Email Content Rules
- Subject line includes the exact count: *"3 items waiting for approval — Campus Swap"*
- Category breakdown uses plain category names (no subcategories for brevity)
- If all pending items are in the same category, just say: *"3 × Mini Fridge"*
- If there are more than 8 distinct categories, show the top 8 by count and add *"+ X more"*

### Failure Handling
- If the Resend API call fails for one admin, log the error and continue to the next admin — do not abort the whole digest
- If the DigestLog insert fails after emails are sent, log the error — the next run will re-send (this is acceptable; admins getting two emails in an edge case is better than missing items forever)
- Wrap the entire digest function in a try/except and log any unhandled exceptions to PostHog as a `backend_error` event

### Edge Cases
- **Multiple Render workers:** If using APScheduler and multiple workers are running, the digest could fire multiple times. Mitigate by checking if a DigestLog record already exists for the current hour before sending. Render Cron avoids this entirely.
- **No admins in the system:** Log a warning, do nothing
- **Admin added between digest runs:** They'll start receiving digests from the next run onward — no backfill needed
- **Admin account unsubscribed:** Respect `user.unsubscribed = True` and skip them — digest is still operational but should follow unsubscribe preferences
- **Zero items at trigger time but items submitted mid-run:** The query runs once at trigger time; items submitted during the few seconds the function runs will be caught in the next hourly digest

---

## Environment Variables
Add to Render environment:
- `DIGEST_CRON_SECRET` — a random secret string used to authenticate the Render Cron Job request to `/admin/digest/trigger`

---

## Constraints
- Do not send individual emails per item submitted — one hourly digest maximum
- Do not include any seller PII (names, emails) in the digest email — category breakdown only
- Do not add an unsubscribe link to this email — it is an operational notification, not marketing
- The `/admin/digest/trigger` endpoint must be protected by the cron secret token, not by session-based admin login — it is called by Render infrastructure, not a browser
- Do not change any existing email templates or the `send_email()` / `wrap_email_template()` helpers
