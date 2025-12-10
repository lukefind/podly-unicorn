"""Add processed_with_preset_id to post table

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2025-01-10

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "e2f3a4b5c6d7"
down_revision = "d1e2f3a4b5c6"
branch_labels = None
depends_on = None


def upgrade():
    # Add processed_with_preset_id column to post table
    with op.batch_alter_table("post", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("processed_with_preset_id", sa.Integer(), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_post_processed_with_preset_id",
            "prompt_preset",
            ["processed_with_preset_id"],
            ["id"],
        )


def downgrade():
    with op.batch_alter_table("post", schema=None) as batch_op:
        batch_op.drop_constraint("fk_post_processed_with_preset_id", type_="foreignkey")
        batch_op.drop_column("processed_with_preset_id")
