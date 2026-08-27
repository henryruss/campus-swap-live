"""buyer pickup fulfillment fields

Records the handoff of a sale the buyer collects themselves (free-delivery promo code,
or an item we marked sold by hand). Those sales never produce a DeliveryStop, so without
these columns there is no record that the buyer actually took the item.

Revision ID: 39737a4ac282
Revises: 543e48c154eb
Create Date: 2026-08-27 19:40:45.145574

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '39737a4ac282'
down_revision = '543e48c154eb'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('inventory_item', sa.Column('picked_up_by_buyer_at', sa.DateTime(), nullable=True))
    op.add_column('inventory_item', sa.Column('picked_up_by_buyer_by_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_inventory_item_picked_up_by_buyer_by_id_user',
        'inventory_item', 'user',
        ['picked_up_by_buyer_by_id'], ['id'],
    )


def downgrade():
    op.drop_constraint('fk_inventory_item_picked_up_by_buyer_by_id_user', 'inventory_item', type_='foreignkey')
    op.drop_column('inventory_item', 'picked_up_by_buyer_by_id')
    op.drop_column('inventory_item', 'picked_up_by_buyer_at')
