"""itemphoto rephoto campaign columns

Revision ID: 4091b1a0e9c8
Revises: 195e2dc3e376
Create Date: 2026-07-08 21:38:11.482549

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '4091b1a0e9c8'
down_revision = '195e2dc3e376'
branch_labels = None
depends_on = None


def upgrade():
    # Warehouse re-photography campaign columns. No backfill by design:
    # captured_at NULL / view NULL = legacy pre-campaign photo; sort_order defaults 0.
    op.add_column('item_photo', sa.Column('captured_at', sa.DateTime(), nullable=True))
    op.add_column('item_photo', sa.Column('sort_order', sa.Integer(), server_default='0', nullable=False))
    op.add_column('item_photo', sa.Column('view', sa.String(length=10), nullable=True))


def downgrade():
    op.drop_column('item_photo', 'view')
    op.drop_column('item_photo', 'sort_order')
    op.drop_column('item_photo', 'captured_at')
