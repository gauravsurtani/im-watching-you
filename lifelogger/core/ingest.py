"""Data ingestion service for processing synced files.

Monitors Syncthing folders and ingests new data into the database.
All classification is done by LLM - no rule-based heuristics.
"""

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import aiofiles

from lifelogger.core.config import Settings, get_settings
from lifelogger.core.database import Database
from lifelogger.core.llm import LLMService, classify_events_batch, get_llm_service
from lifelogger.core.models import ActivityEvent
from lifelogger.sources.transcripts import TranscriptSource


class IngestService:
    """Ingest synced data files into the database.

    Events are stored without classification first. LLM classification
    can be done inline during ingestion or as a separate batch process.
    """

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.db: Database | None = None
        self.llm: LLMService | None = None

    async def _ensure_db(self) -> Database:
        """Ensure database connection exists."""
        if self.db is None:
            self.db = Database(self.settings)
            await self.db.connect()
        return self.db

    async def _ensure_llm(self) -> LLMService:
        """Ensure LLM service exists."""
        if self.llm is None:
            self.llm = get_llm_service(self.settings)
        return self.llm

    async def ingest_activity_files(
        self,
        directory: Path | None = None,
        classify: bool = False,
    ) -> dict[str, int]:
        """Ingest all ActivityWatch JSON files from the sync directory.

        Args:
            directory: Directory to scan (defaults to settings.sync_activity_path)
            classify: If True, run LLM classification during ingestion

        Returns:
            Dict mapping file paths to number of events ingested.
        """
        db = await self._ensure_db()
        directory = directory or self.settings.sync_activity_path

        results: dict[str, int] = {}

        if not directory.exists():
            return results

        # Find all JSON files recursively
        for json_file in directory.rglob("*.json"):
            # Skip already processed files
            file_hash = await self._file_hash(json_file)
            if await self._is_processed(json_file, file_hash):
                continue

            try:
                count = await self._ingest_activity_file(db, json_file, classify=classify)
                await self._mark_processed(json_file, file_hash, count)
                results[str(json_file)] = count
            except Exception as e:
                print(f"Error ingesting {json_file}: {e}")
                results[str(json_file)] = -1

        return results

    async def ingest_transcript_files(
        self,
        directory: Path | None = None,
        analyze: bool = False,
    ) -> dict[str, int]:
        """Ingest all transcript JSON files from the sync directory.

        Args:
            directory: Directory to scan
            analyze: If True, run LLM analysis during ingestion

        Returns:
            Dict mapping file paths to number of transcripts ingested.
        """
        db = await self._ensure_db()
        directory = directory or self.settings.sync_transcripts_path

        results: dict[str, int] = {}

        if not directory.exists():
            return results

        source = TranscriptSource()

        for json_file in directory.rglob("*.json"):
            file_hash = await self._file_hash(json_file)
            if await self._is_processed(json_file, file_hash):
                continue

            try:
                transcript = await source.import_from_file(json_file)

                # Optionally analyze with LLM
                if analyze:
                    llm = await self._ensure_llm()
                    from lifelogger.core.llm import analyze_transcript
                    analysis = await analyze_transcript(llm, transcript.full_text)
                    transcript.analysis = analysis.model_dump()

                event = source.transcript_to_activity_event(transcript)

                await db.insert_activity_event(
                    timestamp=event.timestamp,
                    device_id=event.device_id,
                    source=event.source,
                    duration_seconds=event.duration_seconds,
                    data=event.data,
                    classification=event.classification,
                )

                await self._mark_processed(json_file, file_hash, 1)
                results[str(json_file)] = 1
            except Exception as e:
                print(f"Error ingesting transcript {json_file}: {e}")
                results[str(json_file)] = -1

        return results

    async def _ingest_activity_file(
        self,
        db: Database,
        file_path: Path,
        classify: bool = False,
    ) -> int:
        """Ingest a single ActivityWatch export file."""
        async with aiofiles.open(file_path, "r") as f:
            content = await f.read()
            data = json.loads(content)

        # Handle our export format vs raw AW format
        if isinstance(data, dict) and "events" in data:
            device_id = data.get("device_id", _extract_device_from_path(file_path))
            events = data["events"]
        elif isinstance(data, list):
            device_id = _extract_device_from_path(file_path)
            events = data
        else:
            return 0

        # Convert to our event format (no classification yet)
        db_events: list[dict[str, Any]] = []

        for raw_event in events:
            try:
                event = _convert_raw_aw_event(raw_event, device_id)
                db_events.append({
                    "timestamp": event.timestamp,
                    "device_id": event.device_id,
                    "source": event.source,
                    "app_name": event.app_name,
                    "window_title": event.window_title,
                    "url": event.url,
                    "duration_seconds": event.duration_seconds,
                    "data": event.data,
                    "classification": None,  # Will be populated by LLM if classify=True
                })
            except Exception as e:
                print(f"Warning: Failed to convert event: {e}")
                continue

        # Optionally classify with LLM before insertion
        if classify and db_events:
            llm = await self._ensure_llm()
            classifications = await classify_events_batch(llm, db_events)
            for event, classification in zip(db_events, classifications):
                event["classification"] = classification.model_dump()

        if db_events:
            return await db.insert_activity_events_batch(db_events)
        return 0

    async def classify_unclassified_events(
        self,
        batch_size: int = 50,
        max_events: int = 500,
    ) -> int:
        """Classify events that don't have LLM classification yet.

        This can be run as a background task to catch up on classification.

        Args:
            batch_size: Number of events to classify per LLM call
            max_events: Maximum total events to process

        Returns:
            Number of events classified
        """
        db = await self._ensure_db()
        llm = await self._ensure_llm()

        # Get unclassified events
        events = await db.get_unclassified_events(limit=max_events)

        if not events:
            return 0

        # Classify in batches
        total_classified = 0

        for i in range(0, len(events), batch_size):
            batch = events[i : i + batch_size]

            # Prepare batch for classification
            classify_batch = [
                {
                    "app_name": e.get("app_name"),
                    "window_title": e.get("window_title"),
                    "url": e.get("url"),
                    "duration": e.get("duration_seconds"),
                    "data": e.get("data"),
                }
                for e in batch
            ]

            try:
                classifications = await classify_events_batch(
                    llm, classify_batch, batch_size=batch_size
                )

                # Update database
                updates = [
                    (e["id"], e["timestamp"], c.model_dump())
                    for e, c in zip(batch, classifications)
                ]
                await db.batch_update_classifications(updates)
                total_classified += len(updates)

            except Exception as e:
                print(f"Error classifying batch: {e}")
                continue

        return total_classified

    async def _file_hash(self, file_path: Path) -> str:
        """Calculate SHA-256 hash of a file."""
        sha256 = hashlib.sha256()
        async with aiofiles.open(file_path, "rb") as f:
            content = await f.read()
            sha256.update(content)
        return sha256.hexdigest()

    async def _is_processed(self, file_path: Path, file_hash: str) -> bool:
        """Check if a file has already been processed."""
        db = await self._ensure_db()
        async with db.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT 1 FROM sync_status
                WHERE file_path = $1 AND file_hash = $2
                """,
                str(file_path),
                file_hash,
            )
            return row is not None

    async def _mark_processed(self, file_path: Path, file_hash: str, event_count: int) -> None:
        """Mark a file as processed."""
        db = await self._ensure_db()
        device_id = _extract_device_from_path(file_path)

        async with db.acquire() as conn:
            # Ensure device exists
            await conn.execute(
                """
                INSERT INTO devices (device_id, device_name, platform, last_sync)
                VALUES ($1, $1, 'unknown', $2)
                ON CONFLICT (device_id) DO UPDATE SET last_sync = $2
                """,
                device_id,
                datetime.now(),
            )

            # Record sync status
            await conn.execute(
                """
                INSERT INTO sync_status (device_id, file_path, file_hash, event_count)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (device_id, file_path, file_hash) DO NOTHING
                """,
                device_id,
                str(file_path),
                file_hash,
                event_count,
            )

    async def run_full_ingest(
        self,
        classify: bool = False,
        analyze_transcripts: bool = False,
    ) -> dict[str, Any]:
        """Run a full ingestion cycle for all data types.

        Args:
            classify: If True, classify activity events with LLM
            analyze_transcripts: If True, analyze transcripts with LLM

        Returns:
            Summary of ingestion results
        """
        results = {
            "activity": await self.ingest_activity_files(classify=classify),
            "transcripts": await self.ingest_transcript_files(analyze=analyze_transcripts),
            "timestamp": datetime.now().isoformat(),
        }

        # Summary stats
        activity_count = sum(v for v in results["activity"].values() if v > 0)
        transcript_count = sum(v for v in results["transcripts"].values() if v > 0)

        results["summary"] = {
            "activity_events": activity_count,
            "transcripts": transcript_count,
            "files_processed": len(results["activity"]) + len(results["transcripts"]),
            "llm_classification": classify,
            "llm_analysis": analyze_transcripts,
        }

        return results


def _extract_device_from_path(file_path: Path) -> str:
    """Extract device ID from file path."""
    parts = file_path.parts
    for i, part in enumerate(parts):
        if part in ("activity", "transcripts", "audio") and i > 0:
            return parts[i - 1]
    return "unknown"


def _convert_raw_aw_event(event: dict[str, Any], device_id: str) -> ActivityEvent:
    """Convert a raw ActivityWatch event to our format.

    NOTE: No classification here. Events are stored raw.
    """
    from dateutil.parser import parse as parse_datetime

    data = event.get("data", {})

    return ActivityEvent(
        timestamp=parse_datetime(event["timestamp"]),
        device_id=device_id,
        source="activitywatch",
        app_name=data.get("app"),
        window_title=data.get("title"),
        url=data.get("url"),
        duration_seconds=event.get("duration"),
        data=data,
        classification=None,
    )
