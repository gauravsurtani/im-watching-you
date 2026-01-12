"""Configuration management for lifelogger."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="LIFELOGGER_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "lifelogger"
    db_user: str = "lifelogger"
    db_password: str = "lifelogger"

    @property
    def database_url(self) -> str:
        """PostgreSQL connection URL."""
        return f"postgresql://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"

    # Ollama (local LLM)
    ollama_host: str = "localhost"
    ollama_port: int = 11434
    ollama_model: str = "qwen2.5:7b"

    @property
    def ollama_url(self) -> str:
        """Ollama API base URL."""
        return f"http://{self.ollama_host}:{self.ollama_port}"

    # OpenRouter (cloud LLM - free tier)
    openrouter_api_key: str = ""  # Get from https://openrouter.ai/keys
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    # Model Configuration
    # Preset: "speed" (fastest), "balanced" (recommended), "quality" (best), "minimal"
    model_preset: Literal["speed", "balanced", "quality", "minimal"] = "balanced"

    # Override specific models (optional, uses preset defaults if empty)
    # Use model keys from models_config.py: "llama-3.2-3b", "gemma-2-9b", "mistral-small-24b", etc.
    model_classification: str = ""  # For event/batch classification
    model_analysis: str = ""  # For transcript analysis
    model_digest: str = ""  # For digest generation
    model_general: str = ""  # For other tasks

    # Legacy single-model config (used if no preset/override)
    openrouter_model: str = "meta-llama/llama-3.2-3b-instruct:free"
    openrouter_fallback_model: str = "google/gemma-2-9b-it:free"

    # LLM Provider Strategy
    # "local" = Always use Ollama (maximum privacy)
    # "cloud" = Always use OpenRouter (no local GPU needed)
    # "hybrid" = Use cloud for non-sensitive, local for sensitive data
    # "cloud_fallback" = Try local first, fall back to cloud
    llm_provider: Literal["local", "cloud", "hybrid", "cloud_fallback"] = "hybrid"

    # Privacy settings for hybrid mode
    # When true, these data types are processed locally only
    privacy_local_transcripts: bool = True  # Audio transcripts contain conversations
    privacy_local_urls: bool = True  # Full URLs may be sensitive
    privacy_local_window_titles: bool = False  # Window titles for classification
    privacy_local_digests: bool = False  # Daily digests (can redact before cloud)

    # Rate limiting for free tier (requests per minute)
    openrouter_rate_limit: int = 20  # Free tier is ~20 RPM

    # Syncthing paths
    sync_base_path: Path = Field(default=Path.home() / "Syncthing" / "lifelogger")

    @property
    def sync_activity_path(self) -> Path:
        """Path to synced activity data."""
        return self.sync_base_path / "activity"

    @property
    def sync_transcripts_path(self) -> Path:
        """Path to synced transcripts."""
        return self.sync_base_path / "transcripts"

    @property
    def sync_audio_path(self) -> Path:
        """Path to synced audio files."""
        return self.sync_base_path / "audio"

    # Notifications
    ntfy_server: str = "http://localhost:8080"
    ntfy_topic: str = "lifelogger"
    notification_channels: list[str] = Field(default_factory=lambda: ["ntfy://localhost/lifelogger"])

    # Digest settings
    digest_time_hour: int = 7  # 7 AM
    digest_time_minute: int = 0
    digest_timezone: str = "UTC"

    # Data retention (days)
    audio_retention_days: int = 30
    transcript_retention_days: int = 365
    activity_retention_days: int = 365

    # Device identification
    device_id: str = "server"

    # Logging
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
