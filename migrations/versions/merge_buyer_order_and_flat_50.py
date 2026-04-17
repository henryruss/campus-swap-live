"""Merge buyer_order and flat_50_payout_rate heads

Revision ID: merge_buyer_order_and_flat_50
Revises: add_buyer_order_table, flat_50_payout_rate
Create Date: 2026-04-17 12:45:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'merge_buyer_order_and_flat_50'
down_revision = ('add_buyer_order_table', 'flat_50_payout_rate')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
