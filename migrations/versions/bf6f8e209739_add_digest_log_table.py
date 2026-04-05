"""add digest_log table

Revision ID: bf6f8e209739
Revises: 11e979ce55c8
Create Date: 2026-04-04 22:45:49.473035

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'bf6f8e209739'
down_revision = '11e979ce55c8'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('digest_log',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('sent_at', sa.DateTime(), nullable=True),
    sa.Column('item_count', sa.Integer(), nullable=False),
    sa.Column('recipient_count', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade():
    op.drop_table('digest_log')
