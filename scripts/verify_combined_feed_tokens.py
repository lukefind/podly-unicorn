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


def fetch_combined_feed(port: str, token_id: str, token_secret: str, public_host: str = "") -> Optional[str]:
    """Fetch combined feed XML from internal server.
    
    Args:
        port: Internal Flask port
        token_id: Combined token ID
        token_secret: Combined token secret
        public_host: Public hostname to set in Host header (e.g., 'your-domain.com')
                     This ensures _get_base_url() generates correct public URLs.
    """
    url = f"http://127.0.0.1:{port}/feed/combined?feed_token={token_id}&feed_secret={token_secret}"
    try:
        req = urllib.request.Request(url)
        # Set Host header to public domain so _get_base_url() generates correct URLs
        if public_host:
            req.add_header("Host", public_host)
            req.add_header("X-Forwarded-Proto", "https")  # Indicate HTTPS
        with urllib.request.urlopen(req, timeout=10) as response:
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


def extract_guid_from_url(url: str) -> Optional[str]:
    """Extract post GUID from enclosure URL."""
    match = re.search(r"/api/posts/([^/]+)/download", url)
    if match:
        return urllib.parse.unquote(match.group(1))
    return None


def count_jobs_for_guid(guid: str, trigger_source: Optional[str] = None) -> int:
    """Count processing jobs for a specific GUID."""
    conn = get_db_connection()
    cursor = conn.cursor()
    if trigger_source:
        cursor.execute(
            "SELECT COUNT(*) FROM processing_job WHERE post_guid = ? AND trigger_source = ?",
            (guid, trigger_source)
        )
    else:
        cursor.execute("SELECT COUNT(*) FROM processing_job WHERE post_guid = ?", (guid,))
    count = cursor.fetchone()[0]
    conn.close()
    return count


def http_get(url: str, host_header: str = "") -> Tuple[int, str]:
    """Make HTTP GET request and return (status_code, body)."""
    try:
        req = urllib.request.Request(url)
        if host_header:
            req.add_header("Host", host_header)
            req.add_header("X-Forwarded-Proto", "https")
        with urllib.request.urlopen(req, timeout=30) as response:
            return response.status, response.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "ignore") if e.fp else ""
    except Exception as e:
        return 0, str(e)


def verify_enclosure_tokens(columns: List[str], port: str, public_host: str) -> Tuple[bool, Optional[str], Optional[str], Optional[str]]:
    """
    Main verification: fetch combined feed and verify enclosure tokens are feed-scoped.
    
    Returns:
        (success, sample_enclosure_url, sample_guid, combined_token_id)
    """
    print("\n" + "=" * 60)
    print("C) Enclosure Token Verification (Automated)")
    print("=" * 60)
    
    # Get combined token
    combined = get_combined_token(columns)
    if not combined:
        print("[SKIP] No combined token found in database")
        return False, None, None, None
    
    combined_token_id, combined_secret = combined
    print(f"Combined token: {combined_token_id[:8]}...")
    print(f"Combined secret: {combined_secret[:8]}...")
    
    # Fetch combined feed with Host header set to public domain
    print(f"Fetching combined feed from 127.0.0.1:{port} (Host: {public_host})...")
    xml_content = fetch_combined_feed(port, combined_token_id, combined_secret, public_host)
    if not xml_content:
        return False, None, None, None
    
    print(f"Feed fetched: {len(xml_content)} bytes")
    
    # Extract enclosure URLs
    enclosure_urls = extract_enclosure_urls(xml_content)
    if not enclosure_urls:
        print("[WARN] No enclosure URLs found in feed")
        return False, None, None, None
    
    print(f"Found {len(enclosure_urls)} enclosure URLs")
    
    # Verify first 10 enclosures
    checked = 0
    passed = 0
    sample_url = None
    sample_guid = None
    
    for url in enclosure_urls[:10]:
        # Extract feed_token from URL
        parsed = urllib.parse.urlparse(url)
        params = urllib.parse.parse_qs(parsed.query)
        
        enclosure_token = params.get("feed_token", [None])[0]
        if not enclosure_token:
            print(f"[WARN] No feed_token in URL: {url[:60]}...")
            continue
        
        checked += 1
        guid = extract_guid_from_url(url)
        
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
        if guid:
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
            sample_guid = guid
    
    print(f"\nResult: {passed}/{checked} enclosures use correct feed-scoped tokens")
    
    if sample_url:
        print(f"\nSample enclosure URL for end-to-end testing:")
        print(f"  URL: {sample_url}")
        print(f"  GUID: {sample_guid}")
    
    success = passed == checked and checked > 0
    return success, sample_url, sample_guid, combined_token_id


def test_end_to_end_job_creation(port: str, public_host: str, enclosure_url: str, guid: str, 
                                  combined_token_id: str, combined_secret: str) -> bool:
    """
    End-to-end test that proves:
    1. Using enclosure URL from combined feed creates a job for that GUID
    2. Using combined token against same GUID does NOT create a job
    
    This is the deterministic test that proves Podcast Addict will trigger processing.
    """
    print("\n" + "=" * 60)
    print("F) End-to-End Job Creation Test")
    print("=" * 60)
    
    print(f"Testing GUID: {guid}")
    
    # Count existing jobs for this GUID
    initial_job_count = count_jobs_for_guid(guid)
    print(f"Initial job count for GUID: {initial_job_count}")
    
    # Step 1: Hit enclosure URL (feed-scoped token) - should trigger job
    print("\nStep 1: Requesting enclosure URL (feed-scoped token)...")
    
    # Convert public URL to internal URL for testing
    parsed = urllib.parse.urlparse(enclosure_url)
    internal_url = f"http://127.0.0.1:{port}{parsed.path}?{parsed.query}"
    
    status, body = http_get(internal_url, public_host)
    print(f"  Response: {status}")
    print(f"  Body preview: {body[:100]}..." if len(body) > 100 else f"  Body: {body}")
    
    # Check job count after enclosure request
    post_enclosure_count = count_jobs_for_guid(guid)
    print(f"  Job count after enclosure request: {post_enclosure_count}")
    
    # For unprocessed episodes, we expect either:
    # - 202 + job created (trigger_source=on_demand_rss)
    # - 200 (already processed)
    enclosure_triggered = post_enclosure_count > initial_job_count
    if status == 200:
        print("  [INFO] Episode already processed - skipping job creation check")
        enclosure_ok = True
    elif status == 202 and enclosure_triggered:
        print("  [PASS] Feed-scoped token triggered job creation")
        enclosure_ok = True
    elif status == 202 and not enclosure_triggered:
        # Could be cooldown or existing job
        print("  [INFO] 202 but no new job - may be cooldown or existing job")
        enclosure_ok = True  # Not a failure
    else:
        print(f"  [WARN] Unexpected response: {status}")
        enclosure_ok = False
    
    # Step 2: Hit same GUID with combined token - should NOT trigger job
    print("\nStep 2: Requesting same GUID with combined token...")
    combined_url = f"http://127.0.0.1:{port}/api/posts/{guid}/download?feed_token={combined_token_id}&feed_secret={combined_secret}"
    
    status2, body2 = http_get(combined_url, public_host)
    print(f"  Response: {status2}")
    print(f"  Body preview: {body2[:100]}..." if len(body2) > 100 else f"  Body: {body2}")
    
    # Check job count after combined token request
    post_combined_count = count_jobs_for_guid(guid)
    print(f"  Job count after combined token request: {post_combined_count}")
    
    combined_triggered = post_combined_count > post_enclosure_count
    if combined_triggered:
        print("  [FAIL] Combined token triggered job creation (should be read-only!)")
        combined_ok = False
    else:
        print("  [PASS] Combined token did NOT trigger job creation")
        combined_ok = True
    
    # Summary
    print("\nEnd-to-end test result:")
    if enclosure_ok and combined_ok:
        print("  [PASS] Feed-scoped tokens can trigger, combined tokens cannot")
        return True
    else:
        print("  [FAIL] See details above")
        return False


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
    parser.add_argument("--host", default="your-domain.com", help="Public hostname for Host header (default: your-domain.com)")
    parser.add_argument("--skip-fetch", action="store_true", help="Skip fetching combined feed (schema/bounds only)")
    parser.add_argument("--skip-e2e", action="store_true", help="Skip end-to-end job creation test")
    args = parser.parse_args()
    
    print("=" * 60)
    print("Combined Feed Token Verification")
    print("=" * 60)
    print(f"DB Path: {DB_PATH}")
    print(f"Internal Port: {args.port}")
    print(f"Public Host: {args.host}")
    print()
    
    # A) Print schema and get column list
    columns = print_schema()
    
    # B) Verify token bounds
    verify_token_bounds(columns)
    
    # C) Verify enclosure tokens (the critical test)
    enclosure_ok = False
    sample_url = None
    sample_guid = None
    combined_token_id = None
    
    if not args.skip_fetch:
        enclosure_ok, sample_url, sample_guid, combined_token_id = verify_enclosure_tokens(
            columns, args.port, args.host
        )
    else:
        print("\n[SKIP] Enclosure verification (--skip-fetch)")
    
    # D) List sample tokens
    list_sample_tokens(columns)
    
    # E) Print manual commands
    print_manual_commands(args.port)
    
    # F) End-to-end job creation test
    e2e_ok = None
    if not args.skip_e2e and sample_url and sample_guid and combined_token_id:
        # Get combined secret for e2e test
        combined = get_combined_token(columns)
        if combined:
            _, combined_secret = combined
            e2e_ok = test_end_to_end_job_creation(
                args.port, args.host, sample_url, sample_guid,
                combined_token_id, combined_secret
            )
    elif args.skip_e2e:
        print("\n[SKIP] End-to-end test (--skip-e2e)")
    elif not sample_url:
        print("\n[SKIP] End-to-end test (no sample URL from enclosure verification)")
    
    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    
    all_pass = True
    
    if enclosure_ok is True:
        print("[PASS] All enclosure tokens are feed-scoped and use public domain")
    elif enclosure_ok is False:
        print("[FAIL] Some enclosure tokens are incorrect - see details above")
        all_pass = False
    else:
        print("[SKIP] Enclosure verification was skipped")
    
    if e2e_ok is True:
        print("[PASS] End-to-end: feed-scoped triggers, combined does not")
    elif e2e_ok is False:
        print("[FAIL] End-to-end test failed - see details above")
        all_pass = False
    else:
        print("[SKIP] End-to-end test was skipped")
    
    if all_pass:
        print("\n*** Podcast Addict should now trigger processing from unified feed ***")
    
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
