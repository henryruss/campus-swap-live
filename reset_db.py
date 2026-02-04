from app import app, db

# This script deletes the old database and creates a fresh one
# matching your current code.
with app.app_context():
    db.drop_all()   # Deletes everything
    db.create_all() # Creates fresh tables with the new columns
    print("✅ Database has been reset! You can now sign up.")