"""Add event_type to user_download

Revision ID: i6j7k8l9m0n1
Revises: h5i6j7k8l9m0
Create Date: 2026-01-08
"""

from alembic import op
import sqlalchemy as sa


revision = "i6j7k8l9m0n1"
down_revision = "h5i6j7k8l9m0"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("user_download", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("event_type", sa.String(length=20), nullable=True)
        )
        batch_op.create_index("ix_user_download_event_type", ["event_type"])
    
    # Backfill event_type from decision field for existing records
    op.execute("""
        UPDATE user_download 
        SET event_type = CASE 
            WHEN decision = 'SERVED_AUDIO' THEN 'AUDIO_DOWNLOAD'
            WHEN decision = 'TRIGGERED' THEN 'PROCESS_STARTED'
            WHEN decision IN ('NOT_READY_NO_TRIGGER', 'JOB_EXISTS', 'COOLDOWN_ACTIVE') THEN 'FAILED'
            ELSE 'AUDIO_DOWNLOAD'
        END
        WHERE event_type IS NULL
    """)


def downgrade():
    with op.batch_alter_table("user_download", schema=None) as batch_op:
        batch_op.drop_index("ix_user_download_event_type")
        batch_op.drop_column("event_type")
