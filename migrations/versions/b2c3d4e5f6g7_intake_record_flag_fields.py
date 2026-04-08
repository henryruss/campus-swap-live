"""intake_record_flag_fields

Revision ID: c054f3e452f6
Revises: a5a07dc7a7d9
Create Date: 2026-04-07 18:01:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c054f3e452f6'
down_revision = 'a5a07dc7a7d9'
branch_labels = None
depends_on = None


def upgrade():
    # ── New columns on inventory_item ──────────────────────────────────
    with op.batch_alter_table('inventory_item', schema=None) as batch_op:
        batch_op.add_column(sa.Column('storage_location_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('storage_row', sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column('storage_note', sa.Text(), nullable=True))
        batch_op.create_foreign_key(
            'fk_inventory_item_storage_location',
            'storage_location', ['storage_location_id'], ['id']
        )

    # ── New column on shift_pickup ─────────────────────────────────────
    with op.batch_alter_table('shift_pickup', schema=None) as batch_op:
        batch_op.add_column(sa.Column('storage_location_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_shift_pickup_storage_location',
            'storage_location', ['storage_location_id'], ['id']
        )

    # ── New table: intake_record ───────────────────────────────────────
    op.create_table('intake_record',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('item_id', sa.Integer(), nullable=False),
    sa.Column('shift_id', sa.Integer(), nullable=False),
    sa.Column('organizer_id', sa.Integer(), nullable=False),
    sa.Column('storage_location_id', sa.Integer(), nullable=True),
    sa.Column('storage_row', sa.String(length=50), nullable=True),
    sa.Column('storage_note', sa.Text(), nullable=True),
    sa.Column('quality_before', sa.Integer(), nullable=False),
    sa.Column('quality_after', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['item_id'], ['inventory_item.id'], ),
    sa.ForeignKeyConstraint(['organizer_id'], ['user.id'], ),
    sa.ForeignKeyConstraint(['shift_id'], ['shift.id'], ),
    sa.ForeignKeyConstraint(['storage_location_id'], ['storage_location.id'], ),
    sa.PrimaryKeyConstraint('id')
    )

    # ── New table: intake_flag ─────────────────────────────────────────
    op.create_table('intake_flag',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('item_id', sa.Integer(), nullable=True),
    sa.Column('shift_id', sa.Integer(), nullable=False),
    sa.Column('intake_record_id', sa.Integer(), nullable=True),
    sa.Column('organizer_id', sa.Integer(), nullable=False),
    sa.Column('flag_type', sa.String(length=30), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('resolved', sa.Boolean(), nullable=True),
    sa.Column('resolved_at', sa.DateTime(), nullable=True),
    sa.Column('resolved_by_id', sa.Integer(), nullable=True),
    sa.Column('resolution_note', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['intake_record_id'], ['intake_record.id'], ),
    sa.ForeignKeyConstraint(['item_id'], ['inventory_item.id'], ),
    sa.ForeignKeyConstraint(['organizer_id'], ['user.id'], ),
    sa.ForeignKeyConstraint(['resolved_by_id'], ['user.id'], ),
    sa.ForeignKeyConstraint(['shift_id'], ['shift.id'], ),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade():
    op.drop_table('intake_flag')
    op.drop_table('intake_record')

    with op.batch_alter_table('shift_pickup', schema=None) as batch_op:
        batch_op.drop_constraint('fk_shift_pickup_storage_location', type_='foreignkey')
        batch_op.drop_column('storage_location_id')

    with op.batch_alter_table('inventory_item', schema=None) as batch_op:
        batch_op.drop_constraint('fk_inventory_item_storage_location', type_='foreignkey')
        batch_op.drop_column('storage_note')
        batch_op.drop_column('storage_row')
        batch_op.drop_column('storage_location_id')
