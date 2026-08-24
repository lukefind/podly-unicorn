"""Add nullable per-feed processed episode retention count.

Revision ID: s5t6u7v8w9x0
Revises: r4s5t6u7v8w9
Create Date: 2026-08-24
"""

import sqlalchemy as sa
from alembic import op

revision = "s5t6u7v8w9x0"
down_revision = "r4s5t6u7v8w9"
branch_labels = None
depends_on = None


def _column_exists(table_name, column_name):
    inspector = sa.inspect(op.get_bind())
    return column_name in [
        column["name"] for column in inspector.get_columns(table_name)
    ]


def upgrade():
    if _column_exists("feed", "processed_episode_retention_count"):
        return
    with op.batch_alter_table("feed", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("processed_episode_retention_count", sa.Integer(), nullable=True)
        )


def downgrade():
    if not _column_exists("feed", "processed_episode_retention_count"):
        return
    with op.batch_alter_table("feed", schema=None) as batch_op:
        batch_op.drop_column("processed_episode_retention_count")
