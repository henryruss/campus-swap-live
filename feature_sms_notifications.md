# Spec #9 — SMS Notifications

**Dependencies:** Spec #6 (Route Planning) ✅ + Spec #8 (Seller Rescheduling) ✅
**Status:** Ready to build

---

## ⚠️ Manual Setup Required Before This Feature Works

These steps must be completed by Henry **outside of Claude Code** before deploying. None are handled in code.

### Twilio
1. **Create a Twilio account** at twilio.com if you don't have one
2. **Buy a phone number** — get a local 919 or 984 (Chapel Hill) area code if available; this is the number sellers will see texts from
3. **Register for A2P 10DLC** — required by US carriers for application-to-person SMS. Without this, messages get filtered as spam. Takes 1–3 business days — **do this first, before anything else.**
   - Register your brand (Campus Swap)
   - Register your campaign type: transactional notifications (pickup reminders)
   - Link your purchased number to the campaign
4. **Set the inbound webhook URL** on your Twilio number to `https://usecampusswap.com/sms/webhook` (HTTP POST). This handles STOP/UNSTOP replies from sellers.
5. **Add three env vars on Render:**
   - `TWILIO_ACCOUNT_SID` — from Twilio console dashboard
   - `TWILIO_AUTH_TOKEN` — from Twilio console dashboard
   - `TWILIO_FROM_NUMBER` — your purchased number in E.164 format, e.g. `+19845551234`

### Resend
6. **Upgrade your Resend plan** before pickup week. The free tier caps at 100 emails/day — you will hit this during operations. The $20/month plan gives 50k emails/month, which is more than enough.
7. **Clear suppressed test addresses** in the Resend dashboard (Resend → Suppressions). Test sends that bounced have been added to your suppression list and will block real sellers who used the same address during testing.

### Render Cron Jobs
Add two new cron jobs in Render after deploy:

8. **SMS 24hr reminder:** `POST https://usecampusswap.com/admin/cron/sms-reminders`
   - Header: `Authorization: Bearer <CRON_SECRET>`
   - Schedule: daily at 9am ET (matches `sms_reminder_hour_eastern` AppSetting default)
   - Safe year-round — does nothing when no shifts match tomorrow

9. **No-show recovery emails:** `POST https://usecampusswap.com/admin/cron/no-show-emails`
   - Header: `Authorization: Bearer <CRON_SECRET>`
   - Schedule: daily at 6pm ET (matches `no_show_email_hour_eastern` AppSetting default)
   - Only sends for stops flagged no-show that day

---

## Goal

Replace the `_notify_next_seller` stub with real Twilio SMS. Two goals: get sellers ready and waiting, and give movers a direct line for gate codes or access issues.

Sellers get automated texts at four moments:
1. **Scheduled** — when admin fires "Notify Sellers" (alongside existing email)
2. **24-hour reminder** — morning before their pickup, via cron
3. **Route started** — when mover taps "Start Shift"
4. **You're next** — when the previous stop is marked complete

Movers handle ad-hoc contact via the seller's phone number on their stop card. No automated "we're here" text.

Additionally: sellers whose stop is flagged **no-show** receive a warm recovery email at end of day with a reschedule link.

Every SMS includes an opt-out path. Sellers without a phone number are silently skipped — no crash.

---

## UX Flow

### Seller — SMS
- Admin fires "Notify Sellers" → **SMS**: "Your Campus Swap pickup is scheduled for [Day, Mon D] [AM/PM]. We'll text you the day before as a reminder. Reply STOP to opt out."
- Morning before pickup → cron fires **SMS**: "Reminder: Campus Swap is picking up your stuff tomorrow, [Day Mon D] [AM/PM]. See you then! Reply STOP to opt out."
- Mover starts shift → **SMS**: "Your Campus Swap pickup crew has started today's route! We'll text you again when you're up next."
- Previous stop marked complete → **SMS**: "You're up next! Your Campus Swap driver is heading to you now."
- Seller replies STOP → `sms_opted_out = True`; all future SMS silently skipped.

### Seller — no-show recovery email
- Mover flags stop as "Seller wasn't home" (`issue_type = 'no_show'`)
- End-of-day cron fires → seller receives warm email (subject: "We're sorry we missed you!"):
  > Hey [first name], we stopped by today for your Campus Swap pickup but it looks like we missed each other — no worries at all, things come up! We'd love to come back and grab your stuff. Click below to pick a new time that works for you: [Reschedule My Pickup →]
- Seller clicks link → existing `/reschedule/<token>` flow (Spec #8), using their token which has been extended +7 days from flag time
- Token already `used_at` → "already rescheduled" message (existing)
- Token `revoked_at` set (pickup completed) → "your pickup was already completed — no need to reschedule!"

### Mover — flagging issues
"Flag Issue" now shows a two-option picker before submitting:
- **"Seller wasn't home"** → `issue_type = 'no_show'`; extends reschedule token; queues end-of-day email
- **"Item or access problem"** → `issue_type = 'other'`; no email; admin reviews on ops page as before

Free-text notes field remains available for both types.

### Mover — direct contact
Each stop card shows seller phone as a `tel:` link. Movers tap to call or text for gate codes, buzzers, or anything else needing a human touch.

### Edge cases
- No phone → skip SMS, no error; stop card shows "No phone on file"
- `sms_opted_out = True` → skip SMS; no-show email still sends (email, not SMS)
- Single-stop truck → "route started" fires; "you're next" never fires (no previous stop); mover contacts directly
- Seller rescheduled → `notified_at` cleared; re-running "Notify Sellers" on new shift sends fresh SMS
- Twilio misconfigured → SMS skipped silently; email still sends; admin sees flash warning
- "Notify Sellers" twice → idempotency via `notified_at` blocks duplicate SMS and email
- Retroactive shift completion → no SMS, no token revocations
- No-show email cron: no active token for seller → skip, log warning, no crash
- Stop reverted from issue to pending, then re-flagged no-show → email does NOT re-send (`no_show_email_sent_at` is never cleared)

---

## New Routes

| Method | Path | Function | Description |
|--------|------|----------|-------------|
| `POST` | `/sms/webhook` | `sms_inbound_webhook` | Twilio inbound webhook — STOP/UNSTOP. No auth. Twilio signature validated. |
| `POST` | `/admin/cron/sms-reminders` | `cron_sms_reminders` | 24hr SMS reminder cron. Auth via `CRON_SECRET` header. |
| `POST` | `/admin/cron/no-show-emails` | `cron_no_show_emails` | End-of-day no-show recovery email cron. Auth via `CRON_SECRET` header. |

---

## Model Changes

### `User` — new field
```
sms_opted_out (Boolean, default False, server_default='0')
```
Set `True` on STOP, `False` on UNSTOP/START. Twilio webhook is the only writer.

### `ShiftPickup` — new fields
```
issue_type (String 20, nullable) — 'no_show' | 'other' | NULL
no_show_email_sent_at (DateTime, nullable) — idempotency guard; set when recovery email sent; never cleared
```

### `RescheduleToken` — new field
```
revoked_at (DateTime, nullable) — set when associated stop is marked 'completed'
```

**Why separate from `used_at`:**
- `used_at` = seller clicked the link and rescheduled themselves
- `revoked_at` = system killed it because pickup was completed successfully
- Both null = token still valid (or just expired)
- This distinction matters for metrics: rescheduled-themselves vs. completed-pickup are different outcomes

### Token lifecycle

| Event | Token effect |
|-------|-------------|
| Stop marked `completed` | `revoked_at = now` |
| Stop flagged `no_show` | `expires_at` extended to `now + reschedule_token_ttl_days` |
| Stop flagged `other` | Token untouched |
| Stop reverted to pending | `issue_type` cleared; token untouched |
| Seller submits reschedule | `used_at = now` (existing Spec #8 behavior) |

### `/reschedule/<token>` — new error state (minor Spec #8 extension)
Add `revoked_at` check before the existing `used_at` and expiry checks:
- `revoked_at IS NOT NULL` → render: "Your pickup was already completed — no need to reschedule! Check your dashboard for updates."

### Migration: `add_sms_and_no_show_fields`
- Adds `User.sms_opted_out`
- Adds `ShiftPickup.issue_type`, `ShiftPickup.no_show_email_sent_at`
- Adds `RescheduleToken.revoked_at`
- Seeds all four AppSettings (see below)
- All additions idempotent (check column existence before adding)

---

## New AppSettings (seeded by migration)

| Key | Default | Description |
|-----|---------|-------------|
| `sms_enabled` | `'true'` | Master SMS kill switch. |
| `sms_reminder_hour_eastern` | `'9'` | Hour (24h ET) for daily SMS reminder cron. |
| `no_show_email_enabled` | `'true'` | Kill switch for no-show recovery emails. |
| `no_show_email_hour_eastern` | `'18'` | Hour (24h ET) for no-show email cron. |

---

## Helper Function: `_send_sms(user, body)`

```python
def _send_sms(user, body):
    """
    Send SMS via Twilio. Silently returns False (no exception) if:
      - sms_enabled AppSetting is 'false'
      - user.phone is None or empty
      - user.sms_opted_out is True
      - TWILIO_* env vars not set
    Returns True on successful API call. Logs warnings on skip/failure.
    """
```

**Env vars (Render only — never in DB):**
- `TWILIO_ACCOUNT_SID`
- `TWILIO_AUTH_TOKEN`
- `TWILIO_FROM_NUMBER`

**Phone normalization:**
- 10 digits → prepend `+1`
- 11 digits starting with `1` → prepend `+`
- Already `+1XXXXXXXXXX` → use as-is
- Anything else → log warning, return False

---

## Where SMS Fires (Existing Route Modifications)

### 1. `admin_shift_notify_sellers`
After sending pickup confirmation email, also call `_send_sms(pickup.seller, ...)`.

Message:
```
Your Campus Swap pickup is scheduled for [Day, Mon D] [AM/PM]. We'll text you the day before as a reminder. Reply STOP to opt out.
```

Uses `_shift_date(shift)` (exists from Spec #8).

### 2. `cron_sms_reminders` (new)
Auth: `Authorization: Bearer <CRON_SECRET>`.

1. `tomorrow = _today_eastern() + timedelta(days=1)`
2. Query Shifts where `_shift_date(shift) == tomorrow` and `is_active = True`
3. For each ShiftPickup where `notified_at IS NOT NULL` and `status != 'issue'`
4. `_send_sms(pickup.seller, ...)`
5. Return `{sent: N, skipped: N}`

Message:
```
Reminder: Campus Swap is picking up your stuff tomorrow, [Day Mon D] [AM/PM]. See you then! Reply STOP to opt out.
```

### 3. `crew_shift_start`
After creating ShiftRun, SMS every pending seller on this mover's `truck_number`.

Message:
```
Your Campus Swap pickup crew has started today's route! We'll text you again when you're up next.
```

Guard: `if shift.run: return` before creating ShiftRun — blocks retroactive path.

### 4. `crew_shift_stop_update` — on completion (replaces `_notify_next_seller` stub)

**a) Revoke completed seller's token:**
```python
tokens = RescheduleToken.query.filter_by(
    pickup_id=pickup.id, used_at=None, revoked_at=None
).all()
for token in tokens:
    token.revoked_at = _now_eastern().replace(tzinfo=None)
db.session.commit()
```

**b) SMS next pending seller on same truck:**
```python
next_stop = ShiftPickup.query\
    .filter_by(shift_id=shift.id, truck_number=pickup.truck_number, status='pending')\
    .order_by(nullslast(ShiftPickup.stop_order.asc()))\
    .first()
if next_stop and next_stop.issue_type is None:
    _send_sms(next_stop.seller,
        "You're up next! Your Campus Swap driver is heading to you now.")
```

### 5. `crew_shift_stop_update` — on issue flag
Accept `issue_type` from POST form (`'no_show'` or `'other'`). Save to `pickup.issue_type`.

If `issue_type == 'no_show'`:
```python
token = RescheduleToken.query.filter_by(
    pickup_id=pickup.id, used_at=None, revoked_at=None
).first()
if token:
    ttl = int(_get_app_setting('reschedule_token_ttl_days', '7'))
    token.expires_at = (_now_eastern() + timedelta(days=ttl)).replace(tzinfo=None)
    db.session.commit()
```

### 6. `crew_shift_stop_revert`
Clear `pickup.issue_type = None` on revert. Do NOT clear `no_show_email_sent_at`.

---

## `cron_no_show_emails` Route

Auth: `Authorization: Bearer <CRON_SECRET>`.

1. Find ShiftPickups where `issue_type = 'no_show'` AND `no_show_email_sent_at IS NULL` AND `_shift_date(pickup.shift) <= _today_eastern()`
2. Check `no_show_email_enabled` AppSetting — if `'false'`, return `{sent: 0, skipped: N}` immediately
3. For each pickup, find `RescheduleToken` where `pickup_id = pickup.id AND used_at IS NULL AND revoked_at IS NULL`
4. If no token → log warning, increment `skipped`, continue
5. Build URL: `https://usecampusswap.com/reschedule/<token.token>`
6. Send email via Resend (same pattern as all other emails):
   - To: `pickup.seller.email`
   - Subject: `We're sorry we missed you, [first_name]!`
   - Body: warm brand voice (see UX Flow section for copy)
7. Set `pickup.no_show_email_sent_at = _now_eastern().replace(tzinfo=None)`
8. Return `{sent: N, skipped: N}`

---

## `sms_inbound_webhook` Route

```python
# NOTE FOR CLAUDE CODE:
# After deploy, Henry must manually set the inbound webhook URL in the Twilio console:
# Phone Numbers → Manage → Active Numbers → [your number] → Messaging → Webhook URL
# Set to: https://usecampusswap.com/sms/webhook (HTTP POST)
```

- No login required
- Validate Twilio signature via `twilio.request_validator.RequestValidator` + `TWILIO_AUTH_TOKEN`. Invalid → 403.
- Parse `Body` and `From` from POST form data
- Normalize `From` to E.164, look up User by phone
- STOP / STOPALL / UNSUBSCRIBE / CANCEL / END / QUIT → `sms_opted_out = True`
- START / UNSTOP / YES → `sms_opted_out = False`
- No matching user → log warning, return empty TwiML (never 404 — Twilio retries on error)
- Return `<Response/>` (empty TwiML — no reply message)

---

## Template Changes

### `templates/crew/shift.html`
- Add `<a href="tel:{{ pickup.seller.phone }}">{{ pickup.seller.phone }}</a>` to each stop card
- If `seller.phone` is null → `<span style="color: var(--text-muted)">No phone on file</span>`
- "Flag Issue" button opens an inline picker (no page navigation):
  - Two radio cards: "Seller wasn't home" / "Item or access problem"
  - Maps to hidden input `issue_type` = `no_show` or `other`
  - Notes textarea remains (optional for both)
  - Uses `data-*` attributes — no inline `tojson` in `onclick`
  - Submit POSTs `status=issue`, `issue_type=<value>`, `notes=<value>` to existing `crew_shift_stop_update`

### `templates/seller/reschedule_confirm.html` (Spec #8 template)
Add new error branch for `revoked_at`:
```
{% elif reason == 'revoked' %}
  Your pickup was already completed — no need to reschedule!
  Check your dashboard for updates on your items.
{% endif %}
```

### Admin settings page
Add four new AppSetting rows: `sms_enabled`, `sms_reminder_hour_eastern`, `no_show_email_enabled`, `no_show_email_hour_eastern`. Super admin only. Follow existing edit pattern.

### No new seller-facing pages needed.

---

## Business Logic

### Opt-out scope
`sms_opted_out` blocks SMS only. No-show recovery email still sends to opted-out sellers — it's email, not SMS, and the seller hasn't opted out of email.

### Single-stop truck
"You're next" never fires automatically. Mover uses the phone number on the stop card.

### Token revocation on completion
Find all tokens for `pickup_id` where `used_at IS NULL AND revoked_at IS NULL` and revoke all (edge case: multiple tokens shouldn't exist but handle gracefully).

### No-show email idempotency
`no_show_email_sent_at` is the guard. Set once, never cleared. Even if stop is reverted and re-flagged, no duplicate email.

### Retroactive shift completion
Doesn't pass through `crew_shift_start` or per-stop `crew_shift_stop_update` — no SMS fires, no token revocations. Acceptable for past shifts.

---

## Constraints

- Do NOT touch `_get_payout_percentage` or any payout logic
- Do NOT store Twilio credentials in DB or AppSettings — env vars only
- Do NOT change existing email notification flow — SMS and no-show email are purely additive
- Do NOT send SMS or trigger token revocations for retroactive shift completions
- `sms_enabled` kill switch lives inside `_send_sms` — callers never check it
- `no_show_email_enabled` kill switch checked at top of `cron_no_show_emails`
- `twilio` added to `requirements.txt`
- No-show email via Resend — no new email provider

---

## New Dependencies

```
twilio>=9.0.0
```

---

## Testing Checklist (for SPEC_CHECKLIST.md)

### Migration
- [ ] `flask db migrate -m "add_sms_and_no_show_fields"` runs clean
- [ ] `flask db upgrade` runs clean
- [ ] `User.sms_opted_out` exists, defaults False
- [ ] `ShiftPickup.issue_type` exists, nullable
- [ ] `ShiftPickup.no_show_email_sent_at` exists, nullable
- [ ] `RescheduleToken.revoked_at` exists, nullable
- [ ] All four AppSettings seeded

### `_send_sms` helper
- [ ] Returns False when `user.phone` is None
- [ ] Returns False when `user.sms_opted_out = True`
- [ ] Returns False when `sms_enabled = 'false'`
- [ ] Returns False when Twilio env vars not set
- [ ] `4105551234` → `+14105551234`
- [ ] `+14105551234` → unchanged
- [ ] Unparseable phone → False, no crash

### Notify Sellers
- [ ] Sends email AND SMS per unnotified seller with phone
- [ ] No phone → email sent, no SMS, no crash
- [ ] `sms_opted_out = True` → email sent, no SMS
- [ ] Run twice → no duplicate SMS (idempotency via `notified_at`)

### Cron — SMS Reminder
- [ ] Missing `CRON_SECRET` → 403
- [ ] Shift tomorrow + notified sellers → SMS sent
- [ ] No phone → skipped, `skipped` incremented
- [ ] No shifts tomorrow → `{sent: 0, skipped: 0}`, no error
- [ ] `notified_at = NULL` → skipped

### Stop Card — Phone Number
- [ ] Phone shown as `tel:` link on each stop card
- [ ] No phone → "No phone on file" in muted text, no broken link

### Route Started SMS
- [ ] Start shift → pending sellers on mover's truck receive SMS
- [ ] Other trucks → no SMS
- [ ] No phone → skipped, no crash
- [ ] `crew_shift_complete_retroactive` → no SMS

### You're Next SMS + Token Revocation
- [ ] Mark stop complete → next pending seller on same truck receives SMS
- [ ] Completed seller's token → `revoked_at` set
- [ ] Token already `used_at` → `revoked_at` NOT set (seller rescheduled; don't overwrite)
- [ ] No next stop → no SMS, no crash
- [ ] Single-stop truck → no "you're next" SMS
- [ ] Next stop has `issue_type` set → skip, send to stop after if one exists
- [ ] No phone → skipped, no crash

### Issue Flagging
- [ ] "Seller wasn't home" → `issue_type = 'no_show'`, token `expires_at` extended
- [ ] "Item or access problem" → `issue_type = 'other'`, token untouched
- [ ] Revert stop to pending → `issue_type` cleared to None
- [ ] Revert does NOT clear `no_show_email_sent_at`

### Cron — No-Show Emails
- [ ] Missing `CRON_SECRET` → 403
- [ ] `no_show_email_enabled = 'false'` → `{sent: 0, skipped: N}`, no emails
- [ ] Stop flagged `no_show`, `no_show_email_sent_at = NULL`, shift today → email sent
- [ ] `no_show_email_sent_at` set after send
- [ ] Run cron twice → no duplicate email
- [ ] No active token → skipped, log warning, no crash
- [ ] Future-dated shift stop → skipped

### Token Lifecycle — `/reschedule/<token>`
- [ ] `revoked_at` set → "already completed" error page shown
- [ ] `used_at` set → existing "already rescheduled" message unchanged
- [ ] Expired → existing "link expired" message unchanged
- [ ] Valid token after no-show flag → reschedule grid loads normally

### Inbound Webhook
- [ ] Invalid Twilio signature → 403
- [ ] STOP body → `sms_opted_out = True`
- [ ] START body → `sms_opted_out = False`
- [ ] Unknown phone → 200 empty TwiML, log warning, no crash
- [ ] Response is valid TwiML `<Response/>`

### Regression
- [ ] Existing "Notify Sellers" email content unchanged
- [ ] `crew_shift_start` still creates ShiftRun correctly
- [ ] `crew_shift_stop_update` still marks stop completed, sets `picked_up_at`
- [ ] Existing issue flagging (notes field, ops page banner) still works
- [ ] Spec #8 reschedule flow unaffected for sellers without `revoked_at`
- [ ] Seller dashboard loads normally
- [ ] Admin panel loads normally
- [ ] `_get_payout_percentage` untouched
