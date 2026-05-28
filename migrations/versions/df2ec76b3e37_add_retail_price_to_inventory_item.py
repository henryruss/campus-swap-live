"""add_retail_price_to_inventory_item

Revision ID: df2ec76b3e37
Revises: af636a52a985
Create Date: 2026-05-28 16:45:48.116979

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'df2ec76b3e37'
down_revision = 'af636a52a985'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('inventory_item', schema=None) as batch_op:
        batch_op.add_column(sa.Column('retail_price', sa.Numeric(precision=10, scale=2), nullable=True))


def downgrade():
    with op.batch_alter_table('inventory_item', schema=None) as batch_op:
        batch_op.drop_column('retail_price')
