"""add_seller_rescheduling

Revision ID: add_seller_rescheduling
Revises: add_route_planning_fields
Branch_labels: None
Depends_on: None

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text

revision = 'add_seller_rescheduling'
down_revision = 'add_route_planning_fields'
branch_labels = None
depends_on = None


def _column_exists(table_name, column_name):
    """Return True if the column already exists in the table."""
    conn = op.get_bind()
    inspector = inspect(conn)
    cols = [c['name'] for c in inspector.get_columns(table_name)]
    return column_name in cols


def _table_exists(table_name):
    """Return True if the table already exists."""
    conn = op.get_bind()
    inspector = inspect(conn)
    return table_name in inspector.get_table_names()


def upgrade():
    conn = op.get_bind()

    # 1. Create reschedule_token table
    if not _table_exists('reschedule_token'):
        op.create_table(
            'reschedule_token',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('token', sa.String(length=64), nullable=False),
            sa.Column('pickup_id', sa.Integer(), sa.ForeignKey('shift_pickup.id'), nullable=False),
            sa.Column('seller_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('used_at', sa.DateTime(), nullable=True),
            sa.Column('expires_at', sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('token', name='uq_reschedule_token_token'),
        )
        op.create_index('ix_reschedule_token_token', 'reschedule_token', ['token'])

    # 2. Add shift_pickup.rescheduled_from_shift_id
    if not _column_exists('shift_pickup', 'rescheduled_from_shift_id'):
        with op.batch_alter_table('shift_pickup', schema=None) as batch_op:
            batch_op.add_column(sa.Column('rescheduled_from_shift_id', sa.Integer(), nullable=True))

    # 3. Add shift_pickup.rescheduled_at
    if not _column_exists('shift_pickup', 'rescheduled_at'):
        with op.batch_alter_table('shift_pickup', schema=None) as batch_op:
            batch_op.add_column(sa.Column('rescheduled_at', sa.DateTime(), nullable=True))

    # 4. Add shift.overflow_truck_number
    if not _column_exists('shift', 'overflow_truck_number'):
        with op.batch_alter_table('shift', schema=None) as batch_op:
            batch_op.add_column(sa.Column('overflow_truck_number', sa.Integer(), nullable=True))

    # 5. Add shift.reschedule_locked
    if not _column_exists('shift', 'reschedule_locked'):
        with op.batch_alter_table('shift', schema=None) as batch_op:
            batch_op.add_column(sa.Column('reschedule_locked', sa.Boolean(), nullable=False, server_default='0'))

    # 6. Seed AppSettings (skip if key already exists)
    settings = [
        ('reschedule_token_ttl_days', '7'),
        ('reschedule_max_weeks_forward', '0'),
        ('reschedule_urgent_alert_days', '2'),
    ]
    for key, value in settings:
        existing = conn.execute(text("SELECT id FROM app_setting WHERE key = :key"), {'key': key}).fetchone()
        if not existing:
            conn.execute(
                text("INSERT INTO app_setting (key, value) VALUES (:key, :value)"),
                {'key': key, 'value': value}
            )


def downgrade():
    if _column_exists('shift', 'reschedule_locked'):
        with op.batch_alter_table('shift', schema=None) as batch_op:
            batch_op.drop_column('reschedule_locked')

    if _column_exists('shift', 'overflow_truck_number'):
        with op.batch_alter_table('shift', schema=None) as batch_op:
            batch_op.drop_column('overflow_truck_number')

    if _column_exists('shift_pickup', 'rescheduled_at'):
        with op.batch_alter_table('shift_pickup', schema=None) as batch_op:
            batch_op.drop_column('rescheduled_at')

    if _column_exists('shift_pickup', 'rescheduled_from_shift_id'):
        with op.batch_alter_table('shift_pickup', schema=None) as batch_op:
            batch_op.drop_column('rescheduled_from_shift_id')

    if _table_exists('reschedule_token'):
        op.drop_index('ix_reschedule_token_token', table_name='reschedule_token')
        op.drop_table('reschedule_token')
