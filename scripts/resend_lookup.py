"""Look up sent emails in Resend to diagnose bounces / missing confirmations.

Requires a FULL-ACCESS Resend API key in the local environment as
RESEND_ADMIN_API_KEY. The RESEND_API_KEY used by the app is send-only
(by design) and cannot read logs.

Usage:
    python3 scripts/resend_lookup.py                          # last 100 emails
    python3 scripts/resend_lookup.py aaronhg916@gmail.com     # filter by recipient
    python3 scripts/resend_lookup.py --bounced                # only non-delivered
    python3 scripts/resend_lookup.py --since 2026-08-11       # on/after a date

Never commit the full-access key, and do not add it to Render — the production
app only ever needs send permission.
"""

import json
import os
import sys
import urllib.error
import urllib.request

from dotenv import load_dotenv

load_dotenv()

API = 'https://api.resend.com'
# Resend sits behind Cloudflare; the default urllib UA gets a 403 (error 1010).
HEADERS_UA = 'curl/8.4.0'


def _key():
    key = os.environ.get('RESEND_ADMIN_API_KEY')
    if not key:
        sys.exit(
            "RESEND_ADMIN_API_KEY not set.\n\n"
            "Create a full-access key at https://resend.com/api-keys "
            "(Permission: Full access), then add to .env:\n"
            "  RESEND_ADMIN_API_KEY=re_...\n"
        )
    return key


def _get(path):
    req = urllib.request.Request(
        f"{API}{path}",
        headers={'Authorization': f'Bearer {_key()}', 'User-Agent': HEADERS_UA},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        if e.code == 401 and 'restricted' in body:
            sys.exit(
                f"Key rejected: {body}\n\n"
                "RESEND_ADMIN_API_KEY appears to be a sending-only key. "
                "Create one with 'Full access' permission instead."
            )
        sys.exit(f"Resend API error {e.code}: {body}")


def list_emails(limit=100):
    data = _get(f'/emails?limit={limit}')
    return data.get('data', data if isinstance(data, list) else [])


def main():
    args = [a for a in sys.argv[1:]]
    bounced_only = '--bounced' in args
    args = [a for a in args if a != '--bounced']

    since = None
    if '--since' in args:
        i = args.index('--since')
        since = args[i + 1]
        del args[i:i + 2]

    recipient = args[0].lower() if args else None

    emails = list_emails()
    rows = []
    for e in emails:
        to = e.get('to') or []
        to = [t.lower() for t in (to if isinstance(to, list) else [to])]
        event = (e.get('last_event') or '').lower()
        created = e.get('created_at') or ''

        if recipient and not any(recipient in t for t in to):
            continue
        if since and created[:10] < since:
            continue
        if bounced_only and event in ('delivered', 'sent', 'opened', 'clicked'):
            continue
        rows.append((created, ', '.join(to), event or '?', e.get('subject') or '', e.get('id')))

    if not rows:
        print("No matching emails found.")
        print(f"(scanned {len(emails)} most recent)")
        return

    print(f"{'created_at':<26} {'last_event':<12} {'to':<32} subject")
    print('-' * 110)
    for created, to, event, subject, _id in sorted(rows):
        print(f"{created:<26} {event:<12} {to:<32} {subject[:40]}")
    print(f"\n{len(rows)} matching / {len(emails)} scanned")

    non_delivered = [r for r in rows if r[2] not in ('delivered', 'sent', 'opened', 'clicked')]
    if non_delivered:
        print("\nNot delivered:")
        for created, to, event, subject, _id in non_delivered:
            print(f"  {event:<12} {to}  ({subject[:40]})  id={_id}")


if __name__ == '__main__':
    main()
