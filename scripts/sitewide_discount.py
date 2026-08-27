"""Apply a site-wide discount to every live shop listing.

Scope is status='available' — what buyers can actually see and buy. Sold items are
never touched, so payout and revenue history stays accurate.

Prices land on a charm ending (a whole dollar ending in 9 or 5) where one exists
inside the discount band, and on a plain whole dollar where one does not. Charm
endings are only twice per decade, so rounding down to one unconditionally is
brutal on cheap listings -- a $30 item targets $24 and the next charm value down
is $19, i.e. 37% off. Requiring the result to stay inside the band caps that: every
listing lands between DISCOUNT_PCT and MAX_DISCOUNT_PCT off, and reads as a sale
price whenever the ladder allows.

Seller payout is 50% of item.price and is computed at runtime, so cutting the price
cuts the payout by the same percentage. That is intentional here — seller and Campus
Swap split the discount evenly.

Dry run by default. Prints every change and commits nothing:

    python3 scripts/sitewide_discount.py
    python3 scripts/sitewide_discount.py --apply

--apply writes a snapshot CSV of (id, old_price, new_price) BEFORE committing and
also dumps it to stdout. To undo:

    python3 scripts/sitewide_discount.py --revert <snapshot.csv>
    python3 scripts/sitewide_discount.py --revert <snapshot.csv> --apply

To run against production, set DATABASE_URL to the production database first, or run
it from the Render shell where it is already set.
"""
import csv
import math
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db  # noqa: E402
from models import InventoryItem  # noqa: E402

DISCOUNT_PCT = 0.20        # headline discount
MAX_DISCOUNT_PCT = 0.25    # never go deeper than this to reach a charm ending
MIN_PRICE = 5.0            # never take a listing below this
DEEP_FLAG_PCT = 0.25       # dry run flags anything landing deeper than this
CHARM_ENDINGS = (9, 5)


def discounted_price(old):
    """Sale price for `old`: a charm ending inside the band, else a whole dollar.

    The band runs from DISCOUNT_PCT off down to MAX_DISCOUNT_PCT off. Charm endings
    are sparse, so insisting on one at any depth savages cheap listings; insisting on
    one only inside the band keeps every item within a few points of the headline.
    """
    ceiling = math.floor(old * (1 - DISCOUNT_PCT))      # at least DISCOUNT_PCT off
    floor = math.ceil(old * (1 - MAX_DISCOUNT_PCT))     # at most MAX_DISCOUNT_PCT off
    for v in range(int(ceiling), int(floor) - 1, -1):
        if v % 10 in CHARM_ENDINGS:
            return float(v)
    return float(ceiling) if ceiling >= floor else None


def live_items():
    """Listings a buyer can reach. Purged legacy listings are excluded."""
    return InventoryItem.query.filter(
        InventoryItem.status == 'available',
        InventoryItem.rephoto_disposition.is_distinct_from('discarded'),
    ).order_by(InventoryItem.id).all()


def plan_discount():
    """[(item, old_price, new_price)] for every listing that actually changes."""
    changes, skipped = [], []
    for item in live_items():
        old = float(item.price) if item.price else 0.0
        if old <= 0:
            skipped.append((item, old, 'no price set'))
            continue
        new = discounted_price(old)
        if new is None or new < MIN_PRICE:
            skipped.append((item, old, f'discounted price would fall below ${MIN_PRICE:.0f}'))
            continue
        if new >= old:
            skipped.append((item, old, 'charm rounding would not lower the price'))
            continue
        changes.append((item, old, new))
    return changes, skipped


def report(changes, skipped):
    deep = []
    old_total = new_total = 0.0
    print(f'{"ID":>6}  {"OLD":>8}  {"NEW":>8}  {"OFF":>5}  DESCRIPTION')
    print('-' * 78)
    for item, old, new in changes:
        pct = (old - new) / old
        old_total += old
        new_total += new
        flag = ' *' if pct > DEEP_FLAG_PCT else '  '
        if pct > DEEP_FLAG_PCT:
            deep.append((item, old, new, pct))
        print(f'{item.id:>6}  {old:>8.2f}  {new:>8.2f}  {pct*100:>4.0f}%{flag}{(item.description or "")[:44]}')

    print()
    print(f'Listings changed:     {len(changes)}')
    print(f'Listings skipped:     {len(skipped)}')
    if old_total:
        print(f'Catalog value:        ${old_total:,.2f} -> ${new_total:,.2f}')
        print(f'Effective discount:   {(old_total - new_total) / old_total * 100:.1f}%')
        print(f'Seller payouts (50%): ${old_total/2:,.2f} -> ${new_total/2:,.2f}')

    if deep:
        print()
        print(f'*** {len(deep)} listing(s) land deeper than {DEEP_FLAG_PCT*100:.0f}% off '
              f'(charm rounding rounds DOWN):')
        for item, old, new, pct in sorted(deep, key=lambda r: -r[3]):
            print(f'    #{item.id:<6} ${old:.2f} -> ${new:.2f}  ({pct*100:.0f}% off)  '
                  f'{(item.description or "")[:40]}')

    if skipped:
        print()
        print('Skipped:')
        for item, old, reason in skipped:
            print(f'    #{item.id:<6} ${old:.2f}  {reason}')


def write_snapshot(changes):
    for directory in ('/var/data', os.getcwd()):
        if os.path.isdir(directory) and os.access(directory, os.W_OK):
            break
    path = os.path.join(
        directory, f'discount_snapshot_{datetime.utcnow():%Y%m%dT%H%M%SZ}.csv')
    with open(path, 'w', newline='') as fh:
        writer = csv.writer(fh)
        writer.writerow(['item_id', 'old_price', 'new_price'])
        for item, old, new in changes:
            writer.writerow([item.id, f'{old:.2f}', f'{new:.2f}'])
    return path


def do_discount(apply_changes):
    changes, skipped = plan_discount()
    report(changes, skipped)
    if not changes:
        print('\nNothing to change.')
        return
    if not apply_changes:
        print('\nDRY RUN — nothing written. Re-run with --apply to commit.')
        return

    path = write_snapshot(changes)
    print(f'\nSnapshot written to {path}')
    print('--- SNAPSHOT (copy this out of the terminal as a backup) ---')
    print('item_id,old_price,new_price')
    for item, old, new in changes:
        print(f'{item.id},{old:.2f},{new:.2f}')
    print('--- END SNAPSHOT ---')

    for item, _old, new in changes:
        item.price = new
    db.session.commit()
    print(f'\nApplied. {len(changes)} listing(s) discounted.')
    print(f'To undo: python3 scripts/sitewide_discount.py --revert {path} --apply')


def do_revert(path, apply_changes):
    with open(path) as fh:
        rows = list(csv.DictReader(fh))
    print(f'{"ID":>6}  {"NOW":>8}  {"RESTORE":>8}  STATUS')
    print('-' * 60)
    restores, missing = [], []
    for row in rows:
        item = db.session.get(InventoryItem, int(row['item_id']))
        if item is None:
            missing.append(row['item_id'])
            continue
        now = float(item.price) if item.price else 0.0
        old = float(row['old_price'])
        expected = float(row['new_price'])
        # A price edited by hand since the discount is not ours to overwrite.
        note = 'ok' if abs(now - expected) < 0.005 else 'CHANGED SINCE DISCOUNT — skipping'
        print(f'{item.id:>6}  {now:>8.2f}  {old:>8.2f}  {note}')
        if note == 'ok':
            restores.append((item, old))

    print()
    print(f'Will restore: {len(restores)} of {len(rows)}')
    if missing:
        print(f'Missing items (deleted?): {", ".join(missing)}')
    if not apply_changes:
        print('\nDRY RUN — nothing written. Re-run with --apply to commit.')
        return
    for item, old in restores:
        item.price = old
    db.session.commit()
    print(f'\nReverted {len(restores)} listing(s).')


def main():
    apply_changes = '--apply' in sys.argv
    with app.app_context():
        db_url = str(db.engine.url).split('@')[-1]
        print(f'Database: {db_url}')
        print(f'Mode:     {"APPLY (writes)" if apply_changes else "DRY RUN"}\n')
        if '--revert' in sys.argv:
            path = sys.argv[sys.argv.index('--revert') + 1]
            do_revert(path, apply_changes)
        else:
            do_discount(apply_changes)


if __name__ == '__main__':
    main()
