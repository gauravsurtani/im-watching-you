"""Notification delivery for lifelogger.

Supports multiple channels via Apprise for flexible notification delivery.
"""

from typing import Any

import apprise

from lifelogger.core.config import Settings, get_settings
from lifelogger.core.models import DailyDigest
from lifelogger.exporters.digest import render_digest_markdown


class NotificationService:
    """Send notifications via multiple channels using Apprise."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self._apprise = apprise.Apprise()
        self._configured = False

    def configure(self, channels: list[str] | None = None) -> None:
        """Configure notification channels.

        Args:
            channels: List of Apprise notification URLs. If None, uses settings.
                     Examples:
                     - "ntfy://localhost/lifelogger" (ntfy push)
                     - "mailto://user:pass@smtp.gmail.com" (email)
                     - "tgram://bot_token/chat_id" (Telegram)
                     - "slack://token/channel" (Slack)
        """
        if channels is None:
            channels = self.settings.notification_channels

        self._apprise = apprise.Apprise()
        for channel in channels:
            self._apprise.add(channel)

        self._configured = True

    async def send_digest(self, digest: DailyDigest) -> bool:
        """Send a daily digest notification."""
        if not self._configured:
            self.configure()

        title = f"Daily Digest - {digest.date.strftime('%B %d')}"
        body = render_digest_markdown(digest)

        # Apprise async send
        result = await self._apprise.async_notify(
            title=title,
            body=body,
            body_format=apprise.NotifyFormat.MARKDOWN,
        )

        return result

    async def send_alert(
        self,
        title: str,
        message: str,
        priority: str = "normal",
    ) -> bool:
        """Send a general alert notification.

        Args:
            title: Notification title
            message: Notification body
            priority: One of "min", "low", "normal", "high", "max"
        """
        if not self._configured:
            self.configure()

        notify_type = apprise.NotifyType.INFO
        if priority in ("high", "max"):
            notify_type = apprise.NotifyType.WARNING

        result = await self._apprise.async_notify(
            title=title,
            body=message,
            notify_type=notify_type,
        )

        return result

    async def send_sync_alert(self, device_id: str, status: str, details: str = "") -> bool:
        """Send a sync status alert."""
        title = f"Sync Alert: {device_id}"
        message = f"Status: {status}\n{details}" if details else f"Status: {status}"
        return await self.send_alert(title, message, priority="normal")


class NtfyClient:
    """Direct ntfy client for simple push notifications."""

    def __init__(self, server: str = "http://localhost:8080", topic: str = "lifelogger"):
        self.server = server.rstrip("/")
        self.topic = topic

    @property
    def url(self) -> str:
        """Get the full ntfy topic URL."""
        return f"{self.server}/{self.topic}"

    async def publish(
        self,
        message: str,
        title: str | None = None,
        priority: int = 3,
        tags: list[str] | None = None,
        actions: list[dict[str, Any]] | None = None,
    ) -> bool:
        """Publish a message to ntfy.

        Args:
            message: Message body
            title: Optional title
            priority: 1 (min) to 5 (max), default 3 (normal)
            tags: List of emoji tags (e.g., ["warning", "robot"])
            actions: List of action buttons
        """
        import aiohttp

        headers: dict[str, str] = {}
        if title:
            headers["Title"] = title
        if priority != 3:
            headers["Priority"] = str(priority)
        if tags:
            headers["Tags"] = ",".join(tags)

        data: dict[str, Any] = {"message": message}
        if actions:
            data["actions"] = actions

        async with aiohttp.ClientSession() as session:
            async with session.post(
                self.url,
                data=message if not actions else None,
                json=data if actions else None,
                headers=headers,
            ) as resp:
                return resp.status == 200
