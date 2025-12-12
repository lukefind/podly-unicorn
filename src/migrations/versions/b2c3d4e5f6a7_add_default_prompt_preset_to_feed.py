"""Add default_prompt_preset_id to feed

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2025-12-12

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("feed", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("default_prompt_preset_id", sa.Integer(), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_feed_default_prompt_preset_id",
            "prompt_preset",
            ["default_prompt_preset_id"],
            ["id"],
        )


def downgrade():
    with op.batch_alter_table("feed", schema=None) as batch_op:
        batch_op.drop_constraint("fk_feed_default_prompt_preset_id", type_="foreignkey")
        batch_op.drop_column("default_prompt_preset_id")
