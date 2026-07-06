# src/sources/telegram.py
from datetime import datetime, timezone
from typing import Any

import structlog
from telethon import TelegramClient

from src.schemas.post import RawPost
from src.settings import settings
from src.sources.base import BaseSource

log = structlog.get_logger(__name__)

TELETHON_SESSION_PATH = "/data/telethon.session"


class TelegramSource(BaseSource):
    """
    Коннектор Telegram-каналов через Telethon.

    params:
      channels: list[str] - usernames каналов, например @startupnews
      limit: int          - сколько сообщений запрашивать на канал (default 50)
    """

    type = "telegram"

    def __init__(self, name: str, params: dict[str, Any]) -> None:
        self.name = name
        self.params = params
        self.channels: list[str] = params.get("channels", []) or []
        self.limit: int = int(params.get("limit", 50))

    async def fetch(self, since: datetime) -> list[RawPost]:
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)

        if not settings.TG_API_ID or not settings.TG_API_HASH:
            log.error("telegram.no_credentials", source=self.name)
            return []

        if not self.channels:
            log.warning("telegram.no_channels", source=self.name)
            return []

        client = TelegramClient(
            TELETHON_SESSION_PATH,
            settings.TG_API_ID,
            settings.TG_API_HASH,
        )

        results: list[RawPost] = []
        try:
            await client.connect()
            if not await client.is_user_authorized():
                log.error("telegram.not_authorized", source=self.name)
                return []

            for channel in self.channels:
                try:
                    messages = await client.get_messages(channel, limit=self.limit)
                except Exception:
                    log.exception(
                        "telegram.channel_failed",
                        source=self.name,
                        channel=channel,
                    )
                    continue

                for message in messages:
                    try:
                        post = self._message_to_post(message, channel)
                    except Exception as e:
                        log.warning(
                            "telegram.entry_parse_failed",
                            source=self.name,
                            channel=channel,
                            error=str(e),
                        )
                        continue

                    if post is None:
                        continue
                    if post.published_at <= since:
                        continue
                    results.append(post)
        finally:
            await client.disconnect()

        log.info("telegram.fetched", source=self.name, count=len(results))
        return results

    def _message_to_post(self, message: Any, channel: str) -> RawPost | None:
        message_id = getattr(message, "id", None)
        if message_id is None:
            return None

        text = (
            getattr(message, "message", None)
            or getattr(message, "text", "")
            or ""
        ).strip()
        if not text:
            return None

        published_at = self._normalize_datetime(getattr(message, "date", None))
        if published_at is None:
            log.warning(
                "telegram.no_pubdate",
                source=self.name,
                channel=channel,
                id=message_id,
            )
            return None

        channel_key = self._channel_key(channel)
        external_id = f"{channel_key}_{message_id}"

        return RawPost(
            source_name=self.name,
            external_id=external_id,
            url=self._message_url(channel_key, message_id),
            title=self._title_from_text(text, channel_key),
            author=channel_key,
            content=text,
            published_at=published_at,
            rating=None,
            engagement=self._views(message),
            raw={
                "channel": channel,
                "channel_key": channel_key,
                "id": message_id,
                "views": getattr(message, "views", None),
                "forwards": getattr(message, "forwards", None),
            },
        )

    @staticmethod
    def _normalize_datetime(value: Any) -> datetime | None:
        if not isinstance(value, datetime):
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _channel_key(channel: str) -> str:
        value = str(channel).strip()
        if value.startswith("https://t.me/"):
            value = value.rstrip("/").rsplit("/", 1)[-1]
        return value.lstrip("@")

    @staticmethod
    def _message_url(channel_key: str, message_id: int) -> str:
        return f"https://t.me/{channel_key}/{message_id}"

    @staticmethod
    def _views(message: Any) -> int | None:
        views = getattr(message, "views", None)
        return int(views) if views is not None else None

    @staticmethod
    def _title_from_text(text: str, channel_key: str) -> str:
        first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
        if not first_line:
            return f"Telegram post from {channel_key}"
        if len(first_line) <= 120:
            return first_line
        return f"{first_line[:117].rstrip()}..."
