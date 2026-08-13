"""Send a one-off email to every real seller (buyers excluded).

Subject is the file's first line; the rest of the file is the HTML body.

Dry run by default — prints who it would email and commits nothing:

    python3 scripts/email_sellers.py path/to/email.html
    python3 scripts/email_sellers.py path/to/email.html --send

To run against production, set DATABASE_URL to the production database first
(or run it from the Render shell, where it is already set).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, send_email  # noqa: E402
from models import User  # noqa: E402


def main():
    args = [a for a in sys.argv[1:] if a != '--send']
    if not args:
        raise SystemExit('usage: python3 scripts/email_sellers.py <file.html> [--send]')
    do_send = '--send' in sys.argv

    with open(args[0]) as f:
        lines = f.read().splitlines()
    subject = lines[0].strip()
    html_content = '\n'.join(lines[1:]).strip()
    if not subject or not html_content:
        raise SystemExit('file must have the subject on line 1 and the HTML body after it')

    base_url = os.environ.get('APP_BASE_URL') or os.environ.get('BASE_URL') or 'https://usecampusswap.com'
    with app.test_request_context(base_url=base_url):
        sellers = User.query.filter(
            User.email.isnot(None),
            User.unsubscribed != True,  # noqa: E712
            User.is_seller == True,  # noqa: E712
            User.is_tutorial_user != True,  # noqa: E712
            User.is_internal_account != True,  # noqa: E712
        ).order_by(User.id).all()

        print(f'\nSubject: {subject}')
        print(f'{len(sellers)} sellers would receive this email:')
        for u in sellers:
            print(f'  {u.id:>6}  {u.email}')

        if not do_send:
            print(f'\nDRY RUN — nothing sent. Re-run with --send to actually email {len(sellers)} sellers.')
            return

        sent, failed = 0, []
        for u in sellers:
            ok = send_email(u.email, subject, html_content, is_marketing=True, user=u)
            if ok:
                sent += 1
            else:
                failed.append(u.email)

        print(f'\nSENT — {sent}/{len(sellers)} delivered.')
        if failed:
            print(f'Failed ({len(failed)}): {", ".join(failed)}')


if __name__ == '__main__':
    main()
