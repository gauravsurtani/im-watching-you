# Lifelogger

**Privacy-first personal "second brain"** - A local-first life-logging system combining ActivityWatch for activity tracking, Whisper.cpp for audio transcription, LLM processing (local Ollama or free cloud via OpenRouter), and Syncthing for cross-device sync.

**Flexible LLM options**: Run entirely local for maximum privacy, use free cloud models via OpenRouter (no GPU needed), or hybrid mode that routes sensitive data locally while using cloud for classification.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         CLIENT DEVICES                                   │
├──────────────────┬──────────────────┬──────────────────────────────────┤
│   Mac Desktop    │  Windows PC      │  Android (Pixel)                 │
│   ActivityWatch  │  ActivityWatch   │  ActivityWatch Android           │
│   Export Script  │  Export Script   │  Audio Capture + Whisper         │
└────────┬─────────┴────────┬─────────┴───────────────┬──────────────────┘
         │                  │                         │
         └──────────────────┼─────────────────────────┘
                            │ Syncthing (P2P encrypted)
                            ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                      HOME SERVER                                         │
├─────────────────────────────────────────────────────────────────────────┤
│  Data Ingest → TimescaleDB → Ollama (LLM) → Notifications (ntfy)        │
└─────────────────────────────────────────────────────────────────────────┘
```

## Features

- **Cross-platform activity tracking** via ActivityWatch (Mac, Windows, Android)
- **Audio transcription** with Whisper.cpp (on-device for Android)
- **AI-powered daily digests** using LLMs (local Ollama or free OpenRouter cloud)
- **Hybrid LLM routing** - Cloud for classification, local for sensitive transcripts
- **Push notifications** via ntfy (self-hosted)
- **P2P encrypted sync** with Syncthing
- **Time-series database** with TimescaleDB for efficient queries
- **Web dashboard** with search, stats, and event browser
- **Full-text search** with fuzzy matching support

## Quick Start

### 1. Server Setup

```bash
# Clone the repository
git clone https://github.com/yourusername/im-watching-you.git
cd im-watching-you

# Start Docker services
cd docker
cp .env.example .env
# Edit .env with your settings
docker compose up -d

# Wait for services to be ready
docker compose ps
```

### 2. Configure LLM (Choose One)

**Option A: OpenRouter Cloud (Free, No GPU)**
```bash
# Get your free API key at https://openrouter.ai/keys
# Add to .env:
LIFELOGGER_OPENROUTER_API_KEY=your_key_here
LIFELOGGER_LLM_PROVIDER=cloud
```

**Option B: Local Ollama (Maximum Privacy, Requires GPU)**
```bash
docker exec lifelogger-ollama ollama pull qwen2.5:7b
# In .env:
LIFELOGGER_LLM_PROVIDER=local
```

**Option C: Hybrid (Best of Both)**
```bash
# Set up both, then in .env:
LIFELOGGER_LLM_PROVIDER=hybrid
# Cloud handles classification, local handles sensitive transcripts
```

### 3. Install Python Package

```bash
# From repository root
pip install -e .

# Or with dev dependencies
pip install -e ".[dev]"
```

### 3. Configure Syncthing

1. Open Syncthing UI at http://localhost:8384
2. Add your client devices
3. Configure shared folders:
   - `~/Syncthing/lifelogger/activity` - ActivityWatch exports
   - `~/Syncthing/lifelogger/transcripts` - Audio transcripts

### 4. Client Device Setup

#### Mac/Linux

```bash
# Install ActivityWatch
# Download from https://activitywatch.net

# Install Syncthing
# Download from https://syncthing.net

# Set up export script
cp scripts/clients/export_activitywatch.py ~/bin/
chmod +x ~/bin/export_activitywatch.py

# Add to crontab (hourly export)
crontab -e
# Add: 0 * * * * /usr/bin/python3 ~/bin/export_activitywatch.py
```

#### Windows

1. Install [ActivityWatch](https://activitywatch.net)
2. Install [Syncthing](https://syncthing.net)
3. Copy `scripts/clients/export_activitywatch.ps1` to a local folder
4. Create a Task Scheduler task to run it hourly

### 5. Set Up Server Cron Jobs

```bash
# Edit crontab
crontab -e

# Add:
# Hourly data ingestion
0 * * * * cd /path/to/im-watching-you && python -m lifelogger ingest

# Daily digest at 7 AM
0 7 * * * cd /path/to/im-watching-you && python -m lifelogger digest --send
```

## Claude Desktop Integration (MCP)

Connect Lifelogger to Claude Desktop and ask questions about your life:

- *"What was I working on last Tuesday?"*
- *"How much time did I spend coding this week?"*
- *"When did I last discuss the budget?"*
- *"Am I more productive in mornings or afternoons?"*

### Setup

1. **Start the MCP server** (to test):
   ```bash
   lifelogger mcp-server
   ```

2. **Add to Claude Desktop config** (`~/.config/claude/claude_desktop_config.json` on Linux/Mac, `%APPDATA%\Claude\claude_desktop_config.json` on Windows):
   ```json
   {
     "mcpServers": {
       "lifelogger": {
         "command": "lifelogger-mcp",
         "env": {
           "LIFELOGGER_DB_HOST": "localhost",
           "LIFELOGGER_DB_PORT": "5432",
           "LIFELOGGER_DB_NAME": "lifelogger",
           "LIFELOGGER_DB_USER": "lifelogger",
           "LIFELOGGER_DB_PASSWORD": "your_password"
         }
       }
     }
   }
   ```

3. **Restart Claude Desktop** - you'll see "lifelogger" in the MCP tools list

### Available Tools (What Claude Can Do)

| Tool | What It Does |
|------|--------------|
| `search_activities` | Search through app usage, websites, window titles |
| `get_daily_stats` | Get stats for any day (hours, top apps, productivity) |
| `get_productivity_summary` | Productivity metrics over any time period |
| `get_recent_activities` | What you've been doing recently |
| `search_transcripts` | Search through conversation transcripts |
| `get_app_usage` | Detailed usage stats for any app |
| `compare_periods` | Compare this week vs last week, etc. |
| `get_context_around_time` | Activities before/after a specific moment |
| `get_category_breakdown` | Time by category (Work, Entertainment, etc.) |

All data stays local - Claude queries your MCP server, which queries your local database.

## CLI Commands

```bash
# Run data ingestion
lifelogger ingest

# Generate today's digest
lifelogger digest

# Generate and send digest
lifelogger digest --send

# View activity stats
lifelogger stats --date 2024-01-07

# List registered devices
lifelogger devices

# Send test notification
lifelogger notify "Test message" -t "Test Title"

# Start MCP server for Claude Desktop
lifelogger mcp-server

# Interactive setup guide
lifelogger setup
```

## Configuration

Configuration is via environment variables (or `.env` file):

```bash
# Database
LIFELOGGER_DB_HOST=localhost
LIFELOGGER_DB_PORT=5432
LIFELOGGER_DB_NAME=lifelogger
LIFELOGGER_DB_USER=lifelogger
LIFELOGGER_DB_PASSWORD=your-password

# Ollama
LIFELOGGER_OLLAMA_HOST=localhost
LIFELOGGER_OLLAMA_PORT=11434
LIFELOGGER_OLLAMA_MODEL=qwen2.5:7b

# Syncthing paths
LIFELOGGER_SYNC_BASE_PATH=/home/user/Syncthing/lifelogger

# Notifications
LIFELOGGER_NTFY_SERVER=http://localhost:8080
LIFELOGGER_NTFY_TOPIC=lifelogger

# Data retention (days)
LIFELOGGER_AUDIO_RETENTION_DAYS=30
LIFELOGGER_TRANSCRIPT_RETENTION_DAYS=365
```

## Project Structure

```
im-watching-you/
├── lifelogger/                 # Python package
│   ├── core/                   # Core modules
│   │   ├── config.py           # Settings management
│   │   ├── database.py         # TimescaleDB operations
│   │   ├── models.py           # Pydantic models
│   │   └── ingest.py           # Data ingestion service
│   ├── sources/                # Data source adapters
│   │   ├── activitywatch.py    # ActivityWatch importer
│   │   ├── transcripts.py      # Transcript importer
│   │   └── youtube.py          # YouTube history importer
│   ├── exporters/              # Output generators
│   │   ├── digest.py           # Daily digest with Ollama
│   │   └── notifications.py    # Notification delivery
│   └── cli.py                  # Command-line interface
├── scripts/
│   └── clients/                # Client-side scripts
│       ├── export_activitywatch.py    # Python export script
│       └── export_activitywatch.ps1   # Windows PowerShell
├── docker/
│   ├── docker-compose.yml      # Server services
│   └── .env.example            # Environment template
├── migrations/
│   └── 001_initial_schema.sql  # Database schema
└── android/                    # Android app (future)
```

## Hardware Requirements

### Server
- **CPU**: Any modern x86-64
- **RAM**: 16GB minimum (32GB recommended for larger models)
- **GPU**: NVIDIA GPU with 8GB+ VRAM for Ollama (optional but recommended)
- **Storage**: 100GB+ SSD

### Model Recommendations

| VRAM | Recommended Model | Performance |
|------|-------------------|-------------|
| 8GB  | Qwen2.5 7B        | ~40 tok/s   |
| 16GB | Qwen2.5 14B       | ~30 tok/s   |

## Extending

### Adding New Data Sources

Create a new module in `lifelogger/sources/`:

```python
# lifelogger/sources/newservice.py
from lifelogger.core.models import ActivityEvent, EventType

class NewServiceSource:
    async def import_data(self, path: Path) -> AsyncIterator[ActivityEvent]:
        # Parse your data format
        yield ActivityEvent(
            timestamp=...,
            device_id="newservice",
            event_type=EventType.CUSTOM,
            data={...}
        )
```

### Custom Notification Channels

Add any [Apprise-supported](https://github.com/caronc/apprise) service:

```python
LIFELOGGER_NOTIFICATION_CHANNELS='["ntfy://localhost/alerts", "tgram://bot_token/chat_id"]'
```

## Privacy & Security

- **Local-first architecture** - everything runs on your hardware
- **Hybrid LLM routing** - sensitive data (transcripts, URLs) stays local even when using cloud classification
- **Syncthing uses TLS encryption** for device-to-device sync
- **Database is localhost-only** by default
- **Audio files auto-delete** after configurable retention period
- **MCP integration is local** - Claude queries your local server, data never leaves your machine
- **Configurable privacy settings** - control what goes to cloud vs stays local

## License

MIT
