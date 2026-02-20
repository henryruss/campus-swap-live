"""Add is_super_admin and item lifecycle fields

Revision ID: g1h2i3j4k5l6
Revises: e8f9g0h1i2j3
Create Date: 2026-02-20

"""
from alembic import op
import sqlalchemy as sa


revision = 'g1h2i3j4k5l6'
down_revision = 'e8f9g0h1i2j3'
branch_labels = None
depends_on = None


def upgrade():
    # User: add is_super_admin (helper vs super admin)
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_super_admin', sa.Boolean(), nullable=True))
    
    # Backfill: existing admins become super admins
    op.execute("UPDATE \"user\" SET is_super_admin = true WHERE is_admin = true")
    op.execute("UPDATE \"user\" SET is_super_admin = false WHERE is_super_admin IS NULL")
    
    # InventoryItem: lifecycle tracking fields
    with op.batch_alter_table('inventory_item', schema=None) as batch_op:
        batch_op.add_column(sa.Column('picked_up_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('arrived_at_store_at', sa.DateTime(), nullable=True))


def downgrade():
    with op.batch_alter_table('inventory_item', schema=None) as batch_op:
        batch_op.drop_column('arrived_at_store_at')
        batch_op.drop_column('picked_up_at')
    
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_column('is_super_admin')
