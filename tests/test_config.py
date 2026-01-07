"""Tests for configuration module."""

import os
from pathlib import Path

import pytest

from lifelogger.core.config import Settings, get_settings


class TestSettings:
    """Test Settings configuration."""

    def test_default_settings(self):
        """Test default settings values."""
        settings = Settings()
        assert settings.db_host == "localhost"
        assert settings.db_port == 5432
        assert settings.db_name == "lifelogger"
        assert settings.ollama_port == 11434

    def test_database_url(self):
        """Test database URL construction."""
        settings = Settings(
            db_host="testhost",
            db_port=5433,
            db_name="testdb",
            db_user="testuser",
            db_password="testpass",
        )
        assert settings.database_url == "postgresql://testuser:testpass@testhost:5433/testdb"

    def test_ollama_url(self):
        """Test Ollama URL construction."""
        settings = Settings(ollama_host="gpu-server", ollama_port=11435)
        assert settings.ollama_url == "http://gpu-server:11435"

    def test_sync_paths(self):
        """Test sync path properties."""
        settings = Settings(sync_base_path=Path("/data/sync"))
        assert settings.sync_activity_path == Path("/data/sync/activity")
        assert settings.sync_transcripts_path == Path("/data/sync/transcripts")
        assert settings.sync_audio_path == Path("/data/sync/audio")

    def test_env_override(self, monkeypatch):
        """Test environment variable override."""
        monkeypatch.setenv("LIFELOGGER_DB_HOST", "envhost")
        monkeypatch.setenv("LIFELOGGER_DB_PORT", "5555")

        # Clear cache to pick up new env vars
        get_settings.cache_clear()
        settings = get_settings()

        assert settings.db_host == "envhost"
        assert settings.db_port == 5555


class TestGetSettings:
    """Test get_settings function."""

    def test_cached_settings(self):
        """Test that settings are cached."""
        get_settings.cache_clear()
        settings1 = get_settings()
        settings2 = get_settings()
        assert settings1 is settings2
