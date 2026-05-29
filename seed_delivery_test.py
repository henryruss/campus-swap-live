"""
seed_delivery_test.py — Seed a fake seller + buyer orders for delivery feature testing.

Creates:
  - 1 [DEV-DELIVERY] seller: delivery.seller@unc.edu / password
  - 4 sold items with BuyerOrder records (appear in Unassigned Deliveries queue)
  - 1 sold item WITHOUT a BuyerOrder (should NOT appear in queue — edge case)

Safe to re-run — skips records that already exist.
To remove: python3 seed_delivery_test.py --delete

Usage:
    python3 seed_delivery_test.py
    python3 seed_delivery_test.py --delete
"""

import sys
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash
from app import app, db
from models import (
    User, InventoryCategory, InventoryItem, BuyerOrder,
)

TAG = '[DEV-DELIVERY]'
SELLER_EMAIL = 'delivery.seller@unc.edu'

DAYS = lambda n: datetime.utcnow() - timedelta(days=n)


BUYER_ORDERS = [
    # (item_desc, price, buyer_email, delivery_address, delivery_lat, delivery_lng, days_ago)
    (
        f'{TAG} IKEA MALM Dresser (6-drawer)',
        150,
        'buyer.one@unc.edu',
        '101 Manning Dr, Chapel Hill, NC 27514',
        35.9049,  -79.0469,
        5,
    ),
    (
        f'{TAG} Mini Fridge (black, 3.2 cu ft)',
        90,
        'buyer.two@gmail.com',
        '415 W Franklin St, Chapel Hill, NC 27516',
        35.9132, -79.0558,
        3,
    ),
    (
        f'{TAG} Gaming Chair (DXRacer)',
        120,
        'buyer.three@unc.edu',
        '200 South Rd, Chapel Hill, NC 27514',
        35.9115, -79.0499,
        8,
    ),
    (
        f'{TAG} 32" Monitor (LG)',
        180,
        'buyer.four@example.com',
        '1 University Dr, Chapel Hill, NC 27599',
        35.9049, -79.0469,
        1,
    ),
]

# This item has NO BuyerOrder — should NOT appear in the delivery queue
NO_ORDER_ITEM = f'{TAG} Desk Lamp (no buyer order — should not appear in queue)'


def _get_or_none(email):
    return User.query.filter_by(email=email).first()


def _first_cat(name):
    cat = InventoryCategory.query.filter(InventoryCategory.name.ilike(f'%{name}%')).first()
    return cat or InventoryCategory.query.first()


def seed():
    with app.app_context():
        print('Seeding delivery test data...\n')

        # --- Seller ---
        seller = _get_or_none(SELLER_EMAIL)
        if not seller:
            seller = User(
                email=SELLER_EMAIL,
                full_name='[DEV-DELIVERY] Sam Seller',
                password_hash=generate_password_hash('password'),
                is_seller=True,
                payout_rate=40,
                payout_method='Venmo',
                payout_handle='@sam-seller-dev',
            )
            db.session.add(seller)
            db.session.flush()
            print(f'  ✓ Seller created: {SELLER_EMAIL} / password')
        else:
            print(f'  · Seller already exists: {SELLER_EMAIL}')

        # --- Items with BuyerOrders ---
        for (desc, price, buyer_email, address, lat, lng, days_ago) in BUYER_ORDERS:
            existing = InventoryItem.query.filter_by(description=desc, seller_id=seller.id).first()
            if existing:
                print(f'  · Item already exists: {desc[:50]}')
                continue

            cat = _first_cat('Mini Fridge') if 'Fridge' in desc else _first_cat('Furniture')
            item = InventoryItem(
                description=desc,
                price=price,
                status='sold',
                quality=3,
                collection_method='online',
                category_id=cat.id,
                seller_id=seller.id,
                date_added=DAYS(days_ago + 10),
                sold_at=DAYS(days_ago),
            )
            db.session.add(item)
            db.session.flush()

            order = BuyerOrder(
                item_id=item.id,
                buyer_email=buyer_email,
                delivery_address=address,
                delivery_lat=lat,
                delivery_lng=lng,
                created_at=DAYS(days_ago),
            )
            db.session.add(order)
            print(f'  ✓ Item + BuyerOrder: {desc[:55]} → {buyer_email}')

        # --- Item with NO BuyerOrder (edge-case check) ---
        no_order = InventoryItem.query.filter_by(description=NO_ORDER_ITEM, seller_id=seller.id).first()
        if not no_order:
            cat = _first_cat('Other')
            item = InventoryItem(
                description=NO_ORDER_ITEM,
                price=25,
                status='sold',
                quality=3,
                collection_method='online',
                category_id=cat.id,
                seller_id=seller.id,
                date_added=DAYS(20),
                sold_at=DAYS(2),
            )
            db.session.add(item)
            print(f'  ✓ Sold item (no BuyerOrder): {NO_ORDER_ITEM[:60]}')
        else:
            print(f'  · No-order item already exists')

        db.session.commit()

        print('\n' + '─' * 60)
        print('Delivery test seed complete.\n')
        print(f'  Seller login: {SELLER_EMAIL} / password')
        print()
        print('  Unassigned Deliveries queue should show 4 orders:')
        for (desc, price, buyer_email, address, *_) in BUYER_ORDERS:
            print(f'    ${price:>3}  {buyer_email:<30}  {address[:40]}')
        print()
        print('  The "no BuyerOrder" item should NOT appear in the queue.')
        print('─' * 60)


def delete():
    with app.app_context():
        seller = _get_or_none(SELLER_EMAIL)
        if not seller:
            print('Seller not found — nothing to delete.')
            return

        items = InventoryItem.query.filter(
            InventoryItem.description.like(f'{TAG}%'),
            InventoryItem.seller_id == seller.id,
        ).all()

        for item in items:
            if item.buyer_order:
                db.session.delete(item.buyer_order)
            db.session.delete(item)

        db.session.delete(seller)
        db.session.commit()
        print(f'Deleted delivery test seed ({len(items)} items + seller).')


if __name__ == '__main__':
    if '--delete' in sys.argv:
        delete()
    else:
        seed()
