# Incident Report: London Real RSS Feed Addition Failure & Data Loss

**Date**: January 10, 2026  
**Project**: Podly Unicorn (podcast ad-removal system)  
**Severity**: Critical (production data loss)

---

## Summary

Attempting to add the London Real podcast RSS feed (`https://londonrealtv.libsyn.com/rss`) caused a cascade of issues that ultimately resulted in complete loss of all podcast feeds and episodes in the production database.

---

## Timeline of Events

### 1. Initial Problem: Feed Addition Failure

**Symptom**: User could add other podcast feeds successfully, but London Real consistently failed.

**Investigation**:
- Browser console showed `POST /feed` returning 500 Internal Server Error
- Backend logs showed: `UNIQUE constraint failed: post.download_url`

**Root Cause**: The London Real feed has episodes that share the same audio URL (trailers, reruns, etc.). The `post` table had a `UNIQUE` constraint on `download_url`, which is unnecessary since `guid` already ensures episode uniqueness.

### 2. First Fix Attempt: Remove Unique Constraint

**Action**: Created Alembic migration `k8l9m0n1o2p3_remove_download_url_unique.py` to remove the constraint.

**Problem**: SQLite doesn't support `DROP CONSTRAINT`. The migration had to recreate the table.

**Critical Mistake**: The migration used `SELECT *` to copy data:
```sql
-- WRONG - This caused the data corruption
INSERT INTO post_new SELECT * FROM post
```

### 3. Data Corruption

**What happened**: Column order in the old `post` table didn't match the new table definition. `SELECT *` copies data by position, not by column name. Data was shifted into wrong columns:
- File paths ended up in `release_date` column
- Datetime values ended up in text columns
- etc.

**Error observed**:
```
ValueError: Invalid isoformat string: '/app/src/instance/data/srv/The_Rest_Is_Science/Is Music Getting Worse.mp3'
```

SQLAlchemy tried to parse a file path as a datetime, causing the Settings page to crash.

### 4. Failed Recovery Attempt

**Action**: User was instructed to restore from backup:
```bash
sudo cp src/instance/sqlite3.db.backup src/instance/sqlite3.db
```

**Problem**: The backup was made AFTER the corruption occurred (or after manual SQL commands were run that emptied the tables). The backup contained 0 feeds and 0 posts.

**Result**: Complete data loss - all podcast subscriptions and episode data gone. Only user accounts survived.

---

## Fixes Applied

### 1. Migration Fixed
Updated migration to use explicit column names:
```sql
-- CORRECT - Explicit columns prevent order mismatch
INSERT INTO post_new (
    id, feed_id, guid, download_url, title,
    unprocessed_audio_path, processed_audio_path, description,
    release_date, duration, whitelisted, image_url,
    download_count, processed_with_preset_id
)
SELECT 
    id, feed_id, guid, download_url, title,
    unprocessed_audio_path, processed_audio_path, description,
    release_date, duration, whitelisted, image_url,
    download_count, processed_with_preset_id
FROM post
```

### 2. Model Updated
Removed `unique=True` from `download_url` column in `src/app/models.py`.

### 3. Documentation Updated
Added critical safety rules to `AGENTS.md`:
- NEVER use `SELECT *` when copying data between tables
- ALWAYS use explicit column names in both INSERT and SELECT
- Back up database BEFORE migrations, verify backup has data

---

## Current State

- Migration is now correct and deployed
- London Real feed can now be added successfully
- User must re-add all podcast feeds manually
- User accounts are intact

---

## Current Issue (Unresolved)

After re-adding London Real and a Linux podcast successfully, the "Hybrid Cloud Show" podcast fails to add. Logs show:
- Search requests to `api.podcastindex.org` succeed
- No `[FEED_ADD]` log entries appear
- POST request to `/feed` endpoint not reaching backend

This is the same pattern as the original London Real issue, but the root cause may be different since the unique constraint is now removed.

**Possible causes to investigate**:
1. Frontend error before sending request (check browser console)
2. Invalid feed URL returned from search API
3. Network timeout on slow/large feed
4. Another database constraint violation
5. Feed parsing error in `feedparser`

---

## Key Files Modified

| File | Change |
|------|--------|
| `src/app/models.py` | Removed `unique=True` from `download_url` |
| `src/migrations/versions/k8l9m0n1o2p3_remove_download_url_unique.py` | Fixed to use explicit column names |
| `src/app/routes/feed_routes.py` | Added logging: `[FEED_ADD] POST /feed received` |
| `AGENTS.md` | Added SQLite migration safety rules |

---

## Commits (Jan 10, 2026)

1. `d3be8c2` - debug: add detailed logging for feed add errors
2. `7fccb4d` - fix: remove unique constraint from post.download_url
3. `d89248b` - debug: add early logging to add_feed endpoint
4. `81cb861` - fix: use raw SQL to remove unique constraint on download_url
5. `fd1a7e4` - fix: use explicit column names in migration to prevent data corruption
6. `2e29c47` - docs: add critical SQLite migration safety rules to AGENTS.md

---

## Lessons Learned

1. **NEVER use `SELECT *` in SQLite table recreation** - column order is not guaranteed
2. **Always verify backups have data** before relying on them
3. **Back up BEFORE running migrations**, not after
4. **Test migrations on a copy of production data** before applying to production
5. **Large feeds (1000+ episodes) can overwhelm the server** - consider async loading

---

## Investigation Needed

For the current "Hybrid Cloud Show" issue:

1. Get browser console output when clicking Subscribe
2. Check if POST request is sent at all (Network tab)
3. Get full backend logs: `sudo docker logs --tail 100 podly-pure-podcasts`
4. Test the feed URL directly: `curl -sL "<feed_url>" | head -50`
5. Check if feed has unusual structure that breaks `feedparser`

---

## Server Configuration

- **CPU**: Intel i7-8700K (6 cores / 12 threads)
- **Recommended**: Set `SERVER_THREADS=12` in `.env.local` for better concurrency
- **Current default**: 4 threads (may cause queue buildup on large feeds)
