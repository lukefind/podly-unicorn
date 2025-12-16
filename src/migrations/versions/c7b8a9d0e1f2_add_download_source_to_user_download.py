"""Add download_source to user_download

Revision ID: c7b8a9d0e1f2
Revises: d4e5f6a7b8c9
Create Date: 2025-12-16
"""

from alembic import op
import sqlalchemy as sa


revision = "c7b8a9d0e1f2"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("user_download", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("download_source", sa.String(length=20), nullable=False, server_default="web")
        )


def downgrade():
    with op.batch_alter_table("user_download", schema=None) as batch_op:
        batch_op.drop_column("download_source")
