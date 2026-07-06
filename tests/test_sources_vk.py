# tests/test_sources_vk.py
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.sources.registry import build_source
from src.sources.vk import VkSource


def _make_item(
    post_id: int,
    owner_id: int,
    created_at: datetime,
    text: str,
    likes: int = 0,
    comments: int = 0,
    reposts: int = 0,
) -> dict:
    return {
        "id": post_id,
        "owner_id": owner_id,
        "date": int(created_at.timestamp()),
        "text": text,
        "likes": {"count": likes},
        "comments": {"count": comments},
        "reposts": {"count": reposts},
        "views": {"count": 1000},
    }


def _build_mock_vk(items_by_group: dict[str, list[dict]]) -> MagicMock:
    vk = MagicMock()

    def wall_get(count: int, **kwargs):
        key = kwargs.get("domain") or str(kwargs.get("owner_id"))
        return {"items": items_by_group.get(key, [])[:count]}

    vk.wall.get = MagicMock(side_effect=wall_get)
    return vk


@pytest.mark.asyncio
async def test_vk_fetch_maps_fields_and_filters_since():
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=1)
    fresh = _make_item(
        post_id=10,
        owner_id=-123,
        created_at=now,
        text="Нужен простой инструмент для аналитики стартапов\nПодробности в посте.",
        likes=7,
        comments=3,
        reposts=2,
    )
    old = _make_item(
        post_id=9,
        owner_id=-123,
        created_at=now - timedelta(days=10),
        text="Старый пост",
        likes=100,
    )
    vk = _build_mock_vk({"tproger": [fresh, old]})
    session = MagicMock()
    session.get_api.return_value = vk

    src = VkSource(name="vk_ru_tech", params={"groups": ["tproger"], "limit": 5})

    with patch("src.sources.vk.vk_api.VkApi", return_value=session), patch(
        "src.sources.vk.settings"
    ) as st:
        st.VK_ACCESS_TOKEN = "token"
        posts = await src.fetch(since)

    assert len(posts) == 1
    p = posts[0]
    assert p.source_name == "vk_ru_tech"
    assert p.external_id == "-123_10"
    assert str(p.url) == "https://vk.com/wall-123_10"
    assert p.title == "Нужен простой инструмент для аналитики стартапов"
    assert p.content == "Нужен простой инструмент для аналитики стартапов\nПодробности в посте."
    assert p.engagement == 12
    assert p.published_at.tzinfo == timezone.utc
    vk.wall.get.assert_called_once_with(count=5, domain="tproger")


@pytest.mark.asyncio
async def test_vk_numeric_group_uses_negative_owner_id():
    now = datetime.now(timezone.utc)
    item = _make_item(
        post_id=1,
        owner_id=-777,
        created_at=now,
        text="Пост по числовому id",
    )
    vk = _build_mock_vk({"-777": [item]})
    session = MagicMock()
    session.get_api.return_value = vk

    src = VkSource(name="vk_numeric", params={"groups": ["777"], "limit": 1})

    with patch("src.sources.vk.vk_api.VkApi", return_value=session), patch(
        "src.sources.vk.settings"
    ) as st:
        st.VK_ACCESS_TOKEN = "token"
        posts = await src.fetch(now - timedelta(days=1))

    assert len(posts) == 1
    vk.wall.get.assert_called_once_with(count=1, owner_id=-777)


@pytest.mark.asyncio
async def test_vk_no_token_returns_empty():
    src = VkSource(name="vk_ru_tech", params={"groups": ["tproger"]})

    with patch("src.sources.vk.settings") as st:
        st.VK_ACCESS_TOKEN = ""
        posts = await src.fetch(datetime.now(timezone.utc) - timedelta(days=1))

    assert posts == []


@pytest.mark.asyncio
async def test_vk_group_error_does_not_break_others():
    now = datetime.now(timezone.utc)
    good = _make_item(2, -10, now, "Рабочий пост", likes=1)
    vk = MagicMock()

    def wall_get(count: int, **kwargs):
        if kwargs.get("domain") == "bad":
            raise RuntimeError("vk error")
        return {"items": [good]}

    vk.wall.get = MagicMock(side_effect=wall_get)
    session = MagicMock()
    session.get_api.return_value = vk

    src = VkSource(name="vk_multi", params={"groups": ["bad", "good"], "limit": 10})

    with patch("src.sources.vk.vk_api.VkApi", return_value=session), patch(
        "src.sources.vk.settings"
    ) as st:
        st.VK_ACCESS_TOKEN = "token"
        posts = await src.fetch(now - timedelta(days=1))

    assert len(posts) == 1
    assert posts[0].external_id == "-10_2"


def test_vk_registered():
    source = build_source(
        {
            "name": "vk_ru_tech",
            "type": "vk",
            "params": {"groups": ["tproger"]},
        }
    )

    assert isinstance(source, VkSource)
