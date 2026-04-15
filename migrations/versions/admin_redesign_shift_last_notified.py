"""shift_last_notified_at

Revision ID: shift_last_notified_at
Revises: add_sms_and_no_show_fields
Branch_labels: None
Depends_on: None

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = 'shift_last_notified_at'
down_revision = 'add_sms_and_no_show_fields'
branch_labels = None
depends_on = None


def _table_exists(table_name):
    conn = op.get_bind()
    inspector = inspect(conn)
    return table_name in inspector.get_table_names()


def _column_exists(table_name, column_name):
    conn = op.get_bind()
    inspector = inspect(conn)
    try:
        cols = [c['name'] for c in inspector.get_columns(table_name)]
    except Exception:
        return False
    return column_name in cols


def upgrade():
    if _table_exists('shift') and not _column_exists('shift', 'last_notified_at'):
        with op.batch_alter_table('shift', schema=None) as batch_op:
            batch_op.add_column(sa.Column('last_notified_at', sa.DateTime(), nullable=True))


def downgrade():
    if _table_exists('shift') and _column_exists('shift', 'last_notified_at'):
        with op.batch_alter_table('shift', schema=None) as batch_op:
            batch_op.drop_column('last_notified_at')
