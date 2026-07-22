"""add mattress_size to inventory_item

Revision ID: 700635cb195e
Revises: c2554b94906c
Create Date: 2026-07-21 22:11:59.233117

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '700635cb195e'
down_revision = 'c2554b94906c'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('inventory_item', sa.Column('mattress_size', sa.String(length=20), nullable=True))


def downgrade():
    op.drop_column('inventory_item', 'mattress_size')
