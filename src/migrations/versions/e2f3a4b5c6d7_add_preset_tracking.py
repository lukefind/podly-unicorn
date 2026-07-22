"""Add preset tracking schema

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
    bind = op.get_bind()
    if "prompt_preset" not in sa.inspect(bind).get_table_names():
        op.create_table(
            "prompt_preset",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("name", sa.String(length=100), nullable=False, unique=True),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("aggressiveness", sa.String(length=20), nullable=False),
            sa.Column("system_prompt", sa.Text(), nullable=False),
            sa.Column("user_prompt_template", sa.Text(), nullable=False),
            sa.Column("min_confidence", sa.Float(), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column("is_default", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )

    if "processing_statistics" not in sa.inspect(bind).get_table_names():
        op.create_table(
            "processing_statistics",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("post_id", sa.Integer(), nullable=False, unique=True),
            sa.Column("total_ad_segments_removed", sa.Integer(), nullable=False),
            sa.Column("total_duration_removed_seconds", sa.Float(), nullable=False),
            sa.Column("original_duration_seconds", sa.Float(), nullable=False),
            sa.Column("processed_duration_seconds", sa.Float(), nullable=False),
            sa.Column("percentage_removed", sa.Float(), nullable=False),
            sa.Column("prompt_preset_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["post_id"], ["post.id"]),
            sa.ForeignKeyConstraint(["prompt_preset_id"], ["prompt_preset.id"]),
        )

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

    # Old releases could create these tables through the startup create_all()
    # fallback before Alembic reached this revision. There is no durable way to
    # distinguish those production tables from ones created here, even when
    # they are empty, so a downgrade intentionally leaves both tables in place
    # rather than risk deleting user presets or processing history.
