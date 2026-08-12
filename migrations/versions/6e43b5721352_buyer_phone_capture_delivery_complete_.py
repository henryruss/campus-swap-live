"""buyer phone capture + delivery complete email flag

Adds:
- order.buyer_phone         — collected by Stripe Checkout phone_number_collection
- buyer_order.buyer_phone   — denormalized from Order for ops/crew views
- delivery_stop.completed_email_sent_at — guards against re-sending the
  delivery-complete email when a stop is re-marked

Note: autogenerate also proposed create_table('shop_notify_signup'). That is
pre-existing schema drift unrelated to this change and is deliberately excluded
so a failure there cannot block these columns.

Revision ID: 6e43b5721352
Revises: 480cd6c9c8ba
Create Date: 2026-08-11 20:45:40.836145

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '6e43b5721352'
down_revision = '480cd6c9c8ba'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('order', sa.Column('buyer_phone', sa.String(length=30), nullable=True))
    op.add_column('buyer_order', sa.Column('buyer_phone', sa.String(length=30), nullable=True))
    op.add_column('delivery_stop', sa.Column('completed_email_sent_at', sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column('delivery_stop', 'completed_email_sent_at')
    op.drop_column('buyer_order', 'buyer_phone')
    op.drop_column('order', 'buyer_phone')
