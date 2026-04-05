"""
Nuclear reset: wipe all categories + items, then re-seed from scratch.

Usage:
    python3 reset_categories.py           # categories only
    python3 reset_categories.py --items   # categories + dummy items
"""

import sys


def reset(include_items=False):
    from app import app, db
    from models import InventoryCategory, InventoryItem, ItemPhoto

    with app.app_context():
        # Wipe items and photos first (FK constraints)
        ItemPhoto.query.delete()
        InventoryItem.query.delete()
        InventoryCategory.query.delete()
        db.session.commit()
        print("Cleared all categories, items, and photos.")

    # Now re-seed using the shared seed script
    from seed_categories import seed
    seed(include_items=include_items)


if __name__ == "__main__":
    include_items = "--items" in sys.argv
    reset(include_items=include_items)
