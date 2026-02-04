from app import app, db
from models import InventoryCategory

def reset_categories():
    with app.app_context():
        # 1. Clear existing categories
        db.session.query(InventoryCategory).delete()
        db.session.commit()
        
        # 2. YOUR Specific Categories mapped to Icons
        categories = [
            {"name": "Couch/Sofa", "icon": "fa-couch"},
            {"name": "Mattress", "icon": "fa-bed"}, 
            {"name": "Mini-Fridge", "icon": "fa-snowflake"}, 
            {"name": "Climate Control", "icon": "fa-wind"}, 
            {"name": "Television", "icon": "fa-tv"},
        ]
        
        # 3. Add them to DB
        for item in categories:
            new_cat = InventoryCategory(
                name=item["name"],
                image_url=item["icon"] 
            )
            db.session.add(new_cat)
        
        db.session.commit()
        print("✅ Categories reset with FontAwesome icons!")

if __name__ == "__main__":
    reset_categories()