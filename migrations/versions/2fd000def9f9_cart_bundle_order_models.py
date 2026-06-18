"""cart_bundle_order_models

Adds Order (parent), Cart, CartItem tables and promotes BuyerOrder to a per-item
line item under Order (adds order_id, item_price_paid, item_sales_tax).
Includes a data backfill: one Order per pre-existing BuyerOrder.

Revision ID: 2fd000def9f9
Revises: 1510d2f4b483
Create Date: 2026-06-18

"""
from alembic import op
import sqlalchemy as sa
from decimal import Decimal
from datetime import datetime


revision = '2fd000def9f9'
down_revision = '1510d2f4b483'
branch_labels = None
depends_on = None


def upgrade():
    # --- 1. Create 'order' table ---
    op.create_table(
        'order',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('buyer_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=True),
        sa.Column('buyer_email', sa.String(length=120), nullable=True),
        sa.Column('buyer_name', sa.String(length=100), nullable=True),
        sa.Column('delivery_street', sa.String(length=200), nullable=True),
        sa.Column('delivery_city', sa.String(length=100), nullable=True),
        sa.Column('delivery_state', sa.String(length=20), nullable=True),
        sa.Column('delivery_zip', sa.String(length=20), nullable=True),
        sa.Column('delivery_lat', sa.Float(), nullable=True),
        sa.Column('delivery_lng', sa.Float(), nullable=True),
        sa.Column('distance_miles', sa.Float(), nullable=True),
        sa.Column('delivery_zone', sa.Integer(), nullable=True),
        sa.Column('delivery_fee', sa.Numeric(10, 2), server_default='0', nullable=True),
        sa.Column('bundle_free_delivery', sa.Boolean(), server_default='0', nullable=True),
        sa.Column('is_flexible_delivery', sa.Boolean(), server_default='0', nullable=True),
        sa.Column('flexible_discount', sa.Numeric(10, 2), server_default='0', nullable=True),
        sa.Column('sales_tax', sa.Numeric(10, 2), server_default='0', nullable=True),
        sa.Column('items_subtotal', sa.Numeric(10, 2), server_default='0', nullable=True),
        sa.Column('total_paid', sa.Numeric(10, 2), server_default='0', nullable=True),
        sa.Column('stripe_checkout_session_id', sa.String(length=120), nullable=True),
        sa.Column('status', sa.String(length=20), server_default='pending', nullable=True),
        sa.Column('has_conflict', sa.Boolean(), server_default='0', nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('paid_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )

    # --- 2. Create 'cart' table ---
    op.create_table(
        'cart',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=True),
        sa.Column('session_token', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_cart_session_token', 'cart', ['session_token'], unique=False)

    # --- 3. Create 'cart_item' table ---
    op.create_table(
        'cart_item',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('cart_id', sa.Integer(), sa.ForeignKey('cart.id'), nullable=False),
        sa.Column('item_id', sa.Integer(), sa.ForeignKey('inventory_item.id'), nullable=False),
        sa.Column('added_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('cart_id', 'item_id', name='uq_cart_item'),
    )

    # --- 4. Add new columns to 'buyer_order' ---
    with op.batch_alter_table('buyer_order', schema=None) as batch_op:
        batch_op.add_column(sa.Column('order_id', sa.Integer(), sa.ForeignKey('order.id'), nullable=True))
        batch_op.add_column(sa.Column('item_price_paid', sa.Numeric(10, 2), nullable=True))
        batch_op.add_column(sa.Column('item_sales_tax', sa.Numeric(10, 2), nullable=True))

    # --- 5. Data backfill: one Order per existing BuyerOrder ---
    conn = op.get_bind()

    # Diagnose before backfill
    result = conn.execute(sa.text('SELECT COUNT(*) FROM buyer_order'))
    total = result.scalar()

    if total > 0:
        rows = conn.execute(sa.text('''
            SELECT
                bo.id,
                bo.buyer_email,
                bo.delivery_address,
                bo.delivery_lat,
                bo.delivery_lng,
                bo.distance_miles,
                bo.delivery_zone,
                bo.delivery_fee,
                bo.is_flexible_delivery,
                bo.flexible_discount,
                bo.sales_tax,
                bo.items_subtotal,
                bo.total_paid,
                bo.stripe_checkout_session_id,
                bo.created_at,
                ii.seller_id
            FROM buyer_order bo
            JOIN inventory_item ii ON ii.id = bo.item_id
            WHERE bo.order_id IS NULL
        ''')).fetchall()

        now = datetime.utcnow()

        for row in rows:
            # Parse address into parts (best effort — legacy rows have a single address_string)
            addr = row[2] or ''  # delivery_address
            # Legacy format: "123 Main St, City, ST 27514"
            # We store full address in delivery_street for display; city/state/zip left null
            # (new orders will populate all parts properly)

            delivery_fee = row[7]
            is_flexible = bool(row[8])
            flexible_discount = row[9]
            sales_tax = row[10]
            items_subtotal = row[11]
            total_paid = row[12]
            stripe_csid = row[13]
            created_at = row[14] or now
            buyer_email = row[1] or ''

            # Insert a corresponding Order row
            result2 = conn.execute(sa.text('''
                INSERT INTO "order" (
                    buyer_email,
                    delivery_street,
                    delivery_lat, delivery_lng,
                    distance_miles, delivery_zone,
                    delivery_fee, bundle_free_delivery,
                    is_flexible_delivery, flexible_discount,
                    sales_tax, items_subtotal, total_paid,
                    stripe_checkout_session_id,
                    status, has_conflict,
                    created_at, paid_at
                ) VALUES (
                    :buyer_email,
                    :delivery_street,
                    :delivery_lat, :delivery_lng,
                    :distance_miles, :delivery_zone,
                    :delivery_fee, FALSE,
                    :is_flexible, :flexible_discount,
                    :sales_tax, :items_subtotal, :total_paid,
                    :stripe_csid,
                    'paid', FALSE,
                    :created_at, :created_at
                ) RETURNING id
            '''), {
                'buyer_email': buyer_email,
                'delivery_street': addr,
                'delivery_lat': row[3],
                'delivery_lng': row[4],
                'distance_miles': row[5],
                'delivery_zone': row[6],
                'delivery_fee': delivery_fee if delivery_fee is not None else 0,
                'is_flexible': is_flexible,
                'flexible_discount': flexible_discount if flexible_discount is not None else 0,
                'sales_tax': sales_tax if sales_tax is not None else 0,
                'items_subtotal': items_subtotal if items_subtotal is not None else 0,
                'total_paid': total_paid if total_paid is not None else 0,
                'stripe_csid': stripe_csid,
                'created_at': created_at,
            })
            new_order_id = result2.fetchone()[0]

            # Link BuyerOrder to the new Order; populate per-item financials
            conn.execute(sa.text('''
                UPDATE buyer_order
                SET order_id = :order_id,
                    item_price_paid = COALESCE(items_subtotal, 0),
                    item_sales_tax = COALESCE(sales_tax, 0)
                WHERE id = :bo_id
            '''), {'order_id': new_order_id, 'bo_id': row[0]})

    # Verify counts match
    orders_created = conn.execute(sa.text('SELECT COUNT(*) FROM "order"')).scalar()
    bo_linked = conn.execute(sa.text('SELECT COUNT(*) FROM buyer_order WHERE order_id IS NOT NULL')).scalar()
    print(f"[backfill] BuyerOrders: {total}, Orders created: {orders_created}, BuyerOrders linked: {bo_linked}")


def downgrade():
    # Remove new buyer_order columns first (FK reference to order)
    with op.batch_alter_table('buyer_order', schema=None) as batch_op:
        batch_op.drop_column('item_sales_tax')
        batch_op.drop_column('item_price_paid')
        batch_op.drop_column('order_id')

    op.drop_table('cart_item')
    op.drop_index('ix_cart_session_token', table_name='cart')
    op.drop_table('cart')
    op.drop_table('order')
