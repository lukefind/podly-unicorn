"""Add llm_key_profile table for encrypted saved API keys

Revision ID: m0n1o2p3q4r5
Revises: l9m0n1o2p3q4
Create Date: 2026-03-02
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "m0n1o2p3q4r5"
down_revision = "l9m0n1o2p3q4"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "llm_key_profile" in existing_tables:
        return

    op.create_table(
        "llm_key_profile",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False, server_default="custom"),
        sa.Column("encrypted_api_key", sa.Text(), nullable=False),
        sa.Column("api_key_preview", sa.String(length=64), nullable=False),
        sa.Column("openai_base_url", sa.Text(), nullable=True),
        sa.Column("default_model", sa.Text(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "llm_key_profile" in existing_tables:
        op.drop_table("llm_key_profile")
