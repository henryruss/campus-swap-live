"""Add oauth_provider and oauth_id to user model

Revision ID: d7e8f9g0h1i2
Revises: c2d3e4f5g6h7
Create Date: 2026-02-12

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd7e8f9g0h1i2'
down_revision = 'c2d3e4f5g6h7'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('oauth_provider', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('oauth_id', sa.String(length=120), nullable=True))


def downgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_column('oauth_id')
        batch_op.drop_column('oauth_provider')
