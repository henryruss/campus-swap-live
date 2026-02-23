"""Add oversize_included_in_service_fee and fix legacy multi-oversized data

Revision ID: i3j4k5l6m7n8
Revises: h2i3j4k5l6m7
Create Date: 2026-02-22

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision = 'i3j4k5l6m7n8'
down_revision = 'h2i3j4k5l6m7'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('inventory_item', schema=None) as batch_op:
        batch_op.add_column(sa.Column('oversize_included_in_service_fee', sa.Boolean(), nullable=True))

    # Data fix: For users with 2+ available oversized (online, is_large), the first by id gets
    # oversize_included_in_service_fee=True. The rest revert to pending_logistics and count decremented.
    conn = op.get_bind()
    # Find seller_ids who have 2+ available oversized
    rows = conn.execute(text("""
        SELECT seller_id FROM inventory_item
        WHERE status = 'available' AND is_large = true AND collection_method = 'online'
        GROUP BY seller_id HAVING COUNT(*) >= 2
    """)).fetchall()
    for (seller_id,) in rows:
        if seller_id is None:
            continue
        # Get all available oversized for this seller, ordered by id
        items = conn.execute(text("""
            SELECT id, category_id FROM inventory_item
            WHERE seller_id = :sid AND status = 'available' AND is_large = true AND collection_method = 'online'
            ORDER BY id
        """), {"sid": seller_id}).fetchall()
        # First gets oversize_included_in_service_fee; rest revert to pending_logistics
        for i, (item_id, category_id) in enumerate(items):
            if i == 0:
                conn.execute(text("""
                    UPDATE inventory_item SET oversize_included_in_service_fee = true WHERE id = :id
                """), {"id": item_id})
            else:
                conn.execute(text("""
                    UPDATE inventory_item SET status = 'pending_logistics', oversize_included_in_service_fee = false WHERE id = :id
                """), {"id": item_id})
                if category_id:
                    conn.execute(text("""
                        UPDATE inventory_category
                        SET count_in_stock = COALESCE(count_in_stock, 0) - 1
                        WHERE id = :cid
                    """), {"cid": category_id})


def downgrade():
    with op.batch_alter_table('inventory_item', schema=None) as batch_op:
        batch_op.drop_column('oversize_included_in_service_fee')
