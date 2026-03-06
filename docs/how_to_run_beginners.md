# User Guide

Podly Unicorn removes ads from podcasts using AI. You add podcasts, subscribe to the Podly RSS feed in your podcast app, and trigger processing when you want to listen ad-free.

---

## Quick Start

### 1. Get an API Key

Sign up at [console.groq.com](https://console.groq.com/keys) and create an API key (free tier available).

### 2. Install & Run

```bash
git clone https://github.com/podly-pure-podcasts/podly_pure_podcasts.git
cd podly_pure_podcasts
cp .env.local.example .env.local
# Edit .env.local with auth settings (recommended):
# REQUIRE_AUTH=true
# PODLY_ADMIN_USERNAME=admin
# PODLY_ADMIN_PASSWORD=choose-a-strong-password
# PODLY_SECRET_KEY=replace-with-a-long-random-secret
# SESSION_COOKIE_SECURE=false  # only if running local HTTP (no HTTPS)
docker compose up -d --build
```

No API keys needed in `.env.local` — enter your Groq API key in **Settings → Quick Setup** after starting.

Open http://localhost:5001

### 3. Add a Podcast

1. Click **Add Podcast**
2. Paste an RSS feed URL or search the catalog
3. Click **Subscribe**

### 4. Get Your RSS Feed

1. Go to **Podcasts** page
2. Click **Podly RSS** on any show (or **All-in-One Podly RSS** for all shows combined)
3. Add this URL to your podcast app (Apple Podcasts, Overcast, Pocket Casts, etc.)

---

## Processing Episodes

Episodes are processed **on-demand** when you request it. This saves resources and prevents accidental processing.

### How to Process an Episode

1. Open an episode in your podcast app
2. In the episode description, tap **"Process this episode (remove ads)"**
3. A progress page opens in your browser
4. When it says **"Episode Ready"**, close the tab
5. Return to your podcast app and refresh the feed
6. Play the ad-free episode

### Auto-Process (Optional)

Enable **Auto process new episodes** in show settings to automatically process new episodes when they're released.

### Auth Requirement for Podcast Apps

For the best RSS experience in podcast apps, set `REQUIRE_AUTH=true`.

- With auth enabled: Podly issues tokenized RSS links that podcast apps can use for trigger + download flows.
- With auth disabled: feeds are public, but trigger/download links in podcast apps may fail in the current release because those endpoints expect token/session auth.

---

## Key Features

| Feature | Description |
|---------|-------------|
| **On-demand processing** | Tap trigger link in episode description to start |
| **Combined feed** | One RSS URL for all your podcasts |
| **Auto-process** | Automatically process new episodes |
| **Prompt presets** | Conservative, Balanced, or Aggressive ad detection |
| **Multi-user** | Each user has their own subscriptions |

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Episode not processed | Tap the trigger link in the episode description |
| Logs show `reason=not_whitelisted` | Enable that episode in Podly (it is currently disabled for processing) |
| Podcast app shows `Authentication required` or trigger link fails when auth is off | Enable `REQUIRE_AUTH=true`, restart, then copy a fresh Podly RSS URL from the UI |
| Processing stuck | Check logs: `docker logs -f podly-pure-podcasts` |
| API errors | Verify your API key in Settings |
| Port in use | Stop other apps on port 5001 or change port in compose.yml |

---

## Common Commands

```bash
docker compose up -d --build    # Start/rebuild
docker compose restart          # Restart
docker logs -f podly-pure-podcasts  # View logs
docker compose down             # Stop
```

---

## Upgrading from an Older Version?

If you previously had `GROQ_API_KEY`, `WHISPER_TYPE`, `LLM_API_KEY`, `LLM_MODEL`, or `OPENAI_BASE_URL` in your `.env.local`, those env vars **override** the Settings UI. To use the new UI-based configuration:

1. Remove all of those vars from `.env.local` (keep only auth settings like `REQUIRE_AUTH`, `PODLY_ADMIN_USERNAME`, etc.)
2. Restart: `docker compose restart`
3. Open **Settings → Quick Setup** to enter your Groq key (configures both Whisper and LLM)
4. Or use **Settings → LLM Configuration** for advanced provider selection

See the [full upgrade guide](../README.md#upgrading-from-podly-pure-podcasts--earlier-versions) in the README.

---

## Getting Help

- [GitHub Issues](https://github.com/podly-pure-podcasts/podly_pure_podcasts/issues)
- [Discord Community](https://discord.gg/FRB98GtF6N)
