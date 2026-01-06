# Podly Unicorn - Job Trigger Audit Report

## Overview

This document audits all code paths that can trigger episode processing jobs in Podly Unicorn. The goal is to understand when and why jobs start, and identify potential issues causing unwanted automatic processing.

**Last Updated:** January 2026

---

## Current Implementation Status

| Component | Status | Notes |
|-----------|--------|-------|
| Enclosure URL | ✅ PASS | Points to `/api/posts/<guid>/download` with feed token |
| HTTP Semantics | ✅ PASS | HEAD→204, GET unprocessed→202+Retry-After |
| Separation of Concerns | ✅ PASS | `auto_download_new_episodes` only affects scheduled refresh |
| Cooldown Logic | ⚠️ IN-MEMORY | Lost on restart; should be database-backed |
| Job Idempotency | ⚠️ PARTIAL | Check-then-insert without locking; race window exists |

---

## 1. Entry Points That Trigger Processing Jobs

There are **5 distinct code paths** that call `start_post_processing()`:

### 1.1 Manual UI Process Button
**File:** `src/app/routes/post_routes.py`
**Endpoint:** `POST /api/posts/<guid>/process`
**Trigger Source:** `manual_ui`

**When triggered:** User clicks "Process" button in web UI.
**Expected behavior:** Always triggers processing. This is intentional.

---

### 1.2 Manual UI Reprocess Button
**File:** `src/app/routes/post_routes.py`
**Endpoint:** `POST /api/posts/<guid>/reprocess`
**Trigger Source:** `manual_reprocess`

**When triggered:** User clicks "Reprocess" button in web UI.
**Expected behavior:** Always triggers processing. This is intentional.

---

### 1.3 On-Demand RSS Download Request
**File:** `src/app/routes/post_routes.py`
**Endpoint:** `GET/HEAD /api/posts/<guid>/download`
**Trigger Source:** `on_demand_rss`

**When triggered:** Podcast app (Overcast, Pocket Casts, Apple Podcasts) requests download of an unprocessed episode.

**Current Logic (Two-Tier Trigger):**

#### Tier 1: HEAD = True Probe (Never Triggers)
- HTTP method `HEAD` → Return `204 No Content`
- No processing triggered

#### Tier 2: GET Can Trigger (With Cooldown)
- GET requests CAN trigger processing, even with small Range headers
- Podcast apps use Range requests for real downloads, not just probes
- 10-minute cooldown per GUID prevents trigger storms

**Decision Flow:**
1. **HEAD request?** → 204 (no trigger)
2. **Not authorized?** → 401 (no trigger)
3. **Job already pending/running?** → 202 + Retry-After (no new trigger)
4. **Within cooldown window?** → 202 + Retry-After (no new trigger)
5. **Otherwise** → Start job, return 202 + Retry-After

**Key Design Decisions:**
- `auto_download_new_episodes` does NOT gate on-demand processing
- That setting ONLY controls scheduled refresh auto-processing
- Any authorized user can trigger processing by downloading

---

### 1.4 Scheduled Feed Refresh (Background Job)
**File:** `src/app/jobs_manager.py` (lines 476-481)
**Trigger:** APScheduler runs `scheduled_refresh_all_feeds()` every N minutes
**Trigger Source:** `auto_feed_refresh`

```python
if auto_process_post_guids:
    for post_guid in auto_process_post_guids:
        self.start_post_processing(
            post_guid, priority="background",
            trigger_source="auto_feed_refresh"
        )
```

**When triggered:** Scheduled job runs every `background_update_interval_minute` (default: 30 minutes).

**Guard condition in `refresh_feed()` (src/app/feeds.py lines 198-203):**
```python
auto_download_enabled = (
    UserFeedSubscription.query.filter_by(
        feed_id=feed.id, auto_download_new_episodes=True
    ).count()
    > 0
)
```

Only returns GUIDs for processing if ANY user has `auto_download_new_episodes=True` for that feed.

**Expected behavior:**
- Only processes NEW episodes discovered during refresh
- Only for feeds where at least one subscriber has `auto_download_new_episodes=True`

---

### 1.5 Manual Single Feed Refresh
**File:** `src/app/routes/feed_routes.py` (lines 465-471)
**Endpoint:** `POST /api/feeds/<id>/refresh`
**Trigger Source:** `auto_feed_refresh`

```python
if auto_process_post_guids:
    manager = get_jobs_manager()
    for post_guid in auto_process_post_guids:
        manager.start_post_processing(
            post_guid, priority="background",
            trigger_source="auto_feed_refresh"
        )
```

**When triggered:** User clicks "Refresh feed" button in UI.
**Expected behavior:** Same as scheduled refresh - only processes new episodes if `auto_download_new_episodes=True`.

---

## 2. Code Paths That Do NOT Trigger Processing

### 2.1 GET /feed/<id> (RSS Feed Request)
**File:** `src/app/routes/feed_routes.py` (lines 288-303)

```python
@feed_bp.route("/feed/<int:f_id>", methods=["GET"])
def get_feed(f_id: int) -> Response:
    feed = Feed.query.get_or_404(f_id)
    try:
        refresh_feed(feed)  # <-- This CAN return GUIDs but they are IGNORED here
    except Exception as exc:
        logger.warning("Failed to refresh feed %s, serving cached data: %s", f_id, exc)
    xml_content = generate_feed_xml(feed)
    ...
```

**IMPORTANT:** This calls `refresh_feed()` which returns `auto_process_post_guids`, but the return value is **ignored**. No jobs are started from this endpoint.

However, `refresh_feed()` does:
1. Fetch upstream RSS
2. Create new Post records in database
3. Set `whitelisted=True` if `auto_download_enabled`

So new episodes appear in the feed, but processing is NOT triggered here.

### 2.2 GET /feed/combined (Combined Feed Request)
**File:** `src/app/routes/feed_routes.py` (lines 258-285)

Does NOT call `refresh_feed()` at all. Just generates XML from cached data.

### 2.3 enqueue_pending_jobs()
**File:** `src/app/jobs_manager.py` (lines 106-133)

This method does NOT create new jobs. The `_ensure_jobs_for_all_posts()` method (lines 135-142) explicitly returns 0:

```python
def _ensure_jobs_for_all_posts(self, run_id: Optional[str]) -> int:
    # Don't auto-create jobs - processing is triggered on-demand only
    return 0
```

---

## 3. Database Schema Relevant to Job Triggering

### UserFeedSubscription
```
user_id: int (FK to users)
feed_id: int (FK to feed)
auto_download_new_episodes: bool (default: False)
```

This is the **key setting** that controls automatic processing:
- `True` = New episodes auto-process during feed refresh + RSS downloads trigger processing
- `False` = No automatic processing; must click "Process" in UI

### ProcessingJob
```
post_guid: str
status: enum (pending, running, completed, failed, cancelled)
trigger_source: str (manual_ui, manual_reprocess, auto_feed_refresh, on_demand_rss)
```

---

## 4. Flow Diagrams

### 4.1 Podcast App Downloads Episode (On-Demand Flow)
```
Podcast App                    Podly Server
    |                               |
    |-- GET /feed/combined -------->|
    |                               |-- generate_combined_feed_xml()
    |                               |   (NO processing triggered)
    |<-- RSS XML -------------------|
    |                               |
    |-- HEAD /api/posts/X/download->|
    |                               |-- Return 204 (probe, no trigger)
    |<-- 204 No Content ------------|
    |                               |
    |-- GET /api/posts/X/download ->|
    |   (Range: bytes=0-1023)       |-- Check: is_processed?
    |                               |   NO: Check authorization
    |                               |       Check existing job
    |                               |       Check cooldown
    |                               |       → Start job, return 202
    |<-- 202 + Retry-After: 120 ----|
    |                               |
    |   ... wait 2 minutes ...      |
    |                               |
    |-- GET /api/posts/X/download ->|
    |                               |-- Check: is_processed? YES
    |<-- 200 + audio file ----------|
```

### 4.2 Scheduled Background Refresh
```
APScheduler (every 30 min)
    |
    |-- scheduled_refresh_all_feeds()
    |       |
    |       |-- For each feed:
    |       |       refresh_feed(feed)
    |       |           |-- Fetch upstream RSS
    |       |           |-- Create new Post records
    |       |           |-- If auto_download_enabled for feed:
    |       |           |       Return new post GUIDs
    |       |           |-- Else: Return empty list
    |       |
    |       |-- For each returned GUID:
    |               start_post_processing(guid, trigger_source="auto_feed_refresh")
```

### 4.3 User Clicks Process in UI
```
User Browser                   Podly Server
    |                               |
    |-- POST /api/posts/X/process ->|
    |                               |-- start_post_processing(guid, trigger_source="manual_ui")
    |<-- 200 {status: started} -----|
```

---

## 5. Current User's Configuration

Based on database query:
```
Feed: Late Night Linux Family (id=2)
  User: bob, auto_download_new_episodes: 1  <-- ENABLED

All other feeds:
  auto_download_new_episodes: 0  <-- DISABLED
```

---

## 6. Known Limitations

### Limitation 1: Cooldown is In-Memory
**File:** `src/app/routes/post_routes.py:661`

The cooldown tracking uses a module-level dict:
```python
_on_demand_trigger_cooldowns: dict[str, float] = {}
```

**Impact:**
- Lost on container restart
- Not shared across gunicorn workers (if multi-worker)
- Trigger storms possible after restart

**Recommended Fix:** Use `ProcessingJob.created_at` as implicit cooldown:
```python
last_job = ProcessingJob.query.filter(
    ProcessingJob.post_guid == post.guid
).order_by(ProcessingJob.created_at.desc()).first()

if last_job:
    cooldown_remaining = COOLDOWN_SECONDS - (time.time() - last_job.created_at.timestamp())
```

### Limitation 2: Job Idempotency Race Window
**File:** `src/app/job_manager.py:50-66`

The `ensure_job()` method uses check-then-insert without transactional locking. Under concurrent requests, duplicate jobs are theoretically possible.

**Mitigation:** The download route checks for existing jobs before calling `start_post_processing`, reducing the race window.

---

## 7. Files Involved

| File | Purpose |
|------|---------|
| `src/app/jobs_manager.py` | Core job management, `start_post_processing()` |
| `src/app/routes/post_routes.py` | Download endpoint, manual process/reprocess |
| `src/app/routes/feed_routes.py` | RSS feed endpoints, feed refresh |
| `src/app/feeds.py` | `refresh_feed()` function |
| `src/app/background.py` | Scheduled job setup |
| `src/app/models.py` | Database models including `UserFeedSubscription` |

---

## 9. Expected Behavior Summary

| Action | Should Trigger Processing? | Condition |
|--------|---------------------------|-----------|
| Click "Process" in UI | YES | Always |
| Click "Reprocess" in UI | YES | Always |
| Podcast app HEAD request | NO | Never (returns 204) |
| Podcast app GET request (unprocessed) | YES | If authorized + no existing job + cooldown expired |
| Scheduled feed refresh finds new episode | ONLY IF | `auto_download_new_episodes=True` for that feed |
| Podcast app refreshes RSS feed | NO | Never triggers processing directly |
| GET /feed/combined | NO | Never triggers processing |

**Key Change:** On-demand downloads no longer require `auto_download_new_episodes=True`. That setting only affects scheduled refresh auto-processing.

---

## 10. Debug Commands

Check download requests and decisions:
```bash
docker logs podly-pure-podcasts 2>&1 | grep "DOWNLOAD_" | tail -50
```

Check recent job triggers:
```bash
docker logs podly-pure-podcasts 2>&1 | grep -i "trigger_source\|start_post_processing" | tail -50
```

Check subscription settings:
```bash
docker exec podly-pure-podcasts python -c "
import sqlite3
conn = sqlite3.connect('/app/src/instance/sqlite3.db')
cursor = conn.cursor()
cursor.execute('''
    SELECT f.id, f.title, ufs.auto_download_new_episodes, u.username
    FROM user_feed_subscription ufs
    JOIN feed f ON ufs.feed_id = f.id
    JOIN users u ON ufs.user_id = u.id
''')
for row in cursor.fetchall():
    print(f'Feed {row[0]}: {row[1]} | auto_download={row[2]} | user={row[3]}')
conn.close()
"
```

Check if Late Night Linux is a combined/meta feed:
```bash
docker exec podly-pure-podcasts python -c "
import sqlite3
conn = sqlite3.connect('/app/src/instance/sqlite3.db')
cursor = conn.cursor()
cursor.execute('SELECT id, title, rss_url FROM feed WHERE id = 2')
row = cursor.fetchone()
print(f'Feed ID 2: {row[1]}')
print(f'RSS URL: {row[2]}')
cursor.execute('SELECT COUNT(*) FROM post WHERE feed_id = 2')
print(f'Episode count: {cursor.fetchone()[0]}')
conn.close()
"
```
