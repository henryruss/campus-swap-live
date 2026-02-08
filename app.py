import os
import time
import json
from dotenv import load_dotenv
load_dotenv()  # Load .env for local dev (Render uses env vars directly)

from PIL import Image
import stripe
import resend
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, session, send_from_directory, jsonify
from werkzeug.utils import secure_filename
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect

# Import Models
from models import db, User, InventoryCategory, InventoryItem, ItemPhoto, AppSetting

def get_pickup_period_active():
    """Get pickup period status from database, fallback to environment variable"""
    # Check database first (allows admin toggle)
    db_value = AppSetting.get('pickup_period_active')
    if db_value is not None:
        return db_value.lower() == 'true'
    # Fallback to environment variable
    return os.environ.get('PICKUP_PERIOD_ACTIVE', 'True').lower() == 'true'

# --- APP CONFIGURATION ---
app = Flask(__name__)

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

# --- EXTERNAL SERVICES CONFIGURATION ---

# STRIPE
stripe.api_key = os.environ.get('STRIPE_SECRET_KEY')
endpoint_secret = os.environ.get('STRIPE_WEBHOOK_SECRET')

# RESEND (EMAIL)
resend.api_key = os.environ.get('RESEND_API_KEY')  # Also loaded from .env via load_dotenv()

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

def send_email(to_email, subject, html_content):
    """
    Sends an email using Resend.
    NOTE: Until you verify a domain, you can only send to your own email.
    Once verified, change 'onboarding@resend.dev' to your domain (e.g. hello@usecampusswap.com)
    """
    if not resend.api_key:
        print(f"Skipping email to {to_email}: RESEND_API_KEY not set.")
        return

    try:
        resend.Emails.send({
            "from": "Campus Swap <onboarding@resend.dev>",
            "to": to_email,
            "subject": subject,
            "html": html_content
        })
        print(f"Email sent to {to_email}: {subject}")
    except Exception as e:
        # Log error but don't crash the route
        print(f"Failed to send email to {to_email}: {e}")
        import traceback
        traceback.print_exc()  # Print full traceback for debugging


def _item_sold_email_html(item, seller):
    """Build HTML for item sold notification with 40% payout details."""
    sale_price = item.price or 0
    payout_amount = round(sale_price * 0.40, 2)
    payout_method = seller.payout_method or "Venmo"
    payout_handle = seller.payout_handle or "—"
    return f"""
    <div style="font-family: sans-serif; padding: 20px; max-width: 500px;">
        <h2 style="color: #166534;">Cha-Ching!</h2>
        <p>Good news! Your item <strong>{item.description}</strong> has just been purchased.</p>
        <div style="background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 8px; padding: 16px; margin: 20px 0;">
            <p style="margin: 0 0 8px;"><strong>Sale price:</strong> ${sale_price:.2f}</p>
            <p style="margin: 0 0 8px;"><strong>Your payout (40%):</strong> ${payout_amount:.2f}</p>
            <p style="margin: 0;"><strong>Payout to:</strong> {payout_method} (@{payout_handle})</p>
        </div>
        <p>We'll process your payout shortly. Our team handles the handover to the buyer—you don't need to do anything!</p>
        <p>Thanks for selling with Campus Swap!</p>
    </div>
    """


# =========================================================
# SECTION 1: PUBLIC & LANDING ROUTES
# =========================================================

@app.route('/', methods=['GET', 'POST'])
def index():
    # 1. TRACKING LOGIC
    if request.args.get('source'):
        session['source'] = request.args.get('source')

    if request.method == 'POST':
        email = request.form.get('email')
        
        # Check if pickup period is active
        pickup_period_active = get_pickup_period_active()
        if not pickup_period_active:
            # Pickup period closed - still collect email for marketing
            # Check if email already exists
            existing_user = User.query.filter_by(email=email).first()
            if not existing_user:
                # Create a "waitlist only" user (no account creation)
                waitlist_user = User(email=email, referral_source=session.get('source', 'direct'))
                db.session.add(waitlist_user)
                db.session.commit()
            
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
            
            # Send Welcome Email (Waitlist/Lead)
            dashboard_url = url_for('dashboard', _external=True)
            send_email(
                email,
                "Welcome to Campus Swap!",
                f"""
                <div style="font-family: sans-serif; padding: 20px; max-width: 500px;">
                    <h2 style="color: #166534;">You're on the list!</h2>
                    <p>Thanks for joining Campus Swap. You're one step closer to turning your move-out items into cash.</p>
                    <p><strong>What's next?</strong></p>
                    <ul>
                        <li>Add your pickup location</li>
                        <li>Upload photos of your items</li>
                        <li>Complete activation to go live</li>
                    </ul>
                    <p><a href="{dashboard_url}" style="background: #166534; color: white; padding: 12px 24px; text-decoration: none; border-radius: 8px; display: inline-block;">Go to Dashboard</a></p>
                    <p>Let's make move-out easy.</p>
                </div>
                """
            )
            
            # Redirect straight to action
            flash("Welcome! Complete your profile to secure your spot.", "success")
            return redirect(get_user_dashboard())
    
    pickup_period_active = get_pickup_period_active()
    return render_template('index.html', pickup_period_active=pickup_period_active)

@app.route('/about')
def about():
    return render_template('about.html')

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
        {'url': '/about', 'priority': '0.8', 'changefreq': 'monthly'},
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
    from flask import Response
    
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
            # Create new lead user (like waitlist flow)
            new_user = User(email=email, full_name=name, referral_source='in_person_dropoff')
            db.session.add(new_user)
            db.session.commit()
            flash("Thanks! We'll email you when your item sells.", "success")
        
        return render_template('dropoff.html', success=True, email=email)
    
    return render_template('dropoff.html')

@app.route('/inventory')
def inventory():
    cat_id = request.args.get('category_id')
    commodities = InventoryCategory.query.all() 
    
    # Show Available or Sold (Hide Pending)
    query = InventoryItem.query.filter(InventoryItem.status != 'pending_valuation').order_by(InventoryItem.status.asc(), InventoryItem.date_added.desc())

    if cat_id:
        query = query.filter_by(category_id=cat_id)
        
    items = query.all()
    return render_template('inventory.html', commodities=commodities, items=items, active_cat=cat_id)

@app.route('/item/<int:item_id>')
def product_detail(item_id):
    item = InventoryItem.query.get_or_404(item_id)
    return render_template('product.html', item=item)

# --- IMAGE SERVING ROUTE (CRITICAL FOR RENDER) ---
@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/buy_item/<int:item_id>')
def buy_item(item_id):
    item = InventoryItem.query.get_or_404(item_id)
    
    if item.status == 'sold':
        return "Sorry! This item was just purchased."

    try:
        # Note: We use the new 'uploaded_file' route for the image URL here
        img_url = url_for('uploaded_file', filename=item.photo_url, _external=True)
        
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'usd',
                    'product_data': {
                        'name': item.description,
                        'images': [img_url],
                    },
                    'unit_amount': int(item.price * 100),
                },
                'quantity': 1,
            }],
            mode='payment',
            client_reference_id=str(item.id),
            # Metadata is crucial for the Webhook to know what to do
            metadata={'type': 'item_purchase', 'item_id': item.id},
            success_url=url_for('item_sold_success', _external=True) + '?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=url_for('inventory', _external=True),
        )
        return redirect(checkout_session.url, code=303)
    except Exception as e:
        return str(e)

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
        if session_obj.payment_status == 'paid' and item.status == 'available':
            item.status = 'sold'
            item.sold_at = datetime.utcnow()
            if item.category and item.category.count_in_stock > 0:
                item.category.count_in_stock -= 1
            db.session.commit()
            print(f"IMMEDIATE: Item {item_id} marked as sold from success page.")
        
        return render_template('item_success.html', item=item)
    except Exception as e:
        print(f"Error in item_success route: {e}")
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
            item = InventoryItem.query.get(item_id)
            
            if item:
                # Only update if still available (prevent double-processing)
                if item.status == 'available':
                    # 1. Update DB
                    item.status = 'sold'
                    item.sold_at = datetime.utcnow()  # Track when it sold
                    if item.category and item.category.count_in_stock > 0:
                        item.category.count_in_stock -= 1
                    db.session.commit()
                    print(f"WEBHOOK: Item {item_id} sold.")
                else:
                    print(f"WEBHOOK: Item {item_id} already marked as sold (status: {item.status}).")
                
                # 2. Email Seller (with 40% payout details)
                if item.seller:
                    send_email(
                        item.seller.email,
                        "Your Item Has Sold! - Campus Swap",
                        _item_sold_email_html(item, item.seller)
                    )

        # --- CASE 2: SELLER ACTIVATION ---
        elif session.get('metadata', {}).get('type') == 'seller_activation':
            user_id = session.get('metadata').get('user_id')
            user = User.query.get(user_id)
            
            if user:
                # 1. Update DB
                user.has_paid = True
                user.is_seller = True
                db.session.commit()
                print(f"WEBHOOK: User {user_id} activated.")
                
                # 2. Email User
                send_email(
                    user.email,
                    "You are officially a Campus Swap Seller!",
                    f"""
                    <div style="font-family: sans-serif; padding: 20px;">
                        <h2>Welcome to the Team!</h2>
                        <p>Thanks for activating your seller account, {user.full_name}.</p>
                        <p><strong>Your status is now: ACTIVE.</strong></p>
                        <p>Any items you drafted will be reviewed by our team shortly. Once approved, they will go live on the site.</p>
                        <br>
                        <a href="{url_for('dashboard', _external=True)}" style="background: #166534; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">Go to Dashboard</a>
                    </div>
                    """
                )

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
    
    # Admin can toggle pickup period
    if request.method == 'POST' and 'toggle_pickup_period' in request.form:
        current_status = get_pickup_period_active()
        new_status = not current_status
        AppSetting.set('pickup_period_active', str(new_status))
        flash(f"Pickup period {'activated' if new_status else 'closed'}.", "success")

    # 1. Update Category Counts
    if request.method == 'POST' and 'update_all_counts' in request.form:
        for key, value in request.form.items():
            if key.startswith('counts_'):
                try:
                    cat_id = int(key.split('_')[1])
                    cat = InventoryCategory.query.get(cat_id)
                    if cat: cat.count_in_stock = int(value)
                except ValueError: pass
        db.session.commit()

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
            # Quick Add is always in-person drop-off, status pending (price set later)
            collection_method = request.form.get('collection_method', 'in_person')
            new_item = InventoryItem(
                category_id=cat_id, description=desc, long_description=long_desc,
                price=None, quality=int(quality), photo_url="", status="pending_valuation",
                seller_id=seller_id, collection_method=collection_method
            )
            db.session.add(new_item)
            db.session.flush()
            
            cover_set = False
            for i, file in enumerate(files):
                if file.filename:
                    filename = f"item_{new_item.id}_{int(time.time())}_{i}.jpg"
                    save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    
                    img = Image.open(file).convert("RGBA")
                    bg = Image.new("RGB", img.size, (255, 255, 255))
                    bg.paste(img, (0, 0), img)
                    bg.save(save_path, "JPEG", quality=80)
                    
                    if not cover_set:
                        new_item.photo_url = filename
                        cover_set = True
                    db.session.add(ItemPhoto(item_id=new_item.id, photo_url=filename))
            
            # Don't increment count_in_stock yet - item is pending, not available
            db.session.commit()
            flash(f"Item '{desc}' added to pending items. Set price to approve.", "success")

    # 3. Bulk Update Items
    if request.method == 'POST' and 'bulk_update_items' in request.form:
        updated_count = 0
        for key, value in request.form.items():
            if key.startswith('price_'):
                try:
                    item_id = int(key.split('_')[1])
                    item = InventoryItem.query.get(item_id)
                    if item:
                        new_price = float(value) if value and value.strip() else None
                        
                        # Auto-Activate if pending item gets a price
                        # In-person items can go live without user paying; online items require payment
                        if item.status == 'pending_valuation' and new_price is not None:
                            # Check if item can go live (in-person items bypass payment requirement)
                            can_go_live = False
                            if item.collection_method == 'in_person':
                                can_go_live = True  # In-person items don't require payment
                            elif item.seller and item.seller.has_paid:
                                can_go_live = True  # Online items require user to have paid
                            elif not item.seller:
                                can_go_live = True  # Admin-uploaded items (no seller) can go live
                            
                            if can_go_live:
                                item.status = 'available'
                                cat = InventoryCategory.query.get(item.category_id)
                                if cat: cat.count_in_stock += 1
                                
                                # NOTIFY SELLER THEIR ITEM IS LIVE
                                if item.seller:
                                    try:
                                        item_url = url_for('product_detail', item_id=item.id, _external=True)
                                        send_email(
                                            item.seller.email,
                                            "Your Item is Live! - Campus Swap",
                                            f"""
                                            <div style="font-family: sans-serif; padding: 20px; max-width: 500px;">
                                                <h2 style="color: #166534;">Your item is live!</h2>
                                                <p>Great news! <strong>{item.description}</strong> has been approved and is now listed for sale.</p>
                                                <p>Price: <strong>${new_price:.2f}</strong> — when it sells, you'll get 40%.</p>
                                                <p><a href="{item_url}" style="background: #166534; color: white; padding: 12px 24px; text-decoration: none; border-radius: 8px; display: inline-block;">View listing</a></p>
                                            </div>
                                            """
                                        )
                                    except Exception as e:
                                        print(f"Error sending email notification: {e}")
                            else:
                                flash(f"{item.description} cannot go live yet - seller needs to complete payment.", "warning")
                        
                        item.price = new_price
                        updated_count += 1
                        
                        # Quality & Category Updates
                        if f"quality_{item_id}" in request.form:
                            try:
                                item.quality = int(request.form[f"quality_{item_id}"])
                            except ValueError:
                                pass
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
                    print(f"Error updating item {key}: {e}")
                    continue
                except Exception as e:
                    print(f"Unexpected error updating item {key}: {e}")
                    import traceback
                    traceback.print_exc()
                    continue
        
        try:
            db.session.commit()
            if updated_count > 0:
                flash(f"Updated {updated_count} item(s).", "success")
        except Exception as e:
            db.session.rollback()
            print(f"Error committing changes: {e}")
            import traceback
            traceback.print_exc()
            flash("Error updating items. Please try again.", "error")

    # 4. Delete / Sold / Available Toggles
    if request.method == 'POST':
        if 'delete_item' in request.form:
            item = InventoryItem.query.get(request.form.get('delete_item'))
            if item:
                if item.status == 'available':
                    cat = InventoryCategory.query.get(item.category_id)
                    if cat and cat.count_in_stock > 0: cat.count_in_stock -= 1
                db.session.delete(item)
                db.session.commit()
        
        elif 'mark_sold' in request.form:
            item = InventoryItem.query.get(request.form.get('mark_sold'))
            if item and item.status == 'available':
                item.status = "sold"
                item.sold_at = datetime.utcnow()  # Track when it sold
                cat = InventoryCategory.query.get(item.category_id)
                if cat and cat.count_in_stock > 0: cat.count_in_stock -= 1
                db.session.commit()
                # Email seller (same as webhook - 40% payout details)
                if item.seller:
                    send_email(
                        item.seller.email,
                        "Your Item Has Sold! - Campus Swap",
                        _item_sold_email_html(item, item.seller)
                    )
        
        elif 'mark_payout_sent' in request.form:
            item = InventoryItem.query.get(request.form.get('mark_payout_sent'))
            if item and item.status == 'sold':
                item.payout_sent = True
                db.session.commit()
                flash(f"Payout marked as sent for {item.description}.", "success")

        elif 'mark_available' in request.form:
            item = InventoryItem.query.get(request.form.get('mark_available'))
            if item and item.status == 'sold':
                item.status = "available"
                item.sold_at = None  # Reset sold timestamp
                item.payout_sent = False  # Reset payout status
                cat = InventoryCategory.query.get(item.category_id)
                if cat: cat.count_in_stock += 1
                db.session.commit()

    # Data Loading
    commodities = InventoryCategory.query.all()
    all_cats = InventoryCategory.query.all()
    
    # Filter: Show pending items
    # - In-person items can always be approved (no payment needed)
    # - Online items from paid users can be approved
    # - Admin-uploaded items (no seller) can be approved
    from sqlalchemy import or_
    pending_items = InventoryItem.query.outerjoin(User).filter(
        InventoryItem.status == 'pending_valuation',
        or_(
            InventoryItem.collection_method == 'in_person',  # In-person items (no payment needed)
            User.has_paid == True,  # Items from users who paid
            InventoryItem.seller_id.is_(None)  # Admin-uploaded items (no seller)
        )
    ).order_by(InventoryItem.date_added.asc()).all()
    
    gallery_items = InventoryItem.query.filter(InventoryItem.status != 'pending_valuation').order_by(InventoryItem.date_added.desc()).all()
    
    pickup_period_active = get_pickup_period_active()
    return render_template('admin.html', commodities=commodities, all_cats=all_cats, 
                           pending_items=pending_items, gallery_items=gallery_items,
                           pickup_period_active=pickup_period_active)


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
        item.description = request.form['description']
        if request.form.get('price'):
             item.price = float(request.form['price'])
        item.quality = int(request.form['quality'])
        item.long_description = request.form['long_description']
        if request.form.get('category_id'):
            item.category_id = int(request.form['category_id'])
        
        # Handle new photo uploads
        new_photos = request.files.getlist('new_photos')
        if new_photos and new_photos[0].filename != '':
            for i, file in enumerate(new_photos):
                if file.filename:
                    filename = f"item_{item.id}_{int(time.time())}_{i}.jpg"
                    save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    
                    img = Image.open(file).convert("RGBA")
                    bg = Image.new("RGB", img.size, (255, 255, 255))
                    bg.paste(img, (0, 0), img)
                    bg.save(save_path, "JPEG", quality=80)
                    
                    # If no cover photo exists, set first new photo as cover
                    if not item.photo_url:
                        item.photo_url = filename
                    
                    db.session.add(ItemPhoto(item_id=item.id, photo_url=filename))
        
        db.session.commit()
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
        print(f"Error deleting file: {e}")

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
            print(f"Database error in set_password: {db_error}")
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
                print(f"Error building dashboard URL: {url_error}")
                # Fallback to relative URL
                dashboard_url = url_for('dashboard')
            
            send_email(
                current_user.email,
                "Account Secured - Campus Swap",
                f"""
                <div style="font-family: sans-serif; padding: 20px; max-width: 500px;">
                    <h2 style="color: #166534;">Account Secured!</h2>
                    <p>Your password has been set successfully. You can now log in anytime with your email and password.</p>
                    <p><a href="{dashboard_url}" style="background: #166534; color: white; padding: 12px 24px; text-decoration: none; border-radius: 8px; display: inline-block;">Go to Dashboard</a></p>
                </div>
                """
            )
        except Exception as email_error:
            # Email failure is non-critical - log but don't crash
            print(f"Email sending failed in set_password (non-critical): {email_error}")
            import traceback
            traceback.print_exc()
        
        flash("Account secured! You can now log in anytime.", "success")
        
        # Redirect with fallback
        try:
            return redirect(get_user_dashboard())
        except Exception as redirect_error:
            print(f"Redirect error in set_password: {redirect_error}")
            # Fallback redirect
            try:
                if current_user.is_admin:
                    return redirect(url_for('admin_panel'))
                return redirect(url_for('dashboard'))
            except:
                return redirect(url_for('index'))
                
    except Exception as e:
        # Catch-all for any unexpected errors
        print(f"Unexpected error in set_password route: {e}")
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
    return render_template('account_settings.html')

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
    
    if full_name:
        current_user.full_name = full_name
        db.session.commit()
        flash("Account information updated successfully!", "success")
    else:
        flash("Full name cannot be empty.", "error")
    
    return redirect(url_for('account_settings'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(get_user_dashboard())

    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        full_name = request.form.get('full_name')
        
        user = User.query.filter_by(email=email).first()
        
        if user:
            # Converting a Lead to a User
            if user.password_hash is None:
                user.password_hash = generate_password_hash(password)
                user.full_name = full_name
                db.session.commit()
                login_user(user)
                dashboard_url = url_for('dashboard', _external=True)
                send_email(
                    email,
                    "Your Campus Swap Account is Ready!",
                    f"""
                    <div style="font-family: sans-serif; padding: 20px; max-width: 500px;">
                        <h2 style="color: #166534;">Account Complete!</h2>
                        <p>Hi {full_name or 'there'}, your Campus Swap account is all set.</p>
                        <p>You can now log in anytime with your email and password to manage your items and track payouts.</p>
                        <p><a href="{dashboard_url}" style="background: #166534; color: white; padding: 12px 24px; text-decoration: none; border-radius: 8px; display: inline-block;">Go to Dashboard</a></p>
                    </div>
                    """
                )
                return redirect(get_user_dashboard())
            else:
                flash("Account already exists. Please log in.", "error")
                return redirect(url_for('login'))
        
        new_user = User(email=email, full_name=full_name, password_hash=generate_password_hash(password))
        db.session.add(new_user)
        db.session.commit()
        login_user(new_user)
        dashboard_url = url_for('dashboard', _external=True)
        send_email(
            email,
            "Welcome to Campus Swap!",
            f"""
            <div style="font-family: sans-serif; padding: 20px; max-width: 500px;">
                <h2 style="color: #166534;">Welcome, {full_name or 'there'}!</h2>
                <p>Your Campus Swap account has been created. You're ready to start selling.</p>
                <p><strong>Next steps:</strong></p>
                <ul>
                    <li>Add your pickup address</li>
                    <li>Upload photos of your items</li>
                    <li>Complete activation ($15) to go live</li>
                </ul>
                <p><a href="{dashboard_url}" style="background: #166534; color: white; padding: 12px 24px; text-decoration: none; border-radius: 8px; display: inline-block;">Go to Dashboard</a></p>
            </div>
            """
        )
        return redirect(get_user_dashboard())

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(get_user_dashboard())
    
    # Pre-fill email if passed as query param (from waitlist redirect)
    prefill_email = request.args.get('email', '')
        
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        user = User.query.filter_by(email=email).first()
        
        if user and user.password_hash and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(get_user_dashboard())
        else:
            flash("Invalid email or password.", "error")
            prefill_email = email  # Keep email filled on error
    return render_template('login.html', prefill_email=prefill_email)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    # Admins should use admin panel, not seller dashboard
    if current_user.is_admin:
        return redirect(url_for('admin_panel'))
    
    # Refresh user object to ensure we have latest data (especially has_paid status)
    # This is important after payment webhook updates
    # Expire the cached user object and reload from database
    db.session.expire(current_user)
    db.session.refresh(current_user)
    
    my_items = InventoryItem.query.filter_by(seller_id=current_user.id).all()
    # Check if user has any online items (which require payment)
    has_online_items = any(item.collection_method == 'online' for item in my_items)
    
    # Calculate payout statistics
    live_items = [item for item in my_items if item.status == 'available']
    sold_items = [item for item in my_items if item.status == 'sold']
    
    # Estimated payout (40% of live items)
    estimated_payout = sum(item.price for item in live_items if item.price) * 0.40
    
    # Paid out (40% of sold items where payout_sent=True)
    paid_out = sum(item.price for item in sold_items if item.price and item.payout_sent) * 0.40
    
    # Pending payouts (40% of sold items where payout_sent=False)
    pending_payouts = sum(item.price for item in sold_items if item.price and not item.payout_sent) * 0.40
    
    # Total potential (estimated + pending + paid)
    total_potential = estimated_payout + pending_payouts + paid_out
    
    return render_template('dashboard.html', 
                          my_items=my_items, 
                          has_online_items=has_online_items,
                          estimated_payout=estimated_payout,
                          paid_out=paid_out,
                          pending_payouts=pending_payouts,
                          total_potential=total_potential,
                          sold_items=sold_items)

@app.route('/update_profile', methods=['POST'])
@login_required
def update_profile():
    address = request.form.get('address')
    if address:
        current_user.pickup_address = address
        db.session.commit()
        flash("Address updated.", "success")
    # Remove scroll parameter - form is already visible
    return redirect(get_user_dashboard())

@app.route('/update_payout', methods=['POST'])
@login_required
def update_payout():
    method = request.form.get('payout_method')
    handle = request.form.get('payout_handle')
    
    if method and handle:
        clean_handle = handle.replace('@', '').strip()
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

@app.route('/create_checkout_session', methods=['POST'])
@login_required
def create_checkout_session():
    try:
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'usd',
                    'product_data': {'name': 'Campus Swap Seller Registration'},
                    'unit_amount': 1500,
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
            
            # Check if this is a seller activation payment
            if stripe_session.metadata and stripe_session.metadata.get('type') == 'seller_activation':
                user_id = int(stripe_session.metadata.get('user_id'))
                
                # Verify it's the current user
                if user_id == current_user.id and stripe_session.payment_status == 'paid':
                    # Update user payment status if not already set
                    if not current_user.has_paid:
                        current_user.has_paid = True
                        current_user.is_seller = True
                        db.session.commit()
                    
                    # Refresh user object to ensure latest data
                    db.session.expire(current_user)
                    db.session.refresh(current_user)
                    
                    flash("Payment successful! You can now list items.", "success")
        except Exception as e:
            print(f"Error verifying payment: {e}")
            # Still show success message - webhook will handle it
            flash("Payment received! Processing...", "info")
    else:
        flash("Payment successful! You can now list items.", "success")
    
    return redirect(get_user_dashboard())

@app.route('/add_item', methods=['GET', 'POST'])
@login_required
def add_item():
    # Block item uploads when pickup period is closed
    if not get_pickup_period_active():
        flash("Pickup period has ended. Items can no longer be added. Check back next year!", "error")
        return redirect(get_user_dashboard())
    
    categories = InventoryCategory.query.all()

    if request.method == 'POST':
        cat_id = request.form.get('category_id')
        desc = request.form.get('description')
        long_desc = request.form.get('long_description')
        quality = request.form.get('quality')
        files = request.files.getlist('photos')
        
        if files and files[0].filename != '':
            new_item = InventoryItem(
                seller_id=current_user.id, category_id=cat_id, description=desc,
                long_description=long_desc, quality=int(quality), status="pending_valuation", photo_url="",
                collection_method='online'  # User-uploaded items are always 'online'
            )
            db.session.add(new_item)
            db.session.flush()
            
            cover_set = False
            for i, file in enumerate(files):
                if file.filename:
                    filename = f"item_{new_item.id}_{int(time.time())}_{i}.jpg"
                    save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    
                    img = Image.open(file).convert("RGBA")
                    bg = Image.new("RGB", img.size, (255, 255, 255))
                    bg.paste(img, (0, 0), img)
                    bg.save(save_path, "JPEG", quality=80)
                    
                    if not cover_set:
                        new_item.photo_url = filename
                        cover_set = True
                    db.session.add(ItemPhoto(item_id=new_item.id, photo_url=filename))
            
            db.session.commit()
            flash("Item drafted! Complete your activation to list it.", "success")
            return redirect(get_user_dashboard())
            
    return render_template('add_item.html', categories=categories)

if __name__ == '__main__':
    with app.app_context():
        # Only create DB if it doesn't exist (Local SQLite check)
        # On Render, we use migrations.
        if not os.path.exists('campus.db') and 'DATABASE_URL' not in os.environ:
            db.create_all()
    app.run(debug=True, port=4242, host='0.0.0.0')