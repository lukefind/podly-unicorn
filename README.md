<div align="center">
  <img src="frontend/public/images/social-card1200x630.png" alt="Podly social card" width="900" />
  
  <p>
    <a href="https://github.com/podly-pure-podcasts/podly_pure_podcasts"><img src="https://img.shields.io/badge/GitHub-podly-blue?logo=github" alt="GitHub"></a>
    <a href="https://github.com/podly-pure-podcasts/podly_pure_podcasts/blob/main/LICENCE"><img src="https://img.shields.io/badge/License-MIT-green.svg" alt="License"></a>
    <a href="https://discord.gg/FRB98GtF6N"><img src="https://img.shields.io/badge/Discord-Join%20Community-5865F2?logo=discord&logoColor=white" alt="Discord"></a>
  </p>
</div>

---

## What is Podly?

Podly is a self-hosted podcast ad-removal server with a web app. It transcribes episodes, uses LLMs to detect ad segments, and publishes cleaned RSS feeds you can use in your normal podcast player.

You manage feeds, presets, processing, and users in the browser. Listening still happens in your podcast app, through direct downloads, or in Podly's built-in audio player.

<div align="center">
  <img src="frontend/public/images/screenshots/dashboard-desktop.png" alt="Podly Dashboard" width="700" />
  <p><em>Dashboard showing podcast statistics and ad removal progress</em></p>
</div>

<div align="center">
  <table>
    <tr>
      <td><img src="frontend/public/images/screenshots/podcasts-mobile.jpeg" alt="Mobile View" width="300" /></td>
      <td><img src="frontend/public/images/screenshots/presets-mobile.jpeg" alt="Presets Page" width="300" /></td>
    </tr>
    <tr>
      <td align="center"><em>Mobile podcasts view</em></td>
      <td align="center"><em>Presets page</em></td>
    </tr>
  </table>
</div>

---

## Highlights

### Podcast-App Workflow
- Add shows by search, by browsing feeds already on the server, or by pasting an RSS URL
- Copy either a per-show Podly RSS feed or one combined all-in-one feed
- Start processing from the web UI or from the `Process this episode (remove ads)` link inside episode notes
- Listen through your podcast app, download audio directly, or use the built-in player

### Processing Controls
- On-demand processing by default so RSS polling does not accidentally start jobs
- Optional auto-process for new episodes on a per-feed basis
- Reprocess episodes after changing prompts or settings
- Recent episodes auto-enable when you add a show, and new releases auto-enable as they arrive

### Ad Detection and AI Configuration
- Built-in Conservative, Balanced, and Aggressive presets
- Custom presets and per-show default preset overrides
- Saved encrypted API key profiles in the Settings UI
- Groq, xAI, OpenAI, Anthropic, Google Gemini, and custom OpenAI-compatible providers
- Local, remote, or Groq-based Whisper transcription

### Multi-User and Admin Features
- Session auth for the web app with tokenized RSS/feed links for podcast apps
- Public and private feed subscriptions plus server-wide podcast discovery
- Optional signup requests with admin approval and password reset flows
- Feed visibility controls, user statistics, subscription management, and repair tools

### UI and Mobile
- Responsive desktop and mobile web app
- Blue, Light, and Dark themes
- Installable PWA over HTTPS
- First-run onboarding plus an in-app help modal

---

## How It Works

1. **Add a podcast** — Search, browse, or paste an RSS feed URL
2. **Enable episodes** — Podly auto-enables recent episodes, and you can enable/disable anything else
3. **Choose your feed** — Copy either a per-show Podly RSS link or the combined all-in-one feed
4. **Start processing** — Use the web UI or tap the trigger link in your podcast app
5. **Listen ad-free** — Refresh your feed and play the processed version, or download/play it from the web app

### On-Demand Processing

Podly does **not** process every episode automatically by default. That keeps resource usage predictable and avoids accidental mass processing from RSS polling or podcast-app prefetching.

You can start processing in three ways:
1. **Web UI** — Click **Process** on an enabled episode
2. **Podcast app** — Tap `Process this episode (remove ads)` in the episode description
3. **Auto-process** — Enable it in show settings to process new episodes after feed refresh

When you trigger an episode from your podcast app:
1. A progress page opens in the browser
2. When it says **Episode Ready**, close the tab
3. Refresh the feed in your podcast app and play the processed episode

### Authentication Modes and RSS Behavior

`REQUIRE_AUTH=true` is recommended for podcast app use.

- `REQUIRE_AUTH=true`: Podly generates tokenized RSS/feed links (`feed_token` + `feed_secret`) so podcast apps can use feed, trigger, and download flows directly.
- `REQUIRE_AUTH=false`: Feed URLs are public, but podcast-app trigger/download links are more limited in the current release because those endpoints still rely on token or session auth.

If logs show `reason=not_whitelisted`, that episode is disabled for processing. Enable it in the Podcasts page first.

---

## Quick Start (Docker)

### Prerequisites
- Docker and Docker Compose
- LLM API key from [Groq](https://console.groq.com/keys) (free) or OpenAI/xAI

### 1. Clone and Configure

```bash
git clone https://github.com/podly-pure-podcasts/podly_pure_podcasts.git
cd podly_pure_podcasts
cp .env.local.example .env.local
```

Edit `.env.local`:

```bash
# Recommended: enable authentication for podcast-app trigger/download links
REQUIRE_AUTH=true
PODLY_ADMIN_USERNAME=admin
PODLY_ADMIN_PASSWORD=your-secure-password
PODLY_SECRET_KEY=replace-with-a-long-random-secret

# Local HTTP only (no HTTPS): required so login cookies work on localhost
# SESSION_COOKIE_SECURE=false
```

That's it for `.env.local`. After starting, open **Settings** in the web UI and enter your Groq API key in **Quick Setup** — it configures both transcription and ad detection in one step.

If you run with `REQUIRE_AUTH=true` on plain `http://` (no TLS), you must set `SESSION_COOKIE_SECURE=false`.  
If you are behind HTTPS (recommended), leave it unset.

### 2. Start

```bash
docker compose up -d --build
```

### 3. Access

Open http://localhost:5001

---

## Install as a Mobile App (PWA)

Podly can be installed as a Progressive Web App on your phone or tablet for a native app-like experience — no app store required.

### Android (Chrome)
1. Open your Podly server URL in Chrome
2. Tap the **three-dot menu** (⋮) → **"Add to Home screen"** or **"Install app"**
3. Confirm the installation
4. Podly appears on your home screen as a standalone app

### iOS (Safari)
1. Open your Podly server URL in Safari
2. Tap the **Share button** (📤) → **"Add to Home Screen"**
3. Tap **"Add"**
4. Podly appears on your home screen as a standalone app

> **Note:** Your Podly server must be served over HTTPS for PWA installation to work. If running locally without HTTPS, PWA install will not be available.

---

## Configuration

### LLM Providers

You can configure LLM providers in **Settings** after startup, or through environment variables in `.env.local`. The fastest path is **Settings → Quick Setup** with a Groq key. For advanced setups, use **Settings → LLM Configuration** to save encrypted key profiles or point Podly at env-backed keys.

| Provider | Example Models | Notes |
|----------|----------------|-------|
| **Groq** | `groq/openai/gpt-oss-120b`, `groq/llama-3.3-70b-versatile` | Fast, good default, free tier available |
| **xAI (Grok)** | `xai/grok-3`, `xai/grok-3-mini` | Strong ad detection quality |
| **OpenAI** | `gpt-4o-mini`, `gpt-4o`, `gpt-4.1` | Standard OpenAI-compatible path |
| **Anthropic** | `anthropic/claude-3-7-sonnet-latest` | High quality alternative |
| **Google Gemini** | `gemini/gemini-2.0-flash` | Fast and cost-effective |
| **Custom / Other** | OpenAI-compatible models | Use a custom base URL and API key |

Models with a provider prefix (e.g. `groq/`, `xai/`, `anthropic/`) are routed automatically — no Base URL needed.

For xAI Grok via env vars:
```bash
LLM_API_KEY=xai-your-key
LLM_MODEL=xai/grok-3
# OPENAI_BASE_URL is optional — xai/ prefix auto-routes
```

> **Tip:** You can save encrypted API keys or select env-backed key references in **Settings → LLM Configuration** without editing the runtime config by hand.

### Whisper (Transcription)

| Mode | Config | Notes |
|------|--------|-------|
| **Groq** | `WHISPER_TYPE=groq` | Fast, recommended default |
| **Local** | `WHISPER_TYPE=local` | Runs on your own machine, no transcription API cost |
| **Remote** | `WHISPER_TYPE=remote` | Use an OpenAI-compatible remote Whisper endpoint |

---

## Updating

```bash
cd podly_pure_podcasts
git pull
docker compose up -d --build
```

Database migrations run automatically on startup — no manual steps needed.

---

## Upgrading from Podly Pure Podcasts / Earlier Versions

If you're migrating from an older version of Podly, your `.env.local` likely has LLM settings that will **override** the new Settings UI.

### Clean up your `.env.local`

**Before (old-style — env vars control everything):**
```bash
GROQ_API_KEY=gsk_...
LLM_API_KEY=xai-...
LLM_MODEL=xai/grok-3
OPENAI_BASE_URL=https://api.x.ai/v1
WHISPER_TYPE=groq
```

**After (recommended — let the UI manage everything):**
```bash
# Auth (keep as-is)
REQUIRE_AUTH=true
PODLY_ADMIN_USERNAME=...
PODLY_ADMIN_PASSWORD=...
PODLY_SECRET_KEY=...
```

All LLM and Whisper settings are now configurable in **Settings** — no env vars needed.

**What changed and why:**

| Env var | Action | Reason |
|---------|--------|--------|
| `GROQ_API_KEY` | **Remove** | Enter your Groq key in **Settings → Quick Setup** instead. It's saved encrypted in the database and configures both Whisper and LLM. |
| `LLM_API_KEY` | **Remove** | Manage your LLM API key in **Settings → LLM Configuration**. You can save encrypted key profiles and switch providers without restarting. |
| `LLM_MODEL` | **Remove** | Select your model in the Settings UI. Env var overrides the UI if present. |
| `OPENAI_BASE_URL` | **Remove** | No longer needed — models with a provider prefix (e.g. `xai/grok-3`, `groq/...`) are routed automatically by LiteLLM. |
| `WHISPER_TYPE` | **Remove** | Select Whisper mode (groq/local/remote) in **Settings → Whisper**. Default is groq. |

> **Note:** If you prefer env vars over the UI, that still works — just be aware that any `GROQ_API_KEY`, `WHISPER_TYPE`, `LLM_MODEL`, `LLM_API_KEY`, or `OPENAI_BASE_URL` set in `.env.local` will override what you configure in Settings, and the UI will show a warning.

### After editing `.env.local`

```bash
docker compose restart
```

Then open **Settings → LLM Configuration** to select your provider, model, and API key source.

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

## Contributing

See [contributing guide](docs/contributors.md) for local setup & contribution instructions.

---

<div align="center">
  <p>
    <a href="https://github.com/podly-pure-podcasts/podly_pure_podcasts">GitHub</a> •
    <a href="https://github.com/podly-pure-podcasts/podly_pure_podcasts/issues">Issues</a> •
    <a href="https://discord.gg/FRB98GtF6N">Discord</a>
  </p>
</div>
