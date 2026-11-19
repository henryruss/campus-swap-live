"""junk job assignment

Who is on each job. Crew and managers can both be assigned.

Revision ID: e7b4c2a9d1f3
Revises: d5a91e7c3b20
Create Date: 2026-11-18 22:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = 'e7b4c2a9d1f3'
down_revision = 'd5a91e7c3b20'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'junk_job_assignment',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('job_id', sa.Integer(), sa.ForeignKey('junk_job.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=True),
        sa.UniqueConstraint('job_id', 'user_id', name='uq_junk_job_assignment'),
    )
    op.create_index('ix_junk_job_assignment_job_id', 'junk_job_assignment', ['job_id'])
    op.create_index('ix_junk_job_assignment_user_id', 'junk_job_assignment', ['user_id'])


def downgrade():
    op.drop_index('ix_junk_job_assignment_user_id', table_name='junk_job_assignment')
    op.drop_index('ix_junk_job_assignment_job_id', table_name='junk_job_assignment')
    op.drop_table('junk_job_assignment')
