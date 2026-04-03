"""
Seed script for the two-level category taxonomy.
Idempotent — safe to run multiple times.

Usage:
    flask shell < seed_categories.py
    OR
    python seed_categories.py
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
        # Check for items referencing old categories
        item_count = InventoryItem.query.count()
        if item_count > 0:
            print(f"⚠  {item_count} items exist. Nulling their category_id and subcategory_id before re-seeding.")
            InventoryItem.query.update({
                InventoryItem.category_id: None,
                InventoryItem.subcategory_id: None,
            }, synchronize_session=False)
            db.session.commit()

            # Temporarily allow nullable category_id for the re-seed
            # (SQLite won't enforce NOT NULL during UPDATE, but we fix it after)

        # Delete all existing categories
        InventoryCategory.query.delete()
        db.session.commit()

        created_parents = 0
        created_subs = 0

        for entry in TAXONOMY:
            parent = InventoryCategory(
                name=entry["name"],
                icon=entry["icon"],
                image_url=entry["icon"],  # keep image_url in sync for legacy templates
                parent_id=None,
                count_in_stock=0,
            )
            db.session.add(parent)
            db.session.flush()  # get parent.id
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

        # If items existed, assign them to the first parent category (Other)
        if item_count > 0:
            other_cat = InventoryCategory.query.filter_by(name="Other", parent_id=None).first()
            if other_cat:
                InventoryItem.query.filter(InventoryItem.category_id.is_(None)).update(
                    {InventoryItem.category_id: other_cat.id}, synchronize_session=False
                )
                db.session.commit()
                print(f"   Reassigned {item_count} items to 'Other' category.")

        print(f"✓  Seeded {created_parents} parent categories and {created_subs} subcategories.")

        # Print summary
        for parent in InventoryCategory.query.filter_by(parent_id=None).order_by(InventoryCategory.id).all():
            subs = InventoryCategory.query.filter_by(parent_id=parent.id).all()
            sub_names = ", ".join(s.name for s in subs) if subs else "(none)"
            print(f"   {parent.icon}  {parent.name} → {sub_names}")


if __name__ == "__main__":
    seed()
