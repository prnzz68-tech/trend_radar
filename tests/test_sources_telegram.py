# tests/test_sources_telegram.py
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.sources.registry import build_source
from src.sources.telegram import TelegramSource


def _make_message(
    message_id: int,
    created_at: datetime,
    text: str,
    views: int | None = None,
) -> MagicMock:
    message = MagicMock()
    message.id = message_id
    message.date = created_at
    message.message = text
    message.text = text
    message.views = views
    message.forwards = None
    return message


@pytest.mark.asyncio
async def test_telegram_fetch_maps_fields_and_filters_since():
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=1)
    fresh = _make_message(
        42,
        now,
        "Нужен инструмент для поиска идей\nПодробности ниже.",
        views=1234,
    )
    old = _make_message(41, now - timedelta(days=10), "Старое сообщение", views=100)

    client = MagicMock()
    client.connect = AsyncMock()
    client.disconnect = AsyncMock()
    client.is_user_authorized = AsyncMock(return_value=True)
    client.get_messages = AsyncMock(return_value=[fresh, old])

    src = TelegramSource(
        name="telegram_startups",
        params={"channels": ["startupsi"], "limit": 5},
    )

    with patch("src.sources.telegram.TelegramClient", return_value=client), patch(
        "src.sources.telegram.settings"
    ) as st:
        st.TG_API_ID = 123
        st.TG_API_HASH = "hash"
        posts = await src.fetch(since)

    assert len(posts) == 1
    p = posts[0]
    assert p.source_name == "telegram_startups"
    assert p.external_id == "startupsi_42"
    assert str(p.url) == "https://t.me/startupsi/42"
    assert p.title == "Нужен инструмент для поиска идей"
    assert p.content == "Нужен инструмент для поиска идей\nПодробности ниже."
    assert p.engagement == 1234
    assert p.published_at.tzinfo == timezone.utc
    client.get_messages.assert_awaited_once_with("startupsi", limit=5)
    client.disconnect.assert_awaited_once()


@pytest.mark.asyncio
async def test_telegram_no_credentials_returns_empty():
    src = TelegramSource(name="telegram_startups", params={"channels": ["startupsi"]})

    with patch("src.sources.telegram.settings") as st:
        st.TG_API_ID = 0
        st.TG_API_HASH = ""
        posts = await src.fetch(datetime.now(timezone.utc) - timedelta(days=1))

    assert posts == []


@pytest.mark.asyncio
async def test_telegram_not_authorized_returns_empty_and_disconnects():
    client = MagicMock()
    client.connect = AsyncMock()
    client.disconnect = AsyncMock()
    client.is_user_authorized = AsyncMock(return_value=False)

    src = TelegramSource(name="telegram_startups", params={"channels": ["startupsi"]})

    with patch("src.sources.telegram.TelegramClient", return_value=client), patch(
        "src.sources.telegram.settings"
    ) as st:
        st.TG_API_ID = 123
        st.TG_API_HASH = "hash"
        posts = await src.fetch(datetime.now(timezone.utc) - timedelta(days=1))

    assert posts == []
    client.disconnect.assert_awaited_once()


@pytest.mark.asyncio
async def test_telegram_channel_error_does_not_break_others():
    now = datetime.now(timezone.utc)
    good = _make_message(7, now, "Рабочее сообщение", views=None)

    client = MagicMock()
    client.connect = AsyncMock()
    client.disconnect = AsyncMock()
    client.is_user_authorized = AsyncMock(return_value=True)

    async def get_messages(channel: str, limit: int):
        if channel == "bad":
            raise RuntimeError("telegram error")
        return [good]

    client.get_messages = AsyncMock(side_effect=get_messages)

    src = TelegramSource(
        name="telegram_multi",
        params={"channels": ["bad", "good"], "limit": 10},
    )

    with patch("src.sources.telegram.TelegramClient", return_value=client), patch(
        "src.sources.telegram.settings"
    ) as st:
        st.TG_API_ID = 123
        st.TG_API_HASH = "hash"
        posts = await src.fetch(now - timedelta(days=1))

    assert len(posts) == 1
    assert posts[0].external_id == "good_7"
    assert posts[0].engagement is None


def test_telegram_registered():
    source = build_source(
        {
            "name": "telegram_startups",
            "type": "telegram",
            "params": {"channels": ["startupsi"]},
        }
    )

    assert isinstance(source, TelegramSource)
