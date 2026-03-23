"""
Weekly Analytics Digest for Campus Swap
========================================
Queries PostgreSQL + PostHog, formats an HTML email, sends via Resend.
Designed to run as a standalone Render Cron Job.

Render Cron Job Setup:
  Name:     weekly-digest
  Schedule: 0 9 * * 1   (every Monday at 9:00 UTC)
  Command:  python scripts/weekly_digest.py

Required env vars:
  DATABASE_URL        – PostgreSQL connection string
  RESEND_API_KEY      – Resend API key
  DIGEST_EMAIL        – Recipient email address

Optional env vars:
  RESEND_FROM_EMAIL   – Sender address (default: team@usecampusswap.com)
  POSTHOG_API_KEY     – PostHog personal/project API key
  POSTHOG_PROJECT_ID  – PostHog project ID
  POSTHOG_HOST        – PostHog host (default: https://us.i.posthog.com)
"""

import os
import sys
from datetime import datetime, timedelta

import requests
import resend
from sqlalchemy import create_engine, text


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DATABASE_URL = os.environ.get("DATABASE_URL", "")
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
RESEND_FROM_EMAIL = os.environ.get("RESEND_FROM_EMAIL", "team@usecampusswap.com")
DIGEST_EMAIL = os.environ.get("DIGEST_EMAIL", "")

POSTHOG_API_KEY = os.environ.get("POSTHOG_API_KEY", "")
POSTHOG_PROJECT_ID = os.environ.get("POSTHOG_PROJECT_ID", "")
POSTHOG_HOST = os.environ.get("POSTHOG_HOST", "https://us.i.posthog.com")


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def get_engine():
    url = DATABASE_URL
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    # Render gives postgres://, SQLAlchemy needs postgresql://
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return create_engine(url)


def run_queries(engine):
    """Return a dict of all DB metrics."""
    metrics = {}
    with engine.connect() as conn:
        def scalar(sql):
            return conn.execute(text(sql)).scalar()

        def fetchall(sql):
            return conn.execute(text(sql)).fetchall()

        metrics["new_sellers_this_week"] = scalar(
            "SELECT COUNT(*) FROM \"user\" "
            "WHERE date_joined >= now() - interval '7 days' "
            "AND is_admin = FALSE"
        )

        metrics["items_submitted_this_week"] = scalar(
            "SELECT COUNT(*) FROM inventory_item "
            "WHERE date_added >= now() - interval '7 days'"
        )

        # No approval timestamp column — approximate as items past pending_valuation
        # that were added this week
        metrics["items_approved_this_week"] = scalar(
            "SELECT COUNT(*) FROM inventory_item "
            "WHERE status NOT IN ('pending_valuation', 'rejected') "
            "AND date_added >= now() - interval '7 days'"
        )

        metrics["items_sold_this_week"] = scalar(
            "SELECT COUNT(*) FROM inventory_item "
            "WHERE status = 'sold' AND sold_at >= now() - interval '7 days'"
        )

        avg_days = scalar(
            "SELECT AVG(EXTRACT(EPOCH FROM (sold_at - date_added)) / 86400) "
            "FROM inventory_item "
            "WHERE status = 'sold' AND sold_at >= now() - interval '7 days'"
        )
        metrics["avg_days_to_sell"] = round(avg_days, 1) if avg_days else None

        metrics["total_live_items"] = scalar(
            "SELECT COUNT(*) FROM inventory_item WHERE status = 'available'"
        )

        metrics["total_sold_all_time"] = scalar(
            "SELECT COUNT(*) FROM inventory_item WHERE status = 'sold'"
        )

        metrics["payout_backlog"] = scalar(
            "SELECT COUNT(*) FROM inventory_item "
            "WHERE status = 'sold' AND payout_sent = FALSE"
        )

        rows = fetchall(
            "SELECT collection_method, COUNT(*) FROM inventory_item "
            "WHERE status = 'available' "
            "GROUP BY collection_method"
        )
        metrics["collection_method_split"] = {r[0]: r[1] for r in rows}

        metrics["gmv_this_week"] = scalar(
            "SELECT COALESCE(SUM(price), 0) FROM inventory_item "
            "WHERE status = 'sold' AND sold_at >= now() - interval '7 days'"
        ) or 0

        metrics["gmv_all_time"] = scalar(
            "SELECT COALESCE(SUM(price), 0) FROM inventory_item WHERE status = 'sold'"
        ) or 0

        metrics["signed_up_total"] = scalar(
            "SELECT COUNT(*) FROM \"user\" WHERE is_admin = FALSE"
        )

        metrics["submitted_item_total"] = scalar(
            "SELECT COUNT(DISTINCT seller_id) FROM inventory_item"
        )

    return metrics


# ---------------------------------------------------------------------------
# PostHog helpers
# ---------------------------------------------------------------------------

def fetch_posthog():
    """Query PostHog for pageview / event stats. Returns dict or None."""
    if not POSTHOG_API_KEY or not POSTHOG_PROJECT_ID:
        return None

    base = f"{POSTHOG_HOST}/api/projects/{POSTHOG_PROJECT_ID}"
    headers = {"Authorization": f"Bearer {POSTHOG_API_KEY}"}
    after = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%dT00:00:00Z")

    ph = {}
    try:
        # Pageview count
        r = requests.get(
            f"{base}/events",
            headers=headers,
            params={"event": "$pageview", "after": after, "limit": 1},
            timeout=15,
        )
        if r.ok:
            # Use the count from the response if available, otherwise fallback
            data = r.json()
            ph["pageview_count"] = data.get("count", len(data.get("results", [])))

        # Use insights/trend endpoint for richer data
        trend_payload = {
            "events": [{"id": "$pageview", "math": "total"}],
            "date_from": "-7d",
        }
        r = requests.post(
            f"{base}/insights/trend",
            headers=headers,
            json=trend_payload,
            timeout=15,
        )
        if r.ok:
            results = r.json().get("result", [])
            if results:
                ph["pageview_count"] = sum(results[0].get("data", []))

        # Unique visitors
        trend_payload["events"] = [{"id": "$pageview", "math": "dau"}]
        r = requests.post(
            f"{base}/insights/trend",
            headers=headers,
            json=trend_payload,
            timeout=15,
        )
        if r.ok:
            results = r.json().get("result", [])
            if results:
                ph["unique_visitors"] = int(max(results[0].get("data", [0])))

        # Top 5 URLs
        r = requests.post(
            f"{base}/insights/trend",
            headers=headers,
            json={
                "events": [{"id": "$pageview", "math": "total"}],
                "breakdown": "$current_url",
                "date_from": "-7d",
            },
            timeout=15,
        )
        if r.ok:
            results = r.json().get("result", [])
            top = sorted(results, key=lambda x: sum(x.get("data", [])), reverse=True)[:5]
            ph["top_urls"] = [
                (t.get("breakdown_value", "?"), int(sum(t.get("data", []))))
                for t in top
            ]

        # item_submitted count
        trend_payload["events"] = [{"id": "item_submitted", "math": "total"}]
        r = requests.post(
            f"{base}/insights/trend",
            headers=headers,
            json=trend_payload,
            timeout=15,
        )
        if r.ok:
            results = r.json().get("result", [])
            if results:
                ph["item_submitted_count"] = int(sum(results[0].get("data", [])))

        # Error events
        for evt in ("backend_error", "$exception"):
            trend_payload["events"] = [{"id": evt, "math": "total"}]
            r = requests.post(
                f"{base}/insights/trend",
                headers=headers,
                json=trend_payload,
                timeout=15,
            )
            if r.ok:
                results = r.json().get("result", [])
                if results:
                    ph[f"{evt}_count"] = int(sum(results[0].get("data", [])))

    except Exception as e:
        print(f"[PostHog] Error fetching analytics: {e}")
        return ph if ph else None

    return ph if ph else None


# ---------------------------------------------------------------------------
# Auto-flag logic
# ---------------------------------------------------------------------------

def generate_flags(m, ph):
    """Return list of plain-English flag strings based on thresholds."""
    flags = []

    if m.get("payout_backlog", 0) > 10:
        flags.append(f"Payout backlog is high ({m['payout_backlog']} items). Review pending payouts.")

    if m.get("items_sold_this_week", 0) == 0 and m.get("total_live_items", 0) > 0:
        flags.append("Zero items sold this week despite live inventory.")

    avg = m.get("avg_days_to_sell")
    if avg and avg > 14:
        flags.append(f"Average time to sell is {avg} days — consider price drops or promotions.")

    if m.get("new_sellers_this_week", 0) == 0:
        flags.append("No new sellers signed up this week.")

    if m.get("items_submitted_this_week", 0) == 0:
        flags.append("No new items submitted this week.")

    if ph:
        errors = ph.get("backend_error_count", 0) + ph.get("$exception_count", 0)
        if errors > 50:
            flags.append(f"{errors} errors/exceptions recorded in PostHog this week.")

    return flags


# ---------------------------------------------------------------------------
# Email HTML builder
# ---------------------------------------------------------------------------

def build_email_html(m, ph, flags, week_ending):
    """Build the HTML digest email with inline styles."""
    green = "#1A3D1A"
    amber = "#C8832A"

    def metric_row(label, value):
        return f'<tr><td style="padding:6px 12px;border-bottom:1px solid #eee;">{label}</td><td style="padding:6px 12px;border-bottom:1px solid #eee;text-align:right;font-weight:bold;">{value}</td></tr>'

    def section(title, rows_html):
        return f"""
        <table style="width:100%;border-collapse:collapse;margin-bottom:24px;">
          <tr><td colspan="2" style="padding:8px 12px;background:{green};color:#fff;font-weight:bold;font-size:14px;">{title}</td></tr>
          {rows_html}
        </table>"""

    # --- This Week ---
    this_week_rows = "".join([
        metric_row("New sellers", m.get("new_sellers_this_week", 0)),
        metric_row("Items submitted", m.get("items_submitted_this_week", 0)),
        metric_row("Items approved (approx)", m.get("items_approved_this_week", 0)),
        metric_row("Items sold", m.get("items_sold_this_week", 0)),
        metric_row("Avg days to sell", m.get("avg_days_to_sell") or "N/A"),
        metric_row("GMV", f"${m.get('gmv_this_week', 0):,.2f}"),
    ])

    # --- All Time ---
    all_time_rows = "".join([
        metric_row("Total users (non-admin)", m.get("signed_up_total", 0)),
        metric_row("Unique sellers", m.get("submitted_item_total", 0)),
        metric_row("Total sold", m.get("total_sold_all_time", 0)),
        metric_row("GMV all-time", f"${m.get('gmv_all_time', 0):,.2f}"),
    ])

    # --- Inventory ---
    split = m.get("collection_method_split", {})
    split_str = ", ".join(f"{k}: {v}" for k, v in split.items()) if split else "—"
    inventory_rows = "".join([
        metric_row("Live items", m.get("total_live_items", 0)),
        metric_row("Collection methods", split_str),
        metric_row("Payout backlog", m.get("payout_backlog", 0)),
    ])

    # --- PostHog ---
    posthog_section = ""
    if ph:
        ph_rows = "".join([
            metric_row("Pageviews", ph.get("pageview_count", "—")),
            metric_row("Unique visitors (peak day)", ph.get("unique_visitors", "—")),
            metric_row("item_submitted events", ph.get("item_submitted_count", "—")),
            metric_row("backend_error", ph.get("backend_error_count", 0)),
            metric_row("$exception", ph.get("$exception_count", 0)),
        ])
        top_urls = ph.get("top_urls", [])
        if top_urls:
            for url, count in top_urls:
                ph_rows += metric_row(f"↳ {url}", count)
        posthog_section = section("PostHog Analytics (7d)", ph_rows)
    else:
        posthog_section = f"""
        <table style="width:100%;border-collapse:collapse;margin-bottom:24px;">
          <tr><td style="padding:8px 12px;background:#999;color:#fff;font-weight:bold;font-size:14px;">PostHog Analytics</td></tr>
          <tr><td style="padding:12px;color:#666;font-style:italic;">PostHog data unavailable — POSTHOG_API_KEY or POSTHOG_PROJECT_ID not set.</td></tr>
        </table>"""

    # --- Flags ---
    flags_section = ""
    if flags:
        flag_items = "".join(f'<li style="margin-bottom:6px;color:#b33;">{f}</li>' for f in flags)
        flags_section = f"""
        <table style="width:100%;border-collapse:collapse;margin-bottom:24px;">
          <tr><td style="padding:8px 12px;background:{amber};color:#fff;font-weight:bold;font-size:14px;">⚠ Flags</td></tr>
          <tr><td style="padding:12px;"><ul style="margin:0;padding-left:20px;">{flag_items}</ul></td></tr>
        </table>"""

    html = f"""
    <div style="font-family:'DM Sans',Helvetica,Arial,sans-serif;max-width:600px;margin:0 auto;color:#222;">
      <div style="background:{green};padding:20px 24px;text-align:center;">
        <h1 style="margin:0;color:#fff;font-size:22px;font-family:'DM Serif Display',Georgia,serif;">Campus Swap — Weekly Digest</h1>
        <p style="margin:6px 0 0;color:#ccc;font-size:13px;">Week ending {week_ending}</p>
      </div>
      <div style="padding:24px;">
        {flags_section}
        {section("This Week", this_week_rows)}
        {section("All Time", all_time_rows)}
        {section("Inventory Snapshot", inventory_rows)}
        {posthog_section}
        <p style="font-size:12px;color:#999;text-align:center;margin-top:32px;">
          Sent automatically by Campus Swap weekly digest.
        </p>
      </div>
    </div>"""

    return html


# ---------------------------------------------------------------------------
# Send email
# ---------------------------------------------------------------------------

def send_digest(html, week_ending):
    """Send the digest email via Resend. Returns True on success."""
    resend.api_key = RESEND_API_KEY
    try:
        resend.Emails.send({
            "from": RESEND_FROM_EMAIL,
            "to": [DIGEST_EMAIL],
            "subject": f"Campus Swap — Weekly Digest ({week_ending})",
            "html": html,
        })
        return True
    except Exception as e:
        print(f"[Resend] Failed to send digest: {e}")
        return False


def send_failure_email(error_msg):
    """Send a minimal failure notification."""
    resend.api_key = RESEND_API_KEY
    try:
        resend.Emails.send({
            "from": RESEND_FROM_EMAIL,
            "to": [DIGEST_EMAIL],
            "subject": "Campus Swap — Weekly Digest FAILED",
            "html": f"<p>The weekly digest could not be generated.</p><pre>{error_msg}</pre>",
        })
    except Exception as e:
        print(f"[Resend] Failed to send failure email: {e}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    week_ending = datetime.utcnow().strftime("%Y-%m-%d")

    # Validate required env vars
    if not DATABASE_URL:
        print("ERROR: DATABASE_URL is not set")
        sys.exit(1)
    if not RESEND_API_KEY:
        print("ERROR: RESEND_API_KEY is not set")
        sys.exit(1)
    if not DIGEST_EMAIL:
        print("ERROR: DIGEST_EMAIL is not set")
        sys.exit(1)

    # Query database
    try:
        engine = get_engine()
        metrics = run_queries(engine)
    except Exception as e:
        print(f"ERROR: Database query failed: {e}")
        send_failure_email(str(e))
        sys.exit(1)

    # Query PostHog (optional, graceful skip)
    ph = fetch_posthog()

    # Generate flags
    flags = generate_flags(metrics, ph)

    # Build and send email
    html = build_email_html(metrics, ph, flags, week_ending)
    if send_digest(html, week_ending):
        print(f"Digest sent for week ending {week_ending}")
    else:
        print("ERROR: Digest email failed to send")
        sys.exit(1)


if __name__ == "__main__":
    main()
