"""Tests for data models."""

from datetime import datetime

import pytest

from lifelogger.core.models import (
    ActivityEvent,
    DailyDigest,
    LLMClassification,
    Transcript,
    TranscriptSegment,
)


class TestActivityEvent:
    """Test ActivityEvent model."""

    def test_create_minimal_event(self):
        """Test creating event with minimal fields."""
        event = ActivityEvent(
            timestamp=datetime(2024, 1, 15, 10, 30),
            device_id="test-device",
            source="activitywatch",
        )
        assert event.timestamp == datetime(2024, 1, 15, 10, 30)
        assert event.device_id == "test-device"
        assert event.source == "activitywatch"
        assert event.app_name is None
        assert event.classification is None

    def test_create_full_event(self):
        """Test creating event with all fields."""
        event = ActivityEvent(
            timestamp=datetime(2024, 1, 15, 10, 30),
            device_id="test-device",
            source="activitywatch",
            app_name="Visual Studio Code",
            window_title="main.py - project",
            url=None,
            duration_seconds=1800.5,
            data={"extra": "data"},
            classification={"event_type": "development"},
        )
        assert event.app_name == "Visual Studio Code"
        assert event.duration_seconds == 1800.5
        assert event.data["extra"] == "data"


class TestTranscript:
    """Test Transcript model."""

    def test_full_text_property(self):
        """Test full_text property concatenates segments."""
        transcript = Transcript(
            timestamp=datetime(2024, 1, 15, 10, 30),
            device_id="phone",
            duration_seconds=120.0,
            segments=[
                TranscriptSegment(start_time=0, end_time=5, text="Hello world."),
                TranscriptSegment(start_time=5, end_time=10, text="How are you?"),
                TranscriptSegment(start_time=10, end_time=15, text="I'm fine."),
            ],
        )
        assert transcript.full_text == "Hello world. How are you? I'm fine."

    def test_empty_segments(self):
        """Test transcript with no segments."""
        transcript = Transcript(
            timestamp=datetime(2024, 1, 15, 10, 30),
            device_id="phone",
            duration_seconds=0,
            segments=[],
        )
        assert transcript.full_text == ""


class TestLLMClassification:
    """Test LLMClassification model."""

    def test_create_classification(self):
        """Test creating a classification."""
        classification = LLMClassification(
            event_type="development",
            category="Work",
            subcategory="Coding",
            is_productive=True,
            description="Writing Python code",
            confidence=0.95,
        )
        assert classification.event_type == "development"
        assert classification.is_productive is True
        assert classification.confidence == 0.95


class TestDailyDigest:
    """Test DailyDigest model."""

    def test_create_digest(self):
        """Test creating a daily digest."""
        digest = DailyDigest(
            date=datetime(2024, 1, 15),
            time_summary="Spent 6 hours on development tasks",
            top_apps=[
                {"app": "VS Code", "seconds": 14400},
                {"app": "Chrome", "seconds": 7200},
            ],
            topics_discussed=["project planning", "code review"],
            ideas_captured=["New feature idea"],
            action_items=["Review PR #123"],
            content_referenced=["Python docs"],
            follow_ups=["Check test results"],
        )
        assert len(digest.top_apps) == 2
        assert "project planning" in digest.topics_discussed
