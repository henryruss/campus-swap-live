"""add_itemphoto_is_hidden

Revision ID: 195e2dc3e376
Revises: 3ee9ed093bb3
Create Date: 2026-06-30 22:04:19.988285

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '195e2dc3e376'
down_revision = '3ee9ed093bb3'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('item_photo', sa.Column('is_hidden', sa.Boolean(), server_default='0', nullable=False))


def downgrade():
    op.drop_column('item_photo', 'is_hidden')
