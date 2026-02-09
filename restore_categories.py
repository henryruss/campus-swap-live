from app import app, db
from models import InventoryCategory

def restore_categories():
    """Restore categories if they're missing - only adds if they don't exist"""
    with app.app_context():
        # Standard categories to ensure exist
        categories = [
            {"name": "Couch/Sofa", "icon": "fa-couch"},
            {"name": "Mattress", "icon": "fa-bed"}, 
            {"name": "Mini-Fridge", "icon": "fa-snowflake"}, 
            {"name": "Climate Control", "icon": "fa-wind"}, 
            {"name": "Television", "icon": "fa-tv"},
        ]
        
        added_count = 0
        for item in categories:
            exists = InventoryCategory.query.filter_by(name=item["name"]).first()
            if not exists:
                new_cat = InventoryCategory(
                    name=item["name"],
                    image_url=item["icon"],
                    count_in_stock=0
                )
                db.session.add(new_cat)
                added_count += 1
                print(f"✅ Added category: {item['name']}")
            else:
                print(f"⏭️  Category already exists: {item['name']}")
        
        db.session.commit()
        
        total = InventoryCategory.query.count()
        print(f"\n✅ Restore complete! Added {added_count} categories. Total categories: {total}")

if __name__ == "__main__":
    restore_categories()
