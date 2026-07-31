"""fb marketplace export fields

Revision ID: 480cd6c9c8ba
Revises: 700635cb195e
Create Date: 2026-07-31 07:37:54.274035

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '480cd6c9c8ba'
down_revision = '700635cb195e'
branch_labels = None
depends_on = None


def upgrade():
    # Facebook Marketplace export tracking. Postgres-native ALTERs (no batch_alter_table —
    # that is SQLite-only syntax and this project is Postgres everywhere).
    op.add_column('inventory_item', sa.Column('fb_posted_at', sa.DateTime(), nullable=True))
    op.add_column('inventory_item', sa.Column('fb_listing_url', sa.String(length=300), nullable=True))
    op.add_column(
        'user',
        sa.Column('is_marketplace_poster', sa.Boolean(), server_default=sa.false(), nullable=False),
    )


def downgrade():
    op.drop_column('user', 'is_marketplace_poster')
    op.drop_column('inventory_item', 'fb_listing_url')
    op.drop_column('inventory_item', 'fb_posted_at')
