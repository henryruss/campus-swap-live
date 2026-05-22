"""fix_shift_week_unique_constraint

Revision ID: 1177e795033f
Revises: 5c32e8217b27
Create Date: 2026-05-21 21:10:00.000000

Replace the single-column unique constraint on shift_week.week_start with a
compound constraint on (week_start, is_tutorial). This allows one real week
and one tutorial week to share the same Monday date.

Uses batch_alter_table so the migration works on both SQLite (local dev) and
PostgreSQL (production). On SQLite it rebuilds the table; on Postgres it
issues ALTER TABLE statements.
"""
from alembic import op
import sqlalchemy as sa


revision = '1177e795033f'
down_revision = '5c32e8217b27'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('shift_week', schema=None) as batch_op:
        # Drop the old single-column constraint. It was already removed on
        # SQLite by the prior add_tutorial_system migration's batch rebuild,
        # so we ignore errors here.
        try:
            batch_op.drop_constraint('shift_week_week_start_key', type_='unique')
        except Exception:
            pass
        batch_op.create_unique_constraint(
            'uq_shift_week_week_start_is_tutorial',
            ['week_start', 'is_tutorial'],
        )


def downgrade():
    with op.batch_alter_table('shift_week', schema=None) as batch_op:
        batch_op.drop_constraint('uq_shift_week_week_start_is_tutorial', type_='unique')
        batch_op.create_unique_constraint('shift_week_week_start_key', ['week_start'])
