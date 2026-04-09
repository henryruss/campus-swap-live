"""Fix rug category icon (was fa-th-large, same as View All)

Revision ID: e2f3g4h5i6j7
Revises: d1e2f3g4h5i6
Create Date: 2026-04-09

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = 'e2f3g4h5i6j7'
down_revision = 'd1e2f3g4h5i6'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    # Update any rug category that still has the generic fa-th-large icon
    conn.execute(text(
        "UPDATE inventory_category SET icon = 'fa-chess-board' "
        "WHERE LOWER(name) LIKE '%rug%' AND (icon = 'fa-th-large' OR icon IS NULL)"
    ))


def downgrade():
    conn = op.get_bind()
    conn.execute(text(
        "UPDATE inventory_category SET icon = 'fa-th-large' "
        "WHERE LOWER(name) LIKE '%rug%' AND icon = 'fa-chess-board'"
    ))
