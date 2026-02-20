#!/usr/bin/env python3
"""
Set a user as admin by email.
Usage: FLASK_APP=app python set_admin.py your@email.com

Run from the project directory (where app.py lives).
"""
import sys
import os

# Ensure we're in the right directory
if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: FLASK_APP=app python set_admin.py your@email.com")
        print("Example: FLASK_APP=app python set_admin.py henry@campusswap.com")
        sys.exit(1)

    email = sys.argv[1].strip()

    # Load app and db
    from app import app, db
    from models import User

    with app.app_context():
        user = User.query.filter_by(email=email).first()
        if not user:
            print(f"No user found with email: {email}")
            sys.exit(1)

        user.is_admin = True
        user.is_super_admin = True
        db.session.commit()
        print(f"Done! {email} is now a super admin.")
