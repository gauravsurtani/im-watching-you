"""YouTube watch history data source.

Imports watch history from Google Takeout exports.

NOTE: No rule-based URL parsing or classification here. Raw data is stored
and the LLM enriches it with structured metadata during or after ingestion.
"""

import json
from pathlib import Path
from typing import AsyncIterator

import aiofiles
from dateutil.parser import parse as parse_datetime

from lifelogger.core.models import ActivityEvent


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
    """Convert a YouTube history item to ActivityEvent.

    NOTE: No URL parsing or metadata extraction here. The raw item data
    is stored and the LLM will extract/enrich structured metadata.
    """
    # Skip entries without URLs (ads, etc.)
    if "titleUrl" not in item:
        return None

    # Parse timestamp
    try:
        timestamp = parse_datetime(item["time"])
    except (KeyError, ValueError):
        return None

    # Store raw title - LLM will clean up the "Watched " prefix
    title = item.get("title", "")

    # Get channel info if available
    subtitles = item.get("subtitles", [])
    channel = None
    if subtitles and isinstance(subtitles[0], dict):
        channel = subtitles[0].get("name")

    return ActivityEvent(
        timestamp=timestamp,
        device_id=device_id,
        source="youtube",
        app_name="YouTube",
        window_title=title,
        url=item.get("titleUrl"),
        data={
            # Store raw data - LLM will extract structured fields
            "raw_title": title,
            "url": item.get("titleUrl"),
            "channel": channel,
            "subtitles": subtitles,
            # These will be populated by LLM enrichment:
            # "video_id": ...,
            # "clean_title": ...,
            # "content_type": ...,
            # "topics": [...],
        },
        classification=None,  # Will be populated by LLM
    )


async def import_youtube_history(takeout_path: Path) -> list[ActivityEvent]:
    """Convenience function to import all YouTube history as a list."""
    source = YouTubeSource()
    events = []
    async for event in source.import_from_takeout(takeout_path):
        events.append(event)
    return events
