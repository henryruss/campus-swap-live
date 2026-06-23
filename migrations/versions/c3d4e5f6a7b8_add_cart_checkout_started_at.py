"""add cart.checkout_started_at (checkout-time hold)

Revision ID: c3d4e5f6a7b8
Revises: f7e8d9c0b1a2
Create Date: 2026-06-22

"""
from alembic import op
import sqlalchemy as sa

revision = 'c3d4e5f6a7b8'
down_revision = 'f7e8d9c0b1a2'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('cart', sa.Column('checkout_started_at', sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column('cart', 'checkout_started_at')
