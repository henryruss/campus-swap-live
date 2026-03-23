"""add video_url to inventory_item

Revision ID: a882933b0cca
Revises: n2o3p4q5r6s7
Create Date: 2026-03-23 16:03:47.012650

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a882933b0cca'
down_revision = 'n2o3p4q5r6s7'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('inventory_item', schema=None) as batch_op:
        batch_op.add_column(sa.Column('video_url', sa.String(length=200), nullable=True))


def downgrade():
    with op.batch_alter_table('inventory_item', schema=None) as batch_op:
        batch_op.drop_column('video_url')
