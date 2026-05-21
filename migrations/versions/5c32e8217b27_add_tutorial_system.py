"""add_tutorial_system

Revision ID: 5c32e8217b27
Revises: ffcbf72cb16a
Create Date: 2026-05-21 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = '5c32e8217b27'
down_revision = 'ffcbf72cb16a'
branch_labels = None
depends_on = None


def upgrade():
    # ── User.is_tutorial_user ──────────────────────────────────────────────
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'is_tutorial_user', sa.Boolean(), nullable=False, server_default='0',
        ))

    # ── ShiftWeek.is_tutorial + remove unique constraint on week_start ─────
    # batch_alter_table rebuilds the table from scratch on SQLite, so we
    # add the new column while NOT re-adding the unique constraint on week_start.
    # This allows multiple concurrent tutorial sessions to use the same Monday.
    with op.batch_alter_table('shift_week', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'is_tutorial', sa.Boolean(), nullable=False, server_default='0',
        ))

    # ── TutorialSession table ──────────────────────────────────────────────
    op.create_table(
        'tutorial_session',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('step', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('tutorial_week_id', sa.Integer(), nullable=True),
        sa.Column('last_retake_at', sa.DateTime(), nullable=True),
        sa.Column('is_retaking', sa.Boolean(), nullable=False, server_default='0'),
        sa.ForeignKeyConstraint(['tutorial_week_id'], ['shift_week.id']),
        sa.ForeignKeyConstraint(['user_id'], ['user.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id'),
    )


def downgrade():
    op.drop_table('tutorial_session')

    with op.batch_alter_table('shift_week', schema=None) as batch_op:
        batch_op.drop_column('is_tutorial')

    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_column('is_tutorial_user')
