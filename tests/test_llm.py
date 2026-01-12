"""Tests for hybrid LLM service."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from lifelogger.core.llm import (
    DataSensitivity,
    EventClassification,
    HybridLLMService,
    LLMService,
    OllamaProvider,
    OpenRouterProvider,
    TranscriptAnalysis,
    classify_event,
    check_provider_status,
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

    def test_minimal_classification(self):
        """Test classification with only required fields."""
        classification = EventClassification(
            event_type="other",
            category="Unknown",
            description="Unknown activity",
            confidence=0.0,
        )
        assert classification.subcategory is None
        assert classification.is_productive is None


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


class TestDataSensitivity:
    """Test DataSensitivity enum."""

    def test_sensitivity_levels(self):
        """Test sensitivity levels exist."""
        assert DataSensitivity.LOW.value == "low"
        assert DataSensitivity.MEDIUM.value == "medium"
        assert DataSensitivity.HIGH.value == "high"
        assert DataSensitivity.CRITICAL.value == "critical"


class TestHybridLLMService:
    """Test HybridLLMService class."""

    @pytest.fixture
    def settings(self):
        """Create settings for testing."""
        from lifelogger.core.config import Settings
        return Settings(
            ollama_host="localhost",
            ollama_port=11434,
            openrouter_api_key="test_key",
            llm_provider="hybrid",
        )

    @pytest.fixture
    def llm_service(self, settings):
        """Create LLM service for testing."""
        return HybridLLMService(settings)

    def test_backward_compatibility_alias(self):
        """Test that LLMService is an alias for HybridLLMService."""
        assert LLMService is HybridLLMService

    def test_provider_selection_local(self, settings):
        """Test provider selection for local strategy."""
        settings.llm_provider = "local"
        service = HybridLLMService(settings)
        provider = service._select_provider(DataSensitivity.LOW)
        assert isinstance(provider, OllamaProvider)

    def test_provider_selection_cloud(self, settings):
        """Test provider selection for cloud strategy."""
        settings.llm_provider = "cloud"
        service = HybridLLMService(settings)
        provider = service._select_provider(DataSensitivity.LOW)
        assert isinstance(provider, OpenRouterProvider)

    def test_provider_selection_hybrid_low_sensitivity(self, settings):
        """Test hybrid provider selection routes low sensitivity to cloud."""
        settings.llm_provider = "hybrid"
        service = HybridLLMService(settings)
        provider = service._select_provider(DataSensitivity.LOW)
        assert isinstance(provider, OpenRouterProvider)

    def test_provider_selection_hybrid_high_sensitivity(self, settings):
        """Test hybrid provider selection routes high sensitivity to local."""
        settings.llm_provider = "hybrid"
        service = HybridLLMService(settings)
        provider = service._select_provider(DataSensitivity.HIGH)
        assert isinstance(provider, OllamaProvider)

    def test_provider_selection_hybrid_critical_sensitivity(self, settings):
        """Test hybrid provider selection routes critical sensitivity to local."""
        settings.llm_provider = "hybrid"
        service = HybridLLMService(settings)
        provider = service._select_provider(DataSensitivity.CRITICAL)
        assert isinstance(provider, OllamaProvider)

    def test_provider_fallback_no_api_key(self):
        """Test fallback to Ollama when no API key."""
        from lifelogger.core.config import Settings
        settings = Settings(
            ollama_host="localhost",
            openrouter_api_key="",  # No API key
            llm_provider="cloud",
        )
        service = HybridLLMService(settings)
        provider = service._select_provider(DataSensitivity.LOW)
        # Should fall back to Ollama since OpenRouter isn't available
        assert isinstance(provider, OllamaProvider)


class TestOllamaProvider:
    """Test OllamaProvider class."""

    def test_is_available(self):
        """Test provider availability check."""
        from lifelogger.core.config import Settings
        settings = Settings(ollama_host="localhost")
        provider = OllamaProvider(settings)
        assert provider.is_available() is True

    def test_is_not_available(self):
        """Test provider unavailability."""
        from lifelogger.core.config import Settings
        settings = Settings(ollama_host="")
        provider = OllamaProvider(settings)
        assert provider.is_available() is False


class TestOpenRouterProvider:
    """Test OpenRouterProvider class."""

    def test_is_available_with_key(self):
        """Test provider available with API key."""
        from lifelogger.core.config import Settings
        settings = Settings(openrouter_api_key="test_key")
        provider = OpenRouterProvider(settings)
        assert provider.is_available() is True

    def test_is_not_available_without_key(self):
        """Test provider unavailable without API key."""
        from lifelogger.core.config import Settings
        settings = Settings(openrouter_api_key="")
        provider = OpenRouterProvider(settings)
        assert provider.is_available() is False

    def test_free_models_list(self):
        """Test free models list is populated."""
        assert len(OpenRouterProvider.FREE_MODELS) > 0
        assert "meta-llama/llama-3.2-3b-instruct:free" in OpenRouterProvider.FREE_MODELS


class TestClassifyEvent:
    """Test classify_event function."""

    @pytest.mark.asyncio
    async def test_classify_event_structure(self):
        """Test that classify_event returns proper structure."""
        from lifelogger.core.config import Settings

        mock_llm = MagicMock()
        mock_llm.settings = Settings(llm_provider="local")
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

    @pytest.mark.asyncio
    async def test_classify_event_with_url(self):
        """Test classification with URL."""
        from lifelogger.core.config import Settings

        mock_llm = MagicMock()
        mock_llm.settings = Settings(llm_provider="local")
        mock_llm.generate_structured = AsyncMock(return_value=EventClassification(
            event_type="browser",
            category="Work",
            subcategory="Documentation",
            is_productive=True,
            description="Reading docs",
            confidence=0.9,
        ))

        result = await classify_event(
            mock_llm,
            app_name="Chrome",
            window_title="Python Docs",
            url="https://docs.python.org/3/",
        )

        assert result.event_type == "browser"


class TestPrivacyRedaction:
    """Test privacy-aware redaction."""

    def test_url_redaction(self):
        """Test URL is redacted to domain for cloud."""
        from lifelogger.core.config import Settings
        from lifelogger.core.llm import _redact_sensitive_for_cloud

        settings = Settings(privacy_local_urls=True)
        app, title, url, sensitivity = _redact_sensitive_for_cloud(
            "Chrome",
            "My Secret Doc",
            "https://example.com/private/doc.pdf",
            settings,
        )

        assert url == "example.com"  # Only domain kept
        assert sensitivity == DataSensitivity.HIGH

    def test_no_redaction_when_disabled(self):
        """Test no redaction when privacy settings disabled."""
        from lifelogger.core.config import Settings
        from lifelogger.core.llm import _redact_sensitive_for_cloud

        settings = Settings(privacy_local_urls=False, privacy_local_window_titles=False)
        app, title, url, sensitivity = _redact_sensitive_for_cloud(
            "Chrome",
            "My Secret Doc",
            "https://example.com/private/doc.pdf",
            settings,
        )

        assert url == "https://example.com/private/doc.pdf"  # Full URL kept
        assert sensitivity == DataSensitivity.LOW
