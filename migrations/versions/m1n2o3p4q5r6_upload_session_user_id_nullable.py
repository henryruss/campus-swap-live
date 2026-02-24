"""Make UploadSession.user_id nullable for guest onboarding

Revision ID: m1n2o3p4q5r6
Revises: suggested_price
Create Date: 2026-02-23

"""
from alembic import op
import sqlalchemy as sa


revision = 'm1n2o3p4q5r6'
down_revision = 'suggested_price'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('upload_session', schema=None) as batch_op:
        batch_op.alter_column(
            'user_id',
            existing_type=sa.Integer(),
            nullable=True
        )


def downgrade():
    with op.batch_alter_table('upload_session', schema=None) as batch_op:
        batch_op.alter_column(
            'user_id',
            existing_type=sa.Integer(),
            nullable=False
        )
