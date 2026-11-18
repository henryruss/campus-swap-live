"""junk removal manager calendar

First junk removal tables (feature_junk_calendar.md): junk_job, append-only junk_job_event
history, and the User.is_junk_manager access flag.

Revision ID: 5d42249168ae
Revises: 39737a4ac282
Create Date: 2026-11-17 21:01:27.224747

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '5d42249168ae'
down_revision = '39737a4ac282'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'junk_job',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('customer_name', sa.String(length=120), nullable=True),
        sa.Column('customer_phone', sa.String(length=30), nullable=True),
        sa.Column('address', sa.String(length=255), nullable=True),
        sa.Column('quote_amount', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('scheduled_date', sa.Date(), nullable=True),
        sa.Column('queue_position', sa.Integer(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('completed_by_id', sa.Integer(), nullable=True),
        sa.Column('archived_at', sa.DateTime(), nullable=True),
        sa.Column('archived_by_id', sa.Integer(), nullable=True),
        sa.Column('created_by_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['archived_by_id'], ['user.id']),
        sa.ForeignKeyConstraint(['completed_by_id'], ['user.id']),
        sa.ForeignKeyConstraint(['created_by_id'], ['user.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_junk_job_day_queue', 'junk_job', ['scheduled_date', 'queue_position'])

    op.create_table(
        'junk_job_event',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('job_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('action', sa.String(length=20), nullable=False),
        sa.Column('changes', sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(['job_id'], ['junk_job.id']),
        sa.ForeignKeyConstraint(['user_id'], ['user.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_junk_job_event_job_id', 'junk_job_event', ['job_id'])

    op.add_column('user', sa.Column('is_junk_manager', sa.Boolean(), server_default='false', nullable=False))


def downgrade():
    op.drop_column('user', 'is_junk_manager')
    op.drop_index('ix_junk_job_event_job_id', table_name='junk_job_event')
    op.drop_table('junk_job_event')
    op.drop_index('ix_junk_job_day_queue', table_name='junk_job')
    op.drop_table('junk_job')
