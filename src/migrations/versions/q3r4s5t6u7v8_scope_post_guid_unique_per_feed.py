"""Scope post.guid uniqueness per feed

The same episode may legitimately appear in more than one feed, so the
global UNIQUE on post.guid becomes UNIQUE(feed_id, guid). A plain index on
guid keeps guid-only lookups fast. download_url stays unconstrained — feeds
re-use audio URLs for trailers/reruns within one feed (see k8l9m0n1o2p3).

Revision ID: q3r4s5t6u7v8
Revises: r3s4t5u6v7w8
Create Date: 2026-07-20
"""

import sqlalchemy as sa
from alembic import op

revision = "q3r4s5t6u7v8"
down_revision = "r3s4t5u6v7w8"
branch_labels = None
depends_on = None

# Lets batch mode address SQLite's unnamed inline UNIQUE constraints by a
# deterministic name so they can be dropped during the table rebuild.
NAMING_CONVENTION = {"uq": "uq_%(table_name)s_%(column_0_name)s"}


def _single_column_unique_columns(table_name):
    inspector = sa.inspect(op.get_bind())
    columns = set()
    for constraint in inspector.get_unique_constraints(table_name):
        constraint_columns = constraint.get("column_names") or []
        if len(constraint_columns) == 1:
            columns.add(constraint_columns[0])
    return columns


def upgrade():
    unique_columns = _single_column_unique_columns("post")
    with op.batch_alter_table(
        "post", schema=None, naming_convention=NAMING_CONVENTION
    ) as batch_op:
        if "guid" in unique_columns:
            batch_op.drop_constraint("uq_post_guid", type_="unique")
        if "download_url" in unique_columns:
            # Only present on databases created straight from the old models;
            # migrated databases already dropped it in k8l9m0n1o2p3.
            batch_op.drop_constraint("uq_post_download_url", type_="unique")
        batch_op.create_unique_constraint("uq_post_feed_id_guid", ["feed_id", "guid"])
        batch_op.create_index("ix_post_guid", ["guid"], unique=False)


def downgrade():
    # Restoring the global UNIQUE fails if the same episode meanwhile exists
    # in multiple feeds; those duplicates must be removed manually first.
    with op.batch_alter_table(
        "post", schema=None, naming_convention=NAMING_CONVENTION
    ) as batch_op:
        batch_op.drop_index("ix_post_guid")
        batch_op.drop_constraint("uq_post_feed_id_guid", type_="unique")
        batch_op.create_unique_constraint("uq_post_guid", ["guid"])
