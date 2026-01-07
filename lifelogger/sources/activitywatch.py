"""ActivityWatch data source adapter.

Handles importing activity data from ActivityWatch exports (JSON format).
Supports both direct API queries and file-based imports from Syncthing.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator

import aiofiles
import aiohttp
from dateutil.parser import parse as parse_datetime

from lifelogger.core.models import ActivityEvent, EventType


class ActivityWatchSource:
    """Import activity data from ActivityWatch."""

    def __init__(
        self,
        api_url: str = "http://localhost:5600",
        device_id: str | None = None,
    ):
        self.api_url = api_url.rstrip("/")
        self.device_id = device_id

    async def get_buckets(self) -> list[dict[str, Any]]:
        """Fetch list of available buckets from ActivityWatch API."""
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{self.api_url}/api/0/buckets") as resp:
                resp.raise_for_status()
                return await resp.json()

    async def get_events(
        self,
        bucket_id: str,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = -1,
    ) -> list[dict[str, Any]]:
        """Fetch events from a specific bucket via API."""
        params: dict[str, Any] = {"limit": limit}
        if start:
            params["start"] = start.isoformat()
        if end:
            params["end"] = end.isoformat()

        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{self.api_url}/api/0/buckets/{bucket_id}/events",
                params=params,
            ) as resp:
                resp.raise_for_status()
                return await resp.json()

    async def import_from_file(self, file_path: Path) -> AsyncIterator[ActivityEvent]:
        """Import events from an ActivityWatch JSON export file."""
        async with aiofiles.open(file_path, "r") as f:
            content = await f.read()
            data = json.loads(content)

        # Handle both bucket export format and event list format
        events = data if isinstance(data, list) else data.get("events", [])
        device_id = self.device_id or _extract_device_from_path(file_path)

        for event in events:
            yield _convert_aw_event(event, device_id)

    async def import_from_directory(
        self, directory: Path, pattern: str = "*.json"
    ) -> AsyncIterator[ActivityEvent]:
        """Import all JSON files from a directory."""
        for file_path in sorted(directory.glob(pattern)):
            async for event in self.import_from_file(file_path):
                yield event


def _extract_device_from_path(file_path: Path) -> str:
    """Extract device ID from file path structure like /device-name/activity/2024-01-01.json."""
    parts = file_path.parts
    for i, part in enumerate(parts):
        if part in ("activity", "activitywatch") and i > 0:
            return parts[i - 1]
    return "unknown"


def _convert_aw_event(event: dict[str, Any], device_id: str) -> ActivityEvent:
    """Convert an ActivityWatch event to our ActivityEvent format."""
    data = event.get("data", {})

    # Determine event type based on data contents
    event_type = EventType.APP_USAGE
    if "url" in data:
        event_type = EventType.BROWSER
    elif "status" in data:
        event_type = EventType.AFK

    return ActivityEvent(
        timestamp=parse_datetime(event["timestamp"]),
        device_id=device_id,
        event_type=event_type,
        app_name=data.get("app"),
        window_title=data.get("title"),
        duration_seconds=event.get("duration"),
        data=data,
    )


# Export helper for client scripts
async def export_today_to_json(output_path: Path, api_url: str = "http://localhost:5600") -> Path:
    """Export today's ActivityWatch data to a JSON file.

    This is meant to be run on client devices to export data for Syncthing.
    """
    from datetime import date, timedelta

    source = ActivityWatchSource(api_url)
    buckets = await source.get_buckets()

    today = date.today()
    start = datetime.combine(today, datetime.min.time())
    end = datetime.combine(today + timedelta(days=1), datetime.min.time())

    all_events = []
    for bucket_id in buckets:
        events = await source.get_events(bucket_id, start=start, end=end)
        all_events.extend(events)

    output_file = output_path / f"{today.isoformat()}.json"
    async with aiofiles.open(output_file, "w") as f:
        await f.write(json.dumps(all_events, indent=2, default=str))

    return output_file
