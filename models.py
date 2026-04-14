from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy(session_options={'expire_on_commit': False})

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
    pickup_note = db.Column(db.String(500), nullable=True)  # Optional directions / mover notes
    pickup_lat = db.Column(db.Float, nullable=True)  # Latitude for map preview (off_campus)
    pickup_lng = db.Column(db.Float, nullable=True)  # Longitude for map preview (off_campus)
    pickup_access_type = db.Column(db.String(20), nullable=True)  # 'elevator' | 'stairs_only' | 'ground_floor'
    pickup_floor = db.Column(db.Integer, nullable=True)  # Floor number (1–30)
    pickup_partner_building = db.Column(db.String(100), nullable=True)  # partner apartment building name

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
    
    # PICKUP SCHEDULING
    pickup_week = db.Column(db.String(10), nullable=True)  # 'week1' | 'week2' | None — seller's stated preference
    pickup_time_preference = db.Column(db.String(20), nullable=True)  # 'morning' | 'afternoon' | 'evening'
    moveout_date = db.Column(db.Date, nullable=True)  # Seller's exact move-out date (optional)

    # WORKER / CREW
    is_worker = db.Column(db.Boolean, default=False)
    worker_status = db.Column(db.String(20), nullable=True)  # None | 'pending' | 'approved' | 'rejected'
    worker_role = db.Column(db.String(20), nullable=True)    # None | 'driver' | 'organizer' | 'both'

    # REFERRAL PROGRAM
    referral_code = db.Column(db.String(8), unique=True, nullable=True)
    # 8-char uppercase alphanumeric code (no 0,O,I,1). Generated at account creation.
    referred_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    # FK to the User who gave them their referral code.
    payout_rate = db.Column(db.Integer, default=20, nullable=False)
    # Stored integer percentage (20, 30, 40 ... 100). Updated when a referral is confirmed.

    # PAYOUT BOOST ($15 one-time purchase for +30%)
    has_paid_boost = db.Column(db.Boolean, default=False, nullable=False, server_default='0')
    # True once the seller has completed the $15 payout boost purchase this season.
    # Separate from has_paid (legacy Pro tier flag). Reset annually by the fall cleanup script.

    date_joined = db.Column(db.DateTime, default=datetime.utcnow)
    items = db.relationship('InventoryItem', backref='seller', lazy=True)

    @property
    def has_pickup_location(self):
        """True if user has a complete pickup location set (including access fields)."""
        # Access fields required for all location types
        if not self.pickup_access_type or self.pickup_floor is None:
            return False
        if self.pickup_location_type == 'on_campus':
            return bool(self.pickup_dorm and self.pickup_room)
        if self.pickup_location_type == 'off_campus_complex':
            return bool(self.pickup_dorm and self.pickup_room)
        if self.pickup_location_type in ('off_campus_other', 'off_campus'):
            return bool(self.pickup_address)
        return False

    @property
    def pickup_display(self):
        """Formatted display string for pickup location (used by admin panel and mover shift view)."""
        _access_labels = {
            'elevator': 'Elevator access',
            'stairs_only': 'Stairs only',
            'ground_floor': 'Ground floor',
        }
        access_str = _access_labels.get(self.pickup_access_type or '', '')
        floor_str = f"Floor {self.pickup_floor}" if self.pickup_floor is not None else ''

        if self.pickup_location_type == 'on_campus' and self.pickup_dorm:
            base = f"{self.pickup_dorm}, Room {self.pickup_room}" if self.pickup_room else self.pickup_dorm
        elif self.pickup_location_type == 'off_campus_complex' and self.pickup_dorm:
            unit = f" Unit {self.pickup_room}" if self.pickup_room else ''
            base = f"{self.pickup_dorm}{unit}"
        elif self.pickup_location_type in ('off_campus_other', 'off_campus') and self.pickup_address:
            base = self.pickup_address
        elif self.pickup_address:
            base = self.pickup_address
        else:
            return ''

        parts = [base]
        if floor_str:
            parts.append(floor_str)
        if access_str:
            parts.append(access_str)
        return ' · '.join(parts)

    def set_password(self, password):
        from werkzeug.security import generate_password_hash
        self.password_hash = generate_password_hash(password)

    @property
    def is_guest_account(self):
        """True if user has neither password nor OAuth - needs to create password or link OAuth."""
        return not self.password_hash and not self.oauth_provider

class InventoryCategory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    image_url = db.Column(db.String(200), nullable=True)
    icon = db.Column(db.String(64), nullable=True)  # e.g. 'fa-couch'
    count_in_stock = db.Column(db.Integer, default=0)
    default_unit_size = db.Column(db.Float, default=1.0, nullable=True)
    parent_id = db.Column(db.Integer, db.ForeignKey('inventory_category.id'), nullable=True)

    parent = db.relationship('InventoryCategory', remote_side='InventoryCategory.id', backref='subcategories')
    items = db.relationship('InventoryItem', backref='category', lazy=True, foreign_keys='InventoryItem.category_id')

class InventoryItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    description = db.Column(db.String(200), nullable=False)
    long_description = db.Column(db.Text, nullable=True)
    price = db.Column(db.Float, nullable=True)
    suggested_price = db.Column(db.Float, nullable=True)
    quality = db.Column(db.Integer, nullable=False, default=1)
    status = db.Column(db.String(20), default='pending_valuation')
    date_added = db.Column(db.DateTime, default=datetime.utcnow)
    
    # COLLECTION METHOD: 'online' (default) or 'in_person'
    collection_method = db.Column(db.String(20), default='online')
    
    # LOGISTICS (set when seller confirms after approval)
    pickup_week = db.Column(db.String(20), nullable=True)   # 'week1' (Apr 27-May 3) or 'week2' (May 4-May 10)
    dropoff_pod = db.Column(db.String(40), nullable=True)  # 'greek_row' or 'apartment'
    
    # PAYOUT TRACKING
    sold_at = db.Column(db.DateTime, nullable=True)  # When item was marked sold
    payout_sent = db.Column(db.Boolean, default=False)  # Whether seller has been paid
    payout_sent_at = db.Column(db.DateTime, nullable=True)  # When payout was marked sent (set by admin via /admin/payouts)
    
    # LIFECYCLE: Operational milestones (do not affect count_in_stock or status)
    picked_up_at = db.Column(db.DateTime, nullable=True)  # When item was collected from seller or placed in POD
    arrived_at_store_at = db.Column(db.DateTime, nullable=True)  # When item physically arrived at store
    
    category_id = db.Column(db.Integer, db.ForeignKey('inventory_category.id'), nullable=True)
    subcategory_id = db.Column(db.Integer, db.ForeignKey('inventory_category.id'), nullable=True)
    seller_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

    subcategory = db.relationship('InventoryCategory', foreign_keys=[subcategory_id], backref='subcategory_items')
    
    photo_url = db.Column(db.String(200), nullable=True)
    video_url = db.Column(db.String(200), nullable=True)  # Demo video filename (electronics required, others optional)
    gallery_photos = db.relationship('ItemPhoto', backref='item', lazy=True, cascade='all, delete-orphan')

    # Price transparency: True when seller has acknowledged that we changed their suggested price
    price_changed_acknowledged = db.Column(db.Boolean, default=False)
    # When we set or change the price (approval or later edit) - badge shows until acknowledged
    price_updated_at = db.Column(db.DateTime, nullable=True)

    # SPEC #4 — ORGANIZER INTAKE: where the item actually ended up at the storage unit
    storage_location_id = db.Column(db.Integer, db.ForeignKey('storage_location.id'), nullable=True)
    storage_row         = db.Column(db.String(50), nullable=True)   # e.g. "Row 1", "Row B"
    storage_note        = db.Column(db.Text, nullable=True)         # e.g. "behind the couch stack"
    unit_size = db.Column(db.Float, nullable=True)  # per-item override; NULL = use category default

class ItemPhoto(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey('inventory_item.id'), nullable=False)
    photo_url = db.Column(db.String(200), nullable=False)


class ItemReservation(db.Model):
    """Non-binding reservation with expiry. No payment required."""
    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey('inventory_item.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    cancelled_at = db.Column(db.DateTime, nullable=True)
    expiry_email_sent = db.Column(db.Boolean, default=False)

    user = db.relationship('User', backref='reservations', lazy=True)

class UploadSession(db.Model):
    """Temporary session for QR code mobile-to-desktop photo uploads. user_id is None for guest sessions."""
    id = db.Column(db.Integer, primary_key=True)
    session_token = db.Column(db.String(64), unique=True, nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
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


class SellerAlert(db.Model):
    """Generic alert/notification for sellers. Designed for reuse across features
    (needs_info, pickup_reminder, custom admin messages, etc.)."""
    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey('inventory_item.id'), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    alert_type = db.Column(db.String(30), nullable=False, default='needs_info')  # 'needs_info' | 'pickup_reminder' | 'custom'
    reasons = db.Column(db.Text, nullable=True)  # JSON-encoded list of preset reason strings
    custom_note = db.Column(db.Text, nullable=True)
    resolved = db.Column(db.Boolean, default=False)
    resolved_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    item = db.relationship('InventoryItem', backref=db.backref('alerts', lazy='dynamic'))
    user = db.relationship('User', foreign_keys=[user_id], backref=db.backref('seller_alerts', lazy='dynamic'))
    created_by = db.relationship('User', foreign_keys=[created_by_id])


class DigestLog(db.Model):
    """Tracks when approval digest emails were sent."""
    id = db.Column(db.Integer, primary_key=True)
    sent_at = db.Column(db.DateTime, default=datetime.utcnow)
    item_count = db.Column(db.Integer, nullable=False)
    recipient_count = db.Column(db.Integer, nullable=False)


class ItemAIResult(db.Model):
    """Stores the AI lookup result for each item. One result per item."""
    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey('inventory_item.id'), unique=True, nullable=False)
    status = db.Column(db.String(20), nullable=False, default='pending')  # 'pending' | 'found' | 'unknown' | 'error'
    product_name = db.Column(db.String(500), nullable=True)
    retail_price = db.Column(db.Numeric(10, 2), nullable=True)
    retail_price_source = db.Column(db.String(500), nullable=True)
    suggested_price = db.Column(db.Numeric(10, 2), nullable=True)
    pricing_rationale = db.Column(db.Text, nullable=True)
    ai_description = db.Column(db.Text, nullable=True)
    raw_response = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    item = db.relationship('InventoryItem', backref=db.backref('ai_result', uselist=False))


class WorkerApplication(db.Model):
    """One application per user. Stores role preference, year, and optional blurb."""
    id          = db.Column(db.Integer, primary_key=True)
    user_id     = db.Column(db.Integer, db.ForeignKey('user.id'), unique=True)
    unc_year    = db.Column(db.String(20))
    role_pref   = db.Column(db.String(20))       # driver | organizer | both
    why_blurb   = db.Column(db.Text, nullable=True)
    applied_at  = db.Column(db.DateTime, default=datetime.utcnow)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    reviewed_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

    user     = db.relationship('User', foreign_keys=[user_id], backref=db.backref('worker_application', uselist=False))
    reviewer = db.relationship('User', foreign_keys=[reviewed_by])


class WorkerAvailability(db.Model):
    """
    One record per worker per week.
    week_start=NULL for the initial application submission.
    Weekly updates upsert by (user_id, week_start).
    True = available, False = blacked out.
    """
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('user.id'))
    week_start = db.Column(db.Date, nullable=True)  # NULL = initial | Monday date = weekly update

    mon_am = db.Column(db.Boolean, default=True)
    mon_pm = db.Column(db.Boolean, default=True)
    tue_am = db.Column(db.Boolean, default=True)
    tue_pm = db.Column(db.Boolean, default=True)
    wed_am = db.Column(db.Boolean, default=True)
    wed_pm = db.Column(db.Boolean, default=True)
    thu_am = db.Column(db.Boolean, default=True)
    thu_pm = db.Column(db.Boolean, default=True)
    fri_am = db.Column(db.Boolean, default=True)
    fri_pm = db.Column(db.Boolean, default=True)
    sat_am = db.Column(db.Boolean, default=True)
    sat_pm = db.Column(db.Boolean, default=True)
    sun_am = db.Column(db.Boolean, default=True)
    sun_pm = db.Column(db.Boolean, default=True)

    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)
    user         = db.relationship('User', backref='availabilities')

    __table_args__ = (
        db.UniqueConstraint('user_id', 'week_start', name='uq_worker_avail_user_week'),
    )


# =========================================================
# SPEC #2 — SHIFT SCHEDULING
# =========================================================

class ShiftWeek(db.Model):
    """One record per work week. Holds all shifts for that week."""
    id           = db.Column(db.Integer, primary_key=True)
    week_start   = db.Column(db.Date, unique=True, nullable=False)  # Monday of the work week
    status       = db.Column(db.String(20), nullable=False, default='draft')  # 'draft' | 'published'
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)
    created_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

    shifts       = db.relationship('Shift', backref='week', lazy=True, order_by='Shift.id')
    created_by   = db.relationship('User', foreign_keys=[created_by_id])


class Shift(db.Model):
    """One AM or PM block on a specific day within a ShiftWeek."""
    id           = db.Column(db.Integer, primary_key=True)
    week_id      = db.Column(db.Integer, db.ForeignKey('shift_week.id'), nullable=False)
    day_of_week  = db.Column(db.String(3), nullable=False)  # 'mon'|'tue'|'wed'|'thu'|'fri'|'sat'|'sun'
    slot         = db.Column(db.String(2), nullable=False)   # 'am'|'pm'
    trucks       = db.Column(db.Integer, default=2)
    is_active    = db.Column(db.Boolean, default=True)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)
    # JSON: {"1": storage_location_id, "2": storage_location_id} — planned unit per truck
    truck_unit_plan = db.Column(db.Text, nullable=True)
    sellers_notified = db.Column(db.Boolean, default=False, nullable=False, server_default='0')

    assignments  = db.relationship('ShiftAssignment', backref='shift', lazy=True, cascade='all, delete-orphan')

    _DAY_ORDER = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
    _DAY_LABELS = {'mon': 'Monday', 'tue': 'Tuesday', 'wed': 'Wednesday',
                   'thu': 'Thursday', 'fri': 'Friday', 'sat': 'Saturday', 'sun': 'Sunday'}

    @property
    def label(self):
        return f"{self._DAY_LABELS.get(self.day_of_week, self.day_of_week)} {'AM' if self.slot == 'am' else 'PM'}"

    @property
    def sort_key(self):
        return (self._DAY_ORDER.index(self.day_of_week), 0 if self.slot == 'am' else 1)

    @property
    def drivers_needed(self):
        return self.trucks * int(AppSetting.get('drivers_per_truck', '2'))

    @property
    def organizers_needed(self):
        # 2 organizers per pair of trucks (always 2 at the store; stagger model)
        # 1-2 trucks → 2, 3-4 trucks → 4
        import math
        return math.ceil(self.trucks / 2) * 2

    @property
    def driver_assignments(self):
        return [a for a in self.assignments if a.role_on_shift == 'driver']

    @property
    def organizer_assignments(self):
        return [a for a in self.assignments if a.role_on_shift == 'organizer']

    @property
    def is_fully_staffed(self):
        return (len(self.driver_assignments) >= self.drivers_needed and
                len(self.organizer_assignments) >= self.organizers_needed)

    @property
    def status_label(self):
        if not self.assignments:
            return 'Unassigned'
        if self.is_fully_staffed:
            return 'Fully Staffed'
        return 'Understaffed'


class ShiftAssignment(db.Model):
    """One worker assigned to one shift in a specific role."""
    id             = db.Column(db.Integer, primary_key=True)
    shift_id       = db.Column(db.Integer, db.ForeignKey('shift.id'), nullable=False)
    worker_id      = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    role_on_shift  = db.Column(db.String(20), nullable=False)  # 'driver' | 'organizer'
    truck_number   = db.Column(db.Integer, nullable=True)  # NULL for organizers; 1-N for movers
    assigned_at    = db.Column(db.DateTime, default=datetime.utcnow)
    assigned_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)  # NULL = optimizer
    completed_at   = db.Column(db.DateTime, nullable=True)  # set when this worker marks their role done

    worker      = db.relationship('User', foreign_keys=[worker_id], backref='shift_assignments')
    assigned_by = db.relationship('User', foreign_keys=[assigned_by_id])


# =========================================================
# SPEC #3 — DRIVER SHIFT VIEW / OPS
# =========================================================

class ShiftPickup(db.Model):
    """One seller stop per shift. Populated by admin via the ops page."""
    id            = db.Column(db.Integer, primary_key=True)
    shift_id      = db.Column(db.Integer, db.ForeignKey('shift.id'), nullable=False)
    seller_id     = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    truck_number  = db.Column(db.Integer, nullable=False)
    stop_order    = db.Column(db.Integer, nullable=True)   # populated by spec #6
    status        = db.Column(db.String(20), nullable=False, default='pending')  # pending|completed|issue
    notes         = db.Column(db.Text, nullable=True)
    completed_at  = db.Column(db.DateTime, nullable=True)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)
    created_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

    # SPEC #4 — planned destination set by admin pre-shift; never overwritten by intake flow
    storage_location_id = db.Column(db.Integer, db.ForeignKey('storage_location.id'), nullable=True)
    notified_at     = db.Column(db.DateTime, nullable=True)   # per-seller notification timestamp
    capacity_warning = db.Column(db.Boolean, default=False, nullable=False, server_default='0')

    shift      = db.relationship('Shift', backref='pickups')
    seller     = db.relationship('User', foreign_keys=[seller_id], backref='shift_pickups')
    created_by = db.relationship('User', foreign_keys=[created_by_id])

    __table_args__ = (
        db.UniqueConstraint('shift_id', 'seller_id', name='uq_shift_pickup_shift_seller'),
    )


class ShiftRun(db.Model):
    """Shift-level execution state. Created when a mover taps Start Shift."""
    id             = db.Column(db.Integer, primary_key=True)
    shift_id       = db.Column(db.Integer, db.ForeignKey('shift.id'), unique=True, nullable=False)
    started_at     = db.Column(db.DateTime, default=datetime.utcnow)
    started_by_id  = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    ended_at       = db.Column(db.DateTime, nullable=True)
    status         = db.Column(db.String(20), nullable=False, default='in_progress')  # in_progress|completed

    shift      = db.relationship('Shift', backref=db.backref('run', uselist=False))
    started_by = db.relationship('User', foreign_keys=[started_by_id])


class WorkerPreference(db.Model):
    """Partner preferences between movers. Two row types: preferred and avoided."""
    id              = db.Column(db.Integer, primary_key=True)
    user_id         = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    target_user_id  = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    preference_type = db.Column(db.String(20), nullable=False)  # 'preferred' | 'avoided'
    created_at      = db.Column(db.DateTime, default=datetime.utcnow)

    user        = db.relationship('User', foreign_keys=[user_id], backref='worker_preferences')
    target_user = db.relationship('User', foreign_keys=[target_user_id])

    __table_args__ = (
        db.UniqueConstraint('user_id', 'target_user_id', 'preference_type', name='uq_worker_pref'),
    )


# =========================================================
# SPEC #4 — ORGANIZER INTAKE
# =========================================================

class StorageLocation(db.Model):
    """A physical storage unit Campus Swap controls."""
    id              = db.Column(db.Integer, primary_key=True)
    name            = db.Column(db.String(100), unique=True, nullable=False)  # e.g. "Unit A"
    address         = db.Column(db.String(200), nullable=True)
    location_note   = db.Column(db.Text, nullable=True)    # gate code, landmark, etc.
    capacity_note   = db.Column(db.Text, nullable=True)    # e.g. "fits ~40 large items"
    is_active       = db.Column(db.Boolean, default=True)
    is_full         = db.Column(db.Boolean, default=False)
    created_at      = db.Column(db.DateTime, default=datetime.utcnow)
    created_by_id   = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    lat = db.Column(db.Float, nullable=True)
    lng = db.Column(db.Float, nullable=True)

    created_by      = db.relationship('User', foreign_keys=[created_by_id])
    items           = db.relationship('InventoryItem', backref='storage_location', lazy='dynamic',
                                      foreign_keys='InventoryItem.storage_location_id')
    shift_pickups   = db.relationship('ShiftPickup', backref='planned_storage_location', lazy='dynamic',
                                      foreign_keys='ShiftPickup.storage_location_id')
    intake_records  = db.relationship('IntakeRecord', backref='storage_location', lazy='dynamic',
                                      foreign_keys='IntakeRecord.storage_location_id')


class IntakeRecord(db.Model):
    """Append-only log of each organizer intake action. Never update — always insert."""
    id                  = db.Column(db.Integer, primary_key=True)
    item_id             = db.Column(db.Integer, db.ForeignKey('inventory_item.id'), nullable=False)
    shift_id            = db.Column(db.Integer, db.ForeignKey('shift.id'), nullable=False)
    organizer_id        = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    storage_location_id = db.Column(db.Integer, db.ForeignKey('storage_location.id'), nullable=True)
    storage_row         = db.Column(db.String(50), nullable=True)
    storage_note        = db.Column(db.Text, nullable=True)
    quality_before      = db.Column(db.Integer, nullable=False)  # snapshot of item quality at intake time
    quality_after       = db.Column(db.Integer, nullable=False)  # value organizer recorded
    created_at          = db.Column(db.DateTime, default=datetime.utcnow)

    item      = db.relationship('InventoryItem', backref='intake_records')
    shift     = db.relationship('Shift', backref='intake_records')
    organizer = db.relationship('User', foreign_keys=[organizer_id])


class IntakeFlag(db.Model):
    """Problem flag raised during organizer intake. Resolved by admin."""
    id               = db.Column(db.Integer, primary_key=True)
    item_id          = db.Column(db.Integer, db.ForeignKey('inventory_item.id'), nullable=True)   # null for unknown_item
    shift_id         = db.Column(db.Integer, db.ForeignKey('shift.id'), nullable=False)
    intake_record_id = db.Column(db.Integer, db.ForeignKey('intake_record.id'), nullable=True)    # null for unknown_item
    organizer_id     = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    flag_type        = db.Column(db.String(30), nullable=False)
    # 'missing' | 'damaged' | 'wrong_item' | 'extra_item' | 'unknown_item' | 'other'
    description      = db.Column(db.Text, nullable=False)
    resolved         = db.Column(db.Boolean, default=False)
    resolved_at      = db.Column(db.DateTime, nullable=True)
    resolved_by_id   = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    resolution_note  = db.Column(db.Text, nullable=True)
    created_at       = db.Column(db.DateTime, default=datetime.utcnow)

    item          = db.relationship('InventoryItem', backref='intake_flags', foreign_keys=[item_id])
    shift         = db.relationship('Shift', backref='intake_flags')
    intake_record = db.relationship('IntakeRecord', backref='flags')
    organizer     = db.relationship('User', foreign_keys=[organizer_id])
    resolved_by   = db.relationship('User', foreign_keys=[resolved_by_id])


# =========================================================
# REFERRAL PROGRAM
# =========================================================

class ShopNotifySignup(db.Model):
    """Email capture for pre-launch shop drop teaser. Duplicates allowed — no unique constraint."""
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    ip_address = db.Column(db.String(45), nullable=True)  # for spam review; never displayed


class BuyerOrder(db.Model):
    """Delivery details for each completed item purchase. One record per sold item."""
    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey('inventory_item.id'), unique=True, nullable=False)
    buyer_email = db.Column(db.String(120), nullable=False)
    delivery_address = db.Column(db.String(300), nullable=False)
    delivery_lat = db.Column(db.Float, nullable=True)
    delivery_lng = db.Column(db.Float, nullable=True)
    stripe_session_id = db.Column(db.String(120), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    item = db.relationship('InventoryItem', backref=db.backref('buyer_order', uselist=False))


class Referral(db.Model):
    """One record per (referrer, referred) pair. confirmed=True when referred seller's item arrives."""
    id          = db.Column(db.Integer, primary_key=True)
    referrer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    referred_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, unique=True)
    # unique=True on referred_id: a user can only be referred by one person
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)
    confirmed   = db.Column(db.Boolean, default=False)
    confirmed_at = db.Column(db.DateTime, nullable=True)

    referrer = db.relationship('User', foreign_keys=[referrer_id], backref='referrals_given')
    referred = db.relationship('User', foreign_keys=[referred_id], backref='referral_received', uselist=False)