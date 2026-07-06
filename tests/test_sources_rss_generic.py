# tests/test_sources_rss_generic.py
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from src.sources.rss_generic import RssGenericSource

# hnrss-подобный фид: Points/Comments в description, RFC-822 дата.
FIXTURE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <item>
      <title>Show HN: My tool</title>
      <link>https://example.com/item?id=123</link>
      <guid>https://news.ycombinator.com/item?id=123</guid>
      <description><![CDATA[<p>Great <b>project</b>.</p> Points: 250 Comments: 42]]></description>
      <pubDate>Mon, 06 Jan 2025 10:00:00 +0300</pubDate>
      <author>alice</author>
    </item>
    <item>
      <title>No metrics post</title>
      <link>https://example.com/blog/hello</link>
      <description><![CDATA[<div>Just some &amp; text</div>]]></description>
      <pubDate>Tue, 07 Jan 2025 12:00:00 GMT</pubDate>
    </item>
    <item>
      <title>No pubdate skipped</title>
      <link>https://example.com/nodate</link>
      <description>whatever</description>
    </item>
  </channel>
</rss>
""".encode("utf-8")


@pytest.mark.asyncio
async def test_rss_generic_parsing():
    src = RssGenericSource(name="test_rss", params={"url": "http://fake"})
    since = datetime(2020, 1, 1, tzinfo=timezone.utc)

    with patch("src.sources.rss_generic.fetch_bytes", return_value=FIXTURE_XML):
        posts = await src.fetch(since)

    assert len(posts) == 2

    p1 = posts[0]
    assert p1.source_name == "test_rss"
    assert p1.title == "Show HN: My tool"
    assert p1.author == "alice"
    assert p1.external_id == "https://news.ycombinator.com/item?id=123"
    assert p1.engagement == 250
    assert "<b>" not in p1.content
    assert "Great project" in p1.content
    assert p1.published_at.tzinfo == timezone.utc
    assert p1.published_at.hour == 7  # 10:00 +03:00 -> 07:00 UTC

    p2 = posts[1]
    assert len(p2.external_id) == 32
    assert all(c in "0123456789abcdef" for c in p2.external_id)
    assert p2.engagement is None
    assert "&" in p2.content


@pytest.mark.asyncio
async def test_rss_generic_since_filter():
    src = RssGenericSource(name="test_rss", params={"url": "http://fake"})
    since = datetime(2030, 1, 1, tzinfo=timezone.utc)

    with patch("src.sources.rss_generic.fetch_bytes", return_value=FIXTURE_XML):
        posts = await src.fetch(since)

    assert posts == []


@pytest.mark.asyncio
async def test_rss_generic_fetch_error_returns_empty():
    src = RssGenericSource(name="test_rss", params={"url": "http://fake"})
    since = datetime(2020, 1, 1, tzinfo=timezone.utc)

    with patch("src.sources.rss_generic.fetch_bytes", side_effect=RuntimeError("boom")):
        posts = await src.fetch(since)

    assert posts == []