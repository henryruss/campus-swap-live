import os
import time
from PIL import Image
import stripe
from flask import Flask, render_template, request, redirect, url_for, flash, session
from werkzeug.utils import secure_filename
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash

# Import Models
from models import db, User, InventoryCategory, InventoryItem, ItemPhoto

# --- APP CONFIGURATION ---
app = Flask(__name__)

# SECURITY WARNING: Change this to a random string before deploying!
app.secret_key = 'dev_key' 

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///campus.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'static/uploads'

# Initialize DB
db.init_app(app)

# STRIPE CONFIGURATION
stripe.api_key = os.environ.get('STRIPE_SECRET_KEY')

# LOGIN MANAGER CONFIGURATION
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# =========================================================
# SECTION 1: PUBLIC & LANDING ROUTES
# =========================================================

# In app.py

@app.route('/', methods=['GET', 'POST'])
def index():
    # 1. TRACKING LOGIC: If they arrive with ?source=qr_code, save it!
    if request.args.get('source'):
        session['source'] = request.args.get('source')

    if request.method == 'POST':
        email = request.form.get('email')
        
        # Check if they already exist
        existing_user = User.query.filter_by(email=email).first()
        
        if existing_user:
            flash("You're already on the list! We'll email you soon.", "success")
        else:
            # RETRIEVE TRACKING DATA
            source = session.get('source', 'direct') # Default to 'direct' if no tag
            
            # CREATE THE LEAD
            new_lead = User(email=email, referral_source=source)
            db.session.add(new_lead)
            db.session.commit()
            
            # Change the flash message to feel like a "Win"
            flash("Success! Your seller spot is reserved.", "success")
            
        return redirect(url_for('index'))

    return render_template('index.html')


# =========================================================
# SECTION 2: MARKETPLACE ROUTES (Shop, Buy, View)
# =========================================================

@app.route('/inventory')
def inventory():
    cat_id = request.args.get('category_id')
    commodities = InventoryCategory.query.all() 
    
    # FILTER: Only show items that are 'available' or 'sold' (Exclude pending)
    query = InventoryItem.query.filter(InventoryItem.status != 'pending_valuation').order_by(InventoryItem.status.asc(), InventoryItem.date_added.desc())

    if cat_id:
        query = query.filter_by(category_id=cat_id)
        
    items = query.all()
    
    return render_template('inventory.html', commodities=commodities, items=items, active_cat=cat_id)

@app.route('/item/<int:item_id>')
def product_detail(item_id):
    item = InventoryItem.query.get_or_404(item_id)
    return render_template('product.html', item=item)


@app.route('/buy_item/<int:item_id>')
def buy_item(item_id):
    item = InventoryItem.query.get_or_404(item_id)
    
    if item.status == 'sold':
        return "Sorry! This item was just purchased by someone else."

    try:
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'usd',
                    'product_data': {
                        'name': item.description,
                        'images': [url_for('static', filename='uploads/' + item.photo_url, _external=True)],
                    },
                    'unit_amount': int(item.price * 100),
                },
                'quantity': 1,
            }],
            mode='payment',
            client_reference_id=str(item.id),
            success_url=url_for('item_sold_success', _external=True) + '?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=url_for('inventory', _external=True),
        )
        return redirect(checkout_session.url, code=303)
    except Exception as e:
        return str(e)


# SUCCESS ROUTE FOR BUYING ITEMS (Customer)
@app.route('/item_success')
def item_sold_success():
    session_id = request.args.get('session_id')
    session = stripe.checkout.Session.retrieve(session_id)
    item_id = session.client_reference_id
    
    item = InventoryItem.query.get(item_id)
    if item and item.status == 'available':
        item.status = 'sold'
        
        # AUTOMATION: Decrease Stock Count
        if item.category.count_in_stock > 0:
            item.category.count_in_stock -= 1
            
        db.session.commit()
        
    return render_template('item_success.html', item=item)


# =========================================================
# SECTION 3: ADMIN & MANAGEMENT ROUTES
# =========================================================

@app.route('/admin', methods=['GET', 'POST'])
def admin_panel():
    
    # --- ACTION 1: Bulk Update COMMODITIES ---
    if request.method == 'POST' and 'update_all_counts' in request.form:
        for key, value in request.form.items():
            if key.startswith('counts_'):
                try:
                    cat_id = int(key.split('_')[1])
                    category = InventoryCategory.query.get(cat_id)
                    if category:
                        category.count_in_stock = int(value)
                except ValueError:
                    pass
        db.session.commit()

    # --- ACTION 2: Add New Item ---
    if request.method == 'POST' and 'add_item' in request.form:
        cat_id = request.form.get('category_id')
        desc = request.form.get('description')
        long_desc = request.form.get('long_description')
        price = request.form.get('price')
        quality = request.form.get('quality')
        
        files = request.files.getlist('photos')
        
        if files and files[0].filename != '':
            new_item = InventoryItem(
                category_id=cat_id,
                description=desc,
                long_description=long_desc,
                price=float(price),
                quality=int(quality),
                photo_url="", 
                status="available"
            )
            db.session.add(new_item)
            db.session.flush()
            
            cover_photo_set = False
            for i, file in enumerate(files):
                if file.filename:
                    filename = f"item_{new_item.id}_{int(time.time())}_{i}.jpg"
                    save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    
                    img = Image.open(file)
                    img = img.convert("RGBA")
                    background = Image.new("RGB", img.size, (255, 255, 255))
                    background.paste(img, (0, 0), img)
                    img = background
                    img.save(save_path, "JPEG", quality=80)
                    
                    if not cover_photo_set:
                        new_item.photo_url = filename
                        cover_photo_set = True
                    
                    gallery_pic = ItemPhoto(item_id=new_item.id, photo_url=filename)
                    db.session.add(gallery_pic)

            category = InventoryCategory.query.get(cat_id)
            if category:
                category.count_in_stock += 1
            db.session.commit()

    # --- ACTION 3: BATCH UPDATE (Prices, Quality, Category) ---
    if request.method == 'POST' and 'bulk_update_items' in request.form:
        for key, value in request.form.items():
            if key.startswith('price_'):
                try:
                    item_id = int(key.split('_')[1])
                    item = InventoryItem.query.get(item_id)
                    
                    if item:
                        new_price = float(value) if value else None
                        
                        # AUTOMATION: If pending item gets a price -> Activate it!
                        if item.status == 'pending_valuation' and new_price is not None:
                            item.status = 'available'
                            cat = InventoryCategory.query.get(item.category_id)
                            if cat: cat.count_in_stock += 1
                        
                        item.price = new_price
                        
                        if f"quality_{item_id}" in request.form:
                            item.quality = int(request.form[f"quality_{item_id}"])
                            
                        if f"category_{item_id}" in request.form:
                            new_cat_id = int(request.form[f"category_{item_id}"])
                            if item.category_id != new_cat_id:
                                if item.status == 'available':
                                    old_cat = InventoryCategory.query.get(item.category_id)
                                    new_cat = InventoryCategory.query.get(new_cat_id)
                                    if old_cat: old_cat.count_in_stock -= 1
                                    if new_cat: new_cat.count_in_stock += 1
                                item.category_id = new_cat_id
                                
                except ValueError:
                    pass
        db.session.commit()

    # --- ACTION 4: Row Actions (Delete, Sold, Undo) ---
    if request.method == 'POST' and 'delete_item' in request.form:
        item_id = request.form.get('delete_item')
        item = InventoryItem.query.get(item_id)
        if item:
            if item.status == 'available':
                cat = InventoryCategory.query.get(item.category_id)
                if cat and cat.count_in_stock > 0: cat.count_in_stock -= 1
            db.session.delete(item)
            db.session.commit()

    if request.method == 'POST' and 'mark_sold' in request.form:
        item_id = request.form.get('mark_sold')
        item = InventoryItem.query.get(item_id)
        if item and item.status == 'available':
            item.status = "sold"
            cat = InventoryCategory.query.get(item.category_id)
            if cat and cat.count_in_stock > 0: cat.count_in_stock -= 1
            db.session.commit()

    if request.method == 'POST' and 'mark_available' in request.form:
        item_id = request.form.get('mark_available')
        item = InventoryItem.query.get(item_id)
        if item and item.status == 'sold':
            item.status = "available"
            cat = InventoryCategory.query.get(item.category_id)
            if cat: cat.count_in_stock += 1
            db.session.commit()

# --- LOAD DATA (UPDATED FILTERS) ---
    commodities = InventoryCategory.query.all() 
    all_cats = InventoryCategory.query.all() 
    
    # 1. Pending Items: Only show if the Seller has paid!
    # We join the User table to check 'has_paid'
    pending_items = InventoryItem.query.join(User).filter(
        InventoryItem.status == 'pending_valuation',
        User.has_paid == True 
    ).order_by(InventoryItem.date_added.asc()).all()
    
    # 2. Gallery Items (Active/Sold)
    gallery_items = InventoryItem.query.filter(InventoryItem.status != 'pending_valuation').order_by(InventoryItem.date_added.desc()).all()
    
    return render_template('admin.html', commodities=commodities, all_cats=all_cats, 
                           pending_items=pending_items, gallery_items=gallery_items)


@app.route('/edit_item/<int:item_id>', methods=['GET', 'POST'])
def edit_item(item_id):
    item = InventoryItem.query.get_or_404(item_id)
    
    if request.method == 'POST':
        item.description = request.form['description']
        
        # UNCOMMENTED/RESTORED: Price editing is back!
        if request.form.get('price'):
             item.price = float(request.form['price'])
             
        item.quality = int(request.form['quality'])
        item.long_description = request.form['long_description']
        
        files = request.files.getlist('new_photos')
        # ... (rest of image logic stays the same) ...

        db.session.commit()
        
        # Smart Redirect: If Admin, go to Admin. If User, go to Dashboard.
        if current_user.id == 1: # Assuming you are user 1? Or just check referrer
             return redirect(url_for('admin_panel'))
        return redirect(url_for('dashboard'))
        
    return render_template('edit_item.html', item=item)


@app.route('/delete_photo/<int:photo_id>')
def delete_photo(photo_id):
    photo = ItemPhoto.query.get_or_404(photo_id)
    item = photo.item
    
    try:
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], photo.photo_url)
        if os.path.exists(file_path):
            os.remove(file_path)
    except Exception as e:
        print(f"Error deleting file: {e}")

    if item.photo_url == photo.photo_url:
        remaining_photos = [p for p in item.gallery_photos if p.id != photo.id]
        if remaining_photos:
            item.photo_url = remaining_photos[0].photo_url
        else:
            item.photo_url = ""

    db.session.delete(photo)
    db.session.commit()
    return redirect(url_for('edit_item', item_id=item.id))


# =========================================================
# SECTION 4: SELLER AUTHENTICATION & DASHBOARD
# =========================================================

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        full_name = request.form.get('full_name')
        
        # 1. Check if user exists (Lead Conversion)
        user = User.query.filter_by(email=email).first()
        
        if user:
            # If they are a lead (no password yet)
            if user.password_hash is None:
                user.password_hash = generate_password_hash(password)
                user.full_name = full_name
                db.session.commit()
                login_user(user)
                return redirect(url_for('dashboard'))
            else:
                flash("Account already exists. Please log in.", "error")
                return redirect(url_for('login'))
        
        # 2. New User Registration
        new_user = User(
            email=email,
            full_name=full_name,
            password_hash=generate_password_hash(password)
        )
        db.session.add(new_user)
        db.session.commit()
        
        login_user(new_user)
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
    # Show user's own items
    my_items = InventoryItem.query.filter_by(seller_id=current_user.id).all()
    return render_template('dashboard.html', my_items=my_items)

# --- 1. PROFILE UPDATE ---
@app.route('/update_profile', methods=['POST'])
@login_required
def update_profile():
    address = request.form.get('address')
    if address:
        current_user.pickup_address = address
        db.session.commit()
        flash("Address updated.", "success")
    # Pass 'scroll' param to tell the dashboard where to look
    return redirect(url_for('dashboard', scroll='step-1'))

# --- 2. PAYOUT UPDATE (The Fix) ---
@app.route('/update_payout', methods=['POST'])
@login_required
def update_payout():
    method = request.form.get('payout_method')
    handle = request.form.get('payout_handle')
    
    if method and handle:
        # Clean the handle (remove @ and spaces)
        clean_handle = handle.replace('@', '').strip()
        
        if clean_handle:
            current_user.payout_method = method
            current_user.payout_handle = clean_handle
            
            # Mark as seller now that profile is full
            current_user.is_seller = True
            
            db.session.commit()
            # FORCE REFRESH: Ensures data is actually persisted
            db.session.refresh(current_user)
            
            flash(f"Payout info secured.", "success")
        else:
            flash("Please enter a valid handle.", "error")
            
    # Scroll back to Step 3
    return redirect(url_for('dashboard', scroll='step-3'))

# --- NEW PAYMENT ROUTE (FROM DASHBOARD) ---
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
                    'unit_amount': 1500, # $15.00
                },
                'quantity': 1,
            }],
            mode='payment',
            client_reference_id=str(current_user.id),
            success_url=url_for('payment_success', _external=True) + '?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=url_for('dashboard', _external=True),
        )
        return redirect(checkout_session.url, code=303)
    except Exception as e:
        return str(e)

# SUCCESS ROUTE FOR SELLER REGISTRATION
@app.route('/success')
@login_required
def payment_success():
    session_id = request.args.get('session_id')
    if not session_id:
        return redirect(url_for('dashboard'))

    # Verify session with Stripe
    session = stripe.checkout.Session.retrieve(session_id)
    
    # Check if the payment was for the current user
    if session.client_reference_id == str(current_user.id):
        # STRICT FIX: Explicitly fetch user to ensure commit
        user_to_update = User.query.get(current_user.id)
        user_to_update.has_paid = True
        user_to_update.is_seller = True 
        db.session.commit()
        flash("Payment successful! You can now list items.", "success")
    
    return redirect(url_for('dashboard'))


# --- SELLER ADD ITEM ROUTE ---
@app.route('/add_item', methods=['GET', 'POST'])
@login_required
def add_item():
    # REMOVED: The check for is_seller/has_paid. 
    # Now anyone can draft items (Step 2 of the flow).

    # Load categories for the dropdown
    categories = InventoryCategory.query.all()

    if request.method == 'POST':
        cat_id = request.form.get('category_id')
        desc = request.form.get('description')
        long_desc = request.form.get('long_description')
        quality = request.form.get('quality')
        
        files = request.files.getlist('photos')
        
        if files and files[0].filename != '':
            # Create Item (Status: pending_valuation)
            new_item = InventoryItem(
                seller_id=current_user.id,
                category_id=cat_id,
                description=desc,
                long_description=long_desc,
                quality=int(quality),
                status="pending_valuation", 
                photo_url=""
            )
            db.session.add(new_item)
            db.session.flush()
            
            # --- KEEP THIS IMAGE LOGIC ---
            cover_set = False
            for i, file in enumerate(files):
                if file.filename:
                    filename = f"item_{new_item.id}_{int(time.time())}_{i}.jpg"
                    save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    
                    # Convert to RGB/JPEG safely
                    img = Image.open(file)
                    img = img.convert("RGBA")
                    background = Image.new("RGB", img.size, (255, 255, 255))
                    background.paste(img, (0, 0), img)
                    img = background
                    img.save(save_path, "JPEG", quality=80)
                    
                    if not cover_set:
                        new_item.photo_url = filename
                        cover_set = True
                    
                    db.session.add(ItemPhoto(item_id=new_item.id, photo_url=filename))
            # -----------------------------
            
            db.session.commit()
            flash("Item drafted! Complete your activation to list it.", "success")
            return redirect(url_for('dashboard'))
            
    return render_template('add_item.html', categories=categories)

@app.route('/force_paid')
@login_required
def force_paid():
    # Force the current user to be paid/seller
    user = User.query.get(current_user.id)
    user.has_paid = True
    user.is_seller = True
    db.session.commit()
    flash("DEBUG: Account manually set to PAID.", "success")
    return redirect(url_for('dashboard'))

if __name__ == '__main__':
    with app.app_context():
        if not os.path.exists('campus.db'):
            db.create_all()
    app.run(debug=True, port=4242, host='0.0.0.0')