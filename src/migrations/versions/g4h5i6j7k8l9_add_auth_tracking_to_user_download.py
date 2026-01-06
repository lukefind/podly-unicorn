"""Add auth_type and decision columns to user_download for audit trail

Revision ID: g4h5i6j7k8l9
Revises: h5i6j7k8l9m0
Create Date: 2026-01-06
"""

from alembic import op
import sqlalchemy as sa


revision = "g4h5i6j7k8l9"
down_revision = "h5i6j7k8l9m0"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("user_download", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("auth_type", sa.String(length=20), nullable=True)
        )
        batch_op.add_column(
            sa.Column("decision", sa.String(length=30), nullable=True)
        )


def downgrade():
    with op.batch_alter_table("user_download", schema=None) as batch_op:
        batch_op.drop_column("decision")
        batch_op.drop_column("auth_type")
