from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=True)
    full_name = db.Column(db.String(100), nullable=True)
    
    # NEW: ADMIN TOGGLE
    is_admin = db.Column(db.Boolean, default=False)
    
    # SELLER INFO
    phone = db.Column(db.String(20), nullable=True)
    pickup_address = db.Column(db.String(200), nullable=True)
    
    # PAYOUT INFO
    payout_method = db.Column(db.String(20), nullable=True)
    payout_handle = db.Column(db.String(100), nullable=True)
    
    # STATUS
    is_seller = db.Column(db.Boolean, default=False) 
    has_paid = db.Column(db.Boolean, default=False)
    
    # MARKETING
    referral_source = db.Column(db.String(50), default='direct')
    unsubscribed = db.Column(db.Boolean, default=False)
    unsubscribe_token = db.Column(db.String(64), unique=True, nullable=True)
    
    date_joined = db.Column(db.DateTime, default=datetime.utcnow)
    items = db.relationship('InventoryItem', backref='seller', lazy=True)

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
    quality = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), default='pending_valuation')
    date_added = db.Column(db.DateTime, default=datetime.utcnow)
    
    # COLLECTION METHOD: 'online' (default) or 'in_person'
    collection_method = db.Column(db.String(20), default='online')
    
    # PAYOUT TRACKING
    sold_at = db.Column(db.DateTime, nullable=True)  # When item was marked sold
    payout_sent = db.Column(db.Boolean, default=False)  # Whether seller has been paid
    
    category_id = db.Column(db.Integer, db.ForeignKey('inventory_category.id'), nullable=False)
    seller_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    
    photo_url = db.Column(db.String(200), nullable=True)
    gallery_photos = db.relationship('ItemPhoto', backref='item', lazy=True)

class ItemPhoto(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey('inventory_item.id'), nullable=False)
    photo_url = db.Column(db.String(200), nullable=False)

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