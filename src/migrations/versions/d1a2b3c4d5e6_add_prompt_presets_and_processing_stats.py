"""Add prompt presets and processing statistics

Revision ID: d1a2b3c4d5e6
Revises: 608e0b27fcda
Create Date: 2025-12-10 00:35:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd1a2b3c4d5e6'
down_revision = '608e0b27fcda'
branch_labels = None
depends_on = None


def upgrade():
    # Create prompt_preset table
    op.create_table(
        'prompt_preset',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('aggressiveness', sa.String(length=20), nullable=False, server_default='balanced'),
        sa.Column('system_prompt', sa.Text(), nullable=False),
        sa.Column('user_prompt_template', sa.Text(), nullable=False),
        sa.Column('min_confidence', sa.Float(), nullable=False, server_default='0.7'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('is_default', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name')
    )

    # Create processing_statistics table
    op.create_table(
        'processing_statistics',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('post_id', sa.Integer(), nullable=False),
        sa.Column('total_ad_segments_removed', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_duration_removed_seconds', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('original_duration_seconds', sa.Float(), nullable=False),
        sa.Column('processed_duration_seconds', sa.Float(), nullable=False),
        sa.Column('percentage_removed', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('prompt_preset_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['post_id'], ['post.id'], ),
        sa.ForeignKeyConstraint(['prompt_preset_id'], ['prompt_preset.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('post_id')
    )


def downgrade():
    op.drop_table('processing_statistics')
    op.drop_table('prompt_preset')
