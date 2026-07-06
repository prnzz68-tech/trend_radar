# tests/test_sources_producthunt.py
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from src.sources.producthunt import ProductHuntSource
from src.sources.registry import build_source


GRAPHQL_RESPONSE = {
    "data": {
        "posts": {
            "edges": [
                {
                    "node": {
                        "id": "12345",
                        "name": "Launch Radar",
                        "tagline": "Find fresh startup launches",
                        "description": "Track what makers ship in your niche.",
                        "votesCount": 321,
                        "url": "https://www.producthunt.com/posts/launch-radar",
                        "slug": "launch-radar",
                        "createdAt": "2025-01-06T08:00:00Z",
                        "featuredAt": "2025-01-06T10:00:00+03:00",
                    }
                },
                {
                    "node": {
                        "id": "old",
                        "name": "Old Product",
                        "tagline": "Too old",
                        "description": "",
                        "votesCount": 999,
                        "url": "https://www.producthunt.com/posts/old-product",
                        "slug": "old-product",
                        "createdAt": "2020-01-01T00:00:00Z",
                        "featuredAt": "2020-01-01T00:00:00Z",
                    }
                },
            ]
        }
    }
}


@pytest.mark.asyncio
async def test_producthunt_fetch_maps_graphql_response_and_filters_since():
    src = ProductHuntSource(
        name="producthunt_developer_tools",
        params={"topic": "developer-tools", "limit": 10},
    )
    since = datetime(2025, 1, 1, tzinfo=timezone.utc)

    with patch("src.sources.producthunt.post_json", return_value=GRAPHQL_RESPONSE) as post_json, patch(
        "src.sources.producthunt.settings"
    ) as st:
        st.PRODUCTHUNT_TOKEN = "token"
        posts = await src.fetch(since)

    assert len(posts) == 1
    p = posts[0]
    assert p.source_name == "producthunt_developer_tools"
    assert p.external_id == "12345"
    assert p.title == "Launch Radar"
    assert p.engagement == 321
    assert p.content == "Find fresh startup launches\n\nTrack what makers ship in your niche."
    assert str(p.url) == "https://www.producthunt.com/posts/launch-radar"
    assert p.published_at == datetime(2025, 1, 6, 7, 0, tzinfo=timezone.utc)
    assert p.raw["topic"] == "developer-tools"

    _, kwargs = post_json.call_args
    assert kwargs["headers"]["Authorization"] == "Bearer token"
    assert kwargs["json"]["variables"] == {"first": 10, "topic": "developer-tools"}


@pytest.mark.asyncio
async def test_producthunt_api_errors_return_empty():
    src = ProductHuntSource(name="producthunt_ai", params={"topic": "artificial-intelligence"})

    with patch(
        "src.sources.producthunt.post_json",
        return_value={"errors": [{"message": "bad token"}]},
    ), patch("src.sources.producthunt.settings") as st:
        st.PRODUCTHUNT_TOKEN = "token"
        posts = await src.fetch(datetime(2025, 1, 1, tzinfo=timezone.utc))

    assert posts == []


@pytest.mark.asyncio
async def test_producthunt_no_token_returns_empty():
    src = ProductHuntSource(name="producthunt_productivity", params={"topic": "productivity"})

    with patch("src.sources.producthunt.settings") as st:
        st.PRODUCTHUNT_TOKEN = ""
        posts = await src.fetch(datetime(2025, 1, 1, tzinfo=timezone.utc))

    assert posts == []


def test_producthunt_registered():
    source = build_source(
        {
            "name": "producthunt_productivity",
            "type": "producthunt",
            "params": {"topic": "productivity"},
        }
    )

    assert isinstance(source, ProductHuntSource)
