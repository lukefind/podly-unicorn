"""Add boundary refinement fields

Revision ID: n1o2p3q4r5s6
Revises: m0n1o2p3q4r5
Create Date: 2026-03-06
"""

from alembic import op
import sqlalchemy as sa


revision = "n1o2p3q4r5s6"
down_revision = "m0n1o2p3q4r5"
branch_labels = None
depends_on = None


def _column_names(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    post_columns = _column_names("post")
    with op.batch_alter_table("post", schema=None) as batch_op:
        if "refined_ad_boundaries" not in post_columns:
            batch_op.add_column(sa.Column("refined_ad_boundaries", sa.JSON(), nullable=True))
        if "refined_ad_boundaries_updated_at" not in post_columns:
            batch_op.add_column(
                sa.Column("refined_ad_boundaries_updated_at", sa.DateTime(), nullable=True)
            )

    llm_columns = _column_names("llm_settings")
    with op.batch_alter_table("llm_settings", schema=None) as batch_op:
        if "enable_boundary_refinement" not in llm_columns:
            batch_op.add_column(
                sa.Column(
                    "enable_boundary_refinement",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.true(),
                )
            )
        if "enable_word_level_boundary_refiner" not in llm_columns:
            batch_op.add_column(
                sa.Column(
                    "enable_word_level_boundary_refiner",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.false(),
                )
            )

def downgrade() -> None:
    llm_columns = _column_names("llm_settings")
    with op.batch_alter_table("llm_settings", schema=None) as batch_op:
        if "enable_word_level_boundary_refiner" in llm_columns:
            batch_op.drop_column("enable_word_level_boundary_refiner")
        if "enable_boundary_refinement" in llm_columns:
            batch_op.drop_column("enable_boundary_refinement")

    post_columns = _column_names("post")
    with op.batch_alter_table("post", schema=None) as batch_op:
        if "refined_ad_boundaries_updated_at" in post_columns:
            batch_op.drop_column("refined_ad_boundaries_updated_at")
        if "refined_ad_boundaries" in post_columns:
            batch_op.drop_column("refined_ad_boundaries")
