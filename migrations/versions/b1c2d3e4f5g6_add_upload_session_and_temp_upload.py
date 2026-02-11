"""Add UploadSession and TempUpload models for QR mobile photo upload

Revision ID: b1c2d3e4f5g6
Revises: 6ac62424b704
Create Date: 2026-02-10

"""
from alembic import op
import sqlalchemy as sa


revision = 'b1c2d3e4f5g6'
down_revision = '6ac62424b704'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('upload_session',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('session_token', sa.String(length=64), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('session_token')
    )
    op.create_index('ix_upload_session_session_token', 'upload_session', ['session_token'], unique=True)

    op.create_table('temp_upload',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('session_token', sa.String(length=64), nullable=False),
        sa.Column('filename', sa.String(length=200), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_temp_upload_session_token', 'temp_upload', ['session_token'], unique=False)


def downgrade():
    op.drop_index('ix_temp_upload_session_token', table_name='temp_upload')
    op.drop_table('temp_upload')
    op.drop_index('ix_upload_session_session_token', table_name='upload_session')
    op.drop_table('upload_session')
