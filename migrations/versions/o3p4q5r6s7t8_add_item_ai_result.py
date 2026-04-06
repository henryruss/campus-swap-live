"""Add ItemAIResult table for AI item valuation

Revision ID: o3p4q5r6s7t8
Revises: bf6f8e209739
Create Date: 2026-04-05

"""
from alembic import op
import sqlalchemy as sa


revision = 'o3p4q5r6s7t8'
down_revision = 'bf6f8e209739'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'item_ai_result',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('item_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='pending'),
        sa.Column('product_name', sa.String(length=500), nullable=True),
        sa.Column('retail_price', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('retail_price_source', sa.String(length=500), nullable=True),
        sa.Column('suggested_price', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('pricing_rationale', sa.Text(), nullable=True),
        sa.Column('ai_description', sa.Text(), nullable=True),
        sa.Column('raw_response', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['item_id'], ['inventory_item.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('item_id')
    )


def downgrade():
    op.drop_table('item_ai_result')
