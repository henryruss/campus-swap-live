"""Price the mattress unit at a flat rate per size.

Mattresses are priced by size rather than appraised individually, so this sets a
price on every unpriced item in the mattress unit. Items whose size was never
recorded get DEFAULT_PRICE.

Dry run by default — prints exactly what it would change and commits nothing:

    python3 scripts/price_mattresses.py
    python3 scripts/price_mattresses.py --apply

To run against production, set DATABASE_URL to the production database first (or
run it from the Render shell, where it is already set).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db  # noqa: E402
from models import InventoryItem, StorageLocation  # noqa: E402

MATTRESS_UNIT = 'Unit 119'

# Flat price per size. Adjust these and re-run.
PRICE_BY_SIZE = {
    'twin': 100.0,
    'twin_xl': 100.0,
    'full': 100.0,
    'queen': 100.0,
    'king': 100.0,
    'cal_king': 100.0,
}
DEFAULT_PRICE = 100.0       # size not recorded — flat rate, same as every other size


def main():
    apply_changes = '--apply' in sys.argv
    with app.app_context():
        loc = StorageLocation.query.filter_by(name=MATTRESS_UNIT).first()
        if not loc:
            raise SystemExit(f'{MATTRESS_UNIT} not found.')

        items = InventoryItem.query.filter(
            InventoryItem.storage_location_id == loc.id,
            InventoryItem.replaced_by_item_id.is_(None),
        ).order_by(InventoryItem.id).all()

        changed, total_units, total_value = [], 0, 0.0
        for i in items:
            qty = int(i.stock_quantity or 1)
            price = float(i.price) if i.price else 0.0
            if price > 0:
                total_units += qty
                total_value += price * qty
                continue
            new_price = PRICE_BY_SIZE.get(i.mattress_size or '', DEFAULT_PRICE)
            changed.append((i, new_price, qty))
            total_units += qty
            total_value += new_price * qty

        print(f'\n{MATTRESS_UNIT}: {len(items)} records, {total_units} physical units')
        print(f'{"item":>6}  {"size":<16}{"qty":>4}{"old":>7}{"new":>7}{"extended":>10}')
        for i, new_price, qty in changed:
            print(f'{i.id:>6}  {(i.mattress_size or "—"):<16}{qty:>4}'
                  f'{"$0":>7}{"$" + format(new_price, ".0f"):>7}'
                  f'{"$" + format(new_price * qty, ",.0f"):>10}')
        print(f'\n  would price {len(changed)} records covering '
              f'{sum(q for _, _, q in changed)} units')
        print(f'  unit value after pricing: ${total_value:,.2f}')

        if not changed:
            print('\nNothing to do — every mattress already has a price.')
            return
        if apply_changes:
            for i, new_price, _ in changed:
                i.price = new_price
            db.session.commit()
            print(f'\nAPPLIED — {len(changed)} records priced.')
        else:
            print('\nDRY RUN — nothing written. Re-run with --apply to commit.')


if __name__ == '__main__':
    main()
