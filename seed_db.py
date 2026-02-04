from app import app, db
from models import InventoryCategory

# This script populates your DB with the standard categories
with app.app_context():
    # 1. Commodities (Things we count)
    commodities = [
        {"name": "Twin XL Mattress", "icon": "🛏️", "is_commodity": True},
        {"name": "Mini Fridge", "icon": "❄️", "is_commodity": True},
        {"name": "Box Fan", "icon": "💨", "is_commodity": True},
        {"name": "Desk Lamp", "icon": "💡", "is_commodity": True},
    ]

    # 2. Uniques (Things we photograph)
    uniques = [
        {"name": "Couch / Sofa", "icon": "🛋️", "is_commodity": False},
        {"name": "Armchair", "icon": "🪑", "is_commodity": False},
        {"name": "Unique Decor", "icon": "🖼️", "is_commodity": False},
        {"name": "Rug", "icon": "🧶", "is_commodity": False},
    ]

    # Add them to DB if they don't exist
    for item in commodities + uniques:
        exists = InventoryCategory.query.filter_by(name=item["name"]).first()
        if not exists:
            new_cat = InventoryCategory(
                name=item["name"], 
                image_url=item["icon"], # We are using Emojis as icons for now!
                is_commodity=item["is_commodity"]
            )
            db.session.add(new_cat)
    
    db.session.commit()
    print("✅ Inventory Categories Seeded!")