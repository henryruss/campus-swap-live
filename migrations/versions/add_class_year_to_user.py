"""Add class_year to User

Revision ID: add_class_year_to_user
Revises: merge_buyer_order_and_flat_50
Create Date: 2026-05-04

"""
from alembic import op
import sqlalchemy as sa


revision = 'add_class_year_to_user'
down_revision = 'merge_buyer_order_and_flat_50'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('user', sa.Column('class_year', sa.String(length=20), nullable=True))


def downgrade():
    op.drop_column('user', 'class_year')
