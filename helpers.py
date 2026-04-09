"""
helpers.py — thin re-export layer so tests can import helpers without importing app directly.
All real implementations live in app.py.
"""

from app import (
    generate_unique_referral_code as generate_referral_code,
    apply_referral_code,
    maybe_confirm_referral_for_seller,
    calculate_payout_rate,
)


def backfill_referral_codes():
    from app import db, generate_unique_referral_code
    from models import User
    for user in User.query.filter(User.referral_code == None).all():
        user.referral_code = generate_unique_referral_code()
    db.session.commit()


def send_item_sold_email(item):
    from app import send_email, _item_sold_email_html
    if item.seller and item.seller.email:
        html = _item_sold_email_html(item, item.seller)
        send_email(item.seller.email, "Your item sold — Campus Swap", html)
