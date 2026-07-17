"""category baseline_price for AI autofill

Revision ID: 3cfd0298fc46
Revises: 454f7f6bc046
Create Date: 2026-07-17 13:03:28.420842

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3cfd0298fc46'
down_revision = '454f7f6bc046'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('inventory_category', sa.Column('baseline_price', sa.Numeric(precision=10, scale=2), nullable=True))


def downgrade():
    op.drop_column('inventory_category', 'baseline_price')
