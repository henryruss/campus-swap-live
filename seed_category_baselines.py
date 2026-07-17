#!/usr/bin/env python3
"""Seed InventoryCategory.baseline_price for the AI Autofill flow.

Baselines are grounded in real median sale prices per subcategory (see the
2026-07-17 pricing analysis). Subcategories with thin/no sales history use
estimates from category norms. Top-level categories carry a FALLBACK baseline
used when an item has no subcategory (or an "Other X" subcategory with no
dedicated number).

Idempotent: safe to re-run. Only writes rows whose baseline differs. Matches
categories by name (subcategories are disambiguated by their parent category),
so it is robust to differing category IDs between local and production.

Usage:
    python seed_category_baselines.py            # apply
    python seed_category_baselines.py --dry-run  # preview only
"""

import argparse
from decimal import Decimal

from app import app, db
from models import InventoryCategory

# Top-level category name -> fallback baseline (used when no subcategory match).
CATEGORY_FALLBACKS = {
    'Furniture': 75,
    'Bedroom': 65,
    'Kitchen & Appliances': 50,
    'Electronics': 60,
    'Climate & Comfort': 60,
    'Rugs': 45,
    'Bikes & Scooters': 130,
    'Other': 40,
}

# Subcategory name -> baseline. Names are unique enough across the taxonomy that
# a plain name match is safe; where a generic name could collide we scope by
# parent below in apply().
SUBCATEGORY_BASELINES = {
    # Furniture
    'Couch / Sofa': 325,
    'Futon': 120,
    'Armchair / Accent Chair': 120,
    'Dresser': 110,
    'Desk': 75,
    'TV Stand / Media Console': 65,
    'Desk Chair': 50,
    'Gaming Chair': 80,
    'Coffee Table': 40,
    'Side Table': 40,
    'Bookshelf / Shelving': 25,
    'Storage Ottoman': 35,
    'Other Furniture': 50,
    # Bedroom
    'Mattress': 85,
    'Headboard': 65,
    'Other Bedroom': 60,
    # Kitchen & Appliances
    'Mini Fridge': 95,
    'Microwave': 45,
    'Air Fryer': 35,
    'Coffee Maker / Espresso Machine': 40,
    'Instant Pot / Rice Cooker': 35,
    'Blender': 25,
    'Knife Set': 30,
    'Toaster Oven': 30,
    'Other Kitchen': 30,
    # Electronics
    'TV': 130,
    'Monitor': 70,
    'Laptop': 200,
    'Gaming Console': 120,
    'Speakers / Soundbar': 80,
    'Headphones': 40,
    'Keyboard / Mouse': 25,
    'Printer / Scanner': 35,
    'Other Electronics': 30,
    # Climate & Comfort
    'Portable AC Unit': 120,
    'Space Heater': 25,
    'Tower Fan': 30,
    'Humidifier / Dehumidifier': 40,
    'Other Climate': 40,
    # Rugs
    'Area Rug': 45,
    # Bikes & Scooters
    'Bike': 150,
    'Electric Scooter': 150,
}


def apply(dry_run: bool) -> None:
    cats = InventoryCategory.query.all()
    changed = 0
    skipped_no_baseline = []

    for cat in cats:
        is_top = cat.parent_id is None
        if is_top:
            target = CATEGORY_FALLBACKS.get(cat.name)
        else:
            target = SUBCATEGORY_BASELINES.get(cat.name)

        if target is None:
            skipped_no_baseline.append(cat.name)
            continue

        target_dec = Decimal(str(target))
        if cat.baseline_price is None or Decimal(cat.baseline_price) != target_dec:
            old = cat.baseline_price
            print(f"  {'[dry] ' if dry_run else ''}{cat.name}: {old} -> {target_dec}")
            if not dry_run:
                cat.baseline_price = target_dec
            changed += 1

    if not dry_run:
        db.session.commit()

    print(f"\n{'Would update' if dry_run else 'Updated'} {changed} categor(y/ies).")
    if skipped_no_baseline:
        print(f"No baseline defined for {len(skipped_no_baseline)} categor(y/ies) "
              f"(left as-is): {', '.join(sorted(skipped_no_baseline))}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed category baseline prices for AI Autofill")
    parser.add_argument('--dry-run', action='store_true', help="Preview changes without writing")
    args = parser.parse_args()
    with app.app_context():
        apply(args.dry_run)


if __name__ == '__main__':
    main()
