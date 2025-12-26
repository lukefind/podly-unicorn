"""Add trigger_source to processing_job

Revision ID: h5i6j7k8l9m0
Revises: c7b8a9d0e1f2
Create Date: 2025-12-26
"""

from alembic import op
import sqlalchemy as sa


revision = "h5i6j7k8l9m0"
down_revision = "c7b8a9d0e1f2"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("processing_job", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("trigger_source", sa.String(length=50), nullable=True)
        )
        batch_op.create_index("ix_processing_job_trigger_source", ["trigger_source"])


def downgrade():
    with op.batch_alter_table("processing_job", schema=None) as batch_op:
        batch_op.drop_index("ix_processing_job_trigger_source")
        batch_op.drop_column("trigger_source")
