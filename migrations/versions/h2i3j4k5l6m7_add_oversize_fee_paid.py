"""Add oversize_fee_paid to InventoryItem

Revision ID: h2i3j4k5l6m7
Revises: g1h2i3j4k5l6
Create Date: 2026-02-22

"""
from alembic import op
import sqlalchemy as sa


revision = 'h2i3j4k5l6m7'
down_revision = 'g1h2i3j4k5l6'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('inventory_item', schema=None) as batch_op:
        batch_op.add_column(sa.Column('oversize_fee_paid', sa.Boolean(), nullable=True))


def downgrade():
    with op.batch_alter_table('inventory_item', schema=None) as batch_op:
        batch_op.drop_column('oversize_fee_paid')
