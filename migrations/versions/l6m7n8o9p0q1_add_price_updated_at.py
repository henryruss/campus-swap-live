"""Add price_updated_at to InventoryItem

Revision ID: l6m7n8o9p0q1
Revises: k5l6m7n8o9p0
Create Date: 2026-02-23

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision = 'l6m7n8o9p0q1'
down_revision = 'k5l6m7n8o9p0'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('inventory_item', schema=None) as batch_op:
        batch_op.add_column(sa.Column('price_updated_at', sa.DateTime(), nullable=True))

    # Backfill: items where we changed the price from seller's suggestion (price != suggested_price)
    conn = op.get_bind()
    conn.execute(text("""
        UPDATE inventory_item
        SET price_updated_at = CURRENT_TIMESTAMP
        WHERE price IS NOT NULL AND suggested_price IS NOT NULL
        AND ABS(price - suggested_price) > 0.01
        AND price_updated_at IS NULL
    """))


def downgrade():
    with op.batch_alter_table('inventory_item', schema=None) as batch_op:
        batch_op.drop_column('price_updated_at')
