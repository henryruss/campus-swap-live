"""add pickup_time_preference and moveout_date to user

Revision ID: b5c46df7b729
Revises: dd322174ae00
Create Date: 2026-04-04 22:04:33.861063

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b5c46df7b729'
down_revision = 'dd322174ae00'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('pickup_time_preference', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('moveout_date', sa.Date(), nullable=True))


def downgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_column('moveout_date')
        batch_op.drop_column('pickup_time_preference')
