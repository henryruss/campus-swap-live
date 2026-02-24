from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=True)
    full_name = db.Column(db.String(100), nullable=True)
    
    # ADMIN: is_admin = can access admin panel; is_super_admin = full access (user mgmt, approval, etc.)
    is_admin = db.Column(db.Boolean, default=False)
    is_super_admin = db.Column(db.Boolean, default=False)
    
    # SELLER INFO
    phone = db.Column(db.String(20), nullable=True)
    pickup_address = db.Column(db.String(200), nullable=True)
    pickup_location_type = db.Column(db.String(20), nullable=True)  # 'on_campus' or 'off_campus'
    pickup_dorm = db.Column(db.String(80), nullable=True)  # Dorm name for on_campus
    pickup_room = db.Column(db.String(20), nullable=True)  # Room number for on_campus
    pickup_note = db.Column(db.String(200), nullable=True)  # Optional directions (e.g. "third floor")
    pickup_lat = db.Column(db.Float, nullable=True)  # Latitude for map preview (off_campus)
    pickup_lng = db.Column(db.Float, nullable=True)  # Longitude for map preview (off_campus)
    
    # PAYOUT INFO
    payout_method = db.Column(db.String(20), nullable=True)
    payout_handle = db.Column(db.String(100), nullable=True)
    
    # STATUS
    is_seller = db.Column(db.Boolean, default=False) 
    has_paid = db.Column(db.Boolean, default=False)
    payment_declined = db.Column(db.Boolean, default=False)  # Block until valid card added
    
    # STRIPE (for deferred charge at pickup)
    stripe_customer_id = db.Column(db.String(120), nullable=True)
    stripe_payment_method_id = db.Column(db.String(120), nullable=True)
    
    # MARKETING
    referral_source = db.Column(db.String(50), default='direct')
    unsubscribed = db.Column(db.Boolean, default=False)
    unsubscribe_token = db.Column(db.String(64), unique=True, nullable=True)
    
    # OAUTH (Google, etc.)
    oauth_provider = db.Column(db.String(20), nullable=True)
    oauth_id = db.Column(db.String(120), nullable=True)
    
    date_joined = db.Column(db.DateTime, default=datetime.utcnow)
    items = db.relationship('InventoryItem', backref='seller', lazy=True)

    @property
    def has_pickup_location(self):
        """True if user has a valid pickup location set."""
        if self.pickup_location_type == 'on_campus':
            return bool(self.pickup_dorm and self.pickup_room)
        if self.pickup_location_type == 'off_campus' or self.pickup_address:
            return bool(self.pickup_address)
        return False

    @property
    def pickup_display(self):
        """Formatted display string for pickup location."""
        if self.pickup_location_type == 'on_campus' and self.pickup_dorm:
            base = f"{self.pickup_dorm}, Room {self.pickup_room}" if self.pickup_room else self.pickup_dorm
            return base
        if self.pickup_address:
            return self.pickup_address
        return ''

    @property
    def is_guest_account(self):
        """True if user has neither password nor OAuth - needs to create password or link OAuth."""
        return not self.password_hash and not self.oauth_provider

class InventoryCategory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    image_url = db.Column(db.String(200), nullable=True) 
    count_in_stock = db.Column(db.Integer, default=0)
    items = db.relationship('InventoryItem', backref='category', lazy=True)

class InventoryItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    description = db.Column(db.String(200), nullable=False)
    long_description = db.Column(db.Text, nullable=True)
    price = db.Column(db.Float, nullable=True)
    suggested_price = db.Column(db.Float, nullable=True)
    quality = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), default='pending_valuation')
    date_added = db.Column(db.DateTime, default=datetime.utcnow)
    
    # COLLECTION METHOD: 'online' (default) or 'in_person'
    collection_method = db.Column(db.String(20), default='online')
    
    # LARGE ITEM: Admin marks during approval; $10 fee for online items (pickup only)
    is_large = db.Column(db.Boolean, default=False)
    oversize_included_in_service_fee = db.Column(db.Boolean, default=False)  # True = first oversized, waived with $15
    oversize_fee_paid = db.Column(db.Boolean, default=False)  # True when seller paid $10 (additional oversized)
    
    # LOGISTICS (set when seller confirms after approval)
    pickup_week = db.Column(db.String(20), nullable=True)   # 'week1' (Apr 26-May 2) or 'week2' (May 3-May 9)
    dropoff_pod = db.Column(db.String(40), nullable=True)  # 'greek_row' or 'apartment'
    
    # PAYOUT TRACKING
    sold_at = db.Column(db.DateTime, nullable=True)  # When item was marked sold
    payout_sent = db.Column(db.Boolean, default=False)  # Whether seller has been paid
    
    # LIFECYCLE: Operational milestones (do not affect count_in_stock or status)
    picked_up_at = db.Column(db.DateTime, nullable=True)  # When item was collected from seller or placed in POD
    arrived_at_store_at = db.Column(db.DateTime, nullable=True)  # When item physically arrived at store
    
    category_id = db.Column(db.Integer, db.ForeignKey('inventory_category.id'), nullable=False)
    seller_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    
    photo_url = db.Column(db.String(200), nullable=True)
    gallery_photos = db.relationship('ItemPhoto', backref='item', lazy=True, cascade='all, delete-orphan')

    # Price transparency: True when seller has acknowledged that we changed their suggested price
    price_changed_acknowledged = db.Column(db.Boolean, default=False)
    # When we set or change the price (approval or later edit) - badge shows until acknowledged
    price_updated_at = db.Column(db.DateTime, nullable=True)

class ItemPhoto(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey('inventory_item.id'), nullable=False)
    photo_url = db.Column(db.String(200), nullable=False)

class UploadSession(db.Model):
    """Temporary session for QR code mobile-to-desktop photo uploads"""
    id = db.Column(db.Integer, primary_key=True)
    session_token = db.Column(db.String(64), unique=True, nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class TempUpload(db.Model):
    """Temporary photo upload from phone, linked to an UploadSession by session_token"""
    id = db.Column(db.Integer, primary_key=True)
    session_token = db.Column(db.String(64), nullable=False, index=True)
    filename = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class AdminEmail(db.Model):
    """Emails pre-approved for admin/super_admin. Applied when user signs up."""
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    is_super_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class AppSetting(db.Model):
    """Simple key-value store for app-wide settings"""
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.String(200), nullable=False)
    
    @staticmethod
    def get(key, default=None):
        setting = AppSetting.query.filter_by(key=key).first()
        return setting.value if setting else default
    
    @staticmethod
    def set(key, value):
        setting = AppSetting.query.filter_by(key=key).first()
        if setting:
            setting.value = str(value)
        else:
            setting = AppSetting(key=key, value=str(value))
            db.session.add(setting)
        db.session.commit()