# Podly Unicorn - Complete Repository Audit

**Generated**: January 10, 2026  
**Purpose**: Comprehensive codebase reference for AI assistants (ChatGPT, Claude, etc.)

---

## Table of Contents

1. [Project Overview](#project-overview)
2. [Architecture Summary](#architecture-summary)
3. [Directory Structure](#directory-structure)
4. [Backend (Python/Flask)](#backend-pythonflask)
5. [Frontend (React/TypeScript)](#frontend-reacttypescript)
6. [Database Schema](#database-schema)
7. [Key Workflows](#key-workflows)
8. [Configuration](#configuration)
9. [Known Issues & Recent Incidents](#known-issues--recent-incidents)
10. [Critical Files Reference](#critical-files-reference)

---

## Project Overview

**Podly Unicorn** is a podcast ad-removal system that:
1. Fetches podcast RSS feeds
2. Downloads episode audio
3. Transcribes audio using Whisper (local or Groq API)
4. Uses LLMs to detect ad segments in transcripts
5. Removes detected ads from audio
6. Serves ad-free episodes via a custom RSS feed

**Tech Stack**:
- **Backend**: Python 3.11, Flask, SQLAlchemy, Alembic
- **Frontend**: React 18, TypeScript, Vite, Tailwind CSS
- **Database**: SQLite
- **Audio**: FFmpeg, pydub
- **Transcription**: OpenAI Whisper (local) or Groq API
- **LLM**: LiteLLM (supports OpenAI, Groq, xAI Grok, Anthropic, etc.)
- **Server**: Waitress (WSGI)
- **Container**: Docker

---

## Architecture Summary

```
┌─────────────────────────────────────────────────────────────────┐
│                        User's Podcast App                        │
│                    (Apple Podcasts, Overcast, etc.)              │
└─────────────────────────────────────────────────────────────────┘
                                │
                                │ RSS Feed Request
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                         Podly Unicorn                            │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐   │
│  │   Frontend   │  │   Backend    │  │   Processing Engine  │   │
│  │   (React)    │◄─┤   (Flask)    │◄─┤   (Whisper + LLM)    │   │
│  └──────────────┘  └──────────────┘  └──────────────────────┘   │
│                           │                    │                 │
│                           ▼                    ▼                 │
│                    ┌──────────────┐    ┌──────────────┐         │
│                    │   SQLite DB  │    │  Audio Files │         │
│                    └──────────────┘    └──────────────┘         │
└─────────────────────────────────────────────────────────────────┘
```

### Processing Flow

1. **User adds feed** → Backend fetches RSS, stores feed + episodes in DB
2. **User triggers processing** → Via web UI button OR trigger link in podcast app
3. **Download** → Episode audio downloaded to local storage
4. **Transcribe** → Whisper generates timestamped transcript
5. **Detect Ads** → LLM analyzes transcript, flags ad segments
6. **Process Audio** → FFmpeg removes flagged segments with crossfades
7. **Serve** → Processed audio served via Podly RSS feed

---

## Directory Structure

```
podly-unicorn/
├── AGENTS.md                 # AI assistant guidelines (CRITICAL - read first)
├── README.md                 # User-facing documentation
├── STATUS.md                 # Project status tracking
├── INCIDENT_REPORT_2026-01-10.md  # Recent data loss incident
├── compose.yml               # Docker Compose configuration
├── Dockerfile                # Container build instructions
├── docker-entrypoint.sh      # Container startup script
├── Pipfile / Pipfile.lock    # Python dependencies
│
├── docs/                     # Documentation
│   ├── ARCHITECTURE.md       # System architecture details
│   ├── TRIGGER_ARCHITECTURE.md  # Trigger page flow
│   ├── PROMPT_PRESETS_AND_STATISTICS.md
│   └── how_to_run_beginners.md
│
├── frontend/                 # React frontend
│   ├── src/
│   │   ├── components/       # React components
│   │   ├── pages/            # Page components
│   │   ├── services/api.ts   # Backend API client
│   │   ├── contexts/         # React contexts (auth, theme)
│   │   └── index.css         # Global styles + dark mode
│   ├── tailwind.config.js    # Tailwind configuration
│   └── package.json
│
├── src/                      # Python backend
│   ├── main.py               # Application entry point
│   ├── app/                  # Flask application
│   │   ├── __init__.py       # App factory
│   │   ├── models.py         # SQLAlchemy models (CRITICAL)
│   │   ├── feeds.py          # RSS feed handling
│   │   ├── jobs_manager.py   # Processing job queue
│   │   └── routes/           # API endpoints
│   │       ├── feed_routes.py    # Feed CRUD + RSS generation
│   │       ├── post_routes.py    # Episode operations
│   │       ├── auth_routes.py    # Authentication
│   │       ├── config_routes.py  # Settings
│   │       └── preset_routes.py  # Prompt presets
│   │
│   ├── podcast_processor/    # Audio processing engine
│   │   ├── ad_classifier.py  # LLM ad detection
│   │   ├── transcribe.py     # Whisper transcription
│   │   ├── audio_processor.py # FFmpeg audio editing
│   │   └── podcast_processor.py # Main processing orchestrator
│   │
│   ├── migrations/           # Alembic database migrations
│   │   └── versions/         # Migration files
│   │
│   └── shared/               # Shared utilities
│       ├── config.py         # Configuration management
│       └── defaults.py       # Default values
│
└── scripts/                  # Utility scripts
```

---

## Backend (Python/Flask)

### Entry Point: `src/main.py`

```python
from waitress import serve
from app import create_app

def main():
    app = create_app()
    threads = int(os.environ.get("SERVER_THREADS", 4))
    serve(app, host="0.0.0.0", port=5001, threads=threads)
```

### Key Files

#### `src/app/__init__.py` - App Factory
- Creates Flask app
- Registers blueprints
- Initializes database
- Sets up authentication
- Starts background scheduler

#### `src/app/models.py` - Database Models (CRITICAL)

**Main Models**:

| Model | Purpose | Key Fields |
|-------|---------|------------|
| `Feed` | Podcast subscription | `id`, `title`, `rss_url`, `image_url`, `is_hidden` |
| `Post` | Episode | `id`, `guid`, `feed_id`, `download_url`, `title`, `whitelisted`, `processed_audio_path` |
| `User` | User account | `id`, `username`, `email`, `password_hash`, `role` |
| `UserFeedSubscription` | User-feed relationship | `user_id`, `feed_id`, `is_private`, `auto_download_new_episodes` |
| `ProcessingJob` | Processing task | `id`, `post_id`, `status`, `step`, `error_message` |
| `TranscriptSegment` | Transcript chunk | `post_id`, `sequence_num`, `start_time`, `end_time`, `text` |
| `Identification` | Ad detection result | `segment_id`, `is_ad`, `confidence`, `reason` |
| `PromptPreset` | LLM prompt config | `name`, `system_prompt`, `min_confidence`, `is_active` |
| `FeedAccessToken` | RSS auth token | `token_id`, `token_hash`, `feed_id`, `user_id` |

**Post Model Detail** (recently modified):
```python
class Post(db.Model):
    feed_id = db.Column(db.Integer, db.ForeignKey("feed.id"), nullable=False, index=True)
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    guid = db.Column(db.Text, unique=True, nullable=False)
    download_url = db.Column(db.Text, nullable=False)  # NOT unique (changed Jan 2026)
    title = db.Column(db.Text, nullable=False)
    unprocessed_audio_path = db.Column(db.Text)
    processed_audio_path = db.Column(db.Text)
    description = db.Column(db.Text)
    release_date = db.Column(db.DateTime(timezone=True))
    duration = db.Column(db.Integer)
    whitelisted = db.Column(db.Boolean, default=False, nullable=False)
    image_url = db.Column(db.Text)
    download_count = db.Column(db.Integer, nullable=True, default=0)
    processed_with_preset_id = db.Column(db.Integer, db.ForeignKey("prompt_preset.id"), nullable=True)
```

#### `src/app/routes/feed_routes.py` - Feed API (61KB)

**Key Endpoints**:

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/feed` | Add new feed |
| `GET` | `/feeds` | List all feeds |
| `GET` | `/feed/<id>` | Get feed RSS XML |
| `DELETE` | `/feed/<id>` | Delete/unsubscribe feed |
| `GET` | `/api/feeds/search` | Search podcast index |
| `POST` | `/api/feeds/<id>/refresh` | Refresh feed episodes |
| `GET` | `/api/feeds/combined` | Combined RSS feed |

**Add Feed Flow** (`POST /feed`):
```python
@feed_bp.route("/feed", methods=["POST"])
def add_feed():
    logger.info(f"[FEED_ADD] POST /feed received, form data: {dict(request.form)}")
    url = request.form.get("url")
    url = fix_url(url)  # Add https:// if missing
    
    feed = add_or_refresh_feed(url)  # Fetches RSS, creates Feed + Posts
    
    # Auto-subscribe user
    if current_user:
        subscription = UserFeedSubscription(user_id=current.id, feed_id=feed.id)
        db.session.add(subscription)
    
    return jsonify({"status": "success", "feed_id": feed.id, "title": feed.title})
```

#### `src/app/feeds.py` - RSS Handling (29KB)

**Key Functions**:

| Function | Purpose |
|----------|---------|
| `fetch_feed(url)` | Download and parse RSS with feedparser |
| `add_feed(feed_data)` | Create Feed + Post records |
| `refresh_feed(feed)` | Update existing feed with new episodes |
| `add_or_refresh_feed(url)` | Main entry point - add or update |
| `generate_feed_xml(feed)` | Generate Podly RSS XML |
| `generate_combined_feed_xml()` | Generate combined feed XML |
| `inject_trigger_cta(description)` | Add processing link to episode description |

**Feed Parsing** (with image fallbacks):
```python
def add_feed(feed_data):
    # Extract image URL with fallbacks
    image_url = None
    if hasattr(feed_data.feed, 'image') and hasattr(feed_data.feed.image, 'href'):
        image_url = feed_data.feed.image.href
    elif 'image' in feed_data.feed and isinstance(feed_data.feed.image, dict):
        image_url = feed_data.feed.image.get('href') or feed_data.feed.image.get('url')
    if not image_url:
        image_url = feed_data.feed.get('itunes_image', {}).get('href', '')
```

#### `src/app/jobs_manager.py` - Job Queue (26KB)

Manages processing jobs with states:
- `pending` - Waiting to start
- `running` - Currently processing
- `completed` - Successfully finished
- `failed` - Error occurred

#### `src/podcast_processor/ad_classifier.py` - LLM Integration (38KB)

Uses LiteLLM for multi-provider support:
```python
response = litellm.completion(
    model=self.config.llm_model,
    messages=[
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ],
    api_key=self.config.llm_api_key,
    api_base=self.config.openai_base_url,
    max_tokens=self.config.openai_max_tokens,
)
```

#### `src/podcast_processor/transcribe.py` - Whisper Integration (8KB)

Supports:
- Local Whisper models (`whisper_type: local`)
- Groq Whisper API (`whisper_type: groq`)

---

## Frontend (React/TypeScript)

### Key Files

#### `frontend/src/services/api.ts` - API Client (806 lines)

```typescript
export const feedsApi = {
  addFeed: async (url: string) => {
    const formData = new FormData();
    formData.append('url', url);
    const response = await api.post('/feed', formData, {
      headers: { 'Accept': 'application/json' },
    });
    return response.data;
  },
  // ... other methods
};
```

#### `frontend/src/components/AddFeedForm.tsx` - Feed Addition UI (15KB)

- Search mode: Queries podcast index API
- URL mode: Direct RSS URL input
- Debounced search (400ms)
- Handles subscription state

#### `frontend/src/pages/TriggerPage.tsx` - Processing Trigger (13KB)

Public page for triggering episode processing from podcast apps:
- Shows processing progress
- Displays "Episode Ready" when complete
- No login required (uses feed tokens)

#### `frontend/src/index.css` - Global Styles (14KB)

Contains dark mode overrides using `html.dark .class-name` selectors.
**Important**: Don't use inline `dark:` variants - use global CSS.

---

## Database Schema

### Current Migration Head

**Revision**: `k8l9m0n1o2p3` (Remove unique constraint from post.download_url)

### Tables

```sql
-- Core tables
feed (id, title, description, author, rss_url, image_url, default_prompt_preset_id, is_hidden)
post (id, feed_id, guid, download_url, title, description, release_date, duration, whitelisted, ...)
users (id, username, email, password_hash, role, account_status, created_at)
user_feed_subscription (id, user_id, feed_id, is_private, auto_download_new_episodes)

-- Processing tables
processing_job (id, post_id, status, step, error_message, created_at, updated_at)
transcript_segment (id, post_id, sequence_num, start_time, end_time, text)
identification (id, segment_id, is_ad, confidence, reason)

-- Configuration tables
prompt_preset (id, name, description, system_prompt, min_confidence, is_active)
app_settings, llm_settings, whisper_settings, output_settings, processing_settings

-- Auth tables
feed_access_token (id, token_id, token_hash, token_secret, feed_id, user_id)
password_reset_token (id, user_id, token_hash, expires_at)

-- Analytics
user_download (id, user_id, post_id, feed_id, event_type, downloaded_at)
processing_statistics (id, post_id, ...)
model_call (id, post_id, ...)
```

### Migration Safety Rules (CRITICAL)

**NEVER use `SELECT *` when recreating tables in SQLite migrations.**

```sql
-- WRONG - causes data corruption
INSERT INTO table_new SELECT * FROM table_old

-- CORRECT - explicit columns
INSERT INTO table_new (id, name, created_at)
SELECT id, name, created_at FROM table_old
```

---

## Key Workflows

### 1. Adding a Feed

```
User clicks "Add Feed" → Frontend POSTs to /feed
    → Backend fetches RSS with feedparser
    → Creates Feed record
    → Creates Post records for each episode
    → Auto-subscribes user
    → Returns success with feed_id
```

### 2. Processing an Episode

```
User clicks "Process" or taps trigger link
    → Creates ProcessingJob
    → Downloads audio to /instance/data/in/
    → Transcribes with Whisper → TranscriptSegments
    → LLM analyzes segments → Identifications
    → FFmpeg removes ad segments
    → Saves to /instance/data/srv/
    → Updates Post.processed_audio_path
```

### 3. Serving Processed Audio

```
Podcast app requests RSS feed
    → Backend generates XML with episode enclosures
    → Enclosure URL points to /api/posts/<guid>/download
    → Download endpoint serves processed audio (or original if not processed)
```

---

## Configuration

### Environment Variables

| Variable | Purpose | Example |
|----------|---------|---------|
| `GROQ_API_KEY` | Groq API (Whisper + LLM) | `gsk_...` |
| `LLM_API_KEY` | LLM provider API key | `xai-...` |
| `LLM_MODEL` | LLM model name | `xai/grok-3` |
| `OPENAI_BASE_URL` | Custom LLM endpoint | `https://api.x.ai/v1` |
| `WHISPER_TYPE` | Transcription method | `local` or `groq` |
| `REQUIRE_AUTH` | Enable authentication | `true` |
| `ADMIN_USERNAME` | Initial admin user | `admin` |
| `ADMIN_PASSWORD` | Initial admin password | `secret` |
| `SERVER_THREADS` | Waitress thread count | `12` |
| `PODLY_SECRET_KEY` | Session encryption | Random string |

### Docker Compose

```yaml
services:
  podly:
    container_name: podly-pure-podcasts
    ports:
      - "5001:5001"
    volumes:
      - ./src/instance:/app/src/instance
    env_file:
      - ./.env.local
    environment:
      - SERVER_THREADS=${SERVER_THREADS:-4}
```

---

## Known Issues & Recent Incidents

### January 10, 2026 - Data Loss Incident

**Problem**: Adding London Real podcast failed with `UNIQUE constraint failed: post.download_url`

**Root Cause**: Some feeds have episodes sharing the same audio URL. The `download_url` column had an unnecessary unique constraint.

**Fix Attempt Gone Wrong**: Migration to remove constraint used `SELECT *` which caused column order mismatch, corrupting all data.

**Resolution**:
1. Fixed migration to use explicit column names
2. Added safety rules to AGENTS.md
3. User had to re-add all feeds (data was lost)

**See**: `INCIDENT_REPORT_2026-01-10.md` for full details.

### Current Issue (Unresolved)

Some feeds fail to add with no error in logs. Pattern:
- Search works (logs show API calls to podcastindex.org)
- POST to `/feed` never reaches backend
- No `[FEED_ADD]` log entries

**Debugging Steps**:
1. Check browser console for JavaScript errors
2. Check Network tab for failed requests
3. Test feed URL directly with curl
4. Check if feed has unusual structure

---

## Critical Files Reference

### Must Read First
- `AGENTS.md` - AI assistant guidelines, migration rules, architecture overview

### Backend Core
- `src/app/models.py` - All database models
- `src/app/routes/feed_routes.py` - Feed API endpoints
- `src/app/feeds.py` - RSS parsing and generation
- `src/app/jobs_manager.py` - Processing job queue

### Frontend Core
- `frontend/src/services/api.ts` - Backend API client
- `frontend/src/components/AddFeedForm.tsx` - Feed addition UI
- `frontend/src/index.css` - Global styles and dark mode

### Processing Engine
- `src/podcast_processor/ad_classifier.py` - LLM ad detection
- `src/podcast_processor/transcribe.py` - Whisper integration
- `src/podcast_processor/audio_processor.py` - FFmpeg operations

### Configuration
- `compose.yml` - Docker configuration
- `.env.local.example` - Environment variables template
- `src/shared/config.py` - Configuration management

### Migrations
- `src/migrations/versions/` - All Alembic migrations
- Latest: `k8l9m0n1o2p3_remove_download_url_unique.py`

---

## Common Commands

```bash
# View logs
docker logs -f podly-pure-podcasts

# Restart container
docker restart podly-pure-podcasts

# Shell access
docker exec -it podly-pure-podcasts bash

# Database access (Python, not sqlite3 CLI)
docker exec podly-pure-podcasts python -c "
import sqlite3
conn = sqlite3.connect('/app/src/instance/sqlite3.db')
cursor = conn.cursor()
cursor.execute('SELECT COUNT(*) FROM feed')
print('Feeds:', cursor.fetchone()[0])
conn.close()
"

# Rebuild and restart
docker compose up -d --build
```

---

## Server Recommendations

For Intel i7-8700K (6 cores / 12 threads):
- Set `SERVER_THREADS=12` in `.env.local`
- Current default is 4, which causes queue buildup on large feeds

---

*Generated by Cascade AI - January 10, 2026*
