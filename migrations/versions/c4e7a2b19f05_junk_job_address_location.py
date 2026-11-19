"""junk job address location

Lat/lng of the address, captured when a manager picks a Google Places suggestion. Drives the
map preview in the job modal (and later, crew routing). NULL = typed by hand / not located.

Revision ID: c4e7a2b19f05
Revises: 8b1f3c2d9a47
Create Date: 2026-11-18 19:10:00

"""
from alembic import op
import sqlalchemy as sa


revision = 'c4e7a2b19f05'
down_revision = '8b1f3c2d9a47'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('junk_job', sa.Column('address_lat', sa.Float(), nullable=True))
    op.add_column('junk_job', sa.Column('address_lng', sa.Float(), nullable=True))


def downgrade():
    op.drop_column('junk_job', 'address_lng')
    op.drop_column('junk_job', 'address_lat')
