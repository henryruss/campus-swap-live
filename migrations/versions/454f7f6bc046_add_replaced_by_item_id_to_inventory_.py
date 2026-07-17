"""add replaced_by_item_id to inventory_item

Revision ID: 454f7f6bc046
Revises: 74fd31ce2f07
Create Date: 2026-07-17 11:23:43.147418

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '454f7f6bc046'
down_revision = '74fd31ce2f07'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('inventory_item', sa.Column('replaced_by_item_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_inventory_item_replaced_by_item_id',
        'inventory_item', 'inventory_item',
        ['replaced_by_item_id'], ['id'],
    )


def downgrade():
    op.drop_constraint('fk_inventory_item_replaced_by_item_id', 'inventory_item', type_='foreignkey')
    op.drop_column('inventory_item', 'replaced_by_item_id')
