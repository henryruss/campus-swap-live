"""Add pickup location fields for secure collection point

Revision ID: c2d3e4f5g6h7
Revises: b1c2d3e4f5g6
Create Date: 2026-02-10

"""
from alembic import op
import sqlalchemy as sa


revision = 'c2d3e4f5g6h7'
down_revision = 'b1c2d3e4f5g6'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('pickup_location_type', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('pickup_dorm', sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column('pickup_room', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('pickup_note', sa.String(length=200), nullable=True))
        batch_op.add_column(sa.Column('pickup_lat', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('pickup_lng', sa.Float(), nullable=True))


def downgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_column('pickup_lng')
        batch_op.drop_column('pickup_lat')
        batch_op.drop_column('pickup_note')
        batch_op.drop_column('pickup_room')
        batch_op.drop_column('pickup_dorm')
        batch_op.drop_column('pickup_location_type')
