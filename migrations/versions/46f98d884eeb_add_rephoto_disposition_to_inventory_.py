"""add rephoto_disposition to inventory_item

Revision ID: 46f98d884eeb
Revises: 3cfd0298fc46
Create Date: 2026-07-21 21:02:34.791552

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '46f98d884eeb'
down_revision = '3cfd0298fc46'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('inventory_item', sa.Column('rephoto_disposition', sa.String(length=20), nullable=True))


def downgrade():
    op.drop_column('inventory_item', 'rephoto_disposition')
