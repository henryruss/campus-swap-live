"""Increase password_hash column size to 255

Revision ID: a1b2c3d4e5f6
Revises: 102d8aa73a95
Create Date: 2026-02-08 16:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = '102d8aa73a95'
branch_labels = None
depends_on = None


def upgrade():
    # Alter password_hash column from VARCHAR(128) to VARCHAR(255)
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.alter_column('password_hash',
                              existing_type=sa.String(length=128),
                              type_=sa.String(length=255),
                              existing_nullable=True)


def downgrade():
    # Revert password_hash column back to VARCHAR(128)
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.alter_column('password_hash',
                              existing_type=sa.String(length=255),
                              type_=sa.String(length=128),
                              existing_nullable=True)
