<div align="center">
  <img src="frontend/public/images/logos/unicorn-logo.png" alt="Podly Unicorn" width="120" />
  <h1>Podly Unicorn</h1>
  <p><strong>AI-powered podcast ad removal with a beautiful pastel theme</strong></p>
  
  <p>
    <a href="https://github.com/lukefind/podly-unicorn"><img src="https://img.shields.io/badge/GitHub-podly--unicorn-purple?logo=github" alt="GitHub"></a>
    <a href="https://github.com/jdrbc/podly_pure_podcasts/blob/main/LICENCE"><img src="https://img.shields.io/badge/License-MIT-green.svg" alt="License"></a>
  </p>
</div>

---

## What is Podly Unicorn?

Podly Unicorn automatically removes advertisements from podcasts using AI. Add your favorite shows, and Podly creates ad-free RSS feeds you can subscribe to in any podcast app.

**Key Features:**
- 🤖 **AI-Powered** — Uses LLMs (Groq, OpenAI, xAI Grok) to detect and remove ads
- 📡 **RSS Feeds** — Subscribe in Apple Podcasts, Overcast, Pocket Casts, or any app
- 🎛️ **Adjustable Presets** — Conservative, Balanced, or Aggressive ad removal
- 📊 **Statistics** — See exactly how much ad time was removed per episode
- 👥 **Multi-User** — Per-user feed subscriptions with privacy controls
- 🦄 **Beautiful UI** — Pastel unicorn theme with dark mode and mobile support
- 🔒 **Self-Hosted** — Your data stays on your server

---

## Quick Start (Docker)

### Prerequisites
- Docker and Docker Compose
- LLM API key from [Groq](https://console.groq.com/keys) (free) or OpenAI/xAI

### 1. Clone and Configure

```bash
git clone https://github.com/lukefind/podly-unicorn.git
cd podly-unicorn
cp .env.local.example .env.local
```

Edit `.env.local`:

```bash
# Required: LLM for ad detection
LLM_API_KEY=gsk_your_groq_key
LLM_MODEL=groq/llama-3.3-70b-versatile

# Required: Whisper for transcription
WHISPER_TYPE=groq
GROQ_API_KEY=gsk_your_groq_key

# Recommended: Enable authentication
REQUIRE_AUTH=true
PODLY_ADMIN_USERNAME=admin
PODLY_ADMIN_PASSWORD=your-secure-password
```

### 2. Start

```bash
docker compose up -d --build
```

### 3. Access

Open http://localhost:5001

---

## Configuration

### LLM Providers

| Provider | Model | Notes |
|----------|-------|-------|
| **Groq** | `groq/llama-3.3-70b-versatile` | Free tier, fast |
| **xAI Grok** | `xai/grok-3` | Recommended for accuracy (~$0.10/episode) |
| **OpenAI** | `gpt-4o` | High quality |

For xAI Grok:
```bash
LLM_API_KEY=xai-your-key
LLM_MODEL=xai/grok-3
OPENAI_BASE_URL=https://api.x.ai/v1
```

### Whisper (Transcription)

| Mode | Config | Notes |
|------|--------|-------|
| **Groq** | `WHISPER_TYPE=groq` | Fast, cheap, recommended |
| **Local** | `WHISPER_TYPE=local` | Free, requires RAM |

### Ad Detection Presets

| Preset | Description |
|--------|-------------|
| **Conservative** | Only obvious ads — sponsor reads, "brought to you by" |
| **Balanced** | Default — typical ads while preserving content |
| **Aggressive** | All promotional content including self-promotion |

---

## Updating

```bash
cd podly-unicorn
git pull
docker compose up -d --build
```

---

## Common Commands

```bash
# View logs
docker logs -f podly-pure-podcasts

# Restart
docker compose restart

# Stop
docker compose down

# Backup database
docker cp podly-pure-podcasts:/app/src/instance/sqlite3.db ./backup.db
```

---

## Development

```bash
# Frontend (hot reload)
cd frontend && npm install && npm run dev

# Backend
docker compose up --build
```

---

## Credits

Fork of [Podly Pure Podcasts](https://github.com/jdrbc/podly_pure_podcasts) by [@jdrbc](https://github.com/jdrbc).

---

<div align="center">
  <p>
    <a href="https://github.com/lukefind/podly-unicorn">GitHub</a> •
    <a href="https://github.com/lukefind/podly-unicorn/issues">Issues</a>
  </p>
</div>
