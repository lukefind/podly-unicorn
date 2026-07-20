"""Add feed.last_changed_at for RSS ETag/Last-Modified validators

Backfilled to the migration time so conditional polls start answering 304
immediately; refresh_feed advances it whenever content actually changes.

Revision ID: r4s5t6u7v8w9
Revises: q3r4s5t6u7v8
Create Date: 2026-07-20
"""

import sqlalchemy as sa
from alembic import op

revision = "r4s5t6u7v8w9"
down_revision = "q3r4s5t6u7v8"
branch_labels = None
depends_on = None


def _column_exists(table_name, column_name):
    inspector = sa.inspect(op.get_bind())
    return column_name in [
        column["name"] for column in inspector.get_columns(table_name)
    ]


def upgrade():
    if _column_exists("feed", "last_changed_at"):
        return
    with op.batch_alter_table("feed", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "last_changed_at",
                sa.DateTime(),
                nullable=True,
                server_default=sa.func.current_timestamp(),
            )
        )


def downgrade():
    if not _column_exists("feed", "last_changed_at"):
        return
    with op.batch_alter_table("feed", schema=None) as batch_op:
        batch_op.drop_column("last_changed_at")
