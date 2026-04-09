"""add payout_sent_at to inventory_item

Revision ID: d1e2f3g4h5i6
Revises: c177c356b023
Create Date: 2026-04-09 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd1e2f3g4h5i6'
down_revision = 'c177c356b023'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()
    if 'inventory_item' not in existing_tables:
        return  # table doesn't exist locally (stub DB) — skip
    existing_cols = [c['name'] for c in inspector.get_columns('inventory_item')]
    if 'payout_sent_at' not in existing_cols:
        with op.batch_alter_table('inventory_item', schema=None) as batch_op:
            batch_op.add_column(sa.Column('payout_sent_at', sa.DateTime(), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()
    if 'inventory_item' not in existing_tables:
        return
    existing_cols = [c['name'] for c in inspector.get_columns('inventory_item')]
    if 'payout_sent_at' in existing_cols:
        with op.batch_alter_table('inventory_item', schema=None) as batch_op:
            batch_op.drop_column('payout_sent_at')
