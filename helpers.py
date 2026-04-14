"""
helpers.py — thin re-export layer so tests can import helpers without importing app directly.
All real implementations live in app.py.
"""

from app import (
    generate_unique_referral_code as generate_referral_code,
    apply_referral_code,
    maybe_confirm_referral_for_seller,
    calculate_payout_rate,
    get_item_unit_size,
    get_seller_unit_count,
    get_effective_capacity,
    build_geographic_clusters,
    build_static_map_url,
    _get_payout_percentage as _payout_pct,
)


def get_payout_percentage(item):
    """Return payout percentage as float (0.0–1.0) for an item."""
    return _payout_pct(item)


def maybe_confirm_referral(item):
    """Adapter: call maybe_confirm_referral_for_seller with the item's seller."""
    maybe_confirm_referral_for_seller(item.seller)


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
