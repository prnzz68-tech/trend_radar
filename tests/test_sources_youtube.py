# tests/test_sources_youtube.py
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.sources.registry import build_source
from src.sources.youtube import YouTubeSource


def _request(response: dict) -> MagicMock:
    req = MagicMock()
    req.execute.return_value = response
    return req


def _build_youtube(search_items: list[dict], video_items: list[dict]) -> MagicMock:
    youtube = MagicMock()
    youtube.search.return_value.list.return_value = _request({"items": search_items})
    youtube.videos.return_value.list.return_value = _request({"items": video_items})
    return youtube


def _video_item(
    video_id: str,
    published_at: str,
    title: str = "Fresh video",
    description: str = "Video description",
    views: str | None = "1234",
) -> dict:
    statistics = {} if views is None else {"viewCount": views}
    return {
        "id": video_id,
        "snippet": {
            "publishedAt": published_at,
            "title": title,
            "description": description,
            "channelTitle": "Test Channel",
        },
        "statistics": statistics,
    }


@pytest.mark.asyncio
async def test_youtube_fetch_maps_fields_transcript_and_filters_since():
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=1)
    fresh = _video_item("vid1", now.isoformat().replace("+00:00", "Z"))
    old = _video_item(
        "old",
        (now - timedelta(days=10)).isoformat().replace("+00:00", "Z"),
        title="Old video",
        views="999",
    )
    youtube = _build_youtube(
        search_items=[
            {"id": {"videoId": "vid1"}},
            {"id": {"videoId": "old"}},
        ],
        video_items=[fresh, old],
    )

    src = YouTubeSource(
        name="youtube_startup_data",
        params={"channel_ids": ["UC123"], "limit": 5},
    )

    with patch("src.sources.youtube.build", return_value=youtube), patch(
        "src.sources.youtube.settings"
    ) as st, patch.object(
        YouTubeSource,
        "_fetch_transcript_sync",
        return_value="Transcript text",
    ):
        st.YOUTUBE_API_KEY = "key"
        posts = await src.fetch(since)

    assert len(posts) == 1
    p = posts[0]
    assert p.source_name == "youtube_startup_data"
    assert p.external_id == "vid1"
    assert str(p.url) == "https://www.youtube.com/watch?v=vid1"
    assert p.title == "Fresh video"
    assert p.author == "Test Channel"
    assert p.content == "Video description\n\nTranscript text"
    assert p.engagement == 1234
    assert p.published_at.tzinfo == timezone.utc
    assert p.raw["has_transcript"] is True
    youtube.search.return_value.list.assert_called_once_with(
        part="id",
        channelId="UC123",
        maxResults=5,
        order="date",
        type="video",
    )


@pytest.mark.asyncio
async def test_youtube_transcript_error_keeps_description_only():
    now = datetime.now(timezone.utc)
    youtube = _build_youtube(
        search_items=[{"id": {"videoId": "vid2"}}],
        video_items=[
            _video_item("vid2", now.isoformat(), description="Only description")
        ],
    )
    src = YouTubeSource(name="youtube_test", params={"channel_ids": ["UC123"]})

    with patch("src.sources.youtube.build", return_value=youtube), patch(
        "src.sources.youtube.settings"
    ) as st, patch.object(
        YouTubeSource,
        "_fetch_transcript_sync",
        side_effect=RuntimeError("no transcript"),
    ):
        st.YOUTUBE_API_KEY = "key"
        posts = await src.fetch(now - timedelta(days=1))

    assert len(posts) == 1
    assert posts[0].content == "Only description"
    assert posts[0].raw["has_transcript"] is False


@pytest.mark.asyncio
async def test_youtube_no_api_key_returns_empty():
    src = YouTubeSource(name="youtube_test", params={"channel_ids": ["UC123"]})

    with patch("src.sources.youtube.settings") as st:
        st.YOUTUBE_API_KEY = ""
        posts = await src.fetch(datetime.now(timezone.utc) - timedelta(days=1))

    assert posts == []


@pytest.mark.asyncio
async def test_youtube_channel_error_does_not_break_others():
    now = datetime.now(timezone.utc)
    youtube = MagicMock()

    def search_list(**kwargs):
        if kwargs["channelId"] == "bad":
            raise RuntimeError("api error")
        return _request({"items": [{"id": {"videoId": "ok"}}]})

    youtube.search.return_value.list.side_effect = search_list
    youtube.videos.return_value.list.return_value = _request(
        {"items": [_video_item("ok", now.isoformat())]}
    )

    src = YouTubeSource(
        name="youtube_multi",
        params={"channel_ids": ["bad", "good"], "limit": 10},
    )

    with patch("src.sources.youtube.build", return_value=youtube), patch(
        "src.sources.youtube.settings"
    ) as st, patch.object(
        YouTubeSource,
        "_fetch_transcript_sync",
        return_value="Transcript",
    ):
        st.YOUTUBE_API_KEY = "key"
        posts = await src.fetch(now - timedelta(days=1))

    assert len(posts) == 1
    assert posts[0].external_id == "ok"


def test_youtube_registered():
    source = build_source(
        {
            "name": "youtube_startup_data",
            "type": "youtube",
            "params": {"channel_ids": ["UC123"]},
        }
    )

    assert isinstance(source, YouTubeSource)
