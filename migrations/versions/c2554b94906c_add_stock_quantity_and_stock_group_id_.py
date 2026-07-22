"""add stock_quantity and stock_group_id to inventory_item

Revision ID: c2554b94906c
Revises: 46f98d884eeb
Create Date: 2026-07-21 21:53:44.220676

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c2554b94906c'
down_revision = '46f98d884eeb'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('inventory_item', sa.Column('stock_quantity', sa.Integer(), server_default='1', nullable=False))
    op.add_column('inventory_item', sa.Column('stock_group_id', sa.String(length=36), nullable=True))
    op.create_index('ix_inventory_item_stock_group_id', 'inventory_item', ['stock_group_id'], unique=False)


def downgrade():
    op.drop_index('ix_inventory_item_stock_group_id', table_name='inventory_item')
    op.drop_column('inventory_item', 'stock_group_id')
    op.drop_column('inventory_item', 'stock_quantity')
