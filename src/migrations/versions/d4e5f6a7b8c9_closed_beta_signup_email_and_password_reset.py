"""Closed beta signup + email settings + password reset

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2025-12-13
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ---- users table additions ----
    users_cols = {col["name"] for col in inspector.get_columns("users")}

    with op.batch_alter_table("users", schema=None) as batch_op:
        if "email" not in users_cols:
            batch_op.add_column(sa.Column("email", sa.String(length=255), nullable=True))
        if "account_status" not in users_cols:
            batch_op.add_column(
                sa.Column(
                    "account_status",
                    sa.String(length=50),
                    nullable=False,
                    server_default="active",
                )
            )
        if "approved_at" not in users_cols:
            batch_op.add_column(sa.Column("approved_at", sa.DateTime(), nullable=True))
        if "approved_by_user_id" not in users_cols:
            batch_op.add_column(sa.Column("approved_by_user_id", sa.Integer(), nullable=True))

    # Indexes for users.email - use batch mode for SQLite compatibility
    inspector = sa.inspect(bind)
    existing_indexes = {ix["name"] for ix in inspector.get_indexes("users")}

    if "ix_users_email" not in existing_indexes:
        op.create_index("ix_users_email", "users", ["email"], unique=False)

    # Add unique constraint for users.email if missing - use batch mode for SQLite
    inspector = sa.inspect(bind)
    existing_uniques = {uc["name"] for uc in inspector.get_unique_constraints("users")}
    if "uq_users_email" not in existing_uniques:
        with op.batch_alter_table("users", schema=None) as batch_op:
            batch_op.create_unique_constraint("uq_users_email", ["email"])

    # ---- app_settings additions ----
    existing_tables = set(inspector.get_table_names())
    if "app_settings" in existing_tables:
        app_cols = {col["name"] for col in inspector.get_columns("app_settings")}
        with op.batch_alter_table("app_settings", schema=None) as batch_op:
            if "allow_signup" not in app_cols:
                batch_op.add_column(
                    sa.Column(
                        "allow_signup",
                        sa.Boolean(),
                        nullable=False,
                        server_default=sa.text("0"),
                    )
                )

    # ---- email_settings table ----
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())
    if "email_settings" not in existing_tables:
        op.create_table(
            "email_settings",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("smtp_host", sa.String(length=255), nullable=True),
            sa.Column("smtp_port", sa.Integer(), nullable=True),
            sa.Column("smtp_username", sa.String(length=255), nullable=True),
            sa.Column("smtp_password", sa.String(length=255), nullable=True),
            sa.Column("smtp_use_tls", sa.Boolean(), nullable=False, server_default=sa.text("1")),
            sa.Column("smtp_use_ssl", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column("from_email", sa.String(length=255), nullable=True),
            sa.Column("admin_notify_email", sa.String(length=255), nullable=True),
            sa.Column("app_base_url", sa.String(length=255), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.current_timestamp(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.current_timestamp(),
            ),
            sa.PrimaryKeyConstraint("id"),
        )

        # Seed singleton row
        op.execute(
            "INSERT INTO email_settings (id, smtp_use_tls, smtp_use_ssl) VALUES (1, 1, 0)"
        )

    # ---- password_reset_token table ----
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())
    if "password_reset_token" not in existing_tables:
        op.create_table(
            "password_reset_token",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("token_hash", sa.String(length=64), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("used_at", sa.DateTime(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.current_timestamp(),
            ),
        )
        op.create_index("ix_password_reset_token_user_id", "password_reset_token", ["user_id"], unique=False)
        op.create_index("ix_password_reset_token_token_hash", "password_reset_token", ["token_hash"], unique=True)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "password_reset_token" in existing_tables:
        op.drop_index("ix_password_reset_token_token_hash", table_name="password_reset_token")
        op.drop_index("ix_password_reset_token_user_id", table_name="password_reset_token")
        op.drop_table("password_reset_token")

    if "email_settings" in existing_tables:
        op.drop_table("email_settings")

    if "app_settings" in existing_tables:
        app_cols = {col["name"] for col in inspector.get_columns("app_settings")}
        if "allow_signup" in app_cols:
            with op.batch_alter_table("app_settings", schema=None) as batch_op:
                batch_op.drop_column("allow_signup")

    if "users" in existing_tables:
        users_cols = {col["name"] for col in inspector.get_columns("users")}

        # Drop email unique constraint/index if present
        uniques = {uc["name"] for uc in inspector.get_unique_constraints("users")}
        if "uq_users_email" in uniques:
            with op.batch_alter_table("users", schema=None) as batch_op:
                batch_op.drop_constraint("uq_users_email", type_="unique")

        indexes = {ix["name"] for ix in inspector.get_indexes("users")}
        if "ix_users_email" in indexes:
            op.drop_index("ix_users_email", table_name="users")

        with op.batch_alter_table("users", schema=None) as batch_op:
            if "approved_by_user_id" in users_cols:
                batch_op.drop_column("approved_by_user_id")
            if "approved_at" in users_cols:
                batch_op.drop_column("approved_at")
            if "account_status" in users_cols:
                batch_op.drop_column("account_status")
            if "email" in users_cols:
                batch_op.drop_column("email")
