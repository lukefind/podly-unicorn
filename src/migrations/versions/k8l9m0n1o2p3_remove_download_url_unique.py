"""Remove unique constraint from post.download_url

Some podcast feeds have episodes that share the same audio URL (trailers,
reruns, etc.). The guid column already ensures uniqueness per episode.

Revision ID: k8l9m0n1o2p3
Revises: j7k8l9m0n1o2
Create Date: 2026-01-10
"""

from alembic import op
import sqlalchemy as sa


revision = "k8l9m0n1o2p3"
down_revision = "j7k8l9m0n1o2"
branch_labels = None
depends_on = None


def upgrade():
    # SQLite doesn't support ALTER COLUMN or DROP CONSTRAINT directly.
    # We need to recreate the table without the unique constraint on download_url.
    # The batch_alter_table with recreate="always" handles this by:
    # 1. Creating a new table with the desired schema
    # 2. Copying data from old table
    # 3. Dropping old table
    # 4. Renaming new table
    #
    # Since we can't easily drop an unnamed constraint, we use raw SQL to recreate.
    
    # Get connection for raw SQL
    conn = op.get_bind()
    
    # Create new table without unique constraint on download_url
    conn.execute(sa.text("""
        CREATE TABLE post_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            feed_id INTEGER NOT NULL,
            guid TEXT NOT NULL UNIQUE,
            download_url TEXT NOT NULL,
            title TEXT NOT NULL,
            unprocessed_audio_path TEXT,
            processed_audio_path TEXT,
            description TEXT,
            release_date DATETIME,
            duration INTEGER,
            whitelisted BOOLEAN NOT NULL DEFAULT 0,
            image_url TEXT,
            download_count INTEGER DEFAULT 0,
            processed_with_preset_id INTEGER,
            FOREIGN KEY (feed_id) REFERENCES feed(id),
            FOREIGN KEY (processed_with_preset_id) REFERENCES prompt_preset(id)
        )
    """))
    
    # Copy data
    conn.execute(sa.text("""
        INSERT INTO post_new SELECT * FROM post
    """))
    
    # Drop old table
    conn.execute(sa.text("DROP TABLE post"))
    
    # Rename new table
    conn.execute(sa.text("ALTER TABLE post_new RENAME TO post"))
    
    # Recreate index on feed_id
    conn.execute(sa.text("CREATE INDEX ix_post_feed_id ON post(feed_id)"))


def downgrade():
    # Add back the unique constraint - would require similar table recreation
    pass
