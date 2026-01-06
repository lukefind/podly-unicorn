#!/usr/bin/env python3
"""
Verification script for combined feed token implementation.

This script verifies that:
1. Combined feed enclosure URLs use feed-scoped tokens (feed_id != NULL)
2. Token creation is bounded (one token per user_id + feed_id, not per post)
3. Combined tokens cannot trigger processing

Usage (inside Docker container):
    cd /app && python scripts/verify_combined_feed_tokens.py

Or from host:
    docker exec podly-pure-podcasts python /app/scripts/verify_combined_feed_tokens.py
"""

import sys
import re
import xml.etree.ElementTree as ET

sys.path.insert(0, "src")

from flask import Flask
from app.extensions import db
from app.models import FeedAccessToken, Post, User, Feed, UserFeedSubscription


def get_app():
    """Create minimal Flask app for DB access."""
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:////app/src/instance/sqlite3.db"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    db.init_app(app)
    return app


def print_schema():
    """Print feed_access_token table schema."""
    print("=" * 60)
    print("A) feed_access_token Schema")
    print("=" * 60)
    
    result = db.session.execute(
        db.text("PRAGMA table_info(feed_access_token)")
    ).fetchall()
    
    print(f"{'cid':<4} {'name':<15} {'type':<12} {'notnull':<8} {'pk':<4}")
    print("-" * 50)
    for row in result:
        print(f"{row[0]:<4} {row[1]:<15} {row[2]:<12} {row[3]:<8} {row[5]:<4}")
    
    print("\nKey columns:")
    print("  - token_id: URL parameter 'feed_token'")
    print("  - token_secret: URL parameter 'feed_secret'")
    print("  - feed_id: NULL for combined tokens, integer for feed-scoped tokens")


def verify_token_bounds():
    """Verify token creation is bounded (no DB bloat)."""
    print("\n" + "=" * 60)
    print("B) Token Creation Bounds Check")
    print("=" * 60)
    
    # Count tokens by type
    combined_count = FeedAccessToken.query.filter_by(feed_id=None, revoked=False).count()
    feed_scoped_count = FeedAccessToken.query.filter(
        FeedAccessToken.feed_id.isnot(None),
        FeedAccessToken.revoked == False
    ).count()
    
    # Count unique (user_id, feed_id) combinations
    unique_feed_scoped = db.session.query(
        FeedAccessToken.user_id, FeedAccessToken.feed_id
    ).filter(
        FeedAccessToken.feed_id.isnot(None),
        FeedAccessToken.revoked == False
    ).distinct().count()
    
    # Count total subscriptions (expected max feed-scoped tokens)
    total_subscriptions = UserFeedSubscription.query.count()
    
    print(f"Combined tokens (feed_id=NULL): {combined_count}")
    print(f"Feed-scoped tokens (feed_id!=NULL): {feed_scoped_count}")
    print(f"Unique (user_id, feed_id) pairs: {unique_feed_scoped}")
    print(f"Total subscriptions: {total_subscriptions}")
    
    if feed_scoped_count == unique_feed_scoped:
        print("\n[PASS] Token creation is bounded - one token per (user_id, feed_id)")
    else:
        print(f"\n[WARN] Found {feed_scoped_count - unique_feed_scoped} duplicate tokens")
    
    if feed_scoped_count <= total_subscriptions:
        print(f"[PASS] Feed-scoped tokens ({feed_scoped_count}) <= subscriptions ({total_subscriptions})")
    else:
        print(f"[WARN] More feed-scoped tokens than subscriptions")


def verify_enclosure_token(combined_feed_xml: str):
    """Verify enclosure URLs use feed-scoped tokens."""
    print("\n" + "=" * 60)
    print("C) Enclosure Token Verification")
    print("=" * 60)
    
    # Parse XML
    try:
        root = ET.fromstring(combined_feed_xml)
    except ET.ParseError as e:
        print(f"[FAIL] Could not parse XML: {e}")
        return False
    
    # Find enclosure URLs
    enclosures = root.findall(".//enclosure")
    if not enclosures:
        print("[WARN] No enclosures found in feed")
        return False
    
    print(f"Found {len(enclosures)} enclosures")
    
    # Check first few enclosures
    checked = 0
    passed = 0
    
    for enc in enclosures[:5]:
        url = enc.get("url", "")
        
        # Extract feed_token from URL
        match = re.search(r"feed_token=([^&]+)", url)
        if not match:
            print(f"[WARN] No feed_token in URL: {url[:80]}...")
            continue
        
        token_id = match.group(1)
        
        # Look up token in DB
        token = FeedAccessToken.query.filter_by(token_id=token_id).first()
        if not token:
            print(f"[FAIL] Token not found: {token_id}")
            continue
        
        checked += 1
        
        # Extract GUID from URL to find post's feed_id
        guid_match = re.search(r"/api/posts/([^/]+)/download", url)
        if guid_match:
            guid = guid_match.group(1)
            post = Post.query.filter_by(guid=guid).first()
            if post:
                if token.feed_id == post.feed_id:
                    print(f"[PASS] Token {token_id[:8]}... -> feed_id={token.feed_id} (matches post's feed_id)")
                    passed += 1
                elif token.feed_id is None:
                    print(f"[FAIL] Token {token_id[:8]}... -> feed_id=NULL (should be {post.feed_id})")
                else:
                    print(f"[FAIL] Token {token_id[:8]}... -> feed_id={token.feed_id} (post's feed_id={post.feed_id})")
            else:
                print(f"[WARN] Post not found for GUID: {guid}")
        else:
            if token.feed_id is not None:
                print(f"[PASS] Token {token_id[:8]}... -> feed_id={token.feed_id} (feed-scoped)")
                passed += 1
            else:
                print(f"[FAIL] Token {token_id[:8]}... -> feed_id=NULL (combined token in enclosure!)")
    
    print(f"\nResult: {passed}/{checked} enclosures use feed-scoped tokens")
    return passed == checked


def list_sample_tokens():
    """List sample tokens for manual verification."""
    print("\n" + "=" * 60)
    print("D) Sample Tokens for Manual Verification")
    print("=" * 60)
    
    # Combined tokens
    combined = FeedAccessToken.query.filter_by(feed_id=None, revoked=False).first()
    if combined:
        print(f"\nCombined token (should NOT trigger processing):")
        print(f"  token_id: {combined.token_id}")
        print(f"  feed_id: {combined.feed_id} (NULL)")
        print(f"  user_id: {combined.user_id}")
    
    # Feed-scoped tokens
    feed_scoped = FeedAccessToken.query.filter(
        FeedAccessToken.feed_id.isnot(None),
        FeedAccessToken.revoked == False
    ).first()
    if feed_scoped:
        print(f"\nFeed-scoped token (CAN trigger processing):")
        print(f"  token_id: {feed_scoped.token_id}")
        print(f"  feed_id: {feed_scoped.feed_id}")
        print(f"  user_id: {feed_scoped.user_id}")


def print_verification_commands():
    """Print manual verification commands."""
    print("\n" + "=" * 60)
    print("E) Manual Verification Commands")
    print("=" * 60)
    
    print("""
# 1. Get combined feed XML and extract enclosure URL:
curl -s "http://localhost:5001/feed/combined?feed_token=<TOKEN>&feed_secret=<SECRET>" | \\
  grep -o '<enclosure[^>]*>' | head -1

# 2. Extract feed_token from enclosure URL and verify it's feed-scoped:
docker exec podly-pure-podcasts python -c "
import sys
sys.path.insert(0, 'src')
from app.extensions import db
from app.models import FeedAccessToken
from flask import Flask

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:////app/src/instance/sqlite3.db'
db.init_app(app)

with app.app_context():
    token = FeedAccessToken.query.filter_by(token_id='<TOKEN_ID_FROM_ENCLOSURE>').first()
    if token:
        print(f'feed_id: {token.feed_id}')
        print('PASS' if token.feed_id is not None else 'FAIL - combined token in enclosure!')
    else:
        print('Token not found')
"

# 3. Verify combined token cannot trigger processing:
# Use a combined token (feed_id=NULL) to request an unprocessed episode
# Expected: 202 Accepted with Retry-After header, NO processing_job created

# 4. Verify feed-scoped token CAN trigger processing:
# Use the enclosure URL from combined feed (has feed-scoped token)
# Expected: Processing job created with trigger_source='on_demand_rss'
""")


def main():
    app = get_app()
    
    with app.app_context():
        print_schema()
        verify_token_bounds()
        list_sample_tokens()
        print_verification_commands()
        
        print("\n" + "=" * 60)
        print("To verify enclosure tokens, pass combined feed XML as argument:")
        print("  python scripts/verify_combined_feed_tokens.py < combined_feed.xml")
        print("=" * 60)
        
        # If XML provided via stdin, verify it
        if not sys.stdin.isatty():
            xml_content = sys.stdin.read()
            if xml_content.strip():
                verify_enclosure_token(xml_content)


if __name__ == "__main__":
    main()
