"""storage_location

Revision ID: a5a07dc7a7d9
Revises: 69ddb3d57f86
Create Date: 2026-04-07 18:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a5a07dc7a7d9'
down_revision = '69ddb3d57f86'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('storage_location',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('address', sa.String(length=200), nullable=True),
    sa.Column('location_note', sa.Text(), nullable=True),
    sa.Column('capacity_note', sa.Text(), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=True),
    sa.Column('is_full', sa.Boolean(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('created_by_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['created_by_id'], ['user.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )


def downgrade():
    op.drop_table('storage_location')
