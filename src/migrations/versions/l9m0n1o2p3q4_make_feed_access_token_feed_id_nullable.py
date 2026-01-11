"""Make feed_access_token.feed_id nullable for combined feed tokens

Combined feed tokens don't belong to a specific feed, so feed_id must be nullable.

Revision ID: l9m0n1o2p3q4
Revises: k8l9m0n1o2p3
Create Date: 2026-01-11
"""

from alembic import op
import sqlalchemy as sa


revision = "l9m0n1o2p3q4"
down_revision = "k8l9m0n1o2p3"
branch_labels = None
depends_on = None


def upgrade():
    # SQLite doesn't support ALTER COLUMN, must recreate table
    # IMPORTANT: Use explicit column names to avoid data corruption
    
    conn = op.get_bind()
    
    # Create new table with feed_id nullable
    conn.execute(sa.text("""
        CREATE TABLE feed_access_token_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token_id VARCHAR(32) NOT NULL UNIQUE,
            token_hash VARCHAR(64) NOT NULL,
            token_secret VARCHAR(128),
            feed_id INTEGER,
            user_id INTEGER NOT NULL,
            created_at DATETIME NOT NULL,
            last_used_at DATETIME,
            revoked BOOLEAN NOT NULL DEFAULT 0,
            FOREIGN KEY (feed_id) REFERENCES feed(id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """))
    
    # Copy data with explicit column names
    conn.execute(sa.text("""
        INSERT INTO feed_access_token_new (
            id, token_id, token_hash, token_secret, feed_id,
            user_id, created_at, last_used_at, revoked
        )
        SELECT 
            id, token_id, token_hash, token_secret, feed_id,
            user_id, created_at, last_used_at, revoked
        FROM feed_access_token
    """))
    
    # Drop old table
    conn.execute(sa.text("DROP TABLE feed_access_token"))
    
    # Rename new table
    conn.execute(sa.text("ALTER TABLE feed_access_token_new RENAME TO feed_access_token"))
    
    # Recreate index
    conn.execute(sa.text("CREATE UNIQUE INDEX ix_feed_access_token_token_id ON feed_access_token(token_id)"))


def downgrade():
    # This would require deleting any rows with NULL feed_id first
    pass
