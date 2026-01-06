# Combined Feed Fix - Test Plan

This document provides test commands to verify the fix for the combined/unified feed triggering unwanted processing jobs.

## Summary of Fix

**Problem:** Combined feed token (unified feed) was triggering processing jobs for all episodes across all feeds, causing expensive unwanted processing.

**Solution:** 
- Combined feed tokens (`feed_id=NULL`) are now READ-ONLY
- They can serve processed audio but CANNOT trigger processing
- Only feed-scoped tokens (`feed_id=<specific_id>`) or session auth can trigger processing

---

## Prerequisites

1. Deploy the fix:
```bash
git pull && docker build -t podly-unicorn . && docker restart podly-pure-podcasts
```

2. Get test tokens from the database:
```bash
# Get a combined feed token (feed_id IS NULL)
docker exec podly-pure-podcasts python -c "
import sqlite3
conn = sqlite3.connect('/app/src/instance/sqlite3.db')
cursor = conn.cursor()
cursor.execute('''
    SELECT token_id, token_secret, user_id, feed_id 
    FROM feed_access_token 
    WHERE feed_id IS NULL AND revoked = 0
    LIMIT 1
''')
row = cursor.fetchone()
if row:
    print(f'COMBINED TOKEN: feed_token={row[0]}&feed_secret={row[1]} (user_id={row[2]}, feed_id=NULL)')
else:
    print('No combined token found')
conn.close()
"

# Get a feed-scoped token
docker exec podly-pure-podcasts python -c "
import sqlite3
conn = sqlite3.connect('/app/src/instance/sqlite3.db')
cursor = conn.cursor()
cursor.execute('''
    SELECT token_id, token_secret, user_id, feed_id 
    FROM feed_access_token 
    WHERE feed_id IS NOT NULL AND revoked = 0
    LIMIT 1
''')
row = cursor.fetchone()
if row:
    print(f'FEED-SCOPED TOKEN: feed_token={row[0]}&feed_secret={row[1]} (user_id={row[2]}, feed_id={row[3]})')
else:
    print('No feed-scoped token found')
conn.close()
"
```

3. Get an unprocessed episode GUID:
```bash
docker exec podly-pure-podcasts python -c "
import sqlite3
conn = sqlite3.connect('/app/src/instance/sqlite3.db')
cursor = conn.cursor()
cursor.execute('''
    SELECT p.guid, p.feed_id, p.title, f.title as feed_title
    FROM post p
    JOIN feed f ON p.feed_id = f.id
    WHERE p.whitelisted = 1 
    AND (p.processed_audio_path IS NULL OR p.processed_audio_path = '')
    LIMIT 3
''')
for row in cursor.fetchall():
    print(f'GUID: {row[0][:40]}... feed_id={row[1]} ({row[3]})')
conn.close()
"
```

---

## Test Cases

### Test 1: Combined Token Does NOT Trigger Processing

**Expected:** Returns 202 with `Retry-After: 3600`, NO job created

```bash
# Replace with actual values from prerequisites
COMBINED_TOKEN="feed_token=XXX&feed_secret=YYY"
EPISODE_GUID="your-unprocessed-episode-guid"
SERVER="https://your-server.com"

# Make the request
curl -v "${SERVER}/api/posts/${EPISODE_GUID}/download?${COMBINED_TOKEN}"
```

**Verify:**
1. Response is `202 Accepted`
2. `Retry-After` header is `300`
3. Body contains "Episode not yet processed"
4. Check logs for `COMBINED_TOKEN_NO_TRIGGER`:
```bash
docker logs podly-pure-podcasts 2>&1 | grep "DOWNLOAD_DECISION" | tail -5
```
5. Verify NO new job was created:
```bash
docker exec podly-pure-podcasts python -c "
import sqlite3
conn = sqlite3.connect('/app/src/instance/sqlite3.db')
cursor = conn.cursor()
cursor.execute('''
    SELECT id, post_guid, status, trigger_source, created_at
    FROM processing_job
    ORDER BY created_at DESC
    LIMIT 5
''')
for row in cursor.fetchall():
    print(f'{row[4]} | {row[0][:8]}... | {row[2]} | {row[3]} | {row[1][:20]}...')
conn.close()
"
```
6. Verify attempt was recorded in `user_download` with `decision=NOT_READY_NO_TRIGGER`:
```bash
docker exec podly-pure-podcasts python -c "
import sqlite3
conn = sqlite3.connect('/app/src/instance/sqlite3.db')
cursor = conn.cursor()
cursor.execute('''
    SELECT downloaded_at, auth_type, decision, post_id
    FROM user_download
    ORDER BY downloaded_at DESC
    LIMIT 5
''')
for row in cursor.fetchall():
    print(f'{row[0]} | auth={row[1]} | decision={row[2]} | post_id={row[3]}')
conn.close()
"
```

---

### Test 2: Feed-Scoped Token DOES Trigger Processing

**Expected:** Returns 202 with `Retry-After: 120`, job IS created

```bash
# Replace with actual values - MUST use a GUID from the same feed_id as the token
FEED_SCOPED_TOKEN="feed_token=XXX&feed_secret=YYY"
EPISODE_GUID="guid-from-matching-feed"
SERVER="https://your-server.com"

# Make the request
curl -v "${SERVER}/api/posts/${EPISODE_GUID}/download?${FEED_SCOPED_TOKEN}"
```

**Verify:**
1. Response is `202 Accepted`
2. `Retry-After` header is `120`
3. Body contains "Processing started"
4. Check logs for `TRIGGER_PROCESSING`:
```bash
docker logs podly-pure-podcasts 2>&1 | grep "DOWNLOAD_DECISION" | tail -5
```
5. Verify job WAS created with `trigger_source=on_demand_rss`:
```bash
docker exec podly-pure-podcasts python -c "
import sqlite3
conn = sqlite3.connect('/app/src/instance/sqlite3.db')
cursor = conn.cursor()
cursor.execute('''
    SELECT id, post_guid, status, trigger_source, created_at
    FROM processing_job
    WHERE trigger_source = 'on_demand_rss'
    ORDER BY created_at DESC
    LIMIT 5
''')
for row in cursor.fetchall():
    print(f'{row[4]} | {row[0][:8]}... | {row[2]} | {row[3]} | {row[1][:20]}...')
conn.close()
"
```

---

### Test 3: Duplicate Requests Do NOT Create Duplicate Jobs

**Expected:** Second request returns 202 with `JOB_EXISTS`, no new job

```bash
# Use same feed-scoped token and GUID as Test 2
# Make the same request again immediately
curl -v "${SERVER}/api/posts/${EPISODE_GUID}/download?${FEED_SCOPED_TOKEN}"
```

**Verify:**
1. Response is `202 Accepted`
2. Check logs for `JOB_EXISTS`:
```bash
docker logs podly-pure-podcasts 2>&1 | grep "DOWNLOAD_DECISION" | tail -5
```
3. Verify only ONE job exists for that GUID:
```bash
docker exec podly-pure-podcasts python -c "
import sqlite3
conn = sqlite3.connect('/app/src/instance/sqlite3.db')
cursor = conn.cursor()
cursor.execute('''
    SELECT COUNT(*) FROM processing_job
    WHERE post_guid = 'YOUR_GUID_HERE'
    AND status IN ('pending', 'running')
''')
print(f'Active jobs for GUID: {cursor.fetchone()[0]}')
conn.close()
"
```

---

### Test 4: HEAD Request Returns 204 (No Trigger)

**Expected:** Returns 204, no job created

```bash
curl -I "${SERVER}/api/posts/${EPISODE_GUID}/download?${FEED_SCOPED_TOKEN}"
```

**Verify:**
1. Response is `204 No Content`
2. Check logs for `HEAD_PROBE`:
```bash
docker logs podly-pure-podcasts 2>&1 | grep "DOWNLOAD_DECISION" | tail -5
```

---

### Test 5: Processed Audio is Served (Both Token Types)

**Expected:** Both combined and feed-scoped tokens can download processed audio

```bash
# Get a processed episode GUID
docker exec podly-pure-podcasts python -c "
import sqlite3
conn = sqlite3.connect('/app/src/instance/sqlite3.db')
cursor = conn.cursor()
cursor.execute('''
    SELECT guid, feed_id, title FROM post
    WHERE processed_audio_path IS NOT NULL 
    AND processed_audio_path != ''
    LIMIT 1
''')
row = cursor.fetchone()
if row:
    print(f'PROCESSED GUID: {row[0]} (feed_id={row[1]})')
conn.close()
"

# Test with combined token
curl -I "${SERVER}/api/posts/${PROCESSED_GUID}/download?${COMBINED_TOKEN}"
# Should return 200 OK with Content-Type: audio/mpeg

# Test with feed-scoped token
curl -I "${SERVER}/api/posts/${PROCESSED_GUID}/download?${FEED_SCOPED_TOKEN}"
# Should return 200 OK with Content-Type: audio/mpeg
```

---

### Test 6: Cooldown Persists Across Restart

**Expected:** Cooldown is database-backed and survives restart

```bash
# 1. Trigger processing with feed-scoped token (creates job)
curl -v "${SERVER}/api/posts/${EPISODE_GUID}/download?${FEED_SCOPED_TOKEN}"

# 2. Cancel the job (so it's not pending/running)
docker exec podly-pure-podcasts python -c "
import sqlite3
conn = sqlite3.connect('/app/src/instance/sqlite3.db')
cursor = conn.cursor()
cursor.execute('''
    UPDATE processing_job SET status = 'cancelled'
    WHERE post_guid = 'YOUR_GUID_HERE' AND status IN ('pending', 'running')
''')
conn.commit()
print(f'Cancelled {cursor.rowcount} jobs')
conn.close()
"

# 3. Restart the container
docker restart podly-pure-podcasts

# 4. Try to trigger again (should hit cooldown)
curl -v "${SERVER}/api/posts/${EPISODE_GUID}/download?${FEED_SCOPED_TOKEN}"
# Should return 202 with COOLDOWN_ACTIVE in logs
```

---

## Log Analysis

Check the diagnostic logs to understand what's happening:

```bash
# All download requests
docker logs podly-pure-podcasts 2>&1 | grep "DOWNLOAD_REQUEST" | tail -20

# All download decisions
docker logs podly-pure-podcasts 2>&1 | grep "DOWNLOAD_DECISION" | tail -20

# Filter by auth type
docker logs podly-pure-podcasts 2>&1 | grep "auth_type=combined" | tail -10
docker logs podly-pure-podcasts 2>&1 | grep "auth_type=feed_scoped" | tail -10

# Filter by decision
docker logs podly-pure-podcasts 2>&1 | grep "COMBINED_TOKEN_NO_TRIGGER" | tail -10
docker logs podly-pure-podcasts 2>&1 | grep "TRIGGER_PROCESSING" | tail -10
```

---

## Test 7: Combined Feed Enclosures Use Feed-Scoped Tokens

**Expected:** Enclosure URLs in combined feed use feed-scoped tokens (feed_id != NULL)

This is the key fix: when a podcast app fetches the combined feed, the enclosure URLs
contain feed-scoped tokens that CAN trigger processing, while the feed URL itself
uses a combined token that CANNOT trigger processing.

### Quick Verification

```bash
# Run the verification script
docker exec podly-pure-podcasts python /app/scripts/verify_combined_feed_tokens.py
```

### Manual Verification

```bash
# 1. Get your combined feed URL with tokens
docker exec podly-pure-podcasts python -c "
import sqlite3
conn = sqlite3.connect('/app/src/instance/sqlite3.db')
cursor = conn.cursor()
cursor.execute('''
    SELECT token_id, token_secret, user_id 
    FROM feed_access_token 
    WHERE feed_id IS NULL AND revoked = 0
    LIMIT 1
''')
row = cursor.fetchone()
if row:
    print(f'Combined feed URL:')
    print(f'  /feed/combined?feed_token={row[0]}&feed_secret={row[1]}')
conn.close()
"

# 2. Fetch combined feed and extract an enclosure URL
COMBINED_URL="https://your-server.com/feed/combined?feed_token=XXX&feed_secret=YYY"
curl -s "$COMBINED_URL" | grep -o 'url="[^"]*download[^"]*"' | head -1

# 3. Extract the feed_token from the enclosure URL and verify it's feed-scoped
# (The token in the enclosure should be DIFFERENT from the combined token)
ENCLOSURE_TOKEN="token_id_from_enclosure_url"

docker exec podly-pure-podcasts python -c "
import sqlite3
conn = sqlite3.connect('/app/src/instance/sqlite3.db')
cursor = conn.cursor()
cursor.execute('SELECT feed_id, user_id FROM feed_access_token WHERE token_id = ?', ('$ENCLOSURE_TOKEN',))
row = cursor.fetchone()
if row:
    feed_id, user_id = row
    if feed_id is not None:
        print(f'[PASS] Token is feed-scoped: feed_id={feed_id}, user_id={user_id}')
    else:
        print(f'[FAIL] Token is combined (feed_id=NULL) - enclosure should use feed-scoped token!')
else:
    print('Token not found')
conn.close()
"
```

### Token Bounds Check

Verify that token creation is bounded (no DB bloat from per-post tokens):

```bash
docker exec podly-pure-podcasts python -c "
import sqlite3
conn = sqlite3.connect('/app/src/instance/sqlite3.db')
cursor = conn.cursor()

# Count tokens by type
cursor.execute('SELECT COUNT(*) FROM feed_access_token WHERE feed_id IS NULL AND revoked = 0')
combined = cursor.fetchone()[0]

cursor.execute('SELECT COUNT(*) FROM feed_access_token WHERE feed_id IS NOT NULL AND revoked = 0')
feed_scoped = cursor.fetchone()[0]

# Count unique (user_id, feed_id) pairs
cursor.execute('SELECT COUNT(DISTINCT user_id || "-" || feed_id) FROM feed_access_token WHERE feed_id IS NOT NULL AND revoked = 0')
unique_pairs = cursor.fetchone()[0]

# Count subscriptions
cursor.execute('SELECT COUNT(*) FROM user_feed_subscription')
subscriptions = cursor.fetchone()[0]

print(f'Combined tokens: {combined}')
print(f'Feed-scoped tokens: {feed_scoped}')
print(f'Unique (user,feed) pairs: {unique_pairs}')
print(f'Total subscriptions: {subscriptions}')

if feed_scoped == unique_pairs:
    print('[PASS] One token per (user_id, feed_id) - no bloat')
else:
    print(f'[WARN] {feed_scoped - unique_pairs} duplicate tokens')

conn.close()
"
```

---

## feed_access_token Schema Reference

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | Primary key |
| `token_id` | VARCHAR(32) | URL parameter `feed_token` |
| `token_hash` | VARCHAR(64) | SHA-256 hash of secret |
| `token_secret` | VARCHAR(128) | URL parameter `feed_secret` |
| `feed_id` | INTEGER | NULL for combined tokens, integer for feed-scoped |
| `user_id` | INTEGER | Owner of the token |
| `created_at` | DATETIME | Creation timestamp |
| `last_used_at` | DATETIME | Last usage timestamp |
| `revoked` | BOOLEAN | Whether token is revoked |

**Key distinction:**
- `feed_id = NULL` → Combined token (read-only, cannot trigger processing)
- `feed_id = <int>` → Feed-scoped token (can trigger processing for that feed)

---

## Rollback

If the fix causes issues, revert to previous commit:

```bash
git revert HEAD
docker build -t podly-unicorn . && docker restart podly-pure-podcasts
```
