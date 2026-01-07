"""Data models for lifelogger."""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class EventType(str, Enum):
    """Types of events that can be logged."""

    APP_USAGE = "app_usage"
    BROWSER = "browser"
    AFK = "afk"
    TRANSCRIPT = "transcript"
    YOUTUBE = "youtube_watch"
    CALENDAR = "calendar"
    CUSTOM = "custom"


class ActivityEvent(BaseModel):
    """A single activity event from any source."""

    timestamp: datetime
    device_id: str
    event_type: EventType
    app_name: str | None = None
    window_title: str | None = None
    duration_seconds: float | None = None
    data: dict[str, Any] = Field(default_factory=dict)

    class Config:
        use_enum_values = True


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

    @property
    def full_text(self) -> str:
        """Get the complete transcript text."""
        return " ".join(seg.text for seg in self.segments)


class DailyDigest(BaseModel):
    """A daily summary digest."""

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
