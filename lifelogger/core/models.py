"""Data models for lifelogger.

All categorization is done via LLM - no hardcoded rules.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ActivityEvent(BaseModel):
    """A single activity event from any source.

    Events are stored with raw data. Classification is done
    by the LLM and stored in the `classification` field.
    """

    timestamp: datetime
    device_id: str
    source: str  # "activitywatch", "transcript", "youtube", "browser", etc.
    app_name: str | None = None
    window_title: str | None = None
    url: str | None = None
    duration_seconds: float | None = None
    data: dict[str, Any] = Field(default_factory=dict)

    # LLM-derived classification (populated by enrichment)
    classification: dict[str, Any] | None = None


class LLMClassification(BaseModel):
    """LLM-derived classification for an event.

    Stored in ActivityEvent.classification field.
    """

    event_type: str  # LLM-determined type
    category: str  # High-level category
    subcategory: str | None = None
    is_productive: bool | None = None
    description: str
    confidence: float


class TranscriptSegment(BaseModel):
    """A segment of transcribed audio."""

    start_time: float  # seconds from start of recording
    end_time: float
    text: str
    confidence: float | None = None
    speaker: str | None = None  # for future speaker diarization


class Transcript(BaseModel):
    """A complete transcript from an audio recording."""

    timestamp: datetime
    device_id: str
    audio_file: str | None = None  # path to original audio
    duration_seconds: float
    language: str = "en"
    segments: list[TranscriptSegment] = Field(default_factory=list)

    # LLM-derived analysis (populated by enrichment)
    analysis: dict[str, Any] | None = None

    @property
    def full_text(self) -> str:
        """Get the complete transcript text."""
        return " ".join(seg.text for seg in self.segments)


class TranscriptAnalysis(BaseModel):
    """LLM-derived analysis of a transcript.

    Stored in Transcript.analysis field.
    """

    summary: str
    topics: list[str]
    action_items: list[str]
    ideas: list[str]
    people_mentioned: list[str]
    content_referenced: list[str]
    sentiment: str
    key_quotes: list[str]
    follow_ups: list[str]


class DailyDigest(BaseModel):
    """A daily summary digest - fully LLM-generated."""

    date: datetime
    time_summary: str
    top_apps: list[dict[str, Any]]
    topics_discussed: list[str]
    ideas_captured: list[str]
    action_items: list[str]
    content_referenced: list[str]
    follow_ups: list[str]
    raw_llm_response: str | None = None


class DeviceInfo(BaseModel):
    """Information about a tracked device."""

    device_id: str
    device_name: str
    platform: str  # "windows", "macos", "android"
    last_sync: datetime | None = None
    is_active: bool = True
