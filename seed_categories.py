"""
Seed script for the two-level category taxonomy + dummy items.
Idempotent — safe to run multiple times.

Usage:
    python3 seed_categories.py           # categories only
    python3 seed_categories.py --items   # categories + one dummy item per subcategory
"""

import sys

TAXONOMY = [
    {
        "name": "Furniture",
        "icon": "fa-couch",
        "subs": [
            "Couch / Sofa", "Futon", "Armchair / Accent Chair", "Desk", "Desk Chair",
            "Gaming Chair", "Bookshelf / Shelving", "Dresser", "Coffee Table",
            "Side Table", "TV Stand / Media Console", "Storage Ottoman", "Other Furniture",
        ],
    },
    {
        "name": "Bedroom",
        "icon": "fa-bed",
        "subs": ["Mattress", "Headboard", "Other Bedroom"],
    },
    {
        "name": "Kitchen & Appliances",
        "icon": "fa-blender",
        "subs": [
            "Mini Fridge", "Microwave", "Coffee Maker / Espresso Machine", "Air Fryer",
            "Blender", "Toaster Oven", "Knife Set", "Instant Pot / Rice Cooker",
            "Other Kitchen",
        ],
    },
    {
        "name": "Electronics",
        "icon": "fa-tv",
        "subs": [
            "TV", "Monitor", "Laptop", "Gaming Console", "Speakers / Soundbar",
            "Headphones", "Keyboard / Mouse", "Other Electronics",
        ],
    },
    {
        "name": "Climate & Comfort",
        "icon": "fa-fan",
        "subs": [
            "Portable AC Unit", "Space Heater", "Tower Fan",
            "Humidifier / Dehumidifier", "Other Climate",
        ],
    },
    {
        "name": "Rugs",
        "icon": "fa-th-large",
        "subs": ["Area Rug"],
    },
    {
        "name": "Bikes & Scooters",
        "icon": "fa-bicycle",
        "subs": ["Bike", "Electric Scooter"],
    },
    {
        "name": "Other",
        "icon": "fa-box-open",
        "subs": [],
    },
]

# Dummy item descriptions and prices for each subcategory (and parent-only categories)
DUMMY_ITEMS = {
    # Furniture
    "Couch / Sofa":             ("Gray L-Shaped Sectional Sofa", 120.00),
    "Futon":                    ("Black Futon with Armrests", 65.00),
    "Armchair / Accent Chair":  ("Blue Velvet Accent Chair", 45.00),
    "Desk":                     ("IKEA MALM White Desk", 40.00),
    "Desk Chair":               ("Mesh Ergonomic Desk Chair", 55.00),
    "Gaming Chair":             ("Red/Black Racing Gaming Chair", 80.00),
    "Bookshelf / Shelving":     ("5-Tier Wooden Bookshelf", 35.00),
    "Dresser":                  ("4-Drawer Oak Dresser", 60.00),
    "Coffee Table":             ("Round Glass Coffee Table", 30.00),
    "Side Table":               ("Nightstand with Drawer", 20.00),
    "TV Stand / Media Console": ("Modern TV Stand 55-inch", 50.00),
    "Storage Ottoman":          ("Gray Fabric Storage Ottoman", 25.00),
    "Other Furniture":          ("Folding Card Table", 15.00),
    # Bedroom
    "Mattress":                 ("Queen Memory Foam Mattress", 150.00),
    "Headboard":                ("Upholstered Queen Headboard", 45.00),
    "Other Bedroom":            ("Full-Length Mirror", 20.00),
    # Kitchen & Appliances
    "Mini Fridge":              ("Galanz 3.3 cu ft Mini Fridge", 75.00),
    "Microwave":                ("Hamilton Beach 1000W Microwave", 35.00),
    "Coffee Maker / Espresso Machine": ("Keurig K-Mini Coffee Maker", 30.00),
    "Air Fryer":                ("Ninja 4-Qt Air Fryer", 40.00),
    "Blender":                  ("NutriBullet Pro Blender", 25.00),
    "Toaster Oven":             ("Black+Decker Toaster Oven", 20.00),
    "Knife Set":                ("8-Piece Kitchen Knife Block", 15.00),
    "Instant Pot / Rice Cooker":("Instant Pot Duo 6-Qt", 35.00),
    "Other Kitchen":            ("Brita Water Pitcher", 10.00),
    # Electronics
    "TV":                       ("TCL 43-inch Roku TV", 90.00),
    "Monitor":                  ("Dell 24-inch IPS Monitor", 70.00),
    "Laptop":                   ("MacBook Air M1 2020", 450.00),
    "Gaming Console":           ("Nintendo Switch with Dock", 180.00),
    "Speakers / Soundbar":      ("JBL Flip 5 Bluetooth Speaker", 40.00),
    "Headphones":               ("Sony WH-1000XM4 Headphones", 95.00),
    "Keyboard / Mouse":         ("Logitech MX Keys + MX Master 3", 60.00),
    "Other Electronics":        ("Roku Streaming Stick", 15.00),
    # Climate & Comfort
    "Portable AC Unit":         ("Black+Decker Portable AC 8000 BTU", 120.00),
    "Space Heater":             ("Lasko Ceramic Tower Heater", 25.00),
    "Tower Fan":                ("Honeywell QuietSet Tower Fan", 30.00),
    "Humidifier / Dehumidifier":("Levoit Ultrasonic Humidifier", 20.00),
    "Other Climate":            ("Heated Blanket — Queen", 15.00),
    # Rugs
    "Area Rug":                 ("5x7 Bohemian Area Rug", 35.00),
    # Bikes & Scooters
    "Bike":                     ("Schwinn Hybrid Bike 21-Speed", 100.00),
    "Electric Scooter":         ("Segway Ninebot E22 Scooter", 150.00),
    # Other (parent-level)
    "Other":                    ("Cornhole Board Set", 25.00),
}


def seed(include_items=False):
    from app import app, db
    from models import InventoryCategory, InventoryItem

    with app.app_context():
        old_cat_ids = [c.id for c in InventoryCategory.query.filter_by(parent_id=None).all()]

        created_parents = 0
        created_subs = 0
        new_parent_ids = []

        for entry in TAXONOMY:
            existing = InventoryCategory.query.filter_by(name=entry["name"], parent_id=None).first()
            if existing and existing.icon == entry["icon"]:
                new_parent_ids.append(existing.id)
                existing_sub_names = {s.name for s in InventoryCategory.query.filter_by(parent_id=existing.id).all()}
                for sub_name in entry["subs"]:
                    if sub_name not in existing_sub_names:
                        sub = InventoryCategory(name=sub_name, parent_id=existing.id, count_in_stock=0)
                        db.session.add(sub)
                        created_subs += 1
                continue

            parent = InventoryCategory(
                name=entry["name"],
                icon=entry["icon"],
                image_url=entry["icon"],
                parent_id=None,
                count_in_stock=0,
            )
            db.session.add(parent)
            db.session.flush()
            new_parent_ids.append(parent.id)
            created_parents += 1

            for sub_name in entry["subs"]:
                sub = InventoryCategory(
                    name=sub_name,
                    icon=None,
                    image_url=None,
                    parent_id=parent.id,
                    count_in_stock=0,
                )
                db.session.add(sub)
                created_subs += 1

        db.session.commit()

        # Reassign orphan items to "Other"
        other_cat = InventoryCategory.query.filter_by(name="Other", parent_id=None).first()
        if other_cat:
            items_to_fix = InventoryItem.query.filter(
                ~InventoryItem.category_id.in_(new_parent_ids)
            ).all()
            reassigned = 0
            for item in items_to_fix:
                item.category_id = other_cat.id
                item.subcategory_id = None
                reassigned += 1
            if reassigned:
                db.session.commit()
                print(f"   Reassigned {reassigned} item(s) to 'Other' category.")

        # Clean up old categories
        old_to_delete = InventoryCategory.query.filter(
            InventoryCategory.id.in_(old_cat_ids),
            ~InventoryCategory.id.in_(new_parent_ids),
        ).all()
        for old in old_to_delete:
            if InventoryItem.query.filter_by(category_id=old.id).count() == 0:
                db.session.delete(old)
        db.session.commit()

        print(f"Done: {created_parents} parent categories, {created_subs} subcategories.")

        # Print summary
        for parent in InventoryCategory.query.filter_by(parent_id=None).order_by(InventoryCategory.id).all():
            subs = InventoryCategory.query.filter_by(parent_id=parent.id).all()
            sub_names = ", ".join(s.name for s in subs) if subs else "(none)"
            print(f"   {parent.icon}  {parent.name} -> {sub_names}")

        # Seed dummy items
        if include_items:
            print()
            created_items = 0
            statuses = ['available', 'pending_valuation', 'approved', 'sold']

            for parent in InventoryCategory.query.filter_by(parent_id=None).order_by(InventoryCategory.id).all():
                subs = InventoryCategory.query.filter_by(parent_id=parent.id).all()

                if subs:
                    for i, sub in enumerate(subs):
                        desc, price = DUMMY_ITEMS.get(sub.name, (f"Sample {sub.name}", 25.00))
                        if InventoryItem.query.filter_by(description=desc, category_id=parent.id).first():
                            continue
                        status = statuses[i % len(statuses)]
                        item = InventoryItem(
                            category_id=parent.id,
                            subcategory_id=sub.id,
                            description=desc,
                            long_description=f"Demo item for {parent.name} > {sub.name}. In great condition.",
                            price=price if status != 'pending_valuation' else None,
                            suggested_price=price,
                            quality=5 - (i % 3),  # rotate 5, 4, 3
                            status=status,
                            collection_method='online',
                            photo_url="",
                        )
                        if status == 'available':
                            parent.count_in_stock = (parent.count_in_stock or 0) + 1
                        db.session.add(item)
                        created_items += 1
                else:
                    desc, price = DUMMY_ITEMS.get(parent.name, (f"Sample {parent.name} Item", 25.00))
                    if InventoryItem.query.filter_by(description=desc, category_id=parent.id).first():
                        continue
                    item = InventoryItem(
                        category_id=parent.id,
                        subcategory_id=None,
                        description=desc,
                        long_description=f"Demo item for {parent.name}. In great condition.",
                        price=price,
                        suggested_price=price,
                        quality=4,
                        status='available',
                        collection_method='online',
                        photo_url="",
                    )
                    parent.count_in_stock = (parent.count_in_stock or 0) + 1
                    db.session.add(item)
                    created_items += 1

            db.session.commit()
            print(f"Done: {created_items} dummy items created.")
            print(f"   Statuses rotate: available, pending_valuation, approved, sold")


if __name__ == "__main__":
    include_items = "--items" in sys.argv
    seed(include_items=include_items)
