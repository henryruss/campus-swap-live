#!/usr/bin/env python3
"""
Campus Swap — Shop Purge Verification (READ ONLY)
=================================================
Reports how many items the "re-photographed only" shop filter purges from
Shop the Drop, and lists the legacy items that would drop out. Makes NO writes
of any kind — safe to run on production (Render shell).

The purge criterion (see app.py `_rephotographed_clause`): an item is kept only
if it has at least one ItemPhoto with captured_at set (a warehouse re-photography
campaign photo). Legacy pre-campaign listings have every captured_at NULL.

Usage (local):    python3 verify_shop_purge.py
Usage (Render):   python verify_shop_purge.py
"""

from app import app, db
from models import InventoryItem, ItemPhoto
from sqlalchemy import and_


def _base_shop_filter():
    """The /shop visibility filter WITHOUT the re-photographed requirement."""
    return [
        InventoryItem.ai_approved == True,          # noqa: E712
        InventoryItem.status == 'available',
        InventoryItem.needs_new_photo == False,     # noqa: E712
        InventoryItem.status != 'rejected',
        InventoryItem.price.isnot(None),
        InventoryItem.price > 0,
        InventoryItem.storage_location_id.isnot(None),
        InventoryItem.rephoto_disposition.is_distinct_from('discarded'),
    ]


def _rephotographed_clause():
    return InventoryItem.id.in_(
        db.session.query(ItemPhoto.item_id)
        .filter(ItemPhoto.captured_at.isnot(None))
        .distinct()
    )


def main():
    with app.app_context():
        base = InventoryItem.query.filter(and_(*_base_shop_filter()))
        before = base.count()
        after = base.filter(_rephotographed_clause()).count()
        purged_q = base.filter(~_rephotographed_clause()).order_by(
            InventoryItem.date_added.desc()
        )
        purged = purged_q.all()

        print("=" * 70)
        print("SHOP PURGE VERIFICATION (read-only)")
        print("=" * 70)
        print(f"Shop-visible BEFORE purge (all approved/available): {before}")
        print(f"Shop-visible AFTER purge  (re-photographed only):  {after}")
        print(f"Legacy items that will be PURGED:                  {len(purged)}")
        print("-" * 70)
        if not purged:
            print("Nothing to purge — every shop-visible item is re-photographed.")
            return
        print(f"{'ID':>6}  {'SELLER':>7}  {'ADDED':<10}  TITLE")
        print("-" * 70)
        for it in purged:
            seller = it.seller_id if it.seller_id is not None else '—'
            added = it.date_added.strftime('%Y-%m-%d') if it.date_added else '—'
            title = (it.description or '(no title)')[:45]
            print(f"{it.id:>6}  {str(seller):>7}  {added:<10}  {title}")
        print("-" * 70)
        print(f"Total to purge: {len(purged)}")


if __name__ == '__main__':
    main()
