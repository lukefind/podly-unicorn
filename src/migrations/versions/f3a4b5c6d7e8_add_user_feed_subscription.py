"""Add user_feed_subscription table

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7
Create Date: 2025-12-11 16:45:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f3a4b5c6d7e8'
down_revision = 'e2f3a4b5c6d7'
branch_labels = None
depends_on = None


def upgrade():
    # Create user_feed_subscription table
    op.create_table('user_feed_subscription',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('feed_id', sa.Integer(), nullable=False),
        sa.Column('subscribed_at', sa.DateTime(), nullable=True),
        sa.Column('is_private', sa.Boolean(), nullable=False, server_default='0'),
        sa.ForeignKeyConstraint(['feed_id'], ['feed.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'feed_id', name='uq_user_feed_subscription')
    )
    
    # Create indexes for performance
    op.create_index('ix_user_feed_subscription_user_id', 'user_feed_subscription', ['user_id'])
    op.create_index('ix_user_feed_subscription_feed_id', 'user_feed_subscription', ['feed_id'])


def downgrade():
    op.drop_index('ix_user_feed_subscription_feed_id', table_name='user_feed_subscription')
    op.drop_index('ix_user_feed_subscription_user_id', table_name='user_feed_subscription')
    op.drop_table('user_feed_subscription')
