"""junk job checklist

Slice 3a: checklist photos (cleared out, dump receipt) and the answers that aren't photos
(dumped with another job; truck returned / handed off / still have it).

Revision ID: f2c8d4e6a1b9
Revises: e7b4c2a9d1f3
Create Date: 2026-11-21 14:10:00

"""
from alembic import op
import sqlalchemy as sa


revision = 'f2c8d4e6a1b9'
down_revision = 'e7b4c2a9d1f3'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'junk_job_photo',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('job_id', sa.Integer(), sa.ForeignKey('junk_job.id', ondelete='CASCADE'), nullable=False),
        sa.Column('kind', sa.String(20), nullable=False),
        sa.Column('key', sa.String(120), nullable=False),
        sa.Column('uploaded_by_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_junk_job_photo_job_id', 'junk_job_photo', ['job_id'])
    op.create_table(
        'junk_job_check',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('job_id', sa.Integer(), sa.ForeignKey('junk_job.id', ondelete='CASCADE'), nullable=False),
        sa.Column('item', sa.String(20), nullable=False),
        sa.Column('answer', sa.String(20), nullable=False),
        sa.Column('handed_to_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=True),
        sa.Column('answered_by_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=True),
        sa.Column('answered_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('job_id', 'item', name='uq_junk_job_check'),
    )
    op.create_index('ix_junk_job_check_job_id', 'junk_job_check', ['job_id'])


def downgrade():
    op.drop_index('ix_junk_job_check_job_id', table_name='junk_job_check')
    op.drop_table('junk_job_check')
    op.drop_index('ix_junk_job_photo_job_id', table_name='junk_job_photo')
    op.drop_table('junk_job_photo')
