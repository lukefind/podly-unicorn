# How To Run: Ultimate Beginner's Guide

This guide will walk you through setting up Podly from scratch using Docker. Podly creates ad-free RSS feeds for podcasts by automatically detecting and removing advertisement segments.

## Highly Recommend!

Want an expert to guide you through the setup? Download an AI powered IDE like cursor https://www.cursor.com/ or windsurf https://windsurf.com/

Most IDEs have a free tier you can use to get started. Alternatively, you can use your own [LLM API key in Cursor](https://docs.cursor.com/settings/api-keys) (you'll need a key for Podly anyways).

Open the AI chat in the IDE. Enable 'Agent' mode if available, which will allow the IDE to help you run commands, view the output, and debug or take corrective steps if necessary.

Paste one of the prompts below into the chat box.

If you don't have the repo downloaded:

```
Help me install docker and run Podly https://github.com/jdrbc/podly_pure_podcasts
After the project is cloned, help me:
- install docker & docker compose
- run `./run_podly_docker.sh --build` then `./run_podly_docker.sh -d`
- configure the app via the web UI at http://localhost:5001/config
Be sure to check if a dependency is already installed before downloading.
We recommend Docker because installing ffmpeg & local whisper can be difficult.
The Docker image has both ffmpeg & local whisper preconfigured.
Podly works with many different LLMs, it does not require an OpenAI key.
Check your work by retrieving the index page from localhost:5001 at the end.
```

If you do have the repo pulled, open this file and prompt:

```
Review this project, follow this guide and start Podly on my computer.
Briefly, help me:
- install docker & docker compose
- run `./run_podly_docker.sh --build` and then `./run_podly_docker.sh -d`
- configure the app via the web UI at http://localhost:5001/config
Be sure to check if a dependency is already installed before downloading.
We recommend docker because installing ffmpeg & local whisper can be difficult.
The docker image has both ffmpeg & local whisper preconfigured.
Podly works with many different LLMs; it does not need to work with OpenAI.
Check your work by retrieving the index page from localhost:5001 at the end.
```

## Prerequisites

### Install Docker and Docker Compose

#### On Windows:

1. Download and install [Docker Desktop for Windows](https://docs.docker.com/desktop/install/windows-install/)
2. During installation, make sure "Use WSL 2 instead of Hyper-V" is checked
3. Restart your computer when prompted
4. Open Docker Desktop and wait for it to start completely

#### On macOS:

1. Download and install [Docker Desktop for Mac](https://docs.docker.com/desktop/install/mac-install/)
2. Drag Docker to your Applications folder
3. Launch Docker Desktop from Applications
4. Follow the setup assistant

#### On Linux (Ubuntu/Debian):

```bash
# Update package index
sudo apt update

# Install Docker
sudo apt install docker.io docker-compose-v2

# Add your user to the docker group
sudo usermod -aG docker $USER

# Log out and log back in for group changes to take effect
```

#### Verify Installation:

Open a terminal/command prompt and run:

```bash
docker --version
docker compose version
```

You should see version information for both commands.

### 2. Get an LLM API Key

Podly works with many LLM providers. We recommend **Groq** for the best price/performance:

#### Recommended: Groq (Fast & Cheap)

1. Go to [console.groq.com](https://console.groq.com/keys)
2. Sign up for a free account
3. Click "Create API Key"
4. Copy the key (starts with `gsk_`) and save it somewhere safe

> **Tip**: Set a billing limit at [Settings → Billing → Limits](https://console.groq.com/settings/billing) to control costs (~$2-5/month is typical).

#### Alternative: OpenAI

1. Go to [platform.openai.com](https://platform.openai.com/)
2. Navigate to [API Keys](https://platform.openai.com/api-keys)
3. Click "Create new secret key"
4. Copy the key (starts with `sk-`) and save it

#### Other Providers

Podly uses [LiteLLM](https://docs.litellm.ai/) and supports 100+ providers including Anthropic, Google Gemini, local Ollama, and more. See the main README for configuration details.

## Setup Podly

### Download the Project

```bash
git clone https://github.com/normand1/podly_pure_podcasts.git
cd podly_pure_podcasts
```

## Running Podly

### Run the Application via Docker

```bash
chmod +x run_podly_docker.sh
./run_podly_docker.sh --build
./run_podly_docker.sh            # foreground
./run_podly_docker.sh -d         # detached
```

### Optional: Enable Authentication

The Docker image reads environment variables from `.env` files or your shell. To require login:

1. Export the variables before running Podly, or add them to `config/.env`:

```bash
export REQUIRE_AUTH=true
export PODLY_ADMIN_USERNAME='podly_admin'
export PODLY_ADMIN_PASSWORD='SuperSecurePass!2024'
export PODLY_SECRET_KEY='replace-with-a-strong-64-char-secret'
```

2. Start Podly as usual. On first boot with auth enabled and an empty database, the admin account is created automatically. If you are turning auth on for an existing volume, clear the `sqlite3.db` file so the bootstrap can succeed.

3. Sign in at `http://localhost:5001`, then visit the Config page to change your password, add users, and copy RSS URLs with the "Copy protected feed" button. Podly generates feed-specific access tokens and embeds them in the link so podcast players can subscribe without exposing your main password. Remember to update your environment variables whenever you rotate the admin password.

### First Run

1. Docker will download and build the necessary image (this may take 5-15 minutes)
2. Look for "Running on http://0.0.0.0:5001"
3. Open your browser to `http://localhost:5001`
4. Configure settings at `http://localhost:5001/config`
   - Alternatively, set secrets via Docker env file `.env.local` in the project root and restart the container. See .env.local.example

## Advanced Options

```bash
# Force CPU-only processing (if you have GPU issues)
./run_podly_docker.sh --cpu

# Force GPU processing
./run_podly_docker.sh --gpu

# Just build the container without running
./run_podly_docker.sh --build

# Test build from scratch (useful for troubleshooting)
./run_podly_docker.sh --test-build
```

## Using Podly

### Adding Your First Podcast

1. In the web interface, look for an "Add Podcast" or similar button
2. Paste the RSS feed URL of your podcast
3. Podly will start processing new episodes automatically
4. Processed episodes will have advertisements removed

### Getting Your Ad-Free RSS Feed

1. After adding a podcast, Podly will generate a new RSS feed URL
2. Use this new URL in your podcast app instead of the original
3. Your podcast app will now download ad-free versions!

## Troubleshooting

### "Docker command not found"

- Make sure Docker Desktop is running
- On Windows, restart your terminal after installing Docker
- On Linux, make sure you logged out and back in after adding yourself to the docker group

### Cannot connect to the Docker daemon. Is the docker daemon running?

- If using docker desktop, open up the app, otherwise start the daemon

### "Permission denied" errors

- On macOS/Linux, make sure the script is executable: `chmod +x run_podly_docker.sh`
- On Windows, try running Command Prompt as Administrator

### LLM API errors

- Double-check your API key in the Settings page
- Make sure you have billing set up with your provider (Groq, OpenAI, etc.)
- Check your usage limits haven't been exceeded
- If using Groq, ensure your key starts with `gsk_`

### Port 5001 already in use

- Another application is using port 5001
- **Docker users**: Either stop that application or modify the port in `compose.dev.cpu.yml` and `compose.yml`
- **Native users**: Change the port in the Config page under App settings
- To kill processes on that port run `lsof -i :5001 | grep LISTEN | awk '{print $2}' | xargs kill -9`

### Out of memory errors

- Close other applications to free up RAM
- Consider using `--cpu` flag if you have limited memory

## Stopping Podly

To stop the application:

1. In the terminal where Podly is running, press `Ctrl+C`
2. Wait for the container to stop gracefully

## Getting Help

If you encounter issues ask in our discord, we're friendly!

https://discord.gg/FRB98GtF6N

## What's Next?

Once you have Podly running:

- Explore the web interface to add more podcasts
- Configure settings in the Config page
- Consider setting up automatic background processing
- Enjoy your ad-free podcasts!
