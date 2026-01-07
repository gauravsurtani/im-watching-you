"""Calendar data source.

Imports calendar events from ICS files or Google Calendar API.

NOTE: No rule-based classification here. Raw event data is stored
and the LLM enriches it with structured metadata.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, AsyncIterator

import aiofiles

from lifelogger.core.models import ActivityEvent


class CalendarSource:
    """Import calendar events from ICS files or API."""

    def __init__(self, device_id: str = "calendar"):
        self.device_id = device_id

    async def import_from_ics(self, file_path: Path) -> AsyncIterator[ActivityEvent]:
        """Import events from an ICS calendar file.

        Supports standard iCalendar format exported from Google Calendar,
        Apple Calendar, Outlook, etc.
        """
        async with aiofiles.open(file_path, "r", encoding="utf-8") as f:
            content = await f.read()

        # Simple ICS parser - handles basic VEVENT components
        events = _parse_ics(content)

        for event in events:
            yield ActivityEvent(
                timestamp=event["start"],
                device_id=self.device_id,
                source="calendar",
                app_name="Calendar",
                window_title=event.get("summary", ""),
                duration_seconds=event.get("duration_seconds"),
                data={
                    "summary": event.get("summary"),
                    "description": event.get("description"),
                    "location": event.get("location"),
                    "start": event["start"].isoformat() if event.get("start") else None,
                    "end": event["end"].isoformat() if event.get("end") else None,
                    "attendees": event.get("attendees", []),
                    "organizer": event.get("organizer"),
                    "uid": event.get("uid"),
                    "status": event.get("status"),
                },
                classification=None,
            )

    async def import_from_google_takeout(
        self, takeout_path: Path
    ) -> AsyncIterator[ActivityEvent]:
        """Import from Google Takeout calendar export.

        Expected structure:
        takeout_path/Calendar/*.ics
        """
        calendar_dir = takeout_path / "Calendar"

        if not calendar_dir.exists():
            # Try alternate location
            calendar_dir = takeout_path

        for ics_file in calendar_dir.glob("*.ics"):
            async for event in self.import_from_ics(ics_file):
                yield event


def _parse_ics(content: str) -> list[dict[str, Any]]:
    """Simple ICS parser for VEVENT components.

    This is a basic parser that handles common ICS formats.
    For production use, consider using the icalendar library.
    """
    events = []
    current_event: dict[str, Any] | None = None
    current_key: str | None = None
    current_value: str = ""

    lines = content.replace("\r\n ", "").replace("\r\n\t", "").split("\r\n")
    if len(lines) == 1:
        lines = content.replace("\n ", "").replace("\n\t", "").split("\n")

    for line in lines:
        line = line.strip()
        if not line:
            continue

        if line == "BEGIN:VEVENT":
            current_event = {}
            continue
        elif line == "END:VEVENT":
            if current_event:
                events.append(_process_event(current_event))
            current_event = None
            continue

        if current_event is None:
            continue

        # Parse key:value or key;params:value
        if ":" in line:
            key_part, value = line.split(":", 1)
            # Handle parameters like DTSTART;VALUE=DATE:20240115
            key = key_part.split(";")[0]
            current_event[key] = value

    return events


def _process_event(raw: dict[str, Any]) -> dict[str, Any]:
    """Process raw ICS event data into structured format."""
    event: dict[str, Any] = {
        "summary": raw.get("SUMMARY", ""),
        "description": raw.get("DESCRIPTION", ""),
        "location": raw.get("LOCATION", ""),
        "uid": raw.get("UID", ""),
        "status": raw.get("STATUS", ""),
        "organizer": raw.get("ORGANIZER", ""),
    }

    # Parse dates
    start_str = raw.get("DTSTART", "")
    end_str = raw.get("DTEND", "")

    event["start"] = _parse_ics_datetime(start_str)
    event["end"] = _parse_ics_datetime(end_str)

    # Calculate duration
    if event["start"] and event["end"]:
        duration = event["end"] - event["start"]
        event["duration_seconds"] = duration.total_seconds()

    # Parse attendees
    attendees = []
    for key, value in raw.items():
        if key.startswith("ATTENDEE"):
            # Extract email from mailto:email format
            if "mailto:" in value:
                email = value.split("mailto:")[-1]
                attendees.append(email)
            else:
                attendees.append(value)
    event["attendees"] = attendees

    return event


def _parse_ics_datetime(dt_str: str) -> datetime | None:
    """Parse ICS datetime format."""
    if not dt_str:
        return None

    # Remove timezone indicator for simplicity
    dt_str = dt_str.replace("Z", "")

    formats = [
        "%Y%m%dT%H%M%S",  # 20240115T103000
        "%Y%m%d",  # 20240115 (all-day event)
    ]

    for fmt in formats:
        try:
            return datetime.strptime(dt_str, fmt)
        except ValueError:
            continue

    return None


async def import_calendar_events(
    path: Path,
    is_takeout: bool = False,
) -> list[ActivityEvent]:
    """Convenience function to import calendar events as a list."""
    source = CalendarSource()
    events = []

    if is_takeout:
        async for event in source.import_from_google_takeout(path):
            events.append(event)
    else:
        async for event in source.import_from_ics(path):
            events.append(event)

    return events
