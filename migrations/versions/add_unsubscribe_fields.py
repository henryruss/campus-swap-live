"""Add unsubscribe fields to user model

Revision ID: add_unsubscribe_fields
Revises: 102d8aa73a95
Create Date: 2026-02-09 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_unsubscribe_fields'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade():
    # Add unsubscribe fields to user table
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('unsubscribed', sa.Boolean(), nullable=True, server_default='0'))
        batch_op.add_column(sa.Column('unsubscribe_token', sa.String(length=64), nullable=True))
        batch_op.create_index(batch_op.f('ix_user_unsubscribe_token'), ['unsubscribe_token'], unique=True)


def downgrade():
    # Remove unsubscribe fields
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_user_unsubscribe_token'))
        batch_op.drop_column('unsubscribe_token')
        batch_op.drop_column('unsubscribed')
