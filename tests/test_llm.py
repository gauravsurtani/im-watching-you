"""Tests for LLM service."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from lifelogger.core.llm import (
    EventClassification,
    LLMService,
    TranscriptAnalysis,
    classify_event,
)


class TestEventClassification:
    """Test EventClassification model."""

    def test_valid_classification(self):
        """Test creating a valid classification."""
        classification = EventClassification(
            event_type="browser",
            category="Work",
            subcategory="Research",
            is_productive=True,
            description="Reading documentation",
            confidence=0.9,
        )
        assert classification.event_type == "browser"
        assert classification.confidence == 0.9


class TestTranscriptAnalysis:
    """Test TranscriptAnalysis model."""

    def test_valid_analysis(self):
        """Test creating a valid analysis."""
        analysis = TranscriptAnalysis(
            summary="Discussion about project timeline",
            topics=["deadlines", "milestones"],
            action_items=["Send report by Friday"],
            ideas=["Try new approach"],
            people_mentioned=["John", "Sarah"],
            content_referenced=["Project plan doc"],
            sentiment="positive",
            key_quotes=["We're on track"],
            follow_ups=["Schedule next meeting"],
        )
        assert len(analysis.topics) == 2
        assert "Send report by Friday" in analysis.action_items


class TestLLMService:
    """Test LLMService class."""

    @pytest.fixture
    def llm_service(self):
        """Create LLM service for testing."""
        from lifelogger.core.config import Settings
        settings = Settings(ollama_host="localhost", ollama_port=11434)
        return LLMService(settings)

    @pytest.mark.asyncio
    async def test_generate_json_valid_response(self, llm_service):
        """Test generate_json with valid response."""
        mock_response = {
            "response": '{"event_type": "browser", "category": "Work"}'
        }

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = AsyncMock()
            mock_session_class.return_value.__aenter__.return_value = mock_session

            mock_resp = AsyncMock()
            mock_resp.status = 200
            mock_resp.json = AsyncMock(return_value=mock_response)
            mock_session.post.return_value.__aenter__.return_value = mock_resp

            result = await llm_service.generate_json("Test prompt")

            assert result["event_type"] == "browser"
            assert result["category"] == "Work"

    @pytest.mark.asyncio
    async def test_generate_error_handling(self, llm_service):
        """Test error handling on API failure."""
        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = AsyncMock()
            mock_session_class.return_value.__aenter__.return_value = mock_session

            mock_resp = AsyncMock()
            mock_resp.status = 500
            mock_resp.text = AsyncMock(return_value="Internal Server Error")
            mock_session.post.return_value.__aenter__.return_value = mock_resp

            with pytest.raises(RuntimeError, match="Ollama API error"):
                await llm_service.generate("Test prompt")


class TestClassifyEvent:
    """Test classify_event function."""

    @pytest.mark.asyncio
    async def test_classify_event_structure(self):
        """Test that classify_event returns proper structure."""
        mock_llm = AsyncMock()
        mock_llm.generate_structured = AsyncMock(return_value=EventClassification(
            event_type="development",
            category="Work",
            subcategory="Coding",
            is_productive=True,
            description="Editing code",
            confidence=0.85,
        ))

        result = await classify_event(
            mock_llm,
            app_name="VS Code",
            window_title="main.py",
        )

        assert result.event_type == "development"
        assert result.is_productive is True
        mock_llm.generate_structured.assert_called_once()
