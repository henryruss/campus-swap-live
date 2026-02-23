#!/usr/bin/env python3
"""
Set a user as admin by email. Works for users who haven't signed up yet (pre-assignment).

Usage:
  FLASK_APP=app python set_admin.py your@email.com
  FLASK_APP=app python set_admin.py your@email.com --admin-only

If the user exists: grants admin immediately.
If the user doesn't exist: pre-assigns so they get admin when they sign up.
"""
import sys
import argparse

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Grant admin/super admin access by email')
    parser.add_argument('email', help='Email address')
    parser.add_argument('--admin-only', action='store_true',
                        help='Grant regular admin only (default: super admin)')
    args = parser.parse_args()

    email = args.email.strip()
    is_super = not args.admin_only

    from app import app, db
    from models import User, AdminEmail
    from sqlalchemy import func

    with app.app_context():
        email_lower = email.lower()
        user = User.query.filter(func.lower(User.email) == email_lower).first()
        if user:
            user.is_admin = True
            user.is_super_admin = is_super
            db.session.commit()
            print(f"Done! {email} is now a {'super ' if is_super else ''}admin.")
        else:
            existing = AdminEmail.query.filter_by(email=email_lower).first()
            if existing:
                existing.is_super_admin = is_super
                db.session.commit()
                print(f"Updated! {email} was already pre-assigned. Now {'super ' if is_super else ''}admin.")
            else:
                db.session.add(AdminEmail(email=email_lower, is_super_admin=is_super))
                db.session.commit()
                print(f"Pre-assigned! {email} will be a {'super ' if is_super else ''}admin when they sign up.")
