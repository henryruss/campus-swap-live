"""add_ai_retail_price

Revision ID: af636a52a985
Revises: da3bed86df50
Create Date: 2026-05-28 16:34:53.735922

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'af636a52a985'
down_revision = 'da3bed86df50'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('inventory_item', schema=None) as batch_op:
        batch_op.add_column(sa.Column('ai_retail_price', sa.Numeric(precision=10, scale=2), nullable=True))


def downgrade():
    with op.batch_alter_table('inventory_item', schema=None) as batch_op:
        batch_op.drop_column('ai_retail_price')
