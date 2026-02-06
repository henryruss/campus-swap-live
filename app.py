import os
import time
import json
from dotenv import load_dotenv
load_dotenv()  # Load .env for local dev (Render uses env vars directly)

from PIL import Image
import stripe
import resend
from flask import Flask, render_template, request, redirect, url_for, flash, session, send_from_directory, jsonify
from werkzeug.utils import secure_filename
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect

# Import Models
from models import db, User, InventoryCategory, InventoryItem, ItemPhoto

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
        <h2 style="color: #166534;">Cha-Ching! 💸</h2>
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
        
        # Check if user already exists
        user = User.query.filter_by(email=email).first()
        
        if user:
            # SCENARIO A: User exists
            if user.password_hash:
                # If they have a password, ask them to login
                flash("You already have an account. Please log in.", "info")
                return redirect(url_for('login'))
            else:
                # SCENARIO B: Existing Lead (No password yet) -> Log them in & go to dashboard
                login_user(user)
                return redirect(url_for('dashboard'))
        
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
                    <h2 style="color: #166534;">You're on the list! 🎉</h2>
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
            return redirect(url_for('dashboard'))

    return render_template('index.html')


# =========================================================
# SECTION 2: MARKETPLACE ROUTES
# =========================================================

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
    # WEBHOOK UPDATE: This route is now READ-ONLY.
    session_id = request.args.get('session_id')
    if not session_id:
        return redirect(url_for('inventory'))
    
    session_obj = stripe.checkout.Session.retrieve(session_id)
    item_id = session_obj.metadata.get('item_id')
    
    item = InventoryItem.query.get(item_id)
    return render_template('item_success.html', item=item)


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
            
            if item and item.status == 'available':
                # 1. Update DB
                item.status = 'sold'
                if item.category and item.category.count_in_stock > 0:
                    item.category.count_in_stock -= 1
                db.session.commit()
                print(f"WEBHOOK: Item {item_id} sold.")
                
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
                        <h2>Welcome to the Team! 🚀</h2>
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

    # 2. Add Item (Admin Side)
    if request.method == 'POST' and 'add_item' in request.form:
        cat_id = request.form.get('category_id')
        desc = request.form.get('description')
        long_desc = request.form.get('long_description')
        price = request.form.get('price')
        quality = request.form.get('quality')
        files = request.files.getlist('photos')
        
        if files and files[0].filename != '':
            new_item = InventoryItem(
                category_id=cat_id, description=desc, long_description=long_desc,
                price=float(price), quality=int(quality), photo_url="", status="available"
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
            
            cat = InventoryCategory.query.get(cat_id)
            if cat: cat.count_in_stock += 1
            db.session.commit()

    # 3. Bulk Update Items
    if request.method == 'POST' and 'bulk_update_items' in request.form:
        for key, value in request.form.items():
            if key.startswith('price_'):
                try:
                    item_id = int(key.split('_')[1])
                    item = InventoryItem.query.get(item_id)
                    if item:
                        new_price = float(value) if value else None
                        
                        # Auto-Activate if pending item gets a price
                        if item.status == 'pending_valuation' and new_price is not None:
                            item.status = 'available'
                            cat = InventoryCategory.query.get(item.category_id)
                            if cat: cat.count_in_stock += 1
                            
                            # NOTIFY SELLER THEIR ITEM IS LIVE
                            if item.seller:
                                item_url = url_for('product_detail', item_id=item.id, _external=True)
                                send_email(
                                    item.seller.email,
                                    "Your Item is Live! - Campus Swap",
                                    f"""
                                    <div style="font-family: sans-serif; padding: 20px; max-width: 500px;">
                                        <h2 style="color: #166534;">Your item is live! 🚀</h2>
                                        <p>Great news! <strong>{item.description}</strong> has been approved and is now listed for sale.</p>
                                        <p>Price: <strong>${(item.price or 0):.2f}</strong> — when it sells, you'll get 40%.</p>
                                        <p><a href="{item_url}" style="background: #166534; color: white; padding: 12px 24px; text-decoration: none; border-radius: 8px; display: inline-block;">View listing</a></p>
                                    </div>
                                    """
                                )
                        
                        item.price = new_price
                        
                        # Quality & Category Updates
                        if f"quality_{item_id}" in request.form:
                            item.quality = int(request.form[f"quality_{item_id}"])
                        if f"category_{item_id}" in request.form:
                            new_cat_id = int(request.form[f"category_{item_id}"])
                            if item.category_id != new_cat_id and item.status == 'available':
                                old_cat = InventoryCategory.query.get(item.category_id)
                                new_cat = InventoryCategory.query.get(new_cat_id)
                                if old_cat: old_cat.count_in_stock -= 1
                                if new_cat: new_cat.count_in_stock += 1
                            item.category_id = new_cat_id
                except ValueError: pass
        db.session.commit()

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

        elif 'mark_available' in request.form:
            item = InventoryItem.query.get(request.form.get('mark_available'))
            if item and item.status == 'sold':
                item.status = "available"
                cat = InventoryCategory.query.get(item.category_id)
                if cat: cat.count_in_stock += 1
                db.session.commit()

    # Data Loading
    commodities = InventoryCategory.query.all()
    all_cats = InventoryCategory.query.all()
    
    # Filter: Show pending items only if user has paid the fee
    pending_items = InventoryItem.query.join(User).filter(
        InventoryItem.status == 'pending_valuation',
        User.has_paid == True 
    ).order_by(InventoryItem.date_added.asc()).all()
    
    gallery_items = InventoryItem.query.filter(InventoryItem.status != 'pending_valuation').order_by(InventoryItem.date_added.desc()).all()
    
    return render_template('admin.html', commodities=commodities, all_cats=all_cats, 
                           pending_items=pending_items, gallery_items=gallery_items)


@app.route('/edit_item/<int:item_id>', methods=['GET', 'POST'])
@login_required
def edit_item(item_id):
    item = InventoryItem.query.get_or_404(item_id)
    
    # Security: Only Owner or Admin can edit
    # UPDATED to use is_admin
    if item.seller_id != current_user.id and not current_user.is_admin:
        flash("You cannot edit this item.", "error")
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        item.description = request.form['description']
        if request.form.get('price'):
             item.price = float(request.form['price'])
        item.quality = int(request.form['quality'])
        item.long_description = request.form['long_description']
        
        db.session.commit()
        
        if current_user.is_admin:
             return redirect(url_for('admin_panel'))
        return redirect(url_for('dashboard'))
        
    return render_template('edit_item.html', item=item)


@app.route('/delete_photo/<int:photo_id>')
@login_required
def delete_photo(photo_id):
    photo = ItemPhoto.query.get_or_404(photo_id)
    item = photo.item
    
    # Security check
    if item.seller_id != current_user.id and not current_user.is_admin:
        return redirect(url_for('dashboard'))

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
    return redirect(url_for('edit_item', item_id=item.id))


# =========================================================
# SECTION 5: SELLER AUTH & DASHBOARD
# =========================================================

@app.route('/set_password', methods=['POST'])
@login_required
def set_password():
    password = request.form.get('password')
    if password:
        current_user.password_hash = generate_password_hash(password)
        db.session.commit()
        dashboard_url = url_for('dashboard', _external=True)
        send_email(
            current_user.email,
            "Account Secured - Campus Swap",
            f"""
            <div style="font-family: sans-serif; padding: 20px; max-width: 500px;">
                <h2 style="color: #166534;">Account Secured! 🔐</h2>
                <p>Your password has been set successfully. You can now log in anytime with your email and password.</p>
                <p><a href="{dashboard_url}" style="background: #166534; color: white; padding: 12px 24px; text-decoration: none; border-radius: 8px; display: inline-block;">Go to Dashboard</a></p>
            </div>
            """
        )
        flash("Account secured! You can now log in anytime.", "success")
    return redirect(url_for('dashboard'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

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
                        <h2 style="color: #166534;">Account Complete! 🔐</h2>
                        <p>Hi {full_name or 'there'}, your Campus Swap account is all set.</p>
                        <p>You can now log in anytime with your email and password to manage your items and track payouts.</p>
                        <p><a href="{dashboard_url}" style="background: #166534; color: white; padding: 12px 24px; text-decoration: none; border-radius: 8px; display: inline-block;">Go to Dashboard</a></p>
                    </div>
                    """
                )
                return redirect(url_for('dashboard'))
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
                <h2 style="color: #166534;">Welcome, {full_name or 'there'}! 🎉</h2>
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
        return redirect(url_for('dashboard'))

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
        
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        user = User.query.filter_by(email=email).first()
        
        if user and user.password_hash and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for('dashboard'))
        else:
            flash("Invalid email or password.", "error")
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    my_items = InventoryItem.query.filter_by(seller_id=current_user.id).all()
    return render_template('dashboard.html', my_items=my_items)

@app.route('/update_profile', methods=['POST'])
@login_required
def update_profile():
    address = request.form.get('address')
    if address:
        current_user.pickup_address = address
        db.session.commit()
        flash("Address updated.", "success")
    return redirect(url_for('dashboard', scroll='step-1'))

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
    return redirect(url_for('dashboard', scroll='step-3'))

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
    # WEBHOOK UPDATE: This route is now READ-ONLY.
    session_id = request.args.get('session_id')
    if session_id:
         flash("Payment successful! You can now list items.", "success")
    return redirect(url_for('dashboard'))

@app.route('/add_item', methods=['GET', 'POST'])
@login_required
def add_item():
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
                long_description=long_desc, quality=int(quality), status="pending_valuation", photo_url=""
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
            return redirect(url_for('dashboard'))
            
    return render_template('add_item.html', categories=categories)

if __name__ == '__main__':
    with app.app_context():
        # Only create DB if it doesn't exist (Local SQLite check)
        # On Render, we use migrations.
        if not os.path.exists('campus.db') and 'DATABASE_URL' not in os.environ:
            db.create_all()
    app.run(debug=True, port=4242, host='0.0.0.0')