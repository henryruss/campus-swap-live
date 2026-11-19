"""junk crew flag

User.is_junk_crew: access to the crew side of the junk removal portal.

Revision ID: d5a91e7c3b20
Revises: c4e7a2b19f05
Create Date: 2026-11-18 20:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = 'd5a91e7c3b20'
down_revision = 'c4e7a2b19f05'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('user', sa.Column('is_junk_crew', sa.Boolean(), nullable=False,
                                    server_default=sa.text('false')))


def downgrade():
    op.drop_column('user', 'is_junk_crew')
