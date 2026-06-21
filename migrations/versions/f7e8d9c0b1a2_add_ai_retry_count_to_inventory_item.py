"""add ai_retry_count to inventory_item

Revision ID: a1b2c3d4e5f6
Revises: 2fd000def9f9
Create Date: 2026-06-21

"""
from alembic import op
import sqlalchemy as sa

revision = 'f7e8d9c0b1a2'
down_revision = '2fd000def9f9'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('inventory_item',
        sa.Column('ai_retry_count', sa.Integer(), nullable=False, server_default='0')
    )


def downgrade():
    op.drop_column('inventory_item', 'ai_retry_count')
