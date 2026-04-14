"""add_route_planning_fields

Revision ID: add_route_planning_fields
Revises: 773c1d40cca8
Branch_labels: None
Depends_on: None

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text

revision = 'add_route_planning_fields'
down_revision = '773c1d40cca8'
branch_labels = None
depends_on = None


def _column_exists(table_name, column_name):
    """Return True if the column already exists in the table."""
    conn = op.get_bind()
    inspector = inspect(conn)
    cols = [c['name'] for c in inspector.get_columns(table_name)]
    return column_name in cols


def upgrade():
    conn = op.get_bind()

    # InventoryCategory.default_unit_size
    if not _column_exists('inventory_category', 'default_unit_size'):
        with op.batch_alter_table('inventory_category', schema=None) as batch_op:
            batch_op.add_column(sa.Column('default_unit_size', sa.Float(), nullable=True, server_default='1.0'))

    # InventoryItem.unit_size
    if not _column_exists('inventory_item', 'unit_size'):
        with op.batch_alter_table('inventory_item', schema=None) as batch_op:
            batch_op.add_column(sa.Column('unit_size', sa.Float(), nullable=True))

    # Shift.sellers_notified
    if not _column_exists('shift', 'sellers_notified'):
        with op.batch_alter_table('shift', schema=None) as batch_op:
            batch_op.add_column(sa.Column('sellers_notified', sa.Boolean(), nullable=False, server_default='0'))

    # ShiftPickup.notified_at
    if not _column_exists('shift_pickup', 'notified_at'):
        with op.batch_alter_table('shift_pickup', schema=None) as batch_op:
            batch_op.add_column(sa.Column('notified_at', sa.DateTime(), nullable=True))

    # ShiftPickup.capacity_warning
    if not _column_exists('shift_pickup', 'capacity_warning'):
        with op.batch_alter_table('shift_pickup', schema=None) as batch_op:
            batch_op.add_column(sa.Column('capacity_warning', sa.Boolean(), nullable=False, server_default='0'))

    # User.pickup_partner_building
    if not _column_exists('user', 'pickup_partner_building'):
        with op.batch_alter_table('user', schema=None) as batch_op:
            batch_op.add_column(sa.Column('pickup_partner_building', sa.String(length=100), nullable=True))

    # StorageLocation.lat
    if not _column_exists('storage_location', 'lat'):
        with op.batch_alter_table('storage_location', schema=None) as batch_op:
            batch_op.add_column(sa.Column('lat', sa.Float(), nullable=True))

    # StorageLocation.lng
    if not _column_exists('storage_location', 'lng'):
        with op.batch_alter_table('storage_location', schema=None) as batch_op:
            batch_op.add_column(sa.Column('lng', sa.Float(), nullable=True))

    # Seed AppSettings
    settings = [
        ('truck_raw_capacity', '18'),
        ('truck_capacity_buffer_pct', '10'),
        ('route_am_window', '9am\u20131pm'),
        ('route_pm_window', '1pm\u20135pm'),
        ('maps_static_api_key', ''),
    ]
    for key, value in settings:
        existing = conn.execute(text("SELECT id FROM app_setting WHERE key = :key"), {'key': key}).fetchone()
        if not existing:
            conn.execute(text("INSERT INTO app_setting (key, value) VALUES (:key, :value)"), {'key': key, 'value': value})

    # Seed category unit size defaults by name
    category_defaults = {
        'Couch / Sofa': 3.0,
        'Mattress (Full/Queen)': 2.0,
        'Mattress (Twin)': 1.5,
        'Dresser': 2.0,
        'Desk': 1.5,
        'Mini Fridge': 1.0,
        'Microwave': 0.5,
        'Chair': 1.0,
        'Bookshelf': 1.5,
        'TV': 0.5,
        'Lamp': 0.5,
        'Miscellaneous': 0.5,
    }
    for name, size in category_defaults.items():
        conn.execute(
            text("UPDATE inventory_category SET default_unit_size = :size WHERE name = :name AND (default_unit_size IS NULL OR default_unit_size = 1.0)"),
            {'size': size, 'name': name}
        )


def downgrade():
    if _column_exists('storage_location', 'lng'):
        with op.batch_alter_table('storage_location', schema=None) as batch_op:
            batch_op.drop_column('lng')

    if _column_exists('storage_location', 'lat'):
        with op.batch_alter_table('storage_location', schema=None) as batch_op:
            batch_op.drop_column('lat')

    if _column_exists('user', 'pickup_partner_building'):
        with op.batch_alter_table('user', schema=None) as batch_op:
            batch_op.drop_column('pickup_partner_building')

    if _column_exists('shift_pickup', 'capacity_warning'):
        with op.batch_alter_table('shift_pickup', schema=None) as batch_op:
            batch_op.drop_column('capacity_warning')

    if _column_exists('shift_pickup', 'notified_at'):
        with op.batch_alter_table('shift_pickup', schema=None) as batch_op:
            batch_op.drop_column('notified_at')

    if _column_exists('shift', 'sellers_notified'):
        with op.batch_alter_table('shift', schema=None) as batch_op:
            batch_op.drop_column('sellers_notified')

    if _column_exists('inventory_item', 'unit_size'):
        with op.batch_alter_table('inventory_item', schema=None) as batch_op:
            batch_op.drop_column('unit_size')

    if _column_exists('inventory_category', 'default_unit_size'):
        with op.batch_alter_table('inventory_category', schema=None) as batch_op:
            batch_op.drop_column('default_unit_size')
