# Lifelogger Troubleshooting Guide

## Quick Diagnostics

Run the health check to see what's working and what's not:

```bash
lifelogger health
```

This checks:
- Database connectivity and data freshness
- Ollama (local LLM) availability
- OpenRouter (cloud LLM) connectivity
- Syncthing folder status
- ActivityWatch data files

---

## Common Issues and Fixes

### 1. No Data Being Collected

**Symptoms:**
- `lifelogger stats` shows 0 events
- Daily digest is empty

**Check:**
```bash
lifelogger health
```

**Possible causes:**

| Cause | Fix |
|-------|-----|
| ActivityWatch not running | Start ActivityWatch on client device |
| Export script not running | Set up cron job for `export_activitywatch.py` |
| Syncthing not syncing | Check http://localhost:8384 for sync status |
| Ingest not running | Run `lifelogger ingest` or set up cron |

**Quick workaround - Manual logging:**
```bash
# Log what you're doing manually
lifelogger quick-log "Working on project X" -d 60
lifelogger log -a "VS Code" -t "API refactor" -d 90 -c Work --productive
```

---

### 2. Database Connection Failed

**Symptoms:**
- "Cannot connect to database" errors
- All CLI commands fail

**Fix:**
```bash
# Start the database
cd docker && docker compose up -d timescaledb

# Check it's running
docker ps | grep timescaledb

# Check logs if issues
docker logs lifelogger-db
```

**If database doesn't exist:**
```bash
docker exec -it lifelogger-db psql -U lifelogger -c "CREATE DATABASE lifelogger;"
```

---

### 3. LLM Classification Not Working

**Symptoms:**
- Events stored but no classification
- "LLM unavailable" errors

**For OpenRouter (Cloud):**
```bash
# Check your API key is set
echo $LIFELOGGER_OPENROUTER_API_KEY

# Test with curl
curl -H "Authorization: Bearer $LIFELOGGER_OPENROUTER_API_KEY" \
  https://openrouter.ai/api/v1/models
```

**For Ollama (Local):**
```bash
# Start Ollama
cd docker && docker compose up -d ollama

# Pull a model
docker exec lifelogger-ollama ollama pull qwen2.5:7b

# Test it
docker exec lifelogger-ollama ollama run qwen2.5:7b "Hello"
```

**Fallback strategy:**
```bash
# Use cloud if local fails (in .env)
LIFELOGGER_LLM_PROVIDER=cloud_fallback
```

---

### 4. Syncthing Not Syncing

**Symptoms:**
- Files exist on device but not on server
- `lifelogger health` shows old sync times

**Check:**
```bash
# Open Syncthing UI
open http://localhost:8384

# Check folder status in UI
# Look for "Out of Sync" or error states
```

**Common fixes:**
1. **Device not connected**: Add device ID in both directions
2. **Folder not shared**: Share the `lifelogger` folder with server
3. **Firewall blocking**: Open ports 22000/tcp, 22000/udp, 21027/udp

---

### 5. MCP Server / Claude Integration Issues

**Symptoms:**
- Claude says "lifelogger tools not available"
- MCP connection errors

**Check configuration:**
```bash
# Test MCP server directly
lifelogger mcp-server

# Check Claude Desktop config location
# Linux/Mac: ~/.config/claude/claude_desktop_config.json
# Windows: %APPDATA%\Claude\claude_desktop_config.json
```

**Verify config:**
```json
{
  "mcpServers": {
    "lifelogger": {
      "command": "lifelogger-mcp",
      "env": {
        "LIFELOGGER_DB_HOST": "localhost",
        "LIFELOGGER_DB_PASSWORD": "your_password"
      }
    }
  }
}
```

**After fixing:** Restart Claude Desktop completely.

---

### 6. Web Dashboard Not Loading

**Symptoms:**
- http://localhost:8000 doesn't respond
- API calls fail

**Fix:**
```bash
# Start web server
lifelogger web

# Or via Docker
cd docker && docker compose up -d lifelogger-web

# Check health endpoint
curl http://localhost:8000/health
```

---

### 7. Data is Old / Not Updating

**Symptoms:**
- Stats show data from days ago
- New activity not appearing

**Check the pipeline:**
```bash
# 1. Is ActivityWatch exporting?
ls -la ~/Syncthing/lifelogger/activity/

# 2. Is Syncthing syncing?
# Check http://localhost:8384

# 3. Is ingest running?
lifelogger ingest --verbose

# 4. Check database directly
docker exec -it lifelogger-db psql -U lifelogger -d lifelogger \
  -c "SELECT MAX(timestamp) FROM activity_events;"
```

---

## When All Else Fails: Manual Mode

If automatic tracking isn't working, you can still use the system manually:

```bash
# Log activities as you do them
lifelogger quick-log "Morning standup meeting" -d 30
lifelogger quick-log "Code review for PR #123" -d 45
lifelogger quick-log "Lunch break" -d 60
lifelogger quick-log "Deep work on API" -d 120

# Generate digest from manual entries
lifelogger digest

# Search your manual entries
lifelogger search "standup"
```

This isn't as seamless as automatic tracking, but it still captures your day and lets you use Claude for queries.

---

## Getting Help

1. **Check logs:**
   ```bash
   docker logs lifelogger-db
   docker logs lifelogger-ollama
   docker logs lifelogger-web
   ```

2. **Run verbose commands:**
   ```bash
   lifelogger ingest --verbose
   lifelogger classify --verbose
   ```

3. **Check environment:**
   ```bash
   lifelogger llm-status
   lifelogger health
   ```

---

## Architecture Quick Reference

```
Client Device                 Server
─────────────                 ──────
ActivityWatch ──export──> JSON files
                              │
                    Syncthing sync
                              │
                              ▼
                    ~/Syncthing/lifelogger/
                              │
                    lifelogger ingest
                              │
                              ▼
                        TimescaleDB
                              │
                    lifelogger classify
                              │
                              ▼
                    LLM (Ollama/OpenRouter)
                              │
                              ▼
                    Classified Events
                              │
            ┌─────────────────┼─────────────────┐
            ▼                 ▼                 ▼
      lifelogger         Web API           MCP Server
        digest           :8000             (Claude)
```

If data stops at any point, check that specific component.
