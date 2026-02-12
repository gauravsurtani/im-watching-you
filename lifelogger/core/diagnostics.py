"""Diagnostic and health check utilities for Lifelogger.

Provides comprehensive system health checks, troubleshooting,
and fallback mechanisms when components fail.
"""

import asyncio
import os
import socket
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any

import aiohttp

from lifelogger.core.config import Settings, get_settings


class HealthStatus(Enum):
    """Health status levels."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class ComponentHealth:
    """Health status of a single component."""
    name: str
    status: HealthStatus
    message: str
    details: dict[str, Any] | None = None
    fix_hint: str | None = None


@dataclass
class SystemHealth:
    """Overall system health report."""
    status: HealthStatus
    components: list[ComponentHealth]
    timestamp: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "timestamp": self.timestamp.isoformat(),
            "components": [
                {
                    "name": c.name,
                    "status": c.status.value,
                    "message": c.message,
                    "details": c.details,
                    "fix_hint": c.fix_hint,
                }
                for c in self.components
            ],
        }


async def check_database(settings: Settings) -> ComponentHealth:
    """Check database connectivity and data freshness."""
    try:
        import asyncpg

        conn = await asyncpg.connect(
            host=settings.db_host,
            port=settings.db_port,
            database=settings.db_name,
            user=settings.db_user,
            password=settings.db_password,
            timeout=5,
        )

        try:
            # Check connection
            await conn.fetchval("SELECT 1")

            # Check data freshness
            latest = await conn.fetchval(
                "SELECT MAX(timestamp) FROM activity_events"
            )

            # Check event count
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM activity_events WHERE timestamp > NOW() - INTERVAL '24 hours'"
            )

            details = {
                "latest_event": latest.isoformat() if latest else None,
                "events_last_24h": count,
            }

            # Determine health based on data freshness
            if latest is None:
                return ComponentHealth(
                    name="Database",
                    status=HealthStatus.DEGRADED,
                    message="Connected but no data yet",
                    details=details,
                    fix_hint="Run 'lifelogger ingest' to import data",
                )

            age = datetime.now(latest.tzinfo) - latest
            if age > timedelta(hours=24):
                return ComponentHealth(
                    name="Database",
                    status=HealthStatus.DEGRADED,
                    message=f"Data is {age.days}d {age.seconds//3600}h old",
                    details=details,
                    fix_hint="Check if Syncthing is syncing and run 'lifelogger ingest'",
                )

            return ComponentHealth(
                name="Database",
                status=HealthStatus.HEALTHY,
                message=f"Connected, {count} events in last 24h",
                details=details,
            )

        finally:
            await conn.close()

    except asyncpg.InvalidCatalogNameError:
        return ComponentHealth(
            name="Database",
            status=HealthStatus.UNHEALTHY,
            message="Database does not exist",
            fix_hint="Run: docker exec -it lifelogger-db psql -U lifelogger -c 'CREATE DATABASE lifelogger'",
        )
    except asyncpg.InvalidPasswordError:
        return ComponentHealth(
            name="Database",
            status=HealthStatus.UNHEALTHY,
            message="Invalid database password",
            fix_hint="Check LIFELOGGER_DB_PASSWORD in .env",
        )
    except (OSError, asyncpg.CannotConnectNowError) as e:
        return ComponentHealth(
            name="Database",
            status=HealthStatus.UNHEALTHY,
            message=f"Cannot connect: {e}",
            fix_hint="Run: cd docker && docker compose up -d timescaledb",
        )
    except Exception as e:
        return ComponentHealth(
            name="Database",
            status=HealthStatus.UNHEALTHY,
            message=str(e),
        )


async def check_ollama(settings: Settings) -> ComponentHealth:
    """Check Ollama LLM availability."""
    if not settings.ollama_host:
        return ComponentHealth(
            name="Ollama (Local LLM)",
            status=HealthStatus.UNKNOWN,
            message="Not configured",
            fix_hint="Set LIFELOGGER_OLLAMA_HOST in .env or use cloud LLM",
        )

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{settings.ollama_url}/api/tags",
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    models = [m["name"] for m in data.get("models", [])]

                    if settings.ollama_model in models:
                        return ComponentHealth(
                            name="Ollama (Local LLM)",
                            status=HealthStatus.HEALTHY,
                            message=f"Running with {settings.ollama_model}",
                            details={"installed_models": models},
                        )
                    else:
                        return ComponentHealth(
                            name="Ollama (Local LLM)",
                            status=HealthStatus.DEGRADED,
                            message=f"Running but {settings.ollama_model} not installed",
                            details={"installed_models": models},
                            fix_hint=f"Run: docker exec lifelogger-ollama ollama pull {settings.ollama_model}",
                        )
                else:
                    return ComponentHealth(
                        name="Ollama (Local LLM)",
                        status=HealthStatus.UNHEALTHY,
                        message=f"HTTP {resp.status}",
                    )
    except aiohttp.ClientConnectorError:
        return ComponentHealth(
            name="Ollama (Local LLM)",
            status=HealthStatus.UNHEALTHY,
            message="Cannot connect",
            fix_hint="Run: cd docker && docker compose up -d ollama",
        )
    except Exception as e:
        return ComponentHealth(
            name="Ollama (Local LLM)",
            status=HealthStatus.UNHEALTHY,
            message=str(e),
        )


async def check_openrouter(settings: Settings) -> ComponentHealth:
    """Check OpenRouter cloud LLM availability."""
    if not settings.openrouter_api_key:
        return ComponentHealth(
            name="OpenRouter (Cloud LLM)",
            status=HealthStatus.UNKNOWN,
            message="Not configured (API key missing)",
            fix_hint="Get free key at https://openrouter.ai/keys and set LIFELOGGER_OPENROUTER_API_KEY",
        )

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{settings.openrouter_base_url}/models",
                headers={"Authorization": f"Bearer {settings.openrouter_api_key}"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    return ComponentHealth(
                        name="OpenRouter (Cloud LLM)",
                        status=HealthStatus.HEALTHY,
                        message=f"Connected, using {settings.openrouter_model}",
                        details={"model": settings.openrouter_model},
                    )
                elif resp.status == 401:
                    return ComponentHealth(
                        name="OpenRouter (Cloud LLM)",
                        status=HealthStatus.UNHEALTHY,
                        message="Invalid API key",
                        fix_hint="Check LIFELOGGER_OPENROUTER_API_KEY in .env",
                    )
                else:
                    return ComponentHealth(
                        name="OpenRouter (Cloud LLM)",
                        status=HealthStatus.UNHEALTHY,
                        message=f"HTTP {resp.status}",
                    )
    except Exception as e:
        return ComponentHealth(
            name="OpenRouter (Cloud LLM)",
            status=HealthStatus.DEGRADED,
            message=f"Cannot reach: {e}",
            fix_hint="Check internet connection",
        )


async def check_syncthing(settings: Settings) -> ComponentHealth:
    """Check Syncthing sync status."""
    sync_path = Path(settings.sync_base_path)

    if not sync_path.exists():
        return ComponentHealth(
            name="Syncthing",
            status=HealthStatus.UNHEALTHY,
            message=f"Sync folder does not exist: {sync_path}",
            fix_hint=f"Create folder: mkdir -p {sync_path}",
        )

    # Check for recent files
    activity_path = sync_path / "activity"
    transcript_path = sync_path / "transcripts"

    details = {
        "sync_path": str(sync_path),
        "activity_folder_exists": activity_path.exists(),
        "transcript_folder_exists": transcript_path.exists(),
    }

    # Find most recent file
    recent_file = None
    recent_time = None

    for folder in [activity_path, transcript_path]:
        if folder.exists():
            for f in folder.rglob("*"):
                if f.is_file():
                    mtime = datetime.fromtimestamp(f.stat().st_mtime)
                    if recent_time is None or mtime > recent_time:
                        recent_time = mtime
                        recent_file = f

    if recent_file:
        details["most_recent_file"] = str(recent_file.name)
        details["most_recent_time"] = recent_time.isoformat()

        age = datetime.now() - recent_time
        if age > timedelta(hours=24):
            return ComponentHealth(
                name="Syncthing",
                status=HealthStatus.DEGRADED,
                message=f"Last file {age.days}d {age.seconds//3600}h ago",
                details=details,
                fix_hint="Check Syncthing UI at http://localhost:8384 and client device sync status",
            )

        return ComponentHealth(
            name="Syncthing",
            status=HealthStatus.HEALTHY,
            message=f"Syncing, last file {age.seconds//60}m ago",
            details=details,
        )

    return ComponentHealth(
        name="Syncthing",
        status=HealthStatus.DEGRADED,
        message="Folder exists but no files synced yet",
        details=details,
        fix_hint="Set up Syncthing on client devices and share folders",
    )


async def check_activitywatch_data(settings: Settings) -> ComponentHealth:
    """Check if ActivityWatch data is being collected."""
    sync_path = Path(settings.sync_base_path) / "activity"

    if not sync_path.exists():
        return ComponentHealth(
            name="ActivityWatch Data",
            status=HealthStatus.UNKNOWN,
            message="Activity folder not found",
            fix_hint="Set up ActivityWatch export script on client devices",
        )

    # Look for ActivityWatch JSON files
    aw_files = list(sync_path.rglob("*.json"))

    if not aw_files:
        return ComponentHealth(
            name="ActivityWatch Data",
            status=HealthStatus.UNHEALTHY,
            message="No ActivityWatch export files found",
            fix_hint="Run export script: python scripts/clients/export_activitywatch.py",
        )

    # Check most recent
    most_recent = max(aw_files, key=lambda f: f.stat().st_mtime)
    mtime = datetime.fromtimestamp(most_recent.stat().st_mtime)
    age = datetime.now() - mtime

    details = {
        "file_count": len(aw_files),
        "most_recent_file": most_recent.name,
        "most_recent_time": mtime.isoformat(),
    }

    if age > timedelta(hours=2):
        return ComponentHealth(
            name="ActivityWatch Data",
            status=HealthStatus.DEGRADED,
            message=f"{len(aw_files)} files, last export {age.seconds//3600}h ago",
            details=details,
            fix_hint="Check ActivityWatch is running and export script is scheduled",
        )

    return ComponentHealth(
        name="ActivityWatch Data",
        status=HealthStatus.HEALTHY,
        message=f"{len(aw_files)} files, last export {age.seconds//60}m ago",
        details=details,
    )


async def run_full_health_check(settings: Settings | None = None) -> SystemHealth:
    """Run comprehensive health check on all components."""
    settings = settings or get_settings()

    # Run all checks concurrently
    results = await asyncio.gather(
        check_database(settings),
        check_ollama(settings),
        check_openrouter(settings),
        check_syncthing(settings),
        check_activitywatch_data(settings),
        return_exceptions=True,
    )

    components = []
    for result in results:
        if isinstance(result, Exception):
            components.append(ComponentHealth(
                name="Unknown",
                status=HealthStatus.UNHEALTHY,
                message=str(result),
            ))
        else:
            components.append(result)

    # Determine overall status
    statuses = [c.status for c in components]

    if all(s == HealthStatus.HEALTHY for s in statuses):
        overall = HealthStatus.HEALTHY
    elif any(s == HealthStatus.UNHEALTHY for s in statuses):
        # Check if critical components are down
        critical = ["Database"]
        critical_down = any(
            c.status == HealthStatus.UNHEALTHY and c.name in critical
            for c in components
        )
        overall = HealthStatus.UNHEALTHY if critical_down else HealthStatus.DEGRADED
    else:
        overall = HealthStatus.DEGRADED

    return SystemHealth(
        status=overall,
        components=components,
        timestamp=datetime.now(),
    )


def get_troubleshooting_steps(health: SystemHealth) -> list[str]:
    """Generate prioritized troubleshooting steps based on health report."""
    steps = []

    for component in health.components:
        if component.status in (HealthStatus.UNHEALTHY, HealthStatus.DEGRADED):
            if component.fix_hint:
                steps.append(f"[{component.name}] {component.fix_hint}")

    return steps


# Quick connectivity tests
def check_port(host: str, port: int, timeout: float = 2.0) -> bool:
    """Quick check if a port is open."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except Exception:
        return False


def quick_status() -> dict[str, bool]:
    """Quick connectivity check without async."""
    settings = get_settings()

    return {
        "database": check_port(settings.db_host, settings.db_port),
        "ollama": check_port(settings.ollama_host, settings.ollama_port) if settings.ollama_host else False,
        "syncthing_ui": check_port("localhost", 8384),
        "web_dashboard": check_port("localhost", 8000),
    }
