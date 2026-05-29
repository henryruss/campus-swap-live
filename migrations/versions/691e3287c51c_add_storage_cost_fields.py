"""add_storage_cost_fields

Adds size_sqft and monthly_cost to storage_location for unit efficiency /
cost tracking (warehouse floor addendum). add_warehouse_floor_fields
(9833fccaa78e) was already applied, so this is a separate migration.

Revision ID: 691e3287c51c
Revises: 9833fccaa78e
Create Date: 2026-05-28 19:40:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '691e3287c51c'
down_revision = '9833fccaa78e'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('storage_location', sa.Column('size_sqft', sa.Float(), nullable=True))
    op.add_column('storage_location', sa.Column('monthly_cost', sa.Numeric(8, 2), nullable=True))


def downgrade():
    op.drop_column('storage_location', 'monthly_cost')
    op.drop_column('storage_location', 'size_sqft')
