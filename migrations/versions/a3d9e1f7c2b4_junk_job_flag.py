"""junk job flag

Crew flag a problem on a job; the calendar card turns amber until a manager resolves it.

Revision ID: a3d9e1f7c2b4
Revises: f2c8d4e6a1b9
Create Date: 2026-11-23 10:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = 'a3d9e1f7c2b4'
down_revision = 'f2c8d4e6a1b9'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('junk_job', sa.Column('flag_note', sa.Text(), nullable=True))
    op.add_column('junk_job', sa.Column('flag_by_id', sa.Integer(), sa.ForeignKey('user.id', name='fk_junk_job_flag_by'), nullable=True))
    op.add_column('junk_job', sa.Column('flag_at', sa.DateTime(), nullable=True))
    op.add_column('junk_job', sa.Column('flag_resolved_at', sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column('junk_job', 'flag_resolved_at')
    op.drop_column('junk_job', 'flag_at')
    op.drop_constraint('fk_junk_job_flag_by', 'junk_job', type_='foreignkey')
    op.drop_column('junk_job', 'flag_by_id')
    op.drop_column('junk_job', 'flag_note')
