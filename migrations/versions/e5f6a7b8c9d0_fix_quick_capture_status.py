"""Fix quick-capture items incorrectly set to needs_info status

Quick-capture items should always be pending_valuation until an admin
completes them via the Quick Captures queue. Items that ended up as
needs_info were set there by the standard approval-queue "Request Info"
flow, which now correctly excludes quick captures.

Revision ID: e5f6a7b8c9d0
Revises: d449caa14176
Create Date: 2026-05-20

"""
from alembic import op
import sqlalchemy as sa

revision = 'e5f6a7b8c9d0'
down_revision = 'd449caa14176'
branch_labels = None
depends_on = None


def upgrade():
    # Reset any quick-capture items stuck in needs_info back to pending_valuation
    op.execute(
        "UPDATE inventory_item SET status = 'pending_valuation' "
        "WHERE is_quick_capture = 1 AND status = 'needs_info'"
    )
    # Resolve the stale needs_info SellerAlerts created for those items
    op.execute(
        """
        UPDATE seller_alert
        SET resolved = 1,
            resolved_at = datetime('now')
        WHERE alert_type = 'needs_info'
          AND item_id IN (
              SELECT id FROM inventory_item
              WHERE is_quick_capture = 1
          )
          AND resolved = 0
        """
    )


def downgrade():
    # No meaningful rollback — we can't know which items were originally needs_info
    pass
