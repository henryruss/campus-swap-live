"""add_sms_and_no_show_fields

Revision ID: add_sms_and_no_show_fields
Revises: add_seller_rescheduling
Branch_labels: None
Depends_on: None

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text

revision = 'add_sms_and_no_show_fields'
down_revision = 'add_seller_rescheduling'
branch_labels = None
depends_on = None


def _table_exists(table_name):
    """Return True if the table exists in the database."""
    conn = op.get_bind()
    inspector = inspect(conn)
    return table_name in inspector.get_table_names()


def _column_exists(table_name, column_name):
    """Return True if the column already exists in the table. Returns False if table absent."""
    conn = op.get_bind()
    inspector = inspect(conn)
    try:
        cols = [c['name'] for c in inspector.get_columns(table_name)]
    except Exception:
        return False
    return column_name in cols


def upgrade():
    conn = op.get_bind()

    # 1. Add User.sms_opted_out
    if _table_exists('user') and not _column_exists('user', 'sms_opted_out'):
        with op.batch_alter_table('user', schema=None) as batch_op:
            batch_op.add_column(sa.Column(
                'sms_opted_out', sa.Boolean(), nullable=False, server_default='0'
            ))

    # 2. Add ShiftPickup.issue_type
    if _table_exists('shift_pickup') and not _column_exists('shift_pickup', 'issue_type'):
        with op.batch_alter_table('shift_pickup', schema=None) as batch_op:
            batch_op.add_column(sa.Column('issue_type', sa.String(length=20), nullable=True))

    # 3. Add ShiftPickup.no_show_email_sent_at
    if _table_exists('shift_pickup') and not _column_exists('shift_pickup', 'no_show_email_sent_at'):
        with op.batch_alter_table('shift_pickup', schema=None) as batch_op:
            batch_op.add_column(sa.Column('no_show_email_sent_at', sa.DateTime(), nullable=True))

    # 4. Add RescheduleToken.revoked_at
    if _table_exists('reschedule_token') and not _column_exists('reschedule_token', 'revoked_at'):
        with op.batch_alter_table('reschedule_token', schema=None) as batch_op:
            batch_op.add_column(sa.Column('revoked_at', sa.DateTime(), nullable=True))

    # 5. Seed AppSettings (skip if key already exists or table absent)
    if _table_exists('app_setting'):
        settings = [
            ('sms_enabled', 'true'),
            ('sms_reminder_hour_eastern', '9'),
            ('no_show_email_enabled', 'true'),
            ('no_show_email_hour_eastern', '18'),
        ]
        for key, value in settings:
            existing = conn.execute(
                text("SELECT id FROM app_setting WHERE key = :key"), {'key': key}
            ).fetchone()
            if not existing:
                conn.execute(
                    text("INSERT INTO app_setting (key, value) VALUES (:key, :value)"),
                    {'key': key, 'value': value}
                )


def downgrade():
    if _column_exists('reschedule_token', 'revoked_at'):
        with op.batch_alter_table('reschedule_token', schema=None) as batch_op:
            batch_op.drop_column('revoked_at')

    if _column_exists('shift_pickup', 'no_show_email_sent_at'):
        with op.batch_alter_table('shift_pickup', schema=None) as batch_op:
            batch_op.drop_column('no_show_email_sent_at')

    if _column_exists('shift_pickup', 'issue_type'):
        with op.batch_alter_table('shift_pickup', schema=None) as batch_op:
            batch_op.drop_column('issue_type')

    if _column_exists('user', 'sms_opted_out'):
        with op.batch_alter_table('user', schema=None) as batch_op:
            batch_op.drop_column('sms_opted_out')
