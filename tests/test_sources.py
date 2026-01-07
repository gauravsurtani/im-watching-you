"""Tests for data source adapters."""

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from lifelogger.sources.activitywatch import (
    ActivityWatchSource,
    _convert_aw_event,
    _extract_device_from_path,
)
from lifelogger.sources.transcripts import (
    TranscriptSource,
    _parse_whisper_time,
    parse_whisper_output,
)
from lifelogger.sources.youtube import YouTubeSource, _convert_youtube_item


class TestActivityWatchSource:
    """Test ActivityWatch source adapter."""

    def test_extract_device_from_path(self):
        """Test device extraction from file path."""
        path = Path("/home/user/Syncthing/lifelogger/macbook-pro/activity/2024-01-15.json")
        assert _extract_device_from_path(path) == "macbook-pro"

        path = Path("/data/windows-pc/activitywatch/events.json")
        assert _extract_device_from_path(path) == "windows-pc"

        path = Path("/random/path/file.json")
        assert _extract_device_from_path(path) == "unknown"

    def test_convert_aw_event_basic(self):
        """Test converting a basic ActivityWatch event."""
        raw_event = {
            "timestamp": "2024-01-15T10:30:00.000Z",
            "duration": 1800.5,
            "data": {
                "app": "Firefox",
                "title": "Google Search",
            },
        }

        event = _convert_aw_event(raw_event, "test-device")

        assert event.device_id == "test-device"
        assert event.source == "activitywatch"
        assert event.app_name == "Firefox"
        assert event.window_title == "Google Search"
        assert event.duration_seconds == 1800.5
        assert event.classification is None

    def test_convert_aw_event_with_url(self):
        """Test converting event with URL."""
        raw_event = {
            "timestamp": "2024-01-15T10:30:00.000Z",
            "duration": 300,
            "data": {
                "app": "Chrome",
                "title": "GitHub",
                "url": "https://github.com",
            },
        }

        event = _convert_aw_event(raw_event, "device")
        assert event.url == "https://github.com"


class TestTranscriptSource:
    """Test Transcript source adapter."""

    def test_parse_whisper_time(self):
        """Test parsing whisper.cpp timestamp format."""
        assert _parse_whisper_time("00:00:00.000") == 0.0
        assert _parse_whisper_time("00:01:30.500") == 90.5
        assert _parse_whisper_time("01:30:45.250") == 5445.25
        assert _parse_whisper_time("invalid") == 0.0

    def test_parse_whisper_output(self):
        """Test parsing whisper.cpp JSON output."""
        whisper_json = {
            "transcription": [
                {
                    "timestamps": {"from": "00:00:00.000", "to": "00:00:05.000"},
                    "text": "Hello world",
                },
                {
                    "timestamps": {"from": "00:00:05.000", "to": "00:00:10.000"},
                    "text": "How are you",
                },
            ]
        }

        segments = parse_whisper_output(whisper_json)

        assert len(segments) == 2
        assert segments[0].text == "Hello world"
        assert segments[0].start_time == 0.0
        assert segments[0].end_time == 5.0
        assert segments[1].text == "How are you"


class TestYouTubeSource:
    """Test YouTube source adapter."""

    def test_convert_youtube_item_basic(self):
        """Test converting a YouTube history item."""
        item = {
            "title": "Watched Python Tutorial",
            "titleUrl": "https://www.youtube.com/watch?v=abc123",
            "time": "2024-01-15T10:30:00.000Z",
            "subtitles": [{"name": "Tech Channel"}],
        }

        event = _convert_youtube_item(item, "youtube")

        assert event is not None
        assert event.source == "youtube"
        assert event.app_name == "YouTube"
        assert event.window_title == "Watched Python Tutorial"
        assert event.url == "https://www.youtube.com/watch?v=abc123"
        assert event.data["channel"] == "Tech Channel"

    def test_convert_youtube_item_no_url(self):
        """Test that items without URL are skipped."""
        item = {
            "title": "Some ad",
            "time": "2024-01-15T10:30:00.000Z",
        }

        event = _convert_youtube_item(item, "youtube")
        assert event is None

    def test_convert_youtube_item_no_channel(self):
        """Test item without channel info."""
        item = {
            "title": "Watched Video",
            "titleUrl": "https://youtube.com/watch?v=xyz",
            "time": "2024-01-15T10:30:00.000Z",
        }

        event = _convert_youtube_item(item, "youtube")
        assert event is not None
        assert event.data["channel"] is None
