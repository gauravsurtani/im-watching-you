"""Browser history data source.

Imports browsing history directly from Chrome and Firefox SQLite databases.
Works on Windows, macOS, and Linux.

NOTE: No URL parsing or classification here. Raw data is stored
and the LLM enriches it with structured metadata.
"""

import json
import platform
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator

from lifelogger.core.models import ActivityEvent


class BrowserHistorySource:
    """Import browser history from Chrome and Firefox."""

    def __init__(self, device_id: str | None = None):
        self.device_id = device_id or platform.node().lower()

    def get_chrome_history_path(self) -> Path | None:
        """Get the path to Chrome's History database."""
        system = platform.system()

        if system == "Darwin":  # macOS
            path = Path.home() / "Library/Application Support/Google/Chrome/Default/History"
        elif system == "Windows":
            path = Path.home() / "AppData/Local/Google/Chrome/User Data/Default/History"
        elif system == "Linux":
            path = Path.home() / ".config/google-chrome/Default/History"
        else:
            return None

        return path if path.exists() else None

    def get_firefox_history_path(self) -> Path | None:
        """Get the path to Firefox's places.sqlite database."""
        system = platform.system()

        if system == "Darwin":  # macOS
            profiles_dir = Path.home() / "Library/Application Support/Firefox/Profiles"
        elif system == "Windows":
            profiles_dir = Path.home() / "AppData/Roaming/Mozilla/Firefox/Profiles"
        elif system == "Linux":
            profiles_dir = Path.home() / ".mozilla/firefox"
        else:
            return None

        if not profiles_dir.exists():
            return None

        # Find the default profile (ends with .default or .default-release)
        for profile in profiles_dir.iterdir():
            if profile.is_dir() and ("default" in profile.name.lower()):
                places_db = profile / "places.sqlite"
                if places_db.exists():
                    return places_db

        return None

    async def import_chrome_history(
        self,
        since: datetime | None = None,
        limit: int = 1000,
    ) -> AsyncIterator[ActivityEvent]:
        """Import history from Chrome.

        Args:
            since: Only import visits after this datetime
            limit: Maximum number of entries to import
        """
        history_path = self.get_chrome_history_path()
        if not history_path:
            return

        # Chrome locks the database, so copy it first
        with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as tmp:
            shutil.copy2(history_path, tmp.name)
            tmp_path = tmp.name

        try:
            conn = sqlite3.connect(tmp_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # Chrome stores timestamps as microseconds since Jan 1, 1601
            chrome_epoch = datetime(1601, 1, 1, tzinfo=timezone.utc)

            query = """
                SELECT
                    urls.url,
                    urls.title,
                    visits.visit_time,
                    visits.visit_duration
                FROM visits
                JOIN urls ON visits.url = urls.id
                WHERE 1=1
            """
            params = []

            if since:
                # Convert to Chrome timestamp format
                since_ts = int((since - chrome_epoch).total_seconds() * 1_000_000)
                query += " AND visits.visit_time > ?"
                params.append(since_ts)

            query += " ORDER BY visits.visit_time DESC LIMIT ?"
            params.append(limit)

            cursor.execute(query, params)

            for row in cursor.fetchall():
                # Convert Chrome timestamp to datetime
                visit_time_us = row["visit_time"]
                visit_time = chrome_epoch + timedelta(microseconds=visit_time_us)

                # Duration is in microseconds
                duration_seconds = row["visit_duration"] / 1_000_000 if row["visit_duration"] else None

                yield ActivityEvent(
                    timestamp=visit_time.replace(tzinfo=None),
                    device_id=self.device_id,
                    source="chrome",
                    app_name="Google Chrome",
                    window_title=row["title"] or "",
                    url=row["url"],
                    duration_seconds=duration_seconds,
                    data={
                        "browser": "chrome",
                        "raw_title": row["title"],
                        "raw_url": row["url"],
                    },
                    classification=None,
                )

            conn.close()
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    async def import_firefox_history(
        self,
        since: datetime | None = None,
        limit: int = 1000,
    ) -> AsyncIterator[ActivityEvent]:
        """Import history from Firefox.

        Args:
            since: Only import visits after this datetime
            limit: Maximum number of entries to import
        """
        places_path = self.get_firefox_history_path()
        if not places_path:
            return

        # Firefox also locks the database
        with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as tmp:
            shutil.copy2(places_path, tmp.name)
            tmp_path = tmp.name

        try:
            conn = sqlite3.connect(tmp_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            query = """
                SELECT
                    moz_places.url,
                    moz_places.title,
                    moz_historyvisits.visit_date,
                    moz_historyvisits.visit_type
                FROM moz_historyvisits
                JOIN moz_places ON moz_historyvisits.place_id = moz_places.id
                WHERE 1=1
            """
            params = []

            if since:
                # Firefox stores timestamps as microseconds since Unix epoch
                since_ts = int(since.timestamp() * 1_000_000)
                query += " AND moz_historyvisits.visit_date > ?"
                params.append(since_ts)

            query += " ORDER BY moz_historyvisits.visit_date DESC LIMIT ?"
            params.append(limit)

            cursor.execute(query, params)

            for row in cursor.fetchall():
                # Convert Firefox timestamp to datetime
                visit_time = datetime.fromtimestamp(row["visit_date"] / 1_000_000)

                yield ActivityEvent(
                    timestamp=visit_time,
                    device_id=self.device_id,
                    source="firefox",
                    app_name="Firefox",
                    window_title=row["title"] or "",
                    url=row["url"],
                    duration_seconds=None,  # Firefox doesn't track duration
                    data={
                        "browser": "firefox",
                        "raw_title": row["title"],
                        "raw_url": row["url"],
                        "visit_type": row["visit_type"],
                    },
                    classification=None,
                )

            conn.close()
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    async def import_all_browsers(
        self,
        since: datetime | None = None,
        limit: int = 1000,
    ) -> AsyncIterator[ActivityEvent]:
        """Import history from all available browsers."""
        async for event in self.import_chrome_history(since, limit):
            yield event

        async for event in self.import_firefox_history(since, limit):
            yield event


# Required import for Chrome timestamp conversion
from datetime import timedelta


async def import_browser_history(
    since: datetime | None = None,
    limit: int = 1000,
) -> list[ActivityEvent]:
    """Convenience function to import all browser history as a list."""
    source = BrowserHistorySource()
    events = []
    async for event in source.import_all_browsers(since, limit):
        events.append(event)
    return events
