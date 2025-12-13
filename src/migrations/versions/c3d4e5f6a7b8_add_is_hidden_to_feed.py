"""Add is_hidden to feed

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2025-12-13
"""
from alembic import op
import sqlalchemy as sa

revision = 'c3d4e5f6a7b8'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('feed', sa.Column('is_hidden', sa.Boolean(), nullable=False, server_default='0'))

def downgrade():
    op.drop_column('feed', 'is_hidden')
