"""add shop_notify_signup table

Backs the Shop Drop pre-launch waitlist. The `ShopNotifySignup` model and both
routes that use it (POST /shop/notify from inventory_teaser.html, and the admin
CSV export) have existed for a while, but the table was never created by any
migration — verified absent from the production dump on 2026-08-11. The export
route 500s today; the signup form would 500 as soon as shop_teaser_mode is
switched on.

Duplicates are allowed by design — no unique constraint on email.

Revision ID: 982051a9ce5d
Revises: 6e43b5721352
Create Date: 2026-08-11 21:15:04.825580

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '982051a9ce5d'
down_revision = '6e43b5721352'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'shop_notify_signup',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('email', sa.String(length=120), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('ip_address', sa.String(length=45), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade():
    op.drop_table('shop_notify_signup')
