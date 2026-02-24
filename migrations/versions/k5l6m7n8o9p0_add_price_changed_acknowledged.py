"""Add price_changed_acknowledged to InventoryItem

Revision ID: k5l6m7n8o9p0
Revises: j4k5l6m7n8o9
Create Date: 2026-02-23

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision = 'k5l6m7n8o9p0'
down_revision = 'j4k5l6m7n8o9'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('inventory_item', schema=None) as batch_op:
        batch_op.add_column(sa.Column('price_changed_acknowledged', sa.Boolean(), nullable=True))

    # Set default False for existing rows
    conn = op.get_bind()
    conn.execute(text("UPDATE inventory_item SET price_changed_acknowledged = 0 WHERE price_changed_acknowledged IS NULL"))


def downgrade():
    with op.batch_alter_table('inventory_item', schema=None) as batch_op:
        batch_op.drop_column('price_changed_acknowledged')
