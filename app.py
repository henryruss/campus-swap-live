import os
import math
import random
import shutil
import time
import json
import logging
import re
import secrets
import html as html_module
import threading
import base64
from dotenv import load_dotenv
load_dotenv()  # Load .env for local dev (Render uses env vars directly)

from PIL import Image, ImageOps
import stripe
import resend
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

_EASTERN = ZoneInfo('America/New_York')

def _now_eastern():
    """Current datetime in US Eastern time (handles EST/EDT automatically)."""
    return datetime.now(_EASTERN)

def _today_eastern():
    """Current date in US Eastern time."""
    return _now_eastern().date()
from flask import Flask, render_template, render_template_string, request, redirect, url_for, flash, session, send_from_directory, jsonify, Response, make_response, abort
import csv
from io import StringIO, BytesIO
from werkzeug.utils import secure_filename
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect
from sqlalchemy.orm import joinedload, selectinload
from sqlalchemy import or_, and_, func, nulls_last

# PostHog analytics
import posthog

# Import Models
from models import db, User, InventoryCategory, InventoryItem, ItemPhoto, AppSetting, UploadSession, TempUpload, AdminEmail, SellerAlert, DigestLog, ItemAIResult, WorkerApplication, WorkerAvailability, ShiftWeek, Shift, ShiftAssignment, ShiftPickup, ShiftRun, WorkerPreference, StorageLocation, IntakeRecord, IntakeFlag, Referral, BuyerOrder, ShopNotifySignup, RescheduleToken

# Import Constants
from constants import (
    PAYOUT_PERCENTAGE, PAYOUT_PERCENTAGE_ONLINE,
    PAYOUT_PERCENTAGE_FREE,
    SERVICE_FEE_CENTS, SELLER_ACTIVATION_FEE_CENTS,
    MAX_UPLOAD_SIZE, ALLOWED_EXTENSIONS, ALLOWED_MIME_TYPES,
    MAX_VIDEO_SIZE, ALLOWED_VIDEO_EXTENSIONS, ALLOWED_VIDEO_MIME_TYPES,
    category_requires_video, VIDEO_REQUIRED_CATEGORIES,
    IMAGE_QUALITY, THUMBNAIL_SIZE,
    MIN_PRICE, MAX_PRICE, MIN_QUALITY, MAX_QUALITY,
    MAX_DESCRIPTION_LENGTH, MAX_LONG_DESCRIPTION_LENGTH,
    MAX_EMAIL_LENGTH, MAX_NAME_LENGTH,
    ITEMS_PER_PAGE, RESIDENCE_HALLS_BY_STORE, OFF_CAMPUS_COMPLEXES,
    PICKUP_WEEKS, PICKUP_WEEK_DATE_RANGES, PICKUP_TIME_OPTIONS,
    WAREHOUSE_CAPACITY,
    get_price_range_for_category
)

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def get_pickup_period_active():
    """Get pickup period status from database, fallback to environment variable"""
    # Check database first (allows admin toggle)
    db_value = AppSetting.get('pickup_period_active')
    if db_value is not None:
        return db_value.lower() == 'true'
    # Fallback to environment variable
    return os.environ.get('PICKUP_PERIOD_ACTIVE', 'True').lower() == 'true'

def get_current_store():
    """Get current store location - defaults to UNC Chapel Hill"""
    store = AppSetting.get('current_store')
    if store:
        return store
    # Default store
    return 'UNC Chapel Hill'

def is_super_admin():
    """True if current user is a super admin (full access). Requires request context."""
    if not current_user.is_authenticated:
        return False
    return getattr(current_user, 'is_super_admin', False)

def store_is_open():
    """True if the store is live — controlled by store_open_date admin setting."""
    from datetime import date as _date
    val = AppSetting.get('store_open_date', '2026-06-01')
    return _date.today() >= _date.fromisoformat(val)

def store_open_date():
    """Return the store open date as a human-readable string (e.g. 'June 1st')."""
    from datetime import date as _date
    val = AppSetting.get('store_open_date', '2026-06-01')
    d = _date.fromisoformat(val)
    day = d.day
    if 11 <= day <= 13:
        suffix = 'th'
    else:
        suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(day % 10, 'th')
    return d.strftime('%B ') + str(day) + suffix

def store_open_date_raw():
    """Return the store open date as ISO string (for form inputs)."""
    return AppSetting.get('store_open_date', '2026-06-01')


def haversine_miles(lat1, lng1, lat2, lng2):
    """Return straight-line distance in miles between two lat/lng points."""
    R = 3958.8  # Earth radius in miles
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


def geocode_address(street, city, state, zip_code):
    """Geocode an address using Nominatim. Returns (lat, lng) or (None, None) on failure."""
    from geopy.geocoders import Nominatim
    from geopy.exc import GeocoderTimedOut, GeocoderServiceError
    geolocator = Nominatim(user_agent="campus-swap-delivery/1.0")
    query = f"{street}, {city}, {state} {zip_code}, USA"
    try:
        location = geolocator.geocode(query, timeout=5)
        if location:
            return location.latitude, location.longitude
        return None, None
    except (GeocoderTimedOut, GeocoderServiceError) as e:
        app.logger.error(f"Geocoding error: {e}")
        return None, None


def item_is_picked_up(item):
    """True if item is in Campus Swap's possession (picked up or arrived at store)."""
    return bool(item.picked_up_at or item.arrived_at_store_at)

def get_store_info(store_name):
    """Get store information by name"""
    stores = {
        'UNC Chapel Hill': {
            'name': 'UNC Chapel Hill',
            'address': 'Store location coming soon',
            'zip': '27514',
            'city': 'Chapel Hill',
            'state': 'NC'
        }
    }
    return stores.get(store_name, stores['UNC Chapel Hill'])

# --- APP CONFIGURATION ---
app = Flask(__name__)

@app.context_processor
def inject_store_functions():
    """Make store functions available to all templates"""
    return dict(
        get_current_store=get_current_store,
        get_store_info=get_store_info,
        google_oauth_enabled=bool(oauth),
        is_super_admin=is_super_admin,
        turnstile_site_key=os.environ.get('TURNSTILE_SITE_KEY', ''),
        item_is_picked_up=item_is_picked_up,
        store_is_open=store_is_open,
        store_open_date=store_open_date,
        store_open_date_raw=store_open_date_raw,
        category_requires_video=category_requires_video,
        video_required_keywords=VIDEO_REQUIRED_CATEGORIES
    )

# SECURITY: This secret key enables sessions. 
# On Render, set this as an Environment Variable called 'SECRET_KEY'.
app.secret_key = os.environ.get('SECRET_KEY', 'dev_key_for_local_use')

# Cookie security: only use Secure flag in production (HTTPS).
# On localhost/127.0.0.1 (HTTP), Secure cookies won't be sent, causing auth failures and redirect loops.
if not os.environ.get('DATABASE_URL'):
    app.config['SESSION_COOKIE_SECURE'] = False

# 1. DATABASE CONFIGURATION
db_url = os.environ.get('DATABASE_URL')
if db_url:
    # Fix for SQLAlchemy: Render gives 'postgres://', but SQLAlchemy needs 'postgresql://'
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = db_url
else:
    # Local fallback
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///campus.db'

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# 2. STORAGE CONFIGURATION
# S3: use AWS when env vars set. Local: disk for dev or Render persistent disk.
if os.environ.get('AWS_S3_BUCKET'):
    app.config['UPLOAD_FOLDER'] = '/tmp/campusswap_uploads'  # Temp uploads only when S3
else:
    if os.path.exists('/var/data'):
        app.config['UPLOAD_FOLDER'] = '/var/data'
    else:
        app.config['UPLOAD_FOLDER'] = 'static/uploads'

# Temp uploads (QR mobile) always go to local disk
app.config['TEMP_UPLOAD_FOLDER'] = app.config['UPLOAD_FOLDER']
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Initialize storage backend (S3 or local)
from storage import init_storage
photo_storage = init_storage(app)

# Initialize DB & Migrations
db.init_app(app)
migrate = Migrate(app, db)

# CSRF Protection (exempt webhook - Stripe sends raw POST without token)
csrf = CSRFProtect(app)

# Rate Limiting
_ratelimit_enabled = os.environ.get('RATELIMIT_ENABLED', 'true').lower() != 'false'
try:
    if not _ratelimit_enabled:
        raise ImportError("Rate limiting disabled via RATELIMIT_ENABLED=false")
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address
    limiter = Limiter(
        app=app,
        key_func=get_remote_address,
        default_limits=["200 per day", "50 per hour"],
        storage_uri="memory://"
    )
    logger.info("Rate limiting enabled")
except ImportError:
    limiter = None
    logger.warning("Flask-Limiter not installed. Rate limiting disabled.")

# --- EXTERNAL SERVICES CONFIGURATION ---

# STRIPE
stripe.api_key = os.environ.get('STRIPE_SECRET_KEY')
endpoint_secret = os.environ.get('STRIPE_WEBHOOK_SECRET')

# RESEND (EMAIL)
resend.api_key = os.environ.get('RESEND_API_KEY')  # Also loaded from .env via load_dotenv()

# GOOGLE OAUTH (optional - Sign in with Google)
oauth = None
_google_client_id = os.environ.get('GOOGLE_CLIENT_ID')
_google_client_secret = os.environ.get('GOOGLE_CLIENT_SECRET')
if _google_client_id and _google_client_secret:
    app.config['GOOGLE_CLIENT_ID'] = _google_client_id
    app.config['GOOGLE_CLIENT_SECRET'] = _google_client_secret
    from authlib.integrations.flask_client import OAuth
    oauth = OAuth(app)
    oauth.register(
        name='google',
        server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
        client_kwargs={'scope': 'openid email profile'}
    )
    logger.info("Google OAuth enabled")
else:
    logger.info("Google OAuth disabled (set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET to enable)")

# LOGIN MANAGER
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# Carousel images: use CDN URL when CAROUSEL_CDN_URL is set (e.g. S3/CloudFront) for faster loading.
# Set CAROUSEL_CDN_URL to your CloudFront distribution URL or S3 bucket URL (e.g. https://d1234.cloudfront.net/)
# Upload static/CarouselPics/* to the root of the bucket so URLs resolve as base/CarouselPics/filename.png
_carousel_cdn_base = os.environ.get('CAROUSEL_CDN_URL', '').rstrip('/')
if _carousel_cdn_base:
    _carousel_cdn_base = _carousel_cdn_base + '/'
@app.context_processor
def inject_carousel_cdn():
    return {'carousel_image_base': _carousel_cdn_base}

# PostHog initialization
posthog.api_key = os.environ.get('POSTHOG_API_KEY', '')
posthog.host = os.environ.get('POSTHOG_HOST', 'https://us.i.posthog.com')
if not posthog.api_key:
    posthog.disabled = True
    posthog.api_key = 'disabled'  # prevent ValueError on capture() when no key set

# PostHog context processor
@app.context_processor
def inject_posthog():
    return {'posthog_api_key': os.environ.get('POSTHOG_API_KEY', '')}


@app.context_processor
def inject_template_utils():
    return {'timedelta': timedelta}


def get_user_dashboard():
    """Helper function to determine where user should be redirected"""
    if current_user.is_authenticated and current_user.is_admin:
        return url_for('admin_panel')
    return url_for('dashboard')


def apply_admin_email_if_pending(user):
    """If user's email is in AdminEmail, apply admin status and remove the record."""
    if not user or not user.email:
        return
    email_lower = user.email.strip().lower()
    admin_email = AdminEmail.query.filter_by(email=email_lower).first()
    if admin_email:
        user.is_admin = True
        user.is_super_admin = admin_email.is_super_admin
        db.session.delete(admin_email)
        db.session.commit()

def require_super_admin():
    """Returns redirect response if current user is not a super admin. Call at start of super-admin-only routes."""
    if not current_user.is_authenticated or not current_user.is_admin:
        flash("Access denied.", "error")
        return redirect(url_for('index'))
    if not is_super_admin():
        flash("This action requires super admin access.", "error")
        return redirect(url_for('admin_panel'))
    return None


# --- EMAIL HELPERS ---

def generate_unsubscribe_token():
    """Generate a secure random token for unsubscribe links"""
    return secrets.token_urlsafe(32)

def ensure_unsubscribe_token(user):
    """Ensure user has an unsubscribe token, creating one if needed"""
    # If user is detached, merge it into the current session
    if user not in db.session:
        user = db.session.merge(user)
    if not user.unsubscribe_token:
        user.unsubscribe_token = generate_unsubscribe_token()
        db.session.commit()
    return user.unsubscribe_token

def html_to_text(html_content):
    """Convert HTML email content to plain text version"""
    # Remove HTML tags and decode entities
    text = re.sub(r'<[^>]+>', '', html_content)
    text = html_module.unescape(text)
    # Clean up whitespace
    text = re.sub(r'\n\s*\n', '\n\n', text)
    return text.strip()

def wrap_email_template(html_content, unsubscribe_url=None, is_marketing=False):
    """
    Wrap email content in a proper HTML template with logo and footer.
    
    Args:
        html_content: The main email content (HTML)
        unsubscribe_url: Optional unsubscribe URL for marketing emails
        is_marketing: Whether this is a marketing email (adds unsubscribe link)
    """
    try:
        logo_url = url_for('static', filename='faviconNew.svg', _external=True)
        site_url = url_for('index', _external=True)
    except Exception:
        base = os.environ.get('BASE_URL', 'https://usecampusswap.com')
        logo_url = f"{base.rstrip('/')}/static/faviconNew.svg"
        site_url = base
    logo_block = f"""
        <div style="text-align: center; margin-bottom: 28px;">
            <a href="{site_url}" style="text-decoration: none;">
                <img src="{logo_url}" alt="Campus Swap" style="height: 48px; width: auto; display: inline-block;" />
            </a>
        </div>
    """
    footer = ""
    if is_marketing and unsubscribe_url:
        footer = f"""
        <div style="margin-top: 40px; padding-top: 20px; border-top: 1px solid #e2e8f0; font-size: 0.85rem; color: #64748b;">
            <p style="margin: 0 0 10px;">Campus Swap</p>
            <p style="margin: 0 0 10px;">Physical address coming soon</p>
            <p style="margin: 0;">
                <a href="{unsubscribe_url}" style="color: #64748b; text-decoration: underline;">Unsubscribe from these emails</a>
            </p>
        </div>
        """
    elif is_marketing:
        # Marketing email but no unsubscribe URL provided (shouldn't happen, but handle gracefully)
        footer = """
        <div style="margin-top: 40px; padding-top: 20px; border-top: 1px solid #e2e8f0; font-size: 0.85rem; color: #64748b;">
            <p style="margin: 0 0 10px;">Campus Swap</p>
            <p style="margin: 0;">Physical address coming soon</p>
        </div>
        """
    
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="X-UA-Compatible" content="IE=edge">
</head>
<body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; background-color: #f8fafc;">
    <table role="presentation" style="width: 100%; border-collapse: collapse;">
        <tr>
            <td style="padding: 20px 0;">
                <table role="presentation" style="width: 100%; max-width: 600px; margin: 0 auto; background-color: #ffffff; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">
                    <tr>
                        <td style="padding: 30px;">
                            {logo_block}
                            {html_content}
                            {footer}
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>"""

def send_email(to_email, subject, html_content, from_email=None, is_marketing=False, user=None):
    """
    Sends an email using Resend with automatic unsubscribe handling for marketing emails.
    
    Args:
        to_email: Recipient email address
        subject: Email subject line
        html_content: HTML email content (will be wrapped in template)
        from_email: Optional sender email (defaults to configured sender)
        is_marketing: If True, adds unsubscribe link and headers (default: False)
        user: User object (required if is_marketing=True, used for unsubscribe token)
    
    Returns:
        bool: True if email sent successfully, False otherwise
    """
    if not resend.api_key:
        logger.warning(f"Skipping email to {to_email}: RESEND_API_KEY not set.")
        return False

    # Check if user is unsubscribed (for marketing emails)
    if is_marketing and user and user.unsubscribed:
        logger.info(f"Skipping email to {to_email}: User has unsubscribed")
        return False

    # Default sender - use team@usecampusswap.com
    default_from = os.environ.get('RESEND_FROM_EMAIL', 'Campus Swap <team@usecampusswap.com>')
    sender = from_email or default_from

    # Generate unsubscribe URL if marketing email
    unsubscribe_url = None
    if is_marketing:
        if not user:
            logger.warning(f"Marketing email to {to_email} but no user object provided. Cannot add unsubscribe link.")
        else:
            # Ensure user has unsubscribe token
            token = ensure_unsubscribe_token(user)
            unsubscribe_url = url_for('unsubscribe', token=token, _external=True)

    # Wrap content in email template
    wrapped_html = wrap_email_template(html_content, unsubscribe_url, is_marketing=is_marketing)
    
    # Generate plain text version
    plain_text = html_to_text(html_content)

    # Prepare email data
    email_data = {
        "from": sender,
        "to": to_email,
        "subject": subject,
        "html": wrapped_html,
        "text": plain_text
    }

    # Add headers for marketing emails (improves deliverability)
    if is_marketing and unsubscribe_url:
        email_data["headers"] = {
            "List-Unsubscribe": f"<{unsubscribe_url}>",
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
            "Precedence": "bulk"
        }

    try:
        resend.Emails.send(email_data)
        logger.info(f"Email sent to {to_email}: {subject}")
        return True
    except Exception as e:
        # Log error but don't crash the route
        logger.error(f"Failed to send email to {to_email}: {e}", exc_info=True)
        return False


def _get_payout_percentage(item):
    """Return payout percentage based on seller's payout_rate (referral program).
    Falls back to collection_method logic for legacy data without payout_rate set."""
    if item.seller and item.seller.payout_rate:
        return item.seller.payout_rate / 100
    # Legacy fallback
    if item.collection_method == 'online':
        return PAYOUT_PERCENTAGE_ONLINE
    elif item.collection_method == 'free':
        return PAYOUT_PERCENTAGE_FREE
    return PAYOUT_PERCENTAGE_ONLINE  # safe fallback


def _compute_seller_tracker(seller, items):
    """
    Computes account-level tracker state for the seller dashboard.
    seller: User (current_user)
    items:  list of InventoryItem for this seller (all statuses)
    Returns dict for template context key `tracker`.
    One ShiftPickup query total — never called inside a loop.
    """
    seller_pickup = ShiftPickup.query.filter_by(seller_id=seller.id).first()

    active_items = [i for i in items if i.status != 'rejected']

    conds = {
        'submitted':      len(active_items) > 0,
        'approved':       any(i.status not in ('pending_valuation', 'needs_info', 'rejected')
                              for i in active_items),
        'scheduled':      (seller_pickup is not None and seller_pickup.status != 'issue'),
        'picked_up':      any(i.picked_up_at for i in active_items),
        'at_campus_swap': any(i.arrived_at_store_at for i in active_items),
        'in_the_shop':    (AppSetting.get('shop_teaser_mode', 'false') != 'true'
                           and any(i.status in ('available', 'sold') for i in active_items)),
    }

    stage_defs = [
        ('submitted',      'Submitted'),
        ('approved',       'Approved'),
        ('scheduled',      'Scheduled'),
        ('picked_up',      'Picked Up'),
        ('at_campus_swap', 'At Campus Swap'),
        ('in_the_shop',    'In the Shop'),
    ]

    active_messages = {
        'submitted':      "We're reviewing your items — approval usually takes 1–2 days.",
        'approved':       "We're reviewing your items — approval usually takes 1–2 days.",
        'scheduled':      "Items approved! We'll be adding you to a pickup route soon.",
        'picked_up':      "Pickup scheduled! We'll send you the details and notify you when your driver is on the way.",
        'at_campus_swap': "Driver has your items — they're headed to our storage facility.",
        'in_the_shop':    "Your items are in storage and will go live when the shop opens.",
    }

    stages = []
    found_active = False
    for key, label in stage_defs:
        if not found_active and not conds[key]:
            state = 'active'
            found_active = True
        elif conds[key]:
            state = 'completed'
        else:
            state = 'upcoming'
        stages.append({'key': key, 'label': label, 'state': state})

    active_key = next((s['key'] for s in stages if s['state'] == 'active'), None)
    message = active_messages.get(active_key, "Your items are in the shop. Good luck! 🎉")

    # Interrupts — checked independently of stage states
    interrupt = None
    needs_info_item = next((i for i in active_items if i.status == 'needs_info'), None)
    if needs_info_item:
        interrupt = {
            'message': "One of your items needs attention.",
            'link': f'/edit_item/{needs_info_item.id}'
        }
    elif seller_pickup and seller_pickup.status == 'issue':
        interrupt = {
            'message': "There was an issue with your pickup. We'll be in touch.",
            'link': None
        }

    return {
        'stages':         stages,
        'active_message': message,
        'interrupt':      interrupt,
    }


# =========================================================
# REFERRAL PROGRAM HELPERS
# =========================================================

_REFERRAL_CODE_CHARS = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'  # excludes 0,O,I,1


def generate_unique_referral_code():
    """Generate a unique 8-char uppercase alphanumeric referral code (no 0,O,I,1)."""
    import string
    for _ in range(20):  # 20 attempts before giving up
        code = ''.join(secrets.choice(_REFERRAL_CODE_CHARS) for _ in range(8))
        if not User.query.filter_by(referral_code=code).first():
            return code
    # Extremely unlikely collision fallback
    return secrets.token_hex(4).upper()[:8]


def calculate_payout_rate(user):
    """Calculate payout_rate from confirmed referrals + base rate (capped at max_rate).
    If the user joined via a referral code, their signup bonus is included.
    If the user has purchased the payout boost, that +30 is also included so that
    subsequent referral confirmations stack correctly on top of the boost.
    """
    base = int(AppSetting.get('referral_base_rate', '20'))
    max_rate = int(AppSetting.get('referral_max_rate', '100'))
    bonus_per = int(AppSetting.get('referral_bonus_per_referral', '10'))
    signup_bonus = int(AppSetting.get('referral_signup_bonus', '10')) if user.referred_by_id else 0
    boost = 30 if getattr(user, 'has_paid_boost', False) else 0
    confirmed_count = Referral.query.filter_by(referrer_id=user.id, confirmed=True).count()
    rate = base + signup_bonus + boost + (confirmed_count * bonus_per)
    return min(rate, max_rate)


def apply_referral_code(new_user, code):
    """Apply a referral code to a new user at registration. Sets referred_by_id, bumps payout_rate."""
    if not code:
        return
    if AppSetting.get('referral_program_active', 'true') != 'true':
        return
    referrer = User.query.filter_by(referral_code=code.strip().upper()).first()
    if not referrer or referrer.id == new_user.id:
        return  # invalid or self-referral
    signup_bonus = int(AppSetting.get('referral_signup_bonus', '10'))
    max_rate = int(AppSetting.get('referral_max_rate', '100'))
    new_user.referred_by_id = referrer.id
    new_user.payout_rate = min(new_user.payout_rate + signup_bonus, max_rate)
    referral = Referral(referrer_id=referrer.id, referred_id=new_user.id)
    db.session.add(referral)
    # Do NOT update referrer's payout_rate here — that only happens on item arrival


def maybe_confirm_referral_for_seller(seller):
    """Confirm a referral when a mover marks this seller's stop as completed.
    One credit per referred seller regardless of item count. No-op if already confirmed."""
    if AppSetting.get('referral_program_active', 'true') != 'true':
        return
    if not seller or not seller.referred_by_id:
        return
    existing = Referral.query.filter_by(
        referrer_id=seller.referred_by_id,
        referred_id=seller.id,
        confirmed=True
    ).first()
    if existing:
        # Already confirmed — recalculate and store rate in case it drifted, no email
        referrer = existing.referrer
        referrer.payout_rate = calculate_payout_rate(referrer)
        db.session.flush()
        return
    referral = Referral.query.filter_by(
        referrer_id=seller.referred_by_id,
        referred_id=seller.id
    ).first()
    if not referral:
        return
    referral.confirmed = True
    referral.confirmed_at = datetime.utcnow()
    referrer = referral.referrer
    referrer.payout_rate = calculate_payout_rate(referrer)
    db.session.flush()  # don't commit here — caller commits
    _send_referral_confirmed_email(referrer, seller)


def _send_referral_confirmed_email(referrer, referred_seller):
    """Email the referrer when their referred seller's item arrives at the warehouse."""
    referred_name = referred_seller.full_name or 'Your referral'
    first_name = referred_name.split()[0] if referred_name else 'Your referral'
    new_rate = referrer.payout_rate
    try:
        dashboard_url = url_for('dashboard', _external=True)
    except Exception:
        dashboard_url = 'https://usecampusswap.com/dashboard'
    try:
        content = f"""
        <div style="font-family: sans-serif; padding: 20px; max-width: 500px;">
            <h2 style="color: #166534;">Referral confirmed!</h2>
            <p>Hi {referrer.full_name or 'there'},</p>
            <p><strong>{first_name}</strong> just had their pickup completed by our movers. Your referral is confirmed.</p>
            <div style="background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 8px; padding: 16px; margin: 20px 0;">
                <p style="margin: 0; font-size: 1.1rem;"><strong>Your payout rate is now {new_rate}%.</strong></p>
            </div>
            <p>Keep sharing your referral link to earn even more — up to 100%!</p>
            <p><a href="{dashboard_url}" style="background: #166534; color: white; padding: 12px 24px; text-decoration: none; border-radius: 8px; display: inline-block;">View Dashboard</a></p>
            <p>Thanks for spreading the word!</p>
        </div>
        """
        send_email(referrer.email, "Referral confirmed — your payout rate increased!", content)
    except Exception as e:
        logger.error(f"Failed to send referral confirmed email: {e}")


def send_boost_confirmation_email(user):
    """Send confirmation email after a seller completes the $15 payout boost purchase."""
    first_name = (user.full_name or 'there').split()[0]
    new_rate = user.payout_rate
    try:
        dashboard_url = url_for('dashboard', _external=True)
    except Exception:
        dashboard_url = 'https://usecampusswap.com/dashboard'
    content = wrap_email_template(f"""
        <h2 style="color: #1A3D1A;">Your payout rate is now {new_rate}%!</h2>
        <p>Hi {first_name},</p>
        <p>Your payout boost is confirmed. Your Campus Swap payout rate is now <strong>{new_rate}%</strong>.</p>
        <p>Keep referring friends — every confirmed referral still adds another 10%. The more you refer, the closer you get to keeping 100% of your sales.</p>
        <p><a href="{dashboard_url}" style="background: #C8832A; color: white; padding: 12px 24px; text-decoration: none; border-radius: 8px; display: inline-block;">Go to Dashboard</a></p>
        <p>Thanks for being a Campus Swap seller!</p>
    """)
    send_email(user.email, f"Payout boost confirmed — you're now at {new_rate}%!", content)


def _handle_boost_webhook(session):
    """Process a payout_boost checkout.session.completed event.

    Extracted as a module-level function so tests can call it directly without
    Stripe signature verification. ``session`` is the ``data.object`` dict from
    the Stripe event.
    """
    metadata = session.get('metadata', {})
    if metadata.get('type') != 'payout_boost':
        return
    user_id = metadata.get('user_id')
    if not user_id:
        return
    user = User.query.get(int(user_id))
    if not user or user.has_paid_boost:
        return  # guard: idempotent — never apply twice
    boost = int(metadata.get('boost_amount', 30))
    max_rate = int(AppSetting.get('referral_max_rate', '100'))
    user.payout_rate = min(user.payout_rate + boost, max_rate)
    user.has_paid_boost = True
    db.session.commit()
    try:
        send_boost_confirmation_email(user)
    except Exception as e:
        logger.error(f"Failed to send boost confirmation email to user {user_id}: {e}")


def get_warehouse_spots_remaining():
    """Count remaining warehouse spots. Only online (paid) and free items count against the 2,000 limit.
    """
    committed = InventoryItem.query.filter(
        InventoryItem.collection_method.in_(['online', 'free']),
        ~InventoryItem.status.in_(['rejected'])
    ).count()
    return max(0, WAREHOUSE_CAPACITY - committed)


def _item_sold_email_html(item, seller):
    """Build HTML for item sold notification with payout details."""
    sale_price = item.price or 0
    payout_pct = _get_payout_percentage(item)
    payout_amount = round(sale_price * payout_pct, 2)
    payout_method = seller.payout_method or "Venmo"
    payout_handle = seller.payout_handle or "-"
    return f"""
    <div style="font-family: sans-serif; padding: 20px; max-width: 500px;">
        <h2 style="color: #166534;">Cha-Ching!</h2>
        <p>Good news! Your item <strong>{item.description}</strong> has just been purchased.</p>
        <div style="background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 8px; padding: 16px; margin: 20px 0;">
            <p style="margin: 0 0 8px;"><strong>Sale price:</strong> ${sale_price:.2f}</p>
            <p style="margin: 0 0 8px;"><strong>Your payout ({int(payout_pct * 100)}%):</strong> ${payout_amount:.2f}</p>
            <p style="margin: 0;"><strong>Payout to:</strong> {payout_method} (@{payout_handle})</p>
        </div>
        <p>We'll process your payout shortly. Our team handles the handover to the buyer. You don't need to do anything!</p>
        <p>Thanks for selling with Campus Swap!</p>
    </div>
    """


# --- VALIDATION HELPERS ---

def validate_email(email):
    """Validate email format"""
    if not email or len(email) > MAX_EMAIL_LENGTH:
        return False
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email))


def verify_turnstile(token):
    """Verify Cloudflare Turnstile token. Returns True if valid or if Turnstile not configured."""
    secret = os.environ.get('TURNSTILE_SECRET_KEY')
    if not secret:
        logger.warning("TURNSTILE_SECRET_KEY not set - skipping Turnstile verification")
        return True
    if not token:
        return False
    try:
        import requests
        resp = requests.post(
            'https://challenges.cloudflare.com/turnstile/v0/siteverify',
            data={'secret': secret, 'response': token},
            timeout=10
        )
        return bool(resp.json().get('success'))
    except Exception as e:
        logger.warning(f"Turnstile verification error: {e}")
        return False


def validate_phone(phone):
    """
    Validate US phone number: exactly 10 digits.
    Accepts common formats: 555-123-4567, (555) 123-4567, 555.123.4567, +1 555 123 4567.
    Returns (True, normalized_digits) or (False, error_message).
    """
    if not phone or not phone.strip():
        return False, "Please provide a phone number."
    digits = re.sub(r'\D', '', phone.strip())
    if len(digits) == 11 and digits.startswith('1'):
        digits = digits[1:]  # Strip US country code
    if len(digits) != 10:
        return False, "Please enter a valid 10-digit US phone number."
    return True, digits


def validate_file_upload(file):
    """Validate uploaded file: size, extension, and MIME type"""
    if not file or not file.filename:
        return False, "No file provided"
    
    # Check file size
    file.seek(0, os.SEEK_END)
    file_size = file.tell()
    file.seek(0)  # Reset file pointer
    
    if file_size > MAX_UPLOAD_SIZE:
        return False, f"File size exceeds {MAX_UPLOAD_SIZE / (1024*1024):.1f}MB limit"
    
    # Check extension
    filename = secure_filename(file.filename)
    if not filename:
        return False, "Invalid filename"
    
    ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
    if ext not in ALLOWED_EXTENSIONS:
        return False, f"File type not allowed. Allowed types: {', '.join(ALLOWED_EXTENSIONS)}"
    
    # Check MIME type
    mime_type = file.content_type
    if mime_type and mime_type.lower() not in ALLOWED_MIME_TYPES:
        return False, "Invalid file type"

    return True, None


def validate_video_upload(file):
    """Validate uploaded video file: size, extension, and MIME type."""
    if not file or not file.filename:
        return False, "No file provided"

    file.seek(0, os.SEEK_END)
    file_size = file.tell()
    file.seek(0)

    if file_size > MAX_VIDEO_SIZE:
        return False, f"Video size exceeds {MAX_VIDEO_SIZE / (1024*1024):.0f}MB limit"

    filename = secure_filename(file.filename)
    if not filename:
        return False, "Invalid filename"

    ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
    if ext not in ALLOWED_VIDEO_EXTENSIONS:
        return False, f"Video type not allowed. Allowed types: {', '.join(ALLOWED_VIDEO_EXTENSIONS)}"

    mime_type = (file.content_type or "").lower().strip()
    # Some browsers (especially on Windows) send generic or empty MIME types
    # for valid video files — trust the extension if MIME is missing/generic
    generic_mimes = {"", "application/octet-stream", "application/x-unknown"}
    if mime_type and mime_type not in generic_mimes and mime_type not in ALLOWED_VIDEO_MIME_TYPES:
        return False, "Invalid video file type"

    return True, None


def validate_price(price):
    """Validate price is within acceptable range"""
    try:
        price_float = float(price)
        if price_float < MIN_PRICE or price_float > MAX_PRICE:
            return False, f"Price must be between ${MIN_PRICE:.2f} and ${MAX_PRICE:.2f}"
        return True, price_float
    except (ValueError, TypeError):
        return False, "Invalid price format"


def validate_quality(quality):
    """Validate quality rating"""
    try:
        quality_int = int(quality)
        if quality_int < MIN_QUALITY or quality_int > MAX_QUALITY:
            return False, f"Quality must be between {MIN_QUALITY} and {MAX_QUALITY}"
        return True, quality_int
    except (ValueError, TypeError):
        return False, "Invalid quality value"


def quality_to_label(quality):
    """Map numeric quality (1-5) to rubric label."""
    if quality is None:
        return ''
    try:
        q = int(quality)
        if q >= 5:
            return "Like new"
        if q == 4:
            return "Good"
        return "Fair"  # 1, 2, 3
    except (ValueError, TypeError):
        return ''


@app.template_filter('quality_label')
def quality_label_filter(quality):
    """Jinja filter: map numeric quality to rubric label."""
    return quality_to_label(quality)


@app.template_filter('fromjson')
def fromjson_filter(value):
    """Jinja filter: parse a JSON string into a Python object."""
    import json
    try:
        return json.loads(value) if value else []
    except (json.JSONDecodeError, TypeError):
        return []


# --- ERROR HANDLERS ---

@app.errorhandler(404)
def not_found_error(error):
    logger.warning(f"404 error: {request.url}")
    try:
        posthog.capture('backend_error', distinct_id='anonymous', properties={
            'error_type': '404',
            'route': request.path,
            'method': request.method
        })
    except Exception:
        pass
    return render_template('error.html',
                         error_code=404,
                         error_message="Page not found"), 404


@app.errorhandler(500)
def internal_error(error):
    logger.error(f"500 error: {error}", exc_info=True)
    db.session.rollback()
    try:
        posthog.capture(
            'backend_error',
            distinct_id=str(current_user.id) if current_user.is_authenticated else 'anonymous',
            properties={
                'error_type': type(error).__name__,
                'error_message': str(error),
                'route': request.path
            }
        )
    except Exception:
        pass
    return render_template('error.html',
                         error_code=500,
                         error_message="An internal error occurred. Please try again later."), 500


@app.errorhandler(413)
def request_entity_too_large(error):
    logger.warning(f"413 error: File too large")
    flash("File is too large. Maximum size is 10MB.", "error")
    return redirect(request.url), 413


# =========================================================
# AI ITEM LOOKUP (background thread)
# =========================================================

AI_SYSTEM_PROMPT = """You are a product research assistant for a college student consignment marketplace. \
You will be shown photos of a used item along with its category, condition rating, \
and the seller's description.

Your job is to:
1. Identify the exact product (brand, model name, model number if visible)
2. Search the web to find its current retail price from a major retailer
3. Suggest a fair resale price based on retail price, condition, and any visible wear in the photos
4. Write a clean, accurate 2-3 sentence product description suitable for a resale listing
5. Provide a brief 1-2 sentence rationale for your suggested price

Respond ONLY with a JSON object in this exact format:
{
  "identified": true,
  "product_name": "Full product name and model",
  "retail_price": 129.99,
  "retail_price_source": "https://www.amazon.com/...",
  "suggested_price": 58.00,
  "pricing_rationale": "Retails for $130 new. Condition rated Good with minor scuffs visible on left panel. Suggested at 45% of retail.",
  "description": "Frigidaire 3.2 cu ft compact refrigerator in good condition. Features a small freezer compartment and adjustable shelving. Minor cosmetic wear on exterior."
}

If you cannot confidently identify the specific product or find a retail listing for it, respond with:
{
  "identified": false
}

Do not guess. Only return identified: true if you are confident in the product match and have a real retail URL to provide."""


def run_ai_item_lookup(item_id):
    """Run AI lookup for an item in a background thread. Must be called with app context."""
    try:
        import anthropic
    except ImportError:
        logger.error("anthropic package not installed — AI lookup skipped")
        result = ItemAIResult.query.filter_by(item_id=item_id).first()
        if result:
            result.status = 'error'
            result.raw_response = 'anthropic package not installed'
            db.session.commit()
        return

    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        logger.error("ANTHROPIC_API_KEY not set — AI lookup skipped")
        result = ItemAIResult.query.filter_by(item_id=item_id).first()
        if result:
            result.status = 'error'
            result.raw_response = 'ANTHROPIC_API_KEY not set'
            db.session.commit()
        return

    try:
        item = InventoryItem.query.options(
            joinedload(InventoryItem.category),
            joinedload(InventoryItem.gallery_photos)
        ).get(item_id)
        if not item:
            return

        result = ItemAIResult.query.filter_by(item_id=item_id).first()
        if not result:
            return

        # Collect photos (cover + up to 3 gallery, max 4 total)
        photo_keys = []
        if item.photo_url:
            photo_keys.append(item.photo_url)
        for gp in (item.gallery_photos or []):
            if gp.photo_url and gp.photo_url != item.photo_url:
                photo_keys.append(gp.photo_url)
            if len(photo_keys) >= 4:
                break

        if not photo_keys:
            result.status = 'unknown'
            result.updated_at = datetime.utcnow()
            db.session.commit()
            return

        # Build image content blocks
        image_content = []
        for key in photo_keys:
            photo_bytes = photo_storage.get_photo_bytes(key)
            if not photo_bytes:
                continue
            ext = key.rsplit('.', 1)[-1].lower() if '.' in key else 'jpeg'
            media_type = 'image/png' if ext == 'png' else 'image/jpeg'
            b64 = base64.standard_b64encode(photo_bytes).decode('utf-8')
            image_content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": b64
                }
            })

        if not image_content:
            result.status = 'unknown'
            result.updated_at = datetime.utcnow()
            db.session.commit()
            return

        # Build text context
        category_name = item.category.name if item.category else 'Unknown'
        condition_map = {5: 'Like New', 4: 'Good', 3: 'Fair', 2: 'Fair', 1: 'Fair'}
        condition = condition_map.get(item.quality, 'Unknown')
        seller_desc = item.long_description or item.description or ''

        text_block = {
            "type": "text",
            "text": f"Category: {category_name}\nCondition: {condition}\nSeller's description: {seller_desc}"
        }

        # Call Anthropic API
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            system=AI_SYSTEM_PROMPT,
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}],
            messages=[{
                "role": "user",
                "content": image_content + [text_block]
            }]
        )

        # Extract text from response
        raw_text = ""
        for block in response.content:
            if hasattr(block, 'text'):
                raw_text += block.text

        result.raw_response = raw_text

        # Strip markdown code fences before parsing
        json_text = raw_text.strip()
        if json_text.startswith("```"):
            lines = json_text.split('\n')
            # Remove first line (```json or ```) and last line (```)
            if lines[-1].strip() == '```':
                lines = lines[1:-1]
            else:
                lines = lines[1:]
            json_text = '\n'.join(lines).strip()

        parsed = json.loads(json_text)

        if parsed.get('identified'):
            result.status = 'found'
            result.product_name = str(parsed.get('product_name', ''))[:500]
            result.retail_price = parsed.get('retail_price')
            result.retail_price_source = str(parsed.get('retail_price_source', ''))[:500] if parsed.get('retail_price_source') else None
            result.suggested_price = parsed.get('suggested_price')
            result.pricing_rationale = parsed.get('pricing_rationale')
            result.ai_description = parsed.get('description')
        else:
            result.status = 'unknown'

        result.updated_at = datetime.utcnow()
        db.session.commit()

    except json.JSONDecodeError as e:
        logger.error(f"AI lookup JSON parse error for item {item_id}: {e}")
        result = ItemAIResult.query.filter_by(item_id=item_id).first()
        if result:
            result.status = 'error'
            result.updated_at = datetime.utcnow()
            db.session.commit()
    except Exception as e:
        logger.error(f"AI lookup failed for item {item_id}: {e}", exc_info=True)
        try:
            result = ItemAIResult.query.filter_by(item_id=item_id).first()
            if result:
                result.status = 'error'
                result.updated_at = datetime.utcnow()
                db.session.commit()
        except Exception:
            pass


def trigger_ai_lookup(item_id):
    """Create ItemAIResult record and start background thread for AI lookup."""
    existing = ItemAIResult.query.filter_by(item_id=item_id).first()
    if not existing:
        existing = ItemAIResult(item_id=item_id, status='pending')
        db.session.add(existing)
    else:
        existing.status = 'pending'
        existing.product_name = None
        existing.retail_price = None
        existing.retail_price_source = None
        existing.suggested_price = None
        existing.pricing_rationale = None
        existing.ai_description = None
        existing.raw_response = None
        existing.updated_at = datetime.utcnow()
    db.session.commit()

    def _run_in_context(app_obj, iid):
        with app_obj.app_context():
            run_ai_item_lookup(iid)

    thread = threading.Thread(target=_run_in_context, args=(app, item_id), daemon=True)
    thread.start()


# =========================================================
# SECTION 1: PUBLIC & LANDING ROUTES
# =========================================================

# Ticker prices match the become-a-seller interactive room (seller profit per item)
_TICKER_PRICE_MAP = {
    "mini fridge": 110, "mini-fridge": 110, "minifridge": 110,
    "rug": 80,
    "microwave": 50,
    "headboard": 80,
    "mattress": 160, "twin xl mattress": 160,
    "couch": 140, "sofa": 140, "couch / sofa": 140, "couch/sofa": 140,
    "ac unit": 100, "acunit": 100, "climate control": 100, "box fan": 100,
    "tv": 180, "television": 180,
}
_TICKER_FALLBACK_PRICES = [110, 80, 50, 80, 160, 140, 100, 180]  # From become-a-seller page


def _get_ticker_items():
    """Build ticker items from categories for the index hero slideshow. Uses same prices as become-a-seller page."""
    ticker_cats = InventoryCategory.query.filter_by(parent_id=None).order_by(InventoryCategory.id).limit(8).all()
    if ticker_cats:
        result = []
        for i, c in enumerate(ticker_cats):
            name = (c.name or "").lower().strip()
            price = _TICKER_PRICE_MAP.get(name)
            if price is None:
                price = _TICKER_FALLBACK_PRICES[i % len(_TICKER_FALLBACK_PRICES)]
            result.append({"icon": c.image_url or "fa-box", "price": f"${price}"})
        return result
    # Fallback when no categories - match become-a-seller interactive room
    return [
        {"icon": "fa-couch", "price": "$140"},
        {"icon": "fa-snowflake", "price": "$110"},
        {"icon": "fa-bed", "price": "$160"},
        {"icon": "fa-tv", "price": "$180"},
        {"icon": "fa-wind", "price": "$100"},
        {"icon": "fa-square", "price": "$80"},
    ]


@app.route('/', methods=['GET', 'POST'])
@limiter.limit("10 per hour", methods=['POST']) if limiter else lambda f: f
def index():
    # 1. TRACKING LOGIC
    if request.args.get('source'):
        session['source'] = request.args.get('source')

    ticker_items = _get_ticker_items()

    if request.method == 'POST':
        if not verify_turnstile(request.form.get('cf-turnstile-response', '')):
            flash("Verification failed. Please try again.", "error")
            return render_template('index.html', pickup_period_active=get_pickup_period_active(), ticker_items=ticker_items)
        email = request.form.get('email', '').strip()
        
        # Validate email
        if not email:
            flash("Please provide your email address.", "error")
            return render_template('index.html', pickup_period_active=get_pickup_period_active(), ticker_items=ticker_items)
        
        if not validate_email(email):
            flash("Please provide a valid email address.", "error")
            return render_template('index.html', pickup_period_active=get_pickup_period_active(), ticker_items=ticker_items)
        
        if len(email) > MAX_EMAIL_LENGTH:
            flash(f"Email address is too long (max {MAX_EMAIL_LENGTH} characters).", "error")
            return render_template('index.html', pickup_period_active=get_pickup_period_active(), ticker_items=ticker_items)
        
        # Check if pickup period is active
        pickup_period_active = get_pickup_period_active()
        if not pickup_period_active:
            # Pickup period closed - still collect email for marketing
            # Check if email already exists
            existing_user = User.query.filter_by(email=email).first()
            if not existing_user:
                # Create a guest account (no password set yet)
                guest_user = User(email=email, referral_source=session.get('source', 'direct'))
                db.session.add(guest_user)
                db.session.commit()
                logger.info(f"Guest account created (pickup period closed): {email}")
            
            flash("Pickup period has ended for this year. We've saved your email and will notify you when signups open next year! Check your spam folder when we send the notification.", "info")
            return redirect(url_for('index'))
        
        # Pickup period is active - proceed with normal flow
        # Check if user already exists
        user = User.query.filter_by(email=email).first()
        
        if user:
            # SCENARIO A: User exists
            if user.password_hash:
                # If they have a password, ask them to login
                flash("You already have an account. Please log in.", "info")
                return redirect(url_for('login', email=email))
            else:
                # SCENARIO B: Existing Lead (No password yet) -> Log them in & go to dashboard
                login_user(user)
                return redirect(get_user_dashboard())
        
        else:
            # SCENARIO C: New Lead -> Create, Log In, & Redirect
            source = session.get('source', 'direct')
            
            # Create User with NO password initially
            new_user = User(email=email, referral_source=source)
            db.session.add(new_user)
            db.session.commit()
            
            # Auto-Login the new user
            login_user(new_user)
            
            # Email captured for marketing - no welcome email sent to avoid spam
            # Redirect straight to action
            flash("Account created! Complete your profile and activate as a seller to start listing items.", "success")
            return redirect(get_user_dashboard())
    
    pickup_period_active = get_pickup_period_active()
    return render_template('index.html', pickup_period_active=pickup_period_active, ticker_items=ticker_items)

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/privacy-policy')
def privacy_policy():
    return render_template('privacy_policy.html')

@app.route('/terms-and-conditions')
def terms_conditions():
    return render_template('terms_conditions.html')

@app.route('/refund-policy')
def refund_policy():
    return render_template('refund_policy.html')

@app.route('/contact', methods=['GET', 'POST'])
@limiter.limit("5 per hour", methods=['POST']) if limiter else lambda f: f
def contact():
    name = ''
    email = ''
    subject = ''
    message = ''

    if request.method == 'POST':
        # Honeypot check — real users won't fill this hidden field
        if request.form.get('website', ''):
            flash("Message sent — we'll be in touch soon.", 'success')
            return redirect(url_for('contact'))

        # Turnstile verification
        if not verify_turnstile(request.form.get('cf-turnstile-response', '')):
            flash('Please complete the verification challenge.', 'error')
            return render_template('contact.html', name=name, email=email, subject=subject, message=message)

        name = request.form.get('name', '').strip()
        subject = request.form.get('subject', '').strip()
        message = request.form.get('message', '').strip()

        if current_user.is_authenticated:
            sender_email = current_user.email
        else:
            email = request.form.get('email', '').strip()
            sender_email = email

        if not name or not subject or not message or (not current_user.is_authenticated and not email):
            flash('Please fill in all fields.', 'error')
            return render_template('contact.html', name=name, email=email, subject=subject, message=message)

        if len(name) > 100 or len(subject) > 200 or len(message) > 5000 or len(email) > 254:
            flash('One of your fields is too long — please shorten it.', 'error')
            return render_template('contact.html', name=name, email=email, subject=subject, message=message)
        email_lines = [
            f"<h2>New Contact Form Submission</h2>",
            f"<p><strong>From:</strong> {html_module.escape(name)}</p>",
            f"<p><strong>Email:</strong> {html_module.escape(sender_email) if sender_email else 'No account — guest submission'}</p>",
            f"<p><strong>Subject:</strong> {html_module.escape(subject)}</p>",
            f"<hr>",
            f"<p>{html_module.escape(message).replace(chr(10), '<br>')}</p>",
            f"<hr>",
            f"<p style='color: #999; font-size: 0.85rem;'>Sent at {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}</p>",
        ]
        html_body = '\n'.join(email_lines)
        email_subject = f"[Campus Swap Contact] {subject}"

        recipients = [
            'Ben@UseCampusSwap.com',
            'Henry@UseCampusSwap.com',
            'Jack@UseCampusSwap.com',
        ]
        success = all(send_email(addr, email_subject, html_body) for addr in recipients)

        if success:
            flash("Message sent — we'll be in touch soon.", 'success')
            return redirect(url_for('contact'))
        else:
            flash("Something went wrong — please try again later.", 'error')
            return render_template('contact.html', name=name, email=email, subject=subject, message=message)

    return render_template('contact.html', name=name, email=email, subject=subject, message=message)

@app.route('/become-a-seller', methods=['GET', 'POST'])
@limiter.limit("10 per hour", methods=['POST']) if limiter else lambda f: f
def become_a_seller():
    """Become a Seller page - comprehensive seller guide with timeline, earnings, FAQ, and CTA."""
    if request.args.get('source'):
        session['source'] = request.args.get('source')

    if request.method == 'POST':
        if not verify_turnstile(request.form.get('cf-turnstile-response', '')):
            flash("Verification failed. Please try again.", "error")
            return render_template('become_a_seller.html', pickup_period_active=get_pickup_period_active(), store_info=get_store_info(get_current_store()),
                               warehouse_spots=get_warehouse_spots_remaining())
        email = request.form.get('email', '').strip()

        if not email:
            flash("Please provide your email address.", "error")
            return render_template('become_a_seller.html', pickup_period_active=get_pickup_period_active(), store_info=get_store_info(get_current_store()), warehouse_spots=get_warehouse_spots_remaining())

        if not validate_email(email):
            flash("Please provide a valid email address.", "error")
            return render_template('become_a_seller.html', pickup_period_active=get_pickup_period_active(), store_info=get_store_info(get_current_store()), warehouse_spots=get_warehouse_spots_remaining())

        if len(email) > MAX_EMAIL_LENGTH:
            flash(f"Email address is too long (max {MAX_EMAIL_LENGTH} characters).", "error")
            return render_template('become_a_seller.html', pickup_period_active=get_pickup_period_active(), store_info=get_store_info(get_current_store()), warehouse_spots=get_warehouse_spots_remaining())

        pickup_period_active = get_pickup_period_active()
        if not pickup_period_active:
            existing_user = User.query.filter_by(email=email).first()
            if not existing_user:
                guest_user = User(email=email, referral_source=session.get('source', 'direct'))
                db.session.add(guest_user)
                db.session.commit()
                logger.info(f"Guest account created (become-a-seller, pickup closed): {email}")

            flash("Pickup period has ended for this year. We've saved your email and will notify you when signups open next year! Check your spam folder when we send the notification.", "info")
            return redirect(url_for('become_a_seller'))

        user = User.query.filter_by(email=email).first()
        if user:
            if user.password_hash:
                flash("You already have an account. Please log in.", "info")
                return redirect(url_for('login', email=email))
            else:
                user.is_seller = True
                db.session.commit()
                login_user(user)
                return redirect(get_user_dashboard())
        else:
            source = session.get('source', 'direct')
            new_user = User(email=email, referral_source=source, is_seller=True)
            db.session.add(new_user)
            db.session.commit()
            login_user(new_user)
            flash("Account created! Complete your profile and activate as a seller to start listing items.", "success")
            return redirect(get_user_dashboard())

    pickup_period_active = get_pickup_period_active()
    store_info = get_store_info(get_current_store())
    return render_template('become_a_seller.html', pickup_period_active=pickup_period_active, store_info=store_info,
                           warehouse_spots=get_warehouse_spots_remaining())

@app.route('/sitemap.xml')
def sitemap():
    """Generate dynamic sitemap.xml for Google Search Console"""
    from flask import Response
    
    # Base URL
    base_url = request.url_root.rstrip('/')
    
    # Get current date for lastmod
    current_date = datetime.utcnow().strftime('%Y-%m-%d')
    
    # Start building XML
    xml = ['<?xml version="1.0" encoding="UTF-8"?>']
    xml.append('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">')
    
    # Static pages with priorities
    static_pages = [
        {'url': '/', 'priority': '1.0', 'changefreq': 'weekly'},
        {'url': '/inventory', 'priority': '0.9', 'changefreq': 'daily'},
        {'url': '/become-a-seller', 'priority': '0.9', 'changefreq': 'weekly'},
        {'url': '/about', 'priority': '0.8', 'changefreq': 'monthly'},
        {'url': '/privacy-policy', 'priority': '0.5', 'changefreq': 'monthly'},
        {'url': '/terms-and-conditions', 'priority': '0.5', 'changefreq': 'monthly'},
        {'url': '/refund-policy', 'priority': '0.5', 'changefreq': 'monthly'},
        {'url': '/register', 'priority': '0.7', 'changefreq': 'monthly'},
        {'url': '/login', 'priority': '0.6', 'changefreq': 'monthly'},
    ]
    
    for page in static_pages:
        xml.append('  <url>')
        xml.append(f'    <loc>{base_url}{page["url"]}</loc>')
        xml.append(f'    <lastmod>{current_date}</lastmod>')
        xml.append(f'    <changefreq>{page["changefreq"]}</changefreq>')
        xml.append(f'    <priority>{page["priority"]}</priority>')
        xml.append('  </url>')
    
    # Add all available (live) product pages - same visibility as inventory
    available_items = InventoryItem.query.join(InventoryItem.seller, isouter=True).filter(
        InventoryItem.status == 'available',
        or_(
            InventoryItem.seller_id.is_(None),
            and_(
                InventoryItem.collection_method == 'online',
                User.has_paid == True
            ),
            and_(
                InventoryItem.collection_method == 'free',
                InventoryItem.arrived_at_store_at.isnot(None)
            )
        )
    ).all()
    for item in available_items:
        xml.append('  <url>')
        xml.append(f'    <loc>{base_url}/item/{item.id}</loc>')
        xml.append(f'    <lastmod>{item.date_added.strftime("%Y-%m-%d") if item.date_added else current_date}</lastmod>')
        xml.append('    <changefreq>weekly</changefreq>')
        xml.append('    <priority>0.7</priority>')
        xml.append('  </url>')
    
    xml.append('</urlset>')
    
    # Return XML response
    return Response('\n'.join(xml), mimetype='application/xml')

@app.route('/robots.txt')
def robots_txt():
    """Generate robots.txt file"""
    base_url = request.url_root.rstrip('/')
    robots = [
        'User-agent: *',
        'Allow: /',
        'Disallow: /admin',
        'Disallow: /dashboard',
        'Disallow: /account_settings',
        'Disallow: /webhook',
        f'Sitemap: {base_url}/sitemap.xml'
    ]
    
    return Response('\n'.join(robots), mimetype='text/plain')

@app.route('/favicon.ico')
@app.route('/favicon.png')
def favicon():
    """Serve favicon.png for Google search results and browser tabs."""
    try:
        favicon_path = os.path.join('static', 'faviconNew.png')
        if not os.path.exists(favicon_path):
            return Response('', mimetype='image/png'), 404
        response = send_from_directory('static', 'faviconNew.png', mimetype='image/png')
        response.headers['Cache-Control'] = 'public, max-age=31536000'
        return response
    except Exception as e:
        logger.error(f"Error serving favicon: {e}", exc_info=True)
        return Response('', mimetype='image/png'), 404


# =========================================================
# SECTION 2: MARKETPLACE ROUTES
# =========================================================

@app.route('/unsubscribe/<token>', methods=['GET', 'POST'])
def unsubscribe(token):
    """Handle email unsubscribe requests"""
    user = User.query.filter_by(unsubscribe_token=token).first()
    
    if not user:
        flash("Invalid unsubscribe link. If you continue to receive emails, please contact support.", "error")
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        # Process unsubscribe
        user.unsubscribed = True
        db.session.commit()
        flash("You have been successfully unsubscribed from marketing emails.", "success")
        return render_template('unsubscribe_success.html')
    
    # GET request - show confirmation page
    return render_template('unsubscribe_confirm.html', user_email=user.email)

@app.route('/inventory')
def inventory():
    """Display inventory with pagination, search, and optimized queries"""
    # Shop Drop teaser — renders blurred mosaic + email capture before launch
    if AppSetting.get('shop_teaser_mode', 'false') == 'true':
        preview_items_raw = InventoryItem.query.filter_by(
            status='available'
        ).order_by(func.random()).limit(16).all()
        # Cycle real items to fill 20 tiles so the grid always looks full
        if preview_items_raw:
            tiles = [preview_items_raw[i % len(preview_items_raw)] for i in range(20)]
            random.shuffle(tiles)
        else:
            tiles = []
        placeholder_count = max(0, 20 - len(tiles))
        return render_template(
            'inventory_teaser.html',
            preview_items=tiles,
            placeholder_range=range(placeholder_count),
        )

    cat_id = request.args.get('category_id', type=int)
    sub_id = request.args.get('subcategory', type=int)
    store_name = request.args.get('store', get_current_store())
    search_query = request.args.get('search', '').strip()
    page = request.args.get('page', 1, type=int)

    commodities = InventoryCategory.query.filter_by(parent_id=None).order_by(InventoryCategory.id).all()
    
    # Build query with eager loading to prevent N+1 queries
    # Items appear on shop once approved (pending_logistics or available or sold) - no wait for has_paid or arrived_at_store
    query = InventoryItem.query.join(InventoryItem.seller, isouter=True).options(
        joinedload(InventoryItem.category),
        joinedload(InventoryItem.seller)
    ).filter(
        InventoryItem.status != 'pending_valuation',
        InventoryItem.status != 'rejected',
        InventoryItem.price.isnot(None),
        InventoryItem.price > 0
    )
    
    # Apply category filter (use InventoryItem explicitly; join can make filter_by ambiguous)
    if cat_id:
        query = query.filter(InventoryItem.category_id == cat_id)
    if sub_id:
        query = query.filter(InventoryItem.subcategory_id == sub_id)
    
    # Apply search filter
    if search_query:
        search_pattern = f"%{search_query}%"
        query = query.filter(
            or_(
                InventoryItem.description.ilike(search_pattern),
                InventoryItem.long_description.ilike(search_pattern)
            )
        )
    
    # Order by status (available first) then date
    query = query.order_by(InventoryItem.status.asc(), InventoryItem.date_added.desc())
    
    # Paginate results
    pagination = query.paginate(
        page=page,
        per_page=ITEMS_PER_PAGE,
        error_out=False
    )
    
    items = pagination.items
    store_info = get_store_info(store_name)

    return render_template('inventory.html',
                         commodities=commodities,
                         items=items,
                         pagination=pagination,
                         search_query=search_query,
                         active_cat=cat_id,
                         active_sub=sub_id,
                         current_store=store_name,
                         store_info=store_info)

@app.route('/item/<int:item_id>')
def product_detail(item_id):
    # Redirect to teaser page when shop is in pre-launch mode
    if AppSetting.get('shop_teaser_mode', 'false') == 'true':
        flash('Items go on sale June 1st — sign up to be notified.', 'info')
        return redirect(url_for('inventory'))
    item = InventoryItem.query.get_or_404(item_id)
    # Block non-admins from viewing rejected items
    if item.status == 'rejected' and not (current_user.is_authenticated and current_user.is_admin):
        flash("This item is not available.", "error")
        return redirect(url_for('inventory'))
    # Approved items are visible on shop (no longer block on has_paid or arrived_at_store)
    store_name = request.args.get('store', get_current_store())
    store_info = get_store_info(store_name)
    is_shareable = _is_item_shareable(item)
    return render_template('product.html', item=item, current_store=store_name, store_info=store_info, is_shareable=is_shareable)

# --- SHARE CARD IMAGE GENERATION ---
def _is_item_shareable(item):
    """True if item would appear in inventory and is not sold."""
    if not item or item.status == 'sold':
        return False
    if item.status not in ('available', 'pending_logistics'):
        return False
    if not item.price or item.price <= 0:
        return False
    return True  # Approved items are shareable (no longer require has_paid or arrived_at_store)


def _share_card_font(size, bold=False):
    """Load a TTF font for share card, cross-platform fallback."""
    from PIL import ImageFont
    bold_paths = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ]
    regular_paths = [
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
    ]
    for p in (bold_paths if bold else []) + regular_paths:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except OSError:
                pass
    return ImageFont.load_default()


def _generate_share_card_png(item):
    """Generate 1200x1200 PNG share card. Returns bytes or None."""
    from PIL import ImageDraw, ImageFont
    CARD_W, CARD_H = 1200, 1200
    # Full-bleed photo with gradient overlay (no solid banner)
    WHITE = (255, 255, 255)

    # Load item photo or create placeholder
    photo_bytes = None
    if item.photo_url:
        photo_bytes = photo_storage.get_photo_bytes(item.photo_url)
    if not photo_bytes:
        base = Image.new("RGB", (CARD_W, CARD_H), (200, 200, 200))
        draw = ImageDraw.Draw(base)
        font = _share_card_font(48)
        draw.text((CARD_W // 2 - 80, CARD_H // 2 - 24), "No image", fill=(100, 100, 100), font=font)
    else:
        img = Image.open(BytesIO(photo_bytes))
        img = img.convert("RGB")
        img.thumbnail((CARD_W * 2, CARD_H * 2), Image.Resampling.LANCZOS)
        w, h = img.size
        # Crop center to fill card
        if w / h > CARD_W / CARD_H:
            new_h = h
            new_w = int(h * CARD_W / CARD_H)
            left = (w - new_w) // 2
            img = img.crop((left, 0, left + new_w, new_h))
        else:
            new_w = w
            new_h = int(w * CARD_H / CARD_W)
            top = (h - new_h) // 2
            img = img.crop((0, top, new_w, top + new_h))
        base = img.resize((CARD_W, CARD_H), Image.Resampling.LANCZOS)

    # Gradient overlay: transparent at top, dark at bottom (Spotify-style)
    gradient_h = 420
    band = Image.new("RGBA", (1, gradient_h))
    for y in range(gradient_h):
        t = y / gradient_h
        alpha = int(230 * (t ** 0.7))
        band.putpixel((0, y), (0, 0, 0, alpha))
    overlay = band.resize((CARD_W, gradient_h), Image.Resampling.NEAREST)
    base.paste(overlay, (0, CARD_H - gradient_h), overlay)

    draw = ImageDraw.Draw(base)
    title_font = _share_card_font(54, bold=True)
    price_font = _share_card_font(80, bold=True)
    bottom_y = CARD_H - 50

    # Price - large, bold, bottom-left
    price_str = f"${int(item.price)}" if item.price and item.price == int(item.price) else f"${item.price:.2f}" if item.price else "—"
    # Text shadow for pop
    draw.text((43, bottom_y - 75), price_str, fill=(0, 0, 0), font=price_font)
    draw.text((40, bottom_y - 78), price_str, fill=WHITE, font=price_font)

    # Title - above price, truncated
    title = (item.description or "Item")[:45]
    if len(item.description or "") > 45:
        title = title.rstrip() + "…"
    draw.text((43, bottom_y - 145), title, fill=(0, 0, 0), font=title_font)
    draw.text((40, bottom_y - 148), title, fill=WHITE, font=title_font)

    # Logo only - large, bottom-right corner
    logo_path = os.path.join(app.static_folder, "faviconNew.png")
    if os.path.exists(logo_path):
        try:
            logo_img = Image.open(logo_path)
            logo_img = logo_img.convert("RGBA")
            logo_size = 120
            logo_img.thumbnail((logo_size, logo_size), Image.Resampling.LANCZOS)
            lw, lh = logo_img.size
            base.paste(logo_img, (CARD_W - lw - 30, CARD_H - lh - 30), logo_img)
        except Exception:
            pass  # Skip logo if file is corrupt/empty

    # SOLD overlay when applicable
    if item.status == 'sold':
        sold_overlay = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 0))
        draw_sold = ImageDraw.Draw(sold_overlay)
        sold_font = _share_card_font(120, bold=True)
        sold_text = "SOLD"
        bbox = draw_sold.textbbox((0, 0), sold_text, font=sold_font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        cx, cy = CARD_W // 2 - tw // 2, CARD_H // 2 - th // 2
        for dx, dy in [(3, 3), (-3, -3), (3, -3), (-3, 3)]:
            draw_sold.text((cx + dx, cy + dy), sold_text, fill=(0, 0, 0, 180), font=sold_font)
        draw_sold.text((cx, cy), sold_text, fill=(220, 38, 38, 255), font=sold_font)
        base = base.convert("RGBA")
        base = Image.alpha_composite(base, sold_overlay)

    buf = BytesIO()
    base.save(buf, "PNG", optimize=True)
    return buf.getvalue()


@app.route('/share/item/<int:item_id>/card.png')
def share_card_image(item_id):
    """Serve share card PNG for any item (used for link preview og:image)."""
    item = InventoryItem.query.get_or_404(item_id)
    png_bytes = _generate_share_card_png(item)
    if not png_bytes:
        return "Failed to generate share card.", 500
    return Response(png_bytes, mimetype="image/png", headers={
        "Cache-Control": "public, max-age=300",
        "Content-Disposition": "inline; filename=campus-swap-share.png"
    })


# --- IMAGE SERVING ROUTE ---
@app.route('/uploads/<filename>')
def uploaded_file(filename):
    # Temp files (QR mobile, guest, draft staging) are always on disk, never in S3
    if filename.startswith('temp_') or filename.startswith('guest_temp_') or filename.startswith('draft_temp_'):
        return send_from_directory(app.config['TEMP_UPLOAD_FOLDER'], filename)
    if photo_storage.is_s3():
        return redirect(photo_storage.get_photo_url(filename), code=302)
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


# --- QR CODE MOBILE PHOTO UPLOAD ---
UPLOAD_SESSION_EXPIRY_MINUTES = 30

def _cleanup_expired_upload_sessions():
    """Delete upload sessions and temp uploads older than expiry"""
    cutoff = datetime.utcnow() - timedelta(minutes=UPLOAD_SESSION_EXPIRY_MINUTES)
    temp_folder = app.config['TEMP_UPLOAD_FOLDER']
    expired = UploadSession.query.filter(UploadSession.created_at < cutoff).all()
    for s in expired:
        for t in TempUpload.query.filter_by(session_token=s.session_token).all():
            fp = os.path.join(temp_folder, t.filename)
            if os.path.exists(fp):
                try:
                    os.remove(fp)
                except OSError:
                    pass
        db.session.delete(s)
    TempUpload.query.filter(TempUpload.created_at < cutoff).delete(synchronize_session=False)
    db.session.commit()
    # Clean up draft_temp_ files older than 7 days (not tracked in DB)
    draft_cutoff = datetime.utcnow() - timedelta(days=7)
    if os.path.isdir(temp_folder):
        for fn in os.listdir(temp_folder):
            if fn.startswith('draft_temp_'):
                fp = os.path.join(temp_folder, fn)
                try:
                    if datetime.utcfromtimestamp(os.path.getmtime(fp)) < draft_cutoff:
                        os.remove(fp)
                except OSError:
                    pass


@app.route('/api/photos/stage', methods=['POST'])
@login_required
def stage_draft_photos():
    """Stage photos for a draft — converts File objects to server-side temp files so they can survive localStorage serialization."""
    files = request.files.getlist('photos')
    if not files:
        return jsonify({'success': False, 'error': 'No files provided'}), 400
    temp_folder = app.config['TEMP_UPLOAD_FOLDER']
    result = []
    for file in files:
        if not file or not file.filename:
            continue
        is_valid, error_msg = validate_file_upload(file)
        if not is_valid:
            return jsonify({'success': False, 'error': error_msg}), 400
        filename = f"draft_temp_{current_user.id}_{int(time.time())}_{secrets.token_hex(4)}.jpg"
        save_path = os.path.join(temp_folder, filename)
        try:
            img = Image.open(file)
            img = ImageOps.exif_transpose(img)
            img = img.convert("RGBA")
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, (0, 0), img)
            if bg.width > 2000 or bg.height > 2000:
                ratio = 2000 / max(bg.width, bg.height)
                bg = bg.resize((int(bg.width * ratio), int(bg.height * ratio)), Image.Resampling.LANCZOS)
            bg.save(save_path, "JPEG", quality=IMAGE_QUALITY, optimize=True)
        except Exception as e:
            logger.error(f"Draft photo stage error: {e}", exc_info=True)
            return jsonify({'success': False, 'error': 'Error processing image'}), 500
        result.append({
            'filename': filename,
            'url': url_for('uploaded_file', filename=filename, _external=False),
        })
    return jsonify({'success': True, 'photos': result})


@app.route('/api/upload_session/create', methods=['POST'])
def create_upload_session():
    """Create a session for QR code mobile photo upload. Returns token and QR code image. Guests get user_id=None."""
    import base64
    import qrcode

    _cleanup_expired_upload_sessions()

    token = secrets.token_urlsafe(16)
    upload_url = url_for('upload_from_phone', token=token, _external=True)
    # For local dev: replace localhost/127.0.0.1 with LAN IP so phones can connect
    if app.debug:
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(('8.8.8.8', 80))
            local_ip = s.getsockname()[0]
            s.close()
            upload_url = upload_url.replace('://127.0.0.1', f'://{local_ip}').replace('://localhost', f'://{local_ip}')
        except Exception:
            pass

    user_id = current_user.id if current_user.is_authenticated else None
    session_obj = UploadSession(session_token=token, user_id=user_id)
    db.session.add(session_obj)
    db.session.commit()

    if not current_user.is_authenticated:
        session['guest_upload_token'] = token

    qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=8, border=2)
    qr.add_data(upload_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#1A3D1A", back_color="#fff")
    buf = BytesIO()
    img.save(buf, format="PNG")
    qr_base64 = base64.b64encode(buf.getvalue()).decode()

    return jsonify({
        'token': token,
        'session_token': token,
        'upload_url': upload_url,
        'qr_code_base64': qr_base64,
    })


@app.route('/upload_from_phone')
def upload_from_phone():
    """Mobile page: scan QR to open this page, then take/select photo to upload."""
    token = request.args.get('token', '')
    session_obj = UploadSession.query.filter_by(session_token=token).first()
    if not session_obj:
        return render_template('upload_from_phone.html', error='Invalid or expired link. Please scan the QR code again.'), 400
    if datetime.utcnow() - session_obj.created_at > timedelta(minutes=UPLOAD_SESSION_EXPIRY_MINUTES):
        return render_template('upload_from_phone.html', error='This link has expired. Please scan the QR code again.'), 400
    return render_template('upload_from_phone.html', token=token)


@app.route('/upload_from_phone', methods=['POST'])
@csrf.exempt  # Phone has no session; token in URL authenticates
def upload_from_phone_post():
    """Accept photo upload from phone."""
    token = request.form.get('token') or request.args.get('token', '')
    session_obj = UploadSession.query.filter_by(session_token=token).first()
    if not session_obj:
        return jsonify({'success': False, 'error': 'Invalid or expired session'}), 400
    if datetime.utcnow() - session_obj.created_at > timedelta(minutes=UPLOAD_SESSION_EXPIRY_MINUTES):
        return jsonify({'success': False, 'error': 'Session expired'}), 400

    file = request.files.get('photo')
    if not file or not file.filename:
        return jsonify({'success': False, 'error': 'No file provided'}), 400

    is_valid, error_msg = validate_file_upload(file)
    if not is_valid:
        return jsonify({'success': False, 'error': error_msg}), 400

    safe_token = token.replace('/', '_').replace('+', '-')[:32]
    filename = f"temp_{safe_token}_{int(time.time())}_{secrets.token_hex(4)}.jpg"
    save_path = os.path.join(app.config['TEMP_UPLOAD_FOLDER'], filename)
    try:
        img = Image.open(file)
        img = ImageOps.exif_transpose(img)
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, (0, 0), img)
        max_dimension = 2000
        if bg.width > max_dimension or bg.height > max_dimension:
            if bg.width > bg.height:
                new_width = max_dimension
                new_height = int(bg.height * (max_dimension / bg.width))
            else:
                new_height = max_dimension
                new_width = int(bg.width * (max_dimension / bg.height))
            bg = bg.resize((new_width, new_height), Image.Resampling.LANCZOS)
        bg.save(save_path, "JPEG", quality=IMAGE_QUALITY, optimize=True)
    except Exception as e:
        logger.error(f"Error processing mobile upload: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Error processing image'}), 500

    temp = TempUpload(session_token=token, filename=filename)
    db.session.add(temp)
    db.session.commit()

    return jsonify({
        'success': True,
        'filename': filename,
        'url': url_for('uploaded_file', filename=filename, _external=True),
    })


@app.route('/upload_video_from_phone', methods=['POST'])
@csrf.exempt
def upload_video_from_phone_post():
    """Accept video upload from phone via QR session."""
    token = request.form.get('token') or request.args.get('token', '')
    session_obj = UploadSession.query.filter_by(session_token=token).first()
    if not session_obj:
        return jsonify({'success': False, 'error': 'Invalid or expired session'}), 400
    if datetime.utcnow() - session_obj.created_at > timedelta(minutes=UPLOAD_SESSION_EXPIRY_MINUTES):
        return jsonify({'success': False, 'error': 'Session expired'}), 400

    file = request.files.get('video')
    if not file or not file.filename:
        return jsonify({'success': False, 'error': 'No video provided'}), 400

    is_valid, error_msg = validate_video_upload(file)
    if not is_valid:
        return jsonify({'success': False, 'error': error_msg}), 400

    safe_name = secure_filename(file.filename)
    ext = safe_name.rsplit('.', 1)[1].lower() if '.' in safe_name else 'mp4'
    safe_token = token.replace('/', '_').replace('+', '-')[:32]
    filename = f"temp_video_{safe_token}_{int(time.time())}_{secrets.token_hex(4)}.{ext}"
    save_path = os.path.join(app.config['TEMP_UPLOAD_FOLDER'], filename)
    try:
        file.seek(0)
        with open(save_path, 'wb') as f:
            while chunk := file.read(8192):
                f.write(chunk)
    except Exception as e:
        logger.error(f"Error saving mobile video upload: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Error saving video'}), 500

    temp = TempUpload(session_token=token, filename=filename)
    db.session.add(temp)
    db.session.commit()

    return jsonify({
        'success': True,
        'filename': filename,
        'url': url_for('uploaded_file', filename=filename, _external=True),
        'is_video': True,
    })


@app.route('/api/upload_session/status')
def upload_session_status():
    """Return list of temp uploads for the given token (for desktop polling)."""
    token = request.args.get('token', '')
    session_obj = UploadSession.query.filter_by(session_token=token).first()
    if not session_obj:
        return jsonify({'images': [], 'error': 'Session not found'}), 404
    if session_obj.user_id is not None:
        if not current_user.is_authenticated or session_obj.user_id != current_user.id:
            return jsonify({'images': [], 'error': 'Unauthorized'}), 403
    else:
        if session.get('guest_upload_token') != token:
            return jsonify({'images': [], 'error': 'Unauthorized'}), 403
    if datetime.utcnow() - session_obj.created_at > timedelta(minutes=UPLOAD_SESSION_EXPIRY_MINUTES):
        return jsonify({'images': [], 'error': 'Session expired'}), 400

    uploads = TempUpload.query.filter_by(session_token=token).order_by(TempUpload.created_at).all()
    base_url = request.url_root.rstrip('/')
    images = []
    videos = []
    for u in uploads:
        entry = {'filename': u.filename, 'url': url_for('uploaded_file', filename=u.filename, _external=True)}
        if u.filename.startswith('temp_video_'):
            videos.append(entry)
        else:
            images.append(entry)
    return jsonify({'images': images, 'videos': videos})


@app.route('/api/item/<int:item_id>/acknowledge_price_change', methods=['POST'])
@login_required
def acknowledge_price_change(item_id):
    """Mark that the seller has acknowledged we changed their suggested price."""
    item = InventoryItem.query.get_or_404(item_id)
    if item.seller_id != current_user.id:
        return jsonify({"error": "Forbidden"}), 403
    item.price_changed_acknowledged = True
    db.session.commit()
    return jsonify({"ok": True})


@app.route('/checkout/delivery/<int:item_id>', methods=['GET', 'POST'])
def checkout_delivery(item_id):
    """Render the delivery address form (GET) or validate and save address (POST)."""
    item = InventoryItem.query.get_or_404(item_id)

    if item.status == 'sold':
        flash("That item has already been sold.", "error")
        return redirect(url_for('inventory'))
    if item.status != 'available':
        flash("That item isn't available.", "error")
        return redirect(url_for('product_detail', item_id=item_id))
    if AppSetting.get('reserve_only_mode') == 'true':
        flash("Purchases aren't open yet.", "info")
        return redirect(url_for('product_detail', item_id=item_id))

    radius = AppSetting.get('delivery_radius_miles', '50')

    if request.method == 'GET':
        return render_template('checkout_delivery.html', item=item, radius=radius, form={}, error=None)

    # POST: validate and save address
    street = request.form.get('street', '').strip()
    city = request.form.get('city', '').strip()
    state = request.form.get('state', '').strip()
    zip_code = request.form.get('zip', '').strip()
    form_data = {'street': street, 'city': city, 'state': state, 'zip': zip_code}

    if not all([street, city, state, zip_code]):
        return render_template('checkout_delivery.html', item=item, radius=radius,
                               form=form_data, error="Please fill in all address fields.")

    lat, lng = geocode_address(street, city, state, zip_code)
    if lat is None:
        return render_template('checkout_delivery.html', item=item, radius=radius,
                               form=form_data,
                               error="We could not find that address — please double-check and try again.")

    wh_lat = AppSetting.get('warehouse_lat')
    wh_lng = AppSetting.get('warehouse_lng')

    if wh_lat is None or wh_lng is None:
        app.logger.warning("warehouse_lat/warehouse_lng not configured — skipping range check (fail open)")
    else:
        max_miles = float(AppSetting.get('delivery_radius_miles', '50'))
        distance = haversine_miles(float(wh_lat), float(wh_lng), lat, lng)
        if distance > max_miles:
            return render_template('checkout_delivery.html', item=item, radius=radius,
                                   form=form_data,
                                   error=f"Sorry, {city} is outside our delivery area. We currently deliver within {int(max_miles)} miles of Chapel Hill, NC.")

    session['pending_delivery'] = {
        'item_id': item.id,
        'address_string': f"{street}, {city}, {state} {zip_code}",
        'lat': lat,
        'lng': lng,
    }
    return redirect(url_for('checkout_pay', item_id=item_id))


@app.route('/checkout/pay/<int:item_id>')
def checkout_pay(item_id):
    """Validate session and initiate Stripe checkout for item purchase."""
    item = InventoryItem.query.get_or_404(item_id)

    delivery = session.get('pending_delivery')
    if not delivery or delivery.get('item_id') != item_id:
        flash('Please confirm your delivery address to continue.', 'info')
        return redirect(url_for('checkout_delivery', item_id=item_id))

    if item.status != 'available':
        flash("Sorry! This item is no longer available.", "error")
        return redirect(url_for('inventory'))

    try:
        img_url = url_for('uploaded_file', filename=item.photo_url, _external=True) if item.photo_url else None
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'usd',
                    'product_data': {
                        'name': item.description,
                        'images': [img_url] if img_url else [],
                    },
                    'unit_amount': int(item.price * 100),
                },
                'quantity': 1,
            }],
            mode='payment',
            client_reference_id=str(item.id),
            metadata={
                'item_id': item.id,
                'delivery_address': delivery['address_string'],
                'delivery_lat': str(delivery['lat']),
                'delivery_lng': str(delivery['lng']),
            },
            success_url=url_for('item_sold_success', _external=True) + '?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=url_for('inventory', _external=True),
        )
        return redirect(checkout_session.url, code=303)
    except stripe.error.StripeError as e:
        logger.error(f"Stripe error in checkout_pay: {e}")
        flash("Payment processing error. Please try again.", "error")
        return redirect(url_for('checkout_delivery', item_id=item_id))
    except Exception as e:
        logger.error(f"Unexpected error in checkout_pay: {e}", exc_info=True)
        flash("An error occurred. Please try again.", "error")
        return redirect(url_for('checkout_delivery', item_id=item_id))


@app.route('/buy_item/<int:item_id>')
def buy_item(item_id):
    """Create Stripe checkout session for item purchase. Only available when store is live."""
    if not store_is_open():
        flash("The store isn't live yet. Check back on " + store_open_date() + ".", "info")
        return redirect(url_for('product_detail', item_id=item_id))
    try:
        # Use pessimistic locking to prevent race conditions
        item = InventoryItem.query.with_for_update().filter_by(id=item_id).first()

        if not item:
            logger.warning(f"Item {item_id} not found")
            from flask import abort
            # Let 404 propagate - don't catch it in the exception handler
            raise abort(404)

        # Double-check status with lock
        if item.status != 'available':
            logger.info(f"Item {item_id} not available (status: {item.status})")
            flash("Sorry! This item is no longer available.", "error")
            return redirect(url_for('product_detail', item_id=item_id))
        
        if item.price is None or item.price <= 0:
            logger.warning(f"Item {item_id} has invalid price: {item.price}")
            flash("This item is not available for purchase.", "error")
            return redirect(url_for('product_detail', item_id=item_id))
        
        # Create checkout session
        img_url = url_for('uploaded_file', filename=item.photo_url, _external=True) if item.photo_url else None
        
        line_items = [{
            'price_data': {
                'currency': 'usd',
                'product_data': {
                    'name': item.description,
                    'images': [img_url] if img_url else [],
                },
                'unit_amount': int(item.price * 100),
            },
            'quantity': 1,
        }]
        
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=line_items,
            mode='payment',
            client_reference_id=str(item.id),
            metadata={'type': 'item_purchase', 'item_id': item.id},
            success_url=url_for('item_sold_success', _external=True) + '?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=url_for('inventory', _external=True),
        )
        
        logger.info(f"Checkout session created for item {item_id}")
        return redirect(checkout_session.url, code=303)
        
    except stripe.error.StripeError as e:
        logger.error(f"Stripe error in buy_item: {e}")
        flash("Payment processing error. Please try again.", "error")
        return redirect(url_for('product_detail', item_id=item_id))
    except Exception as e:
        # Don't catch 404 errors - let them propagate
        from werkzeug.exceptions import NotFound
        if isinstance(e, NotFound):
            raise
        logger.error(f"Unexpected error in buy_item: {e}", exc_info=True)
        flash("An error occurred. Please try again.", "error")
        return redirect(url_for('inventory'))

@app.route('/item_success')
def item_sold_success():
    session.pop('pending_delivery', None)
    session_id = request.args.get('session_id')
    if not session_id:
        return render_template('item_success.html', item=None)
    
    try:
        session_obj = stripe.checkout.Session.retrieve(session_id)
        item_id = session_obj.metadata.get('item_id')
        
        if not item_id:
            flash("Invalid session.", "error")
            return redirect(url_for('inventory'))
        
        item = InventoryItem.query.get(item_id)
        if not item:
            flash("Item not found.", "error")
            return redirect(url_for('inventory'))
        
        # Verify payment and mark as sold immediately (in case webhook hasn't fired yet)
        # Use pessimistic locking to prevent race conditions
        item = InventoryItem.query.with_for_update().filter_by(id=item_id).first()
        if item and session_obj.payment_status == 'paid' and item.status == 'available':
            item.status = 'sold'
            item.sold_at = datetime.utcnow()
            if item.category and item.category.count_in_stock > 0:
                item.category.count_in_stock -= 1
            db.session.commit()
            logger.info(f"IMMEDIATE: Item {item_id} marked as sold from success page.")
            
            # Email seller (webhook should handle this, but backup in case webhook fails)
            if item.seller:
                try:
                    send_email(
                        item.seller.email,
                        "Your Item Has Sold! - Campus Swap",
                        _item_sold_email_html(item, item.seller)
                    )
                except Exception as email_error:
                    logger.error(f"Failed to send item sold email: {email_error}")
        
        return render_template('item_success.html', item=item)
    except Exception as e:
        logger.error(f"Error in item_success route: {e}", exc_info=True)
        import traceback
        traceback.print_exc()
        flash("Error processing payment. Please contact support.", "error")
        return redirect(url_for('inventory'))


# =========================================================
# SECTION 3: STRIPE WEBHOOK (CORE LOGIC)
# =========================================================

@app.route('/webhook', methods=['POST'])
@csrf.exempt  # Stripe sends raw POST; no CSRF token in webhook payload
def webhook():
    payload = request.get_data(as_text=True)
    sig_header = request.headers.get('Stripe-Signature')

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, endpoint_secret or ''
        )
    except ValueError as e:
        return 'Invalid payload', 400
    except stripe.error.SignatureVerificationError as e:
        if not endpoint_secret:
            return 'STRIPE_WEBHOOK_SECRET not configured', 400
        return 'Invalid signature', 400

    # Handle the event
    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        
        # --- CASE 1: ITEM PURCHASE (delivery flow or legacy buy_item flow) ---
        _meta = session.get('metadata', {})
        if _meta.get('item_id') and (_meta.get('type') == 'item_purchase' or not _meta.get('type')):
            item_id = _meta.get('item_id')

            # Use pessimistic locking to prevent race conditions
            item = InventoryItem.query.with_for_update().filter_by(id=item_id).first()

            if item:
                # Double-check status before updating (prevent double-processing)
                if item.status == 'available':
                    # 1. Update DB
                    item.status = 'sold'
                    item.sold_at = datetime.utcnow()
                    if item.category and item.category.count_in_stock > 0:
                        item.category.count_in_stock -= 1
                    db.session.commit()
                    # PostHog: item sold via Stripe webhook
                    posthog.capture('item_sold', distinct_id=str(item.seller_id), properties={
                        'item_id': item.id,
                        'category': item.category.name if item.category else None,
                        'price': float(item.price) if item.price else None,
                    })
                    logger.info(f"WEBHOOK: Item {item_id} marked as sold")

                    # 2. Email Seller (with payout details)
                    if item.seller:
                        try:
                            send_email(
                                item.seller.email,
                                "Your Item Has Sold! - Campus Swap",
                                _item_sold_email_html(item, item.seller)
                            )
                        except Exception as email_error:
                            logger.error(f"Failed to send email to seller for item {item_id}: {email_error}")
                else:
                    logger.warning(f"WEBHOOK: Item {item_id} already marked as sold (status: {item.status})")

                # 3. Create BuyerOrder from delivery metadata (if present)
                if _meta.get('delivery_address'):
                    try:
                        order = BuyerOrder(
                            item_id=item.id,
                            buyer_email=(session.get('customer_details') or {}).get('email', ''),
                            delivery_address=_meta['delivery_address'],
                            delivery_lat=float(_meta['delivery_lat']) if _meta.get('delivery_lat') else None,
                            delivery_lng=float(_meta['delivery_lng']) if _meta.get('delivery_lng') else None,
                            stripe_session_id=session['id'],
                        )
                        db.session.add(order)
                        db.session.commit()
                        logger.info(f"WEBHOOK: BuyerOrder created for item {item_id}")
                    except Exception as order_err:
                        logger.error(f"WEBHOOK: Failed to create BuyerOrder for item {item_id}: {order_err}")
            else:
                logger.error(f"WEBHOOK: Item {item_id} not found in database")

        # --- CASE 2: CONFIRM PICKUP (post-approval payment) ---
        elif session.get('metadata', {}).get('type') == 'confirm_pickup':
            item_ids_str = session.get('metadata', {}).get('item_ids', '')
            pickup_week = session.get('metadata', {}).get('pickup_week', '')
            user_id = session.get('metadata', {}).get('user_id')
            if item_ids_str and pickup_week and user_id:
                item_ids = [int(x.strip()) for x in item_ids_str.split(',') if x.strip()]
                for item_id in item_ids:
                    item = InventoryItem.query.get(item_id)
                    if item and item.seller_id == int(user_id) and item.status == 'pending_logistics' and item.collection_method == 'online':
                        item.pickup_week = pickup_week
                        item.status = 'available'
                        if item.category:
                            item.category.count_in_stock = (item.category.count_in_stock or 0) + 1
                user = User.query.get(user_id)
                if user:
                    user.has_paid = True
                    # Auto-resolve pickup reminder alerts
                    for pa in SellerAlert.query.filter_by(user_id=int(user_id), alert_type='pickup_reminder', resolved=False).all():
                        pa.resolved = True
                        pa.resolved_at = datetime.utcnow()
                db.session.commit()
                logger.info(f"WEBHOOK: Confirm pickup - items {item_ids} set to available")

        # --- CASE 3: SELLER ACTIVATION ---
        elif session.get('metadata', {}).get('type') == 'seller_activation':
            user_id = session.get('metadata').get('user_id')
            user = User.query.get(user_id)
            
            if user:
                # 1. Update DB
                user.has_paid = True
                user.is_seller = True
                db.session.commit()
                logger.info(f"WEBHOOK: User {user_id} activated as seller")
                
                # 2. Send activation confirmation email
                try:
                    activation_content = f"""
                    <div style="font-family: sans-serif; padding: 20px; max-width: 500px;">
                        <h2 style="color: #166534;">You're all set!</h2>
                        <p>Hi {user.full_name or 'there'},</p>
                        <p>Your item has been submitted and you've confirmed your space in our store for the summer.</p>
                        <div style="background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 8px; padding: 16px; margin: 20px 0;">
                            <p style="margin: 0 0 8px;"><strong>What happens next:</strong></p>
                            <p style="margin: 0;">We will come to your listed address during move-out week to pick your item up. More information about exact pickup logistics will follow.</p>
                        </div>
                        <p><a href="{url_for('dashboard', _external=True)}" style="background: #166534; color: white; padding: 12px 24px; text-decoration: none; border-radius: 8px; display: inline-block;">Go to Dashboard</a></p>
                        <p>Thanks for joining Campus Swap!</p>
                    </div>
                    """
                    send_email(
                        user.email,
                        "Seller Activation Complete - Campus Swap",
                        activation_content
                    )
                except Exception as email_error:
                    logger.error(f"Failed to send seller activation email: {email_error}")
            else:
                logger.error(f"WEBHOOK: User {user_id} not found in database")

        # --- CASE 4: PAYOUT BOOST ---
        elif session.get('metadata', {}).get('type') == 'payout_boost':
            _handle_boost_webhook(session)

    elif event['type'] == 'setup_intent.succeeded':
        setup_intent = event['data']['object']
        user_id = setup_intent.get('metadata', {}).get('user_id')
        if user_id:
            user = User.query.get(int(user_id))
            if user:
                pm_id = setup_intent.get('payment_method')
                if pm_id:
                    user.stripe_payment_method_id = pm_id
                    user.payment_declined = False
                    db.session.commit()
                    logger.info(f"WEBHOOK: User {user_id} payment method saved")

    return 'Success', 200


@app.route('/shop/notify', methods=['POST'])
def shop_notify_signup():
    """Capture email for Shop Drop launch notification."""
    email = request.form.get('email', '').strip().lower()
    if not email:
        flash("Please enter your email.", "error")
        return redirect(url_for('inventory'))

    ip = request.headers.get('X-Forwarded-For', request.remote_addr or '').split(',')[0].strip()
    signup = ShopNotifySignup(email=email, ip_address=ip or None)
    db.session.add(signup)
    db.session.commit()
    flash("We'll let you know!", "success")
    return redirect(url_for('inventory'))


# =========================================================
# SECTION 4: ADMIN ROUTES
# =========================================================

@app.route('/admin', methods=['GET', 'POST'])
def admin_panel():
    # Only allow Admin (Checks is_admin flag)
    if not current_user.is_authenticated or not current_user.is_admin:
         flash("Access denied.", "error")
         return redirect(url_for('index'))

    # GET /admin → redirect to new ops hub (spec: Admin UI Redesign)
    if request.method == 'GET':
        return redirect(url_for('admin_ops'), 302)

    if request.method == 'POST':
        logger.info(f"ADMIN_POST form_keys={list(request.form.keys())}")
    
    # Admin can toggle pickup period
    if request.method == 'POST' and 'toggle_pickup_period' in request.form:
        current_status = get_pickup_period_active()
        new_status = not current_status
        AppSetting.set('pickup_period_active', str(new_status))
        flash(f"Pickup period {'activated' if new_status else 'closed'}.", "success")

    # Admin can toggle shop teaser mode (pre-launch blurred mosaic + notify form)
    if request.method == 'POST' and 'toggle_shop_teaser' in request.form:
        current = AppSetting.get('shop_teaser_mode', 'false')
        new_val = 'false' if current == 'true' else 'true'
        AppSetting.set('shop_teaser_mode', new_val)
        flash(f"Shop Teaser Mode {'enabled' if new_val == 'true' else 'disabled'}.", "success")

    # Admin can update store go-live date (controls when items become purchaseable)
    if request.method == 'POST' and 'update_store_open_date' in request.form:
        new_date = request.form.get('store_open_date_value', '').strip()
        if new_date:
            try:
                from datetime import date as _date
                _date.fromisoformat(new_date)  # validate format
                AppSetting.set('store_open_date', new_date)
                flash(f"Store open date updated to {new_date}.", "success")
            except ValueError:
                flash("Invalid date format. Use YYYY-MM-DD.", "error")

    # Referral program settings (super admin only)
    if request.method == 'POST' and 'save_referral_settings' in request.form:
        if not is_super_admin():
            flash("Super admin access required.", "error")
        else:
            for key in ('referral_base_rate', 'referral_signup_bonus', 'referral_bonus_per_referral',
                        'referral_max_rate'):
                val = request.form.get(key, '').strip()
                if val.isdigit():
                    AppSetting.set(key, val)
            active_val = 'true' if request.form.get('referral_program_active') == 'true' else 'false'
            AppSetting.set('referral_program_active', active_val)
            flash("Referral program settings saved.", "success")

    # 1. Update Category Counts (super admin only)
    if request.method == 'POST' and 'update_all_counts' in request.form:
        if not is_super_admin():
            is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
            if is_ajax:
                return jsonify({'success': False, 'message': "Category counts require super admin access."}), 403
            flash("Category counts require super admin access.", "error")
            return redirect(url_for('admin_panel') + '#categories')
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        updated = 0
        for key, value in request.form.items():
            if key.startswith('counts_'):
                try:
                    cat_id = int(key.split('_')[1])
                    cat = InventoryCategory.query.get(cat_id)
                    if cat: 
                        cat.count_in_stock = int(value)
                        updated += 1
                except ValueError: pass
        db.session.commit()
        if is_ajax:
            return jsonify({'success': True, 'message': f"Updated {updated} categor{'y' if updated == 1 else 'ies'}."})
        flash(f"Updated {updated} categor{'y' if updated == 1 else 'ies'}.", "success")

    # 2. Add Item (Admin Side - Quick Add)
    if request.method == 'POST' and 'add_item' in request.form:
        cat_id = request.form.get('category_id')
        desc = request.form.get('description')
        long_desc = request.form.get('long_description')
        quality = request.form.get('quality')
        seller_email = request.form.get('seller_email', '').strip()
        seller_name = request.form.get('seller_name', '').strip()
        files = request.files.getlist('photos')
        
        # Handle seller assignment (optional)
        seller_id = None
        if seller_email:
            seller = User.query.filter_by(email=seller_email).first()
            if seller:
                seller_id = seller.id
            elif seller_name:
                # Create new user if email provided but doesn't exist
                new_seller = User(email=seller_email, full_name=seller_name)
                db.session.add(new_seller)
                db.session.flush()
                seller_id = new_seller.id
        
        if files and files[0].filename != '':
            # Validate quality
            quality_valid, quality_value = validate_quality(quality)
            if not quality_valid:
                flash(f"Invalid quality: {quality_value}", "error")
                return redirect(url_for('admin_panel') + '#add-item')
            
            # Validate description length
            if len(desc) > MAX_DESCRIPTION_LENGTH:
                flash(f"Description too long (max {MAX_DESCRIPTION_LENGTH} characters)", "error")
                return redirect(url_for('admin_panel') + '#add-item')
            
            if long_desc and len(long_desc) > MAX_LONG_DESCRIPTION_LENGTH:
                flash(f"Long description too long (max {MAX_LONG_DESCRIPTION_LENGTH} characters)", "error")
                return redirect(url_for('admin_panel') + '#add-item')
            
            # Quick Add: status pending (price set later)
            collection_method = (request.form.get('collection_method') or 'online').strip()
        if collection_method not in ('online', 'free'):
            collection_method = 'online'
            new_item = InventoryItem(
                category_id=cat_id, description=desc, long_description=long_desc,
                price=None, quality=quality_value, photo_url="", status="pending_valuation",
                seller_id=seller_id, collection_method=collection_method
            )
            db.session.add(new_item)
            db.session.flush()
            
            cover_set = False
            for i, file in enumerate(files):
                if file.filename:
                    # Validate file upload
                    is_valid, error_msg = validate_file_upload(file)
                    if not is_valid:
                        db.session.rollback()
                        flash(f"File upload error: {error_msg}", "error")
                        return redirect(url_for('admin_panel') + '#add-item')
                    
                    filename = f"item_{new_item.id}_{int(time.time())}_{i}.jpg"
                    try:
                        photo_storage.save_photo(file, filename)
                        if not cover_set:
                            new_item.photo_url = filename
                            cover_set = True
                        db.session.add(ItemPhoto(item_id=new_item.id, photo_url=filename))
                    except Exception as img_error:
                        db.session.rollback()
                        logger.error(f"Error processing image: {img_error}", exc_info=True)
                        flash("Error processing image. Please try again.", "error")
                        return redirect(url_for('admin_panel') + '#add-item')
            
            # Don't increment count_in_stock yet - item is pending, not available
            db.session.commit()
            flash(f"Item '{desc}' added to pending items. Set price to approve.", "success")

    # 3. Bulk Update Items
    if request.method == 'POST' and 'bulk_update_items' in request.form:
        logger.info("ADMIN: Entering bulk_update_items handler")
        updated_count = 0
        for key, value in request.form.items():
            if key.startswith('price_'):
                try:
                    item_id = int(key.split('_')[1])
                    item = InventoryItem.query.get(item_id)
                    if item:
                        # Validate price if provided
                        if value and value.strip():
                            price_valid, price_result = validate_price(value)
                            if not price_valid:
                                flash(f"Invalid price for item {item_id}: {price_result}", "error")
                                continue
                            new_price = price_result
                        else:
                            new_price = None
                        
                        # When admin approves (sets price): item goes to pending_logistics
                        # Seller must confirm pickup week (and pay) before item goes live
                        if item.status == 'pending_valuation' and new_price is not None:
                            item.status = 'pending_logistics'
                            # Don't add to count_in_stock until seller confirms logistics

                            # Send email: item approved, confirm pickup
                            if item.seller and item.seller.email:
                                try:
                                    fee_text = ""
                                    if item.collection_method == 'online':
                                        fee = SERVICE_FEE_CENTS // 100
                                        fee_text = f" Confirm your pickup week and pay ${fee} to secure your spot."
                                    elif item.collection_method == 'free':
                                        fee_text = " Add your address and select a pickup window in your dashboard—no payment required."
                                    email_content = f"""
                                    <div style="font-family: sans-serif; padding: 20px; max-width: 500px;">
                                        <h2 style="color: #166534;">Your Item Has Been Approved!</h2>
                                        <p>Great news! Your item <strong>{item.description}</strong> has been approved.</p>
                                        <div style="background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 8px; padding: 16px; margin: 20px 0;">
                                            <p style="margin: 0 0 8px;"><strong>Price:</strong> ${new_price:.2f}</p>
                                            <p style="margin: 0;">Next step:{fee_text}</p>
                                        </div>
                                        <p><a href="{url_for('dashboard', _external=True)}" style="background: #166534; color: white; padding: 12px 24px; text-decoration: none; border-radius: 8px;">Confirm in Dashboard</a></p>
                                        <p>Thanks for selling with Campus Swap!</p>
                                    </div>
                                    """
                                    send_email(
                                        item.seller.email,
                                        "Your Item Has Been Approved - Campus Swap",
                                        email_content
                                    )
                                except Exception as email_error:
                                    logger.error(f"Failed to send item approved email: {email_error}")
                        
                        old_price = item.price
                        item.price = new_price
                        item.price_updated_at = datetime.utcnow()
                        item.price_changed_acknowledged = False
                        updated_count += 1
                        
                        # Quality & Category Updates
                        if f"quality_{item_id}" in request.form:
                            quality_valid, quality_value = validate_quality(request.form[f"quality_{item_id}"])
                            if quality_valid:
                                item.quality = quality_value
                            else:
                                flash(f"Invalid quality for item {item_id}: {quality_value}", "error")
                        if f"category_{item_id}" in request.form:
                            try:
                                new_cat_id = int(request.form[f"category_{item_id}"])
                                if item.category_id != new_cat_id and item.status == 'available':
                                    old_cat = InventoryCategory.query.get(item.category_id)
                                    new_cat = InventoryCategory.query.get(new_cat_id)
                                    if old_cat: old_cat.count_in_stock -= 1
                                    if new_cat: new_cat.count_in_stock += 1
                                item.category_id = new_cat_id
                            except ValueError:
                                pass
                except (ValueError, TypeError) as e:
                    logger.error(f"Error updating item {key}: {e}", exc_info=True)
                    continue
                except Exception as e:
                    logger.error(f"Unexpected error updating item {key}: {e}", exc_info=True)
                    import traceback
                    traceback.print_exc()
                    continue
        
        try:
            is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
            db.session.commit()
            result_msg = f"Updated {updated_count} item(s)." if updated_count > 0 else "Changes saved."
            logger.info(f"ADMIN: bulk_update committed, updated_count={updated_count}")
            if is_ajax:
                return jsonify({'success': True, 'message': result_msg, 'reload': True})
            if updated_count > 0:
                flash(f"Updated {updated_count} item(s).", "success")
            else:
                flash("Changes saved.", "success")
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error committing bulk_update: {e}", exc_info=True)
            import traceback
            traceback.print_exc()
            if is_ajax:
                return jsonify({'success': False, 'message': "Error updating items. Please try again."}), 500
            flash("Error updating items. Please try again.", "error")

    # 4. Delete / Sold / Available Toggles
    if request.method == 'POST':
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        
        if 'delete_item' in request.form:
            delete_val = request.form.get('delete_item')
            logger.info(f"ADMIN: delete_item in form, value={delete_val}")
            try:
                item = InventoryItem.query.get(delete_val)
                if item:
                    item_desc = item.description
                    item_id = item.id
                    if item.status == 'available':
                        cat = InventoryCategory.query.get(item.category_id)
                        if cat and cat.count_in_stock > 0: cat.count_in_stock -= 1
                    # Delete related ItemPhotos first (cascade handles it, but explicit delete is safer)
                    for photo in item.gallery_photos[:]:
                        db.session.delete(photo)
                    db.session.delete(item)
                    db.session.commit()
                    logger.info(f"ADMIN: Deleted item {item_id}")
                    if is_ajax:
                        return jsonify({'success': True, 'message': f"Item '{item_desc}' deleted.", 'remove_row': True, 'item_id': item_id})
                    flash(f"Item '{item_desc}' deleted.", "success")
                else:
                    logger.warning(f"ADMIN: delete_item - item not found for id={delete_val}")
            except Exception as e:
                db.session.rollback()
                logger.error(f"ADMIN: Error deleting item {delete_val}: {e}", exc_info=True)
                if is_ajax:
                    return jsonify({'success': False, 'message': f"Could not delete item: {str(e)}"}), 500
                flash(f"Could not delete item: {str(e)}", "error")
        
        elif 'mark_sold' in request.form:
            item = InventoryItem.query.get(request.form.get('mark_sold'))
            if item and item.status == 'available':
                item.status = "sold"
                item.sold_at = datetime.utcnow()  # Track when it sold
                cat = InventoryCategory.query.get(item.category_id)
                if cat and cat.count_in_stock > 0: cat.count_in_stock -= 1
                db.session.commit()
                # Email seller (same as webhook - payout details)
                if item.seller:
                    try:
                        send_email(
                            item.seller.email,
                            "Your Item Has Sold! - Campus Swap",
                            _item_sold_email_html(item, item.seller)
                        )
                    except Exception as e:
                        logger.error(f"Error sending email: {e}", exc_info=True)
                if is_ajax:
                    return jsonify({'success': True, 'message': f"Item '{item.description}' marked as sold.", 'reload': True})
                flash(f"Item '{item.description}' marked as sold.", "success")
        
        elif 'mark_payout_sent' in request.form:
            item = InventoryItem.query.get(request.form.get('mark_payout_sent'))
            if item and item.status == 'sold':
                item.payout_sent = True
                db.session.commit()
                # PostHog: admin marked payout as sent
                posthog.capture('payout_marked_sent', distinct_id=str(current_user.id), properties={
                    'item_id': item.id,
                    'is_admin': True
                })
                if is_ajax:
                    return jsonify({'success': True, 'message': f"Payout marked as sent for {item.description}.", 'reload': True})
                flash(f"Payout marked as sent for {item.description}.", "success")
                return redirect(url_for('admin_panel') + '#gallery-items')

        elif 'mark_available' in request.form:
            item = InventoryItem.query.get(request.form.get('mark_available'))
            if item and item.status == 'sold':
                item.status = "available"
                item.sold_at = None  # Reset sold timestamp
                item.payout_sent = False  # Reset payout status
                cat = InventoryCategory.query.get(item.category_id)
                if cat: cat.count_in_stock += 1
                db.session.commit()
                if is_ajax:
                    return jsonify({'success': True, 'message': f"Item '{item.description}' marked as available.", 'reload': True})
                flash(f"Item '{item.description}' marked as available.", "success")

        elif 'mark_picked_up' in request.form:
            item = InventoryItem.query.get(request.form.get('mark_picked_up'))
            if item:
                item.picked_up_at = datetime.utcnow()
                db.session.commit()
                if is_ajax:
                    return jsonify({'success': True, 'message': f"'{item.description}' marked as picked up.", 'reload': False})
                flash(f"'{item.description}' marked as picked up.", "success")

        elif 'mark_at_store' in request.form:
            item = InventoryItem.query.get(request.form.get('mark_at_store'))
            if item:
                item.arrived_at_store_at = datetime.utcnow()
                db.session.commit()
                if is_ajax:
                    return jsonify({'success': True, 'message': f"'{item.description}' marked as arrived at store.", 'reload': False})
                flash(f"'{item.description}' marked as arrived at store.", "success")

        elif 'unmark_at_store' in request.form:
            item = InventoryItem.query.get(request.form.get('unmark_at_store'))
            if item:
                item.arrived_at_store_at = None
                db.session.commit()
                if is_ajax:
                    return jsonify({'success': True, 'message': f"'{item.description}' unmarked from at store.", 'reload': False})
                flash(f"'{item.description}' unmarked from at store.", "success")

        elif 'unmark_picked_up' in request.form:
            item = InventoryItem.query.get(request.form.get('unmark_picked_up'))
            if item:
                item.picked_up_at = None
                item.arrived_at_store_at = None  # Can't be at store if not picked up
                db.session.commit()
                if is_ajax:
                    return jsonify({'success': True, 'message': f"'{item.description}' unmarked from picked up.", 'reload': False})
                flash(f"'{item.description}' unmarked from picked up.", "success")

    # Data Loading with optimized queries
    commodities = InventoryCategory.query.filter_by(parent_id=None).order_by(InventoryCategory.id).all()
    all_cats = InventoryCategory.query.filter_by(parent_id=None).order_by(InventoryCategory.id).all()
    
    # Filter: Show all pending items (no payment gate; charge at pickup)
    pending_items = InventoryItem.query.options(
        joinedload(InventoryItem.category),
        joinedload(InventoryItem.seller)
    ).filter(InventoryItem.status == 'pending_valuation').order_by(InventoryItem.date_added.asc()).all()
    
    gallery_items = InventoryItem.query.options(
        joinedload(InventoryItem.category),
        joinedload(InventoryItem.seller)
    ).filter(
        InventoryItem.status != 'pending_valuation',
        InventoryItem.status != 'rejected'
    ).order_by(InventoryItem.date_added.desc()).all()
    
    pickup_period_active = get_pickup_period_active()
    
    # Calculate database stats
    total_users = User.query.count()
    total_items = InventoryItem.query.count()
    sold_items = InventoryItem.query.filter_by(status='sold').count()
    pending_items_count = InventoryItem.query.filter_by(status='pending_valuation').count()
    available_items = InventoryItem.query.filter_by(status='available').count()
    
    # Free tier data for admin panel
    free_confirmed_ids_str = AppSetting.get('free_confirmed_user_ids') or ''
    free_rejected_ids_str = AppSetting.get('free_rejected_user_ids') or ''
    free_confirmed_ids = set(int(x) for x in free_confirmed_ids_str.split(',') if x.strip().isdigit())
    free_rejected_ids = set(int(x) for x in free_rejected_ids_str.split(',') if x.strip().isdigit())

    # All users with free-tier items in pending_logistics, sorted by total item value desc
    from sqlalchemy import func as sqlfunc
    free_user_rows = db.session.query(
        InventoryItem.seller_id,
        sqlfunc.sum(InventoryItem.price).label('total_value'),
        sqlfunc.count(InventoryItem.id).label('item_count')
    ).filter(
        InventoryItem.collection_method == 'free',
        InventoryItem.status == 'pending_logistics',
        InventoryItem.seller_id.isnot(None)
    ).group_by(InventoryItem.seller_id).order_by(sqlfunc.sum(InventoryItem.price).desc()).all()

    free_tier_users = []
    for row in free_user_rows:
        user = User.query.get(row.seller_id)
        if user:
            user_items = InventoryItem.query.filter_by(
                seller_id=user.id, collection_method='free', status='pending_logistics'
            ).all()
            free_tier_users.append({
                'user': user,
                'user_items': user_items,
                'total_value': row.total_value or 0,
                'item_count': row.item_count,
                'is_confirmed': user.id in free_confirmed_ids,
                'is_rejected': user.id in free_rejected_ids,
            })

    # Pickup nudge: sellers with approved/available items but no pickup_week on any item
    nudge_sellers_raw = User.query.filter(
        User.is_seller == True,
        User.items.any(InventoryItem.status.in_(['approved', 'available']))
    ).all()
    nudge_sellers = []
    for u in nudge_sellers_raw:
        # Skip if any item already has pickup_week set
        if any(i.pickup_week for i in u.items):
            continue
        # Skip rejected free-tier sellers
        if u.id in free_rejected_ids:
            continue
        # Free-tier sellers must be confirmed to appear
        free_items = [i for i in u.items if i.collection_method == 'free']
        if free_items and u.id not in free_confirmed_ids:
            continue
        approved_items = [i for i in u.items if i.status in ('approved', 'available')]
        if not approved_items:
            continue
        earliest_approved = min((i.date_added for i in approved_items), default=None)
        days_since = (datetime.utcnow() - earliest_approved).days if earliest_approved else 0
        last_nudge = SellerAlert.query.filter_by(
            user_id=u.id, alert_type='pickup_reminder'
        ).order_by(SellerAlert.created_at.desc()).first()
        nudge_sellers.append({
            'user': u,
            'approved_count': len(approved_items),
            'days_since_approval': days_since,
            'last_nudged': last_nudge.created_at.strftime('%b %d') if last_nudge else 'Never',
            'tier': 'Free' if free_items else 'Pro',
        })
    nudge_sellers.sort(key=lambda x: (-x['days_since_approval'], (x['user'].full_name or '').lower()))

    # Crew data
    crew_pending_raw = User.query.filter_by(worker_status='pending').all()
    crew_pending_applications = []
    for u in crew_pending_raw:
        app_record = u.worker_application
        if not app_record:
            continue
        last_avail = (
            WorkerAvailability.query
            .filter_by(user_id=u.id, week_start=None)
            .first()
        )
        avail_dict = {}
        for day in ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']:
            for slot in ['am', 'pm']:
                field = f"{day}_{slot}"
                avail_dict[field] = getattr(last_avail, field, True) if last_avail else True
        crew_pending_applications.append({
            'user': u,
            'application': app_record,
            'availability': last_avail,
            'avail_dict': avail_dict,
        })
    crew_pending_applications.sort(key=lambda x: x['application'].applied_at)
    crew_approved_workers = User.query.filter_by(is_worker=True, worker_status='approved').order_by(User.full_name).all()

    # Referral program stats (super admin only)
    referral_stats = None
    if current_user.is_super_admin:
        total_confirmed_referrals = Referral.query.filter_by(confirmed=True).count()
        seller_users = User.query.filter(User.is_seller == True).all()
        avg_payout_rate = round(sum(u.payout_rate for u in seller_users) / len(seller_users), 1) if seller_users else 0
        sellers_at_max = sum(1 for u in seller_users if u.payout_rate >= int(AppSetting.get('referral_max_rate', '100')))
        referral_stats = {
            'total_confirmed': total_confirmed_referrals,
            'avg_payout_rate': avg_payout_rate,
            'sellers_at_max': sellers_at_max,
        }

    # Payout summary for admin panel banner
    unpaid_sold_items = InventoryItem.query.filter_by(payout_sent=False).filter(InventoryItem.status == 'sold').all()
    unpaid_items_count = len(unpaid_sold_items)
    unpaid_total = round(sum(
        (i.price or 0) * _get_payout_percentage(i) for i in unpaid_sold_items
    ), 2)

    return render_template('admin.html', commodities=commodities, all_cats=all_cats,
                           pending_items=pending_items, gallery_items=gallery_items,
                           pickup_period_active=pickup_period_active,
                           total_users=total_users, total_items=total_items,
                           sold_items=sold_items, pending_items_count=pending_items_count,
                           available_items=available_items,
                           free_tier_users=free_tier_users,
                           free_confirmed_ids=free_confirmed_ids,
                           free_rejected_ids=free_rejected_ids,
                           warehouse_spots=get_warehouse_spots_remaining(),
                           nudge_sellers=nudge_sellers,
                           crew_pending_applications=crew_pending_applications,
                           crew_approved_workers=crew_approved_workers,
                           referral_stats=referral_stats,
                           referral_base_rate=AppSetting.get('referral_base_rate', '20'),
                           referral_signup_bonus=AppSetting.get('referral_signup_bonus', '10'),
                           referral_bonus_per_referral=AppSetting.get('referral_bonus_per_referral', '10'),
                           referral_max_rate=AppSetting.get('referral_max_rate', '100'),
                           referral_program_active=AppSetting.get('referral_program_active', 'true'),
                           unpaid_items_count=unpaid_items_count,
                           unpaid_total=unpaid_total,
                           shop_teaser_mode=AppSetting.get('shop_teaser_mode', 'false'))


@app.route('/admin/approve', methods=['GET', 'POST'])
@login_required
def admin_approve():
    """Approval queue — GET redirects to /admin/items?view=approve (Admin UI Redesign)."""
    if not current_user.is_authenticated or not current_user.is_admin:
        flash("Access denied.", "error")
        return redirect(url_for('index'))
    if not is_super_admin():
        flash("Item approval requires super admin access.", "error")
        return redirect(url_for('admin_ops'))
    if request.method == 'GET' and not request.args.get('item'):
        # Bare GET → new items tab. Single-item GET (?item=<id>) passes through to the old full view.
        return redirect(url_for('admin_items', view='approve'), 302)

    all_cats = InventoryCategory.query.filter_by(parent_id=None).order_by(InventoryCategory.id).all()

    if request.method == 'POST':
        action = request.form.get('action')  # 'approve' or 'reject'
        item_id = request.form.get('item_id')
        sort_val = request.form.get('sort', request.args.get('sort', 'date'))
        if sort_val not in ('price_desc', 'price_asc', 'date'):
            sort_val = 'date'
        if not item_id or action not in ('approve', 'reject'):
            flash("Invalid request.", "error")
            return redirect(url_for('admin_approve', sort=sort_val))
        
        item = InventoryItem.query.options(
            joinedload(InventoryItem.category),
            joinedload(InventoryItem.seller)
        ).get(item_id)
        
        if not item or item.status not in ('pending_valuation', 'needs_info'):
            flash("Item not found or already processed.", "error")
            return redirect(url_for('admin_approve', sort=sort_val))

        # If approving/rejecting a needs_info item, auto-resolve any outstanding alerts
        if item.status == 'needs_info':
            for a in SellerAlert.query.filter_by(item_id=item.id, resolved=False).all():
                a.resolved = True
                a.resolved_at = datetime.utcnow()

        if action == 'reject':
            desc = item.description
            item.status = 'rejected'
            db.session.commit()
            flash(f"Rejected '{desc}'.", "success")
            return redirect(url_for('admin_approve', sort=sort_val))
        
        # Approve: set price, category, quality, status
        price_str = request.form.get('price', '').strip()
        if not price_str:
            flash("Please set a price to approve.", "error")
            return redirect(url_for('admin_approve', item=item_id, sort=sort_val))
        
        price_valid, price_result = validate_price(price_str)
        if not price_valid:
            flash(f"Invalid price: {price_result}", "error")
            return redirect(url_for('admin_approve', item=item_id, sort=sort_val))
        
        item.price = price_result
        item.price_updated_at = datetime.utcnow()
        item.price_changed_acknowledged = False
        if request.form.get('category_id'):
            try:
                item.category_id = int(request.form['category_id'])
            except (ValueError, TypeError):
                pass
        if request.form.get('subcategory_id'):
            try:
                new_sub = int(request.form['subcategory_id'])
                sub_cat = InventoryCategory.query.get(new_sub)
                if sub_cat and sub_cat.parent_id == item.category_id:
                    item.subcategory_id = new_sub
            except (ValueError, TypeError):
                pass
        if request.form.get('quality'):
            qv, qr = validate_quality(request.form['quality'])
            if qv:
                item.quality = qr
        item.status = 'pending_logistics'
        
        # Send approval email
        if item.seller and item.seller.email:
            try:
                fee_text = ""
                if item.collection_method == 'online':
                    fee = SERVICE_FEE_CENTS // 100
                    fee_text = f" Confirm your pickup week and pay ${fee} to secure your spot."
                elif item.collection_method == 'free':
                    fee_text = " Add your address and select a pickup window in your dashboard—no payment required."
                email_content = f"""
                <div style="font-family: sans-serif; padding: 20px; max-width: 500px;">
                    <h2 style="color: #166534;">Your Item Has Been Approved!</h2>
                    <p>Great news! Your item <strong>{item.description}</strong> has been approved.</p>
                    <div style="background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 8px; padding: 16px; margin: 20px 0;">
                        <p style="margin: 0 0 8px;"><strong>Price:</strong> ${item.price:.2f}</p>
                        <p style="margin: 0;">Next step:{fee_text}</p>
                    </div>
                    <p><a href="{url_for('dashboard', _external=True)}" style="background: #166534; color: white; padding: 12px 24px; text-decoration: none; border-radius: 8px;">Confirm in Dashboard</a></p>
                    <p>Thanks for selling with Campus Swap!</p>
                </div>
                """
                send_email(item.seller.email, "Your Item Has Been Approved - Campus Swap", email_content)
            except Exception as e:
                logger.error(f"Failed to send approval email: {e}")
        
        db.session.commit()
        # PostHog: admin approved item
        try:
            posthog.capture('item_approved', distinct_id=str(current_user.id), properties={
                'item_id': item.id,
                'category': item.category.name if item.category else None,
                'price': float(item.price) if item.price else None,
                'is_admin': True
            })
        except Exception:
            pass
        flash(f"Approved '{item.description}' at ${item.price:.2f}.", "success")
        return redirect(url_for('admin_approve', sort=sort_val))
    
    # GET: fetch pending items with sort; optionally one item for approve form
    sort_param = request.args.get('sort', 'date')
    if sort_param not in ('price_desc', 'price_asc', 'date'):
        sort_param = 'date'

    base_query = InventoryItem.query.options(
        joinedload(InventoryItem.category),
        joinedload(InventoryItem.seller)
    ).filter_by(status='pending_valuation')

    if sort_param == 'price_desc':
        base_query = base_query.order_by(nulls_last(InventoryItem.suggested_price.desc()), InventoryItem.date_added.asc())
    elif sort_param == 'price_asc':
        base_query = base_query.order_by(nulls_last(InventoryItem.suggested_price.asc()), InventoryItem.date_added.asc())
    else:
        base_query = base_query.order_by(InventoryItem.date_added.asc())

    pending_items = base_query.all()
    total_pending = len(pending_items)

    item_id_param = request.args.get('item')
    pending_item = None
    if item_id_param:
        try:
            pid = int(item_id_param)
            pending_item = next((i for i in pending_items if i.id == pid), None)
        except (ValueError, TypeError):
            pass

    # Find items that were previously sent back (have resolved needs_info alerts)
    resubmitted_item_ids = set()
    if pending_items:
        pids = [i.id for i in pending_items]
        resubmitted_alerts = SellerAlert.query.filter(
            SellerAlert.item_id.in_(pids),
            SellerAlert.alert_type == 'needs_info',
            SellerAlert.resolved == True
        ).all()
        resubmitted_item_ids = {a.item_id for a in resubmitted_alerts}

    # Load AI result for the selected item (if viewing single item)
    ai_result = None
    if pending_item:
        ai_result = ItemAIResult.query.filter_by(item_id=pending_item.id).first()

    return render_template('admin_approve.html',
        pending_item=pending_item,
        pending_items=pending_items,
        all_cats=all_cats,
        total_pending=total_pending,
        sort=sort_param,
        resubmitted_item_ids=resubmitted_item_ids,
        ai_result=ai_result
    )


@app.route('/admin/item/<int:item_id>/request_info', methods=['POST'])
@login_required
def admin_request_info(item_id):
    """Admin sends a 'more info needed' request to the seller."""
    if not current_user.is_admin:
        flash("Access denied.", "error")
        return redirect(url_for('index'))
    item = InventoryItem.query.get_or_404(item_id)
    if item.status != 'pending_valuation':
        flash("This item is not in the approval queue.", "error")
        return redirect(url_for('admin_approve'))

    reasons = request.form.getlist('reasons')
    custom_note = (request.form.get('custom_note') or '').strip()[:500]
    if not reasons and not custom_note:
        flash("Please select at least one reason or add a note.", "error")
        return redirect(url_for('admin_approve', item=item_id))

    import json
    item.status = 'needs_info'
    alert = SellerAlert(
        item_id=item.id,
        user_id=item.seller_id,
        created_by_id=current_user.id,
        alert_type='needs_info',
        reasons=json.dumps(reasons),
        custom_note=custom_note or None
    )
    db.session.add(alert)
    db.session.commit()
    flash(f"Request sent for '{item.description}'. Item moved to 'Needs Info' status.", "success")
    return redirect(url_for('admin_approve'))


@app.route('/admin/item/<int:item_id>/cancel_request', methods=['POST'])
@login_required
def admin_cancel_info_request(item_id):
    """Admin cancels an outstanding info request, returning item to approval queue."""
    if not current_user.is_admin:
        flash("Access denied.", "error")
        return redirect(url_for('index'))
    item = InventoryItem.query.get_or_404(item_id)
    if item.status != 'needs_info':
        flash("Item is not in 'needs info' status.", "error")
        return redirect(url_for('admin_panel'))

    item.status = 'pending_valuation'
    alerts = SellerAlert.query.filter_by(item_id=item.id, resolved=False).all()
    for a in alerts:
        a.resolved = True
        a.resolved_at = datetime.utcnow()
    db.session.commit()
    flash(f"Request cancelled. '{item.description}' returned to approval queue.", "success")
    return redirect(url_for('admin_panel'))


@app.route('/admin/item/<int:item_id>/ai-lookup', methods=['POST'])
@login_required
def admin_trigger_ai_lookup(item_id):
    """Manually re-run AI lookup for an item. Admin only. Returns JSON."""
    if not current_user.is_admin:
        return jsonify({'error': 'Access denied'}), 403
    item = InventoryItem.query.get(item_id)
    if not item:
        return jsonify({'error': 'Item not found'}), 404
    trigger_ai_lookup(item_id)
    return jsonify({'status': 'pending', 'message': 'AI lookup started'})


@app.route('/admin/item/<int:item_id>/ai-result')
@login_required
def admin_get_ai_result(item_id):
    """Return current AI result for an item as JSON. Admin only. Used for polling."""
    if not current_user.is_admin:
        return jsonify({'error': 'Access denied'}), 403
    result = ItemAIResult.query.filter_by(item_id=item_id).first()
    if not result:
        return jsonify({'status': 'none'})
    data = {
        'status': result.status,
        'product_name': result.product_name,
        'retail_price': float(result.retail_price) if result.retail_price else None,
        'retail_price_source': result.retail_price_source,
        'suggested_price': float(result.suggested_price) if result.suggested_price else None,
        'pricing_rationale': result.pricing_rationale,
        'ai_description': result.ai_description,
    }
    return jsonify(data)


@app.route('/item/<int:item_id>/resubmit', methods=['POST'])
@login_required
def resubmit_item(item_id):
    """Seller resubmits item after addressing admin feedback."""
    item = InventoryItem.query.get_or_404(item_id)
    if item.seller_id != current_user.id:
        flash("You cannot modify this item.", "error")
        return redirect(url_for('dashboard'))
    if item.status != 'needs_info':
        flash("This item cannot be resubmitted.", "error")
        return redirect(url_for('dashboard'))

    item.status = 'pending_valuation'
    alerts = SellerAlert.query.filter_by(item_id=item.id, resolved=False).all()
    for a in alerts:
        a.resolved = True
        a.resolved_at = datetime.utcnow()
    db.session.commit()
    flash("Item resubmitted for review. We'll be in touch soon.", "success")
    return redirect(url_for('dashboard'))


@app.route('/admin/seller/<int:user_id>/panel')
@login_required
def admin_seller_panel(user_id):
    """Returns HTML partial for seller profile slide-out panel."""
    if not current_user.is_admin:
        abort(403)
    user = User.query.get_or_404(user_id)
    items = InventoryItem.query.filter_by(seller_id=user.id).order_by(InventoryItem.date_added.desc()).all()
    unresolved_count = SellerAlert.query.filter_by(user_id=user.id, resolved=False).count()
    # Referral data for panel
    seller_referrals_given = Referral.query.filter_by(referrer_id=user.id).all()
    seller_confirmed_referral_count = sum(1 for r in seller_referrals_given if r.confirmed)
    seller_referred_by = User.query.get(user.referred_by_id) if user.referred_by_id else None
    return render_template('admin_seller_panel.html', seller=user, seller_items=items, unresolved_alert_count=unresolved_count,
                           seller_referrals_given=seller_referrals_given,
                           seller_confirmed_referral_count=seller_confirmed_referral_count,
                           seller_referred_by=seller_referred_by)


@app.route('/admin/seller/<int:user_id>/send_alert', methods=['POST'])
@login_required
def admin_send_seller_alert(user_id):
    """Admin sends an alert/message to a seller from the profile panel."""
    if not current_user.is_admin:
        return jsonify({'success': False, 'message': 'Access denied.'}), 403
    user = User.query.get(user_id)
    if not user:
        return jsonify({'success': False, 'message': 'User not found.'}), 404

    alert_type = request.form.get('alert_type', 'custom')
    preset_reason = request.form.get('preset_reason', '').strip()
    custom_note = request.form.get('custom_note', '').strip()
    item_id = request.form.get('item_id', type=int) or None

    if alert_type == 'preset' and not preset_reason:
        return jsonify({'success': False, 'message': 'Please select a preset reason.'}), 400
    if alert_type == 'custom' and not custom_note:
        return jsonify({'success': False, 'message': 'Please enter a message.'}), 400
    if len(custom_note) > 500:
        return jsonify({'success': False, 'message': 'Custom note must be 500 characters or less.'}), 400

    reasons = json.dumps([preset_reason]) if preset_reason else None
    note = custom_note if custom_note else None

    alert = SellerAlert(
        item_id=item_id,
        user_id=user.id,
        created_by_id=current_user.id,
        alert_type=alert_type,
        reasons=reasons,
        custom_note=note,
        resolved=False
    )
    db.session.add(alert)
    db.session.commit()
    return jsonify({'success': True, 'message': 'Alert sent.'})


@app.route('/admin/pickup-nudge/send', methods=['POST'])
@login_required
def admin_send_pickup_nudge():
    """Send pickup reminder alerts to sellers missing pickup week."""
    if not current_user.is_admin:
        return jsonify({'success': False, 'message': 'Access denied.'}), 403

    user_ids_raw = request.form.getlist('user_ids')
    send_all = not user_ids_raw or 'all' in user_ids_raw

    if send_all:
        # Re-query eligible sellers at send time
        free_confirmed_str = AppSetting.get('free_confirmed_user_ids') or ''
        free_confirmed_ids = set(int(x) for x in free_confirmed_str.split(',') if x.strip().isdigit())
        free_rejected_str = AppSetting.get('free_rejected_user_ids') or ''
        free_rejected_ids = set(int(x) for x in free_rejected_str.split(',') if x.strip().isdigit())

        candidates = User.query.filter(
            User.is_seller == True,
            User.items.any(InventoryItem.status.in_(['approved', 'available']))
        ).all()
        target_users = []
        for u in candidates:
            if any(i.pickup_week for i in u.items):
                continue
            if u.id in free_rejected_ids:
                continue
            free_items = [i for i in u.items if i.collection_method == 'free']
            if free_items and u.id not in free_confirmed_ids:
                continue
            target_users.append(u)
    else:
        target_ids = [int(x) for x in user_ids_raw if x.isdigit()]
        target_users = User.query.filter(User.id.in_(target_ids)).all() if target_ids else []

    sent_count = 0
    for u in target_users:
        # Deduplication: skip if unresolved pickup_reminder already exists
        existing = SellerAlert.query.filter_by(
            user_id=u.id, alert_type='pickup_reminder', resolved=False
        ).first()
        if existing:
            continue
        alert = SellerAlert(
            user_id=u.id,
            created_by_id=current_user.id,
            alert_type='pickup_reminder',
            reasons=json.dumps(['Please select your pickup week']),
            resolved=False
        )
        db.session.add(alert)
        sent_count += 1
    db.session.commit()
    return jsonify({'success': True, 'message': f"Reminder sent to {sent_count} seller{'s' if sent_count != 1 else ''}.", 'reload': True})


def _run_approval_digest():
    """Core digest logic. Returns (success: bool, message: str)."""
    now = datetime.utcnow()

    # Query all items currently pending approval
    new_items = InventoryItem.query.filter(
        InventoryItem.status == 'pending_valuation'
    ).all()

    if not new_items:
        return True, "No items pending approval."

    # Build category breakdown
    cat_counts = {}
    for item in new_items:
        cat_name = item.category.name if item.category else 'Uncategorized'
        cat_counts[cat_name] = cat_counts.get(cat_name, 0) + 1
    # Sort by count desc, cap at 8
    sorted_cats = sorted(cat_counts.items(), key=lambda x: -x[1])
    overflow = len(sorted_cats) - 8
    display_cats = sorted_cats[:8]

    breakdown_html = ''.join(
        f'<li style="margin-bottom: 4px;">{count} &times; {name}</li>'
        for name, count in display_cats
    )
    if overflow > 0:
        breakdown_html += f'<li style="margin-bottom: 4px; color: #64748b;">+ {overflow} more</li>'

    count = len(new_items)
    approve_url = os.environ.get('BASE_URL', 'https://usecampusswap.com').rstrip('/') + '/admin/approve'

    email_body = f'''
    <div style="font-family: sans-serif; padding: 20px; max-width: 500px;">
        <h2 style="color: #1a3d1a; margin-bottom: 8px;">Items Pending Approval</h2>
        <p style="font-size: 1rem; color: #333;">You have <strong>{count}</strong> item{"s" if count != 1 else ""} waiting for review in the approval queue.</p>
        <ul style="list-style: none; padding: 0; margin: 16px 0;">{breakdown_html}</ul>
        <div style="margin: 24px 0;">
            <a href="{approve_url}" style="background: #d97706; color: white; padding: 14px 28px; text-decoration: none; border-radius: 8px; font-weight: 600; font-size: 1rem; display: inline-block;">Review Items &rarr;</a>
        </div>
        <p style="font-size: 0.85rem; color: #64748b; margin-top: 20px;">You're receiving this because you're an admin at Campus Swap.</p>
    </div>
    '''
    subject = f"{count} item{'s' if count != 1 else ''} waiting for approval — Campus Swap"

    # Send to all admins who haven't unsubscribed
    admins = User.query.filter(
        (User.is_admin == True) | (User.is_super_admin == True),
        User.unsubscribed == False
    ).all()

    if not admins:
        logger.warning("Digest: no eligible admin recipients found.")
        return True, "No admin recipients."

    sent = 0
    for admin in admins:
        try:
            send_email(admin.email, subject, email_body)
            sent += 1
        except Exception as e:
            logger.error(f"Digest email failed for {admin.email}: {e}")

    # Log the digest
    log = DigestLog(sent_at=now, item_count=count, recipient_count=sent)
    db.session.add(log)
    db.session.commit()

    msg = f"Digest sent: {count} items to {sent} admin(s)."
    logger.info(msg)
    return True, msg


@app.route('/admin/digest/trigger', methods=['POST'])
@csrf.exempt  # Cron job sends raw POST; authenticated via DIGEST_CRON_SECRET header
def digest_trigger():
    """Endpoint for Render Cron Job. Authenticated via DIGEST_CRON_SECRET."""
    secret = os.environ.get('DIGEST_CRON_SECRET', '')
    provided = request.headers.get('X-Cron-Secret') or request.args.get('secret', '')
    if not secret or provided != secret:
        return jsonify({'success': False, 'message': 'Unauthorized.'}), 403
    try:
        success, msg = _run_approval_digest()
        return jsonify({'success': success, 'message': msg})
    except Exception as e:
        logger.error(f"Digest trigger error: {e}", exc_info=True)
        posthog.capture('backend_error', properties={'error': str(e), 'source': 'digest_trigger'})
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/admin/digest/send', methods=['POST'])
@login_required
def send_approval_digest():
    """Super admin manual trigger for testing the digest."""
    if (r := require_super_admin()):
        return r
    try:
        success, msg = _run_approval_digest()
        flash(msg, 'success' if success else 'error')
    except Exception as e:
        logger.error(f"Manual digest error: {e}", exc_info=True)
        flash(f"Digest error: {e}", 'error')
    return redirect(url_for('admin_panel'))


@app.route('/admin/free/confirm/<int:user_id>', methods=['POST'])
@login_required
def admin_free_confirm(user_id):
    """Admin confirms a free-tier user for warehouse pickup."""
    if not current_user.is_admin:
        flash("Access denied.", "error")
        return redirect(url_for('index'))
    user = User.query.get_or_404(user_id)
    
    # Add to confirmed list, remove from rejected list
    confirmed_str = AppSetting.get('free_confirmed_user_ids') or ''
    confirmed_ids = [x.strip() for x in confirmed_str.split(',') if x.strip()]
    if str(user_id) not in confirmed_ids:
        confirmed_ids.append(str(user_id))
    AppSetting.set('free_confirmed_user_ids', ','.join(confirmed_ids))
    
    rejected_str = AppSetting.get('free_rejected_user_ids') or ''
    rejected_ids = [x.strip() for x in rejected_str.split(',') if x.strip() and x.strip() != str(user_id)]
    AppSetting.set('free_rejected_user_ids', ','.join(rejected_ids))
    
    db.session.commit()
    
    # Send confirmation email
    if user.email:
        try:
            name = user.first_name or user.full_name
            dashboard_url = url_for('confirm_pickup', _external=True)
            email_content = f"""
            <div style="font-family: sans-serif; padding: 20px; max-width: 500px;">
                <h2 style="color: #166534;">Great News &mdash; You're Confirmed for Pickup!</h2>
                <p>Hi {name},</p>
                <p>We have warehouse space available and your items are confirmed for pickup. Please visit your dashboard to add your pickup address and select a pickup window.</p>
                <div style="background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 8px; padding: 16px; margin: 20px 0;">
                    <p style="margin: 0;"><strong>Next step:</strong> Add your address and choose a pickup week in your dashboard.</p>
                </div>
                <p><a href="{dashboard_url}" style="background: #166534; color: white; padding: 12px 24px; text-decoration: none; border-radius: 8px;">Confirm Pickup Details</a></p>
                <p>Thanks for selling with Campus Swap!</p>
            </div>
            """
            send_email(user.email, "You're Confirmed for Pickup — Campus Swap", email_content)
        except Exception as e:
            logger.error(f"Failed to send free confirm email: {e}")
    
    flash(f"Confirmed {user.full_name} for free-tier pickup and sent email.", "success")
    return redirect(url_for('admin_panel') + '#free-tier')


@app.route('/admin/free/reject/<int:user_id>', methods=['POST'])
@login_required
def admin_free_reject(user_id):
    """Admin rejects a free-tier user (no space available)."""
    if not current_user.is_admin:
        flash("Access denied.", "error")
        return redirect(url_for('index'))
    user = User.query.get_or_404(user_id)
    
    # Add to rejected list, remove from confirmed list
    rejected_str = AppSetting.get('free_rejected_user_ids') or ''
    rejected_ids = [x.strip() for x in rejected_str.split(',') if x.strip()]
    if str(user_id) not in rejected_ids:
        rejected_ids.append(str(user_id))
    AppSetting.set('free_rejected_user_ids', ','.join(rejected_ids))
    
    confirmed_str = AppSetting.get('free_confirmed_user_ids') or ''
    confirmed_ids = [x.strip() for x in confirmed_str.split(',') if x.strip() and x.strip() != str(user_id)]
    AppSetting.set('free_confirmed_user_ids', ','.join(confirmed_ids))
    
    db.session.commit()
    
    # Send rejection email
    if user.email:
        try:
            name = user.first_name or user.full_name
            dashboard_url = url_for('dashboard', _external=True)
            email_content = f"""
            <div style="font-family: sans-serif; padding: 20px; max-width: 500px;">
                <h2 style="color: #92400e;">Update on Your Free Plan Items</h2>
                <p>Hi {name},</p>
                <p>Unfortunately, our pickup slots are now full and we're unable to pick up your free-plan items this semester. We're sorry for any inconvenience.</p>
                <div style="background: #fffbeb; border: 1px solid #fde68a; border-radius: 8px; padding: 16px; margin: 20px 0;">
                    <p style="margin: 0 0 8px;"><strong>Your options:</strong></p>
                    <ul style="margin: 0; padding-left: 20px;">
                        <li>Upgrade to <strong>Pro User</strong> &mdash; guaranteed pickup for $15 (50% payout)</li>
                    </ul>
                </div>
                <p><a href="{dashboard_url}" style="background: #166534; color: white; padding: 12px 24px; text-decoration: none; border-radius: 8px;">Visit Your Dashboard</a></p>
                <p>Thanks for considering Campus Swap. We hope to serve you!</p>
            </div>
            """
            send_email(user.email, "Update on Your Free Plan Pickup — Campus Swap", email_content)
        except Exception as e:
            logger.error(f"Failed to send free reject email: {e}")

    flash(f"Rejected {user.full_name}'s free-tier pickup and sent email.", "success")
    return redirect(url_for('admin_panel') + '#free-tier')


@app.route('/admin/free/notify_all', methods=['POST'])
@login_required
def admin_free_notify_all():
    """Notify all unconfirmed free-tier users that warehouse is at capacity."""
    if not current_user.is_admin:
        flash("Access denied.", "error")
        return redirect(url_for('index'))
    
    confirmed_str = AppSetting.get('free_confirmed_user_ids') or ''
    confirmed_ids = set(x.strip() for x in confirmed_str.split(',') if x.strip())
    rejected_str = AppSetting.get('free_rejected_user_ids') or ''
    rejected_ids = set(x.strip() for x in rejected_str.split(',') if x.strip())
    
    from sqlalchemy import func as sqlfunc
    free_user_ids = db.session.query(InventoryItem.seller_id).filter(
        InventoryItem.collection_method == 'free',
        InventoryItem.status == 'pending_logistics',
        InventoryItem.seller_id.isnot(None)
    ).distinct().all()
    
    sent = 0
    for (uid,) in free_user_ids:
        if str(uid) in confirmed_ids or str(uid) in rejected_ids:
            continue
        user = User.query.get(uid)
        if not user or not user.email:
            continue
        try:
            name = user.first_name or user.full_name
            dashboard_url = url_for('dashboard', _external=True)
            email_content = f"""
            <div style="font-family: sans-serif; padding: 20px; max-width: 500px;">
                <h2 style="color: #92400e;">Our Warehouse Is at Capacity</h2>
                <p>Hi {name},</p>
                <p>We wanted to reach out before move-out week. Our warehouse is now at capacity, and we are unable to guarantee pickup for free-plan sellers.</p>
                <div style="background: #fffbeb; border: 1px solid #fde68a; border-radius: 8px; padding: 16px; margin: 20px 0;">
                    <p style="margin: 0 0 8px;"><strong>Your options:</strong></p>
                    <ul style="margin: 0; padding-left: 20px;">
                        <li>Upgrade to <strong>Pro User</strong> &mdash; guaranteed pickup for $15 (50% payout)</li>
                    </ul>
                </div>
                <p><a href="{dashboard_url}" style="background: #166534; color: white; padding: 12px 24px; text-decoration: none; border-radius: 8px;">Visit Your Dashboard</a></p>
                <p>Thanks for your understanding, and we hope to serve you!</p>
            </div>
            """
            send_email(user.email, "Our Warehouse Is at Capacity — Campus Swap", email_content)
            sent += 1
        except Exception as e:
            logger.error(f"Failed to send notify-all email to {user.email}: {e}")
    
    flash(f"Notified {sent} unconfirmed free-tier user(s) that warehouse is at capacity.", "success")
    return redirect(url_for('admin_panel') + '#free-tier')


@app.route('/edit_item/<int:item_id>', methods=['GET', 'POST'])
@login_required
def edit_item(item_id):
    item = InventoryItem.query.get_or_404(item_id)
    
    # Security: Only Owner or Admin can edit
    # UPDATED to use is_admin
    if item.seller_id != current_user.id and not current_user.is_admin:
        flash("You cannot edit this item.", "error")
        return redirect(get_user_dashboard())
    
    # Picked-up items: sellers can submit edits for approval (no direct edit). Admins can edit directly.
    # (No redirect here - we allow the form; on POST we set pending_valuation for re-approval)
    
    # Prevent editing sold items (non-admin sellers)
    if item.status == 'sold' and not current_user.is_admin:
        flash("Sold items cannot be edited.", "error")
        return redirect(url_for('dashboard'))
    
    categories = InventoryCategory.query.filter_by(parent_id=None).order_by(InventoryCategory.id).all()

    if request.method == 'POST' and request.form.get('withdraw_item') == '1':
        # Seller withdraws/removes item. Allowed only until item is picked up (in our possession).
        if item_is_picked_up(item):
            flash("This item can no longer be removed. Contact support if needed.", "error")
            return redirect(url_for('edit_item', item_id=item_id))
        if item.status not in ('pending_valuation', 'pending_logistics', 'rejected', 'available'):
            flash("This item can no longer be removed. Contact support if needed.", "error")
            return redirect(url_for('edit_item', item_id=item_id))
        if current_user.is_admin:
            flash("Admins should use the admin panel to delete items.", "error")
            return redirect(url_for('edit_item', item_id=item_id))
        item_desc = item.description
        # Decrement count_in_stock if item was available (was in stock)
        if item.status == 'available' and item.category:
            if (item.category.count_in_stock or 0) > 0:
                item.category.count_in_stock = item.category.count_in_stock - 1
        for photo in item.gallery_photos[:]:
            db.session.delete(photo)
        db.session.delete(item)
        db.session.commit()
        logger.info(f"Item {item.id} withdrawn by seller {current_user.id}")
        flash("Item removed successfully.", "success")
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        # Validate inputs
        description = request.form.get('description', '').strip()
        if not description or len(description) > MAX_DESCRIPTION_LENGTH:
            flash(f"Description is required and must be under {MAX_DESCRIPTION_LENGTH} characters.", "error")
            return render_template('edit_item.html', item=item, categories=categories,
                               item_alert=SellerAlert.query.filter_by(item_id=item.id, resolved=False).order_by(SellerAlert.created_at.desc()).first() if item.status == 'needs_info' else None)
        
        item.description = description
        
        # Price: lock for seller when editing pending_logistics or rejected (admin-set price)
        if item.status in ('pending_logistics', 'rejected') and not current_user.is_admin:
            pass  # Keep existing price; do not apply form value
        else:
            if request.form.get('price'):
                price_valid, price_result = validate_price(request.form['price'])
                if not price_valid:
                    flash(f"Invalid price: {price_result}", "error")
                    return render_template('edit_item.html', item=item, categories=categories,
                               item_alert=SellerAlert.query.filter_by(item_id=item.id, resolved=False).order_by(SellerAlert.created_at.desc()).first() if item.status == 'needs_info' else None)
                if item.price != price_result:
                    item.price = price_result
                    item.price_updated_at = datetime.utcnow()
                    item.price_changed_acknowledged = False
        
        # Validate quality
        quality_valid, quality_value = validate_quality(request.form.get('quality', item.quality))
        if not quality_valid:
            flash(f"Invalid quality: {quality_value}", "error")
            return render_template('edit_item.html', item=item, categories=categories,
                               item_alert=SellerAlert.query.filter_by(item_id=item.id, resolved=False).order_by(SellerAlert.created_at.desc()).first() if item.status == 'needs_info' else None)
        item.quality = quality_value
        
        long_description = request.form.get('long_description', '').strip()
        if long_description and len(long_description) > MAX_LONG_DESCRIPTION_LENGTH:
            flash(f"Long description is too long (max {MAX_LONG_DESCRIPTION_LENGTH} characters).", "error")
            return render_template('edit_item.html', item=item, categories=categories,
                               item_alert=SellerAlert.query.filter_by(item_id=item.id, resolved=False).order_by(SellerAlert.created_at.desc()).first() if item.status == 'needs_info' else None)
        item.long_description = long_description
        
        if request.form.get('category_id'):
            try:
                item.category_id = int(request.form['category_id'])
            except (ValueError, TypeError):
                flash("Invalid category.", "error")
                return render_template('edit_item.html', item=item, categories=categories,
                               item_alert=SellerAlert.query.filter_by(item_id=item.id, resolved=False).order_by(SellerAlert.created_at.desc()).first() if item.status == 'needs_info' else None)

        # Subcategory
        sub_id_raw = request.form.get('subcategory_id', '')
        if sub_id_raw:
            try:
                new_sub_id = int(sub_id_raw)
                sub_cat = InventoryCategory.query.get(new_sub_id)
                if sub_cat and sub_cat.parent_id == item.category_id:
                    item.subcategory_id = new_sub_id
                else:
                    item.subcategory_id = None
            except (ValueError, TypeError):
                item.subcategory_id = None
        else:
            item.subcategory_id = None

        # Handle new photo uploads
        new_photos = request.files.getlist('new_photos')
        if new_photos and new_photos[0].filename != '':
            for i, file in enumerate(new_photos):
                if file.filename:
                    # Validate file upload
                    is_valid, error_msg = validate_file_upload(file)
                    if not is_valid:
                        flash(f"File upload error: {error_msg}", "error")
                        return redirect(url_for('edit_item', item_id=item_id))
                    
                    filename = f"item_{item.id}_{int(time.time())}_{i}.jpg"
                    try:
                        photo_storage.save_photo(file, filename)
                        # If no cover photo exists, set first new photo as cover
                        if not item.photo_url:
                            item.photo_url = filename
                        
                        db.session.add(ItemPhoto(item_id=item.id, photo_url=filename))
                    except Exception as img_error:
                        logger.error(f"Error processing image: {img_error}", exc_info=True)
                        flash("Error processing image. Please try again.", "error")
                        return redirect(url_for('edit_item', item_id=item_id))
        
        # Handle video upload/replace
        new_video = request.files.get('new_video')
        if new_video and new_video.filename and new_video.filename != '':
            is_valid, error_msg = validate_video_upload(new_video)
            if not is_valid:
                flash(f"Video upload error: {error_msg}", "error")
                return redirect(url_for('edit_item', item_id=item_id))
            safe_name = secure_filename(new_video.filename)
            ext = safe_name.rsplit('.', 1)[1].lower() if '.' in safe_name else 'mp4'
            video_key = f"video_{item.id}_{int(time.time())}.{ext}"
            try:
                photo_storage.save_video(new_video, video_key)
                if item.video_url:
                    photo_storage.delete_photo(item.video_url)
                item.video_url = video_key
            except Exception as vid_error:
                logger.error(f"Video save error: {vid_error}", exc_info=True)
                flash("Error saving video. Please try again.", "error")
                return redirect(url_for('edit_item', item_id=item_id))

        # Handle video removal
        if request.form.get('remove_video') == '1' and item.video_url:
            photo_storage.delete_photo(item.video_url)
            item.video_url = None

        # Re-approval: when seller edits pending_logistics, rejected, or picked-up items, send back to approval queue
        # (needs_info items go through the resubmit route instead)
        needs_reapproval = (
            not current_user.is_admin
            and (item.status in ('pending_logistics', 'rejected') or item_is_picked_up(item))
        )
        if needs_reapproval:
            item.status = 'pending_valuation'
        
        db.session.commit()
        logger.info(f"Item {item.id} updated by user {current_user.id}")
        flash("Edits submitted for re-approval." if needs_reapproval else "Item updated successfully!", "success")
        
        if current_user.is_admin:
            # Check if item was pending - if so, redirect to pending section
            if item.status == 'pending_valuation':
                return redirect(url_for('admin_panel') + '#pending-items')
            return redirect(url_for('admin_panel'))
        return redirect(get_user_dashboard())
        
    return render_template('edit_item.html', item=item, categories=categories,
                               item_alert=SellerAlert.query.filter_by(item_id=item.id, resolved=False).order_by(SellerAlert.created_at.desc()).first() if item.status == 'needs_info' else None)


@app.route('/delete_photo/<int:photo_id>')
@login_required
def delete_photo(photo_id):
    photo = ItemPhoto.query.get_or_404(photo_id)
    item = photo.item
    
    # Security check
    if item.seller_id != current_user.id and not current_user.is_admin:
        return redirect(get_user_dashboard())

    try:
        photo_storage.delete_photo(photo.photo_url)
    except Exception as e:
        logger.error(f"Error deleting file: {e}", exc_info=True)

    # If deleting the cover photo, promote another one
    if item.photo_url == photo.photo_url:
        remaining = [p for p in item.gallery_photos if p.id != photo.id]
        item.photo_url = remaining[0].photo_url if remaining else ""

    db.session.delete(photo)
    db.session.commit()
    if current_user.is_admin:
        return redirect(url_for('admin_panel'))
    return redirect(url_for('edit_item', item_id=item.id))


# =========================================================
# SECTION 5: SELLER AUTH & DASHBOARD
# =========================================================

@app.route('/set_password', methods=['POST'])
@login_required
def set_password():
    try:
        password = request.form.get('password')
        if not password:
            flash("Password is required.", "error")
            return redirect(get_user_dashboard())
        
        # Save password to database
        try:
            current_user.password_hash = generate_password_hash(password)
            db.session.commit()
        except Exception as db_error:
            db.session.rollback()
            logger.error(f"Database error in set_password: {db_error}", exc_info=True)
            import traceback
            traceback.print_exc()
            flash("Error saving password. Please try again.", "error")
            return redirect(get_user_dashboard())
        
        # Try to send email (non-critical - don't fail if this breaks)
        try:
            # Build dashboard URL safely
            try:
                dashboard_url = url_for('dashboard', _external=True)
            except Exception as url_error:
                logger.warning(f"Error building dashboard URL: {url_error}")
                # Fallback to relative URL
                dashboard_url = url_for('dashboard')
            
            # No email sent - user already sees confirmation on site
        except Exception as email_error:
            # Email failure is non-critical - log but don't crash
            logger.warning(f"Email sending failed in set_password (non-critical): {email_error}")
            import traceback
            traceback.print_exc()
        
        flash("Account secured! You can now log in anytime.", "success")
        
        # Redirect with fallback
        try:
            return redirect(get_user_dashboard())
        except Exception as redirect_error:
            logger.warning(f"Redirect error in set_password: {redirect_error}")
            # Fallback redirect
            try:
                if current_user.is_admin:
                    return redirect(url_for('admin_panel'))
                return redirect(url_for('dashboard'))
            except:
                return redirect(url_for('index'))
                
    except Exception as e:
        # Catch-all for any unexpected errors
        logger.error(f"Unexpected error in set_password route: {e}", exc_info=True)
        import traceback
        traceback.print_exc()
        flash("An error occurred. Your password may have been saved. Please try logging in.", "error")
        # Try to redirect anyway
        try:
            if current_user.is_authenticated:
                if current_user.is_admin:
                    return redirect(url_for('admin_panel'))
                return redirect(url_for('dashboard'))
        except:
            pass
        return redirect(url_for('index'))

@app.route('/account_settings')
@login_required
def account_settings():
    dorms = RESIDENCE_HALLS_BY_STORE.get(get_current_store(), {})
    return render_template('account_settings.html',
                          dorms=dorms,
                          google_maps_key=os.environ.get('GOOGLE_MAPS_API_KEY', ''))

@app.route('/change_password', methods=['POST'])
@login_required
def change_password():
    current_password = request.form.get('current_password')
    new_password = request.form.get('new_password')
    confirm_password = request.form.get('confirm_password')
    
    # Validate new password matches confirmation
    if new_password != confirm_password:
        flash("New passwords do not match.", "error")
        return redirect(url_for('account_settings'))
    
    if len(new_password) < 6:
        flash("Password must be at least 6 characters long.", "error")
        return redirect(url_for('account_settings'))
    
    # If user has existing password, verify current password
    if current_user.password_hash:
        if not current_password:
            flash("Please enter your current password.", "error")
            return redirect(url_for('account_settings'))
        
        if not check_password_hash(current_user.password_hash, current_password):
            flash("Current password is incorrect.", "error")
            return redirect(url_for('account_settings'))
    
    # Update password
    current_user.password_hash = generate_password_hash(new_password)
    db.session.commit()
    
    flash("Password updated successfully!", "success")
    return redirect(url_for('account_settings'))

@app.route('/update_account_info', methods=['POST'])
@login_required
def update_account_info():
    full_name = request.form.get('full_name', '').strip()
    phone = request.form.get('phone', '').strip()
    
    if not full_name:
        flash("Full name cannot be empty.", "error")
    elif len(full_name) > MAX_NAME_LENGTH:
        flash(f"Name is too long (max {MAX_NAME_LENGTH} characters).", "error")
    elif phone:
        phone_valid, phone_result = validate_phone(phone)
        if not phone_valid:
            flash(phone_result, "error")
        else:
            current_user.full_name = full_name
            current_user.phone = phone_result
            db.session.commit()
            logger.info(f"User {current_user.id} updated account info")
            flash("Account information updated successfully!", "success")
    else:
        current_user.full_name = full_name
        current_user.phone = phone  # Allow clearing phone
        db.session.commit()
        logger.info(f"User {current_user.id} updated account info")
        flash("Account information updated successfully!", "success")

    # Update pickup preferences if provided (only if seller has a pickup week set on their profile)
    time_pref = request.form.get('pickup_time_preference')
    moveout_raw = request.form.get('moveout_date', '').strip()
    if current_user.pickup_week and time_pref is not None:
        if time_pref in PICKUP_TIME_OPTIONS:
            current_user.pickup_time_preference = time_pref
        elif time_pref == '':
            current_user.pickup_time_preference = None
        if moveout_raw:
            try:
                from datetime import date as _date
                current_user.moveout_date = _date.fromisoformat(moveout_raw)
            except ValueError:
                pass
        else:
            current_user.moveout_date = None
        db.session.commit()

    return redirect(url_for('account_settings'))


@app.route('/account/delete', methods=['POST'])
@login_required
def delete_own_account():
    """Permanently delete the current user's own account and all their data."""
    if current_user.is_admin:
        flash("Admin accounts cannot be self-deleted. Contact another admin.", "error")
        return redirect(url_for('account_settings'))

    user = User.query.get(current_user.id)
    user_id = user.id
    user_email = user.email

    try:
        # 1. Delete items and photo files
        for item in list(user.items):
            if item.status == 'available':
                cat = InventoryCategory.query.get(item.category_id)
                if cat and cat.count_in_stock > 0:
                    cat.count_in_stock -= 1
            photo_filenames = []
            if item.photo_url:
                photo_filenames.append(item.photo_url)
            for p in item.gallery_photos:
                if p.photo_url:
                    photo_filenames.append(p.photo_url)
            for fn in photo_filenames:
                try:
                    photo_storage.delete_photo(fn)
                except Exception as e:
                    logger.error(f"Error deleting photo file {fn}: {e}", exc_info=True)
            db.session.delete(item)

        # 2. Delete upload sessions and temp uploads
        sessions = UploadSession.query.filter_by(user_id=user_id).all()
        session_tokens = [s.session_token for s in sessions]
        for token in session_tokens:
            TempUpload.query.filter_by(session_token=token).delete(synchronize_session=False)
        for s in sessions:
            db.session.delete(s)

        # 3. Logout then delete user record
        logout_user()
        db.session.delete(user)
        db.session.commit()

        logger.info(f"User {user_id} ({user_email}) self-deleted their account")
        flash("Your account has been permanently deleted.", "success")
        return redirect(url_for('index'))
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting own account {user_id}: {e}", exc_info=True)
        flash(f"Could not delete account: {str(e)}", "error")
        return redirect(url_for('account_settings'))


@app.route('/complete_profile', methods=['GET', 'POST'])
@login_required
def complete_profile():
    """Collect required phone number after Google OAuth. Idempotent — redirects away if phone already set."""
    if current_user.phone:
        return redirect(session.pop('next_after_profile', url_for('dashboard')))

    if request.method == 'POST':
        phone_raw = request.form.get('phone', '').strip()
        if not phone_raw:
            flash("Please provide a phone number.", "error")
            return redirect(url_for('complete_profile'))
        phone_valid, phone_result = validate_phone(phone_raw)
        if not phone_valid:
            flash(phone_result, "error")
            return redirect(url_for('complete_profile'))
        current_user.phone = phone_result
        db.session.commit()
        next_url = session.pop('next_after_profile', url_for('dashboard'))
        return redirect(next_url)

    return render_template('complete_profile.html')


@app.route('/api/user/set_pickup_week', methods=['POST'])
@login_required
def api_set_pickup_week():
    """AJAX endpoint for dashboard modal to save pickup week + time preference."""
    _json = request.get_json(silent=True) or {}
    pickup_week = (request.form.get('pickup_week') or _json.get('pickup_week') or '').strip()
    pickup_time = (request.form.get('pickup_time_preference') or _json.get('pickup_time_preference') or '').strip()

    valid_weeks = dict(PICKUP_WEEKS)
    if pickup_week:
        if pickup_week not in valid_weeks:
            return jsonify({'success': False, 'error': 'Invalid pickup week.'}), 400
        if pickup_time not in PICKUP_TIME_OPTIONS:
            return jsonify({'success': False, 'error': 'Invalid time preference.'}), 400
        current_user.pickup_week = pickup_week
        current_user.pickup_time_preference = pickup_time
    else:
        current_user.pickup_week = None
        current_user.pickup_time_preference = None

    # Save moveout_date if provided
    moveout_raw = (request.form.get('moveout_date') or _json.get('moveout_date') or '').strip()
    if moveout_raw:
        try:
            from datetime import date as _date
            current_user.moveout_date = _date.fromisoformat(moveout_raw)
        except ValueError:
            pass  # ignore malformed silently
    else:
        current_user.moveout_date = None

    # Save address fields if provided
    loc_type = (request.form.get('pickup_location_type') or _json.get('pickup_location_type') or '').strip()
    if loc_type in ('on_campus', 'off_campus_complex', 'off_campus_other', 'off_campus'):
        current_user.pickup_location_type = 'off_campus_other' if loc_type == 'off_campus' else loc_type
        if loc_type == 'on_campus':
            current_user.pickup_dorm = (request.form.get('pickup_dorm') or _json.get('pickup_dorm') or '').strip() or None
            current_user.pickup_room = (request.form.get('pickup_room') or _json.get('pickup_room') or '').strip() or None
            current_user.pickup_address = None
        elif loc_type == 'off_campus_complex':
            current_user.pickup_dorm = (request.form.get('pickup_dorm') or _json.get('pickup_dorm') or '').strip() or None
            current_user.pickup_room = (request.form.get('pickup_room') or _json.get('pickup_room') or '').strip() or None
            current_user.pickup_address = None
        else:
            current_user.pickup_address = (request.form.get('pickup_address') or _json.get('pickup_address') or '').strip() or None
            current_user.pickup_dorm = None
            current_user.pickup_room = None
        pickup_note = (request.form.get('pickup_note') or _json.get('pickup_note') or '').strip()
        current_user.pickup_note = pickup_note or None
        # Save access fields if provided
        _at = (request.form.get('pickup_access_type') or _json.get('pickup_access_type') or '').strip()
        if _at in ('elevator', 'stairs_only', 'ground_floor'):
            current_user.pickup_access_type = _at
        _fl = request.form.get('pickup_floor') or _json.get('pickup_floor')
        if _fl is not None:
            try:
                _floor_val = int(_fl)
                if 1 <= _floor_val <= 30:
                    current_user.pickup_floor = _floor_val
            except (ValueError, TypeError):
                pass

    db.session.commit()
    logger.info(f"User {current_user.id} set pickup week={current_user.pickup_week} time={current_user.pickup_time_preference} loc={loc_type or 'unchanged'}")
    return jsonify({
        'success': True,
        'pickup_week': current_user.pickup_week,
        'pickup_week_label': valid_weeks.get(current_user.pickup_week, '') if current_user.pickup_week else '',
        'pickup_time_preference': current_user.pickup_time_preference,
    })


def process_pending_onboard(user):
    """Create item from session['pending_onboard'] after guest registers. Returns True if processed."""
    pending = session.pop('pending_onboard', None)
    if not pending:
        return False
    session.pop('guest_upload_token', None)

    category_id = pending.get('category_id')
    desc = pending.get('description', '')
    long_desc = pending.get('long_description')
    quality = pending.get('quality', 4)
    suggested_price = pending.get('suggested_price')
    collection_method = pending.get('collection_method', 'online')
    photo_filenames = pending.get('photo_filenames', [])
    temp_photo_ids = pending.get('temp_photo_ids', [])
    guest_upload_token = pending.get('guest_upload_token')

    if not category_id or not desc:
        return False

    # Apply user profile
    user.pickup_location_type = pending.get('pickup_location_type')
    user.pickup_dorm = pending.get('pickup_dorm')
    user.pickup_room = pending.get('pickup_room')
    user.pickup_address = pending.get('pickup_address')
    user.pickup_lat = pending.get('pickup_lat')
    user.pickup_lng = pending.get('pickup_lng')
    user.pickup_access_type = pending.get('pickup_access_type')
    user.pickup_floor = pending.get('pickup_floor')
    user.pickup_note = pending.get('pickup_note')
    user.phone = pending.get('phone')
    if pending.get('pickup_week'):
        user.pickup_week = pending.get('pickup_week')
    if pending.get('pickup_time_preference'):
        user.pickup_time_preference = pending.get('pickup_time_preference')
    user.payout_method = pending.get('payout_method')
    user.payout_handle = pending.get('payout_handle')
    user.is_seller = True
    # Apply referral code from pending session if not already applied
    if not user.referred_by_id and pending.get('referral_code'):
        apply_referral_code(user, pending.get('referral_code'))
    db.session.commit()

    new_item = InventoryItem(
        seller_id=user.id, category_id=category_id, description=desc[:MAX_DESCRIPTION_LENGTH],
        long_description=long_desc[:MAX_LONG_DESCRIPTION_LENGTH] if long_desc else None,
        quality=quality, status="pending_valuation", photo_url="",
        collection_method=collection_method,
        suggested_price=suggested_price,
        subcategory_id=pending.get('subcategory_id'),
    )
    db.session.add(new_item)
    db.session.flush()

    cover_set = False
    photo_index = 0
    temp_folder = app.config['TEMP_UPLOAD_FOLDER']

    for filename in photo_filenames:
        old_path = os.path.join(temp_folder, filename)
        if os.path.exists(old_path):
            new_filename = f"item_{new_item.id}_{int(time.time())}_{photo_index}.jpg"
            try:
                photo_storage.save_photo_from_path(old_path, new_filename)
                os.remove(old_path)
            except OSError:
                pass
            if not cover_set:
                new_item.photo_url = new_filename
                cover_set = True
            db.session.add(ItemPhoto(item_id=new_item.id, photo_url=new_filename))
            photo_index += 1

    if guest_upload_token and temp_photo_ids:
        for temp_fn in temp_photo_ids:
            temp_rec = TempUpload.query.filter_by(session_token=guest_upload_token, filename=temp_fn).first()
            if temp_rec:
                old_path = os.path.join(temp_folder, temp_fn)
                if os.path.exists(old_path):
                    new_filename = f"item_{new_item.id}_{int(time.time())}_{photo_index}.jpg"
                    try:
                        photo_storage.save_photo_from_path(old_path, new_filename)
                        os.remove(old_path)
                    except OSError:
                        pass
                    if not cover_set:
                        new_item.photo_url = new_filename
                        cover_set = True
                    db.session.add(ItemPhoto(item_id=new_item.id, photo_url=new_filename))
                    db.session.delete(temp_rec)
                    photo_index += 1

    # --- VIDEO HANDLING (guest -> authenticated) ---
    video_filename = pending.get('video_filename')
    temp_video_id = pending.get('temp_video_id')
    if video_filename:
        old_path = os.path.join(temp_folder, video_filename)
        if os.path.exists(old_path):
            ext = video_filename.rsplit('.', 1)[1].lower() if '.' in video_filename else 'mp4'
            video_key = f"video_{new_item.id}_{int(time.time())}.{ext}"
            try:
                photo_storage.save_video_from_path(old_path, video_key)
                new_item.video_url = video_key
                os.remove(old_path)
            except OSError:
                pass
    elif temp_video_id and guest_upload_token:
        temp_rec = TempUpload.query.filter_by(session_token=guest_upload_token, filename=temp_video_id).first()
        if temp_rec:
            old_path = os.path.join(temp_folder, temp_video_id)
            if os.path.exists(old_path):
                ext = temp_video_id.rsplit('.', 1)[1].lower() if '.' in temp_video_id else 'mp4'
                video_key = f"video_{new_item.id}_{int(time.time())}.{ext}"
                try:
                    photo_storage.save_video_from_path(old_path, video_key)
                    new_item.video_url = video_key
                    os.remove(old_path)
                except OSError:
                    pass
            db.session.delete(temp_rec)

    db.session.commit()

    try:
        submission_content = f"""
        <div style="font-family: sans-serif; padding: 20px; max-width: 500px;">
            <h2 style="color: #166534;">Item Submitted for Review</h2>
            <p>Hi {user.full_name or 'there'},</p>
            <p>We've received your item submission: <strong>{desc}</strong></p>
            <p>We'll review and price it soon. You'll get an email when it's approved—then you'll confirm your pickup week.</p>
            <p><a href="{url_for('dashboard', _external=True)}" style="background: #166534; color: white; padding: 12px 24px; text-decoration: none; border-radius: 8px;">View Dashboard</a></p>
            <p>Thanks for selling with Campus Swap!</p>
        </div>
        """
        send_email(user.email, "Item Submitted - Campus Swap", submission_content)
    except Exception as email_error:
        logger.error(f"Onboard email error: {email_error}")

    return True


@app.route('/admin/settings/referral', methods=['POST'])
@login_required
def admin_settings_referral():
    """Update referral program AppSettings. Super admin only."""
    if not current_user.is_super_admin:
        abort(403)
    for key in ('referral_base_rate', 'referral_signup_bonus', 'referral_bonus_per_referral',
                'referral_max_rate'):
        val = request.form.get(key, '').strip()
        if val.isdigit():
            AppSetting.set(key, val)
    active_val = 'true' if request.form.get('referral_program_active') == 'true' else 'false'
    AppSetting.set('referral_program_active', active_val)
    flash("Referral program settings saved.", "success")
    return redirect(url_for('admin_panel') + '#referral-settings')


@app.route('/register', methods=['GET', 'POST'])
@limiter.limit("3 per hour") if limiter else lambda f: f
def register():
    if current_user.is_authenticated:
        return redirect(get_user_dashboard())

    from_onboard = request.args.get('from_onboard') or request.form.get('from_onboard')

    def _error_redirect():
        if from_onboard:
            return redirect(url_for('onboard_complete_account'))
        return redirect(url_for('login', signup='true', email=request.form.get('email', ''), full_name=request.form.get('full_name', '')))

    if request.method == 'POST':
        _ref_from_session = session.pop('referral_code', None)
        if not verify_turnstile(request.form.get('cf-turnstile-response', '')):
            flash("Verification failed. Please try again.", "error")
            return _error_redirect()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        full_name = request.form.get('full_name', '').strip()
        phone_raw = request.form.get('phone', '').strip()

        # Validate inputs
        if not email or not validate_email(email):
            flash("Please provide a valid email address.", "error")
            return _error_redirect()

        if len(email) > MAX_EMAIL_LENGTH:
            flash(f"Email address is too long (max {MAX_EMAIL_LENGTH} characters).", "error")
            return _error_redirect()

        if not password or len(password) < 6:
            flash("Password must be at least 6 characters long.", "error")
            return _error_redirect()

        if full_name and len(full_name) > MAX_NAME_LENGTH:
            flash(f"Name is too long (max {MAX_NAME_LENGTH} characters).", "error")
            return _error_redirect()

        phone_result = None
        if phone_raw:
            phone_valid, phone_result = validate_phone(phone_raw)
            if not phone_valid:
                flash(phone_result, "error")
                return _error_redirect()
        
        user = User.query.filter_by(email=email).first()
        
        if user:
            # User exists - check if they have a password
            if user.password_hash is None:
                # Guest account - set password to complete account creation
                user.password_hash = generate_password_hash(password)
                user.is_seller = True
                if full_name:
                    user.full_name = full_name
                if phone_result:
                    user.phone = phone_result
                if not user.referral_code:
                    user.referral_code = generate_unique_referral_code()
                if not user.referred_by_id:
                    referral_code_input = request.form.get('referral_code', '').strip()
                    apply_referral_code(user, referral_code_input or _ref_from_session)
                db.session.commit()
                apply_admin_email_if_pending(user)
                db.session.refresh(user)
                login_user(user)
                logger.info(f"Guest account converted to full account: {email}")
                
                # Send welcome email
                try:
                    welcome_content = f"""
                    <div style="font-family: sans-serif; padding: 20px; max-width: 500px;">
                        <h2 style="color: #166534;">Welcome to Campus Swap!</h2>
                        <p>Hi {full_name or 'there'},</p>
                        <p>Thanks for creating your account! You're all set to start selling.</p>
                        <p><a href="{url_for('dashboard', _external=True)}" style="background: #166534; color: white; padding: 12px 24px; text-decoration: none; border-radius: 8px; display: inline-block;">Go to Dashboard</a></p>
                        <p>Happy swapping!</p>
                    </div>
                    """
                    send_email(
                        email,
                        "Welcome to Campus Swap!",
                        welcome_content
                    )
                except Exception as email_error:
                    logger.warning(f"Failed to send welcome email: {email_error}")
                
                if process_pending_onboard(user):
                    flash("Item submitted! We'll review and price it soon. You'll confirm your pickup after approval. Check your spam folder if you don't receive our emails.", "success")
                else:
                    flash("Account created! Complete your profile and activate as a seller to start listing items. Check your spam folder if you don't see our welcome email.", "success")
                return redirect(get_user_dashboard())
            else:
                # Account already exists with password - redirect to login with message
                flash("An account with this email already exists. Please log in.", "error")
                return redirect(url_for('login', email=email))
        
        referral_code_input = request.form.get('referral_code', '').strip()
        new_user = User(email=email, full_name=full_name, password_hash=generate_password_hash(password), phone=phone_result, is_seller=True)
        db.session.add(new_user)
        db.session.flush()  # get new_user.id
        new_user.referral_code = generate_unique_referral_code()
        apply_referral_code(new_user, referral_code_input or _ref_from_session)
        db.session.commit()
        # PostHog: new user registration
        posthog.capture('seller_signed_up', distinct_id=str(new_user.id))
        apply_admin_email_if_pending(new_user)
        db.session.refresh(new_user)
        login_user(new_user)
        logger.info(f"New user registered: {email}")
        
        # Send welcome email
        try:
            welcome_content = f"""
            <div style="font-family: sans-serif; padding: 20px; max-width: 500px;">
                <h2 style="color: #166534;">Welcome to Campus Swap!</h2>
                <p>Hi {full_name or 'there'},</p>
                <p>Thanks for joining Campus Swap! Your account has been created successfully.</p>
                <p>You can now:</p>
                <ul>
                    <li>Browse our inventory</li>
                    <li>List items to sell</li>
                    <li>Track your sales and payouts</li>
                </ul>
                <p><a href="{url_for('dashboard', _external=True)}" style="background: #166534; color: white; padding: 12px 24px; text-decoration: none; border-radius: 8px; display: inline-block;">Go to Dashboard</a></p>
                <p>Happy swapping!</p>
                <p>The Campus Swap Team</p>
            </div>
            """
            send_email(
                email,
                "Welcome to Campus Swap!",
                welcome_content
            )
        except Exception as email_error:
            logger.warning(f"Failed to send welcome email: {email_error}")
            # Don't fail registration if email fails
        
        if process_pending_onboard(new_user):
            flash("Item submitted! We'll review and price it soon. You'll confirm your pickup after approval. Check your spam folder if you don't receive our emails.", "success")
        else:
            flash("Account created! Complete your profile and activate as a seller to start listing items. Check your spam folder if you don't see our welcome email.", "success")
        return redirect(get_user_dashboard())

    ref_code = request.args.get('ref', '').strip()
    if ref_code and not session.get('referral_code'):
        session['referral_code'] = ref_code
    return render_template('register.html',
                           prefill_referral_code=request.args.get('ref', '') or session.get('referral_code', ''))


@app.route('/referral/validate')
def referral_validate():
    """AJAX endpoint: validate a referral code. Returns JSON {valid: bool, referrer_name: str}."""
    code = request.args.get('code', '').strip().upper()
    if not code:
        return jsonify({'valid': False})
    if AppSetting.get('referral_program_active', 'true') != 'true':
        return jsonify({'valid': False})
    referrer = User.query.filter_by(referral_code=code).first()
    if not referrer:
        return jsonify({'valid': False})
    name = referrer.full_name or ''
    parts = name.split()
    display = f"{parts[0]} {parts[-1][0]}." if len(parts) >= 2 else (parts[0] if parts else 'Someone')
    return jsonify({'valid': True, 'referrer_name': display})


@app.route('/health')
def health_check():
    """Health check endpoint for monitoring and load balancers"""
    try:
        # Check database connectivity
        db.session.execute(db.text('SELECT 1'))
        
        # Check external services (basic checks)
        health_status = {
            'status': 'healthy',
            'database': 'connected',
            'timestamp': datetime.utcnow().isoformat()
        }
        
        # Optionally check Stripe and Resend (but don't fail if they're not critical)
        if stripe.api_key:
            health_status['stripe'] = 'configured'
        if resend.api_key:
            health_status['resend'] = 'configured'
        
        return jsonify(health_status), 200
    except Exception as e:
        logger.error(f"Health check failed: {e}", exc_info=True)
        return jsonify({
            'status': 'unhealthy',
            'error': str(e),
            'timestamp': datetime.utcnow().isoformat()
        }), 503


# --- GOOGLE OAUTH ROUTES ---

@app.route('/auth/google')
def auth_google():
    """Initiate Google OAuth flow. Save referral code to session before redirect."""
    if not oauth:
        flash("Sign in with Google is not configured. Please use email to create an account.", "error")
        return redirect(url_for('register'))
    # Preserve ?ref= param across OAuth redirect
    ref = request.args.get('ref', '').strip()
    if ref:
        session['referral_code'] = ref
    redirect_uri = url_for('auth_google_callback', _external=True)
    return oauth.google.authorize_redirect(redirect_uri)


@app.route('/auth/google/callback')
def auth_google_callback():
    """Handle Google OAuth callback - create or log in user."""
    if not oauth:
        flash("Sign in with Google is not configured.", "error")
        return redirect(url_for('login'))
    try:
        token = oauth.google.authorize_access_token()
    except Exception as e:
        logger.warning(f"Google OAuth error: {e}", exc_info=True)
        flash("Sign in with Google failed. Please try again or use email.", "error")
        return redirect(url_for('login'))
    userinfo = token.get('userinfo')
    if not userinfo:
        flash("Could not get your Google profile. Please try again.", "error")
        return redirect(url_for('login'))
    email = (userinfo.get('email') or '').strip()
    name = (userinfo.get('name') or '').strip()
    oauth_id = userinfo.get('sub')
    if not email:
        flash("Google did not provide an email. Please use email signup instead.", "error")
        return redirect(url_for('register'))
    if len(email) > MAX_EMAIL_LENGTH:
        flash("Your email address is too long.", "error")
        return redirect(url_for('register'))
    if name and len(name) > MAX_NAME_LENGTH:
        name = name[:MAX_NAME_LENGTH]
    source = session.get('source', 'direct')
    pickup_period_active = get_pickup_period_active()
    user = User.query.filter_by(email=email).first()
    if user:
        if not user.oauth_provider or not user.oauth_id:
            user.oauth_provider = 'google'
            user.oauth_id = oauth_id
            if name and not user.full_name:
                user.full_name = name
            db.session.commit()
        apply_admin_email_if_pending(user)
        db.session.refresh(user)
        login_user(user, remember=True)
        if not pickup_period_active:
            flash("Pickup period has ended for this year. We've saved your email and will notify you when signups open next year! Check your spam folder when we send the notification.", "info")
            return redirect(url_for('index'))
        if process_pending_onboard(user):
            flash("Item submitted! We'll review and price it soon. You'll confirm your pickup after approval. Check your spam folder if you don't receive our emails.", "success")
        else:
            flash("Welcome back!", "success")
        return redirect(get_user_dashboard())
    if not pickup_period_active:
        new_user = User(email=email, full_name=name or None, referral_source=source,
                        oauth_provider='google', oauth_id=oauth_id)
        db.session.add(new_user)
        db.session.flush()
        new_user.referral_code = generate_unique_referral_code()
        apply_referral_code(new_user, session.pop('referral_code', None))
        db.session.commit()
        apply_admin_email_if_pending(new_user)
        db.session.refresh(new_user)
        login_user(new_user, remember=True)
        flash("Pickup period has ended for this year. We've saved your email and will notify you when signups open next year! Check your spam folder when we send the notification.", "info")
        return redirect(url_for('index'))
    new_user = User(email=email, full_name=name or None, referral_source=source,
                    oauth_provider='google', oauth_id=oauth_id)
    db.session.add(new_user)
    db.session.flush()
    new_user.referral_code = generate_unique_referral_code()
    apply_referral_code(new_user, session.pop('referral_code', None))
    db.session.commit()
    apply_admin_email_if_pending(new_user)
    db.session.refresh(new_user)
    login_user(new_user, remember=True)
    if process_pending_onboard(new_user):
        flash("Item submitted! We'll review and price it soon. You'll confirm your pickup after approval. Check your spam folder if you don't receive our emails.", "success")
    else:
        flash("Account created! Complete your profile and activate as a seller to start listing items.", "success")
    # New Google OAuth accounts: collect phone before sending to destination
    session['next_after_profile'] = get_user_dashboard()
    return redirect(url_for('complete_profile'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated and request.method == 'GET':
        return redirect(get_user_dashboard())
    
    # Pre-fill form data if passed as query param (from account creation redirect)
    prefill_email = request.args.get('email', '')
    prefill_full_name = request.args.get('full_name', '')
        
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        form_type = request.form.get('form_type', 'login')
        
        # Validate email
        if not email or not validate_email(email):
            flash("Please provide a valid email address.", "error")
            return render_template('login.html', prefill_email=email, prefill_full_name=request.form.get('full_name', ''), show_signup=(form_type != 'login'))
        
        # If it's a login attempt
        if form_type == 'login':
            if not password:
                flash("Please enter your password.", "error")
                return render_template('login.html', prefill_email=email, prefill_full_name='', show_signup=False)
            
            user = User.query.filter_by(email=email).first()
            
            if not user:
                # User doesn't exist - suggest creating account
                flash("No account found with this email. Create an account below.", "error")
                return render_template('login.html', prefill_email=email, prefill_full_name='', show_signup=True)
            elif not user.password_hash:
                if user.oauth_provider:
                    # OAuth-only account - tell them to use Google
                    flash("This account uses Sign in with Google. Use the button above to log in.", "error")
                    return render_template('login.html', prefill_email=email, prefill_full_name='', show_signup=False)
                else:
                    # True guest - redirect to signup
                    flash("Please create an account with this email.", "error")
                    return render_template('login.html', prefill_email=email, prefill_full_name='', show_signup=True)
            elif not check_password_hash(user.password_hash, password):
                # Wrong password
                flash("Invalid password. Please try again.", "error")
                return render_template('login.html', prefill_email=email, prefill_full_name='', show_signup=False)
            else:
                # Successful login
                login_user(user)
                if process_pending_onboard(user):
                    flash("Item submitted! We'll review and price it soon. You'll confirm your pickup after approval. Check your spam folder if you don't receive our emails.", "success")
                next_url = request.args.get('next') or request.form.get('next', '')
                if next_url and next_url.startswith('/') and not next_url.startswith('//'):
                    return redirect(next_url)
                return redirect(get_user_dashboard())
        else:
            # This shouldn't happen as signup form posts to /register
            flash("Please use the Create Account form.", "error")
    
    # Save ?ref= to session for OAuth and Google login flows
    ref = request.args.get('ref', '').strip()
    if ref and not session.get('referral_code'):
        session['referral_code'] = ref

    show_signup = request.args.get('signup') == 'true' or request.args.get('show_signup') == 'true'
    return render_template('login.html', prefill_email=prefill_email, prefill_full_name=prefill_full_name, show_signup=show_signup)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    """Seller dashboard with optimized queries"""
    # Admins should use admin panel, not seller dashboard
    if current_user.is_admin:
        return redirect(url_for('admin_panel'))

    # First-time sellers (0 items) go straight to onboarding - never see setup cards
    # Returning sellers who removed all items see empty dashboard instead of onboard
    my_items_pre = InventoryItem.query.filter_by(seller_id=current_user.id).all()
    if len(my_items_pre) == 0:
        if not current_user.is_seller:
            return redirect(url_for('onboard'))

    # Refresh user object to ensure we have latest data (especially has_paid status)
    db.session.expire(current_user)
    db.session.refresh(current_user)
    
    # Optimize query with eager loading
    my_items = InventoryItem.query.options(
        joinedload(InventoryItem.category)
    ).filter_by(seller_id=current_user.id).all()
    
    # Check if user has any online items (which require payment)
    has_online_items = any(item.collection_method == 'online' for item in my_items)
    has_approved_free_items = any(
        item.collection_method == 'free' and item.status != 'pending_valuation'
        for item in my_items
    )
    
    # Calculate payout statistics (per-item percentage: online 50%, in-person 33%)
    available_items = [item for item in my_items if item.status == 'available']
    sold_items = [item for item in my_items if item.status == 'sold']

    # Items visible in inventory (matches inventory route: approved items show on shop)
    live_items = available_items

    # Earnings subtext: shows highest applicable payout rate
    has_any_free = any(i.collection_method == 'free' for i in available_items)
    earnings_subtext = f"Based on your {current_user.payout_rate}% payout rate"
    
    def _payout_for_item(it):
        pct = _get_payout_percentage(it)
        return (it.price or 0) * pct
    
    estimated_payout = sum(_payout_for_item(i) for i in live_items)
    paid_out = sum(_payout_for_item(i) for i in sold_items if i.payout_sent)
    pending_payouts = sum(_payout_for_item(i) for i in sold_items if not i.payout_sent)
    total_potential = estimated_payout + pending_payouts + paid_out
    
    approved_online = [i for i in live_items if i.collection_method == 'online']
    projected_fee_cents = SERVICE_FEE_CENTS if approved_online else 0

    # Pending pickup: items awaiting confirmation
    pending_pickup = [i for i in my_items if i.status == 'pending_logistics' and i.collection_method == 'online']
    pending_free = [i for i in my_items if i.status == 'pending_logistics' and i.collection_method == 'free']
    pending_pickup_fee_cents = SERVICE_FEE_CENTS if pending_pickup else 0

    # Free tier flags
    has_free_items = any(i.collection_method == 'free' for i in my_items if i.status != 'rejected')
    free_confirmed_ids_str = AppSetting.get('free_confirmed_user_ids') or ''
    free_rejected_ids_str = AppSetting.get('free_rejected_user_ids') or ''
    is_free_confirmed = str(current_user.id) in [x.strip() for x in free_confirmed_ids_str.split(',') if x.strip()]
    is_free_rejected = str(current_user.id) in [x.strip() for x in free_rejected_ids_str.split(',') if x.strip()]

    stripe_pk = os.environ.get('STRIPE_PUBLISHABLE_KEY', '')
    stripe_configured = bool(stripe.api_key and stripe_pk)

    # Pickup method for header card — uses User.pickup_week (seller's stated preference)
    pickup_method_type = None
    pickup_method_label = None
    time_labels = {'am': 'AM', 'pm': 'PM'}
    if current_user.pickup_week:
        pickup_method_type = 'week'
        week_label = dict(PICKUP_WEEKS).get(current_user.pickup_week, current_user.pickup_week)
        week_short_map = {'week1': 'Wk 1', 'week2': 'Wk 2', 'week3': 'Wk 3'}
        week_short = week_short_map.get(current_user.pickup_week, current_user.pickup_week)
        if current_user.pickup_time_preference:
            pickup_method_label = f"{week_short} · {time_labels.get(current_user.pickup_time_preference, '')}"
        else:
            pickup_method_label = f"{week_short} — time TBD"
    elif pending_pickup:
        pickup_method_type = 'needs_pickup'
    elif has_free_items:
        if is_free_rejected:
            pickup_method_type = 'free_rejected'
        elif is_free_confirmed:
            pickup_method_type = 'free_confirmed'
        else:
            pickup_method_type = 'free_waiting'

    # Unresolved seller alerts (for "Action Needed" banners)
    unresolved_alerts = SellerAlert.query.filter_by(
        user_id=current_user.id, resolved=False
    ).order_by(SellerAlert.created_at.desc()).all()

    # Determine user's overall collection_method for upgrade card
    user_any_item = my_items[0] if my_items else None
    user_collection_method = current_user.items[0].collection_method if current_user.items else 'free'
    # If any item is 'online', consider user on Pro plan
    if any(i.collection_method == 'online' for i in my_items):
        user_collection_method = 'online'

    # Referral program data for dashboard widget
    referrals_given = Referral.query.filter_by(referrer_id=current_user.id).all()
    confirmed_referral_count = sum(1 for r in referrals_given if r.confirmed)
    referral_base = int(AppSetting.get('referral_base_rate', '20'))
    referral_max = int(AppSetting.get('referral_max_rate', '100'))
    referral_steps = list(range(referral_base, referral_max + 1, 10))
    app_base_url = os.environ.get('APP_BASE_URL', request.url_root.rstrip('/'))

    # Setup strip vs. tracker
    setup_complete = bool(
        current_user.phone and
        current_user.pickup_week and
        current_user.has_pickup_location and
        current_user.payout_method and
        current_user.payout_handle
    )
    tracker = _compute_seller_tracker(current_user, my_items) if setup_complete else None

    # ShiftPickup for the current user (if assigned)
    shift_pickup = ShiftPickup.query.filter_by(seller_id=current_user.id).first()
    # Compute actual shift date as soon as a ShiftPickup exists (not just after notification)
    assigned_shift_date_str = None
    if shift_pickup and shift_pickup.shift and shift_pickup.shift.week:
        _day_order = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
        _sp = shift_pickup.shift
        _sd = _sp.week.week_start + timedelta(days=_day_order.index(_sp.day_of_week))
        assigned_shift_date_str = _sd.strftime('%a, %b %-d')

    return render_template('dashboard.html',
                          my_items=my_items,
                          unresolved_alerts=unresolved_alerts,
                          has_online_items=has_online_items,
                          has_approved_free_items=has_approved_free_items,
                          estimated_payout=estimated_payout,
                          paid_out=paid_out,
                          pending_payouts=pending_payouts,
                          total_potential=total_potential,
                          sold_items=sold_items,
                          live_items=live_items,
                          live_item_ids={i.id for i in live_items},
                          earnings_subtext=earnings_subtext,
                          approved_online_count=len(approved_online),
                          projected_fee_cents=projected_fee_cents,
                          pending_pickup=pending_pickup,
                          pending_pickup_fee_cents=pending_pickup_fee_cents,
                          pickup_weeks=PICKUP_WEEKS,
                          service_fee_cents=SERVICE_FEE_CENTS,
                          has_payment_method=bool(current_user.stripe_payment_method_id),
                          stripe_configured=stripe_configured,
                          dorms=RESIDENCE_HALLS_BY_STORE.get(get_current_store(), {}),
                          google_maps_key=os.environ.get('GOOGLE_MAPS_API_KEY', ''),
                          has_pickup_location=current_user.has_pickup_location,
                          has_payout_info=bool(current_user.payout_handle),
                          pickup_method_type=pickup_method_type,
                          pickup_method_label=pickup_method_label,
                          warehouse_spots=get_warehouse_spots_remaining(),
                          is_free_confirmed=is_free_confirmed,
                          is_free_rejected=is_free_rejected,
                          pending_free=pending_free,
                          user_collection_method=user_collection_method,
                          user_pickup_week=current_user.pickup_week,
                          user_pickup_time_pref=current_user.pickup_time_preference,
                          referrals_given=referrals_given,
                          confirmed_referral_count=confirmed_referral_count,
                          referral_steps=referral_steps,
                          referral_max=referral_max,
                          app_base_url=app_base_url,
                          setup_complete=setup_complete,
                          tracker=tracker,
                          shift_pickup=shift_pickup,
                          assigned_shift_date_str=assigned_shift_date_str)

def _validate_access_fields(form):
    """Validate pickup_access_type and pickup_floor from a form/dict. Returns (access_type, floor) or (None, None) on failure."""
    VALID_ACCESS_TYPES = {'elevator', 'stairs_only', 'ground_floor'}
    access_type = (form.get('pickup_access_type') or '').strip()
    floor_raw = (form.get('pickup_floor') or '').strip() if isinstance(form.get('pickup_floor'), str) else str(form.get('pickup_floor') or '')
    if access_type not in VALID_ACCESS_TYPES:
        return None, None
    try:
        floor = int(floor_raw)
    except (ValueError, TypeError):
        return None, None
    if floor < 1 or floor > 30:
        return None, None
    if floor > 1 and access_type == 'ground_floor':
        logger.warning(f"Floor {floor} with access_type=ground_floor submitted by user {getattr(current_user, 'id', '?')} — allowing (edge case)")
    return access_type, floor


@app.route('/update_profile', methods=['POST'])
@login_required
def update_profile():
    location_type = request.form.get('pickup_location_type')

    # Shared helper to read access fields
    class _FormProxy:
        def get(self, key, default=None):
            return request.form.get(key, default)

    proxy = _FormProxy()

    if location_type == 'on_campus':
        dorm = (request.form.get('pickup_dorm') or '').strip()
        room = (request.form.get('pickup_room') or '').strip()
        access_type, floor = _validate_access_fields(proxy)
        if not dorm:
            flash("Please select a dorm.", "error")
        elif not room:
            flash("Please enter your room number.", "error")
        elif access_type is None:
            flash("Please select a valid access type.", "error")
        elif floor is None:
            flash("Please enter a valid floor number (1–30).", "error")
        else:
            current_user.pickup_location_type = 'on_campus'
            current_user.pickup_dorm = dorm[:80]
            current_user.pickup_room = room[:20]
            current_user.pickup_address = None
            current_user.pickup_lat = None
            current_user.pickup_lng = None
            current_user.pickup_access_type = access_type
            current_user.pickup_floor = floor
            current_user.pickup_note = (request.form.get('pickup_note') or '').strip()[:500] or None
            phone = (request.form.get('phone') or '').replace('(', '').replace(')', '').replace('-', '').replace(' ', '')
            if len(phone) >= 10:
                current_user.phone = phone[:20]
            db.session.commit()
            flash("Pickup location saved.", "success")

    elif location_type == 'off_campus_complex':
        building = (request.form.get('pickup_dorm') or '').strip()
        unit = (request.form.get('pickup_room') or '').strip()
        access_type, floor = _validate_access_fields(proxy)
        if building not in OFF_CAMPUS_COMPLEXES:
            flash("Please select a valid apartment complex.", "error")
        elif not unit:
            flash("Please enter your unit number.", "error")
        elif access_type is None:
            flash("Please select a valid access type.", "error")
        elif floor is None:
            flash("Please enter a valid floor number (1–30).", "error")
        else:
            current_user.pickup_location_type = 'off_campus_complex'
            current_user.pickup_dorm = building
            current_user.pickup_room = unit[:20]
            current_user.pickup_address = None
            current_user.pickup_lat = None
            current_user.pickup_lng = None
            current_user.pickup_access_type = access_type
            current_user.pickup_floor = floor
            current_user.pickup_note = (request.form.get('pickup_note') or '').strip()[:500] or None
            phone = (request.form.get('phone') or '').replace('(', '').replace(')', '').replace('-', '').replace(' ', '')
            if len(phone) >= 10:
                current_user.phone = phone[:20]
            db.session.commit()
            flash("Pickup location saved.", "success")

    elif location_type == 'off_campus_other':
        address = (request.form.get('pickup_address') or '').strip()
        access_type, floor = _validate_access_fields(proxy)
        if not address:
            flash("Please enter your address.", "error")
        elif access_type is None:
            flash("Please select a valid access type.", "error")
        elif floor is None:
            flash("Please enter a valid floor number (1–30).", "error")
        else:
            current_user.pickup_location_type = 'off_campus_other'
            current_user.pickup_address = address[:300]
            current_user.pickup_dorm = None
            current_user.pickup_room = None
            lat = request.form.get('pickup_lat')
            lng = request.form.get('pickup_lng')
            current_user.pickup_lat = float(lat) if lat and lat.strip() else None
            current_user.pickup_lng = float(lng) if lng and lng.strip() else None
            current_user.pickup_access_type = access_type
            current_user.pickup_floor = floor
            current_user.pickup_note = (request.form.get('pickup_note') or '').strip()[:500] or None
            phone = (request.form.get('phone') or '').replace('(', '').replace(')', '').replace('-', '').replace(' ', '')
            if len(phone) >= 10:
                current_user.phone = phone[:20]
            db.session.commit()
            flash("Pickup location saved.", "success")

    else:
        # Legacy: plain address field (backward compat)
        address = request.form.get('address')
        if address:
            current_user.pickup_location_type = 'off_campus_other'
            current_user.pickup_address = address[:300]
            current_user.pickup_dorm = None
            current_user.pickup_room = None
            current_user.pickup_note = None
            current_user.pickup_lat = None
            current_user.pickup_lng = None
            db.session.commit()
            flash("Profile updated.", "success")

    dest = request.form.get('redirect_to')
    if dest == 'account_settings':
        return redirect(url_for('account_settings'))
    return redirect(get_user_dashboard())

@app.route('/update_payout', methods=['POST'])
@login_required
def update_payout():
    method = request.form.get('payout_method')
    handle = request.form.get('payout_handle')
    handle_confirm = request.form.get('payout_handle_confirm', '').strip()

    if method and handle:
        clean_handle = handle.lstrip('@').strip() if method == 'Venmo' else handle.strip()
        clean_confirm = handle_confirm.lstrip('@').strip() if method == 'Venmo' else handle_confirm.strip()
        if not clean_handle:
            flash("Please enter a valid handle.", "error")
            return redirect(url_for('account_settings'))
        if clean_handle.lower() != clean_confirm.lower():
            flash("Handles do not match. Please re-enter to confirm.", "error")
            return redirect(url_for('account_settings'))
        current_user.payout_method = method
        current_user.payout_handle = clean_handle
        current_user.is_seller = True
        db.session.commit()
        db.session.refresh(current_user)
        flash("Payout info secured.", "success")
    return redirect(get_user_dashboard())

@app.route('/add_payment_method')
@login_required
def add_payment_method():
    """Page to add payment method (Setup Intent - no charge until pickup)."""
    stripe_pk = os.environ.get('STRIPE_PUBLISHABLE_KEY', '')
    stripe_configured = bool(stripe.api_key and stripe_pk)
    return render_template('add_payment_method.html',
        stripe_publishable_key=stripe_pk,
        stripe_configured=stripe_configured)

@app.route('/create_setup_intent', methods=['POST'])
@login_required
def create_setup_intent():
    """Create Stripe SetupIntent to save card without charging."""
    if not stripe.api_key:
        return jsonify({'error': 'Stripe not configured'}), 500
    try:
        customer_id = current_user.stripe_customer_id
        if not customer_id:
            customer = stripe.Customer.create(
                email=current_user.email,
                name=current_user.full_name or current_user.email,
                metadata={'user_id': current_user.id}
            )
            customer_id = customer.id
            current_user.stripe_customer_id = customer_id
            db.session.commit()
        
        setup_intent = stripe.SetupIntent.create(
            customer=customer_id,
            payment_method_types=['card'],
            usage='off_session',
            metadata={'user_id': str(current_user.id)}
        )
        return jsonify({'client_secret': setup_intent.client_secret})
    except Exception as e:
        logger.error(f"create_setup_intent: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@app.route('/payment_method_success')
@login_required
def payment_method_success():
    """After SetupIntent completes; payment_declined cleared."""
    current_user.payment_declined = False
    flash("Payment method saved. You won't be charged until pickup week.", "success")
    db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/upgrade_checkout', methods=['POST'])
@login_required
def upgrade_checkout():
    """Legacy Pro upgrade — retired. Redirect to dashboard."""
    flash("The Pro plan upgrade is no longer available.", "info")
    return redirect(url_for('dashboard'))

@app.route('/create_checkout_session', methods=['POST'])
def create_checkout_session():
    """Item purchase checkout (delivery flow) or legacy seller activation."""
    item_id = request.form.get('item_id', type=int)

    if item_id is not None:
        # Item purchase flow — requires pending_delivery in session
        delivery = session.get('pending_delivery')
        if not delivery or delivery.get('item_id') != item_id:
            flash('Please confirm your delivery address to continue.', 'info')
            return redirect(url_for('checkout_delivery', item_id=item_id))

        item = InventoryItem.query.get_or_404(item_id)
        if item.status != 'available':
            flash("Sorry! This item is no longer available.", "error")
            return redirect(url_for('inventory'))

        try:
            img_url = url_for('uploaded_file', filename=item.photo_url, _external=True) if item.photo_url else None
            stripe_session = stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=[{
                    'price_data': {
                        'currency': 'usd',
                        'product_data': {
                            'name': item.description,
                            'images': [img_url] if img_url else [],
                        },
                        'unit_amount': int(item.price * 100),
                    },
                    'quantity': 1,
                }],
                mode='payment',
                client_reference_id=str(item.id),
                metadata={
                    'item_id': item.id,
                    'delivery_address': delivery['address_string'],
                    'delivery_lat': str(delivery['lat']),
                    'delivery_lng': str(delivery['lng']),
                },
                success_url=url_for('item_sold_success', _external=True) + '?session_id={CHECKOUT_SESSION_ID}',
                cancel_url=url_for('inventory', _external=True),
            )
            return redirect(stripe_session.url, code=303)
        except stripe.error.StripeError as e:
            logger.error(f"Stripe error in create_checkout_session (item): {e}")
            flash("Payment processing error. Please try again.", "error")
            return redirect(url_for('checkout_delivery', item_id=item_id))
        except Exception as e:
            logger.error(f"Error in create_checkout_session (item): {e}", exc_info=True)
            flash("An error occurred. Please try again.", "error")
            return redirect(url_for('checkout_delivery', item_id=item_id))
    else:
        # Legacy seller activation flow — requires login
        if not current_user.is_authenticated:
            flash('Please log in to continue.', 'error')
            return redirect(url_for('login'))
        try:
            stripe_session = stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=[{
                    'price_data': {
                        'currency': 'usd',
                        'product_data': {'name': 'Campus Swap Seller Registration'},
                        'unit_amount': SELLER_ACTIVATION_FEE_CENTS,
                    },
                    'quantity': 1,
                }],
                mode='payment',
                client_reference_id=str(current_user.id),
                metadata={'type': 'seller_activation', 'user_id': current_user.id},
                success_url=url_for('payment_success', _external=True) + '?session_id={CHECKOUT_SESSION_ID}',
                cancel_url=url_for('dashboard', _external=True),
            )
            return redirect(stripe_session.url, code=303)
        except Exception as e:
            return str(e)

@app.route('/success')
@login_required
def payment_success():
    session_id = request.args.get('session_id')
    if session_id:
        try:
            # Verify payment status directly from Stripe (in case webhook hasn't fired yet)
            stripe_session = stripe.checkout.Session.retrieve(session_id)
            
            if stripe_session.metadata and stripe_session.payment_status == 'paid':
                user_id = int(stripe_session.metadata.get('user_id', 0))
                if user_id != current_user.id:
                    pass  # Not for this user
                elif stripe_session.metadata.get('type') == 'upgrade':
                    # Upgrade: batch-update free items to online
                    upgraded = InventoryItem.query.filter(
                        InventoryItem.seller_id == current_user.id,
                        InventoryItem.collection_method == 'free'
                    ).update({'collection_method': 'online'}, synchronize_session=False)
                    current_user.payment_declined = False
                    current_user.has_paid = True  # Required for online items to go live
                    db.session.commit()
                    # PostHog: seller upgraded from free to paid tier
                    posthog.capture('seller_upgraded_to_paid', distinct_id=str(current_user.id))
                    db.session.expire(current_user)
                    db.session.refresh(current_user)
                    flash("Upgraded to Campus Swap Pickup! Paid $15. All your items are now on our pickup route.", "success")
                elif stripe_session.metadata.get('type') == 'seller_activation':
                    # Seller activation
                    if not current_user.has_paid:
                        current_user.has_paid = True
                        current_user.is_seller = True
                        db.session.commit()
                    
                    db.session.expire(current_user)
                    db.session.refresh(current_user)
                    
                    flash("Your item is submitted and you've secured your spot for the summer. We'll pick up from your listed address during move-out week. More details on exact pickup logistics will follow.", "success")
        except Exception as e:
            logger.error(f"Error verifying payment: {e}", exc_info=True)
            # Still show success message - webhook will handle it
            flash("Payment received! Processing...", "info")
    else:
        flash("Your item is submitted and you've secured your spot for the summer. We'll pick up from your listed address during move-out week. More details on exact pickup logistics will follow.", "success")
    
    return redirect(get_user_dashboard())

def _user_has_payout(user):
    return (
        user.is_authenticated
        and user.payout_method is not None
        and user.payout_handle is not None
        and user.payout_handle.strip() != ''
    )


@app.route('/onboard', methods=['GET', 'POST'])
def onboard():
    """6-step wizard for first-time sellers (0 items). Guests can complete wizard then create account at end."""
    if current_user.is_authenticated:
        if current_user.is_admin:
            return redirect(url_for('admin_panel'))
        if current_user.payment_declined:
            flash("Please add a valid payment method to continue.", "error")
            return redirect(url_for('add_payment_method'))

    # Save ?ref= param to session for guest flow
    ref_param = request.args.get('ref', '').strip()
    if ref_param and not session.get('referral_code'):
        session['referral_code'] = ref_param

    pickup_period_active = get_pickup_period_active()
    if not pickup_period_active:
        # Render onboard page with "closed" message instead of redirecting (avoids redirect loop with dashboard)
        return render_template('onboard.html', pickup_ended=True, categories=[], category_price_ranges={}, dorms={}, google_maps_key='', is_guest=not current_user.is_authenticated, warehouse_spots=0, skip_payout=True)

    categories = InventoryCategory.query.filter_by(parent_id=None).order_by(InventoryCategory.id).all()
    category_price_ranges = {cat.id: get_price_range_for_category(cat.name) for cat in categories}
    # Also include subcategory price ranges for the JS price hint
    all_subcats = InventoryCategory.query.filter(InventoryCategory.parent_id.isnot(None)).all()
    for sc in all_subcats:
        category_price_ranges[sc.id] = get_price_range_for_category(sc.name)
    dorms = RESIDENCE_HALLS_BY_STORE.get(get_current_store(), {})
    google_maps_key = os.environ.get('GOOGLE_MAPS_API_KEY', '')

    if not categories:
        # Don't redirect authenticated non-admin users to get_user_dashboard() — that sends them
        # back to /dashboard which redirects here again, causing an infinite loop.
        if current_user.is_authenticated and current_user.is_admin:
            return redirect(url_for('admin_panel'))
        return render_template('onboard.html', pickup_ended=True, categories=[], category_price_ranges={}, dorms={}, google_maps_key='', is_guest=not current_user.is_authenticated, warehouse_spots=0, no_categories=True, skip_payout=True)

    if request.method == 'POST':
        _step_param = request.form.get('step', '').strip()

        # ---- Step location: save pickup location to session (guest + authenticated) ----
        if _step_param == 'location':
            _loc_type = (request.form.get('pickup_location_type') or '').strip()
            _render_kwargs = dict(
                categories=categories, category_price_ranges=category_price_ranges,
                dorms=dorms, google_maps_key=google_maps_key,
                is_guest=not current_user.is_authenticated, skip_payout=True,
            )

            class _FormProxyOnboard:
                def get(self, key, default=None):
                    return request.form.get(key, default)
            _proxy = _FormProxyOnboard()
            _access_type, _floor = _validate_access_fields(_proxy)

            if _loc_type == 'on_campus':
                _dorm = (request.form.get('pickup_dorm') or '').strip()
                _room = (request.form.get('pickup_room') or '').strip()
                if not _dorm or not _room or _access_type is None or _floor is None:
                    flash("Please complete all location fields.", "error")
                    return render_template('onboard.html', **_render_kwargs)
                session['onboard_pickup_location_type'] = 'on_campus'
                session['onboard_pickup_dorm'] = _dorm[:80]
                session['onboard_pickup_room'] = _room[:20]
                session['onboard_pickup_address'] = None
                session['onboard_pickup_lat'] = None
                session['onboard_pickup_lng'] = None
                session['onboard_pickup_access_type'] = _access_type
                session['onboard_pickup_floor'] = _floor
                session['onboard_pickup_note'] = (request.form.get('pickup_note') or '').strip()[:500] or None
            elif _loc_type == 'off_campus_complex':
                _building = (request.form.get('pickup_dorm') or '').strip()
                _unit = (request.form.get('pickup_room') or '').strip()
                if _building not in OFF_CAMPUS_COMPLEXES or not _unit or _access_type is None or _floor is None:
                    flash("Please complete all location fields.", "error")
                    return render_template('onboard.html', **_render_kwargs)
                session['onboard_pickup_location_type'] = 'off_campus_complex'
                session['onboard_pickup_dorm'] = _building
                session['onboard_pickup_room'] = _unit[:20]
                session['onboard_pickup_address'] = None
                session['onboard_pickup_lat'] = None
                session['onboard_pickup_lng'] = None
                session['onboard_pickup_access_type'] = _access_type
                session['onboard_pickup_floor'] = _floor
                session['onboard_pickup_note'] = (request.form.get('pickup_note') or '').strip()[:500] or None
            elif _loc_type == 'off_campus_other':
                _address = (request.form.get('pickup_address') or '').strip()
                if not _address or _access_type is None or _floor is None:
                    flash("Please complete all location fields.", "error")
                    return render_template('onboard.html', **_render_kwargs)
                _lat_raw = request.form.get('pickup_lat')
                _lng_raw = request.form.get('pickup_lng')
                session['onboard_pickup_location_type'] = 'off_campus_other'
                session['onboard_pickup_dorm'] = None
                session['onboard_pickup_room'] = None
                session['onboard_pickup_address'] = _address[:300]
                session['onboard_pickup_lat'] = float(_lat_raw) if _lat_raw and _lat_raw.strip() else None
                session['onboard_pickup_lng'] = float(_lng_raw) if _lng_raw and _lng_raw.strip() else None
                session['onboard_pickup_access_type'] = _access_type
                session['onboard_pickup_floor'] = _floor
                session['onboard_pickup_note'] = (request.form.get('pickup_note') or '').strip()[:500] or None
            else:
                flash("Please select a location type.", "error")
                return render_template('onboard.html', **_render_kwargs)

            # If authenticated, save directly to user
            if current_user.is_authenticated:
                current_user.pickup_location_type = session['onboard_pickup_location_type']
                current_user.pickup_dorm = session['onboard_pickup_dorm']
                current_user.pickup_room = session['onboard_pickup_room']
                current_user.pickup_address = session['onboard_pickup_address']
                current_user.pickup_lat = session['onboard_pickup_lat']
                current_user.pickup_lng = session['onboard_pickup_lng']
                current_user.pickup_access_type = session['onboard_pickup_access_type']
                current_user.pickup_floor = session['onboard_pickup_floor']
                current_user.pickup_note = session['onboard_pickup_note']
                db.session.commit()
            return redirect(url_for('onboard'))

        # ---- Step 7: save payout (authenticated, no photos required) ----
        if _step_param == '7' and current_user.is_authenticated:
            _pr = (request.form.get('payout_handle') or '').strip()
            _pc = (request.form.get('payout_handle_confirm') or '').strip()
            _pm = (request.form.get('payout_method') or 'Venmo').strip()[:20]
            _ph = _pr.lstrip('@') if _pm == 'Venmo' else _pr
            _pch = _pc.lstrip('@') if _pm == 'Venmo' else _pc
            if _ph:
                if _ph.lower() != _pch.lower():
                    flash("Handles do not match. Please re-enter to confirm.", "error")
                    return render_template('onboard.html', categories=categories, category_price_ranges=category_price_ranges, dorms=dorms, google_maps_key=google_maps_key, is_guest=False, skip_payout=True)
                current_user.payout_method = _pm if _pm.lower() in ('venmo', 'paypal', 'zelle') else 'Venmo'
                current_user.payout_handle = _ph
                current_user.is_seller = True
                db.session.commit()
            return redirect(url_for('onboard'))

        # ---- Step submit: create item from session data (authenticated) ----
        if _step_param == 'submit' and current_user.is_authenticated:
            _cat_id = session.get('onboard_category_id')
            _quality_val = session.get('onboard_quality', 4)
            _desc = str(session.get('onboard_description', ''))[:MAX_DESCRIPTION_LENGTH]
            _long_desc_raw = session.get('onboard_long_description')
            _long_desc = str(_long_desc_raw)[:MAX_LONG_DESCRIPTION_LENGTH] if _long_desc_raw else None
            _sp_raw = session.get('onboard_suggested_price', '')
            _suggested_price = None
            try:
                _sp = float(str(_sp_raw))
                if _sp >= 0:
                    _suggested_price = _sp
            except (ValueError, TypeError):
                pass
            _new_item = InventoryItem(
                seller_id=current_user.id,
                category_id=int(_cat_id) if _cat_id else 1,
                description=_desc,
                long_description=_long_desc,
                quality=int(_quality_val) if _quality_val else 4,
                status='pending_valuation',
                photo_url='',
                collection_method='free',
                suggested_price=_suggested_price,
            )
            db.session.add(_new_item)
            current_user.is_seller = True
            db.session.commit()
            flash("Item submitted! We'll review and price it soon.", "success")
            return redirect(get_user_dashboard())

        # ---- Step create_account: guest creates account + item ----
        if _step_param == 'create_account' and not current_user.is_authenticated:
            from werkzeug.security import generate_password_hash as _gph
            _full_name = request.form.get('full_name', '').strip()
            _email = request.form.get('email', '').strip().lower()
            _phone_raw = request.form.get('phone', '').replace('(', '').replace(')', '').replace('-', '').replace(' ', '')
            _password = request.form.get('password', '')
            if not _email or not _password:
                flash("Email and password are required.", "error")
                return render_template('onboard.html', categories=categories, category_price_ranges=category_price_ranges, dorms=dorms, google_maps_key=google_maps_key, is_guest=True, skip_payout=True, warehouse_spots=get_warehouse_spots_remaining())
            if User.query.filter_by(email=_email).first():
                flash("An account with this email already exists. Please log in.", "error")
                return render_template('onboard.html', categories=categories, category_price_ranges=category_price_ranges, dorms=dorms, google_maps_key=google_maps_key, is_guest=True, skip_payout=True, warehouse_spots=get_warehouse_spots_remaining())
            _cat_id = session.get('onboard_category_id')
            _quality_val = session.get('onboard_quality', 4)
            _desc = str(session.get('onboard_description', ''))[:MAX_DESCRIPTION_LENGTH]
            _long_desc_raw = session.get('onboard_long_description')
            _long_desc = str(_long_desc_raw)[:MAX_LONG_DESCRIPTION_LENGTH] if _long_desc_raw else None
            _sp_raw = session.get('onboard_suggested_price', '')
            _suggested_price = None
            try:
                _sp = float(str(_sp_raw))
                if _sp >= 0:
                    _suggested_price = _sp
            except (ValueError, TypeError):
                pass
            _payout_method = session.get('onboard_payout_method', 'Venmo')
            _payout_handle_raw = session.get('onboard_payout_handle', '')
            _payout_handle = str(_payout_handle_raw).lstrip('@') if str(_payout_method).lower() == 'venmo' else str(_payout_handle_raw)
            _new_user = User(
                email=_email,
                full_name=_full_name,
                password_hash=_gph(_password),
                phone=_phone_raw[:20] if len(_phone_raw) >= 10 else None,
                is_seller=True,
                payout_method=_payout_method if _payout_method in ('Venmo', 'PayPal', 'Zelle') else 'Venmo',
                payout_handle=_payout_handle or None,
            )
            db.session.add(_new_user)
            db.session.flush()
            if _cat_id:
                _new_item = InventoryItem(
                    seller_id=_new_user.id,
                    category_id=int(_cat_id),
                    description=_desc,
                    long_description=_long_desc,
                    quality=int(_quality_val) if _quality_val else 4,
                    status='pending_valuation',
                    photo_url='',
                    collection_method='free',
                    suggested_price=_suggested_price,
                )
                db.session.add(_new_item)
            db.session.commit()
            login_user(_new_user)
            return redirect(url_for('onboard_complete'))

    if request.method == 'POST' and current_user.is_authenticated:
        cat_id = request.form.get('category_id')
        desc = request.form.get('description', '').strip()
        long_desc = (request.form.get('long_description') or '').strip()
        quality = request.form.get('quality')
        suggested_price_raw = request.form.get('suggested_price', '').strip()
        # All new sellers start on free tier — upgrade is a deliberate dashboard action
        collection_method = 'free'
        files = request.files.getlist('photos')
        temp_photo_ids_raw = request.form.get('temp_photo_ids', '')
        temp_photo_ids = [x.strip() for x in temp_photo_ids_raw.split(',') if x.strip()]

        has_files = files and files[0].filename and files[0].filename != ''
        has_temp_photos = len(temp_photo_ids) > 0

        # Mattress photo exemption — check category name before photo validation
        try:
            _cat_early = db.session.get(InventoryCategory, int(cat_id)) if cat_id else None
            is_mattress = _cat_early is not None and _cat_early.name.lower() == 'mattress'
        except (ValueError, TypeError):
            is_mattress = False
        if is_mattress and request.form.get('mattress_condition_acknowledged') != '1':
            flash("Please confirm the mattress condition policy.", "error")
            return render_template('onboard.html', categories=categories, category_price_ranges=category_price_ranges, dorms=dorms, google_maps_key=google_maps_key, is_guest=False, skip_payout=True)

        if not is_mattress and not has_files and not has_temp_photos:
            flash("Please add at least one photo.", "error")
            return render_template('onboard.html', categories=categories, category_price_ranges=category_price_ranges, dorms=dorms, google_maps_key=google_maps_key, is_guest=False, skip_payout=True)
        if not cat_id:
            flash("Please select a category.", "error")
            return render_template('onboard.html', categories=categories, category_price_ranges=category_price_ranges, dorms=dorms, google_maps_key=google_maps_key, is_guest=False, skip_payout=True)

        quality_valid, quality_value = validate_quality(quality)
        if not quality_valid:
            flash(f"Invalid condition.", "error")
            return render_template('onboard.html', categories=categories, category_price_ranges=category_price_ranges, dorms=dorms, google_maps_key=google_maps_key, is_guest=False, skip_payout=True)

        suggested_price = None
        if suggested_price_raw:
            try:
                sp = float(suggested_price_raw)
                if sp >= 0:
                    suggested_price = sp
            except ValueError:
                pass

        payout_raw = (request.form.get('payout_handle') or '').strip()
        payout_confirm_raw = (request.form.get('payout_handle_confirm') or '').strip()
        payout_method = (request.form.get('payout_method') or 'Venmo').strip()[:20]
        payout_handle = payout_raw.lstrip('@') if payout_method == 'Venmo' else payout_raw
        payout_confirm = payout_confirm_raw.lstrip('@') if payout_method == 'Venmo' else payout_confirm_raw
        if payout_handle:
            if payout_handle.lower() != payout_confirm.lower():
                flash("Handles do not match. Please re-enter to confirm.", "error")
                return render_template('onboard.html', categories=categories, category_price_ranges=category_price_ranges, dorms=dorms, google_maps_key=google_maps_key, is_guest=False, skip_payout=True)
            current_user.payout_method = payout_method if payout_method in ('Venmo', 'PayPal', 'Zelle') else 'Venmo'
            current_user.payout_handle = payout_handle
            current_user.is_seller = True

        db.session.commit()

        # Subcategory validation
        sub_id = request.form.get('subcategory_id')
        subcategory_id = None
        if sub_id:
            try:
                subcategory_id = int(sub_id)
                sub_cat = InventoryCategory.query.get(subcategory_id)
                if not sub_cat or sub_cat.parent_id != int(cat_id):
                    subcategory_id = None
            except (ValueError, TypeError):
                subcategory_id = None

        # Create the item (reuse add_item logic)
        new_item = InventoryItem(
            seller_id=current_user.id, category_id=int(cat_id), description=desc[:MAX_DESCRIPTION_LENGTH],
            long_description=long_desc[:MAX_LONG_DESCRIPTION_LENGTH] if long_desc else None,
            quality=quality_value, status="pending_valuation", photo_url="",
            collection_method=collection_method,
            suggested_price=suggested_price,
            subcategory_id=subcategory_id,
        )
        db.session.add(new_item)
        db.session.flush()

        cover_set = False
        photo_index = 0
        if has_files:
            for file in files:
                if file.filename:
                    is_valid, error_msg = validate_file_upload(file)
                    if not is_valid:
                        db.session.rollback()
                        flash(f"File upload error: {error_msg}", "error")
                        return render_template('onboard.html', categories=categories, category_price_ranges=category_price_ranges, dorms=dorms, google_maps_key=google_maps_key, is_guest=False, skip_payout=True)
                    filename = f"item_{new_item.id}_{int(time.time())}_{photo_index}.jpg"
                    try:
                        photo_storage.save_photo(file, filename)
                        if not cover_set:
                            new_item.photo_url = filename
                            cover_set = True
                        db.session.add(ItemPhoto(item_id=new_item.id, photo_url=filename))
                        photo_index += 1
                    except Exception as img_error:
                        db.session.rollback()
                        logger.error(f"Image error: {img_error}", exc_info=True)
                        flash("Error processing image. Please try again.", "error")
                        return render_template('onboard.html', categories=categories, category_price_ranges=category_price_ranges, dorms=dorms, google_maps_key=google_maps_key, is_guest=False, skip_payout=True)

        if has_temp_photos:
            temp_folder = app.config['TEMP_UPLOAD_FOLDER']
            for temp_fn in temp_photo_ids:
                temp_rec = TempUpload.query.filter(
                    TempUpload.filename == temp_fn,
                    TempUpload.session_token.in_(
                        db.session.query(UploadSession.session_token).filter(UploadSession.user_id == current_user.id)
                    )
                ).first()
                if not temp_rec:
                    db.session.rollback()
                    flash("Invalid or expired photo from phone. Please try again.", "error")
                    return render_template('onboard.html', categories=categories, category_price_ranges=category_price_ranges, dorms=dorms, google_maps_key=google_maps_key, is_guest=False, skip_payout=True)
                old_path = os.path.join(temp_folder, temp_fn)
                if not os.path.exists(old_path):
                    db.session.rollback()
                    flash("Photo from phone no longer available. Please re-upload.", "error")
                    return render_template('onboard.html', categories=categories, category_price_ranges=category_price_ranges, dorms=dorms, google_maps_key=google_maps_key, is_guest=False, skip_payout=True)
                new_filename = f"item_{new_item.id}_{int(time.time())}_{photo_index}.jpg"
                try:
                    photo_storage.save_photo_from_path(old_path, new_filename)
                    os.remove(old_path)
                except OSError:
                    pass
                if not cover_set:
                    new_item.photo_url = new_filename
                    cover_set = True
                db.session.add(ItemPhoto(item_id=new_item.id, photo_url=new_filename))
                db.session.delete(temp_rec)
                photo_index += 1

        # --- VIDEO HANDLING ---
        video_file = request.files.get('video')
        temp_video_id = (request.form.get('temp_video_id') or '').strip()
        has_video_file = video_file and video_file.filename and video_file.filename != ''
        cat_obj = InventoryCategory.query.get(int(cat_id))
        cat_name = cat_obj.name if cat_obj else ''
        sub_cat_name = sub_cat.name if subcategory_id and sub_cat else ''

        if has_video_file:
            is_valid, error_msg = validate_video_upload(video_file)
            if not is_valid:
                db.session.rollback()
                flash(f"Video upload error: {error_msg}", "error")
                return render_template('onboard.html', categories=categories, category_price_ranges=category_price_ranges, dorms=dorms, google_maps_key=google_maps_key, is_guest=False, skip_payout=True)
            safe_name = secure_filename(video_file.filename)
            ext = safe_name.rsplit('.', 1)[1].lower() if '.' in safe_name else 'mp4'
            video_key = f"video_{new_item.id}_{int(time.time())}.{ext}"
            try:
                photo_storage.save_video(video_file, video_key)
                new_item.video_url = video_key
            except Exception as vid_error:
                db.session.rollback()
                logger.error(f"Video save error: {vid_error}", exc_info=True)
                flash("Error saving video. Please try again.", "error")
                return render_template('onboard.html', categories=categories, category_price_ranges=category_price_ranges, dorms=dorms, google_maps_key=google_maps_key, is_guest=False, skip_payout=True)
        elif temp_video_id:
            temp_rec = TempUpload.query.filter(
                TempUpload.filename == temp_video_id,
                TempUpload.session_token.in_(
                    db.session.query(UploadSession.session_token).filter(UploadSession.user_id == current_user.id)
                )
            ).first()
            if temp_rec:
                old_path = os.path.join(app.config['TEMP_UPLOAD_FOLDER'], temp_video_id)
                if os.path.exists(old_path):
                    ext = temp_video_id.rsplit('.', 1)[1].lower() if '.' in temp_video_id else 'mp4'
                    video_key = f"video_{new_item.id}_{int(time.time())}.{ext}"
                    try:
                        photo_storage.save_video_from_path(old_path, video_key)
                        new_item.video_url = video_key
                        os.remove(old_path)
                    except OSError:
                        pass
                db.session.delete(temp_rec)
        elif category_requires_video(cat_name, sub_cat_name):
            db.session.rollback()
            flash("A video is required for this item category.", "error")
            return render_template('onboard.html', categories=categories, category_price_ranges=category_price_ranges, dorms=dorms, google_maps_key=google_maps_key, is_guest=False, skip_payout=True)

        db.session.commit()
        # PostHog: item submitted for review
        try:
            posthog.capture('item_submitted', distinct_id=str(current_user.id), properties={
                'item_id': new_item.id,
                'category': new_item.category.name if new_item.category else None,
            })
        except Exception:
            pass

        # Trigger AI lookup in background (after commit, never blocks response)
        try:
            trigger_ai_lookup(new_item.id)
        except Exception:
            logger.error(f"Failed to trigger AI lookup for item {new_item.id}", exc_info=True)

        # No payment at onboarding - user pays after approval when confirming pickup
        try:
            submission_content = f"""
            <div style="font-family: sans-serif; padding: 20px; max-width: 500px;">
                <h2 style="color: #166534;">Item Submitted for Review</h2>
                <p>Hi {current_user.full_name or 'there'},</p>
                <p>We've received your item submission: <strong>{desc}</strong></p>
                <p>We'll review and price it soon. You'll get an email when it's approved—then you'll confirm your pickup week.</p>
                <p><a href="{url_for('dashboard', _external=True)}" style="background: #166534; color: white; padding: 12px 24px; text-decoration: none; border-radius: 8px;">View Dashboard</a></p>
                <p>Thanks for selling with Campus Swap!</p>
            </div>
            """
            send_email(current_user.email, "Item Submitted - Campus Swap", submission_content)
        except Exception as email_error:
            logger.error(f"Onboard email error: {email_error}")
        flash("Item submitted! We'll review and price it soon. You'll confirm your pickup after approval. Check your spam folder if you don't receive our emails.", "success")

        return redirect(get_user_dashboard())

    return render_template('onboard.html', categories=categories, category_price_ranges=category_price_ranges, dorms=dorms, google_maps_key=google_maps_key, is_guest=not current_user.is_authenticated,
                           warehouse_spots=get_warehouse_spots_remaining(), skip_payout=True)


@app.route('/onboard/guest/save', methods=['POST'])
def onboard_guest_save():
    """Save guest onboarding data to session; redirect or return JSON for embedded step 11."""
    ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    def _err(msg):
        if ajax:
            return jsonify({'success': False, 'error': msg}), 400
        flash(msg, "error")
        return redirect(url_for('onboard'))

    def _ok():
        if ajax:
            return jsonify({'success': True})
        return redirect(url_for('onboard_complete_account'))

    if current_user.is_authenticated:
        return redirect(url_for('onboard'))

    pickup_period_active = get_pickup_period_active()
    if not pickup_period_active:
        if ajax:
            return jsonify({'success': False, 'error': "Pickup period has ended."}), 400
        flash("Pickup period has ended. We'll notify you when signups open again.", "info")
        return redirect(url_for('index'))

    cat_id = request.form.get('category_id')
    desc = request.form.get('description', '').strip()
    long_desc = (request.form.get('long_description') or '').strip()
    quality = request.form.get('quality')
    suggested_price_raw = request.form.get('suggested_price', '').strip()
    # All new sellers start on free tier — upgrade is a deliberate dashboard action
    collection_method = 'free'
    files = request.files.getlist('photos')
    temp_photo_ids_raw = request.form.get('temp_photo_ids', '')
    temp_photo_ids = [x.strip() for x in temp_photo_ids_raw.split(',') if x.strip()]
    guest_upload_token = session.get('guest_upload_token')

    has_files = files and files[0].filename and files[0].filename != ''
    has_temp_photos = len(temp_photo_ids) > 0
    if not has_files and not has_temp_photos:
        return _err("Please add at least one photo.")
    if not cat_id:
        return _err("Please select a category.")

    quality_valid, quality_value = validate_quality(quality)
    if not quality_valid:
        return _err("Invalid condition.")

    suggested_price = None
    if suggested_price_raw:
        try:
            sp = float(suggested_price_raw)
            if sp >= 0:
                suggested_price = sp
        except ValueError:
            pass

    # Address and phone are collected at confirm_pickup when user selects their week
    phone_raw = (request.form.get('phone') or '').replace('(', '').replace(')', '').replace('-', '').replace(' ', '')

    # Payout is no longer collected during onboarding — set up in account settings
    payout_method = None
    payout_handle = None

    photo_filenames = []
    if has_files:
        for file in files:
            if file.filename:
                is_valid, error_msg = validate_file_upload(file)
                if not is_valid:
                    return _err(f"File upload error: {error_msg}")
                filename = f"guest_temp_{int(time.time())}_{secrets.token_hex(4)}_{len(photo_filenames)}.jpg"
                save_path = os.path.join(app.config['TEMP_UPLOAD_FOLDER'], filename)
                try:
                    img = Image.open(file)
                    img = ImageOps.exif_transpose(img)
                    img = img.convert("RGBA")
                    bg = Image.new("RGB", img.size, (255, 255, 255))
                    bg.paste(img, (0, 0), img)
                    max_dimension = 2000
                    if bg.width > max_dimension or bg.height > max_dimension:
                        ratio = max_dimension / max(bg.width, bg.height)
                        new_w, new_h = int(bg.width * ratio), int(bg.height * ratio)
                        bg = bg.resize((new_w, new_h), Image.Resampling.LANCZOS)
                    bg.save(save_path, "JPEG", quality=IMAGE_QUALITY, optimize=True)
                    photo_filenames.append(filename)
                except Exception as img_error:
                    logger.error(f"Guest onboard image error: {img_error}", exc_info=True)
                    return _err("Error processing image. Please try again.")

    if has_temp_photos:
        if not guest_upload_token:
            return _err("Photo session expired. Please re-scan the QR code to add photos from your phone.")
        for temp_fn in temp_photo_ids:
            temp_rec = TempUpload.query.filter_by(session_token=guest_upload_token, filename=temp_fn).first()
            if not temp_rec:
                return _err("Invalid or expired photo from phone. Please re-scan the QR code.")
            old_path = os.path.join(app.config['TEMP_UPLOAD_FOLDER'], temp_fn)
            if not os.path.exists(old_path):
                return _err("Photo from phone no longer available. Please re-upload.")

    # --- VIDEO HANDLING (guest) ---
    video_file = request.files.get('video')
    temp_video_id = (request.form.get('temp_video_id') or '').strip()
    has_video_file = video_file and video_file.filename and video_file.filename != ''
    guest_video_filename = None

    cat_obj = InventoryCategory.query.get(int(cat_id))
    cat_name = cat_obj.name if cat_obj else ''

    # Resolve subcategory name for video requirement check
    guest_sub_id = request.form.get('subcategory_id')
    guest_subcategory_id = None
    guest_sub_cat_name = ''
    if guest_sub_id:
        try:
            guest_subcategory_id = int(guest_sub_id)
            gsub = InventoryCategory.query.get(guest_subcategory_id)
            if gsub and gsub.parent_id == int(cat_id):
                guest_sub_cat_name = gsub.name
            else:
                guest_subcategory_id = None
        except (ValueError, TypeError):
            guest_subcategory_id = None

    if has_video_file:
        is_valid, error_msg = validate_video_upload(video_file)
        if not is_valid:
            return _err(f"Video upload error: {error_msg}")
        safe_name = secure_filename(video_file.filename)
        ext = safe_name.rsplit('.', 1)[1].lower() if '.' in safe_name else 'mp4'
        guest_video_filename = f"guest_temp_video_{int(time.time())}_{secrets.token_hex(4)}.{ext}"
        save_path = os.path.join(app.config['TEMP_UPLOAD_FOLDER'], guest_video_filename)
        try:
            video_file.seek(0)
            with open(save_path, 'wb') as f:
                while chunk := video_file.read(8192):
                    f.write(chunk)
        except Exception as vid_error:
            logger.error(f"Guest video save error: {vid_error}", exc_info=True)
            return _err("Error saving video. Please try again.")
    elif temp_video_id:
        guest_video_filename = temp_video_id
    elif category_requires_video(cat_name, guest_sub_cat_name):
        return _err("A video is required for this item category.")

    # Capture referral code from form or existing session
    guest_referral_code = (request.form.get('referral_code') or '').strip() or session.get('referral_code', '')

    session['pending_onboard'] = {
        'category_id': int(cat_id),
        'subcategory_id': guest_subcategory_id,
        'description': desc[:MAX_DESCRIPTION_LENGTH],
        'long_description': long_desc[:MAX_LONG_DESCRIPTION_LENGTH] if long_desc else None,
        'quality': quality_value,
        'suggested_price': suggested_price,
        'collection_method': 'free',
        'referral_code': guest_referral_code,
        'pickup_location_type': session.get('onboard_pickup_location_type'),
        'pickup_dorm': session.get('onboard_pickup_dorm'),
        'pickup_room': session.get('onboard_pickup_room'),
        'pickup_address': session.get('onboard_pickup_address'),
        'pickup_lat': session.get('onboard_pickup_lat'),
        'pickup_lng': session.get('onboard_pickup_lng'),
        'pickup_access_type': session.get('onboard_pickup_access_type'),
        'pickup_floor': session.get('onboard_pickup_floor'),
        'pickup_note': session.get('onboard_pickup_note'),
        'phone': phone_raw[:20] if len(phone_raw) >= 10 else None,
        'payout_method': None,
        'payout_handle': None,
        'photo_filenames': photo_filenames,
        'temp_photo_ids': temp_photo_ids,
        'guest_upload_token': guest_upload_token,
        'video_filename': guest_video_filename,
        'temp_video_id': temp_video_id,
    }
    return _ok()


@app.route('/onboard/complete_account', methods=['GET', 'POST'])
def onboard_complete_account():
    """Create account page shown after guest completes onboarding."""
    if current_user.is_authenticated:
        return redirect(get_user_dashboard())

    if request.method == 'POST':
        _ref_from_session = session.pop('referral_code', None)
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        full_name = request.form.get('full_name', '').strip()
        if not email or not password:
            flash("Email and password are required.", "error")
            return redirect(url_for('onboard_complete_account'))
        existing = User.query.filter_by(email=email).first()
        if existing and existing.password_hash:
            flash("An account with this email already exists. Please log in.", "error")
            return redirect(url_for('login', email=email))
        if existing and not existing.password_hash:
            existing.password_hash = generate_password_hash(password)
            if full_name and not existing.full_name:
                existing.full_name = full_name
            if not existing.referral_code:
                existing.referral_code = generate_unique_referral_code()
            ref_code = request.form.get('referral_code', '').strip() or _ref_from_session
            if not existing.referred_by_id:
                apply_referral_code(existing, ref_code)
            db.session.commit()
            apply_admin_email_if_pending(existing)
            login_user(existing)
            if process_pending_onboard(existing):
                flash("Item submitted! We'll review and price it soon.", "success")
            else:
                flash("Account created!", "success")
            return redirect(get_user_dashboard())
        new_user = User(email=email, full_name=full_name or None,
                        password_hash=generate_password_hash(password))
        db.session.add(new_user)
        db.session.flush()
        new_user.referral_code = generate_unique_referral_code()
        ref_code = request.form.get('referral_code', '').strip() or _ref_from_session
        apply_referral_code(new_user, ref_code)
        db.session.commit()
        apply_admin_email_if_pending(new_user)
        login_user(new_user)
        if process_pending_onboard(new_user):
            flash("Item submitted! We'll review and price it soon.", "success")
        else:
            flash("Account created!", "success")
        return redirect(get_user_dashboard())

    if not session.get('pending_onboard'):
        flash("Your session expired. Please start over.", "info")
        return redirect(url_for('onboard'))
    return render_template('onboard_complete_account.html')


@app.route('/onboard_complete')
def onboard_complete():
    """Success page shown after a new account is created via the onboarding wizard."""
    return render_template('onboard_complete.html')

@app.route('/onboard_cancel')
@login_required
def onboard_cancel():
    """Legacy redirect - no payment at onboarding anymore."""
    return redirect(get_user_dashboard())


@app.route('/confirm_pickup', methods=['GET', 'POST'])
@login_required
def confirm_pickup():
    """Superseded — pickup week is now set from the dashboard modal. Redirect to dashboard."""
    flash("You can set your pickup week from your dashboard.", "info")
    return redirect(url_for('dashboard'))

    # --- LEGACY CODE BELOW (superseded by open-enrollment model — storage units added on demand) ---
    # Free-tier path: any user with approved free items can select pickup window (no payment)
    pending_free = [i for i in current_user.items if i.status == 'pending_logistics' and i.collection_method == 'free']
    free_rejected_ids_str = AppSetting.get('free_rejected_user_ids') or ''
    is_free_rejected = str(current_user.id) in [x.strip() for x in free_rejected_ids_str.split(',') if x.strip()]

    if pending_free and not is_free_rejected:
        # Free path: collect address + phone + pickup week, no payment
        if request.method == 'POST':
            pickup_week = request.form.get('pickup_week')
            if pickup_week not in dict(PICKUP_WEEKS):
                flash("Please select a pickup week.", "error")
                return redirect(url_for('confirm_pickup'))

            # Validate time preference (required)
            pickup_time = request.form.get('pickup_time_preference')
            if pickup_time not in PICKUP_TIME_OPTIONS:
                flash("Please select a preferred time of day.", "error")
                return redirect(url_for('confirm_pickup'))

            # Validate moveout date (optional)
            moveout_raw = request.form.get('moveout_date', '').strip()
            moveout_date = None
            if moveout_raw:
                try:
                    from datetime import date as _date
                    moveout_date = _date.fromisoformat(moveout_raw)
                    week_start, week_end = PICKUP_WEEK_DATE_RANGES[pickup_week]
                    if not (_date.fromisoformat(week_start) <= moveout_date <= _date.fromisoformat(week_end)):
                        flash("Move-out date must fall within your selected pickup week.", "error")
                        return redirect(url_for('confirm_pickup'))
                except (ValueError, KeyError):
                    flash("Invalid move-out date.", "error")
                    return redirect(url_for('confirm_pickup'))

            current_user.pickup_time_preference = pickup_time
            current_user.moveout_date = moveout_date

            # Collect address if not already on file
            location_type = request.form.get('pickup_location_type')
            if not current_user.pickup_location_type:
                if location_type == 'on_campus':
                    dorm = (request.form.get('pickup_dorm') or '').strip()
                    room = (request.form.get('pickup_room') or '').strip()
                    if not dorm or not room:
                        flash("Please select your dorm and room number.", "error")
                        return redirect(url_for('confirm_pickup'))
                    current_user.pickup_location_type = 'on_campus'
                    current_user.pickup_dorm = dorm[:80]
                    current_user.pickup_room = room[:20]
                elif location_type == 'off_campus':
                    address = (request.form.get('pickup_address') or '').strip()
                    if not address:
                        flash("Please enter your address.", "error")
                        return redirect(url_for('confirm_pickup'))
                    current_user.pickup_location_type = 'off_campus'
                    current_user.pickup_address = address[:200]
                    lat = request.form.get('pickup_lat')
                    lng = request.form.get('pickup_lng')
                    current_user.pickup_lat = float(lat) if lat and str(lat).strip() else None
                    current_user.pickup_lng = float(lng) if lng and str(lng).strip() else None
                else:
                    flash("Please select your pickup location.", "error")
                    return redirect(url_for('confirm_pickup'))

            # Collect phone number (required for pickup)
            phone_raw = (request.form.get('phone') or '').replace('(', '').replace(')', '').replace('-', '').replace(' ', '')
            if len(phone_raw) >= 10:
                current_user.phone = phone_raw[:20]
            elif not current_user.phone:
                flash("Please enter a valid 10-digit phone number.", "error")
                return redirect(url_for('confirm_pickup'))
            current_user.pickup_note = (request.form.get('pickup_note') or '').strip()[:200] or None

            # Move free items to available
            for item in pending_free:
                item.pickup_week = pickup_week
                item.status = 'available'
                if item.category:
                    item.category.count_in_stock = (item.category.count_in_stock or 0) + 1
            # Auto-resolve any pickup reminder alerts
            for pa in SellerAlert.query.filter_by(user_id=current_user.id, alert_type='pickup_reminder', resolved=False).all():
                pa.resolved = True
                pa.resolved_at = datetime.utcnow()
            db.session.commit()
            flash("Pickup confirmed! Your items are now live in our inventory.", "success")
            return redirect(url_for('dashboard'))

        return render_template('confirm_pickup.html',
                              pending_items=pending_free,
                              pickup_weeks=PICKUP_WEEKS,
                                                            is_free_confirmed=True,
                              dorms=RESIDENCE_HALLS_BY_STORE.get(get_current_store(), {}),
                              has_pickup_location=current_user.has_pickup_location,
                              google_maps_key=os.environ.get('GOOGLE_MAPS_API_KEY', ''))

    if pending_free and is_free_rejected:
        flash("Pickup slots are full for the free plan. Upgrade to Campus Swap Pickup to secure your spot.", "info")
        return redirect(url_for('dashboard'))

    # Standard paid pickup path
    pending = [i for i in current_user.items if i.status == 'pending_logistics' and i.collection_method == 'online']
    if not pending:
        flash("No items awaiting pickup confirmation.", "info")
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        pickup_week = request.form.get('pickup_week')
        if pickup_week not in dict(PICKUP_WEEKS):
            flash("Please select a pickup week.", "error")
            return redirect(url_for('confirm_pickup'))

        # Validate time preference (required)
        pickup_time = request.form.get('pickup_time_preference')
        if pickup_time not in PICKUP_TIME_OPTIONS:
            flash("Please select a preferred time of day.", "error")
            return redirect(url_for('confirm_pickup'))

        # Validate moveout date (optional)
        moveout_raw = request.form.get('moveout_date', '').strip()
        moveout_date = None
        if moveout_raw:
            try:
                from datetime import date as _date
                moveout_date = _date.fromisoformat(moveout_raw)
                week_start, week_end = PICKUP_WEEK_DATE_RANGES[pickup_week]
                if not (_date.fromisoformat(week_start) <= moveout_date <= _date.fromisoformat(week_end)):
                    flash("Move-out date must fall within your selected pickup week.", "error")
                    return redirect(url_for('confirm_pickup'))
            except (ValueError, KeyError):
                flash("Invalid move-out date.", "error")
                return redirect(url_for('confirm_pickup'))

        current_user.pickup_time_preference = pickup_time
        current_user.moveout_date = moveout_date

        # Save address if not already on file
        if not current_user.has_pickup_location:
            location_type = request.form.get('pickup_location_type')
            if location_type == 'on_campus':
                dorm = (request.form.get('pickup_dorm') or '').strip()
                room = (request.form.get('pickup_room') or '').strip()
                if not dorm or not room:
                    flash("Please select your dorm and enter your room number.", "error")
                    return redirect(url_for('confirm_pickup'))
                current_user.pickup_location_type = 'on_campus'
                current_user.pickup_dorm = dorm[:80]
                current_user.pickup_room = room[:20]
                current_user.pickup_address = None
                current_user.pickup_lat = None
                current_user.pickup_lng = None
            elif location_type == 'off_campus':
                address = (request.form.get('pickup_address') or '').strip()
                if not address:
                    flash("Please enter your address.", "error")
                    return redirect(url_for('confirm_pickup'))
                current_user.pickup_location_type = 'off_campus'
                current_user.pickup_address = address[:200]
                current_user.pickup_dorm = None
                current_user.pickup_room = None
                lat = request.form.get('pickup_lat')
                lng = request.form.get('pickup_lng')
                current_user.pickup_lat = float(lat) if lat and str(lat).strip() else None
                current_user.pickup_lng = float(lng) if lng and str(lng).strip() else None
            else:
                flash("Please select your pickup location.", "error")
                return redirect(url_for('confirm_pickup'))
            phone_raw = (request.form.get('phone') or '').replace('(','').replace(')','').replace('-','').replace(' ','')
            if len(phone_raw) >= 10:
                current_user.phone = phone_raw[:20]
            current_user.pickup_note = (request.form.get('pickup_note') or '').strip()[:200] or None
            db.session.commit()

        if not stripe.api_key:
            flash("Payment is not configured. Please contact support.", "error")
            return redirect(url_for('confirm_pickup'))

        try:
            item_ids = ','.join(str(i.id) for i in pending)
            checkout_session = stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=[{
                    'price_data': {
                        'currency': 'usd',
                        'product_data': {
                            'name': 'Campus Swap Pickup - Service Fee',
                            'description': f"Pickup week: {dict(PICKUP_WEEKS).get(pickup_week, pickup_week)}",
                        },
                        'unit_amount': SERVICE_FEE_CENTS,
                    },
                    'quantity': 1,
                }],
                mode='payment',
                metadata={
                    'type': 'confirm_pickup',
                    'item_ids': item_ids,
                    'pickup_week': pickup_week,
                    'user_id': str(current_user.id),
                },
                success_url=url_for('confirm_pickup_success', _external=True) + '?session_id={CHECKOUT_SESSION_ID}',
                cancel_url=url_for('confirm_pickup', _external=True),
            )
            return redirect(checkout_session.url, code=303)
        except stripe.error.StripeError as e:
            logger.error(f"Confirm pickup Stripe error: {e}", exc_info=True)
            flash("Payment setup failed. Please try again.", "error")
            return redirect(url_for('confirm_pickup'))

    return render_template('confirm_pickup.html',
                          pending_items=pending,
                          pickup_weeks=PICKUP_WEEKS,
                                                    is_free_confirmed=False,
                          dorms=RESIDENCE_HALLS_BY_STORE.get(get_current_store(), {}),
                          has_pickup_location=current_user.has_pickup_location,
                          google_maps_key=os.environ.get('GOOGLE_MAPS_API_KEY', ''))


@app.route('/confirm_pickup_success')
@login_required
def confirm_pickup_success():
    """After Stripe payment for $15 service fee. Move all pending items to available."""
    session_id = request.args.get('session_id')
    if not session_id:
        return redirect(get_user_dashboard())
    try:
        stripe_session = stripe.checkout.Session.retrieve(session_id)
        if stripe_session.metadata.get('type') == 'confirm_pickup' and stripe_session.payment_status == 'paid':
            item_ids_str = stripe_session.metadata.get('item_ids', '')
            pickup_week = stripe_session.metadata.get('pickup_week', '')
            if item_ids_str and pickup_week:
                item_ids = [int(x.strip()) for x in item_ids_str.split(',') if x.strip()]
                items = [InventoryItem.query.get(iid) for iid in item_ids]
                items = [i for i in items if i and i.seller_id == current_user.id and i.status == 'pending_logistics']
                for item in items:
                    item.pickup_week = pickup_week
                    item.status = 'available'
                    if item.category:
                        item.category.count_in_stock = (item.category.count_in_stock or 0) + 1
                current_user.has_paid = True
                # Auto-resolve pickup reminder alerts
                for pa in SellerAlert.query.filter_by(user_id=current_user.id, alert_type='pickup_reminder', resolved=False).all():
                    pa.resolved = True
                    pa.resolved_at = datetime.utcnow()
                db.session.commit()
    except Exception as e:
        logger.error(f"confirm_pickup_success error: {e}", exc_info=True)
    flash("Pickup confirmed! Your items are now live.", "success")
    return redirect(get_user_dashboard())


@app.route('/upgrade_pickup', methods=['GET', 'POST'])
@login_required
def upgrade_pickup():
    """Legacy Pro upgrade flow — retired. Redirects to dashboard."""
    flash("The pickup upgrade is no longer available. Your payout rate is now based on your referral count.", "info")
    return redirect(url_for('dashboard'))


@app.route('/upgrade_pickup_success')
@login_required
def upgrade_pickup_success():
    """Legacy pickup upgrade success page — retired. Redirects to dashboard."""
    flash("That page is no longer active.", "info")
    return redirect(url_for('dashboard'))


@app.route('/upgrade_payout_boost', methods=['POST'])
@login_required
def upgrade_payout_boost():
    """Create a Stripe Checkout Session for the $15 payout boost (+30%).

    Guards (checked server-side regardless of template visibility):
    1. has_paid_boost must be False — already purchased this season.
    2. payout_rate must be < 100 — already at ceiling.
    """
    if current_user.has_paid_boost:
        flash("You've already purchased the payout boost this season.", "info")
        return redirect(url_for('dashboard'))
    if current_user.payout_rate >= 100:
        flash("You're already at 100% — nothing to boost!", "info")
        return redirect(url_for('dashboard'))
    try:
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'usd',
                    'unit_amount': 1500,
                    'product_data': {
                        'name': 'Payout Boost',
                        'description': '+30% added to your Campus Swap payout rate',
                    },
                },
                'quantity': 1,
            }],
            mode='payment',
            metadata={
                'type': 'payout_boost',
                'user_id': str(current_user.id),
                'boost_amount': '30',
                'rate_at_purchase': str(current_user.payout_rate),
            },
            success_url=url_for('upgrade_boost_success', _external=True),
            cancel_url=url_for('dashboard', _external=True),
        )
        return redirect(checkout_session.url, code=303)
    except stripe.error.StripeError as e:
        logger.error(f"upgrade_payout_boost Stripe error: {e}", exc_info=True)
        flash("Payment setup failed. Please try again.", "error")
        return redirect(url_for('dashboard'))
    except Exception as e:
        logger.error(f"upgrade_payout_boost error: {e}", exc_info=True)
        flash("Payment setup failed. Please try again.", "error")
        return redirect(url_for('dashboard'))


@app.route('/upgrade_boost_success')
@login_required
def upgrade_boost_success():
    """Post-payment success page. Shows seller their current payout rate."""
    return render_template('upgrade_boost_success.html')


@app.route('/add_item', methods=['GET', 'POST'])
@login_required
def add_item():
    # First-time sellers (0 items) go to onboarding wizard
    if len(current_user.items) == 0:
        return redirect(url_for('onboard'))

    # Block item uploads when pickup period is closed
    if not get_pickup_period_active():
        flash("Pickup period has ended. Items can no longer be added. Check back next year!", "error")
        return redirect(get_user_dashboard())
    
    # Block users whose card was declined until they add a valid card
    if current_user.payment_declined:
        flash("Your payment was declined. Please add a valid payment method to continue.", "error")
        return redirect(url_for('add_payment_method'))
    
    categories = InventoryCategory.query.filter_by(parent_id=None).order_by(InventoryCategory.id).all()
    category_price_ranges = {cat.id: get_price_range_for_category(cat.name) for cat in categories}
    for sc in InventoryCategory.query.filter(InventoryCategory.parent_id.isnot(None)).all():
        category_price_ranges[sc.id] = get_price_range_for_category(sc.name)

    # Check if categories exist - if not, show error
    if not categories:
        flash("No categories available. Please contact an administrator.", "error")
        logger.error("No categories found in database - item submission blocked")
        return redirect(get_user_dashboard())

    if request.method == 'POST':
        cat_id = request.form.get('category_id')
        desc = request.form.get('description')
        long_desc = request.form.get('long_description')
        quality = request.form.get('quality')
        suggested_price_raw = request.form.get('suggested_price', '').strip()
        files = request.files.getlist('photos')
        temp_photo_ids_raw = request.form.get('temp_photo_ids', '')
        temp_photo_ids = [x.strip() for x in temp_photo_ids_raw.split(',') if x.strip()]
        
        has_files = files and files[0].filename and files[0].filename != ''
        has_temp_photos = len(temp_photo_ids) > 0

        # Mattress photo exemption — check category name before photo validation
        try:
            _cat_early = InventoryCategory.query.get(int(cat_id)) if cat_id else None
            is_mattress = _cat_early is not None and _cat_early.name.lower() == 'mattress'
        except (ValueError, TypeError):
            is_mattress = False
        if is_mattress and request.form.get('mattress_condition_acknowledged') != '1':
            flash("Please confirm the mattress condition policy.", "error")
            return render_template('add_item.html', categories=categories, category_price_ranges=category_price_ranges)

        if not is_mattress and not has_files and not has_temp_photos:
            flash("Please add at least one photo.", "error")
            return render_template('add_item.html', categories=categories, category_price_ranges=category_price_ranges)

        # Validate category_id
        if not cat_id:
            flash("Please select a category.", "error")
            return render_template('add_item.html', categories=categories, category_price_ranges=category_price_ranges)
        
        try:
            cat_id = int(cat_id)
        except (ValueError, TypeError):
            flash("Invalid category selected.", "error")
            return render_template('add_item.html', categories=categories, category_price_ranges=category_price_ranges)
        
        # Verify category exists
        category = InventoryCategory.query.get(cat_id)
        if not category:
            flash("Selected category does not exist. Please select a valid category.", "error")
            logger.error(f"Invalid category_id {cat_id} submitted - category not found")
            return render_template('add_item.html', categories=categories, category_price_ranges=category_price_ranges)
        
        # Validate inputs
        quality_valid, quality_value = validate_quality(quality)
        if not quality_valid:
            flash(f"Invalid quality: {quality_value}", "error")
            return render_template('add_item.html', categories=categories, category_price_ranges=category_price_ranges)
        
        if len(desc) > MAX_DESCRIPTION_LENGTH:
            flash(f"Description too long (max {MAX_DESCRIPTION_LENGTH} characters)", "error")
            return render_template('add_item.html', categories=categories, category_price_ranges=category_price_ranges)
        
        if long_desc and len(long_desc) > MAX_LONG_DESCRIPTION_LENGTH:
            flash(f"Long description too long (max {MAX_LONG_DESCRIPTION_LENGTH} characters)", "error")
            return render_template('add_item.html', categories=categories, category_price_ranges=category_price_ranges)
        
        suggested_price = None
        if suggested_price_raw:
            try:
                sp = float(suggested_price_raw)
                if sp >= 0:
                    suggested_price = sp
            except ValueError:
                pass

        # Subcategory validation
        sub_id_raw = request.form.get('subcategory_id')
        subcategory_id = None
        if sub_id_raw:
            try:
                subcategory_id = int(sub_id_raw)
                sub_cat = InventoryCategory.query.get(subcategory_id)
                if not sub_cat or sub_cat.parent_id != cat_id:
                    subcategory_id = None
            except (ValueError, TypeError):
                subcategory_id = None

        # Use same collection method as user's other items (from onboarding choice)
        existing = [i.collection_method for i in current_user.items if i.collection_method]
        collection_method = existing[-1] if existing else 'online'
        new_item = InventoryItem(
            seller_id=current_user.id, category_id=cat_id, description=desc,
            long_description=long_desc, quality=quality_value, status="pending_valuation", photo_url="",
            collection_method=collection_method,
            suggested_price=suggested_price,
            subcategory_id=subcategory_id,
        )
        db.session.add(new_item)
        db.session.flush()
        
        cover_set = False
        photo_index = 0
        
        # Process files from desktop
        if has_files:
            for file in files:
                if file.filename:
                    # Validate file upload
                    is_valid, error_msg = validate_file_upload(file)
                    if not is_valid:
                        db.session.rollback()
                        flash(f"File upload error: {error_msg}", "error")
                        return render_template('add_item.html', categories=categories, category_price_ranges=category_price_ranges)
                    
                    filename = f"item_{new_item.id}_{int(time.time())}_{photo_index}.jpg"
                    try:
                        photo_storage.save_photo(file, filename)
                        if not cover_set:
                            new_item.photo_url = filename
                            cover_set = True
                        db.session.add(ItemPhoto(item_id=new_item.id, photo_url=filename))
                        photo_index += 1
                    except Exception as img_error:
                        db.session.rollback()
                        logger.error(f"Error processing image: {img_error}", exc_info=True)
                        flash("Error processing image. Please try again.", "error")
                        return render_template('add_item.html', categories=categories, category_price_ranges=category_price_ranges)
        
        # Process temp photos from phone (QR upload)
        if has_temp_photos:
            temp_folder = app.config['TEMP_UPLOAD_FOLDER']
            for temp_fn in temp_photo_ids:
                temp_rec = TempUpload.query.filter(
                    TempUpload.filename == temp_fn,
                    TempUpload.session_token.in_(
                        db.session.query(UploadSession.session_token).filter(UploadSession.user_id == current_user.id)
                    )
                ).first()
                if not temp_rec:
                    db.session.rollback()
                    flash("Invalid or expired photo from phone. Please try again.", "error")
                    return render_template('add_item.html', categories=categories, category_price_ranges=category_price_ranges)
                old_path = os.path.join(temp_folder, temp_fn)
                if not os.path.exists(old_path):
                    db.session.rollback()
                    flash("Photo from phone no longer available. Please re-upload.", "error")
                    return render_template('add_item.html', categories=categories, category_price_ranges=category_price_ranges)
                new_filename = f"item_{new_item.id}_{int(time.time())}_{photo_index}.jpg"
                try:
                    photo_storage.save_photo_from_path(old_path, new_filename)
                    os.remove(old_path)
                except OSError:
                    pass
                if not cover_set:
                    new_item.photo_url = new_filename
                    cover_set = True
                db.session.add(ItemPhoto(item_id=new_item.id, photo_url=new_filename))
                db.session.delete(temp_rec)
                photo_index += 1

        # --- VIDEO HANDLING (add_item) ---
        video_file = request.files.get('video')
        temp_video_id = (request.form.get('temp_video_id') or '').strip()
        has_video_file = video_file and video_file.filename and video_file.filename != ''
        cat_name = category.name if category else ''
        add_sub_cat_name = sub_cat.name if subcategory_id and sub_cat else ''

        if has_video_file:
            is_valid, error_msg = validate_video_upload(video_file)
            if not is_valid:
                db.session.rollback()
                flash(f"Video upload error: {error_msg}", "error")
                return render_template('add_item.html', categories=categories, category_price_ranges=category_price_ranges)
            safe_name = secure_filename(video_file.filename)
            ext = safe_name.rsplit('.', 1)[1].lower() if '.' in safe_name else 'mp4'
            video_key = f"video_{new_item.id}_{int(time.time())}.{ext}"
            try:
                photo_storage.save_video(video_file, video_key)
                new_item.video_url = video_key
            except Exception as vid_error:
                db.session.rollback()
                logger.error(f"Video save error: {vid_error}", exc_info=True)
                flash("Error saving video. Please try again.", "error")
                return render_template('add_item.html', categories=categories, category_price_ranges=category_price_ranges)
        elif temp_video_id:
            temp_rec = TempUpload.query.filter(
                TempUpload.filename == temp_video_id,
                TempUpload.session_token.in_(
                    db.session.query(UploadSession.session_token).filter(UploadSession.user_id == current_user.id)
                )
            ).first()
            if temp_rec:
                old_path = os.path.join(app.config['TEMP_UPLOAD_FOLDER'], temp_video_id)
                if os.path.exists(old_path):
                    ext = temp_video_id.rsplit('.', 1)[1].lower() if '.' in temp_video_id else 'mp4'
                    video_key = f"video_{new_item.id}_{int(time.time())}.{ext}"
                    try:
                        photo_storage.save_video_from_path(old_path, video_key)
                        new_item.video_url = video_key
                        os.remove(old_path)
                    except OSError:
                        pass
                db.session.delete(temp_rec)
        elif category_requires_video(cat_name, add_sub_cat_name):
            db.session.rollback()
            flash("A video is required for this item category.", "error")
            return render_template('add_item.html', categories=categories, category_price_ranges=category_price_ranges)

        db.session.commit()

        # Trigger AI lookup in background (after commit, never blocks response)
        try:
            trigger_ai_lookup(new_item.id)
        except Exception:
            logger.error(f"Failed to trigger AI lookup for item {new_item.id}", exc_info=True)

        # Send item submission confirmation email
        try:
            submission_content = f"""
            <div style="font-family: sans-serif; padding: 20px; max-width: 500px;">
                <h2 style="color: #166534;">Item Submitted for Review</h2>
                <p>Hi {current_user.full_name or 'there'},</p>
                <p>We've received your item submission: <strong>{desc}</strong></p>
                <div style="background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 8px; padding: 16px; margin: 20px 0;">
                    <p style="margin: 0 0 8px;"><strong>Status:</strong> Pending Review</p>
                    <p style="margin: 0;">Our team will review your item and set a price.</p>
                </div>
                <p>What happens next:</p>
                <ul>
                    <li>Our team reviews your item and photos</li>
                    <li>We set a fair market price</li>
                    <li>You'll receive an email when your item goes live</li>
                    <li>Once live, buyers can purchase your item</li>
                </ul>
                <p>You can track your item's status in your <a href="{url_for('dashboard', _external=True)}">dashboard</a>.</p>
                <p>Thanks for selling with Campus Swap!</p>
            </div>
            """
            send_email(
                current_user.email,
                "Item Submitted for Review - Campus Swap",
                submission_content
            )
        except Exception as email_error:
            logger.error(f"Failed to send item submission email: {email_error}")

        flash("Item drafted! Complete your activation to list it.", "success")
        return redirect(get_user_dashboard())
            
    return render_template('add_item.html', categories=categories, category_price_ranges=category_price_ranges)

# =========================================================
# SECTION: ADMIN DATABASE MANAGEMENT
# =========================================================

@app.route('/admin/category/add', methods=['POST'])
@login_required
def admin_add_category():
    """Add a new category (super admin only)"""
    if (r := require_super_admin()):
        return r
    if not current_user.is_admin:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': "Access denied."}), 403
        flash("Access denied.", "error")
        return redirect(url_for('index'))
    
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    name = request.form.get('name', '').strip()
    icon = request.form.get('icon', 'fa-box').strip()
    
    if not name:
        if is_ajax:
            return jsonify({'success': False, 'message': "Category name is required."}), 400
        flash("Category name is required.", "error")
        return redirect(url_for('admin_panel') + '#categories')
    
    # Check if category already exists
    existing = InventoryCategory.query.filter_by(name=name).first()
    if existing:
        if is_ajax:
            return jsonify({'success': False, 'message': f"Category '{name}' already exists."}), 400
        flash(f"Category '{name}' already exists.", "error")
        return redirect(url_for('admin_panel') + '#categories')
    
    new_category = InventoryCategory(name=name, image_url=icon, count_in_stock=0)
    db.session.add(new_category)
    db.session.commit()
    
    if is_ajax:
        return jsonify({'success': True, 'message': f"Category '{name}' added successfully!", 'reload': True})
    flash(f"Category '{name}' added successfully!", "success")
    return redirect(url_for('admin_panel') + '#categories')

@app.route('/admin/category/edit/<int:cat_id>', methods=['POST'])
@login_required
def admin_edit_category(cat_id):
    """Edit an existing category (super admin only)"""
    if (r := require_super_admin()):
        return r
    if not current_user.is_admin:
        flash("Access denied.", "error")
        return redirect(url_for('index'))
    
    category = InventoryCategory.query.get_or_404(cat_id)
    name = request.form.get('name', '').strip()
    icon = request.form.get('icon', '').strip()
    
    if not name:
        flash("Category name is required.", "error")
        return redirect(url_for('admin_panel') + '#categories')
    
    # Check if another category has this name
    existing = InventoryCategory.query.filter(InventoryCategory.name == name, InventoryCategory.id != cat_id).first()
    if existing:
        flash(f"Category '{name}' already exists.", "error")
        return redirect(url_for('admin_panel') + '#categories')
    
    category.name = name
    if icon:
        category.image_url = icon
    db.session.commit()
    
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    if is_ajax:
        return jsonify({'success': True, 'message': "Category updated successfully!", 'reload': True})
    flash(f"Category updated successfully!", "success")
    return redirect(url_for('admin_panel') + '#categories')

@app.route('/admin/category/bulk-update', methods=['POST'])
@login_required
def admin_bulk_update_categories():
    """Bulk update multiple categories at once (super admin only)"""
    if (r := require_super_admin()):
        return r
    if not current_user.is_admin:
        flash("Access denied.", "error")
        return redirect(url_for('index'))
    
    updated_count = 0
    errors = []
    
    # Process all category updates
    for key, value in request.form.items():
        if key.startswith('cat_name_'):
            cat_id = int(key.replace('cat_name_', ''))
            new_name = value.strip()
            icon_key = f'cat_icon_{cat_id}'
            new_icon = request.form.get(icon_key, '').strip()
            
            if not new_name:
                errors.append(f"Category ID {cat_id}: Name cannot be empty.")
                continue
            
            category = InventoryCategory.query.get(cat_id)
            if not category:
                errors.append(f"Category ID {cat_id}: Not found.")
                continue
            
            # Check if another category has this name
            existing = InventoryCategory.query.filter(
                InventoryCategory.name == new_name, 
                InventoryCategory.id != cat_id
            ).first()
            if existing:
                errors.append(f"Category '{new_name}' already exists.")
                continue
            
            # Update category
            category.name = new_name
            if new_icon:
                category.image_url = new_icon
            updated_count += 1
    
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    try:
        db.session.commit()
        if updated_count > 0:
            if is_ajax:
                return jsonify({
                    'success': True, 
                    'message': f"Updated {updated_count} categor{'y' if updated_count == 1 else 'ies'} successfully!",
                    'reload': True
                })
            flash(f"Updated {updated_count} categor{'y' if updated_count == 1 else 'ies'} successfully!", "success")
        if errors:
            if is_ajax:
                return jsonify({'success': False, 'message': '; '.join(errors)}), 400
            for error in errors:
                flash(error, "error")
    except Exception as e:
        db.session.rollback()
        error_msg = f"Error updating categories: {str(e)}"
        if is_ajax:
            return jsonify({'success': False, 'message': error_msg}), 500
        flash(error_msg, "error")
    
    if not is_ajax:
        return redirect(url_for('admin_panel') + '#categories')

@app.route('/admin/category/delete/<int:cat_id>', methods=['POST'])
@login_required
def admin_delete_category(cat_id):
    """Delete a category (only if no items use it) (super admin only)"""
    if (r := require_super_admin()):
        return r
    if not current_user.is_admin:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': "Access denied."}), 403
        flash("Access denied.", "error")
        return redirect(url_for('index'))
    
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    category = InventoryCategory.query.get_or_404(cat_id)
    
    # Check if category has items
    item_count = InventoryItem.query.filter_by(category_id=cat_id).count()
    if item_count > 0:
        error_msg = f"Cannot delete category '{category.name}' - it has {item_count} item(s). Please reassign or delete items first."
        if is_ajax:
            return jsonify({'success': False, 'message': error_msg}), 400
        flash(error_msg, "error")
        return redirect(url_for('admin_panel') + '#categories')
    
    cat_name = category.name
    db.session.delete(category)
    db.session.commit()
    
    if is_ajax:
        return jsonify({'success': True, 'message': f"Category '{cat_name}' deleted successfully!", 'reload': True})
    flash(f"Category '{cat_name}' deleted successfully!", "success")
    return redirect(url_for('admin_panel') + '#categories')


# =========================================================
# SECTION: SUBCATEGORY API & ADMIN ROUTES
# =========================================================

@app.route('/api/subcategories/<int:parent_id>')
def api_subcategories(parent_id):
    """Return JSON list of subcategories for a parent category."""
    parent = InventoryCategory.query.get_or_404(parent_id)
    subs = InventoryCategory.query.filter_by(parent_id=parent_id).order_by(InventoryCategory.id).all()
    skip = len(subs) == 0 or (len(subs) == 1)
    return jsonify({
        'subcategories': [{'id': s.id, 'name': s.name} for s in subs],
        'skip_subcategory': skip,
        'auto_select_id': subs[0].id if len(subs) == 1 else None,
    })


@app.route('/admin/category/add-subcategory', methods=['POST'])
@login_required
def admin_add_subcategory():
    """Add a new subcategory under a parent (super admin only)."""
    if (r := require_super_admin()):
        return r
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    parent_id = request.form.get('parent_id', type=int)
    name = request.form.get('name', '').strip()
    if not parent_id or not name:
        msg = "Parent category and name are required."
        if is_ajax:
            return jsonify({'success': False, 'message': msg}), 400
        flash(msg, "error")
        return redirect(url_for('admin_panel') + '#categories')
    parent = InventoryCategory.query.get(parent_id)
    if not parent or parent.parent_id is not None:
        msg = "Invalid parent category."
        if is_ajax:
            return jsonify({'success': False, 'message': msg}), 400
        flash(msg, "error")
        return redirect(url_for('admin_panel') + '#categories')
    existing = InventoryCategory.query.filter_by(name=name, parent_id=parent_id).first()
    if existing:
        msg = f"Subcategory '{name}' already exists under {parent.name}."
        if is_ajax:
            return jsonify({'success': False, 'message': msg}), 400
        flash(msg, "error")
        return redirect(url_for('admin_panel') + '#categories')
    sub = InventoryCategory(name=name, parent_id=parent_id, count_in_stock=0)
    db.session.add(sub)
    db.session.commit()
    if is_ajax:
        return jsonify({'success': True, 'message': f"Subcategory '{name}' added.", 'reload': True})
    flash(f"Subcategory '{name}' added to {parent.name}.", "success")
    return redirect(url_for('admin_panel') + '#categories')


@app.route('/admin/category/edit-subcategory/<int:sub_id>', methods=['POST'])
@login_required
def admin_edit_subcategory(sub_id):
    """Rename a subcategory (super admin only)."""
    if (r := require_super_admin()):
        return r
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    sub = InventoryCategory.query.get_or_404(sub_id)
    if sub.parent_id is None:
        msg = "Not a subcategory."
        if is_ajax:
            return jsonify({'success': False, 'message': msg}), 400
        flash(msg, "error")
        return redirect(url_for('admin_panel') + '#categories')
    name = request.form.get('name', '').strip()
    if not name:
        msg = "Name is required."
        if is_ajax:
            return jsonify({'success': False, 'message': msg}), 400
        flash(msg, "error")
        return redirect(url_for('admin_panel') + '#categories')
    sub.name = name
    db.session.commit()
    if is_ajax:
        return jsonify({'success': True, 'message': f"Subcategory renamed to '{name}'.", 'reload': True})
    flash(f"Subcategory renamed to '{name}'.", "success")
    return redirect(url_for('admin_panel') + '#categories')


@app.route('/admin/category/delete-subcategory/<int:sub_id>', methods=['POST'])
@login_required
def admin_delete_subcategory(sub_id):
    """Delete a subcategory if no items reference it (super admin only)."""
    if (r := require_super_admin()):
        return r
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    sub = InventoryCategory.query.get_or_404(sub_id)
    if sub.parent_id is None:
        msg = "Not a subcategory."
        if is_ajax:
            return jsonify({'success': False, 'message': msg}), 400
        flash(msg, "error")
        return redirect(url_for('admin_panel') + '#categories')
    item_count = InventoryItem.query.filter_by(subcategory_id=sub_id).count()
    if item_count > 0:
        msg = f"Cannot delete '{sub.name}' — {item_count} item(s) use it."
        if is_ajax:
            return jsonify({'success': False, 'message': msg}), 400
        flash(msg, "error")
        return redirect(url_for('admin_panel') + '#categories')
    sub_name = sub.name
    db.session.delete(sub)
    db.session.commit()
    if is_ajax:
        return jsonify({'success': True, 'message': f"Subcategory '{sub_name}' deleted.", 'reload': True})
    flash(f"Subcategory '{sub_name}' deleted.", "success")
    return redirect(url_for('admin_panel') + '#categories')


@app.route('/admin/user/delete/<int:user_id>', methods=['POST'])
@login_required
def admin_delete_user(user_id):
    """Delete a user account and all related data. Super admin only."""
    if (r := require_super_admin()):
        return r
    if not current_user.is_admin:
        flash("Access denied.", "error")
        return redirect(url_for('index'))

    user = User.query.get(user_id)
    if not user:
        flash("User not found.", "error")
        return redirect(url_for('admin_sellers'))

    if user_id == current_user.id:
        flash("You cannot delete your own account.", "error")
        return redirect(url_for('admin_sellers'))

    if user.is_admin and User.query.filter_by(is_admin=True).count() == 1:
        flash("Cannot delete the last admin account.", "error")
        return redirect(url_for('admin_sellers'))

    try:
        # 1. Delete user's items (and their photo files)
        for item in list(user.items):
            if item.status == 'available':
                cat = InventoryCategory.query.get(item.category_id)
                if cat and cat.count_in_stock > 0:
                    cat.count_in_stock -= 1
            photo_filenames = []
            if item.photo_url:
                photo_filenames.append(item.photo_url)
            for p in item.gallery_photos:
                if p.photo_url:
                    photo_filenames.append(p.photo_url)
            for fn in photo_filenames:
                try:
                    photo_storage.delete_photo(fn)
                except Exception as e:
                    logger.error(f"Error deleting photo file {fn}: {e}", exc_info=True)
            db.session.delete(item)

        # 2. Delete UploadSessions and related TempUploads
        sessions = UploadSession.query.filter_by(user_id=user_id).all()
        session_tokens = [s.session_token for s in sessions]
        for token in session_tokens:
            TempUpload.query.filter_by(session_token=token).delete(synchronize_session=False)
        for s in sessions:
            db.session.delete(s)

        # 3. Delete the user
        user_email = user.email
        db.session.delete(user)
        db.session.commit()

        flash(f"Account for {user_email} has been permanently deleted.", "success")
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting user {user_id}: {e}", exc_info=True)
        flash(f"Could not delete account: {str(e)}", "error")

    return redirect(url_for('admin_sellers'))


@app.route('/admin/item/<int:item_id>/delete', methods=['GET', 'POST'])
@login_required
def admin_delete_item_direct(item_id):
    """Emergency standalone item delete page. Accessible without the main admin dashboard."""
    if not current_user.is_authenticated or not current_user.is_admin:
        flash("Access denied.", "error")
        return redirect(url_for('index'))
    item = InventoryItem.query.options(
        joinedload(InventoryItem.category),
        joinedload(InventoryItem.seller)
    ).get(item_id)
    if not item:
        flash("Item not found.", "error")
        return redirect(url_for('admin_panel'))
    if request.method == 'POST':
        try:
            item_desc = item.description
            if item.status == 'available':
                cat = InventoryCategory.query.get(item.category_id)
                if cat and cat.count_in_stock > 0:
                    cat.count_in_stock -= 1
            for photo in item.gallery_photos[:]:
                db.session.delete(photo)
            db.session.delete(item)
            db.session.commit()
            flash(f"Item '{item_desc}' deleted.", "success")
            ref = request.referrer or ''
            if 'admin/items' in ref:
                return redirect(url_for('admin_items'))
            return redirect(url_for('admin_panel'))
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error deleting item {item_id}: {e}", exc_info=True)
            flash(f"Could not delete item: {str(e)}", "error")
    return render_template_string("""
<!DOCTYPE html><html><head><title>Delete Item</title>
<style>body{font-family:sans-serif;max-width:500px;margin:60px auto;padding:20px;}
.card{border:1px solid #e2e8f0;border-radius:12px;padding:24px;background:#fff;}
h2{color:#166534;margin-bottom:16px;}
.info{margin-bottom:8px;font-size:0.95rem;}
.label{font-weight:600;color:#64748b;}
.btn-delete{background:#dc2626;color:white;border:none;padding:12px 24px;border-radius:8px;font-size:1rem;cursor:pointer;margin-top:16px;}
.btn-cancel{background:#f1f5f9;color:#334155;border:1px solid #cbd5e1;padding:12px 24px;border-radius:8px;font-size:1rem;cursor:pointer;margin-top:16px;margin-right:8px;text-decoration:none;display:inline-block;}
.warning{background:#fef2f2;border:1px solid #fecaca;border-radius:8px;padding:12px;margin-top:16px;color:#991b1b;font-size:0.9rem;}
</style></head><body>
<div class="card">
<h2>Delete Item</h2>
<div class="info"><span class="label">ID:</span> {{ item.id }}</div>
<div class="info"><span class="label">Description:</span> {{ item.description }}</div>
<div class="info"><span class="label">Status:</span> {{ item.status }}</div>
<div class="info"><span class="label">Category:</span> {{ item.category.name if item.category else 'N/A' }}</div>
<div class="info"><span class="label">Seller:</span> {{ item.seller.email if item.seller else 'Admin' }}</div>
<div class="info"><span class="label">Price:</span> {{ ('$%.2f' % item.price) if item.price else 'Not set' }}</div>
<div class="warning">⚠ This will permanently delete the item and all its photos. This cannot be undone.</div>
<form method="POST">
<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
<a href="/admin" class="btn-cancel">Cancel</a>
<button type="submit" class="btn-delete" onclick="return confirm('Delete this item permanently?')">Delete Item</button>
</form>
</div></body></html>
""", item=item)


@app.route('/admin/user/make-admin', methods=['POST'])
@login_required
def admin_make_admin():
    """Grant admin or super admin access by email. Supports pre-assignment for users who haven't signed up yet."""
    if (r := require_super_admin()):
        return r
    email = request.form.get('email', '').strip()
    if not email:
        flash("Please enter an email address.", "error")
        return redirect(url_for('admin_panel') + '#database')
    is_super = request.form.get('super_admin') == 'on'
    email_lower = email.lower()
    user = User.query.filter(func.lower(User.email) == email_lower).first()
    if not user:
        # Pre-assign: add to AdminEmail so they get admin when they sign up
        existing = AdminEmail.query.filter_by(email=email_lower).first()
        if existing:
            existing.is_super_admin = is_super
            db.session.commit()
            flash(f"{email} was already pre-assigned. Updated to {'super admin' if is_super else 'admin'}.", "info")
        else:
            db.session.add(AdminEmail(email=email_lower, is_super_admin=is_super))
            db.session.commit()
            flash(f"Pre-assigned {email}. When they sign up, they will be granted {'super admin' if is_super else 'admin'} access.", "success")
        return redirect(url_for('admin_panel') + '#database')
    if user.is_admin:
        # Allow upgrading admin to super admin
        if is_super and not user.is_super_admin:
            user.is_super_admin = True
            db.session.commit()
            flash(f"Promoted {email} to super admin.", "success")
        else:
            flash(f"{email} is already an admin.", "info")
        return redirect(url_for('admin_panel') + '#database')
    user.is_admin = True
    user.is_super_admin = is_super
    db.session.commit()
    flash(f"Granted {'super admin' if is_super else 'admin'} access to {email}.", "success")
    return redirect(url_for('admin_panel') + '#database')


@app.route('/admin/user/revoke-admin', methods=['POST'])
@login_required
def admin_revoke_admin():
    """Revoke admin access from a user by email. Also removes from AdminEmail if pre-assigned."""
    if (r := require_super_admin()):
        return r
    email = request.form.get('email', '').strip()
    if not email:
        flash("Please enter an email address.", "error")
        return redirect(url_for('admin_panel') + '#database')
    email_lower = email.lower()
    # Remove from AdminEmail if pre-assigned (so future signups don't get admin)
    pending = AdminEmail.query.filter_by(email=email_lower).first()
    if pending:
        db.session.delete(pending)
        db.session.commit()
        flash(f"Removed {email} from pre-assigned admins.", "success")
        return redirect(url_for('admin_panel') + '#database')
    user = User.query.filter(func.lower(User.email) == email_lower).first()
    if not user:
        flash(f"No user found with email '{email}'.", "error")
        return redirect(url_for('admin_panel') + '#database')
    if not user.is_admin:
        flash(f"{email} is not an admin.", "info")
        return redirect(url_for('admin_panel') + '#database')
    if user.id == current_user.id:
        flash("You cannot revoke your own admin access.", "error")
        return redirect(url_for('admin_panel') + '#database')
    if user.is_super_admin and User.query.filter_by(is_super_admin=True).count() <= 1:
        flash("Cannot revoke the last super admin.", "error")
        return redirect(url_for('admin_panel') + '#database')
    user.is_admin = False
    user.is_super_admin = False
    db.session.commit()
    flash(f"Revoked admin access from {email}.", "success")
    return redirect(url_for('admin_panel') + '#database')


@app.route('/admin/preview/users')
@login_required
def admin_preview_users():
    """Preview all users in browser (super admin only)"""
    if (r := require_super_admin()):
        return r
    if not current_user.is_admin:
        flash("Access denied.", "error")
        return redirect(url_for('index'))
    
    users = User.query.order_by(User.date_joined.desc()).all()
    
    # Prepare data for template
    headers = ['Email', 'Full Name', 'Phone', 'Date Joined', 'Has Account', 'Is Seller', 'Has Paid', 'Is Admin', 'Payout Method', 'Payout Handle', 'Actions']
    rows = []
    for user in users:
        rows.append({
            'id': user.id,
            'email': user.email,
            'full_name': user.full_name or '',
            'phone': user.phone or '—',
            'date_joined': user.date_joined.strftime('%Y-%m-%d %H:%M:%S') if user.date_joined else '',
            'has_account': 'Yes' if user.password_hash else 'No (Guest Account)',
            'is_seller': 'Yes' if user.is_seller else 'No',
            'has_paid': 'Yes' if user.has_paid else 'No',
            'is_admin': 'Yes' if user.is_admin else 'No',
            'payout_method': user.payout_method or '',
            'payout_handle': user.payout_handle or '',
            'actions': ''  # Rendered by template for Users Preview
        })
    
    return render_template('data_preview.html', 
                         title='Users Preview',
                         export_url='/admin/export/users',
                         headers=headers,
                         rows=rows,
                         row_keys=['email', 'full_name', 'phone', 'date_joined', 'has_account', 'is_seller', 'has_paid', 'is_admin', 'payout_method', 'payout_handle', 'actions'])

@app.route('/admin/export/users')
@login_required
def admin_export_users():
    """Export all users to CSV (super admin only)"""
    if (r := require_super_admin()):
        return r
    if not current_user.is_admin:
        flash("Access denied.", "error")
        return redirect(url_for('index'))
    
    users = User.query.order_by(User.date_joined.desc()).all()
    
    output = StringIO()
    writer = csv.writer(output)
    
    # Header row
    writer.writerow(['Email', 'Full Name', 'Date Joined', 'Has Account', 'Is Seller', 'Has Paid', 'Is Admin', 'Payout Method', 'Payout Handle', 'Pickup Time Preference', 'Move-Out Date'])

    # Data rows
    for user in users:
        writer.writerow([
            user.email,
            user.full_name or '',
            user.date_joined.strftime('%Y-%m-%d %H:%M:%S') if user.date_joined else '',
            'Yes' if user.password_hash else 'No (Guest Account)',
            'Yes' if user.is_seller else 'No',
            'Yes' if user.has_paid else 'No',
            'Yes' if user.is_admin else 'No',
            user.payout_method or '',
            user.payout_handle or '',
            user.pickup_time_preference or '',
            user.moveout_date.isoformat() if user.moveout_date else ''
        ])
    
    output.seek(0)
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = f'attachment; filename=campus_swap_users_{datetime.utcnow().strftime("%Y%m%d")}.csv'
    return response

@app.route('/admin/preview/items')
@login_required
def admin_preview_items():
    """Preview all items in browser (super admin only)"""
    if (r := require_super_admin()):
        return r
    if not current_user.is_admin:
        flash("Access denied.", "error")
        return redirect(url_for('index'))
    
    items = InventoryItem.query.order_by(InventoryItem.date_added.desc()).all()
    
    # Prepare data for template
    headers = ['ID', 'Description', 'Category', 'Price', 'Condition', 'Status', 'Collection Method', 'Seller Email', 'Seller Name', 'Date Added', 'Sold At', 'Payout Sent']
    rows = []
    for item in items:
        seller_email = item.seller.email if item.seller else ''
        seller_name = item.seller.full_name if item.seller else ''
        category_name = item.category.name if item.category else ''
        
        rows.append({
            'id': item.id,
            'description': item.description,
            'category': category_name,
            'price': f"${item.price:.2f}" if item.price else '',
            'quality': quality_to_label(item.quality),
            'status': item.status,
            'collection_method': item.collection_method,
            'seller_email': seller_email,
            'seller_name': seller_name,
            'date_added': item.date_added.strftime('%Y-%m-%d %H:%M:%S') if item.date_added else '',
            'sold_at': item.sold_at.strftime('%Y-%m-%d %H:%M:%S') if item.sold_at else '',
            'payout_sent': 'Yes' if item.payout_sent else 'No'
        })
    
    return render_template('data_preview.html', 
                         title='Items Preview',
                         export_url='/admin/export/items',
                         headers=headers,
                         rows=rows,
                         row_keys=['id', 'description', 'category', 'price', 'quality', 'status', 'collection_method', 'seller_email', 'seller_name', 'date_added', 'sold_at', 'payout_sent'])

@app.route('/admin/export/items')
@login_required
def admin_export_items():
    """Export all items to CSV (super admin only)"""
    if (r := require_super_admin()):
        return r
    if not current_user.is_admin:
        flash("Access denied.", "error")
        return redirect(url_for('index'))
    
    items = InventoryItem.query.order_by(InventoryItem.date_added.desc()).all()
    
    output = StringIO()
    writer = csv.writer(output)
    
    # Header row
    writer.writerow(['ID', 'Description', 'Category', 'Price', 'Condition', 'Status', 'Collection Method', 'Seller Email', 'Seller Name', 'Date Added', 'Sold At', 'Payout Sent'])
    
    # Data rows
    for item in items:
        seller_email = item.seller.email if item.seller else ''
        seller_name = item.seller.full_name if item.seller else ''
        category_name = item.category.name if item.category else ''
        
        writer.writerow([
            item.id,
            item.description,
            category_name,
            item.price or '',
            quality_to_label(item.quality),
            item.status,
            item.collection_method,
            seller_email,
            seller_name,
            item.date_added.strftime('%Y-%m-%d %H:%M:%S') if item.date_added else '',
            item.sold_at.strftime('%Y-%m-%d %H:%M:%S') if item.sold_at else '',
            'Yes' if item.payout_sent else 'No'
        ])
    
    output.seek(0)
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = f'attachment; filename=campus_swap_items_{datetime.utcnow().strftime("%Y%m%d")}.csv'
    return response

@app.route('/admin/preview/sales')
@login_required
def admin_preview_sales():
    """Preview sales data in browser (super admin only)"""
    if (r := require_super_admin()):
        return r
    if not current_user.is_admin:
        flash("Access denied.", "error")
        return redirect(url_for('index'))
    
    sold_items = InventoryItem.query.filter_by(status='sold').order_by(InventoryItem.sold_at.desc()).all()
    
    # Prepare data for template (payout % varies: online 50%, in-person 33%)
    headers = ['Item ID', 'Description', 'Sale Price', 'Payout Amount', 'Seller Email', 'Seller Name', 'Payout Method', 'Payout Handle', 'Sold Date', 'Payout Sent']
    rows = []
    total_payout = 0
    for item in sold_items:
        pct = _get_payout_percentage(item)
        payout_amount = (item.price or 0) * pct
        total_payout += payout_amount
        seller_email = item.seller.email if item.seller else ''
        seller_name = item.seller.full_name if item.seller else ''
        payout_method = item.seller.payout_method if item.seller else ''
        payout_handle = item.seller.payout_handle if item.seller else ''
        
        rows.append({
            'id': item.id,
            'description': item.description,
            'sale_price': f"${item.price:.2f}" if item.price else '$0.00',
            'payout_amount': f"${payout_amount:.2f}",
            'seller_email': seller_email,
            'seller_name': seller_name,
            'payout_method': payout_method,
            'payout_handle': payout_handle,
            'sold_date': item.sold_at.strftime('%Y-%m-%d %H:%M:%S') if item.sold_at else '',
            'payout_sent': 'Yes' if item.payout_sent else 'No'
        })
    
    return render_template('data_preview.html', 
                         title='Sales Preview',
                         export_url='/admin/export/sales',
                         headers=headers,
                         rows=rows,
                         row_keys=['id', 'description', 'sale_price', 'payout_amount', 'seller_email', 'seller_name', 'payout_method', 'payout_handle', 'sold_date', 'payout_sent'],
                         total_payout=total_payout)

@app.route('/admin/export/sales')
@login_required
def admin_export_sales():
    """Export sold items with payout information (super admin only)"""
    if (r := require_super_admin()):
        return r
    if not current_user.is_admin:
        flash("Access denied.", "error")
        return redirect(url_for('index'))
    
    sold_items = InventoryItem.query.filter_by(status='sold').order_by(InventoryItem.sold_at.desc()).all()
    
    output = StringIO()
    writer = csv.writer(output)
    
    # Header row (payout % varies: online 50%, in-person 33%)
    writer.writerow(['Item ID', 'Description', 'Sale Price', 'Payout Amount', 'Seller Email', 'Seller Name', 'Payout Method', 'Payout Handle', 'Sold Date', 'Payout Sent'])
    
    # Data rows
    for item in sold_items:
        pct = _get_payout_percentage(item)
        payout_amount = (item.price or 0) * pct
        seller_email = item.seller.email if item.seller else ''
        seller_name = item.seller.full_name if item.seller else ''
        payout_method = item.seller.payout_method if item.seller else ''
        payout_handle = item.seller.payout_handle if item.seller else ''
        
        writer.writerow([
            item.id,
            item.description,
            item.price or 0,
            f"{payout_amount:.2f}",
            seller_email,
            seller_name,
            payout_method,
            payout_handle,
            item.sold_at.strftime('%Y-%m-%d %H:%M:%S') if item.sold_at else '',
            'Yes' if item.payout_sent else 'No'
        ])
    
    output.seek(0)
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = f'attachment; filename=campus_swap_sales_{datetime.utcnow().strftime("%Y%m%d")}.csv'
    return response

@app.route('/admin/export/notify-signups')
@login_required
def admin_export_notify_signups():
    """Export Shop Drop notification signups to CSV (admin only)."""
    if not current_user.is_admin:
        flash("Access denied.", "error")
        return redirect(url_for('index'))

    signups = ShopNotifySignup.query.order_by(ShopNotifySignup.created_at.desc()).all()

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['Email', 'Signed Up At', 'IP Address'])
    for s in signups:
        writer.writerow([
            s.email,
            s.created_at.strftime('%Y-%m-%d %H:%M:%S') if s.created_at else '',
            s.ip_address or '',
        ])

    output.seek(0)
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = (
        f'attachment; filename=shop_notify_signups_{datetime.utcnow().strftime("%Y%m%d")}.csv'
    )
    return response


@app.route('/admin/database/reset', methods=['POST'])
@login_required
def admin_database_reset():
    """Safely reset database - requires confirmation (super admin only)"""
    if (r := require_super_admin()):
        return r
    if not current_user.is_admin:
        flash("Access denied.", "error")
        return redirect(url_for('index'))
    
    confirmation = request.form.get('confirmation', '').strip().lower()
    
    # Require explicit confirmation
    if confirmation != 'reset database':
        flash("Please type 'reset database' to confirm. This action cannot be undone.", "error")
        return redirect(url_for('admin_panel') + '#database')
    
    try:
        # Drop all tables and recreate
        db.drop_all()
        db.create_all()
        
        # Recreate default categories
        default_categories = [
            {"name": "Couch/Sofa", "icon": "fa-couch"},
            {"name": "Mattress", "icon": "fa-bed"},
            {"name": "Mini-Fridge", "icon": "fa-snowflake"},
            {"name": "Climate Control", "icon": "fa-wind"},
            {"name": "Television", "icon": "fa-tv"},
        ]
        
        for cat_data in default_categories:
            category = InventoryCategory(
                name=cat_data["name"],
                image_url=cat_data["icon"],
                count_in_stock=0
            )
            db.session.add(category)
        
        db.session.commit()
        
        flash("Database reset successfully! Default categories have been created.", "success")
        return redirect(url_for('admin_panel'))
        
    except Exception as e:
        db.session.rollback()
        flash(f"Error resetting database: {str(e)}", "error")
        return redirect(url_for('admin_panel') + '#database')

@app.route('/admin/mass-email', methods=['POST'])
@login_required
def admin_mass_email():
    """Send marketing email to all users in database (super admin only)"""
    if (r := require_super_admin()):
        return r
    if not current_user.is_admin:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': "Access denied."}), 403
        flash("Access denied.", "error")
        return redirect(url_for('index'))
    
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    
    subject = request.form.get('subject', '').strip()
    html_content = request.form.get('html_content', '').strip()
    
    if not subject or not html_content:
        error_msg = "Subject and email content are required."
        if is_ajax:
            return jsonify({'success': False, 'message': error_msg}), 400
        flash(error_msg, "error")
        return redirect(url_for('admin_panel') + '#mass-email')
    
    # Get all users with email addresses, excluding unsubscribed users
    users = User.query.filter(
        User.email.isnot(None),
        User.unsubscribed != True  # Filter out unsubscribed users
    ).all()
    total_users = len(users)
    
    if total_users == 0:
        error_msg = "No users found in database (or all users have unsubscribed)."
        if is_ajax:
            return jsonify({'success': False, 'message': error_msg}), 400
        flash(error_msg, "error")
        return redirect(url_for('admin_panel') + '#mass-email')
    
    # Check if Resend API key is configured
    if not resend.api_key:
        error_msg = "RESEND_API_KEY is not configured. Cannot send emails."
        logger.error(f"Mass email error: {error_msg}")
        if is_ajax:
            return jsonify({'success': False, 'message': error_msg}), 500
        flash(error_msg, "error")
        return redirect(url_for('admin_panel') + '#mass-email')
    
    logger.info(f"Starting mass email send to {total_users} users (excluding unsubscribed)")
    logger.info(f"Subject: {subject}")
    
    # Send emails using send_email function (handles unsubscribe links, headers, and filtering automatically)
    sent_count = 0
    failed_count = 0
    failed_emails = []
    
    # Send emails one by one (send_email handles rate limiting internally via Resend)
    # Note: Resend has rate limits, so we add a small delay between sends
    for idx, user in enumerate(users):
        try:
            # send_email automatically:
            # - Checks if user is unsubscribed (double-check)
            # - Generates unsubscribe token if needed
            # - Wraps content in email template
            # - Adds unsubscribe link and headers
            # - Includes plain text version
            success = send_email(
                to_email=user.email,
                subject=subject,
                html_content=html_content,
                is_marketing=True,
                user=user
            )
            
            if success:
                sent_count += 1
            else:
                failed_count += 1
                failed_emails.append(user.email)
            
            # Rate limiting: Resend allows 2 req/s, so wait 0.5s between emails
            # Add small buffer to be safe
            if idx < len(users) - 1:  # Don't wait after last email
                time.sleep(0.55)
                
        except Exception as e:
            error_type = type(e).__name__
            logger.error(f"Error sending email to {user.email} ({error_type}): {str(e)}", exc_info=True)
            failed_count += 1
            failed_emails.append(user.email)
    
    logger.info(f"Mass email complete. Sent: {sent_count}, Failed: {failed_count}, Total: {total_users}")
    
    # Prepare response message
    if sent_count == total_users:
        message = f"Successfully sent email to all {sent_count} users!"
    elif sent_count > 0:
        message = f"Sent to {sent_count} users. {failed_count} failed."
        if failed_emails:
            message += f" Failed emails: {', '.join(failed_emails[:5])}"
            if len(failed_emails) > 5:
                message += f" and {len(failed_emails) - 5} more."
    else:
        message = f"Failed to send emails. Check server logs for details."

    if is_ajax:
        return jsonify({
            'success': sent_count > 0,
            'message': message,
            'sent': sent_count,
            'failed': failed_count,
            'total': total_users
        })
    
    if sent_count > 0:
        flash(message, "success")
    else:
        flash(message, "error")
    
    return redirect(url_for('admin_panel') + '#mass-email')

# =========================================================
# SECTION: CREW / OPS ROUTES
# =========================================================

def require_crew():
    """Returns redirect if current user is not an approved worker. Call at top of crew-only routes."""
    if not current_user.is_authenticated:
        flash("Please log in to access the crew portal.", "error")
        return redirect(url_for('login', next='/crew'))
    if not current_user.is_worker or current_user.worker_status != 'approved':
        if current_user.worker_status == 'pending':
            return redirect(url_for('crew_pending'))
        flash("Access denied.", "error")
        return redirect(url_for('index'))
    return None


def _is_edu_email(email):
    """True if email domain matches crew_allowed_email_domain, or if no domain is configured (open applications)."""
    allowed_domain = (AppSetting.get('crew_allowed_email_domain') or '').strip().lstrip('.')
    if not allowed_domain:
        return True
    email_domain = email.strip().split('@')[-1].lower()
    return email_domain == allowed_domain or email_domain.endswith('.' + allowed_domain)


def _availability_booleans(form):
    """Parse the 14 availability fields from a submitted form into a dict of booleans."""
    fields = [
        'mon_am', 'mon_pm', 'tue_am', 'tue_pm',
        'wed_am', 'wed_pm', 'thu_am', 'thu_pm',
        'fri_am', 'fri_pm', 'sat_am', 'sat_pm',
        'sun_am', 'sun_pm',
    ]
    return {f: form.get(f, 'false').lower() == 'true' for f in fields}


def _availability_as_dict(avail):
    """Convert a WorkerAvailability ORM object to a plain dict for template pre-fill."""
    fields = [
        'mon_am', 'mon_pm', 'tue_am', 'tue_pm',
        'wed_am', 'wed_pm', 'thu_am', 'thu_pm',
        'fri_am', 'fri_pm', 'sat_am', 'sat_pm',
        'sun_am', 'sun_pm',
    ]
    return {f: getattr(avail, f, True) for f in fields}


def _is_availability_open():
    """True if today (Eastern) is Sunday, Monday, or Tuesday — availability submission window."""
    return _now_eastern().weekday() in (6, 0, 1)  # Sun=6, Mon=0, Tue=1


@app.route('/crew/apply', methods=['GET', 'POST'])
def crew_apply():
    """Public worker application page. Gated to .edu emails on POST."""
    # Check if applications are open
    if AppSetting.get('crew_applications_open', 'true') != 'true':
        flash("Applications are currently closed. Check back soon.", "info")
        return redirect(url_for('index'))

    if request.method == 'GET':
        if current_user.is_authenticated:
            if current_user.worker_status == 'approved':
                return redirect(url_for('crew_dashboard'))
            if current_user.worker_status in ('pending', 'rejected'):
                return redirect(url_for('crew_pending'))
        return render_template('crew/apply.html')

    # POST — process application
    full_name = request.form.get('full_name', '').strip()
    email = request.form.get('email', '').strip().lower()
    phone = request.form.get('phone', '').strip()
    unc_year = request.form.get('unc_year', '').strip()
    why_blurb = request.form.get('why_blurb', '').strip()

    # unc.edu enforcement disabled — re-enable before launch by restoring _is_edu_email check

    # Validate required fields
    if not all([full_name, email, phone, unc_year]):
        flash("Please fill in all required fields.", "error")
        return render_template('crew/apply.html', form_data=request.form)

    if len(why_blurb) > 500:
        flash("Optional blurb must be 500 characters or fewer.", "error")
        return render_template('crew/apply.html', form_data=request.form)

    # Find or create user
    user = User.query.filter_by(email=email).first()
    if user:
        # Check for existing application
        if user.worker_status == 'approved':
            flash("You're already an approved crew member!", "info")
            return redirect(url_for('crew_dashboard'))
        if user.worker_status in ('pending', 'rejected'):
            if user.worker_status == 'pending':
                flash("You've already applied. We'll reach out soon.", "error")
            else:
                flash("Applications are closed for this account.", "error")
            return redirect(url_for('index'))
    else:
        # Create new account
        user = User(email=email, full_name=full_name, phone=phone)
        db.session.add(user)
        db.session.flush()

    # Update name/phone if this is a returning user applying fresh
    if current_user.is_authenticated and current_user.id == user.id:
        pass  # pre-filled read-only fields; trust existing values
    else:
        if not user.full_name:
            user.full_name = full_name
        if not user.phone:
            user.phone = phone

    # Mark as pending worker
    user.worker_status = 'pending'

    # Create application record
    application = WorkerApplication(
        user_id=user.id,
        unc_year=unc_year,
        role_pref='both',  # all movers are both; role_pref field no longer collected
        why_blurb=why_blurb or None,
    )
    db.session.add(application)

    # Create initial availability record (week_start=None)
    avail_data = _availability_booleans(request.form)
    availability = WorkerAvailability(user_id=user.id, week_start=None, **avail_data)
    db.session.add(availability)

    db.session.commit()

    # If this was a brand-new user (not logged in), log them in
    if not current_user.is_authenticated:
        login_user(user)

    return redirect(url_for('crew_pending'))


@app.route('/crew/pending')
@login_required
def crew_pending():
    """Holding page shown to applicants while their application is under review."""
    if current_user.worker_status == 'approved':
        return redirect(url_for('crew_dashboard'))
    if current_user.worker_status == 'rejected':
        flash("Your application wasn't selected this time. Thanks for your interest in Campus Swap.", "info")
        return redirect(url_for('index'))
    return render_template('crew/pending.html')


@app.route('/crew')
def crew_dashboard():
    """Approved worker portal — shows role, current availability, schedule card."""
    if (r := require_crew()):
        return r
    last_avail = (
        WorkerAvailability.query
        .filter_by(user_id=current_user.id)
        .order_by(WorkerAvailability.submitted_at.desc())
        .first()
    )
    avail_dict = _availability_as_dict(last_avail) if last_avail else None

    # Schedule context
    current_week = _get_current_published_week()
    _day_order = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']

    # Completed assignments — each role tracked independently via ShiftAssignment.completed_at
    completed_assignments = (
        ShiftAssignment.query
        .filter_by(worker_id=current_user.id)
        .filter(ShiftAssignment.completed_at.isnot(None))
        .join(Shift, ShiftAssignment.shift_id == Shift.id)
        .order_by(ShiftAssignment.completed_at.desc())
        .all()
    )
    completed_shift_role_pairs = {(a.shift_id, a.role_on_shift) for a in completed_assignments}
    completed_shift_ids = {a.shift_id for a in completed_assignments}

    # Build shift history entries for the dashboard card
    completed_entries = []
    for a in completed_assignments:
        shift = a.shift
        shift_date = shift.week.week_start + timedelta(days=_day_order.index(shift.day_of_week))
        completed_entries.append({
            'shift': shift,
            'role': a.role_on_shift,
            'completed_at': a.completed_at,
            'date': shift_date,
        })

    # my_shifts: exclude shifts where THIS worker's role is already marked complete
    my_shifts = []
    if current_week:
        for shift in sorted([s for s in current_week.shifts if s.is_active], key=lambda s: s.sort_key):
            for a in shift.assignments:
                if a.worker_id == current_user.id:
                    if (shift.id, a.role_on_shift) in completed_shift_role_pairs:
                        break  # this role is done — lives in Shift History
                    my_shifts.append((shift, a.role_on_shift))
                    break

    # Find today's shift for the banner — use Eastern time throughout
    _day_map = {0: 'mon', 1: 'tue', 2: 'wed', 3: 'thu', 4: 'fri', 5: 'sat', 6: 'sun'}
    now_et = _now_eastern()
    today_dow = _day_map[now_et.weekday()]
    today_shifts = [(s, r) for s, r in my_shifts if s.day_of_week == today_dow]
    today_shift = None
    today_shift_run = None
    # If a shift is actively in-progress, always surface it — mover must be able to end it
    for shift, _role in today_shifts:
        if shift.run and shift.run.status == 'in_progress':
            today_shift = shift
            today_shift_run = shift.run
            break
    # No in-progress shift: pick by time (Eastern) — before noon prefer AM, at/after noon prefer PM
    if not today_shift:
        prefer_slot = 'pm' if now_et.hour >= 12 else 'am'
        for preferred in (prefer_slot, ('pm' if prefer_slot == 'am' else 'am')):
            for shift, _role in today_shifts:
                if shift.slot == preferred:
                    today_shift = shift
                    today_shift_run = shift.run
                    break
            if today_shift:
                break
    shifts_required = int(AppSetting.get('shifts_required', '10'))

    # Group shifts by day for the dashboard card (one row per day)
    from itertools import groupby as _groupby
    my_shifts_by_day = [
        (day, list(group))
        for day, group in _groupby(my_shifts, key=lambda x: x[0].day_of_week)
    ]

    # Spec #4: organizer context — based on shift-level role, not worker_role
    # True if the worker has an organizer assignment on today's shift
    is_organizer = any(role == 'organizer' for _, role in today_shifts)
    # Unresolved flags raised by this worker across any past shift
    flagged_shift_ids = {
        f.shift_id for f in
        IntakeFlag.query
        .filter_by(organizer_id=current_user.id, resolved=False)
        .all()
    }

    return render_template(
        'crew/dashboard.html',
        avail=avail_dict,
        last_avail=last_avail,
        current_week=current_week,
        my_shifts=my_shifts,
        my_shifts_by_day=my_shifts_by_day,
        today_shift=today_shift,
        today_shift_run=today_shift_run,
        completed_entries=completed_entries,
        shifts_required=shifts_required,
        is_organizer=is_organizer,
        flagged_shift_ids=flagged_shift_ids,
    )


@app.route('/crew/availability', methods=['GET', 'POST'])
def crew_availability():
    """Weekly availability form. Pre-filled from last submission. Locks after Tuesday."""
    if (r := require_crew()):
        return r

    if request.method == 'POST':
        if not _is_availability_open():
            flash("Availability window is closed for this week.", "error")
            return redirect(url_for('crew_availability'))

        avail_data = _availability_booleans(request.form)
        # week_start = Monday of current week (Eastern date)
        today = _today_eastern()
        week_start = today - timedelta(days=today.weekday())

        existing = WorkerAvailability.query.filter_by(
            user_id=current_user.id, week_start=week_start
        ).first()
        if existing:
            for field, val in avail_data.items():
                setattr(existing, field, val)
            existing.submitted_at = datetime.utcnow()
        else:
            record = WorkerAvailability(user_id=current_user.id, week_start=week_start, **avail_data)
            db.session.add(record)
        db.session.commit()
        flash("Availability submitted.", "success")
        return redirect(url_for('crew_dashboard'))

    # GET — pre-fill from last submission
    last_avail = (
        WorkerAvailability.query
        .filter_by(user_id=current_user.id)
        .order_by(WorkerAvailability.submitted_at.desc())
        .first()
    )
    avail_dict = _availability_as_dict(last_avail) if last_avail else None
    window_open = _is_availability_open()
    # Partner preferences for the form
    my_preferred_ids = [
        p.target_user_id for p in WorkerPreference.query.filter_by(
            user_id=current_user.id, preference_type='preferred'
        ).all()
    ]
    my_avoided_ids = [
        p.target_user_id for p in WorkerPreference.query.filter_by(
            user_id=current_user.id, preference_type='avoided'
        ).all()
    ]
    all_workers = User.query.filter_by(is_worker=True, worker_status='approved').filter(
        User.id != current_user.id
    ).order_by(User.full_name).all()
    return render_template(
        'crew/availability.html',
        avail=avail_dict,
        window_open=window_open,
        all_workers=all_workers,
        my_preferred_ids=my_preferred_ids,
        my_avoided_ids=my_avoided_ids,
    )


@app.route('/crew/preferences', methods=['POST'])
@login_required
def crew_save_preferences():
    """Save partner preferences for this worker."""
    if (r := require_crew()):
        return r
    preferred_ids = request.form.getlist('preferred_ids')
    avoided_ids   = request.form.getlist('avoided_ids')

    # Validate: same worker can't be in both lists
    preferred_set = set(preferred_ids)
    avoided_set   = set(avoided_ids)
    overlap = preferred_set & avoided_set
    if overlap:
        flash("A worker can't be in both lists.", "error")
        return redirect(url_for('crew_availability'))

    # Replace all existing preferences for this user
    WorkerPreference.query.filter_by(user_id=current_user.id).delete()
    for wid in preferred_set:
        try:
            wid_int = int(wid)
        except (ValueError, TypeError):
            continue
        db.session.add(WorkerPreference(
            user_id=current_user.id,
            target_user_id=wid_int,
            preference_type='preferred',
        ))
    for wid in avoided_set:
        try:
            wid_int = int(wid)
        except (ValueError, TypeError):
            continue
        db.session.add(WorkerPreference(
            user_id=current_user.id,
            target_user_id=wid_int,
            preference_type='avoided',
        ))
    db.session.commit()
    flash("Preferences saved.", "success")
    return redirect(url_for('crew_availability'))


@app.route('/crew/shift/<int:shift_id>')
@login_required
def crew_shift_view(shift_id):
    """Phone-optimized mover shift view."""
    if (r := _require_mover(shift_id)):
        return r
    shift = Shift.query.get_or_404(shift_id)
    assignment = ShiftAssignment.query.filter_by(
        shift_id=shift.id, worker_id=current_user.id
    ).first()
    if not assignment:
        abort(403)

    # Compute the actual calendar date of this shift (compare in Eastern time)
    _DAY_ORDER = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
    shift_date = shift.week.week_start + timedelta(days=_DAY_ORDER.index(shift.day_of_week))
    today = _today_eastern()
    is_today = (shift_date == today)
    is_past  = (shift_date < today)
    is_future = (shift_date > today)

    # Block access to future shifts — not on the clock yet
    if is_future and not shift.run:
        flash("This shift isn't scheduled until " + shift_date.strftime('%A, %b %-d') + ". Come back then.", "info")
        return redirect(url_for('crew_dashboard'))

    my_truck_number = assignment.truck_number

    # Get pickups for this mover's truck only
    pickup_query = ShiftPickup.query.filter_by(shift_id=shift.id)
    if my_truck_number is not None:
        pickup_query = pickup_query.filter_by(truck_number=my_truck_number)
    all_pickups = pickup_query.order_by(
        nulls_last(ShiftPickup.stop_order.asc()), ShiftPickup.id.asc()
    ).all()

    shift_run = shift.run

    seller_items = {}
    item_counts = {}
    for p in all_pickups:
        items = InventoryItem.query.filter_by(
            seller_id=p.seller_id, status='available'
        ).all()
        seller_items[p.seller_id] = items
        item_counts[p.seller_id] = len(items)

    total_stops = len(all_pickups)
    done_stops = sum(1 for p in all_pickups if p.status in ('completed', 'issue'))

    return render_template(
        'crew/shift.html',
        shift=shift,
        shift_run=shift_run,
        pickups=all_pickups,
        is_today=is_today,
        is_past=is_past,
        seller_items=seller_items,
        item_counts=item_counts,
        total_stops=total_stops,
        done_stops=done_stops,
        shift_date=shift_date,
    )


@app.route('/crew/shift/<int:shift_id>/start', methods=['POST'])
@login_required
def crew_shift_start(shift_id):
    """Create ShiftRun, notify first seller."""
    if (r := _require_mover(shift_id)):
        return r
    shift = Shift.query.get_or_404(shift_id)
    assignment = ShiftAssignment.query.filter_by(
        shift_id=shift.id, worker_id=current_user.id
    ).first()
    if not assignment:
        abort(403)
    _DAY_ORDER = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
    shift_date = shift.week.week_start + timedelta(days=_DAY_ORDER.index(shift.day_of_week))
    today = _today_eastern()
    if shift_date > today:
        flash("You can only start a shift on or after the day it's scheduled.", "error")
        return redirect(url_for('crew_dashboard'))
    if shift.run:
        return redirect(url_for('crew_shift_view', shift_id=shift_id))
    run = ShiftRun(shift_id=shift.id, started_by_id=current_user.id)
    db.session.add(run)
    db.session.commit()
    # Spec #9: SMS every pending seller assigned to this mover's truck
    pending_stops = (
        ShiftPickup.query
        .filter_by(shift_id=shift.id, truck_number=assignment.truck_number, status='pending')
        .order_by(nulls_last(ShiftPickup.stop_order.asc()), ShiftPickup.id.asc())
        .all()
    )
    for stop in pending_stops:
        _send_sms(
            stop.seller,
            "Your Campus Swap pickup crew has started today's route! "
            "We'll text you again when you're up next."
        )
    flash("Shift started — good luck out there!", "success")
    return redirect(url_for('crew_shift_view', shift_id=shift_id))


@app.route('/crew/shift/<int:shift_id>/complete_retroactive', methods=['POST'])
@login_required
def crew_shift_complete_retroactive(shift_id):
    """Mark a past shift complete in one step — creates ShiftRun and immediately closes it."""
    if (r := _require_mover(shift_id)):
        return r
    shift = Shift.query.get_or_404(shift_id)
    assignment = ShiftAssignment.query.filter_by(
        shift_id=shift.id, worker_id=current_user.id
    ).first()
    if not assignment:
        abort(403)
    _DAY_ORDER = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
    shift_date = shift.week.week_start + timedelta(days=_DAY_ORDER.index(shift.day_of_week))
    if shift_date >= _today_eastern():
        flash("Use the normal End Shift flow for today's shifts.", "error")
        return redirect(url_for('crew_shift_view', shift_id=shift_id))
    if not shift.run:
        run = ShiftRun(shift_id=shift.id, started_by_id=current_user.id)
        db.session.add(run)
        db.session.flush()
    else:
        run = shift.run
    run.status = 'completed'
    run.ended_at = datetime.utcnow()
    db.session.commit()
    flash("Shift marked as complete.", "success")
    return redirect(url_for('crew_dashboard'))


@app.route('/crew/shift/<int:shift_id>/stop/<int:pickup_id>/update', methods=['POST'])
@login_required
def crew_shift_stop_update(shift_id, pickup_id):
    """Mark a stop completed or issue."""
    if (r := _require_mover(shift_id)):
        return r
    shift = Shift.query.get_or_404(shift_id)
    assignment = ShiftAssignment.query.filter_by(
        shift_id=shift.id, worker_id=current_user.id
    ).first()
    if not assignment:
        abort(403)
    pickup = ShiftPickup.query.get_or_404(pickup_id)
    if pickup.shift_id != shift.id:
        abort(404)

    new_status = request.form.get('status')
    if new_status not in ('completed', 'issue'):
        flash("Invalid status.", "error")
        return redirect(url_for('crew_shift_view', shift_id=shift_id))

    notes = request.form.get('notes', '').strip()

    pickup.status = new_status
    pickup.completed_at = datetime.utcnow()
    pickup.notes = notes or None

    if new_status == 'completed':
        # Write picked_up_at on seller's available items (do not overwrite if already set)
        items = InventoryItem.query.filter_by(
            seller_id=pickup.seller_id, status='available'
        ).all()
        for item in items:
            if not item.picked_up_at:
                item.picked_up_at = datetime.utcnow()
        # Confirm referral for this seller — stop completion is the trigger, not warehouse arrival
        maybe_confirm_referral_for_seller(pickup.seller)

        # Spec #9: revoke any open reschedule tokens for this pickup
        open_tokens = RescheduleToken.query.filter_by(
            pickup_id=pickup.id, used_at=None, revoked_at=None
        ).all()
        for tok in open_tokens:
            tok.revoked_at = _now_eastern().replace(tzinfo=None)

    elif new_status == 'issue':
        # Spec #9: save issue_type; default 'other' if not supplied (graceful degradation)
        raw_issue_type = request.form.get('issue_type', '').strip()
        pickup.issue_type = raw_issue_type if raw_issue_type in ('no_show', 'other') else 'other'

        if pickup.issue_type == 'no_show':
            # Extend reschedule token TTL so seller has time to rebook
            token = RescheduleToken.query.filter_by(
                pickup_id=pickup.id, used_at=None, revoked_at=None
            ).first()
            if token:
                ttl = int(AppSetting.get('reschedule_token_ttl_days', '7'))
                token.expires_at = (_now_eastern() + timedelta(days=ttl)).replace(tzinfo=None)

    db.session.commit()
    _notify_next_seller(shift, pickup)
    return redirect(url_for('crew_shift_view', shift_id=shift_id))


@app.route('/crew/shift/<int:shift_id>/stop/<int:pickup_id>/revert', methods=['POST'])
@login_required
def crew_shift_stop_revert(shift_id, pickup_id):
    """Revert a resolved stop back to pending so the mover can re-log it."""
    if (r := _require_mover(shift_id)):
        return r
    shift = Shift.query.get_or_404(shift_id)
    assignment = ShiftAssignment.query.filter_by(
        shift_id=shift.id, worker_id=current_user.id
    ).first()
    if not assignment:
        abort(403)
    pickup = ShiftPickup.query.get_or_404(pickup_id)
    if pickup.shift_id != shift.id:
        abort(404)
    pickup.status = 'pending'
    pickup.notes = None
    pickup.completed_at = None
    pickup.issue_type = None  # Spec #9: clear issue type on revert
    # picked_up_at is intentionally left as-is — items were physically collected
    # no_show_email_sent_at intentionally NOT cleared — no duplicate emails if re-flagged
    db.session.commit()
    return redirect(url_for('crew_shift_view', shift_id=shift_id))


@app.route('/crew/shift/<int:shift_id>/end', methods=['POST'])
@login_required
def crew_shift_end(shift_id):
    """Close ShiftRun."""
    if (r := _require_mover(shift_id)):
        return r
    shift = Shift.query.get_or_404(shift_id)
    assignment = ShiftAssignment.query.filter_by(
        shift_id=shift.id, worker_id=current_user.id
    ).first()
    if not assignment:
        abort(403)
    run = shift.run
    if run and run.status == 'in_progress':
        run.status = 'completed'
        run.ended_at = datetime.utcnow()
    # Mark this driver's assignment as individually complete
    if not assignment.completed_at:
        assignment.completed_at = datetime.utcnow()
    db.session.commit()
    flash("Shift complete — great work!", "success")
    return redirect(url_for('crew_dashboard'))


# =========================================================
# SPEC #4 — ORGANIZER INTAKE (Crew routes)
# =========================================================

def _require_organizer():
    """Returns redirect if current user is not an approved crew member."""
    return require_crew()


def _require_mover(shift_id=None):
    """Returns redirect if current user is not an approved crew member.
    The per-shift role (driver vs organizer) is enforced by ShiftAssignment.role_on_shift."""
    return require_crew()


@app.route('/crew/intake/<int:shift_id>')
@login_required
def crew_intake_shift(shift_id):
    """Organizer shift-scoped intake page."""
    if (r := _require_organizer()):
        return r
    shift = Shift.query.get_or_404(shift_id)
    # Block access to future shifts (Eastern date)
    _day_order = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
    shift_date = shift.week.week_start + timedelta(days=_day_order.index(shift.day_of_week))
    if shift_date > _today_eastern():
        flash("Intake is not available for future shifts.", "error")
        return redirect(url_for('crew_dashboard'))
    # Organizer must be assigned to this shift
    assignment = ShiftAssignment.query.filter_by(
        shift_id=shift.id, worker_id=current_user.id, role_on_shift='organizer'
    ).first()
    if not assignment:
        flash("You are not assigned as an organizer for this shift.", "error")
        return redirect(url_for('crew_dashboard'))

    # Build data: for each truck, list of (pickup, items) pairs
    truck_numbers = list(range(1, shift.trucks + 1))
    pickups = (
        ShiftPickup.query
        .filter_by(shift_id=shift.id)
        .order_by(ShiftPickup.truck_number.asc(), ShiftPickup.id.asc())
        .all()
    )
    from collections import defaultdict
    pickups_by_truck = defaultdict(list)
    for p in pickups:
        pickups_by_truck[p.truck_number].append(p)

    # All items for each seller in this shift
    seller_items = {}
    for p in pickups:
        items = InventoryItem.query.filter_by(seller_id=p.seller_id).filter(
            InventoryItem.status.in_(['approved', 'available'])
        ).all()
        seller_items[p.seller_id] = items

    # Intake status per item: latest IntakeRecord
    all_item_ids = [i.id for items in seller_items.values() for i in items]
    latest_intake = {}
    if all_item_ids:
        from sqlalchemy import func
        subq = (
            db.session.query(
                IntakeRecord.item_id,
                func.max(IntakeRecord.id).label('max_id')
            )
            .filter(IntakeRecord.item_id.in_(all_item_ids))
            .group_by(IntakeRecord.item_id)
            .subquery()
        )
        records = (
            db.session.query(IntakeRecord)
            .join(subq, IntakeRecord.id == subq.c.max_id)
            .all()
        )
        for rec in records:
            latest_intake[rec.item_id] = rec

    # Open flags for this shift
    open_flags = IntakeFlag.query.filter_by(shift_id=shift.id, resolved=False).all()

    # Live counts — "accounted for" = has an IntakeRecord (received OR flagged with issue)
    received_item_ids = set(latest_intake.keys())
    total_items = len(all_item_ids)
    received_count = len(received_item_ids)
    all_accounted = (total_items == 0 or received_count >= total_items)

    # Active storage locations (for the intake modal dropdown — all active, including full)
    storage_locations = StorageLocation.query.filter_by(is_active=True).order_by(StorageLocation.name).all()

    return render_template(
        'crew/intake.html',
        shift=shift,
        truck_numbers=truck_numbers,
        pickups_by_truck=pickups_by_truck,
        seller_items=seller_items,
        latest_intake=latest_intake,
        open_flags=open_flags,
        received_count=received_count,
        total_items=total_items,
        all_accounted=all_accounted,
        storage_locations=storage_locations,
    )


@app.route('/crew/intake/<int:shift_id>/item/<int:item_id>', methods=['POST'])
@login_required
def crew_intake_submit(shift_id, item_id):
    """Submit intake for one item. Creates IntakeRecord. Never updates existing records."""
    if (r := _require_organizer()):
        return r
    shift = Shift.query.get_or_404(shift_id)
    item = InventoryItem.query.get_or_404(item_id)

    storage_location_id = request.form.get('storage_location_id', type=int)
    storage_row = request.form.get('storage_row', '').strip() or None
    storage_note = request.form.get('storage_note', '').strip() or None
    quality_after = request.form.get('quality', type=int)
    flag_checked = request.form.get('flag_issue') == 'on'
    flag_type = request.form.get('flag_type', '').strip()
    flag_description = request.form.get('flag_description', '').strip()

    # Storage unit is required only if the item was actually received (not flagged as an issue)
    if not storage_location_id and not flag_checked:
        flash("Storage unit is required for received items.", "error")
        return redirect(url_for('crew_intake_shift', shift_id=shift_id))
    if not quality_after or quality_after not in range(1, 6):
        flash("Condition rating is required (1–5).", "error")
        return redirect(url_for('crew_intake_shift', shift_id=shift_id))
    if flag_checked and not flag_description:
        flash("Please describe the issue when flagging an item.", "error")
        return redirect(url_for('crew_intake_shift', shift_id=shift_id))

    # Snapshot quality before any update
    quality_before = item.quality

    # Update InventoryItem — only write location/arrival if item actually made it to the unit
    was_arrived = bool(item.arrived_at_store_at)
    if storage_location_id:
        if not item.arrived_at_store_at:
            item.arrived_at_store_at = datetime.utcnow()
        item.storage_location_id = storage_location_id
        item.storage_row = storage_row
        item.storage_note = storage_note
    item.quality = quality_after

    # Append new IntakeRecord (never update existing)
    record = IntakeRecord(
        item_id=item.id,
        shift_id=shift.id,
        organizer_id=current_user.id,
        storage_location_id=storage_location_id,
        storage_row=storage_row,
        storage_note=storage_note,
        quality_before=quality_before,
        quality_after=quality_after,
    )
    db.session.add(record)
    db.session.flush()  # get record.id for IntakeFlag FK

    if flag_checked:
        flag = IntakeFlag(
            item_id=item.id,
            shift_id=shift.id,
            intake_record_id=record.id,
            organizer_id=current_user.id,
            flag_type=flag_type or 'other',
            description=flag_description,
        )
        db.session.add(flag)

    db.session.commit()
    flash(f"Item #{item.id} received.", "success")
    return redirect(url_for('crew_intake_shift', shift_id=shift_id))


@app.route('/crew/intake/<int:shift_id>/complete', methods=['POST'])
@login_required
def crew_intake_complete(shift_id):
    """Organizer marks their intake work done — independent of ShiftRun completion."""
    if (r := _require_organizer()):
        return r
    shift = Shift.query.get_or_404(shift_id)
    assignment = ShiftAssignment.query.filter_by(
        shift_id=shift.id, worker_id=current_user.id, role_on_shift='organizer'
    ).first()
    if not assignment:
        flash("You are not assigned as organizer for this shift.", "error")
        return redirect(url_for('crew_dashboard'))
    if not assignment.completed_at:
        assignment.completed_at = datetime.utcnow()
        db.session.commit()
    flash("Intake complete — great work!", "success")
    return redirect(url_for('crew_dashboard'))


@app.route('/crew/intake/<int:shift_id>/unknown', methods=['POST'])
@login_required
def crew_intake_log_unknown(shift_id):
    """Log an unknown item (no DB record) as an IntakeFlag."""
    if (r := _require_organizer()):
        return r
    shift = Shift.query.get_or_404(shift_id)
    description = request.form.get('description', '').strip()
    if not description:
        flash("Please describe the unknown item.", "error")
        return redirect(url_for('crew_intake_shift', shift_id=shift_id))
    flag = IntakeFlag(
        item_id=None,
        shift_id=shift.id,
        intake_record_id=None,
        organizer_id=current_user.id,
        flag_type='unknown_item',
        description=description,
    )
    db.session.add(flag)
    db.session.commit()
    flash("Unknown item logged as a flag for admin review.", "success")
    return redirect(url_for('crew_intake_shift', shift_id=shift_id))


@app.route('/crew/intake/search')
@login_required
def crew_intake_search():
    """Search items by ID or partial seller name. Returns a rendered partial (no layout)."""
    if (r := _require_organizer()):
        return r
    q = request.args.get('q', '').strip()
    results = []
    if q:
        # Try numeric ID match first
        if q.lstrip('#').isdigit():
            item_id = int(q.lstrip('#'))
            item = InventoryItem.query.get(item_id)
            if item:
                results = [item]
        if not results:
            # Seller name partial match
            results = (
                InventoryItem.query
                .join(User, InventoryItem.seller_id == User.id)
                .filter(User.full_name.ilike(f'%{q}%'))
                .filter(InventoryItem.status.in_(['approved', 'available']))
                .limit(20)
                .all()
            )
    # Build latest intake state for results
    item_ids = [i.id for i in results]
    latest_intake = {}
    if item_ids:
        from sqlalchemy import func
        subq = (
            db.session.query(
                IntakeRecord.item_id,
                func.max(IntakeRecord.id).label('max_id')
            )
            .filter(IntakeRecord.item_id.in_(item_ids))
            .group_by(IntakeRecord.item_id)
            .subquery()
        )
        records = (
            db.session.query(IntakeRecord)
            .join(subq, IntakeRecord.id == subq.c.max_id)
            .all()
        )
        for rec in records:
            latest_intake[rec.item_id] = rec
    storage_locations = StorageLocation.query.filter_by(is_active=True).order_by(StorageLocation.name).all()
    shift_id = request.args.get('shift_id', type=int)
    return render_template(
        'crew/intake_search_results.html',
        results=results,
        latest_intake=latest_intake,
        storage_locations=storage_locations,
        query=q,
        shift_id=shift_id,
    )


# ── Admin Shift Ops routes ──────────────────────────────────────────────────

@app.route('/admin/crew/shift/<int:shift_id>/ops')
@login_required
def admin_shift_ops(shift_id):
    """Live admin ops view — assign sellers to shift stops."""
    if not current_user.is_admin:
        abort(403)
    shift = Shift.query.get_or_404(shift_id)
    max_trucks = int(AppSetting.get('max_trucks_per_shift', '4'))
    pickups = (
        ShiftPickup.query
        .filter_by(shift_id=shift.id)
        .order_by(ShiftPickup.truck_number.asc(),
                  nulls_last(ShiftPickup.stop_order.asc()),
                  ShiftPickup.id.asc())
        .all()
    )
    # Sellers already on ANY shift (a seller should only be picked up once)
    assigned_seller_ids = {
        p.seller_id for p in ShiftPickup.query.all()
    }
    # Available sellers: have 'available' items and not already on any shift
    available_sellers = [
        s for s in (
            User.query
            .join(InventoryItem, InventoryItem.seller_id == User.id)
            .filter(InventoryItem.status == 'available')
            .filter(User.id.notin_(assigned_seller_ids))
            .group_by(User.id)
            .order_by(User.full_name)
            .all()
        )
        if s.pickup_week and s.has_pickup_location
    ]
    # Item counts for available sellers
    seller_item_counts = {}
    for s in available_sellers:
        seller_item_counts[s.id] = InventoryItem.query.filter_by(
            seller_id=s.id, status='available'
        ).count()
    # Item counts for assigned sellers
    pickup_item_counts = {}
    for p in pickups:
        pickup_item_counts[p.seller_id] = InventoryItem.query.filter_by(
            seller_id=p.seller_id, status='available'
        ).count()
    # Group pickups by truck
    from collections import defaultdict
    pickups_by_truck = defaultdict(list)
    for p in pickups:
        pickups_by_truck[p.truck_number].append(p)
    truck_numbers = list(range(1, shift.trucks + 1))
    # Group driver assignments by truck for the ops page mover section
    movers_by_truck = defaultdict(list)
    unassigned_movers = []
    for a in shift.assignments:
        if a.role_on_shift == 'driver':
            if a.truck_number and a.truck_number in truck_numbers:
                movers_by_truck[a.truck_number].append(a)
            else:
                unassigned_movers.append(a)
    drivers_per_truck = int(AppSetting.get('drivers_per_truck', '2'))
    # Spec #4: storage locations for the Destination Unit dropdown (active + non-full)
    storage_locations = (
        StorageLocation.query
        .filter_by(is_active=True, is_full=False)
        .order_by(StorageLocation.name.asc())
        .all()
    )
    # Parse the shift-level truck unit plan (keyed by truck number string)
    import json as _json
    truck_unit_plan = _json.loads(shift.truck_unit_plan or '{}')
    # Build a lookup: truck_number (int) → StorageLocation object
    storage_loc_by_id = {loc.id: loc for loc in StorageLocation.query.filter_by(is_active=True).all()}
    truck_planned_unit = {
        int(k): storage_loc_by_id.get(v)
        for k, v in truck_unit_plan.items()
        if storage_loc_by_id.get(v)
    }
    # Spec #4: intake summary — received count + open flags per truck
    all_pickups = pickups
    item_ids_by_truck = {}
    for truck_num in truck_numbers:
        truck_pickups = pickups_by_truck[truck_num]
        ids = []
        for p in truck_pickups:
            for item in InventoryItem.query.filter_by(seller_id=p.seller_id).filter(
                InventoryItem.status.in_(['approved', 'available'])
            ).all():
                ids.append(item.id)
        item_ids_by_truck[truck_num] = ids
    # Items received = those with an IntakeRecord in this shift
    received_by_truck = {}
    for truck_num in truck_numbers:
        ids = item_ids_by_truck[truck_num]
        if ids:
            received_by_truck[truck_num] = (
                db.session.query(IntakeRecord.item_id)
                .filter(IntakeRecord.shift_id == shift.id, IntakeRecord.item_id.in_(ids))
                .distinct()
                .count()
            )
        else:
            received_by_truck[truck_num] = 0
    open_flags = IntakeFlag.query.filter_by(shift_id=shift.id, resolved=False).all()
    open_flags_by_truck = {n: [] for n in truck_numbers}
    for f in open_flags:
        if f.item_id:
            # find which truck this item belongs to
            for truck_num in truck_numbers:
                if f.item_id in item_ids_by_truck[truck_num]:
                    open_flags_by_truck[truck_num].append(f)
                    break
        else:
            # unknown_item flags — attach to truck 1 for display
            open_flags_by_truck[truck_numbers[0]].append(f)
    # Spec #8: unnotified count for confirmation dialog
    unnotified_count = sum(1 for p in pickups if p.notified_at is None)

    # Spec #8: reschedule activity lists
    rescheduled_in = [p for p in pickups if p.rescheduled_from_shift_id is not None]
    rescheduled_out = ShiftPickup.query.filter(
        ShiftPickup.rescheduled_from_shift_id == shift.id
    ).all()

    # Spec #8: stale route flag — any pickup rescheduled in with no stop_order yet
    has_stale_route = any(
        p.rescheduled_at is not None and p.stop_order is None
        for p in pickups
    )

    return render_template(
        'admin/shift_ops.html',
        shift=shift,
        pickups_by_truck=pickups_by_truck,
        truck_numbers=truck_numbers,
        movers_by_truck=movers_by_truck,
        unassigned_movers=unassigned_movers,
        available_sellers=available_sellers,
        seller_item_counts=seller_item_counts,
        pickup_item_counts=pickup_item_counts,
        max_trucks=max_trucks,
        drivers_per_truck=drivers_per_truck,
        storage_locations=storage_locations,
        truck_planned_unit=truck_planned_unit,
        item_ids_by_truck=item_ids_by_truck,
        received_by_truck=received_by_truck,
        open_flags_by_truck=open_flags_by_truck,
        unnotified_count=unnotified_count,
        rescheduled_in=rescheduled_in,
        rescheduled_out=rescheduled_out,
        has_stale_route=has_stale_route,
    )


@app.route('/admin/crew/shift/<int:shift_id>/assign_movers_bulk', methods=['POST'])
@login_required
def admin_shift_assign_movers_bulk(shift_id):
    """Assign multiple movers to a truck in one submit."""
    if not current_user.is_admin:
        abort(403)
    truck_number = request.form.get('truck_number', type=int)
    assignment_ids = [v for v in request.form.getlist('assignment_ids') if v]
    if not truck_number or not assignment_ids:
        flash("Select at least one mover and a truck.", "error")
        return redirect(url_for('admin_shift_ops', shift_id=shift_id))
    drivers_per_truck = int(AppSetting.get('drivers_per_truck', '2'))
    current_count = ShiftAssignment.query.filter_by(
        shift_id=shift_id, role_on_shift='driver', truck_number=truck_number
    ).count()
    seen = set()
    assigned = 0
    for aid in assignment_ids:
        if aid in seen:
            continue
        seen.add(aid)
        if current_count + assigned >= drivers_per_truck:
            flash(f"Truck {truck_number} is full — only {drivers_per_truck} movers allowed.", "error")
            break
        try:
            a = ShiftAssignment.query.get(int(aid))
        except (ValueError, TypeError):
            continue
        if not a or a.shift_id != shift_id:
            continue
        a.truck_number = truck_number
        assigned += 1
    db.session.commit()
    if assigned:
        flash(f"{assigned} mover{'s' if assigned != 1 else ''} assigned to Truck {truck_number}.", "success")
    return redirect(url_for('admin_shift_ops', shift_id=shift_id))


@app.route('/admin/crew/shift/<int:shift_id>/mover/<int:assignment_id>/assign_truck', methods=['POST'])
@login_required
def admin_shift_assign_mover_truck(shift_id, assignment_id):
    """Reassign a driver to a specific truck on this shift."""
    if not current_user.is_admin:
        abort(403)
    assignment = ShiftAssignment.query.get_or_404(assignment_id)
    if assignment.shift_id != shift_id:
        abort(404)
    truck_number = request.form.get('truck_number', type=int)
    # truck_number=0 means remove from truck (unassign)
    if truck_number == 0:
        assignment.truck_number = None
        db.session.commit()
        flash(f"{assignment.worker.full_name} removed from truck.", "success")
        return redirect(url_for('admin_shift_ops', shift_id=shift_id))
    if not truck_number:
        flash("Truck number required.", "error")
        return redirect(url_for('admin_shift_ops', shift_id=shift_id))
    drivers_per_truck = int(AppSetting.get('drivers_per_truck', '2'))
    current_on_truck = ShiftAssignment.query.filter_by(
        shift_id=shift_id, role_on_shift='driver', truck_number=truck_number
    ).count()
    already_there = (assignment.truck_number == truck_number)
    if not already_there and current_on_truck >= drivers_per_truck:
        flash(f"Truck {truck_number} is full ({drivers_per_truck} movers max).", "error")
        return redirect(url_for('admin_shift_ops', shift_id=shift_id))
    assignment.truck_number = truck_number
    db.session.commit()
    flash(f"{assignment.worker.full_name} assigned to Truck {truck_number}.", "success")
    return redirect(url_for('admin_shift_ops', shift_id=shift_id))


@app.route('/admin/crew/shift/<int:shift_id>/assign', methods=['POST'])
@login_required
def admin_shift_assign_seller(shift_id):
    """Add a seller stop to this shift."""
    if not current_user.is_admin:
        abort(403)
    shift = Shift.query.get_or_404(shift_id)
    seller_id = request.form.get('seller_id', type=int)
    truck_number = request.form.get('truck_number', type=int)
    if not seller_id or not truck_number:
        flash("Seller and truck number are required.", "error")
        return redirect(url_for('admin_shift_ops', shift_id=shift_id))
    seller = User.query.get_or_404(seller_id)
    if not seller.pickup_week or not seller.has_pickup_location:
        flash(f"{seller.full_name} hasn't set their pickup week and address yet.", "error")
        return redirect(url_for('admin_shift_ops', shift_id=shift_id))
    # Check for duplicate — a seller should only appear on one shift total
    existing = ShiftPickup.query.filter_by(seller_id=seller_id).first()
    if existing:
        flash(f"{seller.full_name} is already assigned to a shift.", "error")
        return redirect(url_for('admin_shift_ops', shift_id=shift_id))
    # Pre-populate storage_location_id from the truck unit plan if set
    import json as _json
    plan = _json.loads(shift.truck_unit_plan or '{}')
    planned_unit_id = plan.get(str(truck_number))
    pickup = ShiftPickup(
        shift_id=shift.id,
        seller_id=seller_id,
        truck_number=truck_number,
        storage_location_id=planned_unit_id,
        created_by_id=current_user.id,
    )
    db.session.add(pickup)
    db.session.commit()
    flash(f"{seller.full_name} added to Truck {truck_number}.", "success")
    return redirect(url_for('admin_shift_ops', shift_id=shift_id))


@app.route('/admin/crew/shift/<int:shift_id>/stop/<int:pickup_id>/remove', methods=['POST'])
@login_required
def admin_shift_remove_stop(shift_id, pickup_id):
    """Remove a pending stop from this shift."""
    if not current_user.is_admin:
        abort(403)
    pickup = ShiftPickup.query.get_or_404(pickup_id)
    if pickup.shift_id != shift_id:
        abort(404)
    if pickup.status != 'pending':
        flash("Cannot remove a stop that is already in progress.", "error")
        return redirect(url_for('admin_shift_ops', shift_id=shift_id))
    db.session.delete(pickup)
    db.session.commit()
    flash("Stop removed.", "success")
    return redirect(url_for('admin_shift_ops', shift_id=shift_id))


# =========================================================
# SPEC #4 — ORGANIZER INTAKE (Admin routes)
# =========================================================

@app.route('/admin/storage')
@login_required
def admin_storage_index():
    """Storage locations — GET redirects to /admin/settings#storage (Admin UI Redesign)."""
    if not current_user.is_super_admin:
        flash("Super admin access required.", "error")
        return redirect(url_for('admin_ops'))
    return redirect(url_for('admin_settings') + '#storage', 302)


@app.route('/admin/storage/create', methods=['POST'])
@login_required
def admin_storage_create():
    """Create a new storage location. Super admin only."""
    if not current_user.is_super_admin:
        abort(403)
    name = request.form.get('name', '').strip()
    address = request.form.get('address', '').strip() or None
    location_note = request.form.get('location_note', '').strip() or None
    capacity_note = request.form.get('capacity_note', '').strip() or None
    if not name:
        flash("Location name is required.", "error")
        return redirect(url_for('admin_storage_index'))
    if StorageLocation.query.filter_by(name=name).first():
        flash(f"A location named '{name}' already exists.", "error")
        return redirect(url_for('admin_storage_index'))
    loc = StorageLocation(
        name=name,
        address=address,
        location_note=location_note,
        capacity_note=capacity_note,
        created_by_id=current_user.id,
    )
    db.session.add(loc)
    db.session.commit()
    flash(f"Storage location '{name}' created.", "success")
    return redirect(url_for('admin_storage_index'))


@app.route('/admin/storage/<int:loc_id>/edit', methods=['POST'])
@login_required
def admin_storage_edit(loc_id):
    """Edit a storage location. Super admin only."""
    if not current_user.is_super_admin:
        abort(403)
    loc = StorageLocation.query.get_or_404(loc_id)
    name = request.form.get('name', '').strip()
    if not name:
        flash("Location name is required.", "error")
        return redirect(url_for('admin_storage_index'))
    # Unique name check (exclude self)
    existing = StorageLocation.query.filter_by(name=name).first()
    if existing and existing.id != loc.id:
        flash(f"A location named '{name}' already exists.", "error")
        return redirect(url_for('admin_storage_index'))
    loc.name = name
    loc.address = request.form.get('address', '').strip() or None
    loc.location_note = request.form.get('location_note', '').strip() or None
    loc.capacity_note = request.form.get('capacity_note', '').strip() or None
    loc.is_active = request.form.get('is_active') == 'on'
    loc.is_full = request.form.get('is_full') == 'on'
    db.session.commit()
    flash(f"'{loc.name}' updated.", "success")
    return redirect(url_for('admin_storage_index'))


@app.route('/admin/storage/<int:loc_id>')
@login_required
def admin_storage_detail(loc_id):
    """View all items stored at this location. Admin."""
    if not current_user.is_admin:
        abort(403)
    loc = StorageLocation.query.get_or_404(loc_id)
    items = (
        InventoryItem.query
        .filter_by(storage_location_id=loc.id)
        .order_by(InventoryItem.storage_row.asc(), InventoryItem.id.asc())
        .all()
    )
    # Latest intake record per item for the intake date column
    item_ids = [i.id for i in items]
    latest_intake = {}
    if item_ids:
        from sqlalchemy import func
        subq = (
            db.session.query(
                IntakeRecord.item_id,
                func.max(IntakeRecord.id).label('max_id')
            )
            .filter(IntakeRecord.item_id.in_(item_ids))
            .group_by(IntakeRecord.item_id)
            .subquery()
        )
        for rec in db.session.query(IntakeRecord).join(subq, IntakeRecord.id == subq.c.max_id).all():
            latest_intake[rec.item_id] = rec
    return render_template('admin/storage_detail.html', loc=loc, items=items, latest_intake=latest_intake)


@app.route('/admin/crew/shift/<int:shift_id>/truck/<int:truck_number>/assign_unit', methods=['POST'])
@login_required
def admin_shift_assign_unit(shift_id, truck_number):
    """Set the planned StorageLocation for a truck. Persists on the shift and all pending pickups."""
    if not current_user.is_admin:
        abort(403)
    shift = Shift.query.get_or_404(shift_id)
    storage_location_id = request.form.get('storage_location_id', type=int) or None

    # Write to the shift-level plan (source of truth even before pickups exist)
    import json as _json
    plan = _json.loads(shift.truck_unit_plan or '{}')
    if storage_location_id:
        plan[str(truck_number)] = storage_location_id
    else:
        plan.pop(str(truck_number), None)
    shift.truck_unit_plan = _json.dumps(plan) if plan else None

    # Also update any existing pending pickups on this truck
    for p in ShiftPickup.query.filter_by(
        shift_id=shift.id, truck_number=truck_number, status='pending'
    ).all():
        p.storage_location_id = storage_location_id

    db.session.commit()
    if storage_location_id:
        loc = StorageLocation.query.get(storage_location_id)
        flash(f"Truck {truck_number} destination set to '{loc.name}'.", "success")
    else:
        flash(f"Truck {truck_number} destination cleared.", "success")
    return redirect(url_for('admin_shift_ops', shift_id=shift_id))


@app.route('/admin/crew/shift/<int:shift_id>/intake')
@login_required
def admin_shift_intake_log(shift_id):
    """Full read-only intake log for a shift. Admin."""
    if not current_user.is_admin:
        abort(403)
    shift = Shift.query.get_or_404(shift_id)
    records = (
        IntakeRecord.query
        .filter_by(shift_id=shift.id)
        .order_by(IntakeRecord.created_at.asc())
        .all()
    )
    flags = (
        IntakeFlag.query
        .filter_by(shift_id=shift.id)
        .order_by(IntakeFlag.created_at.asc())
        .all()
    )
    # Group records by truck via seller → pickup → truck_number
    pickup_by_seller = {p.seller_id: p for p in shift.pickups}
    truck_numbers = list(range(1, shift.trucks + 1))
    from collections import defaultdict
    records_by_truck = defaultdict(list)
    for rec in records:
        if rec.item and rec.item.seller_id in pickup_by_seller:
            tn = pickup_by_seller[rec.item.seller_id].truck_number
            records_by_truck[tn].append(rec)
        else:
            records_by_truck[0].append(rec)  # unattributed
    return render_template(
        'admin/shift_intake_log.html',
        shift=shift,
        records=records,
        records_by_truck=records_by_truck,
        flags=flags,
        pickup_by_seller=pickup_by_seller,
        truck_numbers=truck_numbers,
    )


@app.route('/admin/intake/flag/<int:flag_id>/resolve', methods=['POST'])
@login_required
def admin_intake_flag_resolve(flag_id):
    """Resolve an intake flag with an admin note."""
    if not current_user.is_admin:
        abort(403)
    flag = IntakeFlag.query.get_or_404(flag_id)
    shift_id = flag.shift_id
    note = request.form.get('resolution_note', '').strip() or None
    flag.resolved = True
    flag.resolved_at = datetime.utcnow()
    flag.resolved_by_id = current_user.id
    flag.resolution_note = note
    db.session.commit()
    flash("Flag resolved.", "success")
    return redirect(url_for('admin_shift_intake_log', shift_id=shift_id))


@app.route('/admin/intake/flagged')
@login_required
def admin_intake_flagged():
    """Items flagged during intake as missing/damaged/wrong — admin review queue."""
    if not current_user.is_admin:
        abort(403)
    # All unresolved flags that reference a real item and indicate a quality/availability issue
    flags = (
        IntakeFlag.query
        .filter(IntakeFlag.resolved == False)
        .filter(IntakeFlag.item_id.isnot(None))
        .order_by(IntakeFlag.created_at.desc())
        .all()
    )
    # Deduplicate by item — keep the most recent flag per item
    seen_items = {}
    for flag in flags:
        if flag.item_id not in seen_items:
            seen_items[flag.item_id] = flag
    flagged_items = list(seen_items.values())
    # Exclude items already rejected or sold
    flagged_items = [
        f for f in flagged_items
        if f.item and f.item.status not in ('rejected', 'sold')
    ]
    return render_template('admin/intake_flagged.html', flagged_items=flagged_items)


@app.route('/admin/intake/flagged/remove', methods=['POST'])
@login_required
def admin_intake_flagged_remove():
    """Bulk-remove flagged items from the marketplace (set status=rejected)."""
    if not current_user.is_admin:
        abort(403)
    item_ids = request.form.getlist('item_ids')
    if not item_ids:
        flash("No items selected.", "error")
        return redirect(url_for('admin_intake_flagged'))
    removed = 0
    for raw_id in item_ids:
        try:
            item_id = int(raw_id)
        except (ValueError, TypeError):
            continue
        item = InventoryItem.query.get(item_id)
        if not item or item.status in ('sold',):
            continue
        item.status = 'rejected'
        # Resolve all open flags for this item
        IntakeFlag.query.filter_by(item_id=item_id, resolved=False).update({
            'resolved': True,
            'resolved_at': datetime.utcnow(),
            'resolved_by_id': current_user.id,
            'resolution_note': 'Removed from marketplace by admin after intake flag.',
        }, synchronize_session=False)
        removed += 1
    db.session.commit()
    flash(f"{removed} item{'s' if removed != 1 else ''} removed from the marketplace.", "success")
    return redirect(url_for('admin_intake_flagged'))


# =========================================================
# PAYOUT RECONCILIATION (Spec #5)
# =========================================================

@app.route('/admin/payouts')
@login_required
def admin_payouts():
    """Payout reconciliation page — unpaid queue + paid history."""
    if not current_user.is_admin:
        flash("Access denied.", "error")
        return redirect(url_for('index'))

    # --- Unpaid queue ---
    unpaid_items = (
        InventoryItem.query
        .filter_by(payout_sent=False)
        .filter(InventoryItem.status == 'sold')
        .order_by(InventoryItem.sold_at.asc())
        .all()
    )

    unpaid_item_ids = [i.id for i in unpaid_items]

    # Batch intake check
    intake_item_ids = set()
    if unpaid_item_ids:
        intake_item_ids = {
            r.item_id for r in
            IntakeRecord.query
            .filter(IntakeRecord.item_id.in_(unpaid_item_ids))
            .with_entities(IntakeRecord.item_id)
            .all()
        }

    # Batch flag check (unresolved, item-linked flags only)
    flagged_item_ids = {}  # item_id -> flag_type
    if unpaid_item_ids:
        flag_rows = (
            IntakeFlag.query
            .filter(
                IntakeFlag.item_id.in_(unpaid_item_ids),
                IntakeFlag.resolved == False,
                IntakeFlag.item_id != None
            )
            .with_entities(IntakeFlag.item_id, IntakeFlag.flag_type)
            .all()
        )
        for row in flag_rows:
            flagged_item_ids[row.item_id] = row.flag_type

    # Group by seller, compute payout amounts
    seller_groups = {}  # seller_id -> {seller, items, total}
    for item in unpaid_items:
        if not item.seller:
            continue
        sid = item.seller_id
        pct = _get_payout_percentage(item)
        payout_amt = round((item.price or 0) * pct, 2)
        if sid not in seller_groups:
            seller_groups[sid] = {
                'seller': item.seller,
                'items': [],
                'total': 0.0,
            }
        seller_groups[sid]['items'].append({
            'item': item,
            'payout_amount': payout_amt,
            'payout_rate_pct': item.seller.payout_rate,
            'has_intake': item.id in intake_item_ids,
            'flag_type': flagged_item_ids.get(item.id),
        })
        seller_groups[sid]['total'] = round(seller_groups[sid]['total'] + payout_amt, 2)

    # Sort seller groups by total descending
    sorted_sellers = sorted(seller_groups.values(), key=lambda g: g['total'], reverse=True)

    # --- Paid history (paginated, 50/page) ---
    page = request.args.get('page', 1, type=int)
    paid_q = (
        InventoryItem.query
        .filter_by(payout_sent=True)
        .filter(InventoryItem.status == 'sold')
        .order_by(nulls_last(InventoryItem.payout_sent_at.desc()))
    )
    paid_pagination = paid_q.paginate(page=page, per_page=50, error_out=False)
    paid_items_page = paid_pagination.items

    paid_rows = []
    for item in paid_items_page:
        if not item.seller:
            continue
        pct = _get_payout_percentage(item)
        paid_rows.append({
            'item': item,
            'seller': item.seller,
            'payout_rate_pct': item.seller.payout_rate,
            'payout_amount': round((item.price or 0) * pct, 2),
        })

    active_tab = request.args.get('tab', 'unpaid')

    return render_template(
        'admin/payouts.html',
        sorted_sellers=sorted_sellers,
        intake_item_ids=intake_item_ids,
        flagged_item_ids=flagged_item_ids,
        paid_rows=paid_rows,
        pagination=paid_pagination,
        active_tab=active_tab,
    )


@app.route('/admin/payouts/item/<int:item_id>/mark_paid', methods=['POST'])
@login_required
def admin_payout_mark_paid(item_id):
    """Mark one item's payout as sent; triggers confirmation email."""
    if not current_user.is_admin:
        flash("Access denied.", "error")
        return redirect(url_for('index'))

    item = InventoryItem.query.get_or_404(item_id)

    # Guard: item must be sold
    if item.status != 'sold':
        flash("Item is not in a sold state.", "error")
        return redirect(url_for('admin_payouts'))

    # Idempotency guard
    if item.payout_sent:
        flash("Already marked paid.", "warning")
        return redirect(url_for('admin_payouts'))

    item.payout_sent = True
    item.payout_sent_at = datetime.utcnow()
    db.session.commit()

    # PostHog event
    posthog.capture('payout_marked_sent', distinct_id=str(current_user.id), properties={
        'item_id': item.id,
        'is_admin': True,
    })

    # Send payout confirmation email to seller
    if item.seller:
        try:
            seller = item.seller
            pct = _get_payout_percentage(item)
            payout_amount = round((item.price or 0) * pct, 2)
            payout_rate_pct = seller.payout_rate
            first_name = (seller.full_name or '').split()[0] if seller.full_name else 'there'

            # Build payout method line
            if seller.payout_handle:
                sent_to_line = f"<p><strong>Sent to:</strong> {seller.payout_method or 'Venmo'} — {seller.payout_handle}</p>"
            else:
                sent_to_line = ""

            # Build thumbnail line
            if item.photo_url:
                thumb_url = url_for('uploaded_file', filename=item.photo_url, _external=True)
                thumb_html = f'<img src="{thumb_url}" alt="{item.description}" style="max-width:200px; border-radius:8px; margin-bottom:12px;">'
            else:
                thumb_html = ""

            email_html = wrap_email_template(f"""
                <h2>You've been paid!</h2>
                <p>Hi {first_name},</p>
                <p>Great news — we've sent your payout for the following item sold through Campus Swap:</p>
                {thumb_html}
                <p><strong>{item.description}</strong></p>
                <p><strong>Sale price:</strong> ${item.price:.2f}</p>
                <p><strong>Your payout ({payout_rate_pct}%):</strong> ${payout_amount:.2f}</p>
                {sent_to_line}
                <p>Thanks for selling with Campus Swap. We'll be in touch if anything else sells!</p>
                <p>— The Campus Swap Team</p>
            """)

            send_email(
                seller.email,
                "You've been paid for your Campus Swap item!",
                email_html,
            )
        except Exception as e:
            logger.error(f"Payout confirmation email failed for item {item.id}: {e}", exc_info=True)

    flash(f"Payout marked as sent for '{item.description}'.", "success")
    return redirect(url_for('admin_payouts'))


@app.route('/admin/payouts/export')
@login_required
def admin_payouts_export():
    """CSV export of all sold items with full payout data."""
    if not current_user.is_admin:
        flash("Access denied.", "error")
        return redirect(url_for('index'))

    sold_items = (
        InventoryItem.query
        .filter(InventoryItem.status == 'sold')
        .order_by(InventoryItem.sold_at.desc())
        .all()
    )

    all_item_ids = [i.id for i in sold_items]

    # Batch intake + flag lookups
    intake_ids = set()
    flagged_ids = set()
    if all_item_ids:
        intake_ids = {
            r.item_id for r in
            IntakeRecord.query
            .filter(IntakeRecord.item_id.in_(all_item_ids))
            .with_entities(IntakeRecord.item_id)
            .all()
        }
        flagged_ids = {
            f.item_id for f in
            IntakeFlag.query
            .filter(
                IntakeFlag.item_id.in_(all_item_ids),
                IntakeFlag.resolved == False,
                IntakeFlag.item_id != None,
            )
            .with_entities(IntakeFlag.item_id)
            .all()
        }

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'item_id', 'item_title', 'seller_name', 'seller_email',
        'payout_method', 'payout_handle', 'sale_price', 'payout_rate',
        'payout_amount', 'sold_at', 'payout_sent', 'payout_sent_at',
        'has_intake_record', 'has_unresolved_flag',
    ])

    for item in sold_items:
        seller = item.seller
        pct = _get_payout_percentage(item)
        payout_amount = round((item.price or 0) * pct, 2)
        payout_rate = seller.payout_rate if seller else ''
        writer.writerow([
            item.id,
            item.description or '',
            seller.full_name if seller else '',
            seller.email if seller else '',
            seller.payout_method if seller else '',
            seller.payout_handle if seller else '',
            item.price or 0,
            payout_rate,
            payout_amount,
            item.sold_at.strftime('%Y-%m-%dT%H:%M:%S') if item.sold_at else '',
            'True' if item.payout_sent else 'False',
            item.payout_sent_at.strftime('%Y-%m-%dT%H:%M:%S') if item.payout_sent_at else '',
            'True' if item.id in intake_ids else 'False',
            'True' if item.id in flagged_ids else 'False',
        ])

    output.seek(0)
    return Response(
        output,
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=campus_swap_payouts.csv'},
    )


@app.route('/admin/crew/approve/<int:user_id>', methods=['POST'])
@login_required
def admin_crew_approve(user_id):
    """Admin approves a worker application and assigns their role."""
    if not current_user.is_admin:
        flash("Access denied.", "error")
        return redirect(url_for('index'))

    worker = User.query.get_or_404(user_id)

    worker.is_worker = True
    worker.worker_status = 'approved'
    worker.worker_role = 'both'  # all movers are both roles; role_on_shift assigned per shift

    if worker.worker_application:
        worker.worker_application.reviewed_at = datetime.utcnow()
        worker.worker_application.reviewed_by = current_user.id

    db.session.commit()

    # Send approval email
    try:
        crew_url = url_for('crew_dashboard', _external=True)
        email_content = f"""
        <div style="font-family: sans-serif; padding: 20px; max-width: 500px;">
            <h2 style="color: #1A3D1A;">You're on the Campus Swap Crew!</h2>
            <p>Hi {worker.full_name},</p>
            <p>Your application has been approved. Here's what's next:</p>
            <div style="background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 8px; padding: 16px; margin: 20px 0;">
                <p style="margin: 0 0 8px;"><strong>Role:</strong> Mover</p>
                <p style="margin: 0 0 8px;"><strong>Pay:</strong> $130/shift</p>
                <p style="margin: 0 0 8px;"><strong>Season:</strong> ~3 weeks (late April – mid May)</p>
                <p style="margin: 0;"><strong>Next step:</strong> Submit your weekly availability by Tuesday — schedule posts by Thursday each week.</p>
            </div>
            <p><a href="{crew_url}" style="background: #C8832A; color: white; padding: 12px 24px; text-decoration: none; border-radius: 8px; display: inline-block;">Go to Crew Portal</a></p>
            <p>See you out there!</p>
            <p>— The Campus Swap Team</p>
        </div>
        """
        send_email(worker.email, "You're on the Campus Swap Crew — here's what's next", email_content)
    except Exception as e:
        logger.error(f"Failed to send crew approval email to {worker.email}: {e}")

    flash(f"Approved {worker.full_name} as a Mover.", "success")
    return redirect(url_for('admin_panel') + '#crew')


@app.route('/admin/crew/reject/<int:user_id>', methods=['POST'])
@login_required
def admin_crew_reject(user_id):
    """Admin rejects a worker application."""
    if not current_user.is_admin:
        flash("Access denied.", "error")
        return redirect(url_for('index'))

    worker = User.query.get_or_404(user_id)
    send_rejection_email = request.form.get('send_email') == 'true'

    worker.worker_status = 'rejected'

    if worker.worker_application:
        worker.worker_application.reviewed_at = datetime.utcnow()
        worker.worker_application.reviewed_by = current_user.id

    db.session.commit()

    if send_rejection_email and worker.email:
        try:
            email_content = f"""
            <div style="font-family: sans-serif; padding: 20px; max-width: 500px;">
                <h2 style="color: #1A3D1A;">Campus Swap Crew — Application Update</h2>
                <p>Hi {worker.full_name},</p>
                <p>Thank you for applying to work with Campus Swap this season. After reviewing all applications,
                we weren't able to offer you a position this time around.</p>
                <p>We really appreciate your interest and hope to work with you in the future.</p>
                <p>— The Campus Swap Team</p>
            </div>
            """
            send_email(worker.email, "Campus Swap Crew — Application Update", email_content)
        except Exception as e:
            logger.error(f"Failed to send crew rejection email to {worker.email}: {e}")

    flash(f"Rejected {worker.full_name}'s application.", "success")
    return redirect(url_for('admin_panel') + '#crew')



# =========================================================
# SECTION: SHIFT SCHEDULING (ADMIN + CREW)
# =========================================================

_SHIFT_DAY_ORDER = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
_SHIFT_DAY_LABELS = {
    'mon': 'Monday', 'tue': 'Tuesday', 'wed': 'Wednesday',
    'thu': 'Thursday', 'fri': 'Friday', 'sat': 'Saturday', 'sun': 'Sunday',
}


def _get_worker_availability_for_week(worker, week_start):
    """Return the best WorkerAvailability record for this worker and week.
    Priority: weekly record → application record → None."""
    avail = WorkerAvailability.query.filter_by(
        user_id=worker.id, week_start=week_start
    ).first()
    if avail:
        return avail
    return WorkerAvailability.query.filter_by(
        user_id=worker.id, week_start=None
    ).first()


def _worker_available_for_slot(worker, shift, week_start):
    """True if worker has availability for shift.day_of_week + shift.slot."""
    avail = _get_worker_availability_for_week(worker, week_start)
    if not avail:
        return False
    field = f"{shift.day_of_week}_{shift.slot}"
    return bool(getattr(avail, field, False))


def _notify_next_seller(shift, current_pickup=None):
    """Send 'you're up next' SMS to the next pending seller on current_pickup's truck."""
    if not current_pickup:
        return
    next_stop = (
        ShiftPickup.query
        .filter_by(shift_id=shift.id, truck_number=current_pickup.truck_number, status='pending')
        .order_by(nulls_last(ShiftPickup.stop_order.asc()), ShiftPickup.id.asc())
        .first()
    )
    # Skip if next stop already has an issue_type flagged (e.g. known access problem)
    if next_stop and next_stop.issue_type is None:
        _send_sms(
            next_stop.seller,
            "You're up next! Your Campus Swap driver is heading to you now."
        )


def _run_optimizer(week):
    """Core optimizer. Clears all existing assignments for the week, then re-assigns greedily.
    Returns a summary dict: {fully_staffed: int, understaffed: int}."""
    # Clear existing assignments
    for shift in week.shifts:
        if shift.is_active:
            ShiftAssignment.query.filter_by(shift_id=shift.id).delete()
    db.session.flush()

    import math as _math
    drivers_per_truck = int(AppSetting.get('drivers_per_truck', '2'))

    all_workers = User.query.filter_by(is_worker=True, worker_status='approved').all()

    # Pre-cache all availability records — avoids repeated DB queries inside the loop
    # avail_cache[worker_id] = set of "day_slot" strings the worker is available for
    avail_cache = {}
    for w in all_workers:
        record = _get_worker_availability_for_week(w, week.week_start)
        if record:
            avail_cache[w.id] = {
                f"{day}_{slot}"
                for day in _SHIFT_DAY_ORDER
                for slot in ('am', 'pm')
                if getattr(record, f"{day}_{slot}", False)
            }
        else:
            avail_cache[w.id] = set()

    def worker_available(worker_id, day, slot):
        return f"{day}_{slot}" in avail_cache[worker_id]

    # Role imbalance: truck_count - storage_count per worker (from all historical assignments)
    # positive → has done more truck; prefer storage next
    # negative → has done more storage; prefer truck next
    role_imbalance = {}
    for w in all_workers:
        truck_count = ShiftAssignment.query.filter_by(worker_id=w.id, role_on_shift='driver').count()
        storage_count = ShiftAssignment.query.filter_by(worker_id=w.id, role_on_shift='organizer').count()
        role_imbalance[w.id] = truck_count - storage_count

    # Partner preferences: build avoided and preferred pair sets
    preferred_pairs = set()  # frozenset({id_a, id_b})
    avoided_pairs   = set()  # frozenset({id_a, id_b})
    for pref in WorkerPreference.query.all():
        pair = frozenset({pref.user_id, pref.target_user_id})
        if pref.preference_type == 'avoided':
            avoided_pairs.add(pair)
        else:
            preferred_pairs.add(pair)
    preferred_pairs -= avoided_pairs  # avoid always overrides prefer

    # Track load and same-day assignments in memory — never query DB mid-loop
    worker_load = {w.id: 0 for w in all_workers}
    # worker_day_assigned[worker_id] = set of (day, slot) tuples assigned so far
    worker_day_assigned = {w.id: set() for w in all_workers}

    active_shifts = sorted([s for s in week.shifts if s.is_active], key=lambda s: s.sort_key)

    fully_staffed = 0
    understaffed = 0

    for shift in active_shifts:
        drivers_needed = shift.trucks * drivers_per_truck
        organizers_needed = _math.ceil(shift.trucks / 2) * 2
        day, slot = shift.day_of_week, shift.slot
        other_slot = 'pm' if slot == 'am' else 'am'

        # Build eligible pools using the pre-cached availability
        # All workers are eligible for both roles — role is assigned per shift
        driver_pool = [
            w for w in all_workers
            if worker_available(w.id, day, slot)
        ]
        organizer_pool = [
            w for w in all_workers
            if worker_available(w.id, day, slot)
        ]

        def make_sort_key(already_on_shift_ids):
            def sort_key(w):
                # 1. Already assigned to other slot today → last resort
                already_doubled = (day, other_slot) in worker_day_assigned[w.id]
                # 2. Available for the other slot today → deprioritize (save them for it)
                flexible = worker_available(w.id, day, other_slot)
                # 3. Load balancing
                load = worker_load[w.id]
                # 4. Role imbalance tiebreaker (more imbalanced sorted last)
                imbalance = abs(role_imbalance.get(w.id, 0))
                # 5. Partner preferences (avoid conflicts first, then preferred matches)
                avoid_conflict = 1 if any(
                    frozenset({w.id, a_id}) in avoided_pairs for a_id in already_on_shift_ids
                ) else 0
                preferred_match = 0 if any(
                    frozenset({w.id, a_id}) in preferred_pairs for a_id in already_on_shift_ids
                ) else 1
                return (already_doubled, flexible, load, imbalance, avoid_conflict, preferred_match)
            return sort_key

        driver_pool.sort(key=make_sort_key(set()))

        # Assign drivers
        assigned_driver_ids = set()
        for w in driver_pool:
            if len(assigned_driver_ids) >= drivers_needed:
                break
            truck_num = (len(assigned_driver_ids) // drivers_per_truck) + 1
            db.session.add(ShiftAssignment(
                shift_id=shift.id, worker_id=w.id,
                role_on_shift='driver', truck_number=truck_num, assigned_by_id=None,
            ))
            assigned_driver_ids.add(w.id)
            worker_load[w.id] += 1
            worker_day_assigned[w.id].add((day, slot))

        # Assign organizers — exclude workers already assigned as drivers to this same shift
        # Sort organizer pool with knowledge of assigned drivers (for partner preference scoring)
        organizer_pool.sort(key=make_sort_key(assigned_driver_ids))
        assigned_org_ids = set()
        for w in organizer_pool:
            if len(assigned_org_ids) >= organizers_needed:
                break
            if w.id in assigned_driver_ids:
                continue
            db.session.add(ShiftAssignment(
                shift_id=shift.id, worker_id=w.id,
                role_on_shift='organizer', assigned_by_id=None,
            ))
            assigned_org_ids.add(w.id)
            worker_load[w.id] += 1
            worker_day_assigned[w.id].add((day, slot))

        if (len(assigned_driver_ids) >= drivers_needed
                and len(assigned_org_ids) >= organizers_needed):
            fully_staffed += 1
        else:
            understaffed += 1

    db.session.commit()
    return {'fully_staffed': fully_staffed, 'understaffed': understaffed, 'total': fully_staffed + understaffed}


def _get_current_published_week():
    """Return the most relevant published ShiftWeek for the worker dashboard.
    Priority:
      1. Active week: week_start <= today <= week_start + 6 (currently running)
      2. Nearest upcoming published week (week_start > today)
      3. Most recently completed published week (week_start < today, as fallback)
    """
    today = _today_eastern()
    week_end = today + timedelta(days=6 - today.weekday())  # Saturday of current week (Eastern)

    # 1. Active: week contains today
    active = (
        ShiftWeek.query
        .filter(
            ShiftWeek.status == 'published',
            ShiftWeek.week_start <= today,
            ShiftWeek.week_start >= today - timedelta(days=6),
        )
        .order_by(ShiftWeek.week_start.desc())
        .first()
    )
    if active:
        return active

    # 2. Nearest upcoming
    upcoming = (
        ShiftWeek.query
        .filter(ShiftWeek.status == 'published', ShiftWeek.week_start > today)
        .order_by(ShiftWeek.week_start.asc())
        .first()
    )
    if upcoming:
        return upcoming

    # 3. Most recent past
    return (
        ShiftWeek.query
        .filter(ShiftWeek.status == 'published', ShiftWeek.week_start < today)
        .order_by(ShiftWeek.week_start.desc())
        .first()
    )


@app.route('/admin/schedule')
@login_required
def admin_schedule_index():
    """List all ShiftWeeks and form to create a new week. Super admin only."""
    if (r := require_super_admin()):
        return r
    weeks = ShiftWeek.query.order_by(ShiftWeek.week_start.asc()).all()
    return render_template('admin/schedule_index.html', weeks=weeks)


@app.route('/admin/schedule/create', methods=['POST'])
@login_required
def admin_schedule_create():
    """Create a ShiftWeek + Shifts from the week form. Super admin only."""
    if (r := require_super_admin()):
        return r

    monday_str = request.form.get('week_start', '').strip()
    if not monday_str:
        flash("Please select a Monday date.", "error")
        return redirect(url_for('admin_schedule_index'))

    try:
        week_start = datetime.strptime(monday_str, '%Y-%m-%d').date()
    except ValueError:
        flash("Invalid date format.", "error")
        return redirect(url_for('admin_schedule_index'))

    if week_start.weekday() != 0:
        flash("Week must start on a Monday.", "error")
        return redirect(url_for('admin_schedule_index'))

    if ShiftWeek.query.filter_by(week_start=week_start).first():
        flash("A schedule for that week already exists.", "error")
        return redirect(url_for('admin_schedule_index'))

    week = ShiftWeek(week_start=week_start, status='draft', created_by_id=current_user.id)
    db.session.add(week)
    db.session.flush()

    for day in _SHIFT_DAY_ORDER:
        for slot in ('am', 'pm'):
            active = request.form.get(f"slot_{day}_{slot}") == 'on'
            shift = Shift(
                week_id=week.id,
                day_of_week=day,
                slot=slot,
                trucks=2,
                is_active=active,
            )
            db.session.add(shift)

    db.session.commit()
    flash(f"Week of {week_start.strftime('%B %-d')} created.", "success")
    return redirect(url_for('admin_schedule_week', week_id=week.id))


@app.route('/admin/schedule/<int:week_id>')
@login_required
def admin_schedule_week(week_id):
    """Schedule builder view for a single week. Super admin only."""
    if (r := require_super_admin()):
        return r
    week = ShiftWeek.query.get_or_404(week_id)

    # All approved workers for the dropdowns
    all_workers = User.query.filter_by(is_worker=True, worker_status='approved').order_by(User.full_name).all()

    # For each shift, build per-slot availability set
    worker_availability = {}  # {worker_id: set of "day_slot" strings}
    for w in all_workers:
        avail = _get_worker_availability_for_week(w, week.week_start)
        available_slots = set()
        if avail:
            for day in _SHIFT_DAY_ORDER:
                for slot in ('am', 'pm'):
                    if getattr(avail, f"{day}_{slot}", False):
                        available_slots.add(f"{day}_{slot}")
        worker_availability[w.id] = available_slots

    shifts_sorted = sorted([s for s in week.shifts], key=lambda s: s.sort_key)
    has_any_assignments = any(s.assignments for s in week.shifts if s.is_active)

    drivers_per_truck = int(AppSetting.get('drivers_per_truck', '2'))
    organizers_per_truck = int(AppSetting.get('organizers_per_truck', '2'))

    return render_template(
        'admin/schedule_week.html',
        week=week,
        shifts=shifts_sorted,
        all_workers=all_workers,
        worker_availability=worker_availability,
        has_any_assignments=has_any_assignments,
        drivers_per_truck=drivers_per_truck,
        organizers_per_truck=organizers_per_truck,
    )


@app.route('/admin/schedule/<int:week_id>/optimize', methods=['POST'])
@login_required
def admin_schedule_optimize(week_id):
    """Run optimizer for the week. Clears and rewrites all ShiftAssignments."""
    if (r := require_super_admin()):
        return r
    week = ShiftWeek.query.get_or_404(week_id)
    result = _run_optimizer(week)
    total = result['total']
    fully = result['fully_staffed']
    under = result['understaffed']
    if total == 0:
        flash("No active shifts found. Add shifts before optimizing.", "info")
    else:
        msg = f"Optimizer ran. {fully} of {total} shifts fully staffed."
        if under:
            msg += f" {under} shift{'s' if under != 1 else ''} understaffed — see below."
        flash(msg, "success")
    return redirect(url_for('admin_schedule_week', week_id=week_id))


@app.route('/admin/schedule/<int:week_id>/publish', methods=['POST'])
@login_required
def admin_schedule_publish(week_id):
    """Publish the schedule and email all assigned workers."""
    if (r := require_super_admin()):
        return r
    week = ShiftWeek.query.get_or_404(week_id)

    # Collect workers with ≥1 assignment
    assigned_worker_ids = set(
        a.worker_id
        for shift in week.shifts if shift.is_active
        for a in shift.assignments
    )
    if not assigned_worker_ids:
        flash("Cannot publish — no workers are assigned yet.", "error")
        return redirect(url_for('admin_schedule_week', week_id=week_id))

    week.status = 'published'
    db.session.commit()

    # Send publish emails
    week_label = week.week_start.strftime('%B %-d')
    notified = 0
    for worker_id in assigned_worker_ids:
        worker = User.query.get(worker_id)
        if not worker:
            continue
        # Build their personal shift list
        my_shifts = [
            a for shift in sorted([s for s in week.shifts if s.is_active], key=lambda s: s.sort_key)
            for a in shift.assignments if a.worker_id == worker_id
        ]
        shift_lines = ''.join(
            f"<li>{a.shift.label} — {'Mover' if a.role_on_shift == 'driver' else 'Organizer'}</li>"
            for a in my_shifts
        )
        body = wrap_email_template(f"""
            <h2>Your Campus Swap Schedule — Week of {week_label}</h2>
            <p>Hey {worker.full_name.split()[0]},</p>
            <p>Your schedule for the week of {week_label} is set. Here are your shifts:</p>
            <ul>{shift_lines}</ul>
            <p><a href="{request.host_url.rstrip('/')}/crew" style="color:#C8832A;">View your crew portal →</a></p>
            <p>Questions? Reply to this email or reach out to your admin.</p>
        """)
        try:
            send_email(worker.email, f"Your Campus Swap Schedule — Week of {week_label}", body)
            notified += 1
        except Exception as e:
            logger.error(f"Failed to send publish email to {worker.email}: {e}")

    flash(f"Schedule published. {notified} worker{'s' if notified != 1 else ''} notified.", "success")
    return redirect(url_for('admin_schedule_week', week_id=week_id))


@app.route('/admin/schedule/<int:week_id>/unpublish', methods=['POST'])
@login_required
def admin_schedule_unpublish(week_id):
    """Return week to draft status. Silent — no worker emails."""
    if (r := require_super_admin()):
        return r
    week = ShiftWeek.query.get_or_404(week_id)
    week.status = 'draft'
    db.session.commit()
    flash("Schedule returned to draft.", "success")
    return redirect(url_for('admin_schedule_week', week_id=week_id))


@app.route('/admin/schedule/<int:week_id>/delete', methods=['POST'])
@login_required
def admin_schedule_delete(week_id):
    """Delete a ShiftWeek and all its shifts, assignments, and associated ops data."""
    if (r := require_super_admin()):
        return r
    week = ShiftWeek.query.get_or_404(week_id)
    if week.status == 'published':
        flash("Unpublish the schedule before deleting it.", "error")
        return redirect(url_for('admin_schedule_week', week_id=week_id))

    week_label = week.week_start.strftime('%b %-d, %Y')
    week_id_val = week.id  # capture before we touch anything

    # Collect shift IDs via a scalar query — do NOT load Shift ORM objects.
    # Loading them would put them in the identity map and cause SQLAlchemy to
    # emit a stale UPDATE when we later delete the rows directly.
    shift_ids = [row[0] for row in
                 db.session.execute(
                     db.select(Shift.id).where(Shift.week_id == week_id_val)
                 ).fetchall()]

    # Delete bottom-up (children before parents, all via bulk SQL).
    # synchronize_session=False keeps the ORM identity map out of the picture.
    if shift_ids:
        IntakeFlag.query.filter(IntakeFlag.shift_id.in_(shift_ids)).delete(synchronize_session=False)
        IntakeRecord.query.filter(IntakeRecord.shift_id.in_(shift_ids)).delete(synchronize_session=False)
        ShiftPickup.query.filter(ShiftPickup.shift_id.in_(shift_ids)).delete(synchronize_session=False)
        ShiftRun.query.filter(ShiftRun.shift_id.in_(shift_ids)).delete(synchronize_session=False)
        ShiftAssignment.query.filter(ShiftAssignment.shift_id.in_(shift_ids)).delete(synchronize_session=False)
        Shift.query.filter(Shift.week_id == week_id_val).delete(synchronize_session=False)

    # Delete the week itself via bulk SQL — avoids db.session.delete(week) which
    # would trigger ORM cascade logic and try to UPDATE already-deleted Shift rows.
    ShiftWeek.query.filter_by(id=week_id_val).delete(synchronize_session=False)
    db.session.commit()
    flash(f"Week of {week_label} deleted.", "success")
    return redirect(url_for('admin_schedule_index'))


@app.route('/admin/schedule/shift/<int:shift_id>/update', methods=['POST'])
@login_required
def admin_shift_update(shift_id):
    """Save trucks count and manual assignment changes for one shift."""
    if (r := require_super_admin()):
        return r
    shift = Shift.query.get_or_404(shift_id)

    max_trucks = int(AppSetting.get('max_trucks_per_shift', '4'))
    try:
        new_trucks = int(request.form.get('trucks', shift.trucks))
        new_trucks = max(1, min(new_trucks, max_trucks))
    except (ValueError, TypeError):
        new_trucks = shift.trucks

    shift.trucks = new_trucks

    # Process manual driver assignments
    import math as _math
    drivers_per_truck = int(AppSetting.get('drivers_per_truck', '2'))
    drivers_needed = new_trucks * drivers_per_truck
    organizers_needed = _math.ceil(new_trucks / 2) * 2

    # Remove all existing assignments and replace with submitted form data
    ShiftAssignment.query.filter_by(shift_id=shift.id).delete()
    db.session.flush()

    # Collect submitted worker IDs for each role
    driver_ids = request.form.getlist('driver_ids')
    organizer_ids = request.form.getlist('organizer_ids')

    seen_workers = set()
    driver_slot_index = 0
    for wid in driver_ids[:drivers_needed]:
        try:
            wid_int = int(wid)
        except (ValueError, TypeError):
            continue
        if wid_int in seen_workers:
            continue
        seen_workers.add(wid_int)
        truck_num = (driver_slot_index // drivers_per_truck) + 1
        db.session.add(ShiftAssignment(
            shift_id=shift.id,
            worker_id=wid_int,
            role_on_shift='driver',
            truck_number=truck_num,
            assigned_by_id=current_user.id,
        ))
        driver_slot_index += 1

    for wid in organizer_ids[:organizers_needed]:
        try:
            wid_int = int(wid)
        except (ValueError, TypeError):
            continue
        if wid_int in seen_workers:
            continue
        seen_workers.add(wid_int)
        db.session.add(ShiftAssignment(
            shift_id=shift.id,
            worker_id=wid_int,
            role_on_shift='organizer',
            assigned_by_id=current_user.id,
        ))

    db.session.commit()
    flash(f"{shift.label} saved.", "success")
    return redirect(url_for('admin_schedule_week', week_id=shift.week_id) + f'#shift-{shift_id}')


@app.route('/admin/schedule/shift/<int:shift_id>/swap', methods=['POST'])
@login_required
def admin_shift_swap(shift_id):
    """Replace one worker on a shift. Sends swap emails to removed and added workers."""
    if (r := require_super_admin()):
        return r
    shift = Shift.query.get_or_404(shift_id)

    remove_assignment_id = request.form.get('remove_assignment_id', type=int)
    replacement_worker_id = request.form.get('replacement_worker_id', type=int)

    if not remove_assignment_id or not replacement_worker_id:
        flash("Invalid swap request.", "error")
        return redirect(url_for('admin_schedule_week', week_id=shift.week_id))

    old_assignment = ShiftAssignment.query.get_or_404(remove_assignment_id)
    if old_assignment.shift_id != shift.id:
        flash("Assignment does not belong to this shift.", "error")
        return redirect(url_for('admin_schedule_week', week_id=shift.week_id))

    removed_worker = User.query.get(old_assignment.worker_id)
    replacement_worker = User.query.get_or_404(replacement_worker_id)
    role = old_assignment.role_on_shift

    # Remove old assignment
    db.session.delete(old_assignment)
    db.session.flush()

    # Add new assignment
    new_assignment = ShiftAssignment(
        shift_id=shift.id,
        worker_id=replacement_worker_id,
        role_on_shift=role,
        assigned_by_id=current_user.id,
    )
    db.session.add(new_assignment)
    db.session.commit()

    # Send swap emails
    shift_label = shift.label
    crew_url = f"{request.host_url.rstrip('/')}/crew"

    if removed_worker:
        try:
            send_email(
                removed_worker.email,
                "Campus Swap Shift Update",
                wrap_email_template(f"""
                    <h2>Campus Swap Shift Update</h2>
                    <p>Hey {removed_worker.full_name.split()[0]},</p>
                    <p>Your <strong>{shift_label}</strong> shift assignment has been updated.
                    Please contact your admin with any questions.</p>
                """),
            )
        except Exception as e:
            logger.error(f"Failed to send swap removal email to {removed_worker.email}: {e}")

    # Only email new worker if they have no other assignments this week (they may already know)
    other_assignments = [
        a for s in shift.week.shifts if s.is_active and s.id != shift.id
        for a in s.assignments if a.worker_id == replacement_worker_id
    ]
    try:
        send_email(
            replacement_worker.email,
            "You've Been Scheduled — Campus Swap",
            wrap_email_template(f"""
                <h2>You've Been Scheduled — Campus Swap</h2>
                <p>Hey {replacement_worker.full_name.split()[0]},</p>
                <p>You've been added to the <strong>{shift_label}</strong> shift as a
                <strong>{role.capitalize()}</strong>.</p>
                <p><a href="{crew_url}" style="color:#C8832A;">View your crew portal →</a></p>
            """),
        )
    except Exception as e:
        logger.error(f"Failed to send swap addition email to {replacement_worker.email}: {e}")

    flash(f"Swap complete: {removed_worker.full_name if removed_worker else 'worker'} replaced by {replacement_worker.full_name}.", "success")
    return redirect(url_for('admin_schedule_week', week_id=shift.week_id) + f'#shift-{shift_id}')


@app.route('/crew/schedule/<int:week_id>')
@login_required
def crew_schedule_week(week_id):
    """Full week schedule HTML partial. Requires approved worker. Returns partial HTML (no layout)."""
    if (r := require_crew()):
        return r
    week = ShiftWeek.query.get_or_404(week_id)
    if week.status != 'published':
        return "Schedule not available.", 403
    shifts_sorted = sorted([s for s in week.shifts if s.is_active], key=lambda s: s.sort_key)
    return render_template(
        'crew/schedule_week_partial.html',
        week=week,
        shifts=shifts_sorted,
        current_user=current_user,
    )


def seed_crew_app_settings():
    """Seed AppSetting keys needed by the crew/ops system. Safe to call multiple times — only sets if missing."""
    defaults = {
        'crew_applications_open': 'true',
        'crew_allowed_email_domain': '',
        'availability_deadline_day': 'tuesday',
        'drivers_per_truck': '2',
        'organizers_per_truck': '2',
        'max_trucks_per_shift': '4',
        'shifts_required': '10',
        # Referral program defaults
        'referral_base_rate': '20',
        'referral_signup_bonus': '10',
        'referral_bonus_per_referral': '10',
        'referral_max_rate': '100',
        'referral_program_active': 'true',
        # Admin UI Redesign: pickup window for shift auto-generation
        'pickup_week_start': '',
        'pickup_week_end': '',
    }
    for key, value in defaults.items():
        if AppSetting.get(key) is None:
            db.session.add(AppSetting(key=key, value=value))
    db.session.commit()


@app.cli.command('backfill-referral-codes')
def backfill_referral_codes():
    """One-time: generate referral codes for all users who don't have one yet."""
    count = 0
    users = User.query.filter(User.referral_code == None).all()
    for user in users:
        user.referral_code = generate_unique_referral_code()
        count += 1
    db.session.commit()
    print(f"Assigned referral codes to {count} existing users.")


# =========================================================
# SPEC #6 — ROUTE PLANNING HELPERS
# =========================================================

import math as _math

def get_item_unit_size(item):
    """Return effective unit size for an item: per-item override > category default > 1.0."""
    if item.unit_size is not None:
        return item.unit_size
    if item.category and item.category.default_unit_size is not None:
        return item.category.default_unit_size
    return 1.0


def get_seller_unit_count(seller):
    """Sum of unit sizes for all 'available' items belonging to this seller."""
    items = InventoryItem.query.filter_by(seller_id=seller.id, status='available').all()
    return sum(get_item_unit_size(i) for i in items)


def get_effective_capacity():
    """Effective truck capacity = floor(raw * (1 - buffer/100))."""
    raw = float(AppSetting.get('truck_raw_capacity', '18'))
    buffer = float(AppSetting.get('truck_capacity_buffer_pct', '10'))
    return _math.floor(raw * (1 - buffer / 100))


def build_geographic_clusters(sellers):
    """
    Group sellers into geographic clusters for display on the route builder.
    Returns list of {'label': str, 'sellers': [User]} dicts.
    Priority:
      1. Named building: pickup_partner_building (partner apt) OR pickup_dorm when on_campus
      2. Off-campus proximity: haversine < 0.25 miles
      3. Unlocated: no lat/lng, no building
    """
    clusters = {}   # label -> list of sellers
    remaining = []  # sellers not yet placed in a named cluster

    for s in sellers:
        # Partner apartment (explicit building name)
        if s.pickup_partner_building:
            label = s.pickup_partner_building
            clusters.setdefault(label, []).append(s)
            continue
        # On-campus dorm
        if s.pickup_location_type == 'on_campus' and s.pickup_dorm:
            label = s.pickup_dorm
            clusters.setdefault(label, []).append(s)
            continue
        remaining.append(s)

    # Proximity clustering for remaining sellers
    clustered_set = set()
    proximity_clusters = []

    for i, s in enumerate(remaining):
        if s.id in clustered_set:
            continue
        if s.pickup_lat is None or s.pickup_lng is None:
            continue
        group = [s]
        clustered_set.add(s.id)
        for j, other in enumerate(remaining):
            if other.id in clustered_set:
                continue
            if other.pickup_lat is None or other.pickup_lng is None:
                continue
            dist = haversine_miles(s.pickup_lat, s.pickup_lng, other.pickup_lat, other.pickup_lng)
            if dist < 0.25:
                group.append(other)
                clustered_set.add(other.id)
        street_label = (s.pickup_address or '').split(',')[0].strip() or 'Off-Campus'
        proximity_clusters.append({'label': street_label, 'sellers': group})

    # Unlocated
    unlocated = [s for s in remaining if s.id not in clustered_set]

    result = [{'label': k, 'sellers': v} for k, v in clusters.items()]
    result.extend(proximity_clusters)
    if unlocated:
        result.append({'label': 'Unlocated', 'sellers': unlocated})
    return result


def build_static_map_url(truck_stops, storage_location):
    """
    Build a Google Maps Static API URL for a truck's stop list.
    Returns None if maps_static_api_key is not set.
    truck_stops: list of ShiftPickup objects
    storage_location: StorageLocation object (needs .lat / .lng)
    """
    api_key = AppSetting.get('maps_static_api_key', '')
    if not api_key:
        return None

    base = 'https://maps.googleapis.com/maps/api/staticmap?size=600x300'
    params = []

    if storage_location and getattr(storage_location, 'lat', None) and getattr(storage_location, 'lng', None):
        params.append(f'markers=label:S|{storage_location.lat},{storage_location.lng}')

    for i, pickup in enumerate(truck_stops, start=1):
        seller = pickup.seller
        if seller and seller.pickup_lat and seller.pickup_lng:
            params.append(f'markers=label:{i}|{seller.pickup_lat},{seller.pickup_lng}')

    params.append(f'key={api_key}')
    return base + '&' + '&'.join(params)


def _run_auto_assignment():
    """
    Auto-assign all eligible sellers (available items, no existing ShiftPickup, pickup_week set)
    to the best-fit shift+truck.
    Returns dict: {assigned: [ids], tbd: [{seller_id, reason}], over_cap_warnings: [pickup_ids]}
    """
    from sqlalchemy import func as _func

    effective_cap = get_effective_capacity()

    # All seller_ids that already have a ShiftPickup
    existing_pickup_ids = {p.seller_id for p in ShiftPickup.query.all()}

    # Eligible sellers: has available items, no pickup yet, pickup_week set, address complete
    eligible_sellers = [
        s for s in (
            User.query
            .join(InventoryItem, InventoryItem.seller_id == User.id)
            .filter(
                InventoryItem.status == 'available',
                User.pickup_week.isnot(None),
                User.id.notin_(existing_pickup_ids),
            )
            .group_by(User.id)
            .all()
        )
        if s.has_pickup_location
    ]

    # Cluster-first sort (Admin UI Redesign spec):
    # 1. Partner buildings (alphabetical) → dorms/on-campus (alphabetical) → proximity → Unlocated
    # 2. Within cluster: unit count descending
    _clusters = build_geographic_clusters(eligible_sellers)

    def _cluster_sort_key(label):
        """Return a tuple for ordering cluster labels by priority."""
        from constants import OFF_CAMPUS_COMPLEXES
        if label == 'Unlocated':
            return (3, label)
        # Partner building: pickup_partner_building set — these appear as named buildings
        # Check if label matches any seller's pickup_partner_building
        for c in _clusters:
            if c['label'] == label and c['sellers']:
                s0 = c['sellers'][0]
                if s0.pickup_partner_building and s0.pickup_partner_building == label:
                    return (0, label)
                if s0.pickup_location_type == 'on_campus':
                    return (1, label)
        return (2, label)  # proximity cluster

    ordered_sellers = []
    sorted_cluster_labels = sorted([c['label'] for c in _clusters], key=_cluster_sort_key)
    cluster_by_label = {c['label']: c['sellers'] for c in _clusters}
    for lbl in sorted_cluster_labels:
        cluster_sellers = sorted(
            cluster_by_label.get(lbl, []),
            key=lambda s: get_seller_unit_count(s),
            reverse=True,
        )
        ordered_sellers.extend(cluster_sellers)

    seller_units = [(s, get_seller_unit_count(s)) for s in ordered_sellers]

    assigned = []
    tbd = []
    over_cap_warnings = []

    # Map slot preference: 'morning' → 'am', 'afternoon' → 'pm'
    def _pref_to_slot(pref):
        if pref == 'morning':
            return 'am'
        if pref == 'afternoon':
            return 'pm'
        return pref  # fall through for 'evening' or None

    for seller, unit_count in seller_units:
        pref_slot = _pref_to_slot(seller.pickup_time_preference)

        # Candidate shifts: same week, matching slot (if preference set)
        query = Shift.query.join(ShiftWeek, Shift.week_id == ShiftWeek.id)
        query = query.filter(ShiftWeek.week_start.isnot(None))

        # Filter by seller.pickup_week (week1/week2) based on week_start ranges
        # week1 = Apr 27–May 3, week2 = May 4–May 10
        from datetime import date
        if seller.pickup_week == 'week1':
            query = query.filter(ShiftWeek.week_start >= date(2026, 4, 27),
                                 ShiftWeek.week_start <= date(2026, 5, 3))
        elif seller.pickup_week == 'week2':
            query = query.filter(ShiftWeek.week_start >= date(2026, 5, 4),
                                 ShiftWeek.week_start <= date(2026, 5, 10))

        if pref_slot in ('am', 'pm'):
            query = query.filter(Shift.slot == pref_slot)

        candidates = query.filter(Shift.is_active == True).all()

        # Spec #8: filter out shifts on or after seller's move-out date
        if seller.moveout_date:
            from datetime import date as _date
            _day_order_aa = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
            filtered = []
            for _s in candidates:
                if _s.week and _s.week.week_start:
                    _sd = _s.week.week_start + timedelta(days=_day_order_aa.index(_s.day_of_week))
                    if _sd < seller.moveout_date:
                        filtered.append(_s)
            candidates = filtered
            if not candidates:
                tbd.append({'seller_id': seller.id, 'reason': f'No eligible shift before move-out date ({seller.moveout_date})'})
                continue

        if not candidates:
            slot_label = pref_slot.upper() if pref_slot in ('am', 'pm') else 'any'
            week_label = seller.pickup_week.replace('week', 'Week ') if seller.pickup_week else '?'
            tbd.append({'seller_id': seller.id, 'reason': f'No {slot_label} shifts in {week_label}'})
            continue

        # For each candidate shift, compute current load per truck, pick best truck
        best_shift = None
        best_truck = None
        best_remaining = None

        for shift in candidates:
            existing_pickups = ShiftPickup.query.filter_by(shift_id=shift.id).all()
            truck_loads = {t: 0.0 for t in range(1, shift.trucks + 1)}
            for p in existing_pickups:
                if p.truck_number in truck_loads:
                    truck_loads[p.truck_number] += get_seller_unit_count(p.seller)

            # Best truck = lowest load
            best_t = min(truck_loads, key=lambda t: truck_loads[t])
            remaining = effective_cap - truck_loads[best_t]

            if best_shift is None or remaining > best_remaining:
                best_shift = shift
                best_truck = best_t
                best_remaining = remaining

        # Find existing truck load for the best truck
        existing_pickups = ShiftPickup.query.filter_by(shift_id=best_shift.id, truck_number=best_truck).all()
        current_load = sum(get_seller_unit_count(p.seller) for p in existing_pickups)
        over_cap = (current_load + unit_count) > effective_cap

        pickup = ShiftPickup(
            shift_id=best_shift.id,
            seller_id=seller.id,
            truck_number=best_truck,
            status='pending',
            capacity_warning=over_cap,
            created_by_id=None,
        )
        db.session.add(pickup)
        db.session.flush()
        assigned.append(seller.id)
        if over_cap:
            over_cap_warnings.append(pickup.id)

    db.session.commit()
    return {
        'assigned': assigned,
        'tbd': tbd,
        'over_cap_warnings': over_cap_warnings,
    }


# ── Spec #6 routes — admin shift extensions ──────────────────────────────────

@app.route('/admin/crew/shift/<int:shift_id>/add-truck', methods=['POST'])
@login_required
def admin_shift_add_truck(shift_id):
    """Increment Shift.trucks by 1. New truck = max existing + 1."""
    if not current_user.is_admin:
        abort(403)
    # Use raw SQL to avoid mutating the ORM identity-mapped object in the caller's session.
    from sqlalchemy import text as _text
    row = db.session.execute(_text("SELECT trucks FROM shift WHERE id=:id"), {'id': shift_id}).fetchone()
    if not row:
        abort(404)
    new_truck_number = row[0] + 1
    db.session.execute(_text("UPDATE shift SET trucks=:t WHERE id=:id"), {'t': new_truck_number, 'id': shift_id})
    db.session.commit()
    # If called from the ops panel form (has Accept: text/html and no JSON), redirect back
    accept = request.headers.get('Accept', '')
    if 'text/html' in accept and not request.is_json and not request.headers.get('X-Requested-With'):
        return redirect(url_for('admin_ops', shift_id=shift_id))
    return jsonify({'new_truck_number': new_truck_number})


@app.route('/admin/crew/shift/<int:shift_id>/order', methods=['POST'])
@login_required
def admin_shift_order_stops(shift_id):
    """Run nearest-neighbor stop ordering; write stop_order to all ShiftPickups for this shift."""
    if not current_user.is_admin:
        abort(403)
    shift = Shift.query.get_or_404(shift_id)

    # Determine storage unit origin
    import json as _json
    truck_unit_plan = _json.loads(shift.truck_unit_plan or '{}')
    origin_loc = None
    for truck_key, loc_id in truck_unit_plan.items():
        loc = StorageLocation.query.get(loc_id)
        if loc and loc.lat and loc.lng:
            origin_loc = loc
            break

    pickups = ShiftPickup.query.filter_by(shift_id=shift.id).all()
    if not pickups:
        flash("No stops to order.", "info")
        return redirect(url_for('admin_shift_ops', shift_id=shift_id))

    if origin_loc is None:
        # Fallback to insertion order
        for i, p in enumerate(sorted(pickups, key=lambda x: x.id), start=1):
            p.stop_order = i
        db.session.commit()
        flash("Storage unit has no coordinates — stops ordered by insertion order.", "info")
        return redirect(url_for('admin_shift_ops', shift_id=shift_id))

    # Nearest-neighbor from storage location
    with_coords = [p for p in pickups if p.seller.pickup_lat and p.seller.pickup_lng]
    without_coords = [p for p in pickups if not p.seller.pickup_lat or not p.seller.pickup_lng]

    current_lat, current_lng = origin_loc.lat, origin_loc.lng
    ordered = []
    unvisited = list(with_coords)

    while unvisited:
        best = min(unvisited, key=lambda p: haversine_miles(
            current_lat, current_lng, p.seller.pickup_lat, p.seller.pickup_lng))
        ordered.append(best)
        current_lat, current_lng = best.seller.pickup_lat, best.seller.pickup_lng
        unvisited.remove(best)

    # Assign stop_order
    for i, p in enumerate(ordered, start=1):
        p.stop_order = i
    for i, p in enumerate(without_coords, start=len(ordered) + 1):
        p.stop_order = i

    db.session.commit()
    flash("Route ordered.", "success")
    referrer = request.referrer or ''
    if '/admin/ops' in referrer:
        return redirect(url_for('admin_ops', shift_id=shift_id))
    return redirect(url_for('admin_shift_ops', shift_id=shift_id))


@app.route('/admin/crew/shift/<int:shift_id>/stop/<int:pickup_id>/reorder', methods=['POST'])
@login_required
def admin_shift_reorder_stop(shift_id, pickup_id):
    """Set a specific stop_order value on a pickup."""
    if not current_user.is_admin:
        abort(403)
    pickup = ShiftPickup.query.get_or_404(pickup_id)
    if pickup.shift_id != shift_id:
        abort(404)
    data = request.get_json(silent=True) or {}
    stop_order = data.get('stop_order')
    if stop_order is None:
        return jsonify({'error': 'stop_order required'}), 400
    pickup.stop_order = int(stop_order)
    db.session.commit()
    return jsonify({'stop_order': pickup.stop_order})


@app.route('/admin/crew/shift/<int:shift_id>/notify', methods=['POST'])
@login_required
def admin_shift_notify_sellers(shift_id):
    """Send pickup confirmation email to all unnotified sellers on this shift. Idempotent."""
    if not current_user.is_admin:
        abort(403)
    shift = Shift.query.get_or_404(shift_id)
    pickups = ShiftPickup.query.filter_by(shift_id=shift_id).filter(
        ShiftPickup.notified_at == None).all()

    am_window = AppSetting.get('route_am_window', '9am–1pm')
    pm_window = AppSetting.get('route_pm_window', '1pm–5pm')
    time_window = am_window if shift.slot == 'am' else pm_window

    shift_day_str = shift.label  # e.g. "Monday AM"

    base_url = os.environ.get('APP_BASE_URL', 'https://usecampusswap.com').rstrip('/')
    sent_count = 0
    for pickup in pickups:
        seller = pickup.seller
        if not seller or not seller.email:
            continue
        first_name = seller.full_name.split()[0] if seller.full_name else 'there'
        try:
            # Spec #8: generate reschedule token (idempotent — piggybacks on notify loop)
            token_rec = _get_or_create_reschedule_token(pickup)
            reschedule_url = f"{base_url}/reschedule/{token_rec.token}"
            html = wrap_email_template(f"""
                <h2>Your Campus Swap pickup is confirmed!</h2>
                <p>Hi {first_name},</p>
                <p>Your pickup has been scheduled for <strong>{shift_day_str}</strong>, {time_window}.</p>
                <p>Our team will arrive at your location during this window to collect your items.
                Please make sure everything is ready and accessible.</p>
                <p>If you have any questions, reply to this email or reach out at
                <a href="mailto:hello@usecampusswap.com">hello@usecampusswap.com</a>.</p>
                <p>Thanks for selling with Campus Swap!</p>
                <p style="margin-top:24px; padding-top:20px; border-top:1px solid #e2e8f0; text-align:center;">
                  <a href="{reschedule_url}"
                     style="display:inline-block; padding:10px 22px; background:#f5f0e8; color:#1A3D1A; border:1px solid #d8d0c4; border-radius:8px; text-decoration:none; font-size:0.9rem; font-weight:600;">
                    Need to reschedule? Pick a new time &rarr;
                  </a>
                </p>
            """)
            send_email(seller.email, f"Your Campus Swap pickup is {shift_day_str}", html)
            # Spec #9: also send SMS alongside email
            shift_date_obj = _shift_date(shift)
            day_label = shift_date_obj.strftime('%A, %b %-d')
            slot_label = 'AM' if shift.slot == 'am' else 'PM'
            _send_sms(
                seller,
                f"Your Campus Swap pickup is scheduled for {day_label} {slot_label}. "
                f"We'll text you the day before as a reminder. Reply STOP to opt out."
            )
            pickup.notified_at = _now_eastern()
            sent_count += 1
        except Exception as e:
            logger.error(f"Failed to send pickup notification to {seller.email}: {e}")

    if sent_count > 0 or not pickups:
        shift.sellers_notified = True
        shift.last_notified_at = _now_eastern()
    db.session.commit()

    flash(f"Notified {sent_count} seller(s).", "success")
    # Redirect to new ops page if coming from there, otherwise fall back to old shift ops
    referrer = request.referrer or ''
    if '/admin/ops' in referrer:
        return redirect(url_for('admin_ops', shift_id=shift_id))
    return redirect(url_for('admin_shift_ops', shift_id=shift_id))


# ── Spec #9 — Cron Routes & SMS Webhook ──────────────────────────────────────

def _cron_auth_ok():
    """Return True if the request carries a valid CRON_SECRET Bearer token."""
    secret = os.environ.get('CRON_SECRET', '')
    if not secret:
        return False
    auth_header = request.headers.get('Authorization', '')
    provided = auth_header.removeprefix('Bearer ').strip()
    return provided == secret


@app.route('/admin/cron/sms-reminders', methods=['POST'])
@csrf.exempt
def cron_sms_reminders():
    """
    Daily cron — send 24hr SMS reminder to sellers whose pickup is tomorrow.
    Auth: Authorization: Bearer <CRON_SECRET>
    Schedule: 9am ET (or sms_reminder_hour_eastern AppSetting).
    NOTE: This cron is NOT idempotent — if run twice in one day it sends duplicate SMS.
    """
    if not _cron_auth_ok():
        return jsonify({'error': 'Unauthorized'}), 403

    tomorrow = _today_eastern() + timedelta(days=1)
    sent = 0
    skipped = 0

    # Load all active shifts and filter to those falling on tomorrow
    _DAY_ORDER_C = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
    shifts_tomorrow = [
        s for s in Shift.query.filter_by(is_active=True).all()
        if s.week and (s.week.week_start + timedelta(days=_DAY_ORDER_C.index(s.day_of_week))) == tomorrow
    ]

    for shift in shifts_tomorrow:
        day_label = tomorrow.strftime('%A, %b %-d')
        slot_label = 'AM' if shift.slot == 'am' else 'PM'
        for pickup in shift.pickups:
            # Only remind sellers who were notified and aren't in an issue state
            if not pickup.notified_at or pickup.status == 'issue':
                skipped += 1
                continue
            ok = _send_sms(
                pickup.seller,
                f"Reminder: Campus Swap is picking up your stuff tomorrow, "
                f"{day_label} {slot_label}. See you then! Reply STOP to opt out."
            )
            if ok:
                sent += 1
            else:
                skipped += 1

    return jsonify({'sent': sent, 'skipped': skipped})


@app.route('/admin/cron/no-show-emails', methods=['POST'])
@csrf.exempt
def cron_no_show_emails():
    """
    End-of-day cron — send warm recovery email to sellers whose stop was flagged no-show today.
    Auth: Authorization: Bearer <CRON_SECRET>
    Schedule: 6pm ET (or no_show_email_hour_eastern AppSetting).
    Idempotent: no_show_email_sent_at guards against duplicate sends.
    """
    if not _cron_auth_ok():
        return jsonify({'error': 'Unauthorized'}), 403

    if AppSetting.get('no_show_email_enabled', 'true').lower() != 'true':
        # Count pending stops for reporting
        pending_count = ShiftPickup.query.filter_by(
            issue_type='no_show', no_show_email_sent_at=None
        ).count()
        return jsonify({'sent': 0, 'skipped': pending_count})

    base_url = os.environ.get('APP_BASE_URL', 'https://usecampusswap.com').rstrip('/')
    today = _today_eastern()
    _DAY_ORDER_C = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
    sent = 0
    skipped = 0

    candidates = ShiftPickup.query.filter_by(
        issue_type='no_show', no_show_email_sent_at=None
    ).all()

    for pickup in candidates:
        # Only email for shifts on or before today (don't email before pickup day)
        if not pickup.shift or not pickup.shift.week:
            skipped += 1
            continue
        shift_date = pickup.shift.week.week_start + timedelta(
            days=_DAY_ORDER_C.index(pickup.shift.day_of_week)
        )
        if shift_date > today:
            skipped += 1
            continue

        # Find an active reschedule token
        token = RescheduleToken.query.filter_by(
            pickup_id=pickup.id, used_at=None, revoked_at=None
        ).first()
        if not token:
            logger.warning(
                f'cron_no_show_emails: no active token for pickup {pickup.id} '
                f'(seller {pickup.seller_id}) — skipped'
            )
            skipped += 1
            continue

        reschedule_url = f"{base_url}/reschedule/{token.token}"
        seller = pickup.seller
        first_name = seller.full_name.split()[0] if seller.full_name else 'there'

        try:
            html = wrap_email_template(f"""
                <h2>We're sorry we missed you, {first_name}!</h2>
                <p>Hi {first_name},</p>
                <p>We stopped by today for your Campus Swap pickup but it looks like we missed
                each other — no worries at all, things come up!</p>
                <p>We'd love to come back and grab your stuff. Click below to pick a new time
                that works for you:</p>
                <p style="text-align:center; margin:28px 0;">
                  <a href="{reschedule_url}"
                     style="display:inline-block; padding:14px 28px; background:#C8832A; color:white; border-radius:10px; text-decoration:none; font-size:1rem; font-weight:700;">
                    Reschedule My Pickup &rarr;
                  </a>
                </p>
                <p>If you have any questions, reply to this email or reach out at
                <a href="mailto:hello@usecampusswap.com">hello@usecampusswap.com</a>.</p>
                <p>Thanks for your patience — we'll make it work!</p>
            """)
            send_email(seller.email, f"We're sorry we missed you, {first_name}!", html)
            pickup.no_show_email_sent_at = _now_eastern().replace(tzinfo=None)
            db.session.commit()
            sent += 1
        except Exception as e:
            logger.error(
                f'cron_no_show_emails: failed to email seller {seller.id} '
                f'for pickup {pickup.id}: {e}'
            )
            skipped += 1

    return jsonify({'sent': sent, 'skipped': skipped})


@app.route('/sms/webhook', methods=['POST'])
@csrf.exempt
def sms_inbound_webhook():
    """
    Twilio inbound SMS webhook — handles STOP/UNSTOP replies.
    No login required. Twilio signature validated.
    After deploy, set webhook URL in Twilio console:
    Phone Numbers → Manage → Active Numbers → [your number] → Messaging → Webhook URL
    Set to: https://usecampusswap.com/sms/webhook (HTTP POST)
    """
    auth_token = os.environ.get('TWILIO_AUTH_TOKEN', '')
    if auth_token:
        # Validate Twilio signature
        try:
            from twilio.request_validator import RequestValidator
            validator = RequestValidator(auth_token)
            # Use the full HTTPS URL for signature validation
            base_url = os.environ.get('APP_BASE_URL', 'https://usecampusswap.com').rstrip('/')
            url = f"{base_url}/sms/webhook"
            signature = request.headers.get('X-Twilio-Signature', '')
            if not validator.validate(url, request.form, signature):
                logger.warning('sms_inbound_webhook: invalid Twilio signature — 403')
                return Response('Forbidden', status=403)
        except Exception as e:
            logger.error(f'sms_inbound_webhook: signature validation error: {e}')
            return Response('Forbidden', status=403)
    else:
        # No auth token configured — skip validation (dev/test environment)
        logger.warning('sms_inbound_webhook: TWILIO_AUTH_TOKEN not set, skipping signature check')

    body = (request.form.get('Body') or '').strip().upper()
    from_number = request.form.get('From', '').strip()

    # Opt-out keywords (per CTIA/Twilio standards)
    OPT_OUT_KEYWORDS  = {'STOP', 'STOPALL', 'UNSUBSCRIBE', 'CANCEL', 'END', 'QUIT'}
    OPT_IN_KEYWORDS   = {'START', 'UNSTOP', 'YES'}

    if body in OPT_OUT_KEYWORDS or body in OPT_IN_KEYWORDS:
        normalized = _normalize_phone(from_number)
        user = None
        if normalized:
            # Match on both stored formats (normalized and raw)
            all_users = User.query.filter(User.phone.isnot(None)).all()
            for u in all_users:
                if _normalize_phone(u.phone) == normalized:
                    user = u
                    break
        if not user:
            logger.warning(f'sms_inbound_webhook: no user found for {from_number}')
        else:
            user.sms_opted_out = body in OPT_OUT_KEYWORDS
            db.session.commit()
            logger.info(
                f'sms_inbound_webhook: user {user.id} sms_opted_out={user.sms_opted_out} '
                f'(keyword: {body})'
            )

    # Always return empty TwiML — never 404 (Twilio retries on errors)
    return Response('<Response/>', status=200, mimetype='text/xml')


# ── Route Builder ────────────────────────────────────────────────────────────

@app.route('/admin/routes')
@login_required
def admin_routes_index():
    """Route planner — redirects to /admin/ops (Admin UI Redesign)."""
    if not current_user.is_admin:
        abort(403)
    return redirect(url_for('admin_ops'), 302)


def _admin_routes_index_data():
    """Internal: build the route planner data (used by admin_ops)."""
    # Sellers with available items and a pickup_week set (include only those)
    assigned_seller_ids = {p.seller_id for p in ShiftPickup.query.all()}
    unassigned_sellers = [
        s for s in (
            User.query
            .join(InventoryItem, InventoryItem.seller_id == User.id)
            .filter(
                InventoryItem.status == 'available',
                User.pickup_week.isnot(None),
                User.id.notin_(assigned_seller_ids),
            )
            .group_by(User.id)
            .order_by(User.full_name)
            .all()
        )
        if s.has_pickup_location
    ]

    clusters = build_geographic_clusters(unassigned_sellers)

    # All shifts for all active weeks
    weeks = ShiftWeek.query.filter_by(status='published').order_by(ShiftWeek.week_start).all()
    all_shifts = []
    for week in weeks:
        all_shifts.extend([s for s in week.shifts if s.is_active])
    all_shifts.sort(key=lambda s: (s.week.week_start, s.sort_key))

    effective_cap = get_effective_capacity()

    # Compute capacity data per shift + truck
    from collections import defaultdict
    shift_truck_data = {}
    for shift in all_shifts:
        pickups = ShiftPickup.query.filter_by(shift_id=shift.id).order_by(
            ShiftPickup.truck_number, nulls_last(ShiftPickup.stop_order.asc()), ShiftPickup.id).all()
        trucks_data = {}
        for truck_num in range(1, shift.trucks + 1):
            truck_pickups = [p for p in pickups if p.truck_number == truck_num]
            load = sum(get_seller_unit_count(p.seller) for p in truck_pickups)
            trucks_data[truck_num] = {
                'pickups': truck_pickups,
                'load': load,
                'effective_cap': effective_cap,
            }
        shift_truck_data[shift.id] = trucks_data

    # Seller unit counts for display
    seller_unit_counts = {s.id: get_seller_unit_count(s) for s in unassigned_sellers}

    # All shifts for the "assign to" dropdowns (all trucks across all shifts)
    shift_truck_options = []
    for shift in all_shifts:
        for t in range(1, shift.trucks + 1):
            shift_truck_options.append({
                'shift': shift,
                'truck_number': t,
                'label': f"{shift.label} (week of {shift.week.week_start.strftime('%b %-d')}) — Truck {t}",
            })

    # Count stats — "ready" means pickup_week set + address complete (matches assignment eligibility)
    all_ready_sellers = [
        s for s in (
            User.query
            .join(InventoryItem, InventoryItem.seller_id == User.id)
            .filter(InventoryItem.status == 'available', User.pickup_week.isnot(None))
            .group_by(User.id)
            .all()
        )
        if s.has_pickup_location
    ]
    total_with_items = len(all_ready_sellers)
    total_assigned = len(assigned_seller_ids & {s.id for s in all_ready_sellers})
    total_unassigned = len(unassigned_sellers)

    # Over-cap warnings
    overcap_pickups = ShiftPickup.query.filter_by(capacity_warning=True).all()

    return {
        'clusters': clusters,
        'all_shifts': all_shifts,
        'shift_truck_data': shift_truck_data,
        'seller_unit_counts': seller_unit_counts,
        'shift_truck_options': shift_truck_options,
        'effective_cap': effective_cap,
        'total_with_items': total_with_items,
        'total_assigned': total_assigned,
        'total_unassigned': total_unassigned,
        'overcap_pickups': overcap_pickups,
    }


@app.route('/admin/routes/auto-assign', methods=['POST'])
@login_required
def admin_routes_auto_assign():
    """Run auto-assignment for all unassigned sellers. Returns JSON."""
    if not current_user.is_admin:
        abort(403)
    result = _run_auto_assignment()
    return jsonify(result)


@app.route('/admin/routes/stop/<int:pickup_id>/move', methods=['POST'])
@login_required
def admin_routes_move_stop(pickup_id):
    """Move a ShiftPickup to a different shift + truck. Returns JSON."""
    if not current_user.is_admin:
        abort(403)
    pickup = ShiftPickup.query.get_or_404(pickup_id)
    data = request.get_json(silent=True) or {}
    new_shift_id = data.get('shift_id')
    new_truck = data.get('truck_number')
    if not new_shift_id or not new_truck:
        return jsonify({'error': 'shift_id and truck_number required'}), 400

    original_shift_id = pickup.shift_id
    pickup.shift_id = int(new_shift_id)
    pickup.truck_number = int(new_truck)

    # Spec #8: clear notified_at when shift identity changes (email copy would be wrong)
    if pickup.shift_id != original_shift_id:
        pickup.notified_at = None

    # Recompute capacity warning for this pickup on the new truck
    effective_cap = get_effective_capacity()
    truck_pickups = ShiftPickup.query.filter_by(
        shift_id=pickup.shift_id, truck_number=pickup.truck_number).all()
    load = sum(get_seller_unit_count(p.seller) for p in truck_pickups if p.id != pickup.id)
    seller_units = get_seller_unit_count(pickup.seller)
    pickup.capacity_warning = (load + seller_units) > effective_cap

    db.session.commit()
    return jsonify({'ok': True, 'capacity_warning': pickup.capacity_warning})


@app.route('/admin/routes/seller/<int:user_id>/assign', methods=['POST'])
@login_required
def admin_routes_assign_seller(user_id):
    """Manually assign a single unassigned seller to a shift + truck. Returns JSON (409 if already has ShiftPickup)."""
    if not current_user.is_admin:
        abort(403)
    seller = User.query.get_or_404(user_id)

    if not seller.pickup_week or not seller.has_pickup_location:
        return jsonify({'error': 'Seller has not set their pickup week and address'}), 422

    # Global uniqueness check
    existing = ShiftPickup.query.filter_by(seller_id=user_id).first()
    if existing:
        return jsonify({'error': 'Seller already has a pickup assignment'}), 409

    # Accept JSON body OR form-encoded shift_truck="shift_id_truck_num" (from ops panel)
    data = request.get_json(silent=True) or {}
    shift_id = data.get('shift_id')
    truck_number = data.get('truck_number')
    if not shift_id or not truck_number:
        # Fall back to form data: shift_truck = "<shift_id>_<truck_number>"
        shift_truck_raw = request.form.get('shift_truck', '')
        parts = shift_truck_raw.split('_') if shift_truck_raw else []
        if len(parts) == 2:
            shift_id, truck_number = parts[0], parts[1]
    if not shift_id or not truck_number:
        if request.is_json or not request.form:
            return jsonify({'error': 'shift_id and truck_number required'}), 400
        flash("Could not determine shift and truck for assignment.", "error")
        return redirect(url_for('admin_ops'))

    shift = Shift.query.get_or_404(int(shift_id))
    effective_cap = get_effective_capacity()
    truck_pickups = ShiftPickup.query.filter_by(shift_id=shift.id, truck_number=int(truck_number)).all()
    load = sum(get_seller_unit_count(p.seller) for p in truck_pickups)
    seller_units = get_seller_unit_count(seller)
    over_cap = (load + seller_units) > effective_cap

    pickup = ShiftPickup(
        shift_id=shift.id,
        seller_id=seller.id,
        truck_number=int(truck_number),
        status='pending',
        capacity_warning=over_cap,
        created_by_id=current_user.id,
    )
    db.session.add(pickup)
    db.session.commit()
    # If request came from the ops panel form (not JSON), redirect back
    if not request.is_json and request.form:
        return redirect(url_for('admin_ops', shift_id=shift.id))
    return jsonify({'ok': True, 'pickup_id': pickup.id, 'capacity_warning': over_cap})


@app.route('/admin/settings/route', methods=['GET', 'POST'])
@login_required
def admin_route_settings():
    """Route capacity + category unit size settings. Super admin only."""
    if not current_user.is_super_admin:
        abort(403)
    if request.method == 'GET':
        return redirect(url_for('admin_settings') + '#route', 302)
    categories = InventoryCategory.query.order_by(InventoryCategory.name).all()
    if request.method == 'POST':
        # Save AppSettings
        for key in ['truck_raw_capacity', 'truck_capacity_buffer_pct',
                    'route_am_window', 'route_pm_window', 'maps_static_api_key',
                    'sms_enabled', 'sms_reminder_hour_eastern',
                    'no_show_email_enabled', 'no_show_email_hour_eastern']:
            val = request.form.get(key)
            if val is not None:
                AppSetting.set(key, val.strip())
        # Save per-category unit sizes
        for cat in categories:
            field_key = f'category_unit_{cat.id}'
            val = request.form.get(field_key, '').strip()
            if val:
                try:
                    cat.default_unit_size = float(val)
                except ValueError:
                    pass
        db.session.commit()
        flash("Route settings saved.", "success")
        return redirect(url_for('admin_route_settings'))
    return render_template(
        'admin/route_settings.html',
        categories=categories,
        truck_raw_capacity=AppSetting.get('truck_raw_capacity', '18'),
        truck_capacity_buffer_pct=AppSetting.get('truck_capacity_buffer_pct', '10'),
        route_am_window=AppSetting.get('route_am_window', '9am–1pm'),
        route_pm_window=AppSetting.get('route_pm_window', '1pm–5pm'),
        maps_static_api_key=AppSetting.get('maps_static_api_key', ''),
        effective_cap=get_effective_capacity(),
        sms_enabled=AppSetting.get('sms_enabled', 'true'),
        sms_reminder_hour_eastern=AppSetting.get('sms_reminder_hour_eastern', '9'),
        no_show_email_enabled=AppSetting.get('no_show_email_enabled', 'true'),
        no_show_email_hour_eastern=AppSetting.get('no_show_email_hour_eastern', '18'),
    )


# ── Spec #9 — SMS Helpers ────────────────────────────────────────────────────

def _normalize_phone(raw):
    """
    Normalize a raw phone string to E.164 (+1XXXXXXXXXX).
    Returns normalized string on success, None on failure.
    """
    if not raw:
        return None
    digits = re.sub(r'\D', '', raw)
    if len(digits) == 10:
        return f'+1{digits}'
    if len(digits) == 11 and digits.startswith('1'):
        return f'+{digits}'
    if raw.startswith('+') and len(digits) == 11:
        return f'+{digits}'
    return None


def _send_sms(user, body):
    """
    Send an SMS via Twilio. Silently returns False (no exception raised) if:
      - sms_enabled AppSetting is 'false'
      - user.phone is None or empty
      - user.sms_opted_out is True
      - TWILIO_* env vars are not set
    Returns True on successful API call. Logs warnings on skip/failure.
    """
    if AppSetting.get('sms_enabled', 'true').lower() != 'true':
        return False

    if not user or not user.phone:
        return False

    if user.sms_opted_out:
        return False

    account_sid = os.environ.get('TWILIO_ACCOUNT_SID', '')
    auth_token  = os.environ.get('TWILIO_AUTH_TOKEN', '')
    from_number = os.environ.get('TWILIO_FROM_NUMBER', '')
    if not account_sid or not auth_token or not from_number:
        logger.warning('_send_sms: Twilio env vars not set — SMS skipped')
        return False

    to_number = _normalize_phone(user.phone)
    if not to_number:
        logger.warning(f'_send_sms: unparseable phone "{user.phone}" for user {user.id} — skipped')
        return False

    try:
        from twilio.rest import Client as TwilioClient
        client = TwilioClient(account_sid, auth_token)
        client.messages.create(body=body, from_=from_number, to=to_number)
        return True
    except Exception as e:
        logger.error(f'_send_sms: Twilio error for user {user.id}: {e}')
        return False


# ── Spec #8 — Seller Rescheduling ────────────────────────────────────────────

_DAY_ORDER_RS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']


def _shift_date(shift):
    """Return the calendar date of a Shift object."""
    return shift.week.week_start + timedelta(days=_DAY_ORDER_RS.index(shift.day_of_week))


def _get_or_create_reschedule_token(pickup):
    """Return a valid unused token for this pickup, creating one if needed. Caller commits."""
    ttl = int(AppSetting.get('reschedule_token_ttl_days', '7'))
    # Use naive datetime — SQLite/Postgres store datetimes without tzinfo
    now = _now_eastern().replace(tzinfo=None)
    existing = (RescheduleToken.query
        .filter_by(pickup_id=pickup.id)
        .filter(RescheduleToken.used_at.is_(None))
        .filter(RescheduleToken.expires_at > now)
        .order_by(RescheduleToken.created_at.desc())
        .first())
    if existing:
        return existing
    rec = RescheduleToken(
        token=secrets.token_urlsafe(48),
        pickup_id=pickup.id,
        seller_id=pickup.seller_id,
        created_at=now,
        expires_at=now + timedelta(days=ttl),
    )
    db.session.add(rec)
    return rec


def _get_eligible_reschedule_slots(pickup):
    """
    Return a set of (date, slot) tuples the seller can reschedule into.
    Covers ALL dates in the defined pickup window — not just days with existing Shift records.
    Uncreated slots are auto-created in _get_or_create_shift_for_date when submitted.
    """
    from constants import PICKUP_WEEK_DATE_RANGES
    from datetime import date as _date_type

    seller = pickup.seller
    today = _today_eastern()
    current_shift = pickup.shift
    current_date = _shift_date(current_shift)

    # Full set of date/slot combos across all defined pickup weeks
    all_slots = set()
    for _wk, (start_str, end_str) in PICKUP_WEEK_DATE_RANGES.items():
        d = _date_type.fromisoformat(start_str)
        end = _date_type.fromisoformat(end_str)
        while d <= end:
            all_slots.add((d, 'am'))
            all_slots.add((d, 'pm'))
            d += timedelta(days=1)

    # Existing Shift lookup for locked / in-progress checks
    _day_names_rs = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
    existing_shifts = {}
    for s in Shift.query.join(ShiftWeek, Shift.week_id == ShiftWeek.id).all():
        if s.week and s.week.week_start:
            sd = s.week.week_start + timedelta(days=_day_names_rs.index(s.day_of_week))
            existing_shifts[(sd, s.slot)] = s

    eligible = set()
    for (d, slot) in all_slots:
        if d < today:
            continue
        if d == today:
            if not (current_date == today and current_shift.slot == 'am' and slot == 'pm'):
                continue
        if seller.moveout_date and d >= seller.moveout_date:
            continue
        existing = existing_shifts.get((d, slot))
        if existing:
            if existing.reschedule_locked:
                continue
            if existing.run and existing.run.status == 'in_progress':
                continue
        eligible.add((d, slot))

    return eligible


def _get_or_create_shift_for_date(target_date, slot):
    """
    Get or create a ShiftWeek + Shift for the given date and slot.
    Called when a seller reschedules to a slot admin hasn't created yet.
    Caller must commit after this returns.
    """
    _day_names_rs = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
    day_of_week = _day_names_rs[target_date.weekday()]
    week_start = target_date - timedelta(days=target_date.weekday())

    week = ShiftWeek.query.filter_by(week_start=week_start).first()
    if not week:
        week = ShiftWeek(week_start=week_start, status='published', created_by_id=None)
        db.session.add(week)
        db.session.flush()

    shift = Shift.query.filter_by(week_id=week.id, day_of_week=day_of_week, slot=slot).first()
    if not shift:
        shift = Shift(week_id=week.id, day_of_week=day_of_week, slot=slot, trucks=1, is_active=True)
        db.session.add(shift)
        db.session.flush()

    return shift


def _build_reschedule_grid(eligible_slots, current_shift):
    """
    Build week-grouped grid data for the reschedule page.
    Shows all weeks defined in PICKUP_WEEK_DATE_RANGES (the full pickup window).
    eligible_slots is a set of (date, slot) tuples from _get_eligible_reschedule_slots.
    Returns (weeks, initial_week_idx).
    """
    from constants import PICKUP_WEEK_DATE_RANGES
    from datetime import date as _date_type

    current_shift_date = _shift_date(current_shift)
    cs_monday = current_shift_date - timedelta(days=current_shift_date.weekday())
    current_key = (current_shift_date, current_shift.slot)

    # The weeks to show = all pickup window weeks + the current shift's week if outside
    week_mondays = set()
    for _wk, (start_str, _end_str) in PICKUP_WEEK_DATE_RANGES.items():
        week_mondays.add(_date_type.fromisoformat(start_str))
    week_mondays.add(cs_monday)

    weeks = []
    initial_week_idx = 0
    for ws in sorted(week_mondays):
        dates = [ws + timedelta(days=i) for i in range(7)]
        rows = {'am': [], 'pm': []}
        for d in dates:
            for slot in ('am', 'pm'):
                key = (d, slot)
                rows[slot].append({
                    'date': d,
                    'slot': slot,
                    'is_current': key == current_key,
                    'eligible': key in eligible_slots,
                    'disabled': key not in eligible_slots and key != current_key,
                })
        end_of_week = ws + timedelta(days=6)
        label = ws.strftime('%b %-d') + ' – ' + end_of_week.strftime('%b %-d')
        weeks.append({'week_start': ws, 'label': label, 'dates': dates, 'rows': rows})
        if ws == cs_monday:
            initial_week_idx = len(weeks) - 1

    return weeks, initial_week_idx


def _send_admin_reschedule_alert(pickup, old_shift, new_shift):
    """Send an immediate email alert to admin when a seller reschedules urgently."""
    admin_email = os.environ.get('ADMIN_EMAIL')
    if not admin_email:
        return
    seller = pickup.seller
    old_date = _shift_date(old_shift).strftime('%A, %b %-d')
    new_date = _shift_date(new_shift).strftime('%A, %b %-d')
    base_url = os.environ.get('APP_BASE_URL', 'https://usecampusswap.com').rstrip('/')
    seller_link = f"{base_url}/admin/seller/{seller.id}"
    now_str = _now_eastern().strftime('%b %-d at %-I:%M %p ET')
    subject = f"Reschedule alert: {seller.full_name} — {old_shift.label} -> {new_shift.label}"
    html = wrap_email_template(f"""
        <h2>Seller Reschedule Alert</h2>
        <p><strong>{seller.full_name}</strong> has rescheduled their pickup.</p>
        <ul>
          <li><strong>From:</strong> {old_shift.label} ({old_date})</li>
          <li><strong>To:</strong> {new_shift.label} ({new_date})</li>
          <li><strong>Rescheduled at:</strong> {now_str}</li>
        </ul>
        <p><a href="{seller_link}">View seller profile &rarr;</a></p>
    """)
    try:
        send_email(admin_email, subject, html)
    except Exception as e:
        logger.error(f"Failed to send admin reschedule alert: {e}")


def _do_reschedule(pickup, new_shift):
    """Move a ShiftPickup to new_shift cleanly. Commits the session."""
    overflow_truck = new_shift.overflow_truck_number or 1
    old_shift = pickup.shift  # hold reference before mutation

    # Repack remaining stop_order values on old route
    remaining = (ShiftPickup.query
        .filter_by(shift_id=old_shift.id)
        .filter(ShiftPickup.id != pickup.id)
        .order_by(nulls_last(ShiftPickup.stop_order.asc()), ShiftPickup.id)
        .all())
    for i, p in enumerate(remaining, start=1):
        p.stop_order = i

    # Move to new shift
    pickup.shift_id = new_shift.id
    pickup.truck_number = overflow_truck
    pickup.stop_order = None          # appended last; shown at bottom of mover list
    pickup.rescheduled_from_shift_id = old_shift.id
    pickup.rescheduled_at = _now_eastern()
    pickup.notified_at = None         # fresh notification needed for new shift

    # Capacity warning on overflow truck
    existing_count = ShiftPickup.query.filter_by(
        shift_id=new_shift.id, truck_number=overflow_truck
    ).count()
    effective_cap = get_effective_capacity()
    pickup.capacity_warning = (existing_count >= effective_cap)

    db.session.commit()

    # Admin alert — immediate email only if shift is soon
    days_until = (_shift_date(new_shift) - _today_eastern()).days
    threshold = int(AppSetting.get('reschedule_urgent_alert_days', '2'))
    if days_until <= threshold:
        _send_admin_reschedule_alert(pickup, old_shift, new_shift)


@app.route('/reschedule/<token>', methods=['GET'])
def seller_reschedule_get(token):
    """Token-gated reschedule page — no login required."""
    rec = RescheduleToken.query.filter_by(token=token).first_or_404()
    # Spec #9: revoked_at check must come before used_at (completed pickup supersedes reschedule)
    if rec.revoked_at:
        return render_template('seller/reschedule_confirm.html',
                               error='revoked', new_shift=None, token=token)
    if rec.used_at:
        return render_template('seller/reschedule_confirm.html',
                               error='already_used', new_shift=None, token=token)
    if rec.expires_at < _now_eastern().replace(tzinfo=None):
        return render_template('seller/reschedule_confirm.html',
                               error='expired', new_shift=None, token=token)
    pickup = rec.pickup
    run = pickup.shift.run
    if run and run.status == 'in_progress':
        return render_template('seller/reschedule_confirm.html',
                               error='underway', new_shift=None, token=token)
    eligible_slots = _get_eligible_reschedule_slots(pickup)
    weeks, initial_week_idx = _build_reschedule_grid(eligible_slots, pickup.shift)
    current_shift = pickup.shift
    current_shift_date_str = _shift_date(current_shift).strftime('%B %-d') if current_shift.week else ''
    return render_template('seller/reschedule.html',
                           token=token, pickup=pickup,
                           weeks=weeks, initial_week_idx=initial_week_idx,
                           has_eligible=bool(eligible_slots),
                           current_shift=current_shift,
                           current_shift_date_str=current_shift_date_str,
                           form_action=url_for('seller_reschedule_post', token=token))


def _parse_and_validate_slot(pickup, redirect_fn):
    """
    Parse new_slot_key from form (format 'YYYY-MM-DD:am'/'YYYY-MM-DD:pm'),
    validate eligibility. Returns (new_date, slot, error_response).
    error_response is non-None if validation failed.
    """
    from datetime import date as _date_type
    slot_key = request.form.get('new_slot_key', '')
    try:
        date_str, slot = slot_key.rsplit(':', 1)
        new_date = _date_type.fromisoformat(date_str)
        assert slot in ('am', 'pm')
    except Exception:
        flash("Please select a new time slot.", "error")
        return None, None, redirect_fn()
    eligible_slots = _get_eligible_reschedule_slots(pickup)
    if (new_date, slot) not in eligible_slots:
        return None, None, (abort(400) or '')
    current_date = _shift_date(pickup.shift)
    if new_date == current_date and slot == pickup.shift.slot:
        flash("No changes made.", "info")
        return None, None, redirect(url_for('dashboard'))
    return new_date, slot, None


@app.route('/reschedule/<token>', methods=['POST'])
def seller_reschedule_post(token):
    """Submit reschedule via token — no login required."""
    rec = RescheduleToken.query.filter_by(token=token).first_or_404()
    # Spec #9: revoked_at check must come before used_at
    if rec.revoked_at:
        return render_template('seller/reschedule_confirm.html',
                               error='revoked', new_shift=None, token=token)
    if rec.used_at:
        return render_template('seller/reschedule_confirm.html',
                               error='already_used', new_shift=None, token=token)
    if rec.expires_at < _now_eastern().replace(tzinfo=None):
        return render_template('seller/reschedule_confirm.html',
                               error='expired', new_shift=None, token=token)
    pickup = rec.pickup
    run = pickup.shift.run
    if run and run.status == 'in_progress':
        return render_template('seller/reschedule_confirm.html',
                               error='underway', new_shift=None, token=token)

    new_date, slot, err = _parse_and_validate_slot(pickup, lambda: redirect(url_for('seller_reschedule_get', token=token)))
    if err is not None:
        return err
    new_shift = _get_or_create_shift_for_date(new_date, slot)
    _do_reschedule(pickup, new_shift)
    rec.used_at = _now_eastern().replace(tzinfo=None)
    db.session.commit()
    return render_template('seller/reschedule_confirm.html',
                           error=None, new_shift=new_shift, token=None)


@app.route('/seller/reschedule', methods=['GET'])
@login_required
def seller_reschedule_auth_get():
    """Auth-gated reschedule page for logged-in sellers."""
    pickup = ShiftPickup.query.filter_by(seller_id=current_user.id).first()
    if not pickup:
        abort(404)
    run = pickup.shift.run
    if run and run.status == 'in_progress':
        return render_template('seller/reschedule_confirm.html',
                               error='underway', new_shift=None, token=None)
    eligible_slots = _get_eligible_reschedule_slots(pickup)
    weeks, initial_week_idx = _build_reschedule_grid(eligible_slots, pickup.shift)
    current_shift = pickup.shift
    current_shift_date_str = _shift_date(current_shift).strftime('%B %-d') if current_shift.week else ''
    return render_template('seller/reschedule.html',
                           token=None, pickup=pickup,
                           weeks=weeks, initial_week_idx=initial_week_idx,
                           has_eligible=bool(eligible_slots),
                           current_shift=current_shift,
                           current_shift_date_str=current_shift_date_str,
                           form_action=url_for('seller_reschedule_auth_post'))


@app.route('/seller/reschedule', methods=['POST'])
@login_required
def seller_reschedule_auth_post():
    """Submit reschedule via auth session."""
    pickup = ShiftPickup.query.filter_by(seller_id=current_user.id).first()
    if not pickup:
        abort(404)
    run = pickup.shift.run
    if run and run.status == 'in_progress':
        return render_template('seller/reschedule_confirm.html',
                               error='underway', new_shift=None, token=None)
    new_date, slot, err = _parse_and_validate_slot(pickup, lambda: redirect(url_for('seller_reschedule_auth_get')))
    if err is not None:
        return err
    new_shift = _get_or_create_shift_for_date(new_date, slot)
    _do_reschedule(pickup, new_shift)
    return render_template('seller/reschedule_confirm.html',
                           error=None, new_shift=new_shift, token=None)


@app.route('/admin/crew/shift/<int:shift_id>/set-overflow-truck', methods=['POST'])
@login_required
def admin_set_overflow_truck(shift_id):
    """Set or toggle the overflow truck designation for a shift."""
    if not current_user.is_admin:
        abort(403)
    shift = Shift.query.get_or_404(shift_id)
    truck_number = request.form.get('truck_number', type=int)
    if truck_number is None:
        flash("truck_number required.", "error")
        return redirect(url_for('admin_shift_ops', shift_id=shift_id))
    shift.overflow_truck_number = (
        None if shift.overflow_truck_number == truck_number else truck_number
    )
    db.session.commit()
    flash("Overflow truck updated.", "success")
    return redirect(url_for('admin_shift_ops', shift_id=shift_id))


@app.route('/admin/crew/shift/<int:shift_id>/toggle-reschedule-lock', methods=['POST'])
@login_required
def admin_toggle_reschedule_lock(shift_id):
    """Toggle the reschedule lock on a shift."""
    if not current_user.is_admin:
        abort(403)
    shift = Shift.query.get_or_404(shift_id)
    shift.reschedule_locked = not shift.reschedule_locked
    db.session.commit()
    msg = "Rescheduling locked." if shift.reschedule_locked else "Rescheduling unlocked."
    flash(msg, "success")
    return redirect(url_for('admin_shift_ops', shift_id=shift_id))


@app.route('/crew/shift/<int:shift_id>/stops_partial')
@login_required
def crew_shift_stops_partial(shift_id):
    """HTML partial of stops for current mover's truck. Used by 30-second auto-refresh."""
    if (r := require_crew()):
        return r
    shift = Shift.query.get_or_404(shift_id)
    # Find the worker's truck assignment for this shift
    assignment = ShiftAssignment.query.filter_by(
        shift_id=shift_id, worker_id=current_user.id, role_on_shift='driver'
    ).first()
    if not assignment or not assignment.truck_number:
        return '<div id="stop-list"><p style="color:var(--text-muted);font-size:0.875rem;">No stops assigned.</p></div>'

    pickups = (
        ShiftPickup.query
        .filter_by(shift_id=shift_id, truck_number=assignment.truck_number)
        .order_by(nulls_last(ShiftPickup.stop_order.asc()), ShiftPickup.id)
        .all()
    )
    item_counts = {}
    for p in pickups:
        item_counts[p.seller_id] = InventoryItem.query.filter_by(
            seller_id=p.seller_id, status='available').count()

    return render_template(
        'crew/stops_partial.html',
        shift=shift,
        pickups=pickups,
        item_counts=item_counts,
    )


# =========================================================
# ADMIN UI REDESIGN — New routes (spec: feature_admin_redesign.md)
# =========================================================

_DAY_ORDER_OPS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
_DAY_LABELS_OPS = {
    'mon': 'Mon', 'tue': 'Tue', 'wed': 'Wed',
    'thu': 'Thu', 'fri': 'Fri', 'sat': 'Sat', 'sun': 'Sun',
}
_MONTH_LABELS = {
    1:'Jan',2:'Feb',3:'Mar',4:'Apr',5:'May',6:'Jun',
    7:'Jul',8:'Aug',9:'Sep',10:'Oct',11:'Nov',12:'Dec',
}


def _ops_shift_date(shift):
    """Calendar date for a Shift (week_start + day_of_week offset)."""
    return shift.week.week_start + timedelta(days=_DAY_ORDER_OPS.index(shift.day_of_week))


def _ops_build_truck_cards(shift, pickups, effective_cap):
    """
    Build per-truck card data for the Ops main content area.
    Returns list of dicts (one per truck), sorted by truck_number.
    """
    from collections import defaultdict
    import json as _json

    truck_unit_plan = _json.loads(shift.truck_unit_plan or '{}')
    storage_loc_by_id = {loc.id: loc for loc in StorageLocation.query.filter_by(is_active=True).all()}
    truck_planned_unit = {
        int(k): storage_loc_by_id.get(v)
        for k, v in truck_unit_plan.items()
        if storage_loc_by_id.get(v)
    }

    pickups_by_truck = defaultdict(list)
    for p in pickups:
        pickups_by_truck[p.truck_number].append(p)

    shift_run = ShiftRun.query.filter_by(shift_id=shift.id).first()

    cards = []
    for truck_num in range(1, shift.trucks + 1):
        truck_stops = pickups_by_truck[truck_num]
        load = sum(get_seller_unit_count(p.seller) for p in truck_stops)
        storage_loc = truck_planned_unit.get(truck_num)

        # Live state
        live = None
        if shift_run:
            stops_done = sum(1 for p in truck_stops if p.status == 'completed')
            stops_issue = sum(1 for p in truck_stops if p.status == 'issue')
            current_stop = next(
                (p for p in sorted(truck_stops, key=lambda p: (p.stop_order is None, p.stop_order or 0))
                 if p.status == 'pending'), None
            )
            live = {
                'status': shift_run.status,
                'stops_total': len(truck_stops),
                'stops_done': stops_done,
                'stops_issue': stops_issue,
                'items_total': sum(
                    InventoryItem.query.filter_by(seller_id=p.seller_id, status='available').count()
                    for p in truck_stops
                ),
                'current_stop': current_stop,
                'has_issue': stops_issue > 0,
            }

        # "new" badge: created after last_notified_at or shift never notified
        def _is_new(p):
            if not shift.sellers_notified:
                return True
            if shift.last_notified_at and p.created_at and p.created_at > shift.last_notified_at:
                return True
            return False

        stop_rows = []
        for p in sorted(truck_stops, key=lambda p: (p.stop_order is None, p.stop_order or 0, p.id)):
            seller = p.seller
            unit_count = get_seller_unit_count(seller)
            map_url = None
            if storage_loc:
                map_url = build_static_map_url([p], storage_loc)
            stop_rows.append({
                'pickup': p,
                'seller': seller,
                'unit_count': unit_count,
                'is_new': _is_new(p),
                'is_rescheduled': p.rescheduled_from_shift_id is not None,
                'item_count': InventoryItem.query.filter_by(seller_id=seller.id, status='available').count(),
            })

        # Capacity bar pct
        cap_pct = min(round((load / effective_cap) * 100), 150) if effective_cap > 0 else 0

        cards.append({
            'truck_number': truck_num,
            'storage_loc': storage_loc,
            'load': load,
            'effective_cap': effective_cap,
            'cap_pct': cap_pct,
            'stop_rows': stop_rows,
            'live': live,
            'map_url': build_static_map_url(truck_stops, storage_loc) if storage_loc else None,
        })
    return cards, shift_run


def _ops_build_unassigned_panel(shift):
    """Build unassigned sellers pool for the right panel, filtered by shift slot."""
    assigned_seller_ids = {p.seller_id for p in ShiftPickup.query.all()}
    all_unassigned = [
        s for s in (
            User.query
            .join(InventoryItem, InventoryItem.seller_id == User.id)
            .filter(
                InventoryItem.status == 'available',
                User.pickup_week.isnot(None),
                User.id.notin_(assigned_seller_ids),
            )
            .group_by(User.id)
            .order_by(User.full_name)
            .all()
        )
        if s.has_pickup_location
    ]

    # Filter by pickup_week matching shift's week
    shift_week_start = shift.week.week_start if shift.week else None
    from datetime import date as _date_cls
    if shift_week_start:
        from constants import PICKUP_WEEK_DATE_RANGES
        # Determine which pickup_week (week1/week2/week3) this shift belongs to
        shift_date = _ops_shift_date(shift)
        shift_pickup_week = None
        for wk, (start_str, end_str) in PICKUP_WEEK_DATE_RANGES.items():
            start = _date_cls.fromisoformat(start_str)
            end = _date_cls.fromisoformat(end_str)
            if start <= shift_date <= end:
                shift_pickup_week = wk
                break

        def _slot_match(seller):
            pref = seller.pickup_time_preference
            if pref == 'morning' and shift.slot != 'am':
                return False
            if pref == 'afternoon' and shift.slot != 'pm':
                return False
            return True

        slot_matched = [s for s in all_unassigned if _slot_match(s)]
        slot_unmatched = [s for s in all_unassigned if not _slot_match(s)]
    else:
        slot_matched = all_unassigned
        slot_unmatched = []

    clusters = build_geographic_clusters(slot_matched)
    from datetime import datetime as _dt
    _now = datetime.utcnow()
    _24h_ago = _now - timedelta(hours=24)
    for s in slot_matched:
        s._is_new = bool(s.date_joined and s.date_joined > _24h_ago)
        s._unit_count = get_seller_unit_count(s)
    for s in slot_unmatched:
        s._is_new = bool(s.date_joined and s.date_joined > _24h_ago)
        s._unit_count = get_seller_unit_count(s)

    return {
        'clusters': clusters,
        'slot_unmatched': slot_unmatched,
        'total_unassigned': len(all_unassigned),
    }


def _ops_build_shift_list():
    """All shifts sorted by date+slot, grouped by ShiftWeek, for the left panel."""
    all_weeks = ShiftWeek.query.order_by(ShiftWeek.week_start.asc()).all()
    shift_list = []
    for week in all_weeks:
        week_shifts = sorted(
            [s for s in week.shifts if s.is_active],
            key=lambda s: s.sort_key
        )
        for sh in week_shifts:
            sh_date = _ops_shift_date(sh)
            pickups = ShiftPickup.query.filter_by(shift_id=sh.id).all()
            unnotified = sum(1 for p in pickups if p.notified_at is None)
            shift_list.append({
                'shift': sh,
                'week': week,
                'date': sh_date,
                'date_label': sh_date.strftime('%-d %b'),
                'day_label': _DAY_LABELS_OPS.get(sh.day_of_week, sh.day_of_week),
                'stop_count': len(pickups),
                'truck_count': sh.trucks,
                'unnotified_count': unnotified,
                'notified': sh.sellers_notified and unnotified == 0,
            })
    return all_weeks, shift_list


@app.route('/admin/ops')
@login_required
def admin_ops():
    """Main ops view — four-zone layout."""
    if not current_user.is_admin:
        abort(403)

    shift_id = request.args.get('shift_id', type=int)
    today = _today_eastern()

    # Select active shift
    if shift_id:
        shift = Shift.query.get_or_404(shift_id)
    else:
        shift = (Shift.query
                 .join(ShiftWeek, Shift.week_id == ShiftWeek.id)
                 .filter(ShiftWeek.week_start.isnot(None))
                 .filter(Shift.is_active == True)
                 .order_by(ShiftWeek.week_start.asc(), Shift.slot.asc())
                 .first())
        if shift:
            # Prefer shifts on or after today
            upcoming = (Shift.query
                        .join(ShiftWeek, Shift.week_id == ShiftWeek.id)
                        .filter(ShiftWeek.week_start.isnot(None))
                        .filter(Shift.is_active == True)
                        .all())
            future = [s for s in upcoming if _ops_shift_date(s) >= today]
            if future:
                shift = min(future, key=lambda s: (_ops_shift_date(s), s.sort_key))
            else:
                past = [s for s in upcoming]
                if past:
                    shift = max(past, key=lambda s: (_ops_shift_date(s), s.sort_key))

    all_weeks, shift_list = _ops_build_shift_list()

    if not shift:
        return render_template(
            'admin/ops.html',
            shift=None,
            all_weeks=all_weeks,
            shift_list=shift_list,
            cards=[],
            shift_run=None,
            unassigned={},
            unnotified_count=0,
            shift_date=None,
            storage_locations=[],
            shift_truck_options=[],
        )

    # Zone 2: truck cards
    effective_cap = get_effective_capacity()
    pickups = (
        ShiftPickup.query
        .filter_by(shift_id=shift.id)
        .order_by(ShiftPickup.truck_number.asc(),
                  nulls_last(ShiftPickup.stop_order.asc()),
                  ShiftPickup.id.asc())
        .all()
    )
    cards, shift_run = _ops_build_truck_cards(shift, pickups, effective_cap)
    unnotified_count = sum(1 for p in pickups if p.notified_at is None)

    # Zone 3: unassigned panel
    unassigned = _ops_build_unassigned_panel(shift)

    shift_date = _ops_shift_date(shift)

    # Storage locations for the "Assign unit" dropdown
    storage_locations = (
        StorageLocation.query
        .filter_by(is_active=True, is_full=False)
        .order_by(StorageLocation.name.asc())
        .all()
    )

    # Shift+truck options for the move-stop selector
    all_shifts_flat = sorted(
        [s for w in all_weeks for s in w.shifts if s.is_active],
        key=lambda s: (_ops_shift_date(s), s.sort_key)
    )
    shift_truck_options = []
    for s in all_shifts_flat:
        sd = _ops_shift_date(s)
        for t in range(1, s.trucks + 1):
            shift_truck_options.append({
                'shift': s,
                'truck_number': t,
                'label': f"{sd.strftime('%a %b %-d')} {'AM' if s.slot=='am' else 'PM'} — Truck {t}",
            })

    return render_template(
        'admin/ops.html',
        shift=shift,
        shift_date=shift_date,
        all_weeks=all_weeks,
        shift_list=shift_list,
        cards=cards,
        shift_run=shift_run,
        unassigned=unassigned,
        unnotified_count=unnotified_count,
        storage_locations=storage_locations,
        shift_truck_options=shift_truck_options,
        effective_cap=effective_cap,
    )


@app.route('/admin/ops/truck-detail')
@login_required
def admin_ops_truck_detail():
    """HTML partial for the truck detail modal/drawer."""
    if not current_user.is_admin:
        abort(403)
    shift_id = request.args.get('shift_id', type=int)
    truck_num = request.args.get('truck', type=int)
    if not shift_id or not truck_num:
        abort(400)
    shift = Shift.query.get_or_404(shift_id)
    shift_date = _ops_shift_date(shift)

    pickups = (
        ShiftPickup.query
        .filter_by(shift_id=shift_id, truck_number=truck_num)
        .order_by(nulls_last(ShiftPickup.stop_order.asc()), ShiftPickup.id.asc())
        .all()
    )
    shift_run = ShiftRun.query.filter_by(shift_id=shift_id).first()

    # Assigned movers for this truck
    movers = [a for a in shift.assignments
              if a.role_on_shift == 'driver' and a.truck_number == truck_num]

    effective_cap = get_effective_capacity()
    load = sum(get_seller_unit_count(p.seller) for p in pickups)

    # Storage location for this truck
    import json as _json
    truck_unit_plan = _json.loads(shift.truck_unit_plan or '{}')
    storage_loc_by_id = {loc.id: loc for loc in StorageLocation.query.filter_by(is_active=True).all()}
    storage_loc = storage_loc_by_id.get(truck_unit_plan.get(str(truck_num)))

    # Other shifts for "move stop" selector
    other_shifts = (Shift.query
                    .join(ShiftWeek, Shift.week_id == ShiftWeek.id)
                    .filter(Shift.is_active == True)
                    .all())
    move_options = []
    for s in sorted(other_shifts, key=lambda s: (_ops_shift_date(s), s.sort_key)):
        sd = _ops_shift_date(s)
        for t in range(1, s.trucks + 1):
            move_options.append({
                'shift': s,
                'truck_number': t,
                'label': f"{sd.strftime('%a %b %-d')} {'AM' if s.slot=='am' else 'PM'} — Truck {t}",
            })

    return render_template(
        'admin/ops_truck_detail.html',
        shift=shift,
        shift_date=shift_date,
        truck_number=truck_num,
        pickups=pickups,
        shift_run=shift_run,
        movers=movers,
        effective_cap=effective_cap,
        load=load,
        storage_loc=storage_loc,
        move_options=move_options,
    )


@app.route('/admin/items')
@login_required
def admin_items():
    """Items tab — approval queue + lifecycle table."""
    if not current_user.is_admin:
        abort(403)

    view = request.args.get('view', 'all')  # 'all' or 'approve'

    # Stats bar
    total_items = InventoryItem.query.count()
    pending_approval = InventoryItem.query.filter_by(status='pending_valuation').count()
    available_count = InventoryItem.query.filter_by(status='available').count()
    sold_count = InventoryItem.query.filter_by(status='sold').count()

    # Approval queue items (pending_valuation, for super admins)
    approval_items = []
    if current_user.is_super_admin:
        approval_items = (
            InventoryItem.query
            .filter_by(status='pending_valuation')
            .order_by(InventoryItem.date_added.asc())
            .all()
        )

    # All items for lifecycle table
    filter_cat = request.args.get('cat', type=int)
    filter_email = request.args.get('email', '').strip()
    filter_title = request.args.get('title', '').strip()

    items_q = InventoryItem.query
    if filter_cat:
        items_q = items_q.filter_by(category_id=filter_cat)
    if filter_email:
        seller_ids = [u.id for u in User.query.filter(User.email.ilike(f'%{filter_email}%')).all()]
        items_q = items_q.filter(InventoryItem.seller_id.in_(seller_ids))
    if filter_title:
        items_q = items_q.filter(InventoryItem.description.ilike(f'%{filter_title}%'))

    all_items = items_q.order_by(InventoryItem.date_added.desc()).all()
    categories = InventoryCategory.query.order_by(InventoryCategory.name).all()

    # Store controls
    pickup_period_active = get_pickup_period_active()
    reserve_only = AppSetting.get('reserve_only_mode', 'false') == 'true'
    store_open_date = AppSetting.get('store_open_date', '')
    shop_teaser_mode = AppSetting.get('shop_teaser_mode', 'false')

    return render_template(
        'admin/items.html',
        view=view,
        total_items=total_items,
        pending_approval=pending_approval,
        available_count=available_count,
        sold_count=sold_count,
        approval_items=approval_items,
        all_items=all_items,
        categories=categories,
        pickup_period_active=pickup_period_active,
        reserve_only=reserve_only,
        store_open_date=store_open_date,
        shop_teaser_mode=shop_teaser_mode,
        filter_cat=filter_cat,
        filter_email=filter_email,
        filter_title=filter_title,
    )


@app.route('/admin/sellers')
@login_required
def admin_sellers():
    """Sellers tab — list, pickup nudge, free-tier management."""
    if not current_user.is_admin:
        abort(403)

    sellers = (
        User.query
        .filter_by(is_seller=True)
        .order_by(User.date_joined.desc())
        .all()
    )

    # Seller item counts and pickup info
    for s in sellers:
        s._item_count = InventoryItem.query.filter_by(seller_id=s.id).filter(
            InventoryItem.status.in_(['available', 'pending_valuation', 'pending_logistics', 'approved'])
        ).count()
        s._days_since_joined = (datetime.utcnow().date() - s.date_joined.date()).days if s.date_joined else None

    # Pickup nudge queue: has approved items but no pickup week
    nudge_sellers = [
        s for s in sellers
        if s.pickup_week is None and InventoryItem.query.filter_by(
            seller_id=s.id, status='available'
        ).count() > 0
    ]

    # Free-tier sellers with pending items (awaiting free-tier approval)
    free_tier_sellers = (
        User.query
        .join(InventoryItem, InventoryItem.seller_id == User.id)
        .filter(
            InventoryItem.collection_method == 'free',
            InventoryItem.status == 'pending_valuation',
        )
        .group_by(User.id)
        .all()
    )

    return render_template(
        'admin/sellers.html',
        sellers=sellers,
        nudge_sellers=nudge_sellers,
        free_tier_sellers=free_tier_sellers,
    )


@app.route('/admin/crew')
@login_required
def admin_crew_panel():
    """Crew tab — pending applications + approved workers."""
    if not current_user.is_admin:
        abort(403)

    pending_apps = (
        WorkerApplication.query
        .join(User, WorkerApplication.user_id == User.id)
        .filter(User.worker_status == 'pending')
        .order_by(WorkerApplication.applied_at.desc())
        .all()
    )

    approved_workers = (
        User.query
        .filter_by(worker_status='approved')
        .order_by(User.full_name.asc())
        .all()
    )

    # Shift completion counts per worker
    for w in approved_workers:
        w._shifts_done = ShiftAssignment.query.filter_by(
            worker_id=w.id
        ).filter(ShiftAssignment.completed_at.isnot(None)).count()

    # Availability for pending applicants
    for app_rec in pending_apps:
        app_rec._avail = WorkerAvailability.query.filter_by(
            user_id=app_rec.user_id, week_start=None
        ).first()

    return render_template(
        'admin/crew.html',
        pending_apps=pending_apps,
        approved_workers=approved_workers,
    )


@app.route('/admin/settings', methods=['GET', 'POST'])
@login_required
def admin_settings():
    """Settings tab — all config sections. Super admin only."""
    if not current_user.is_super_admin:
        abort(403)

    if request.method == 'POST':
        # Delegate to the appropriate sub-handler based on form key
        # All existing POST sub-routes stay unchanged — this catches settings
        # submitted directly via the consolidated settings page.
        action = request.form.get('_action', '')
        if action == 'toggle_pickup_period':
            current_status = get_pickup_period_active()
            AppSetting.set('pickup_period_active', str(not current_status))
            flash(f"Pickup period {'activated' if not current_status else 'closed'}.", "success")
        elif action == 'toggle_reserve_only':
            current = AppSetting.get('reserve_only_mode', 'false')
            AppSetting.set('reserve_only_mode', 'false' if current == 'true' else 'true')
            flash("Reserve-only mode updated.", "success")
        elif action == 'toggle_shop_teaser':
            current = AppSetting.get('shop_teaser_mode', 'false')
            AppSetting.set('shop_teaser_mode', 'false' if current == 'true' else 'true')
            flash("Shop Teaser Mode updated.", "success")
        elif action == 'save_route_settings':
            for key in ['truck_raw_capacity', 'truck_capacity_buffer_pct',
                        'route_am_window', 'route_pm_window', 'maps_static_api_key',
                        'sms_enabled', 'sms_reminder_hour_eastern',
                        'no_show_email_enabled', 'no_show_email_hour_eastern']:
                val = request.form.get(key)
                if val is not None:
                    AppSetting.set(key, val.strip())
            categories = InventoryCategory.query.order_by(InventoryCategory.name).all()
            for cat in categories:
                raw = request.form.get(f'unit_size_{cat.id}', '').strip()
                if raw:
                    try:
                        cat.default_unit_size = float(raw)
                    except ValueError:
                        pass
            db.session.commit()
            flash("Route & capacity settings saved.", "success")
        elif action == 'save_referral_settings':
            for key in ('referral_base_rate', 'referral_signup_bonus',
                        'referral_bonus_per_referral', 'referral_max_rate'):
                val = request.form.get(key, '').strip()
                if val.isdigit():
                    AppSetting.set(key, val)
            active_val = 'true' if request.form.get('referral_program_active') == 'true' else 'false'
            AppSetting.set('referral_program_active', active_val)
            flash("Referral program settings saved.", "success")
        elif action == 'save_sms_settings':
            for key in ['sms_enabled', 'sms_reminder_hour_eastern',
                        'no_show_email_enabled', 'no_show_email_hour_eastern']:
                val = request.form.get(key)
                if val is not None:
                    AppSetting.set(key, val.strip())
            flash("SMS notification settings saved.", "success")
        elif action == 'save_pickup_window':
            start = request.form.get('pickup_week_start', '').strip()
            end = request.form.get('pickup_week_end', '').strip()
            from datetime import date as _date_cls
            try:
                if start:
                    _date_cls.fromisoformat(start)
                if end:
                    _date_cls.fromisoformat(end)
                AppSetting.set('pickup_week_start', start)
                AppSetting.set('pickup_week_end', end)
                flash("Pickup window saved.", "success")
            except ValueError:
                flash("Invalid date format. Use YYYY-MM-DD.", "error")
        elif action == 'make_admin':
            email = request.form.get('admin_email', '').strip()
            is_super = request.form.get('is_super') == '1'
            u = User.query.filter_by(email=email).first()
            if u:
                u.is_admin = True
                if is_super:
                    u.is_super_admin = True
                db.session.commit()
                flash(f"Admin access granted to {email}.", "success")
            else:
                flash(f"User not found: {email}.", "error")
        elif action == 'revoke_admin':
            email = request.form.get('admin_email', '').strip()
            u = User.query.filter_by(email=email).first()
            if u and u.id != current_user.id:
                u.is_admin = False
                u.is_super_admin = False
                db.session.commit()
                flash(f"Admin access revoked for {email}.", "success")
            elif u and u.id == current_user.id:
                flash("Cannot revoke your own admin access.", "error")
            else:
                flash(f"User not found: {email}.", "error")
        return redirect(url_for('admin_settings'))

    # GET: build settings page
    categories = InventoryCategory.query.order_by(InventoryCategory.name).all()
    storage_locations = StorageLocation.query.order_by(StorageLocation.is_active.desc(), StorageLocation.name).all()
    admin_users = User.query.filter_by(is_admin=True).order_by(User.email).all()

    return render_template(
        'admin/settings.html',
        categories=categories,
        storage_locations=storage_locations,
        admin_users=admin_users,
        # Route settings
        truck_raw_capacity=AppSetting.get('truck_raw_capacity', '18'),
        truck_capacity_buffer_pct=AppSetting.get('truck_capacity_buffer_pct', '10'),
        route_am_window=AppSetting.get('route_am_window', '9am–1pm'),
        route_pm_window=AppSetting.get('route_pm_window', '1pm–5pm'),
        maps_static_api_key=AppSetting.get('maps_static_api_key', ''),
        # SMS
        sms_enabled=AppSetting.get('sms_enabled', 'true'),
        sms_reminder_hour_eastern=AppSetting.get('sms_reminder_hour_eastern', '9'),
        no_show_email_enabled=AppSetting.get('no_show_email_enabled', 'true'),
        no_show_email_hour_eastern=AppSetting.get('no_show_email_hour_eastern', '18'),
        # Referral
        referral_base_rate=AppSetting.get('referral_base_rate', '20'),
        referral_signup_bonus=AppSetting.get('referral_signup_bonus', '10'),
        referral_bonus_per_referral=AppSetting.get('referral_bonus_per_referral', '10'),
        referral_max_rate=AppSetting.get('referral_max_rate', '100'),
        referral_program_active=AppSetting.get('referral_program_active', 'true'),
        # Pickup window
        pickup_week_start=AppSetting.get('pickup_week_start', ''),
        pickup_week_end=AppSetting.get('pickup_week_end', ''),
        # Store
        pickup_period_active=get_pickup_period_active(),
        reserve_only=AppSetting.get('reserve_only_mode', 'false') == 'true',
        store_open_date=AppSetting.get('store_open_date', ''),
        shop_teaser_mode=AppSetting.get('shop_teaser_mode', 'false'),
    )


@app.route('/admin/settings/generate-shifts', methods=['POST'])
@login_required
def admin_generate_shifts():
    """Idempotent: generate AM + PM shifts for every date in the configured pickup window."""
    if not current_user.is_super_admin:
        abort(403)

    from datetime import date as _date_cls

    start_str = AppSetting.get('pickup_week_start', '').strip()
    end_str = AppSetting.get('pickup_week_end', '').strip()
    if not start_str or not end_str:
        flash("Set pickup_week_start and pickup_week_end in Settings first.", "error")
        return redirect(url_for('admin_settings') + '#pickup-window')

    try:
        start_date = _date_cls.fromisoformat(start_str)
        end_date = _date_cls.fromisoformat(end_str)
    except ValueError:
        flash("Invalid pickup window dates. Use YYYY-MM-DD format.", "error")
        return redirect(url_for('admin_settings') + '#pickup-window')

    if end_date < start_date:
        flash("End date must be on or after start date.", "error")
        return redirect(url_for('admin_settings') + '#pickup-window')

    created_count = 0
    current_date = start_date
    while current_date <= end_date:
        # Find or create ShiftWeek whose week contains this date
        monday = current_date - timedelta(days=current_date.weekday())
        week = ShiftWeek.query.filter_by(week_start=monday).first()
        if not week:
            week = ShiftWeek(
                week_start=monday,
                status='draft',
                created_by_id=current_user.id,
            )
            db.session.add(week)
            db.session.flush()

        day_str = _DAY_ORDER_OPS[current_date.weekday()]
        for slot in ('am', 'pm'):
            existing = Shift.query.filter_by(week_id=week.id, day_of_week=day_str, slot=slot).first()
            if not existing:
                sh = Shift(
                    week_id=week.id,
                    day_of_week=day_str,
                    slot=slot,
                    trucks=1,
                    is_active=True,
                )
                db.session.add(sh)
                created_count += 1

        current_date += timedelta(days=1)

    db.session.commit()
    date_range = f"{start_date.strftime('%b %-d')}–{end_date.strftime('%b %-d')}"
    flash(f"Generated {created_count} shift(s) for {date_range}.", "success")
    return redirect(url_for('admin_settings') + '#pickup-window')


if __name__ == '__main__':
    with app.app_context():
        # Only create DB if it doesn't exist (Local SQLite check)
        # On Render, we use migrations.
        if 'DATABASE_URL' not in os.environ:
            db.create_all()
        try:
            seed_crew_app_settings()
        except Exception as _seed_err:
            logger.warning(f"seed_crew_app_settings skipped (run flask db upgrade): {_seed_err}")
        # Auto-seed categories if table is empty (local dev safety net)
        if 'DATABASE_URL' not in os.environ:
            from models import InventoryCategory
            if InventoryCategory.query.count() == 0:
                logger.info("No categories found — auto-seeding from seed_categories.py")
                from seed_categories import seed as seed_cats
                seed_cats(include_items=False)
    app.run(debug=True, port=4242, host='0.0.0.0')