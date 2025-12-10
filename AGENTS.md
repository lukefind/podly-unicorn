# Podly Unicorn - AI Agent Guidelines

This file contains important context for AI assistants working on this codebase.

## Project Overview

Podly Unicorn is a fork of Podly - a podcast ad-removal system. It uses Whisper for transcription and LLMs for ad detection.

**Key documentation**: See `docs/ARCHITECTURE.md` for detailed system architecture.

---

## Database

### Location
- **Local**: `src/instance/sqlite3.db`
- **Docker**: `/app/src/instance/sqlite3.db` (NOT `/app/instance/podly.db`)

### Migrations (Alembic / Flask‑Migrate)

The assistant may generate or modify Alembic/Flask‑Migrate migrations, but must:
- Clearly announce when a schema change requires a migration.
- Keep migrations minimal and focused on the actual model changes made in this PR.
- Never drop or rename tables/columns that contain production data unless explicitly requested and the intent is documented.
- Prefer additive changes (new tables/columns/indexes) over destructive ones.

After editing models, the assistant should:
- Either provide the exact `flask db migrate` / `flask db upgrade` commands for the user to run,
- Or, if asked to generate migrations, ensure they are idempotent, reversible, and match the updated models.

The assistant must not fabricate migrations for schemas it hasn't actually inspected; it should always base migration content on the current `app/models.py` and existing migration history.

---

## Prompt Presets

Presets are stored in the database (`prompt_preset` table), not just in code.

### Updating Default Presets

When modifying `src/prompt_presets.py`, the database must also be updated:

```bash
# In Docker container
docker exec podly-pure-podcasts bash -c "cd /app && python -c \"
import sys
sys.path.insert(0, 'src')
from app.extensions import db
from app.models import PromptPreset
from prompt_presets import PRESET_DEFINITIONS
from flask import Flask

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:////app/src/instance/sqlite3.db'
db.init_app(app)

with app.app_context():
    for preset_def in PRESET_DEFINITIONS:
        existing = PromptPreset.query.filter_by(name=preset_def['name']).first()
        if existing:
            existing.system_prompt = preset_def['system_prompt']
            existing.description = preset_def['description']
            existing.min_confidence = preset_def['min_confidence']
    db.session.commit()
    print('Presets updated!')
\""
```

### User-Created Presets

Users can create/edit presets via the UI. These are stored in the database and persist correctly. The init script only affects the 3 default presets (Conservative, Balanced, Aggressive).

### Preset Access Control

**Presets page is admin-only.** Regular users cannot change presets, which prevents one user's preset change from affecting another user's downloads.

### Preset Tracking

When an episode is processed, the active preset ID is stored on the `Post` record (`processed_with_preset_id`). This allows:
- Viewing which preset was used in the episode stats modal (Overview tab)
- Understanding why ad detection behaved a certain way
- Episodes processed before this feature show "Processed before preset tracking was added"

**Important behavior:** If User A processes an episode with "Conservative" preset, and User B later downloads it, User B gets the Conservative-processed version. The preset is locked at processing time, not download time.

### Prompt Design Principles

All presets emphasize flagging **ALL segments within an ad block**, not just the announcement. Key prompt elements:
- "CRITICAL: Flag EVERY segment that is part of an ad"
- Examples showing multiple consecutive segments being flagged
- Clear distinction between ad content and legitimate discussion

---

## Frontend

### Theme
Uses "Unicorn" pastel theme with Tailwind CSS. Key files:
- `frontend/tailwind.config.js` - Custom colors
- `frontend/src/index.css` - Global overrides

### Logo
Custom unicorn logo at `frontend/public/images/logos/unicorn-logo.png`. Used in:
- Sidebar header (`Sidebar.tsx`)
- Login page (`LoginPage.tsx`)

### Modals
Use `createPortal` from `react-dom` to render modals to `document.body` to avoid z-index issues with parent containers.

### CSS Overrides
Global CSS in `index.css` overrides gray colors with purple tints. Use inline `style={{}}` for elements that need original colors (e.g., inside modals).

### User Statistics
Admin users can view per-user statistics in Settings → User Statistics section:
- Episodes processed per user
- Downloads per user  
- Ad time removed per user
- Recent download history

---

## LLM Configuration

### ⚠️ Groq vs Grok - Don't Get Confused!

These are **completely different companies/products**:

| Name | Company | What it is | Used for |
|------|---------|------------|----------|
| **Groq** | Groq Inc (groq.com) | Fast inference platform | Whisper transcription + LLM |
| **Grok** | xAI (x.ai) | Chatbot/LLM model | LLM only (ad detection) |

- **Groq API key** starts with `gsk_...`
- **Grok (xAI) API key** starts with `xai-...`

### Supported Providers

Podly uses [LiteLLM](https://docs.litellm.ai/) which supports 100+ providers. Recommended options:

| Provider | Model Format | Base URL | Notes |
|----------|--------------|----------|-------|
| **Groq** | `groq/llama-3.3-70b-versatile` | *(ignored)* | Fast, free tier, handles both LLM + Whisper |
| **xAI Grok** | `xai/grok-3` | `https://api.x.ai/v1` | High quality, ~$0.10/episode |
| **OpenAI** | `gpt-4o` | *(default)* | Excellent quality, higher cost |
| **Anthropic** | `anthropic/claude-3-sonnet` | *(ignored)* | High quality alternative |

### Recommended Setup

**Simplest**: Just set `GROQ_API_KEY` - it handles both transcription and ad detection.

**Best quality**: Use Groq for Whisper (fast, free) + xAI Grok for LLM (better ad detection):
```bash
GROQ_API_KEY=gsk_...        # For Whisper transcription
LLM_API_KEY=xai-...         # For ad detection
LLM_MODEL=xai/grok-3
OPENAI_BASE_URL=https://api.x.ai/v1
WHISPER_TYPE=groq
```

### Model Name Format
- **With provider prefix** (e.g., `groq/...`, `xai/...`): LiteLLM routes automatically, Base URL setting is ignored
- **Without prefix** (e.g., `gpt-4o`): Uses `OPENAI_BASE_URL` if set

### API Key and Base URL
The `api_key` and `api_base` are passed explicitly in completion calls to support providers like xAI that require them.

---

## Processing Flow

**On-Demand**: Episodes are NOT auto-processed when enabled. Processing triggers:
1. Podcast app requests episode from Podly RSS feed
2. User clicks "Process" in web UI

---

## Docker

### Container: `podly-pure-podcasts`

### Common Commands
```bash
docker logs -f podly-pure-podcasts          # View logs
docker restart podly-pure-podcasts          # Restart
docker exec -it podly-pure-podcasts bash    # Shell access
```

### Database Access in Docker
The running app locks the database. To run scripts:
1. Stop the app, OR
2. Use a minimal Flask app that doesn't start the scheduler (see preset update script above)

---

## Security

### Authentication
- **Session-based auth** with HttpOnly, SameSite=Lax cookies
- **bcrypt** password hashing (12 rounds)
- **Rate limiting** with exponential backoff on failed auth attempts (max 5 min)
- **Feed tokens** for RSS access - SHA-256 hashed, timing-safe comparison

### Authorization
- **Admin-only routes**: Settings, Presets, User Management
- Backend enforces admin checks via `_require_admin()` helper
- Frontend hides admin UI but backend is the source of truth

### Environment Variables
| Variable | Purpose | Required |
|----------|---------|----------|
| `PODLY_SECRET_KEY` | Session encryption key | Recommended for production |
| `REQUIRE_AUTH` | Enable authentication | Yes for multi-user |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | Initial admin credentials | Yes if auth enabled |
| `CORS_ORIGINS` | Allowed CORS origins | Production only |

### Production Recommendations
1. Set `PODLY_SECRET_KEY` to a stable secret (sessions persist across restarts)
2. Use HTTPS (reverse proxy like nginx/Caddy)
3. Set `CORS_ORIGINS` to your domain only

### RSS Feed Authentication
When auth is enabled, RSS feeds require tokens. The "Subscribe to Podly RSS" button automatically generates a tokenized URL that podcast apps can use without login.
