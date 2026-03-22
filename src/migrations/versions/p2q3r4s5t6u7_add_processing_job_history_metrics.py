"""add processing job history metrics

Revision ID: p2q3r4s5t6u7
Revises: n1o2p3q4r5s6
Create Date: 2026-03-22 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "p2q3r4s5t6u7"
down_revision = "n1o2p3q4r5s6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    existing_tables = set(inspector.get_table_names())
    if "processing_job" not in existing_tables:
        return

    columns = {col["name"] for col in inspector.get_columns("processing_job")}
    additions: list[sa.Column] = []
    if "feed_id" not in columns:
        additions.append(sa.Column("feed_id", sa.Integer(), nullable=True))
    if "feed_title" not in columns:
        additions.append(sa.Column("feed_title", sa.Text(), nullable=True))
    if "post_title" not in columns:
        additions.append(sa.Column("post_title", sa.Text(), nullable=True))
    if "total_ad_segments_removed" not in columns:
        additions.append(
            sa.Column("total_ad_segments_removed", sa.Integer(), nullable=True)
        )
    if "total_duration_removed_seconds" not in columns:
        additions.append(
            sa.Column(
                "total_duration_removed_seconds", sa.Float(), nullable=True
            )
        )
    if "original_duration_seconds" not in columns:
        additions.append(
            sa.Column("original_duration_seconds", sa.Float(), nullable=True)
        )
    if "processed_duration_seconds" not in columns:
        additions.append(
            sa.Column("processed_duration_seconds", sa.Float(), nullable=True)
        )
    if "percentage_removed" not in columns:
        additions.append(sa.Column("percentage_removed", sa.Float(), nullable=True))

    existing_indexes = {idx["name"] for idx in inspector.get_indexes("processing_job")}

    if additions:
        with op.batch_alter_table("processing_job", schema=None) as batch_op:
            for column in additions:
                batch_op.add_column(column)
    refreshed_columns = {col["name"] for col in sa.inspect(bind).get_columns("processing_job")}
    if "feed_id" in refreshed_columns and "ix_processing_job_feed_id" not in existing_indexes:
        op.create_index(
            "ix_processing_job_feed_id",
            "processing_job",
            ["feed_id"],
            unique=False,
        )

    op.execute(
        sa.text(
            """
            UPDATE processing_job
            SET
                feed_id = COALESCE(
                    feed_id,
                    (SELECT post.feed_id FROM post WHERE post.guid = processing_job.post_guid)
                ),
                post_title = COALESCE(
                    post_title,
                    (SELECT post.title FROM post WHERE post.guid = processing_job.post_guid)
                ),
                feed_title = COALESCE(
                    feed_title,
                    (
                        SELECT feed.title
                        FROM post
                        JOIN feed ON feed.id = post.feed_id
                        WHERE post.guid = processing_job.post_guid
                    )
                ),
                total_ad_segments_removed = COALESCE(
                    total_ad_segments_removed,
                    (
                        SELECT processing_statistics.total_ad_segments_removed
                        FROM post
                        JOIN processing_statistics ON processing_statistics.post_id = post.id
                        WHERE post.guid = processing_job.post_guid
                    )
                ),
                total_duration_removed_seconds = COALESCE(
                    total_duration_removed_seconds,
                    (
                        SELECT processing_statistics.total_duration_removed_seconds
                        FROM post
                        JOIN processing_statistics ON processing_statistics.post_id = post.id
                        WHERE post.guid = processing_job.post_guid
                    )
                ),
                original_duration_seconds = COALESCE(
                    original_duration_seconds,
                    (
                        SELECT processing_statistics.original_duration_seconds
                        FROM post
                        JOIN processing_statistics ON processing_statistics.post_id = post.id
                        WHERE post.guid = processing_job.post_guid
                    )
                ),
                processed_duration_seconds = COALESCE(
                    processed_duration_seconds,
                    (
                        SELECT processing_statistics.processed_duration_seconds
                        FROM post
                        JOIN processing_statistics ON processing_statistics.post_id = post.id
                        WHERE post.guid = processing_job.post_guid
                    )
                ),
                percentage_removed = COALESCE(
                    percentage_removed,
                    (
                        SELECT processing_statistics.percentage_removed
                        FROM post
                        JOIN processing_statistics ON processing_statistics.post_id = post.id
                        WHERE post.guid = processing_job.post_guid
                    )
                )
            """
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    existing_tables = set(inspector.get_table_names())
    if "processing_job" not in existing_tables:
        return

    columns = {col["name"] for col in inspector.get_columns("processing_job")}
    existing_indexes = {idx["name"] for idx in inspector.get_indexes("processing_job")}
    if "feed_id" in columns and "ix_processing_job_feed_id" in existing_indexes:
        op.drop_index("ix_processing_job_feed_id", table_name="processing_job")

    drop_order = [
        "percentage_removed",
        "processed_duration_seconds",
        "original_duration_seconds",
        "total_duration_removed_seconds",
        "total_ad_segments_removed",
        "post_title",
        "feed_title",
        "feed_id",
    ]
    removable = [name for name in drop_order if name in columns]
    if removable:
        with op.batch_alter_table("processing_job", schema=None) as batch_op:
            for column_name in removable:
                batch_op.drop_column(column_name)
