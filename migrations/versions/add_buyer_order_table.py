"""add buyer_order table

Revision ID: add_buyer_order_table
Revises: admin_redesign_shift_last_notified
Create Date: 2026-04-16
"""
from alembic import op
import sqlalchemy as sa

revision = 'add_buyer_order_table'
down_revision = 'shift_last_notified_at'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'buyer_order',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('item_id', sa.Integer(), nullable=False),
        sa.Column('buyer_email', sa.String(length=120), nullable=True),
        sa.Column('delivery_address', sa.Text(), nullable=True),
        sa.Column('delivery_lat', sa.Float(), nullable=True),
        sa.Column('delivery_lng', sa.Float(), nullable=True),
        sa.Column('stripe_session_id', sa.String(length=120), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['item_id'], ['inventory_item.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('item_id'),
    )


def downgrade():
    op.drop_table('buyer_order')
