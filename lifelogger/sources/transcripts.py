"""Transcript data source adapter.

Handles importing transcribed audio data from JSON files synced via Syncthing.

NOTE: No rule-based classification here. Transcripts are stored raw and
analyzed by the LLM service during or after ingestion.
"""

import json
from pathlib import Path
from typing import AsyncIterator

import aiofiles
from dateutil.parser import parse as parse_datetime

from lifelogger.core.models import ActivityEvent, Transcript, TranscriptSegment


class TranscriptSource:
    """Import transcripts from JSON files."""

    def __init__(self, device_id: str | None = None):
        self.device_id = device_id

    async def import_from_file(self, file_path: Path) -> Transcript:
        """Import a single transcript file."""
        async with aiofiles.open(file_path, "r") as f:
            content = await f.read()
            data = json.loads(content)

        device_id = self.device_id or _extract_device_from_path(file_path)

        segments = [
            TranscriptSegment(
                start_time=seg.get("start", 0),
                end_time=seg.get("end", 0),
                text=seg.get("text", ""),
                confidence=seg.get("confidence"),
                speaker=seg.get("speaker"),
            )
            for seg in data.get("segments", [])
        ]

        return Transcript(
            timestamp=parse_datetime(data.get("timestamp", file_path.stem)),
            device_id=device_id,
            audio_file=data.get("audio_file"),
            duration_seconds=data.get("duration", 0),
            language=data.get("language", "en"),
            segments=segments,
            analysis=None,  # Will be populated by LLM
        )

    async def import_from_directory(
        self, directory: Path, pattern: str = "*.json"
    ) -> AsyncIterator[Transcript]:
        """Import all transcript files from a directory."""
        for file_path in sorted(directory.glob(pattern)):
            try:
                yield await self.import_from_file(file_path)
            except (json.JSONDecodeError, KeyError) as e:
                # Log but continue on malformed files
                print(f"Warning: Failed to parse {file_path}: {e}")
                continue

    def transcript_to_activity_event(self, transcript: Transcript) -> ActivityEvent:
        """Convert a Transcript to an ActivityEvent for database storage.

        NOTE: No classification here. Stored as source="transcript".
        """
        return ActivityEvent(
            timestamp=transcript.timestamp,
            device_id=transcript.device_id,
            source="transcript",
            duration_seconds=transcript.duration_seconds,
            data={
                "full_text": transcript.full_text,
                "language": transcript.language,
                "audio_file": transcript.audio_file,
                "segment_count": len(transcript.segments),
                "analysis": transcript.analysis,  # May be None until LLM processes it
            },
            classification=None,  # Will be populated by LLM
        )


def _extract_device_from_path(file_path: Path) -> str:
    """Extract device ID from file path structure."""
    parts = file_path.parts
    for i, part in enumerate(parts):
        if part in ("transcripts", "transcript") and i > 0:
            return parts[i - 1]
    return "unknown"


def parse_whisper_output(whisper_json: dict) -> list[TranscriptSegment]:
    """Parse whisper.cpp JSON output format into TranscriptSegments.

    Uses time field parsing that matches whisper.cpp's output format.
    """
    segments = []
    for seg in whisper_json.get("transcription", []):
        # whisper.cpp format uses "timestamps" with "from" and "to"
        timestamps = seg.get("timestamps", {})
        segments.append(
            TranscriptSegment(
                start_time=_parse_whisper_time(timestamps.get("from", "00:00:00.000")),
                end_time=_parse_whisper_time(timestamps.get("to", "00:00:00.000")),
                text=seg.get("text", "").strip(),
            )
        )
    return segments


def _parse_whisper_time(time_str: str) -> float:
    """Parse whisper.cpp timestamp format (HH:MM:SS.mmm) to seconds.

    This parses a fixed, known format from whisper.cpp output.
    """
    # Split by colon to get hours, minutes, seconds
    parts = time_str.split(":")
    if len(parts) == 3:
        hours = float(parts[0])
        minutes = float(parts[1])
        seconds = float(parts[2])
        return hours * 3600 + minutes * 60 + seconds
    return 0.0
