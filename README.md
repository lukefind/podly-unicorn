<div align="center">
  <h1>🦄 Podly Unicorn</h1>
  <h3>✨ Ad-block for podcasts with a magical pastel theme ✨</h3>
  
  <p>
    <a href="https://discord.gg/FRB98GtF6N"><img src="https://img.shields.io/badge/Discord-Join%20Community-5865F2?logo=discord&logoColor=white" alt="Discord"></a>
    <a href="https://github.com/jdrbc/podly_pure_podcasts"><img src="https://img.shields.io/badge/Fork%20of-Podly%20Pure%20Podcasts-ff69b4" alt="Fork"></a>
    <a href="https://github.com/jdrbc/podly_pure_podcasts/blob/main/LICENCE"><img src="https://img.shields.io/badge/License-MIT-green.svg" alt="License"></a>
  </p>
  
  <p>
    <strong>This is a fork of <a href="https://github.com/jdrbc/podly_pure_podcasts">Podly Pure Podcasts</a></strong> with UI/UX improvements and a beautiful pastel unicorn theme.
  </p>
</div>

---

## ✨ What is Podly Unicorn?

Podly Unicorn automatically removes advertisements from podcasts using AI. It creates clean RSS feeds you can subscribe to in any podcast app.

**This fork adds:**
- 🦄 Beautiful pastel unicorn theme (pink, purple, blue, mint gradients)
- 🎨 Improved UI/UX with glass-morphism cards and rainbow effects
- 📋 Better job history management with clear history button
- ⚙️ Streamlined settings page layout
- 👥 Multi-user support with per-user usage statistics
- 🔐 Themed login page with custom unicorn branding
- 📖 Updated documentation

> 💜 **Original project:** [github.com/jdrbc/podly_pure_podcasts](https://github.com/jdrbc/podly_pure_podcasts) — All credit to the original Podly team!

<img width="100%" src="docs/images/screenshot.png" alt="Podly Dashboard" />

### How It Works

1. **Subscribe** — Add your favorite podcast's RSS feed
2. **Enable** — Mark episodes as enabled (eligible for processing) or disabled (skipped)
3. **Process** — Episodes are processed **on-demand** when:
   - Your podcast app requests the episode from the Podly RSS feed
   - You manually click "Process" in the web UI
4. **Listen** — Get a clean RSS feed URL to use in your podcast app

> 💡 **On-Demand Processing**: Enabled episodes are NOT processed automatically. They're processed when requested, saving compute resources and API costs. Disabled episodes are skipped entirely.

---

## 🚀 Quick Start

### Option 1: Try the Preview Server
**[→ podly.up.railway.app](https://podly.up.railway.app/)** — No setup required

### Option 2: Deploy to Railway (Recommended for sharing)
[![Deploy on Railway](https://railway.com/button.svg)](https://railway.com/deploy/podly?referralCode=NMdeg5&utm_medium=integration&utm_source=template&utm_campaign=generic)

See our [Railway deployment guide](docs/how_to_run_railway.md) for details.

### Option 3: Run Locally with Docker (Home Machine or Server)

This is the recommended way to run Podly on your own hardware — whether that's a laptop, desktop, Raspberry Pi, or home server.

#### Prerequisites

- **Docker** and **Docker Compose** installed
  - Mac/Windows: Install [Docker Desktop](https://www.docker.com/products/docker-desktop/)
  - Linux: `sudo apt install docker.io docker-compose-v2` (or equivalent for your distro)
- **LLM API Key** — Get a free one from [Groq](https://console.groq.com/keys) (recommended) or use OpenAI/xAI

#### Step 1: Clone the Repository

```bash
git clone https://github.com/lukefind/podly-unicorn.git
cd podly-unicorn
```

#### Step 2: Create Your Config File

```bash
cp .env.local.example .env.local
```

Edit `.env.local` with your preferred text editor:

```bash
nano .env.local   # or vim, code, etc.
```

**Minimum required settings:**

```bash
# Get a free key at https://console.groq.com/keys
LLM_API_KEY=gsk_your_groq_api_key_here
LLM_MODEL=groq/llama-3.3-70b-versatile

# Whisper transcription (Groq is fast and cheap)
WHISPER_TYPE=groq
GROQ_API_KEY=gsk_your_groq_api_key_here
```

**Optional: Enable authentication** (recommended for servers):

```bash
REQUIRE_AUTH=true
PODLY_ADMIN_USERNAME=admin
PODLY_ADMIN_PASSWORD=your-secure-password-here
PODLY_SECRET_KEY=generate-a-64-character-random-string
```

> 💡 Generate a secret key: `openssl rand -hex 32`

#### Step 3: Build and Start

```bash
docker compose up -d --build
```

This will:
- Build the Docker image (~2-5 minutes first time)
- Start the container in the background
- Run database migrations automatically

#### Step 4: Access the Web UI

Open your browser to:
- **Local machine:** http://localhost:5001
- **Home server:** http://YOUR_SERVER_IP:5001

If you enabled auth, log in with the username/password you set.

#### Useful Commands

```bash
# View logs
docker logs -f podly-pure-podcasts

# Restart after config changes
docker compose down && docker compose up -d

# Rebuild after code updates (e.g., git pull)
docker compose up -d --build

# Stop Podly
docker compose down
```

#### Updating to Latest Version

```bash
cd ~/podly-unicorn
git pull origin main
docker compose up -d --build
```

#### Data Persistence

Your data is stored in Docker volumes and persists across restarts:
- **Database:** `src/instance/sqlite3.db` (feeds, episodes, users)
- **Processed audio:** `processing_output/` directory

To back up your data:
```bash
docker cp podly-pure-podcasts:/app/src/instance/sqlite3.db ./backup.db
```

#### Exposing to the Internet (Optional)

To access Podly from outside your home network:
1. **Port forward** port 5001 on your router to your server's IP
2. Or use a reverse proxy like **Caddy** or **nginx** with HTTPS
3. Or use a tunnel service like **Cloudflare Tunnel** or **Tailscale**

> ⚠️ **Always enable authentication** (`REQUIRE_AUTH=true`) if exposing to the internet!

📖 See our [detailed beginner's guide](docs/how_to_run_beginners.md) for more help.

---

## ⚙️ Configuration

### LLM Setup (Required)

Podly uses [LiteLLM](https://docs.litellm.ai/) which supports 100+ LLM providers.

#### Recommended Providers

| Provider | Model | Cost | Quality | Setup |
|----------|-------|------|---------|-------|
| **Groq** | `groq/llama-3.3-70b-versatile` | Very cheap | Good | Free API key at [console.groq.com](https://console.groq.com/keys) |
| **xAI Grok** | `xai/grok-3` | ~$0.10/episode | Excellent | API key from [x.ai](https://x.ai) |
| **OpenAI** | `gpt-4o` | ~$0.10/episode | Excellent | API key from [platform.openai.com](https://platform.openai.com) |

#### Quick Setup (Groq)

1. Get a free API key at [console.groq.com](https://console.groq.com/keys)
2. In Podly Settings → Quick Setup, paste your Groq API key
3. Done! Podly auto-configures the recommended models

#### Using xAI Grok (Recommended for Quality)

For best ad detection quality, use xAI's Grok-3:

```bash
# In .env.local
LLM_API_KEY=xai-your-api-key
LLM_MODEL=xai/grok-3
OPENAI_BASE_URL=https://api.x.ai/v1
```

#### Model Name Format

| Model Format | Base URL | How it works |
|--------------|----------|--------------|
| `groq/llama-3.3-70b-versatile` | *(ignored)* | LiteLLM routes to Groq automatically |
| `xai/grok-3` | `https://api.x.ai/v1` | LiteLLM routes to xAI |
| `gpt-4o` | *(default)* | Uses OpenAI directly |

> 💡 **Provider prefixes** (like `groq/`, `xai/`, `anthropic/`) tell LiteLLM where to route. The Base URL is only used for models without a prefix.

### Whisper Setup (Transcription)

| Mode | Description | Cost |
|------|-------------|------|
| **Groq** | Fast cloud transcription (recommended) | ~$0.04/hour |
| **Local** | Runs on your machine | Free (requires RAM/GPU) |
| **Remote** | OpenAI Whisper API | ~$0.006/min |

---

## 🎯 Ad Detection Presets

Podly includes 3 preset aggressiveness levels:

| Preset | Confidence | Description |
|--------|------------|-------------|
| **Conservative** | 80% | Only obvious ads — sponsor reads, "brought to you by" |
| **Balanced** | 70% | Default — typical ads while preserving content |
| **Aggressive** | 55% | All promotional content including host-read ads, self-promotion |

All presets are designed to flag **complete ad blocks**, not just the announcement. When an ad is detected, all consecutive segments within that ad are flagged for removal.

You can also create custom presets with your own prompts in the Presets page.

---

## 💰 Cost Breakdown

*Estimated monthly cost for ~6 podcasts, 6 hours/week*

| Setup | Hosting | Transcription | LLM | Total |
|-------|---------|---------------|-----|-------|
| **Preview Server** | Shared | Included | Included | ~$1/3hrs |
| **Local + Groq** | Free | ~$1 | ~$1.50 | **~$2.50/mo** |
| **Local + Local Whisper** | Free | Free | ~$1.50 | **~$1.50/mo** |
| **Railway + Groq** | ~$5 | ~$1 | ~$1.50 | **~$7.50/mo** |

---

## 🔐 Authentication (Optional)

Enable multi-user support with protected RSS feeds:

```bash
export REQUIRE_AUTH=true
export PODLY_ADMIN_USERNAME='admin'
export PODLY_ADMIN_PASSWORD='your-secure-password'
export PODLY_SECRET_KEY='64-character-random-string'
```

Protected feeds use per-feed access tokens so your podcast app can subscribe without exposing your password.

---

## 🛠️ Development

### Frontend Development (Hot Reload)

```bash
cd frontend
npm install
npm run dev  # Runs on http://localhost:5173
```

The Vite dev server proxies API calls to the backend on port 5001.

### Backend Development

```bash
# With Docker (recommended)
docker compose -f compose.dev.cpu.yml up --build

# Or natively with pipenv
pipenv install
pipenv run flask --app ./src/main.py run
```

### Running Tests

```bash
pipenv run pytest src/tests/
```

---

## 📁 Project Structure

```
podly_pure_podcasts/
├── frontend/          # React + TypeScript + Vite
│   ├── src/
│   │   ├── pages/     # Dashboard, Podcasts, Jobs, Presets, Settings
│   │   ├── components/
│   │   └── services/  # API client
├── src/
│   ├── app/           # Flask backend
│   │   ├── routes/    # API endpoints
│   │   └── models.py  # Database models
│   ├── podcast_processor/  # Core processing logic
│   └── migrations/    # Alembic database migrations
└── docs/              # Documentation
```

---

## 🤝 Contributing

We welcome contributions! See our [contributing guide](docs/contributors.md).

### Quick Links
- [Discord Community](https://discord.gg/FRB98GtF6N) — Get help, share feedback
- [Issue Tracker](https://github.com/jdrbc/podly_pure_podcasts/issues) — Report bugs, request features
- [Prompt Presets Guide](docs/PROMPT_PRESETS_AND_STATISTICS.md) — Customize ad detection

---

## 📄 License

MIT License — see [LICENCE](LICENCE) for details.

---

<div align="center">
  <p>Made with 🦄 by the Podly community</p>
  <p>
    <a href="https://discord.gg/FRB98GtF6N">Discord</a> •
    <a href="https://github.com/jdrbc/podly_pure_podcasts">Original Podly</a> •
    <a href="https://podly.up.railway.app/">Try It</a>
  </p>
</div>
