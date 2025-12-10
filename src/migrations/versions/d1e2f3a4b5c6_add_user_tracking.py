"""add_user_tracking

Revision ID: d1e2f3a4b5c6
Revises: 91ff431c832e
Create Date: 2025-12-10

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "d1e2f3a4b5c6"
down_revision = "608e0b27fcda"
branch_labels = None
depends_on = None


def upgrade():
    # Create user_download table for tracking downloads per user
    op.create_table(
        "user_download",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("post_id", sa.Integer(), nullable=False),
        sa.Column("downloaded_at", sa.DateTime(), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=True),
        sa.Column("is_processed", sa.Boolean(), nullable=True, default=True),
        sa.ForeignKeyConstraint(["post_id"], ["post.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_download_user_id", "user_download", ["user_id"])
    op.create_index("ix_user_download_post_id", "user_download", ["post_id"])
    op.create_index("ix_user_download_user_date", "user_download", ["user_id", "downloaded_at"])

    # Add triggered_by_user_id to processing_job table
    with op.batch_alter_table("processing_job", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("triggered_by_user_id", sa.Integer(), nullable=True)
        )
        batch_op.create_index(
            "ix_processing_job_triggered_by_user_id", ["triggered_by_user_id"]
        )
        batch_op.create_foreign_key(
            "fk_processing_job_triggered_by_user_id",
            "users",
            ["triggered_by_user_id"],
            ["id"],
        )


def downgrade():
    # Remove triggered_by_user_id from processing_job
    with op.batch_alter_table("processing_job", schema=None) as batch_op:
        batch_op.drop_constraint("fk_processing_job_triggered_by_user_id", type_="foreignkey")
        batch_op.drop_index("ix_processing_job_triggered_by_user_id")
        batch_op.drop_column("triggered_by_user_id")

    # Drop user_download table
    op.drop_index("ix_user_download_user_date", table_name="user_download")
    op.drop_index("ix_user_download_post_id", table_name="user_download")
    op.drop_index("ix_user_download_user_id", table_name="user_download")
    op.drop_table("user_download")
