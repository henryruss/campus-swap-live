"""Flatten payout rate to 50/50 — remove referral program variable rate

Revision ID: flat_50_payout_rate
Revises: shift_last_notified_at
Create Date: 2026-04-17 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'flat_50_payout_rate'
down_revision = 'shift_last_notified_at'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('UPDATE "user" SET payout_rate = 50')
    with op.batch_alter_table('user') as batch_op:
        batch_op.alter_column('payout_rate',
                              existing_type=sa.Integer(),
                              server_default='50',
                              existing_nullable=False)


def downgrade():
    with op.batch_alter_table('user') as batch_op:
        batch_op.alter_column('payout_rate',
                              existing_type=sa.Integer(),
                              server_default='20',
                              existing_nullable=False)
