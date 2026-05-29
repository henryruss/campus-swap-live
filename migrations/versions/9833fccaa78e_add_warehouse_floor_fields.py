"""add_warehouse_floor_fields

Revision ID: 9833fccaa78e
Revises: 3549247ca9e5
Create Date: 2026-05-28 18:35:42.777066

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9833fccaa78e'
down_revision = '3549247ca9e5'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('storage_location', schema=None) as batch_op:
        batch_op.add_column(sa.Column('snapshot_capacity', sa.Float(), nullable=True))


def downgrade():
    with op.batch_alter_table('storage_location', schema=None) as batch_op:
        batch_op.drop_column('snapshot_capacity')
