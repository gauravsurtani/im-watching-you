"""YouTube watch history data source.

Imports watch history from Google Takeout exports.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import AsyncIterator

import aiofiles
from dateutil.parser import parse as parse_datetime

from lifelogger.core.models import ActivityEvent, EventType


class YouTubeSource:
    """Import YouTube watch history from Google Takeout."""

    def __init__(self, device_id: str = "youtube"):
        self.device_id = device_id

    async def import_from_takeout(
        self, takeout_path: Path
    ) -> AsyncIterator[ActivityEvent]:
        """Import from Google Takeout directory structure.

        Expected path structure:
        takeout_path/YouTube and YouTube Music/history/watch-history.json
        """
        history_file = takeout_path / "YouTube and YouTube Music" / "history" / "watch-history.json"

        if not history_file.exists():
            # Try alternate location
            history_file = takeout_path / "watch-history.json"

        if not history_file.exists():
            raise FileNotFoundError(f"Watch history not found at {history_file}")

        async for event in self.import_from_file(history_file):
            yield event

    async def import_from_file(self, file_path: Path) -> AsyncIterator[ActivityEvent]:
        """Import from a watch-history.json file."""
        async with aiofiles.open(file_path, "r", encoding="utf-8") as f:
            content = await f.read()
            history = json.loads(content)

        for item in history:
            event = _convert_youtube_item(item, self.device_id)
            if event:
                yield event


def _convert_youtube_item(item: dict, device_id: str) -> ActivityEvent | None:
    """Convert a YouTube history item to ActivityEvent."""
    # Skip ads and other non-video entries
    if "titleUrl" not in item:
        return None

    # Parse timestamp (format: "2024-01-07T14:30:00.000Z")
    try:
        timestamp = parse_datetime(item["time"])
    except (KeyError, ValueError):
        return None

    # Extract channel name from subtitles array
    channel = None
    subtitles = item.get("subtitles", [])
    if subtitles and isinstance(subtitles[0], dict):
        channel = subtitles[0].get("name")

    # Extract video ID from URL
    url = item.get("titleUrl", "")
    video_id = None
    if "watch?v=" in url:
        video_id = url.split("watch?v=")[-1].split("&")[0]

    return ActivityEvent(
        timestamp=timestamp,
        device_id=device_id,
        event_type=EventType.YOUTUBE,
        app_name="YouTube",
        window_title=item.get("title", "").replace("Watched ", ""),
        data={
            "url": url,
            "video_id": video_id,
            "channel": channel,
            "title": item.get("title", "").replace("Watched ", ""),
        },
    )


async def import_youtube_history(takeout_path: Path) -> list[ActivityEvent]:
    """Convenience function to import all YouTube history as a list."""
    source = YouTubeSource()
    events = []
    async for event in source.import_from_takeout(takeout_path):
        events.append(event)
    return events
