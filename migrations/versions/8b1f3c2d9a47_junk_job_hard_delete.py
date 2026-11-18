"""junk job hard delete

Henry dropped the Removed-jobs / put-back flow: deleting a junk job now deletes it.
The soft-delete columns are no longer used. Any rows that were soft-deleted locally are
deleted for real first, along with their history.

Revision ID: 8b1f3c2d9a47
Revises: 5d42249168ae
Create Date: 2026-11-17 23:30:00

"""
from alembic import op
import sqlalchemy as sa


revision = '8b1f3c2d9a47'
down_revision = '5d42249168ae'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("DELETE FROM junk_job_event WHERE job_id IN (SELECT id FROM junk_job WHERE archived_at IS NOT NULL)")
    op.execute("DELETE FROM junk_job WHERE archived_at IS NOT NULL")
    op.drop_constraint('junk_job_archived_by_id_fkey', 'junk_job', type_='foreignkey')
    op.drop_column('junk_job', 'archived_by_id')
    op.drop_column('junk_job', 'archived_at')


def downgrade():
    op.add_column('junk_job', sa.Column('archived_at', sa.DateTime(), nullable=True))
    op.add_column('junk_job', sa.Column('archived_by_id', sa.Integer(), nullable=True))
    op.create_foreign_key('junk_job_archived_by_id_fkey', 'junk_job', 'user', ['archived_by_id'], ['id'])
