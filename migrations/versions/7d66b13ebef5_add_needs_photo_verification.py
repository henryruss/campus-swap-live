"""add_needs_photo_verification

Revision ID: 7d66b13ebef5
Revises: 7978e1bce77b
Create Date: 2026-05-28 21:58:05.406187

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7d66b13ebef5'
down_revision = '7978e1bce77b'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('inventory_item', schema=None) as batch_op:
        batch_op.add_column(sa.Column('needs_photo_verification', sa.Boolean(), server_default='0', nullable=False))


def downgrade():
    with op.batch_alter_table('inventory_item', schema=None) as batch_op:
        batch_op.drop_column('needs_photo_verification')
