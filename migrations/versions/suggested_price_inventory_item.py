"""Add suggested_price to InventoryItem

Revision ID: suggested_price
Revises: add_unsubscribe_fields
Create Date: 2026-02-09 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'suggested_price'
down_revision = 'add_unsubscribe_fields'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('inventory_item', schema=None) as batch_op:
        batch_op.add_column(sa.Column('suggested_price', sa.Float(), nullable=True))


def downgrade():
    with op.batch_alter_table('inventory_item', schema=None) as batch_op:
        batch_op.drop_column('suggested_price')
