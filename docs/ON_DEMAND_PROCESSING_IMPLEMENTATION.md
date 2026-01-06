# On-Demand Processing Implementation Guide

This guide explains how to implement on-demand episode processing triggered by podcast app downloads. It is designed for developers working on Podly or similar podcast processing systems.

**Target Audience:** Developers of the original Podly fork or similar systems.

---

## Problem Statement

When a user subscribes to a Podly RSS feed in their podcast app (Overcast, Pocket Casts, Apple Podcasts), they expect:

1. Attempting to download an episode triggers processing (if not already processed)
2. The podcast app retries automatically until the episode is ready
3. Probes/prefetches do NOT trigger processing
4. No duplicate jobs are created

The challenge is that podcast apps behave differently:
- Some send `HEAD` requests to probe URLs
- Some send small `Range` requests (e.g., `bytes=0-1023`) before full downloads
- Some don't send cookies or session auth
- Some cache failure responses aggressively

---

## Architecture Overview

```
Podcast App                         Podly Server
    |                                    |
    |-- GET /feed/combined ------------->|  (RSS feed, no processing)
    |<-- RSS XML with enclosure URLs ----|
    |                                    |
    |-- HEAD /api/posts/X/download ----->|  (probe)
    |<-- 204 No Content -----------------|  (no trigger)
    |                                    |
    |-- GET /api/posts/X/download ------>|  (real download attempt)
    |    Range: bytes=0-1023             |
    |                                    |-- Check: is_processed?
    |                                    |   NO: Start job, return 202
    |<-- 202 Accepted + Retry-After: 120-|
    |                                    |
    |   ... podcast app waits ...        |
    |                                    |
    |-- GET /api/posts/X/download ------>|  (retry)
    |                                    |-- Check: is_processed? YES
    |<-- 200 OK + audio file ------------|
```

---

## Implementation

### Step 1: Ensure Enclosure URLs Point to Your Download Endpoint

In your RSS feed generation, the `<enclosure url>` must point to your local download endpoint, not the upstream MP3 URL.

```python
# In your feed generation code (e.g., feeds.py)
def feed_item(post: Post) -> RSSItem:
    # CORRECT: Local download endpoint with auth token
    audio_url = f"{base_url}/api/posts/{post.guid}/download?feed_token={token}"
    
    # WRONG: Upstream URL (bypasses your server entirely)
    # audio_url = post.original_download_url
    
    return RSSItem(
        enclosure=Enclosure(url=audio_url, type="audio/mpeg", length=...),
        ...
    )
```

### Step 2: Implement the Download Endpoint

```python
import time
from flask import Blueprint, request, make_response, g, send_file
from threading import Thread

# Cooldown tracking (see Step 5 for database-backed alternative)
_cooldowns: dict[str, float] = {}
COOLDOWN_SECONDS = 600  # 10 minutes

@post_bp.route("/api/posts/<string:guid>/download", methods=["GET", "HEAD"])
def download_post(guid: str):
    post = Post.query.filter_by(guid=guid).first()
    if not post:
        return make_response(("Post not found", 404))
    
    if not post.whitelisted:
        return make_response(("Post not whitelisted", 403))
    
    # Get request metadata
    current_user = getattr(g, "current_user", None)
    range_header = request.headers.get("Range")
    user_agent = request.headers.get("User-Agent", "")
    
    # Check if already processed
    is_processed = post.processed_audio_path and Path(post.processed_audio_path).exists()
    
    # DIAGNOSTIC LOGGING (essential for debugging)
    logger.info(
        "DOWNLOAD_REQUEST: post=%s method=%s range=%s user_id=%s ua=%s is_processed=%s",
        guid[:16], request.method, range_header,
        current_user.id if current_user else None,
        user_agent[:50], is_processed
    )
    
    if is_processed:
        # Serve the processed audio
        return send_file(post.processed_audio_path, mimetype="audio/mpeg")
    
    # --- TIER 1: HEAD = true probe, never trigger ---
    if request.method == "HEAD":
        logger.info("DOWNLOAD_DECISION: post=%s decision=HEAD_PROBE response=204", guid[:16])
        return make_response(("", 204))
    
    # --- AUTHORIZATION CHECK ---
    # User must be authorized (via session or feed token in URL)
    is_authorized = False
    if current_user and post.feed_id:
        subscription = UserFeedSubscription.query.filter_by(
            user_id=current_user.id,
            feed_id=post.feed_id,
        ).first()
        if subscription:
            is_authorized = True
    
    if not is_authorized:
        logger.info("DOWNLOAD_DECISION: post=%s decision=NOT_AUTHORIZED response=401", guid[:16])
        return make_response(("Authentication required", 401))
    
    # --- CHECK FOR EXISTING JOB ---
    existing_job = ProcessingJob.query.filter(
        ProcessingJob.post_guid == guid,
        ProcessingJob.status.in_(["pending", "running"])
    ).first()
    
    if existing_job:
        logger.info("DOWNLOAD_DECISION: post=%s decision=JOB_EXISTS response=202", guid[:16])
        response = make_response(("Processing in progress", 202))
        response.headers["Retry-After"] = "120"
        return response
    
    # --- COOLDOWN CHECK ---
    now = time.time()
    last_trigger = _cooldowns.get(guid, 0)
    cooldown_remaining = COOLDOWN_SECONDS - (now - last_trigger)
    
    if cooldown_remaining > 0:
        logger.info("DOWNLOAD_DECISION: post=%s decision=COOLDOWN response=202", guid[:16])
        response = make_response(("Processing recently requested", 202))
        response.headers["Retry-After"] = str(min(int(cooldown_remaining) + 10, 300))
        return response
    
    # --- TRIGGER PROCESSING ---
    logger.info("DOWNLOAD_DECISION: post=%s decision=TRIGGER_PROCESSING response=202", guid[:16])
    _cooldowns[guid] = now
    
    # Start processing in background thread
    Thread(
        target=_start_processing_async,
        args=(current_app._get_current_object(), guid, current_user.id),
        daemon=True,
    ).start()
    
    response = make_response(("Processing started", 202))
    response.headers["Retry-After"] = "120"
    return response


def _start_processing_async(app, post_guid: str, user_id: int):
    """Start processing in background thread with app context."""
    with app.app_context():
        get_jobs_manager().start_post_processing(
            post_guid,
            priority="interactive",
            triggered_by_user_id=user_id,
            trigger_source="on_demand_rss",
        )
```

### Step 3: HTTP Response Semantics

| Scenario | Response | Triggers Processing? |
|----------|----------|---------------------|
| HEAD request | `204 No Content` | No |
| Not authorized | `401 Unauthorized` | No |
| Job already pending/running | `202 Accepted` + `Retry-After` | No |
| Within cooldown | `202 Accepted` + `Retry-After` | No |
| Trigger new job | `202 Accepted` + `Retry-After` | Yes |
| Already processed | `200 OK` + audio file | N/A |

**Critical:** Never return `404` for "not yet processed". Podcast apps treat 404 as permanent failure and may not retry.

### Step 4: Why GET with Range Can Trigger

Previous implementations blocked small Range requests (e.g., `bytes=0-1023`) as "probes". This is **wrong** because:

- Overcast, Pocket Casts, and Apple Podcasts all use Range requests for real downloads
- Some apps do multiple small Range requests before committing
- Blocking Range requests means real downloads never trigger processing

The correct approach:
- **HEAD = probe** (never trigger)
- **GET = potential real download** (can trigger, with cooldown to prevent storms)

### Step 5: Database-Backed Cooldown (Recommended)

The in-memory cooldown dict is lost on restart. For production, use the `ProcessingJob.created_at` as implicit cooldown:

```python
# Replace in-memory cooldown with database check
last_job = ProcessingJob.query.filter(
    ProcessingJob.post_guid == guid
).order_by(ProcessingJob.created_at.desc()).first()

if last_job:
    job_age = time.time() - last_job.created_at.timestamp()
    if job_age < COOLDOWN_SECONDS:
        # Within cooldown
        response = make_response(("Processing recently requested", 202))
        response.headers["Retry-After"] = str(int(COOLDOWN_SECONDS - job_age) + 10)
        return response
```

### Step 6: Authentication for Podcast Apps

Podcast apps don't send cookies. You need one of:

1. **Feed token in URL** (recommended):
   ```
   /api/posts/{guid}/download?feed_token=abc123&feed_secret=xyz789
   ```

2. **HTTP Basic Auth** (if your app supports it)

3. **Signed URLs** (time-limited tokens)

Your auth middleware must extract and validate these tokens:

```python
@app.before_request
def authenticate_request():
    # Try session auth first
    if session.get("user_id"):
        g.current_user = User.query.get(session["user_id"])
        return
    
    # Try feed token auth
    feed_token = request.args.get("feed_token")
    feed_secret = request.args.get("feed_secret")
    if feed_token and feed_secret:
        token = FeedAccessToken.query.filter_by(token_id=feed_token).first()
        if token and token.verify_secret(feed_secret):
            g.current_user = token.user
            g.feed_token = token
            return
    
    g.current_user = None
```

---

## Separation of Concerns

**On-demand processing** (this feature) and **scheduled auto-processing** should be separate:

| Setting | Controls |
|---------|----------|
| `auto_download_new_episodes` | Scheduled feed refresh auto-processing |
| User subscription exists | On-demand download triggering |

Do NOT gate on-demand processing on `auto_download_new_episodes`. Users should be able to:
- Disable auto-processing (to save costs)
- Still trigger processing by manually downloading in their podcast app

---

## Testing

### Manual Test with curl

```bash
# HEAD request (should return 204, no trigger)
curl -I "https://your-server/api/posts/GUID/download?feed_token=XXX&feed_secret=YYY"

# GET request (should return 202 and trigger processing)
curl -v "https://your-server/api/posts/GUID/download?feed_token=XXX&feed_secret=YYY"

# GET with Range (should also return 202 and trigger)
curl -v -H "Range: bytes=0-1023" "https://your-server/api/posts/GUID/download?feed_token=XXX&feed_secret=YYY"
```

### Check Logs

```bash
docker logs your-container 2>&1 | grep "DOWNLOAD_"
```

You should see:
```
DOWNLOAD_REQUEST: post=abc123 method=GET range=bytes=0-1023 user_id=1 ...
DOWNLOAD_DECISION: post=abc123 decision=TRIGGER_PROCESSING response=202
```

### Test with Real Podcast Apps

1. Add your Podly RSS feed to Overcast/Pocket Casts/Apple Podcasts
2. Try to download an unprocessed episode
3. Check logs for `DOWNLOAD_REQUEST` entries
4. Verify job was created
5. Wait for processing, retry download
6. Verify audio is served

---

## Common Issues

### Issue: "Podcast app never triggers processing"

**Check:**
1. Is the enclosure URL pointing to your server? (not upstream)
2. Is auth working? (check `user_id` in logs)
3. Is the app sending GET requests? (check `method` in logs)

### Issue: "Processing triggers on every RSS refresh"

**Check:**
1. Is `refresh_feed()` return value being used to start jobs?
2. RSS feed GET should NOT trigger processing, only download GET

### Issue: "Duplicate jobs created"

**Check:**
1. Is existing job check happening before `start_post_processing()`?
2. Is cooldown working?

### Issue: "Podcast app shows permanent error"

**Check:**
1. Are you returning 404 for unprocessed episodes? (should be 202)
2. Is `Retry-After` header present?

---

## Summary

1. **Enclosure URLs** must point to your download endpoint
2. **HEAD = probe**, return 204, never trigger
3. **GET can trigger**, even with Range headers
4. **Cooldown** prevents trigger storms (10 min per GUID)
5. **202 + Retry-After** for all "not ready" responses
6. **Auth via URL tokens** since apps don't send cookies
7. **Separate concerns**: `auto_download_new_episodes` only affects scheduled refresh
