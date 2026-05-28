"""add_ai_approved_to_inventory_item

Revision ID: 3549247ca9e5
Revises: df2ec76b3e37
Create Date: 2026-05-28 17:00:08.136644

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3549247ca9e5'
down_revision = 'df2ec76b3e37'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('inventory_item', schema=None) as batch_op:
        batch_op.add_column(sa.Column('ai_approved', sa.Boolean(), server_default='0', nullable=False))


def downgrade():
    with op.batch_alter_table('inventory_item', schema=None) as batch_op:
        batch_op.drop_column('ai_approved')
