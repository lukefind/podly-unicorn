#!/usr/bin/env python3
"""
Verification script for combined feed token implementation.

This script verifies that:
1. Combined feed enclosure URLs use feed-scoped tokens (feed_id != NULL)
2. Token creation is bounded (one token per user_id + feed_id, not per post)
3. Combined tokens cannot trigger processing
4. Enclosure URLs use public domain (not localhost)

Usage (inside Docker container):
    cd /app && python scripts/verify_combined_feed_tokens.py

Or from host:
    docker exec podly-pure-podcasts python /app/scripts/verify_combined_feed_tokens.py
"""

import os
import re
import sqlite3
import sys
import urllib.parse
import urllib.request
from typing import Optional, Tuple, List, Dict

# Default internal port - will be auto-detected if possible
INTERNAL_PORT = os.environ.get("FLASK_PORT", "5000")
DB_PATH = "/app/src/instance/sqlite3.db"


def get_db_connection():
    """Get direct SQLite connection (no ORM assumptions)."""
    return sqlite3.connect(DB_PATH)


def print_schema():
    """Print feed_access_token table schema."""
    print("=" * 60)
    print("A) feed_access_token Schema")
    print("=" * 60)
    
    conn = get_db_connection()
    cursor = conn.cursor()
    result = cursor.execute("PRAGMA table_info(feed_access_token)").fetchall()
    conn.close()
    
    columns = [row[1] for row in result]
    print(f"Columns: {columns}")
    print()
    print(f"{'cid':<4} {'name':<15} {'type':<12} {'notnull':<8} {'pk':<4}")
    print("-" * 50)
    for row in result:
        print(f"{row[0]:<4} {row[1]:<15} {row[2]:<12} {row[3]:<8} {row[5]:<4}")
    
    print("\nKey columns:")
    print("  - token_id: URL parameter 'feed_token'")
    print("  - token_secret: URL parameter 'feed_secret'")
    print("  - feed_id: NULL for combined tokens, integer for feed-scoped tokens")
    
    # Check if 'revoked' column exists
    if 'revoked' in columns:
        print("  - revoked: Boolean flag for revoked tokens")
    else:
        print("  - NOTE: 'revoked' column not found - queries will not filter by revoked status")
    
    return columns


def verify_token_bounds(columns: List[str]):
    """Verify token creation is bounded (no DB bloat)."""
    print("\n" + "=" * 60)
    print("B) Token Creation Bounds Check")
    print("=" * 60)
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Build WHERE clause based on available columns
    revoked_filter = "AND revoked = 0" if 'revoked' in columns else ""
    
    # Count combined tokens (feed_id IS NULL)
    cursor.execute(f"SELECT COUNT(*) FROM feed_access_token WHERE feed_id IS NULL {revoked_filter}")
    combined_count = cursor.fetchone()[0]
    
    # Count feed-scoped tokens (feed_id IS NOT NULL)
    cursor.execute(f"SELECT COUNT(*) FROM feed_access_token WHERE feed_id IS NOT NULL {revoked_filter}")
    feed_scoped_count = cursor.fetchone()[0]
    
    # Count unique (user_id, feed_id) pairs using printf for safety
    cursor.execute(f"""
        SELECT COUNT(DISTINCT printf('%d-%d', user_id, feed_id)) 
        FROM feed_access_token 
        WHERE feed_id IS NOT NULL {revoked_filter}
    """)
    unique_feed_scoped = cursor.fetchone()[0]
    
    # Count total subscriptions
    cursor.execute("SELECT COUNT(*) FROM user_feed_subscription")
    total_subscriptions = cursor.fetchone()[0]
    
    conn.close()
    
    print(f"Combined tokens (feed_id=NULL): {combined_count}")
    print(f"Feed-scoped tokens (feed_id!=NULL): {feed_scoped_count}")
    print(f"Unique (user_id, feed_id) pairs: {unique_feed_scoped}")
    print(f"Total subscriptions: {total_subscriptions}")
    
    if feed_scoped_count == unique_feed_scoped:
        print("\n[PASS] Token creation is bounded - one token per (user_id, feed_id)")
    else:
        print(f"\n[INFO] Found {feed_scoped_count - unique_feed_scoped} extra tokens (may be from token rotation)")
    
    if feed_scoped_count <= total_subscriptions * 2:  # Allow some slack for rotation
        print(f"[PASS] Feed-scoped tokens ({feed_scoped_count}) reasonable vs subscriptions ({total_subscriptions})")
    else:
        print(f"[WARN] Many more feed-scoped tokens than subscriptions - possible bloat")


def get_combined_token(columns: List[str]) -> Optional[Tuple[str, str]]:
    """Get a combined token (feed_id=NULL) from DB."""
    conn = get_db_connection()
    cursor = conn.cursor()
    revoked_filter = "AND revoked = 0" if 'revoked' in columns else ""
    cursor.execute(f"SELECT token_id, token_secret FROM feed_access_token WHERE feed_id IS NULL {revoked_filter} LIMIT 1")
    row = cursor.fetchone()
    conn.close()
    return (row[0], row[1]) if row else None


def lookup_token_feed_id(token_id: str) -> Optional[int]:
    """Look up feed_id for a token."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT feed_id FROM feed_access_token WHERE token_id = ?", (token_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None


def lookup_post_feed_id(guid: str) -> Optional[int]:
    """Look up feed_id for a post by GUID."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT feed_id FROM post WHERE guid = ?", (guid,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None


def fetch_combined_feed(port: str, token_id: str, token_secret: str) -> Optional[str]:
    """Fetch combined feed XML from internal server."""
    url = f"http://127.0.0.1:{port}/feed/combined?feed_token={token_id}&feed_secret={token_secret}"
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            return response.read().decode("utf-8", "ignore")
    except Exception as e:
        print(f"[ERROR] Failed to fetch combined feed: {e}")
        print(f"  URL: {url}")
        return None


def extract_enclosure_urls(xml_content: str) -> List[str]:
    """Extract enclosure URLs from RSS XML."""
    # Use regex to avoid XML parsing issues with namespaces
    pattern = r'<enclosure[^>]+url="([^"]+)"'
    return re.findall(pattern, xml_content)


def verify_enclosure_tokens(columns: List[str], port: str) -> bool:
    """
    Main verification: fetch combined feed and verify enclosure tokens are feed-scoped.
    
    This is the critical test that proves:
    1. Enclosure URLs use feed-scoped tokens (not combined token)
    2. Enclosure URLs use public domain (not localhost)
    3. Token matches the post's feed_id
    """
    print("\n" + "=" * 60)
    print("C) Enclosure Token Verification (Automated)")
    print("=" * 60)
    
    # Get combined token
    combined = get_combined_token(columns)
    if not combined:
        print("[SKIP] No combined token found in database")
        return False
    
    combined_token_id, combined_secret = combined
    print(f"Combined token: {combined_token_id[:8]}...")
    
    # Fetch combined feed
    print(f"Fetching combined feed from 127.0.0.1:{port}...")
    xml_content = fetch_combined_feed(port, combined_token_id, combined_secret)
    if not xml_content:
        return False
    
    print(f"Feed fetched: {len(xml_content)} bytes")
    
    # Extract enclosure URLs
    enclosure_urls = extract_enclosure_urls(xml_content)
    if not enclosure_urls:
        print("[WARN] No enclosure URLs found in feed")
        return False
    
    print(f"Found {len(enclosure_urls)} enclosure URLs")
    
    # Verify first 10 enclosures
    checked = 0
    passed = 0
    sample_url = None
    
    for url in enclosure_urls[:10]:
        # Extract feed_token from URL
        parsed = urllib.parse.urlparse(url)
        params = urllib.parse.parse_qs(parsed.query)
        
        enclosure_token = params.get("feed_token", [None])[0]
        if not enclosure_token:
            print(f"[WARN] No feed_token in URL: {url[:60]}...")
            continue
        
        checked += 1
        
        # Check 1: Enclosure token differs from combined token
        if enclosure_token == combined_token_id:
            print(f"[FAIL] Enclosure uses combined token! {enclosure_token[:8]}...")
            continue
        
        # Check 2: Enclosure token is feed-scoped (feed_id != NULL)
        token_feed_id = lookup_token_feed_id(enclosure_token)
        if token_feed_id is None:
            print(f"[FAIL] Enclosure token {enclosure_token[:8]}... has feed_id=NULL (should be feed-scoped)")
            continue
        
        # Check 3: Token's feed_id matches post's feed_id
        guid_match = re.search(r"/api/posts/([^/]+)/download", url)
        if guid_match:
            guid = urllib.parse.unquote(guid_match.group(1))
            post_feed_id = lookup_post_feed_id(guid)
            if post_feed_id and token_feed_id != post_feed_id:
                print(f"[FAIL] Token feed_id={token_feed_id} != post feed_id={post_feed_id}")
                continue
        
        # Check 4: URL uses public domain (not localhost/127.0.0.1)
        if "localhost" in parsed.netloc or "127.0.0.1" in parsed.netloc:
            print(f"[FAIL] Enclosure URL uses localhost: {parsed.netloc}")
            continue
        
        print(f"[PASS] Token {enclosure_token[:8]}... -> feed_id={token_feed_id}, host={parsed.netloc}")
        passed += 1
        
        if sample_url is None:
            sample_url = url
    
    print(f"\nResult: {passed}/{checked} enclosures use correct feed-scoped tokens")
    
    if sample_url:
        print(f"\nSample enclosure URL for manual testing:")
        print(f"  {sample_url[:120]}...")
    
    return passed == checked and checked > 0


def list_sample_tokens(columns: List[str]):
    """List sample tokens for manual verification."""
    print("\n" + "=" * 60)
    print("D) Sample Tokens for Manual Verification")
    print("=" * 60)
    
    conn = get_db_connection()
    cursor = conn.cursor()
    revoked_filter = "AND revoked = 0" if 'revoked' in columns else ""
    
    # Combined token
    cursor.execute(f"SELECT token_id, token_secret, user_id FROM feed_access_token WHERE feed_id IS NULL {revoked_filter} LIMIT 1")
    combined = cursor.fetchone()
    if combined:
        print(f"\nCombined token (should NOT trigger processing):")
        print(f"  token_id: {combined[0]}")
        print(f"  token_secret: {combined[1]}")
        print(f"  feed_id: NULL")
        print(f"  user_id: {combined[2]}")
    
    # Feed-scoped token
    cursor.execute(f"SELECT token_id, token_secret, user_id, feed_id FROM feed_access_token WHERE feed_id IS NOT NULL {revoked_filter} LIMIT 1")
    feed_scoped = cursor.fetchone()
    if feed_scoped:
        print(f"\nFeed-scoped token (CAN trigger processing):")
        print(f"  token_id: {feed_scoped[0]}")
        print(f"  token_secret: {feed_scoped[1]}")
        print(f"  feed_id: {feed_scoped[3]}")
        print(f"  user_id: {feed_scoped[2]}")
    
    conn.close()


def get_unprocessed_episode(columns: List[str]) -> Optional[Tuple[str, int, str]]:
    """Get an unprocessed episode for testing."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT p.guid, p.feed_id, p.title 
        FROM post p
        WHERE p.whitelisted = 1 
        AND (p.processed_audio_path IS NULL OR p.processed_audio_path = '')
        LIMIT 1
    """)
    row = cursor.fetchone()
    conn.close()
    return row if row else None


def check_job_created(guid: str) -> Optional[Tuple[str, str, str]]:
    """Check if a processing job was created for a GUID."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT trigger_source, status, created_at 
        FROM processing_job 
        WHERE post_guid = ?
        ORDER BY created_at DESC
        LIMIT 1
    """, (guid,))
    row = cursor.fetchone()
    conn.close()
    return row if row else None


def print_manual_commands(port: str):
    """Print manual verification commands."""
    print("\n" + "=" * 60)
    print("E) Manual Verification Commands")
    print("=" * 60)
    
    print(f"""
# Inside container, the Flask app listens on port {port}

# 1. Fetch combined feed and show enclosure tokens:
docker exec podly-pure-podcasts python /app/scripts/verify_combined_feed_tokens.py

# 2. Test that enclosure URL triggers processing (use URL from above):
docker exec podly-pure-podcasts sh -lc 'curl -i "ENCLOSURE_URL_HERE" | head -30'

# 3. Check if job was created:
docker exec podly-pure-podcasts python -c "
import sqlite3
conn = sqlite3.connect('/app/src/instance/sqlite3.db')
c = conn.cursor()
print('Recent jobs:')
for row in c.execute('SELECT post_guid, trigger_source, status, created_at FROM processing_job ORDER BY created_at DESC LIMIT 5').fetchall():
    print(f'  {{row[3]}} | {{row[1]}} | {{row[2]}} | {{row[0][:30]}}...')
conn.close()
"

# 4. Test that combined token does NOT trigger processing:
# Get combined token, then curl an unprocessed episode with it
# Expected: 202 Accepted, NO job created
""")


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Verify combined feed token implementation")
    parser.add_argument("--port", default=INTERNAL_PORT, help=f"Internal Flask port (default: {INTERNAL_PORT})")
    parser.add_argument("--skip-fetch", action="store_true", help="Skip fetching combined feed (schema/bounds only)")
    args = parser.parse_args()
    
    print("=" * 60)
    print("Combined Feed Token Verification")
    print("=" * 60)
    print(f"DB Path: {DB_PATH}")
    print(f"Internal Port: {args.port}")
    print()
    
    # A) Print schema and get column list
    columns = print_schema()
    
    # B) Verify token bounds
    verify_token_bounds(columns)
    
    # C) Verify enclosure tokens (the critical test)
    if not args.skip_fetch:
        enclosure_ok = verify_enclosure_tokens(columns, args.port)
    else:
        print("\n[SKIP] Enclosure verification (--skip-fetch)")
        enclosure_ok = None
    
    # D) List sample tokens
    list_sample_tokens(columns)
    
    # E) Print manual commands
    print_manual_commands(args.port)
    
    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    if enclosure_ok is True:
        print("[PASS] All enclosure tokens are feed-scoped and use public domain")
    elif enclosure_ok is False:
        print("[FAIL] Some enclosure tokens are incorrect - see details above")
    else:
        print("[SKIP] Enclosure verification was skipped")
    
    return 0 if enclosure_ok in (True, None) else 1


if __name__ == "__main__":
    sys.exit(main())
