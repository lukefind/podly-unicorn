"""Add auto_download_new_episodes to user_feed_subscription

Revision ID: a1b2c3d4e5f6
Revises: f3a4b5c6d7e8
Create Date: 2025-12-12

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f6"
down_revision = "f3a4b5c6d7e8"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("user_feed_subscription", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "auto_download_new_episodes",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            )
        )


def downgrade():
    with op.batch_alter_table("user_feed_subscription", schema=None) as batch_op:
        batch_op.drop_column("auto_download_new_episodes")
