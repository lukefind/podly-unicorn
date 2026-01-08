"""Add feed_id to user_download and make post_id nullable

Revision ID: j7k8l9m0n1o2
Revises: i6j7k8l9m0n1
Create Date: 2026-01-08
"""

from alembic import op
import sqlalchemy as sa


revision = "j7k8l9m0n1o2"
down_revision = "i6j7k8l9m0n1"
branch_labels = None
depends_on = None


def upgrade():
    # Add feed_id column for feed-level events like RSS_READ
    with op.batch_alter_table("user_download", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("feed_id", sa.Integer(), nullable=True)
        )
        batch_op.create_index("ix_user_download_feed_id", ["feed_id"])
        batch_op.create_foreign_key(
            "fk_user_download_feed_id", "feed", ["feed_id"], ["id"]
        )
    
    # Note: post_id is already nullable=True in SQLite (it ignores NOT NULL in ALTER)
    # For new installs, the model already has nullable=True
    # Existing data all has post_id set, so no backfill needed


def downgrade():
    with op.batch_alter_table("user_download", schema=None) as batch_op:
        batch_op.drop_constraint("fk_user_download_feed_id", type_="foreignkey")
        batch_op.drop_index("ix_user_download_feed_id")
        batch_op.drop_column("feed_id")
