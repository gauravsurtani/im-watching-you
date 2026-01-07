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

    # Ollama
    ollama_host: str = "localhost"
    ollama_port: int = 11434
    ollama_model: str = "qwen2.5:7b"

    @property
    def ollama_url(self) -> str:
        """Ollama API base URL."""
        return f"http://{self.ollama_host}:{self.ollama_port}"

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
