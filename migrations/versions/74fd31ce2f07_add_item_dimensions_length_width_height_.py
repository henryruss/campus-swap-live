"""add item dimensions length/width/height inches

Revision ID: 74fd31ce2f07
Revises: 4091b1a0e9c8
Create Date: 2026-07-17 09:51:25.835916

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '74fd31ce2f07'
down_revision = '4091b1a0e9c8'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('inventory_item', sa.Column('length_in', sa.Numeric(precision=5, scale=1), nullable=True))
    op.add_column('inventory_item', sa.Column('width_in', sa.Numeric(precision=5, scale=1), nullable=True))
    op.add_column('inventory_item', sa.Column('height_in', sa.Numeric(precision=5, scale=1), nullable=True))


def downgrade():
    op.drop_column('inventory_item', 'height_in')
    op.drop_column('inventory_item', 'width_in')
    op.drop_column('inventory_item', 'length_in')
