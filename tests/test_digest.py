"""Tests for digest generation."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from lifelogger.core.models import DailyDigest
from lifelogger.exporters.digest import (
    DigestGenerator,
    DigestOutput,
    render_digest_markdown,
)


class TestDigestOutput:
    """Test DigestOutput model."""

    def test_valid_digest_output(self):
        """Test creating valid digest output."""
        output = DigestOutput(
            time_summary="Worked for 8 hours",
            topics_discussed=["project", "planning"],
            ideas_captured=["new feature"],
            action_items=["review code"],
            content_referenced=["docs"],
            follow_ups=["meeting"],
            daily_highlight="Completed feature X",
            mood_assessment="productive",
        )
        assert output.time_summary == "Worked for 8 hours"
        assert len(output.topics_discussed) == 2


class TestRenderDigestMarkdown:
    """Test digest markdown rendering."""

    def test_render_full_digest(self):
        """Test rendering a complete digest."""
        digest = DailyDigest(
            date=datetime(2024, 1, 15),
            time_summary="Spent 6 hours coding, 2 hours in meetings",
            top_apps=[
                {"app": "VS Code", "seconds": 21600},
                {"app": "Slack", "seconds": 3600},
            ],
            topics_discussed=["API design", "testing strategy"],
            ideas_captured=["Cache invalidation approach"],
            action_items=["Write tests for auth module"],
            content_referenced=["REST API best practices article"],
            follow_ups=["Research Redis options"],
        )

        markdown = render_digest_markdown(digest)

        assert "January 15, 2024" in markdown
        assert "VS Code" in markdown
        assert "6.0 hours" in markdown
        assert "API design" in markdown
        assert "Write tests for auth module" in markdown
        assert "[ ]" in markdown  # Action items as checkboxes

    def test_render_empty_sections(self):
        """Test rendering digest with empty sections."""
        digest = DailyDigest(
            date=datetime(2024, 1, 15),
            time_summary="Quiet day",
            top_apps=[],
            topics_discussed=[],
            ideas_captured=[],
            action_items=[],
            content_referenced=[],
            follow_ups=[],
        )

        markdown = render_digest_markdown(digest)

        assert "Quiet day" in markdown
        # Empty sections should not appear
        assert "Topics Discussed" not in markdown
        assert "Action Items" not in markdown


class TestDigestGenerator:
    """Test DigestGenerator class."""

    @pytest.fixture
    def generator(self):
        """Create a digest generator for testing."""
        from lifelogger.core.config import Settings
        settings = Settings()
        return DigestGenerator(settings)

    def test_format_app_usage_empty(self, generator):
        """Test formatting empty app usage."""
        result = generator._format_app_usage([])
        assert result == "(No activity data recorded)"

    def test_format_app_usage_hours(self, generator):
        """Test formatting app usage in hours."""
        app_usage = [
            {"app_name": "VS Code", "total_seconds": 7200},  # 2 hours
            {"app_name": "Slack", "total_seconds": 3600},  # 1 hour
        ]
        result = generator._format_app_usage(app_usage)

        assert "VS Code: 2.0 hours" in result
        assert "Slack: 1.0 hours" in result

    def test_format_app_usage_minutes(self, generator):
        """Test formatting app usage in minutes."""
        app_usage = [
            {"app_name": "Terminal", "total_seconds": 1800},  # 30 min
        ]
        result = generator._format_app_usage(app_usage)
        assert "Terminal: 30 minutes" in result

    def test_format_transcripts_empty(self, generator):
        """Test formatting empty transcripts."""
        result = generator._format_transcripts([])
        assert result == ""

    def test_format_transcripts_with_data(self, generator):
        """Test formatting transcripts with data."""
        transcripts = [
            {
                "timestamp": datetime(2024, 1, 15, 10, 30),
                "data": {"full_text": "Hello, this is a test transcript."},
            },
        ]
        result = generator._format_transcripts(transcripts)

        assert "[10:30]" in result
        assert "Hello, this is a test transcript." in result
