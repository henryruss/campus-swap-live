"""Add pickup_week and dropoff_pod to inventory_item for post-approval logistics

Revision ID: e8f9g0h1i2j3
Revises: d7e8f9g0h1i2
Create Date: 2026-02-17

"""
from alembic import op
import sqlalchemy as sa


revision = 'e8f9g0h1i2j3'
down_revision = 'd7e8f9g0h1i2'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('inventory_item', schema=None) as batch_op:
        batch_op.add_column(sa.Column('pickup_week', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('dropoff_pod', sa.String(length=40), nullable=True))


def downgrade():
    with op.batch_alter_table('inventory_item', schema=None) as batch_op:
        batch_op.drop_column('dropoff_pod')
        batch_op.drop_column('pickup_week')
