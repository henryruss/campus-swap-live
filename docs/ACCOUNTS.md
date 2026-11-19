# Accounts & External Services

Every outside service the site depends on: what it's for, which env vars it uses, who owns the
login, and how Claude can operate it. **Names only — never put a secret value in this file.**

Keep this current: when a service, key, domain, or env var is added or moved, update the row here
in the same change.

Legend for **Claude access**:
- **CLI** — a command-line tool is installed and logged in; Claude can run it (with approval)
- **API** — has an API Claude could use with a key, but nothing is set up yet
- **Connector** — available as a Claude connector (authorize once in claude.ai)
- **Console only** — has to be clicked through in a web dashboard by Henry

---

## Hosting & infrastructure

### Render — app hosting + production Postgres
- **Used for:** the web service (`gunicorn app:app`, see `Procfile`), the production database, the persistent disk at `/var/data`.
- **Deploys:** automatic on push to `main`. Build command runs `flask db upgrade`, so migrations apply on deploy.
- **Env vars (set in Render → Environment):** all of the ones below that production needs.
- **Local:** `RENDER_DATABASE_URL` in `.env` is a direct connection to the **production** DB. Read-only use only; CLAUDE.md forbids writing to prod via psql.
- **Workspace:** Campus Swap (`tea-d618to8gjchc73f0md9g`). Owner login: henry@usecampusswap.com
- **Services:**

  | Type | Name | ID | Plan |
  |---|---|---|---|
  | Web service | `campus-swap` (https://campus-swap.onrender.com, custom domain usecampusswap.com) | `srv-d6190pp4tr6s73c4lo80` | starter |
  | Postgres | `campus-swap-db` | `dpg-d619at3uibrs73dfm0i0-a` | basic_256mb |
  | Cron | `campus-swap-digest` | `crn-d79ca06dqaus739ja5fg` | starter |
  | Cron | `campus-swap-live-data` | `crn-d70b1p9r0fns73co3mq0` | starter |
  | Cron | `send-scheduled-mass-emails` | `crn-da2454butv3s73bft9mg` | starter |

  All deploy from `main`.
- **Claude access:** CLI (`render`, logged in 2026-11-18; `render services list -o json`, `render logs`, `render deploys`)

### Domain & DNS — usecampusswap.com
- **Registrar / DNS host:** TBD (find out — if it's Cloudflare, DNS changes become scriptable)
- **Records that matter:** Render custom domain, Resend sending-domain records, Google Workspace MX.
- `www.usecampusswap.com` 301-redirects to `usecampusswap.com` (checked 2026-11-18), so only the bare domain needs to be on referrer-restricted keys.
- **Claude access:** TBD

### AWS S3 (+ optional CloudFront) — photo storage
- **Used for:** item photos when `AWS_S3_BUCKET` is set (`storage.py`); otherwise local disk. Carousel images optionally via `CAROUSEL_CDN_URL` (see `docs/setup/CAROUSEL_CDN_SETUP.md`).
- **Env vars:** `AWS_S3_BUCKET`, `AWS_S3_REGION`, `AWS_REGION`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `CAROUSEL_CDN_URL`
- **Status:** TBD — confirm whether production uses S3 or the Render disk.
- **Claude access:** API (no CLI set up)

---

## Google

One Google Cloud project holds the OAuth client and the Maps keys: **`usecampusswap`** (project number `596217962437`, display name "useCampusSwap"). `gcloud` is logged in as henry@usecampusswap.com with this as the default project.

Other projects on the account (not used by the site): `campus-swap-beta`, plus four auto-named "My First Project"s.

**Enabled APIs that matter:** Maps JavaScript API, Places API, Places API (New), Routes API, Maps Embed API, Identity Toolkit API.

### Google Sign-In (OAuth client)
- **Used for:** "Sign in with Google" on the main site (`/auth/google`) and the junk portal (popup on `/junk/login`).
- **Env vars:** `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`
- **Client ID prefix:** `596217962437-`
- **Must list (Credentials → the OAuth client):**
  - Authorized redirect URIs: `https://usecampusswap.com/auth/google/callback`, `http://localhost:4242/auth/google/callback`
  - Authorized JavaScript origins (junk popup sign-in): `https://usecampusswap.com`, `http://localhost:4242`, `http://localhost`
  - **Any new domain must be added to both lists.**
  - Verified working 2026-11-18 by opening the popup from each origin (localhost:4242, usecampusswap.com, www).
- **Claude access:** Console only. gcloud can't read or edit standard OAuth web clients; Claude verifies changes by testing the popup from each origin.

### Google Maps Platform
- **`GOOGLE_MAPS_API_KEY`** = key "API key 1". Browser key, **restricted by website**: `https://usecampusswap.com/*`, `http://localhost:4242/*`, `http://127.0.0.1:4242/*`. Allowed for most Maps Platform APIs. Used for address autocomplete (Places API New) and map previews. **Any new domain must be added to its allowed websites.**
- **`GOOGLE_ROUTES_API_KEY`** = key "routes". Server key, **restricted by IP** (Render's outbound ranges `74.220.57.0/24`, `74.220.49.0/24`, plus one home IP), Routes API only. Used by the delivery route optimizer. A referrer-restricted key 403s from the server.
- Two Firebase auto-created keys (iOS, Browser) exist; the site doesn't use them.
- **Claude access:** CLI (`gcloud services list`, `gcloud services api-keys list/update`)

### Google Workspace — email for usecampusswap.com
- **Mailboxes:** henry@, ben@, team@ (team@ created 2026-08-11; it's the Reply-To on all outgoing mail).
- **Claude access:** Connector (Gmail, Calendar, Drive, Docs, Sheets — authorize in claude.ai)

---

## Payments, email, SMS

### Stripe — payments
- **Used for:** checkout, webhooks (the only source of truth for payment state).
- **Env vars:** `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`, `STRIPE_WEBHOOK_SECRET`
- **Settings in the DB (AppSetting):** `stripe_flexible_coupon_id`
- **Claude access:** Connector (Stripe plugin installed in Claude Code)

### Resend — transactional email
- **Used for:** all outgoing email (`send_email()` in app.py). Sending domain: usecampusswap.com.
- **Env vars:** `RESEND_API_KEY` (send-only), `RESEND_FROM_EMAIL`, `RESEND_REPLY_TO`
- **Local only:** a full-access admin key for reading logs/bounces. Never put it on Render.
- **Dev behavior:** mail is logged, not sent, on a debug server (`SUPPRESS_EMAILS` overrides).
- **A new domain** needs verifying in Resend (DNS records) before mail can come from it.
- **Claude access:** API (local admin key)

### Twilio — SMS
- **Used for:** seller/crew SMS notifications (Spec #9).
- **Env vars:** `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER`
- **Claude access:** API (no CLI set up). Twilio also has an official CLI.

---

## Other services

| Service | Used for | Env vars | Claude access |
|---|---|---|---|
| Cloudflare Turnstile | Bot check on public forms | `TURNSTILE_SITE_KEY`, `TURNSTILE_SECRET_KEY` | API |
| PostHog | Product analytics | `POSTHOG_API_KEY`, `POSTHOG_HOST` | API |
| Anthropic | AI item autofill (descriptions, pricing) | `ANTHROPIC_API_KEY` | API |
| OpenAI | TBD — confirm still used | `OPENAI_API_KEY` | API |
| remove.bg | Photo background removal | `REMOVEBG_API_KEY` | API |

## App-internal secrets (no outside account)
`SECRET_KEY` (sessions, signed links — changing it logs everyone out and kills outstanding set-password links), `CRON_SECRET`, `DIGEST_CRON_SECRET`, `ADMIN_EMAIL`, `APP_BASE_URL` / `BASE_URL`.

---

## Moving to a new domain — checklist
1. Render: add the custom domain, then add its DNS records at the registrar.
2. Google OAuth client: add the domain to redirect URIs **and** JavaScript origins.
3. Google Maps browser key: add the domain to allowed websites.
4. Resend: verify the domain, then update `RESEND_FROM_EMAIL`.
5. Update `APP_BASE_URL` on Render.
6. Expect everyone to sign in once on the new domain (cookies don't carry over).
