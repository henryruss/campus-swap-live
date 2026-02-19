import os
import shutil
import time
import json
import logging
import re
import secrets
import html as html_module
from dotenv import load_dotenv
load_dotenv()  # Load .env for local dev (Render uses env vars directly)

from PIL import Image, ImageOps
import stripe
import resend
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, session, send_from_directory, jsonify, Response, make_response, abort
import csv
from io import StringIO, BytesIO
from werkzeug.utils import secure_filename
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect
from sqlalchemy.orm import joinedload, selectinload
from sqlalchemy import or_, and_

# Import Models
from models import db, User, InventoryCategory, InventoryItem, ItemPhoto, AppSetting, UploadSession, TempUpload

# Import Constants
from constants import (
    PAYOUT_PERCENTAGE, PAYOUT_PERCENTAGE_ONLINE, PAYOUT_PERCENTAGE_IN_PERSON,
    SERVICE_FEE_CENTS, LARGE_ITEM_FEE_CENTS, SELLER_ACTIVATION_FEE_CENTS,
    MAX_UPLOAD_SIZE, ALLOWED_EXTENSIONS, ALLOWED_MIME_TYPES,
    IMAGE_QUALITY, THUMBNAIL_SIZE,
    MIN_PRICE, MAX_PRICE, MIN_QUALITY, MAX_QUALITY,
    MAX_DESCRIPTION_LENGTH, MAX_LONG_DESCRIPTION_LENGTH,
    MAX_EMAIL_LENGTH, MAX_NAME_LENGTH,
    ITEMS_PER_PAGE, RESIDENCE_HALLS_BY_STORE,
    PICKUP_WEEKS, POD_LOCATIONS
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
        google_oauth_enabled=bool(oauth)
    )

# SECURITY: This secret key enables sessions. 
# On Render, set this as an Environment Variable called 'SECRET_KEY'.
app.secret_key = os.environ.get('SECRET_KEY', 'dev_key_for_local_use')

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
# Check if the Render Disk folder exists. If so, use it.
if os.path.exists('/var/data'):
    app.config['UPLOAD_FOLDER'] = '/var/data'
else:
    # Local fallback
    app.config['UPLOAD_FOLDER'] = 'static/uploads'

# Ensure the upload folder actually exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Initialize DB & Migrations
db.init_app(app)
migrate = Migrate(app, db)

# CSRF Protection (exempt webhook - Stripe sends raw POST without token)
csrf = CSRFProtect(app)

# Rate Limiting
try:
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

def get_user_dashboard():
    """Helper function to determine where user should be redirected"""
    if current_user.is_authenticated and current_user.is_admin:
        return url_for('admin_panel')
    return url_for('dashboard')


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
    Wrap email content in a proper HTML template with footer.
    
    Args:
        html_content: The main email content (HTML)
        unsubscribe_url: Optional unsubscribe URL for marketing emails
        is_marketing: Whether this is a marketing email (adds unsubscribe link)
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
    """Return payout percentage based on collection method."""
    return PAYOUT_PERCENTAGE_ONLINE if item.collection_method == 'online' else PAYOUT_PERCENTAGE_IN_PERSON

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


# --- ERROR HANDLERS ---

@app.errorhandler(404)
def not_found_error(error):
    logger.warning(f"404 error: {request.url}")
    return render_template('error.html', 
                         error_code=404, 
                         error_message="Page not found"), 404


@app.errorhandler(500)
def internal_error(error):
    logger.error(f"500 error: {error}", exc_info=True)
    db.session.rollback()
    return render_template('error.html',
                         error_code=500,
                         error_message="An internal error occurred. Please try again later."), 500


@app.errorhandler(413)
def request_entity_too_large(error):
    logger.warning(f"413 error: File too large")
    flash("File is too large. Maximum size is 10MB.", "error")
    return redirect(request.url), 413


# =========================================================
# SECTION 1: PUBLIC & LANDING ROUTES
# =========================================================

@app.route('/', methods=['GET', 'POST'])
def index():
    # 1. TRACKING LOGIC
    if request.args.get('source'):
        session['source'] = request.args.get('source')

    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        
        # Validate email
        if not email:
            flash("Please provide your email address.", "error")
            return render_template('index.html', pickup_period_active=get_pickup_period_active())
        
        if not validate_email(email):
            flash("Please provide a valid email address.", "error")
            return render_template('index.html', pickup_period_active=get_pickup_period_active())
        
        if len(email) > MAX_EMAIL_LENGTH:
            flash(f"Email address is too long (max {MAX_EMAIL_LENGTH} characters).", "error")
            return render_template('index.html', pickup_period_active=get_pickup_period_active())
        
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
            
            flash("Pickup period has ended for this year. We've saved your email and will notify you when signups open next year!", "info")
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
    return render_template('index.html', pickup_period_active=pickup_period_active)

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

@app.route('/become-a-seller', methods=['GET', 'POST'])
def become_a_seller():
    """Become a Seller page - comprehensive seller guide with timeline, earnings, FAQ, and CTA."""
    if request.args.get('source'):
        session['source'] = request.args.get('source')

    if request.method == 'POST':
        email = request.form.get('email', '').strip()

        if not email:
            flash("Please provide your email address.", "error")
            return render_template('become_a_seller.html', pickup_period_active=get_pickup_period_active(), store_info=get_store_info(get_current_store()))

        if not validate_email(email):
            flash("Please provide a valid email address.", "error")
            return render_template('become_a_seller.html', pickup_period_active=get_pickup_period_active(), store_info=get_store_info(get_current_store()))

        if len(email) > MAX_EMAIL_LENGTH:
            flash(f"Email address is too long (max {MAX_EMAIL_LENGTH} characters).", "error")
            return render_template('become_a_seller.html', pickup_period_active=get_pickup_period_active(), store_info=get_store_info(get_current_store()))

        pickup_period_active = get_pickup_period_active()
        if not pickup_period_active:
            existing_user = User.query.filter_by(email=email).first()
            if not existing_user:
                guest_user = User(email=email, referral_source=session.get('source', 'direct'))
                db.session.add(guest_user)
                db.session.commit()
                logger.info(f"Guest account created (become-a-seller, pickup closed): {email}")

            flash("Pickup period has ended for this year. We've saved your email and will notify you when signups open next year!", "info")
            return redirect(url_for('become_a_seller'))

        user = User.query.filter_by(email=email).first()
        if user:
            if user.password_hash:
                flash("You already have an account. Please log in.", "info")
                return redirect(url_for('login', email=email))
            else:
                login_user(user)
                return redirect(get_user_dashboard())
        else:
            source = session.get('source', 'direct')
            new_user = User(email=email, referral_source=source)
            db.session.add(new_user)
            db.session.commit()
            login_user(new_user)
            flash("Account created! Complete your profile and activate as a seller to start listing items.", "success")
            return redirect(get_user_dashboard())

    pickup_period_active = get_pickup_period_active()
    store_info = get_store_info(get_current_store())
    return render_template('become_a_seller.html', pickup_period_active=pickup_period_active, store_info=store_info)

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
    
    # Add all available (live) product pages
    available_items = InventoryItem.query.filter_by(status='available').all()
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
        favicon_path = os.path.join('static', 'favicon.png')
        if not os.path.exists(favicon_path):
            return Response('', mimetype='image/png'), 404
        response = send_from_directory('static', 'favicon.png', mimetype='image/png')
        response.headers['Cache-Control'] = 'public, max-age=31536000'
        return response
    except Exception as e:
        logger.error(f"Error serving favicon: {e}", exc_info=True)
        return Response('', mimetype='image/png'), 404


# =========================================================
# SECTION 2: MARKETPLACE ROUTES
# =========================================================

@app.route('/dropoff', methods=['GET', 'POST'])
def dropoff():
    """QR code landing page for in-person drop-offs. Quick signup without full onboarding."""
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        name = request.form.get('name', '').strip()
        
        if not email:
            flash("Please provide your email.", "error")
            return render_template('dropoff.html', prefill_name=name)
        
        # Check if user exists
        user = User.query.filter_by(email=email).first()
        
        if user:
            # User exists - update name if provided and different
            if name and name != user.full_name:
                user.full_name = name
                db.session.commit()
            flash("Thanks! We'll email you when your item sells.", "success")
        else:
            # Create new guest account (no password set yet)
            new_user = User(email=email, full_name=name, referral_source='in_person_dropoff')
            db.session.add(new_user)
            db.session.commit()
            flash("Thanks! We'll email you when your item sells.", "success")
        
        return render_template('dropoff.html', success=True, email=email)
    
    return render_template('dropoff.html')

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
    cat_id = request.args.get('category_id', type=int)
    store_name = request.args.get('store', get_current_store())
    search_query = request.args.get('search', '').strip()
    page = request.args.get('page', 1, type=int)
    
    commodities = InventoryCategory.query.all()
    
    # Build query with eager loading to prevent N+1 queries
    query = InventoryItem.query.options(
        joinedload(InventoryItem.category),
        joinedload(InventoryItem.seller)
    ).filter(InventoryItem.status != 'pending_valuation')
    
    # Apply category filter
    if cat_id:
        query = query.filter_by(category_id=cat_id)
    
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
                         current_store=store_name, 
                         store_info=store_info)

@app.route('/item/<int:item_id>')
def product_detail(item_id):
    item = InventoryItem.query.get_or_404(item_id)
    store_name = request.args.get('store', get_current_store())
    store_info = get_store_info(store_name)
    # Preserve search and filter parameters for "Back" link
    return render_template('product.html', item=item, current_store=store_name, store_info=store_info)

# --- IMAGE SERVING ROUTE (CRITICAL FOR RENDER) ---
@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


# --- QR CODE MOBILE PHOTO UPLOAD ---
UPLOAD_SESSION_EXPIRY_MINUTES = 30

def _cleanup_expired_upload_sessions():
    """Delete upload sessions and temp uploads older than expiry"""
    cutoff = datetime.utcnow() - timedelta(minutes=UPLOAD_SESSION_EXPIRY_MINUTES)
    expired = UploadSession.query.filter(UploadSession.created_at < cutoff).all()
    for s in expired:
        for t in TempUpload.query.filter_by(session_token=s.session_token).all():
            fp = os.path.join(app.config['UPLOAD_FOLDER'], t.filename)
            if os.path.exists(fp):
                try:
                    os.remove(fp)
                except OSError:
                    pass
        db.session.delete(s)
    TempUpload.query.filter(TempUpload.created_at < cutoff).delete(synchronize_session=False)
    db.session.commit()


@app.route('/api/upload_session/create', methods=['POST'])
@login_required
def create_upload_session():
    """Create a session for QR code mobile photo upload. Returns token and QR code image."""
    import base64
    import qrcode

    _cleanup_expired_upload_sessions()

    token = secrets.token_urlsafe(16)
    upload_url = url_for('upload_from_phone', token=token, _external=True)

    session_obj = UploadSession(session_token=token, user_id=current_user.id)
    db.session.add(session_obj)
    db.session.commit()

    qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=8, border=2)
    qr.add_data(upload_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#000", back_color="#fff")
    buf = BytesIO()
    img.save(buf, format="PNG")
    qr_base64 = base64.b64encode(buf.getvalue()).decode()

    return jsonify({
        'token': token,
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
    save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
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


@app.route('/api/upload_session/status')
@login_required
def upload_session_status():
    """Return list of temp uploads for the given token (for desktop polling)."""
    token = request.args.get('token', '')
    session_obj = UploadSession.query.filter_by(session_token=token).first()
    if not session_obj:
        return jsonify({'images': [], 'error': 'Session not found'}), 404
    if session_obj.user_id != current_user.id:
        return jsonify({'images': [], 'error': 'Unauthorized'}), 403
    if datetime.utcnow() - session_obj.created_at > timedelta(minutes=UPLOAD_SESSION_EXPIRY_MINUTES):
        return jsonify({'images': [], 'error': 'Session expired'}), 400

    uploads = TempUpload.query.filter_by(session_token=token).order_by(TempUpload.created_at).all()
    base_url = request.url_root.rstrip('/')
    images = [
        {'filename': u.filename, 'url': url_for('uploaded_file', filename=u.filename, _external=True)}
        for u in uploads
    ]
    return jsonify({'images': images})


@app.route('/buy_item/<int:item_id>')
def buy_item(item_id):
    """Create Stripe checkout session for item purchase with race condition protection"""
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
    session_id = request.args.get('session_id')
    if not session_id:
        return redirect(url_for('inventory'))
    
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
    if not endpoint_secret:
        return 'STRIPE_WEBHOOK_SECRET not configured', 500

    payload = request.get_data(as_text=True)
    sig_header = request.headers.get('Stripe-Signature')

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, endpoint_secret
        )
    except ValueError as e:
        return 'Invalid payload', 400
    except stripe.error.SignatureVerificationError as e:
        return 'Invalid signature', 400

    # Handle the event
    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        
        # --- CASE 1: ITEM PURCHASE ---
        if session.get('metadata', {}).get('type') == 'item_purchase':
            item_id = session.get('metadata').get('item_id')
            
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


# =========================================================
# SECTION 4: ADMIN ROUTES
# =========================================================

@app.route('/admin', methods=['GET', 'POST'])
def admin_panel():
    # Only allow Admin (Checks is_admin flag)
    if not current_user.is_authenticated or not current_user.is_admin:
         flash("Access denied.", "error")
         return redirect(url_for('index'))
    
    # Debug: capture form data for troubleshooting (always on for admin)
    admin_debug = session.pop('admin_debug', None) if request.method == 'GET' else None
    if request.method == 'POST':
        form_keys = list(request.form.keys())
        admin_debug = {'form_keys': form_keys, 'action': None, 'result': None, 'has_bulk': 'bulk_update_items' in request.form, 'has_delete': 'delete_item' in request.form}
        logger.info(f"ADMIN_POST form_keys={form_keys}")
    
    # Admin can toggle pickup period
    if request.method == 'POST' and 'toggle_pickup_period' in request.form:
        current_status = get_pickup_period_active()
        new_status = not current_status
        AppSetting.set('pickup_period_active', str(new_status))
        flash(f"Pickup period {'activated' if new_status else 'closed'}.", "success")

    # 1. Update Category Counts
    if request.method == 'POST' and 'update_all_counts' in request.form:
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

    # 2. Add Item (Admin Side - Quick Add for in-person drop-offs)
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
            
            # Quick Add is always in-person drop-off, status pending (price set later)
            collection_method = request.form.get('collection_method', 'in_person')
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
                    save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    
                    try:
                        img = Image.open(file)
                        img = ImageOps.exif_transpose(img)
                        img = img.convert("RGBA")
                        bg = Image.new("RGB", img.size, (255, 255, 255))
                        bg.paste(img, (0, 0), img)
                        
                        # Resize if image is too large (max 2000px on longest side)
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
        if admin_debug:
            admin_debug['action'] = 'bulk_update_items'
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
                        # Seller must confirm pickup week (and pay) or dropoff pod before item goes live
                        if item.status == 'pending_valuation' and new_price is not None:
                            item.status = 'pending_logistics'
                            # Don't add to count_in_stock until seller confirms logistics
                            
                            # Send email: item approved, confirm pickup/dropoff
                            if item.seller and item.seller.email:
                                try:
                                    is_pickup = item.collection_method == 'online'
                                    fee_text = ""
                                    if is_pickup:
                                        fee = SERVICE_FEE_CENTS // 100
                                        if item.is_large:
                                            fee += LARGE_ITEM_FEE_CENTS // 100
                                        fee_text = f" Confirm your pickup week and pay ${fee} to secure your spot."
                                    else:
                                        fee_text = " Select your dropoff pod location—no payment required."
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
                        # is_large: admin marks during approval; $10 fee for online items
                        if f"is_large_{item_id}" in request.form:
                            item.is_large = request.form[f"is_large_{item_id}"].lower() in ('1', 'true', 'on', 'yes')
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
            if admin_debug:
                admin_debug['result'] = result_msg
                admin_debug['updated_count'] = updated_count
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
            if admin_debug:
                admin_debug['result'] = f"ERROR: {str(e)}"
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
            if admin_debug:
                admin_debug['action'] = 'delete_item'
                admin_debug['delete_item_value'] = delete_val
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
                    if admin_debug:
                        admin_debug['result'] = f"Deleted item {item_id} ({item_desc})"
                    logger.info(f"ADMIN: Deleted item {item_id}")
                    if is_ajax:
                        return jsonify({'success': True, 'message': f"Item '{item_desc}' deleted.", 'remove_row': True, 'item_id': item_id})
                    flash(f"Item '{item_desc}' deleted.", "success")
                else:
                    if admin_debug:
                        admin_debug['result'] = f"Item not found for id={delete_val}"
                    logger.warning(f"ADMIN: delete_item - item not found for id={delete_val}")
            except Exception as e:
                db.session.rollback()
                logger.error(f"ADMIN: Error deleting item {delete_val}: {e}", exc_info=True)
                if admin_debug:
                    admin_debug['result'] = f"ERROR: {str(e)}"
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

    # If we had a POST but no gallery action ran, record for debugging
    if admin_debug and admin_debug.get('action') is None:
        admin_debug['action'] = 'none'
        admin_debug['result'] = f"No action matched. bulk_update_items in form? {admin_debug.get('has_bulk')}. delete_item in form? {admin_debug.get('has_delete')}."

    # Persist admin_debug to session so it survives redirects (e.g. mark_payout_sent)
    if admin_debug:
        session['admin_debug'] = admin_debug

    # Data Loading with optimized queries
    commodities = InventoryCategory.query.all()
    all_cats = InventoryCategory.query.all()
    
    # Filter: Show all pending items (no payment gate; charge at pickup)
    pending_items = InventoryItem.query.options(
        joinedload(InventoryItem.category),
        joinedload(InventoryItem.seller)
    ).filter(InventoryItem.status == 'pending_valuation').order_by(InventoryItem.date_added.asc()).all()
    
    gallery_items = InventoryItem.query.options(
        joinedload(InventoryItem.category),
        joinedload(InventoryItem.seller)
    ).filter(InventoryItem.status != 'pending_valuation').order_by(InventoryItem.date_added.desc()).all()
    
    pickup_period_active = get_pickup_period_active()
    
    # Calculate database stats
    total_users = User.query.count()
    total_items = InventoryItem.query.count()
    sold_items = InventoryItem.query.filter_by(status='sold').count()
    pending_items_count = InventoryItem.query.filter_by(status='pending_valuation').count()
    available_items = InventoryItem.query.filter_by(status='available').count()
    
    return render_template('admin.html', commodities=commodities, all_cats=all_cats, 
                           pending_items=pending_items, gallery_items=gallery_items,
                           pickup_period_active=pickup_period_active,
                           total_users=total_users, total_items=total_items,
                           sold_items=sold_items, pending_items_count=pending_items_count,
                           available_items=available_items,
                           admin_debug=admin_debug)


@app.route('/edit_item/<int:item_id>', methods=['GET', 'POST'])
@login_required
def edit_item(item_id):
    item = InventoryItem.query.get_or_404(item_id)
    
    # Security: Only Owner or Admin can edit
    # UPDATED to use is_admin
    if item.seller_id != current_user.id and not current_user.is_admin:
        flash("You cannot edit this item.", "error")
        return redirect(get_user_dashboard())
    
    # Prevent editing live items (non-admin sellers)
    if item.status == 'available' and not current_user.is_admin:
        flash("This item is live and cannot be edited. Contact support if you need changes.", "error")
        return redirect(url_for('dashboard'))
    
    categories = InventoryCategory.query.all()
    
    if request.method == 'POST':
        # Validate inputs
        description = request.form.get('description', '').strip()
        if not description or len(description) > MAX_DESCRIPTION_LENGTH:
            flash(f"Description is required and must be under {MAX_DESCRIPTION_LENGTH} characters.", "error")
            return render_template('edit_item.html', item=item, categories=categories)
        
        item.description = description
        
        # Validate price
        if request.form.get('price'):
            price_valid, price_result = validate_price(request.form['price'])
            if not price_valid:
                flash(f"Invalid price: {price_result}", "error")
                return render_template('edit_item.html', item=item, categories=categories)
            item.price = price_result
        
        # Validate quality
        quality_valid, quality_value = validate_quality(request.form.get('quality', item.quality))
        if not quality_valid:
            flash(f"Invalid quality: {quality_value}", "error")
            return render_template('edit_item.html', item=item, categories=categories)
        item.quality = quality_value
        
        long_description = request.form.get('long_description', '').strip()
        if long_description and len(long_description) > MAX_LONG_DESCRIPTION_LENGTH:
            flash(f"Long description is too long (max {MAX_LONG_DESCRIPTION_LENGTH} characters).", "error")
            return render_template('edit_item.html', item=item, categories=categories)
        item.long_description = long_description
        
        if request.form.get('category_id'):
            try:
                item.category_id = int(request.form['category_id'])
            except (ValueError, TypeError):
                flash("Invalid category.", "error")
                return render_template('edit_item.html', item=item, categories=categories)
        
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
                    save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    
                    try:
                        img = Image.open(file)
                        img = ImageOps.exif_transpose(img)
                        img = img.convert("RGBA")
                        bg = Image.new("RGB", img.size, (255, 255, 255))
                        bg.paste(img, (0, 0), img)
                        
                        # Resize if image is too large (max 2000px on longest side)
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
                        
                        # If no cover photo exists, set first new photo as cover
                        if not item.photo_url:
                            item.photo_url = filename
                        
                        db.session.add(ItemPhoto(item_id=item.id, photo_url=filename))
                    except Exception as img_error:
                        logger.error(f"Error processing image: {img_error}", exc_info=True)
                        flash("Error processing image. Please try again.", "error")
                        return redirect(url_for('edit_item', item_id=item_id))
        
        db.session.commit()
        logger.info(f"Item {item.id} updated by user {current_user.id}")
        flash("Item updated successfully!", "success")
        
        if current_user.is_admin:
            # Check if item was pending - if so, redirect to pending section
            if item.status == 'pending_valuation':
                return redirect(url_for('admin_panel') + '#pending-items')
            return redirect(url_for('admin_panel'))
        return redirect(get_user_dashboard())
        
    return render_template('edit_item.html', item=item, categories=categories)


@app.route('/delete_photo/<int:photo_id>')
@login_required
def delete_photo(photo_id):
    photo = ItemPhoto.query.get_or_404(photo_id)
    item = photo.item
    
    # Security check
    if item.seller_id != current_user.id and not current_user.is_admin:
        return redirect(get_user_dashboard())

    try:
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], photo.photo_url)
        if os.path.exists(file_path):
            os.remove(file_path)
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
    
    return redirect(url_for('account_settings'))

@app.route('/register', methods=['GET', 'POST'])
@limiter.limit("3 per hour") if limiter else lambda f: f
def register():
    if current_user.is_authenticated:
        return redirect(get_user_dashboard())

    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        full_name = request.form.get('full_name', '').strip()
        
        # Validate inputs - redirect to login with signup view to keep same layout
        if not email or not validate_email(email):
            flash("Please provide a valid email address.", "error")
            return redirect(url_for('login', signup='true', email=email or '', full_name=full_name or ''))
        
        if len(email) > MAX_EMAIL_LENGTH:
            flash(f"Email address is too long (max {MAX_EMAIL_LENGTH} characters).", "error")
            return redirect(url_for('login', signup='true', email=email, full_name=full_name))
        
        if not password or len(password) < 6:
            flash("Password must be at least 6 characters long.", "error")
            return redirect(url_for('login', signup='true', email=email, full_name=full_name))
        
        if full_name and len(full_name) > MAX_NAME_LENGTH:
            flash(f"Name is too long (max {MAX_NAME_LENGTH} characters).", "error")
            return redirect(url_for('login', signup='true', email=email, full_name=full_name))
        
        user = User.query.filter_by(email=email).first()
        
        if user:
            # User exists - check if they have a password
            if user.password_hash is None:
                # Guest account - set password to complete account creation
                user.password_hash = generate_password_hash(password)
                if full_name:
                    user.full_name = full_name
                db.session.commit()
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
                
                return redirect(get_user_dashboard())
            else:
                # Account already exists with password - redirect to login with message
                flash("An account with this email already exists. Please log in.", "error")
                return redirect(url_for('login', email=email))
        
        new_user = User(email=email, full_name=full_name, password_hash=generate_password_hash(password))
        db.session.add(new_user)
        db.session.commit()
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
        
        return redirect(get_user_dashboard())

    return render_template('register.html')


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
    """Initiate Google OAuth flow."""
    if not oauth:
        flash("Sign in with Google is not configured. Please use email to create an account.", "error")
        return redirect(url_for('register'))
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
        login_user(user)
        if not pickup_period_active:
            flash("Pickup period has ended for this year. We've saved your email and will notify you when signups open next year!", "info")
            return redirect(url_for('index'))
        flash("Welcome back!", "success")
        return redirect(get_user_dashboard())
    if not pickup_period_active:
        new_user = User(email=email, full_name=name or None, referral_source=source,
                        oauth_provider='google', oauth_id=oauth_id)
        db.session.add(new_user)
        db.session.commit()
        login_user(new_user)
        flash("Pickup period has ended for this year. We've saved your email and will notify you when signups open next year!", "info")
        return redirect(url_for('index'))
    new_user = User(email=email, full_name=name or None, referral_source=source,
                    oauth_provider='google', oauth_id=oauth_id)
    db.session.add(new_user)
    db.session.commit()
    login_user(new_user)
    flash("Account created! Complete your profile and activate as a seller to start listing items.", "success")
    return redirect(get_user_dashboard())


@app.route('/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute") if limiter else lambda f: f
def login():
    if current_user.is_authenticated:
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
                # User exists but has no password (guest account) - redirect to signup
                flash("Please create an account with this email.", "error")
                return render_template('login.html', prefill_email=email, prefill_full_name='', show_signup=True)
            elif not check_password_hash(user.password_hash, password):
                # Wrong password
                flash("Invalid password. Please try again.", "error")
                return render_template('login.html', prefill_email=email, prefill_full_name='', show_signup=False)
            else:
                # Successful login
                login_user(user)
                return redirect(get_user_dashboard())
        else:
            # This shouldn't happen as signup form posts to /register
            flash("Please use the Create Account form.", "error")
    
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
    my_items_pre = InventoryItem.query.filter_by(seller_id=current_user.id).all()
    if len(my_items_pre) == 0:
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
    
    # Calculate payout statistics (per-item percentage: online 50%, in-person 33%)
    live_items = [item for item in my_items if item.status == 'available']
    sold_items = [item for item in my_items if item.status == 'sold']
    
    def _payout_for_item(it):
        pct = _get_payout_percentage(it)
        return (it.price or 0) * pct
    
    estimated_payout = sum(_payout_for_item(i) for i in live_items)
    paid_out = sum(_payout_for_item(i) for i in sold_items if i.payout_sent)
    pending_payouts = sum(_payout_for_item(i) for i in sold_items if not i.payout_sent)
    total_potential = estimated_payout + pending_payouts + paid_out
    
    # Fee calculation for pickup: $15 + $10 per large online item
    approved_online = [i for i in live_items if i.collection_method == 'online']
    approved_large_count = sum(1 for i in approved_online if i.is_large)
    projected_fee_cents = SERVICE_FEE_CENTS + (LARGE_ITEM_FEE_CENTS * approved_large_count) if approved_online else 0

    # Pending pickup: items awaiting confirmation + fee breakdown for receipt modal
    pending_pickup = [i for i in my_items if i.status == 'pending_logistics' and i.collection_method == 'online']
    pending_pickup_large_count = sum(1 for i in pending_pickup if i.is_large)
    pending_pickup_fee_cents = SERVICE_FEE_CENTS + (LARGE_ITEM_FEE_CENTS * pending_pickup_large_count) if pending_pickup else 0

    stripe_pk = os.environ.get('STRIPE_PUBLISHABLE_KEY', '')
    stripe_configured = bool(stripe.api_key and stripe_pk)

    return render_template('dashboard.html',
                          my_items=my_items,
                          has_online_items=has_online_items,
                          estimated_payout=estimated_payout,
                          paid_out=paid_out,
                          pending_payouts=pending_payouts,
                          total_potential=total_potential,
                          sold_items=sold_items,
                          live_items=live_items,
                          approved_online_count=len(approved_online),
                          approved_large_count=approved_large_count,
                          projected_fee_cents=projected_fee_cents,
                          pending_pickup=pending_pickup,
                          pending_pickup_large_count=pending_pickup_large_count,
                          pending_pickup_fee_cents=pending_pickup_fee_cents,
                          pickup_weeks=PICKUP_WEEKS,
                          service_fee_cents=SERVICE_FEE_CENTS,
                          large_item_fee_cents=LARGE_ITEM_FEE_CENTS,
                          has_payment_method=bool(current_user.stripe_payment_method_id),
                          stripe_configured=stripe_configured,
                          dorms=RESIDENCE_HALLS_BY_STORE.get(get_current_store(), {}),
                          pod_locations=POD_LOCATIONS,
                          google_maps_key=os.environ.get('GOOGLE_MAPS_API_KEY', ''),
                          has_pickup_location=current_user.has_pickup_location,
                          has_payout_info=bool(current_user.payout_handle))

@app.route('/update_profile', methods=['POST'])
@login_required
def update_profile():
    location_type = request.form.get('pickup_location_type')
    if location_type == 'on_campus':
        dorm = (request.form.get('pickup_dorm') or '').strip()
        room = (request.form.get('pickup_room') or '').strip()
        if dorm and room:
            current_user.pickup_location_type = 'on_campus'
            current_user.pickup_dorm = dorm[:80]
            current_user.pickup_room = room[:20]
            current_user.pickup_address = None
            current_user.pickup_lat = None
            current_user.pickup_lng = None
            current_user.pickup_note = (request.form.get('pickup_note') or '').strip()[:200] or None
            phone = (request.form.get('phone') or '').replace('(', '').replace(')', '').replace('-', '').replace(' ', '')
            if len(phone) >= 10:
                current_user.phone = phone[:20]
            db.session.commit()
            flash("Pickup location saved.", "success")
        else:
            flash("Please select a dorm and enter your room number.", "error")
    elif location_type == 'off_campus':
        address = (request.form.get('pickup_address') or '').strip()
        if address:
            current_user.pickup_location_type = 'off_campus'
            current_user.pickup_address = address[:200]
            current_user.pickup_dorm = None
            current_user.pickup_room = None
            lat = request.form.get('pickup_lat')
            lng = request.form.get('pickup_lng')
            current_user.pickup_lat = float(lat) if lat and lat.strip() else None
            current_user.pickup_lng = float(lng) if lng and lng.strip() else None
            current_user.pickup_note = (request.form.get('pickup_note') or '').strip()[:200] or None
            phone = (request.form.get('phone') or '').replace('(', '').replace(')', '').replace('-', '').replace(' ', '')
            if len(phone) >= 10:
                current_user.phone = phone[:20]
            db.session.commit()
            flash("Pickup location saved.", "success")
        else:
            flash("Please enter your address.", "error")
    else:
        # Legacy: plain address field (backward compat)
        address = request.form.get('address')
        if address:
            current_user.pickup_location_type = 'off_campus'
            current_user.pickup_address = address[:200]
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
    
    if method and handle:
        clean_handle = handle.lstrip('@').strip() if method == 'Venmo' else handle.strip()
        if clean_handle:
            current_user.payout_method = method
            current_user.payout_handle = clean_handle
            current_user.is_seller = True
            db.session.commit()
            db.session.refresh(current_user)
            flash("Payout info secured.", "success")
        else:
            flash("Please enter a valid handle.", "error")
    # Remove scroll parameter - form is already visible, no need to scroll
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
    """After SetupIntent completes; payment_declined cleared. If upgrade flow, batch-update items to online."""
    current_user.payment_declined = False
    # Batch-update all in_person items to online (Campus Swap Pickup upgrade)
    upgraded = InventoryItem.query.filter_by(seller_id=current_user.id, collection_method='in_person').update(
        {'collection_method': 'online'}, synchronize_session=False
    )
    if upgraded:
        flash("Upgraded to Campus Swap Pickup! All your items are now on our pickup route.", "success")
    else:
        flash("Payment method saved. You won't be charged until pickup week.", "success")
    db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/upgrade_checkout', methods=['POST'])
@login_required
def upgrade_checkout():
    """Create Stripe Checkout session for $15 upgrade to Campus Swap Pickup."""
    if not stripe.api_key:
        flash("Payment is not configured yet. Please contact support.", "error")
        return redirect(url_for('dashboard'))
    try:
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'usd',
                    'product_data': {'name': 'Campus Swap Pickup - Service Fee'},
                    'unit_amount': SERVICE_FEE_CENTS,
                },
                'quantity': 1,
            }],
            mode='payment',
            client_reference_id=str(current_user.id),
            metadata={'type': 'upgrade', 'user_id': current_user.id},
            success_url=url_for('payment_success', _external=True) + '?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=url_for('dashboard', _external=True),
        )
        return redirect(checkout_session.url, code=303)
    except Exception as e:
        logger.error(f"upgrade_checkout: {e}", exc_info=True)
        flash("Could not start payment. Please try again.", "error")
        return redirect(url_for('dashboard'))

@app.route('/create_checkout_session', methods=['POST'])
@login_required
def create_checkout_session():
    """Legacy: instant $15 payment. New flow uses Setup Intent + charge at pickup."""
    try:
        checkout_session = stripe.checkout.Session.create(
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
        return redirect(checkout_session.url, code=303)
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
                    # Upgrade: batch-update in_person items to online
                    upgraded = InventoryItem.query.filter_by(seller_id=current_user.id, collection_method='in_person').update(
                        {'collection_method': 'online'}, synchronize_session=False
                    )
                    current_user.payment_declined = False
                    db.session.commit()
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

@app.route('/onboard', methods=['GET', 'POST'])
@login_required
def onboard():
    """6-step wizard for first-time sellers (0 items)."""
    if not get_pickup_period_active():
        flash("Pickup period has ended. Check back next year!", "error")
        return redirect(get_user_dashboard())
    if current_user.payment_declined:
        flash("Please add a valid payment method to continue.", "error")
        return redirect(url_for('add_payment_method'))

    categories = InventoryCategory.query.all()
    dorms = RESIDENCE_HALLS_BY_STORE.get(get_current_store(), {})
    google_maps_key = os.environ.get('GOOGLE_MAPS_API_KEY', '')

    if not categories:
        flash("No categories available. Please contact an administrator.", "error")
        return redirect(get_user_dashboard())

    if request.method == 'POST':
        cat_id = request.form.get('category_id')
        desc = request.form.get('description', '').strip()
        long_desc = (request.form.get('long_description') or '').strip()
        quality = request.form.get('quality')
        suggested_price_raw = request.form.get('suggested_price', '').strip()
        collection_method = request.form.get('collection_method', 'in_person')
        files = request.files.getlist('photos')
        temp_photo_ids_raw = request.form.get('temp_photo_ids', '')
        temp_photo_ids = [x.strip() for x in temp_photo_ids_raw.split(',') if x.strip()]

        has_files = files and files[0].filename and files[0].filename != ''
        has_temp_photos = len(temp_photo_ids) > 0
        if not has_files and not has_temp_photos:
            flash("Please add at least one photo.", "error")
            return render_template('onboard.html', categories=categories, dorms=dorms, google_maps_key=google_maps_key)
        if not cat_id:
            flash("Please select a category.", "error")
            return render_template('onboard.html', categories=categories, dorms=dorms, google_maps_key=google_maps_key)

        quality_valid, quality_value = validate_quality(quality)
        if not quality_valid:
            flash(f"Invalid condition.", "error")
            return render_template('onboard.html', categories=categories, dorms=dorms, google_maps_key=google_maps_key)

        suggested_price = None
        if suggested_price_raw:
            try:
                sp = float(suggested_price_raw)
                if sp >= 0:
                    suggested_price = sp
            except ValueError:
                pass

        # Save user profile: location, phone, payout
        location_type = request.form.get('pickup_location_type')
        if location_type == 'on_campus':
            dorm = (request.form.get('pickup_dorm') or '').strip()
            room = (request.form.get('pickup_room') or '').strip()
            if dorm and room:
                current_user.pickup_location_type = 'on_campus'
                current_user.pickup_dorm = dorm[:80]
                current_user.pickup_room = room[:20]
                current_user.pickup_address = None
                current_user.pickup_lat = None
                current_user.pickup_lng = None
        elif location_type == 'off_campus':
            address = (request.form.get('pickup_address') or '').strip()
            if address:
                current_user.pickup_location_type = 'off_campus'
                current_user.pickup_address = address[:200]
                current_user.pickup_dorm = None
                current_user.pickup_room = None
                lat = request.form.get('pickup_lat')
                lng = request.form.get('pickup_lng')
                current_user.pickup_lat = float(lat) if lat and str(lat).strip() else None
                current_user.pickup_lng = float(lng) if lng and str(lng).strip() else None

        current_user.pickup_note = (request.form.get('pickup_note') or '').strip()[:200] or None
        phone_raw = (request.form.get('phone') or '').replace('(', '').replace(')', '').replace('-', '').replace(' ', '')
        if len(phone_raw) >= 10:
            current_user.phone = phone_raw[:20]

        payout_raw = (request.form.get('payout_handle') or '').strip()
        payout_method = (request.form.get('payout_method') or 'Venmo').strip()[:20]
        payout_handle = payout_raw.lstrip('@') if payout_method == 'Venmo' else payout_raw
        if payout_handle:
            current_user.payout_method = payout_method if payout_method in ('Venmo', 'PayPal', 'Zelle') else 'Venmo'
            current_user.payout_handle = payout_handle
            current_user.is_seller = True

        db.session.commit()

        # Create the item (reuse add_item logic)
        new_item = InventoryItem(
            seller_id=current_user.id, category_id=int(cat_id), description=desc[:MAX_DESCRIPTION_LENGTH],
            long_description=long_desc[:MAX_LONG_DESCRIPTION_LENGTH] if long_desc else None,
            quality=quality_value, status="pending_valuation", photo_url="",
            collection_method=collection_method,
            suggested_price=suggested_price
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
                        return render_template('onboard.html', categories=categories, dorms=dorms, google_maps_key=google_maps_key)
                    filename = f"item_{new_item.id}_{int(time.time())}_{photo_index}.jpg"
                    save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
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
                        if not cover_set:
                            new_item.photo_url = filename
                            cover_set = True
                        db.session.add(ItemPhoto(item_id=new_item.id, photo_url=filename))
                        photo_index += 1
                    except Exception as img_error:
                        db.session.rollback()
                        logger.error(f"Image error: {img_error}", exc_info=True)
                        flash("Error processing image. Please try again.", "error")
                        return render_template('onboard.html', categories=categories, dorms=dorms, google_maps_key=google_maps_key)

        if has_temp_photos:
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
                    return render_template('onboard.html', categories=categories, dorms=dorms, google_maps_key=google_maps_key)
                old_path = os.path.join(app.config['UPLOAD_FOLDER'], temp_fn)
                if not os.path.exists(old_path):
                    db.session.rollback()
                    flash("Photo from phone no longer available. Please re-upload.", "error")
                    return render_template('onboard.html', categories=categories, dorms=dorms, google_maps_key=google_maps_key)
                new_filename = f"item_{new_item.id}_{int(time.time())}_{photo_index}.jpg"
                new_path = os.path.join(app.config['UPLOAD_FOLDER'], new_filename)
                try:
                    os.rename(old_path, new_path)
                except OSError:
                    shutil.move(old_path, new_path)
                if not cover_set:
                    new_item.photo_url = new_filename
                    cover_set = True
                db.session.add(ItemPhoto(item_id=new_item.id, photo_url=new_filename))
                db.session.delete(temp_rec)
                photo_index += 1

        db.session.commit()

        # No payment at onboarding - user pays after approval when confirming pickup
        try:
            submission_content = f"""
            <div style="font-family: sans-serif; padding: 20px; max-width: 500px;">
                <h2 style="color: #166534;">Item Submitted for Review</h2>
                <p>Hi {current_user.full_name or 'there'},</p>
                <p>We've received your item submission: <strong>{desc}</strong></p>
                <p>We'll review and price it soon. You'll get an email when it's approved—then you'll confirm pickup week or dropoff location.</p>
                <p><a href="{url_for('dashboard', _external=True)}" style="background: #166534; color: white; padding: 12px 24px; text-decoration: none; border-radius: 8px;">View Dashboard</a></p>
                <p>Thanks for selling with Campus Swap!</p>
            </div>
            """
            send_email(current_user.email, "Item Submitted - Campus Swap", submission_content)
        except Exception as email_error:
            logger.error(f"Onboard email error: {email_error}")
        flash("Item submitted! We'll review and price it soon. You'll confirm pickup or dropoff after approval.", "success")

        return redirect(get_user_dashboard())

    return render_template('onboard.html', categories=categories, dorms=dorms, google_maps_key=google_maps_key)

@app.route('/onboard_complete')
@login_required
def onboard_complete():
    """Legacy redirect - no payment at onboarding anymore."""
    return redirect(get_user_dashboard())

@app.route('/onboard_cancel')
@login_required
def onboard_cancel():
    """Legacy redirect - no payment at onboarding anymore."""
    return redirect(get_user_dashboard())


@app.route('/confirm_pickup', methods=['GET', 'POST'])
@login_required
def confirm_pickup():
    """Pickup users confirm week and pay ($15 + $10 per oversized item)."""
    pending = [i for i in current_user.items if i.status == 'pending_logistics' and i.collection_method == 'online']
    if not pending:
        flash("No items awaiting pickup confirmation.", "info")
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        pickup_week = request.form.get('pickup_week')
        if pickup_week not in ('week1', 'week2'):
            flash("Please select a pickup week.", "error")
            return redirect(url_for('confirm_pickup'))

        large_count = sum(1 for i in pending if i.is_large)
        fee_cents = SERVICE_FEE_CENTS + (LARGE_ITEM_FEE_CENTS * large_count)

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
                            'description': f"Pickup week: {dict(PICKUP_WEEKS).get(pickup_week, pickup_week)}" + (f" ({large_count} oversized)" if large_count else ''),
                        },
                        'unit_amount': fee_cents,
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

    large_count = sum(1 for i in pending if i.is_large)
    fee_cents = SERVICE_FEE_CENTS + (LARGE_ITEM_FEE_CENTS * large_count)
    fee_dollars = fee_cents / 100
    return render_template('confirm_pickup.html',
                          pending_items=pending,
                          pickup_weeks=PICKUP_WEEKS,
                          fee_dollars=fee_dollars,
                          large_count=large_count,
                          service_fee_cents=SERVICE_FEE_CENTS,
                          large_item_fee_cents=LARGE_ITEM_FEE_CENTS)


@app.route('/confirm_pickup_success')
@login_required
def confirm_pickup_success():
    """After Stripe payment for pickup confirmation."""
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
                for item_id in item_ids:
                    item = InventoryItem.query.get(item_id)
                    if item and item.seller_id == current_user.id and item.status == 'pending_logistics':
                        item.pickup_week = pickup_week
                        item.status = 'available'
                        if item.category:
                            item.category.count_in_stock = (item.category.count_in_stock or 0) + 1
                current_user.has_paid = True
                db.session.commit()
    except Exception as e:
        logger.error(f"confirm_pickup_success error: {e}", exc_info=True)
    flash("Pickup confirmed! Your items are now live.", "success")
    return redirect(get_user_dashboard())


@app.route('/confirm_dropoff', methods=['POST'])
@login_required
def confirm_dropoff():
    """Pod users confirm dropoff location—no payment."""
    item_id = request.form.get('item_id')
    dropoff_pod = request.form.get('dropoff_pod')

    valid_pods = [p[0] for p in POD_LOCATIONS]
    if dropoff_pod not in valid_pods:
        flash("Please select a valid dropoff location.", "error")
        return redirect(get_user_dashboard())

    item = InventoryItem.query.get(item_id) if item_id else None
    if not item or item.seller_id != current_user.id or item.status != 'pending_logistics' or item.collection_method != 'in_person':
        flash("Invalid item or item not awaiting confirmation.", "error")
        return redirect(get_user_dashboard())

    item.dropoff_pod = dropoff_pod
    item.status = 'available'
    if item.category:
        item.category.count_in_stock = (item.category.count_in_stock or 0) + 1
    db.session.commit()
    flash("Dropoff location confirmed! Your item is now live.", "success")
    return redirect(get_user_dashboard())


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
    
    categories = InventoryCategory.query.all()
    
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
        
        if not has_files and not has_temp_photos:
            flash("Please add at least one photo.", "error")
            return render_template('add_item.html', categories=categories)
        
        # Validate category_id
        if not cat_id:
            flash("Please select a category.", "error")
            return render_template('add_item.html', categories=categories)
        
        try:
            cat_id = int(cat_id)
        except (ValueError, TypeError):
            flash("Invalid category selected.", "error")
            return render_template('add_item.html', categories=categories)
        
        # Verify category exists
        category = InventoryCategory.query.get(cat_id)
        if not category:
            flash("Selected category does not exist. Please select a valid category.", "error")
            logger.error(f"Invalid category_id {cat_id} submitted - category not found")
            return render_template('add_item.html', categories=categories)
        
        # Validate inputs
        quality_valid, quality_value = validate_quality(quality)
        if not quality_valid:
            flash(f"Invalid quality: {quality_value}", "error")
            return render_template('add_item.html', categories=categories)
        
        if len(desc) > MAX_DESCRIPTION_LENGTH:
            flash(f"Description too long (max {MAX_DESCRIPTION_LENGTH} characters)", "error")
            return render_template('add_item.html', categories=categories)
        
        if long_desc and len(long_desc) > MAX_LONG_DESCRIPTION_LENGTH:
            flash(f"Long description too long (max {MAX_LONG_DESCRIPTION_LENGTH} characters)", "error")
            return render_template('add_item.html', categories=categories)
        
        suggested_price = None
        if suggested_price_raw:
            try:
                sp = float(suggested_price_raw)
                if sp >= 0:
                    suggested_price = sp
            except ValueError:
                pass

        # Use same collection method as user's other items (from onboarding choice)
        existing = [i.collection_method for i in current_user.items if i.collection_method]
        collection_method = existing[-1] if existing else 'in_person'
        new_item = InventoryItem(
            seller_id=current_user.id, category_id=cat_id, description=desc,
            long_description=long_desc, quality=quality_value, status="pending_valuation", photo_url="",
            collection_method=collection_method,
            suggested_price=suggested_price
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
                        return render_template('add_item.html', categories=categories)
                    
                    filename = f"item_{new_item.id}_{int(time.time())}_{photo_index}.jpg"
                    save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    
                    try:
                        img = Image.open(file)
                        img = ImageOps.exif_transpose(img)
                        img = img.convert("RGBA")
                        bg = Image.new("RGB", img.size, (255, 255, 255))
                        bg.paste(img, (0, 0), img)
                        
                        # Resize if image is too large (max 2000px on longest side)
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
                        
                        if not cover_set:
                            new_item.photo_url = filename
                            cover_set = True
                        db.session.add(ItemPhoto(item_id=new_item.id, photo_url=filename))
                        photo_index += 1
                    except Exception as img_error:
                        db.session.rollback()
                        logger.error(f"Error processing image: {img_error}", exc_info=True)
                        flash("Error processing image. Please try again.", "error")
                        return render_template('add_item.html', categories=categories)
        
        # Process temp photos from phone (QR upload)
        if has_temp_photos:
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
                    return render_template('add_item.html', categories=categories)
                old_path = os.path.join(app.config['UPLOAD_FOLDER'], temp_fn)
                if not os.path.exists(old_path):
                    db.session.rollback()
                    flash("Photo from phone no longer available. Please re-upload.", "error")
                    return render_template('add_item.html', categories=categories)
                new_filename = f"item_{new_item.id}_{int(time.time())}_{photo_index}.jpg"
                new_path = os.path.join(app.config['UPLOAD_FOLDER'], new_filename)
                try:
                    os.rename(old_path, new_path)
                except OSError:
                    shutil.move(old_path, new_path)
                if not cover_set:
                    new_item.photo_url = new_filename
                    cover_set = True
                db.session.add(ItemPhoto(item_id=new_item.id, photo_url=new_filename))
                db.session.delete(temp_rec)
                photo_index += 1
        
        db.session.commit()

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
            
    return render_template('add_item.html', categories=categories)

# =========================================================
# SECTION: ADMIN DATABASE MANAGEMENT
# =========================================================

@app.route('/admin/category/add', methods=['POST'])
@login_required
def admin_add_category():
    """Add a new category"""
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
    """Edit an existing category"""
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
    """Bulk update multiple categories at once"""
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
    """Delete a category (only if no items use it)"""
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


@app.route('/admin/user/delete/<int:user_id>', methods=['POST'])
@login_required
def admin_delete_user(user_id):
    """Delete a user account and all related data. Admin only."""
    if not current_user.is_admin:
        flash("Access denied.", "error")
        return redirect(url_for('index'))

    user = User.query.get(user_id)
    if not user:
        flash("User not found.", "error")
        return redirect(url_for('admin_preview_users'))

    if user_id == current_user.id:
        flash("You cannot delete your own account.", "error")
        return redirect(url_for('admin_preview_users'))

    if user.is_admin and User.query.filter_by(is_admin=True).count() == 1:
        flash("Cannot delete the last admin account.", "error")
        return redirect(url_for('admin_preview_users'))

    try:
        upload_folder = app.config['UPLOAD_FOLDER']

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
                    path = os.path.join(upload_folder, fn)
                    if os.path.exists(path):
                        os.remove(path)
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

    return redirect(url_for('admin_preview_users'))


@app.route('/admin/preview/users')
@login_required
def admin_preview_users():
    """Preview all users in browser"""
    if not current_user.is_admin:
        flash("Access denied.", "error")
        return redirect(url_for('index'))
    
    users = User.query.order_by(User.date_joined.desc()).all()
    
    # Prepare data for template
    headers = ['Email', 'Full Name', 'Date Joined', 'Has Account', 'Is Seller', 'Has Paid', 'Is Admin', 'Payout Method', 'Payout Handle', 'Actions']
    rows = []
    for user in users:
        rows.append({
            'id': user.id,
            'email': user.email,
            'full_name': user.full_name or '',
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
                         row_keys=['email', 'full_name', 'date_joined', 'has_account', 'is_seller', 'has_paid', 'is_admin', 'payout_method', 'payout_handle', 'actions'])

@app.route('/admin/export/users')
@login_required
def admin_export_users():
    """Export all users to CSV"""
    if not current_user.is_admin:
        flash("Access denied.", "error")
        return redirect(url_for('index'))
    
    users = User.query.order_by(User.date_joined.desc()).all()
    
    output = StringIO()
    writer = csv.writer(output)
    
    # Header row
    writer.writerow(['Email', 'Full Name', 'Date Joined', 'Has Account', 'Is Seller', 'Has Paid', 'Is Admin', 'Payout Method', 'Payout Handle'])
    
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
            user.payout_handle or ''
        ])
    
    output.seek(0)
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = f'attachment; filename=campus_swap_users_{datetime.utcnow().strftime("%Y%m%d")}.csv'
    return response

@app.route('/admin/preview/items')
@login_required
def admin_preview_items():
    """Preview all items in browser"""
    if not current_user.is_admin:
        flash("Access denied.", "error")
        return redirect(url_for('index'))
    
    items = InventoryItem.query.order_by(InventoryItem.date_added.desc()).all()
    
    # Prepare data for template
    headers = ['ID', 'Description', 'Category', 'Price', 'Quality', 'Status', 'Collection Method', 'Seller Email', 'Seller Name', 'Date Added', 'Sold At', 'Payout Sent']
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
            'quality': item.quality,
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
    """Export all items to CSV"""
    if not current_user.is_admin:
        flash("Access denied.", "error")
        return redirect(url_for('index'))
    
    items = InventoryItem.query.order_by(InventoryItem.date_added.desc()).all()
    
    output = StringIO()
    writer = csv.writer(output)
    
    # Header row
    writer.writerow(['ID', 'Description', 'Category', 'Price', 'Quality', 'Status', 'Collection Method', 'Seller Email', 'Seller Name', 'Date Added', 'Sold At', 'Payout Sent'])
    
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
            item.quality,
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
    """Preview sales data in browser"""
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
    """Export sold items with payout information"""
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

@app.route('/admin/database/reset', methods=['POST'])
@login_required
def admin_database_reset():
    """Safely reset database - requires confirmation"""
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
    """Send marketing email to all users in database"""
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

if __name__ == '__main__':
    with app.app_context():
        # Only create DB if it doesn't exist (Local SQLite check)
        # On Render, we use migrations.
        if not os.path.exists('campus.db') and 'DATABASE_URL' not in os.environ:
            db.create_all()
    app.run(debug=True, port=4242, host='0.0.0.0')