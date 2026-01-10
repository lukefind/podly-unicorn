"""Remove unique constraint from post.download_url

Some podcast feeds have episodes that share the same audio URL (trailers,
reruns, etc.). The guid column already ensures uniqueness per episode.

Revision ID: k8l9m0n1o2p3
Revises: j7k8l9m0n1o2
Create Date: 2026-01-10
"""

from alembic import op
import sqlalchemy as sa


revision = "k8l9m0n1o2p3"
down_revision = "j7k8l9m0n1o2"
branch_labels = None
depends_on = None


def upgrade():
    # SQLite doesn't support DROP CONSTRAINT directly, need to use batch mode
    # which recreates the table without the constraint
    with op.batch_alter_table("post", schema=None) as batch_op:
        batch_op.drop_constraint("uq_post_download_url", type_="unique")


def downgrade():
    with op.batch_alter_table("post", schema=None) as batch_op:
        batch_op.create_unique_constraint("uq_post_download_url", ["download_url"])
