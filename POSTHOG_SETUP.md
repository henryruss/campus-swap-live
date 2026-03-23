# PostHog Analytics Setup

Integrated March 22, 2026. PostHog provides product analytics (funnel tracking, user behavior) and error monitoring for Campus Swap.

## Architecture

- **Server-side (Python SDK):** `posthog>=3.0.0` in `app.py` — captures business events after `db.session.commit()` calls
- **Client-side (JS snippet):** In `templates/layout.html` — captures pageviews, sessions, and enables session replay
- **Guarded by env var:** If `POSTHOG_API_KEY` is unset, the Python SDK is disabled and the JS snippet is not rendered

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `POSTHOG_API_KEY` | Yes | _(disabled)_ | Project API key (`phc_...`) from PostHog |
| `POSTHOG_HOST` | No | `https://us.i.posthog.com` | Ingestion endpoint (US cloud) |

These are set in the Render dashboard under Environment Variables.

## Events Tracked

### Business Events (server-side)

| Event | Trigger | Properties | Why It Matters |
|-------|---------|------------|----------------|
| `seller_signed_up` | New user registers | _(none)_ | Top of funnel — how many signups per day/week |
| `item_submitted` | Seller submits item for review | `item_id`, `category` | Measures seller activation — signup alone isn't enough |
| `item_approved` | Admin approves item with price | `item_id`, `category`, `price`, `is_admin` | Tracks admin throughput and approval rate |
| `item_sold` | Stripe webhook confirms purchase | `item_id`, `category`, `price` | Revenue event — the most important metric |
| `payout_marked_sent` | Admin marks payout complete | `item_id`, `is_admin` | Tracks payout turnaround time |
| `seller_upgraded_to_paid` | Seller upgrades from free to paid tier | _(none)_ | Measures upgrade conversion ($15 revenue) |

### Error Events (server-side)

| Event | Trigger | Properties |
|-------|---------|------------|
| `backend_error` | 404 or 500 error | `error_type`, `route`, `method`, `error_message` (500 only) |

### Client-Side (automatic via JS snippet)

PostHog's JS SDK auto-captures:
- **Pageviews** — every page load
- **Autocapture** — clicks, form submissions, page leaves
- **Sessions** — session duration, bounce rate
- **Session Replay** — (if enabled in PostHog settings) full session recordings

---

## How to Use PostHog Effectively

### 1. Core Funnel: Signup to Sale

The most important view. In PostHog, go to **Insights > Funnel** and create:

```
seller_signed_up  ->  item_submitted  ->  item_approved  ->  item_sold
```

This tells you:
- What % of signups actually submit an item (activation rate)
- What % of submitted items get approved (quality/review bottleneck)
- What % of approved items sell (demand signal)

**Action items by stage:**
- Low signup -> submitted: Onboarding UX is confusing or too many steps
- Low submitted -> approved: Pricing expectations are off, or admin review is too slow
- Low approved -> sold: Items aren't appealing to buyers, or pricing is too high

### 2. Upgrade Funnel: Free to Paid

```
seller_signed_up  ->  item_submitted  ->  seller_upgraded_to_paid
```

This measures your $15 upgrade conversion. Compare against total free-tier users to find your conversion rate. If it's low, the value proposition of 50/50 vs 20/80 payout may not be clear enough.

### 3. Web Analytics Dashboard

Go to **Web Analytics** (left sidebar). Out of the box you get:
- Top pages by traffic
- Referral sources (where users come from)
- Device/browser breakdown
- Bounce rate by page
- Geography

**Key things to watch:**
- Which pages have high bounce rates (landing page optimization)
- Whether mobile vs desktop traffic matches your design effort
- Which referral sources drive actual signups (not just visits)

### 4. Error Monitoring

Go to **Insights > Trends** and filter for `backend_error`. Break down by `error_type` and `route`.

**What to look for:**
- Spikes in 404s (broken links, crawlers hitting dead URLs)
- Any 500s at all (these need immediate investigation)
- Repeated errors on the same route (systematic bug)

### 5. Session Replay (Optional)

If you enable Session Replay in PostHog settings, you can watch real user sessions. Most useful for:
- Debugging why users drop off during onboarding
- Seeing where users get confused on the item submission form
- Understanding how buyers browse inventory

To enable: PostHog dashboard > Project Settings > Session Replay > Toggle on.

### 6. Cohort Analysis

Create cohorts to compare behavior:
- **Free vs Paid sellers** — do paid sellers submit more items?
- **Sellers who sold vs didn't** — what did successful sellers do differently?
- **Users by signup week** — are newer cohorts converting better?

### 7. Key Metrics to Track Weekly

| Metric | How to Find It |
|--------|---------------|
| New signups | Trends: `seller_signed_up` count, weekly |
| Items submitted | Trends: `item_submitted` count, weekly |
| Items sold | Trends: `item_sold` count, weekly |
| Revenue from sales | Trends: `item_sold`, sum of `price` property |
| Upgrade conversions | Trends: `seller_upgraded_to_paid` count, weekly |
| Activation rate | Funnel: `seller_signed_up` -> `item_submitted` |
| Error rate | Trends: `backend_error` count, daily |

### 8. Alerts

Set up PostHog **Actions & Alerts** for:
- Any `backend_error` with `error_type: 500` (Slack/email notification)
- Daily digest of `item_sold` count (revenue tracking)
- `seller_signed_up` drops to zero (site may be down)

---

## Files Modified

| File | What Changed |
|------|-------------|
| `requirements.txt` | Added `posthog>=3.0.0` |
| `app.py` | Import, init block, context processor, error handlers, 6 event captures |
| `templates/layout.html` | JS snippet before `</head>`, wrapped in `{% if posthog_api_key %}` |
| `.env.example` | Added `POSTHOG_API_KEY` and `POSTHOG_HOST` placeholders |

## Troubleshooting

- **No events showing up?** Check that `POSTHOG_API_KEY` is set in Render env vars and the app was redeployed
- **JS snippet not in page source?** The key isn't reaching the template — verify the env var name is exactly `POSTHOG_API_KEY`
- **Python events not appearing?** The SDK queues events and flushes in batches — wait 60 seconds, then check Live Events
- **Local dev:** Events won't send locally unless you set `POSTHOG_API_KEY` in your `.env` file (usually you don't want to — it keeps dev noise out of your data)
