"""
Seed script for the two-level category taxonomy.
Idempotent — safe to run multiple times.

Usage:
    python3 seed_categories.py
"""

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
        "icon": "fa-th-large",  # fa-rug requires FA 6.2+; using fa-th-large for FA 6.0 compat
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


def seed():
    from app import app, db
    from models import InventoryCategory, InventoryItem

    with app.app_context():
        # Collect IDs of old categories (ones without the new parent_id structure)
        old_cat_ids = [c.id for c in InventoryCategory.query.filter_by(parent_id=None).all()]

        # Step 1: Create new parent categories + subcategories
        created_parents = 0
        created_subs = 0
        new_parent_ids = []

        for entry in TAXONOMY:
            # Skip if already seeded (idempotent check)
            existing = InventoryCategory.query.filter_by(name=entry["name"], parent_id=None).first()
            if existing and existing.icon == entry["icon"]:
                # Already seeded — check subcategories too
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

        # Step 2: Reassign any items on old categories to "Other"
        other_cat = InventoryCategory.query.filter_by(name="Other", parent_id=None).first()
        if other_cat:
            # Find items whose category_id is NOT one of the new parent IDs
            reassigned = 0
            items_to_fix = InventoryItem.query.filter(
                ~InventoryItem.category_id.in_(new_parent_ids)
            ).all()
            for item in items_to_fix:
                item.category_id = other_cat.id
                item.subcategory_id = None
                reassigned += 1
            if reassigned:
                db.session.commit()
                print(f"   Reassigned {reassigned} item(s) to 'Other' category.")

        # Step 3: Delete old categories that are no longer needed
        old_to_delete = InventoryCategory.query.filter(
            InventoryCategory.id.in_(old_cat_ids),
            ~InventoryCategory.id.in_(new_parent_ids),
        ).all()
        for old in old_to_delete:
            # Only delete if no items reference it
            if InventoryItem.query.filter_by(category_id=old.id).count() == 0:
                db.session.delete(old)
        db.session.commit()

        print(f"✓  Seeded {created_parents} new parent categories and {created_subs} new subcategories.")

        # Print summary
        for parent in InventoryCategory.query.filter_by(parent_id=None).order_by(InventoryCategory.id).all():
            subs = InventoryCategory.query.filter_by(parent_id=parent.id).all()
            sub_names = ", ".join(s.name for s in subs) if subs else "(none)"
            print(f"   {parent.icon}  {parent.name} → {sub_names}")


if __name__ == "__main__":
    seed()
