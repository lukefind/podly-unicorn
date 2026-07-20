"""Make user_download.post_id nullable for feed-level audit events.

Revision ID: r3s4t5u6v7w8
Revises: p2q3r4s5t6u7
Create Date: 2026-07-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "r3s4t5u6v7w8"
down_revision = "p2q3r4s5t6u7"
branch_labels = None
depends_on = None


def _post_id_column(bind):
    inspector = sa.inspect(bind)
    if "user_download" not in inspector.get_table_names():
        return None
    return next(
        (
            column
            for column in inspector.get_columns("user_download")
            if column["name"] == "post_id"
        ),
        None,
    )


def upgrade() -> None:
    bind = op.get_bind()
    post_id = _post_id_column(bind)
    if post_id is None or post_id["nullable"]:
        return

    with op.batch_alter_table("user_download", schema=None) as batch_op:
        batch_op.alter_column(
            "post_id",
            existing_type=sa.Integer(),
            nullable=True,
        )


def downgrade() -> None:
    bind = op.get_bind()
    post_id = _post_id_column(bind)
    if post_id is None or not post_id["nullable"]:
        return

    null_count = bind.execute(
        sa.text("SELECT COUNT(*) FROM user_download WHERE post_id IS NULL")
    ).scalar_one()
    if null_count:
        raise RuntimeError(
            "Cannot make user_download.post_id NOT NULL while rows with NULL post_id exist."
        )

    with op.batch_alter_table("user_download", schema=None) as batch_op:
        batch_op.alter_column(
            "post_id",
            existing_type=sa.Integer(),
            nullable=False,
        )
