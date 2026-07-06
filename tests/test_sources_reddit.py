# tests/test_sources_reddit.py
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.sources.reddit import RedditSource


def _make_submission(
    sub_id: str,
    title: str,
    created_utc: float,
    score: int,
    selftext: str = "",
    permalink: str = "/r/test/comments/x/y/",
    url: str = "https://example.com",
    author: str = "someuser",
    num_comments: int = 5,
    is_self: bool = True,
) -> MagicMock:
    s = MagicMock()
    s.id = sub_id
    s.title = title
    s.created_utc = created_utc
    s.score = score
    s.selftext = selftext
    s.permalink = permalink
    s.url = url
    s.author = author
    s.num_comments = num_comments
    s.is_self = is_self
    return s


class _AsyncIter:
    """Оборачивает список в async-итератор (эмулирует subreddit.new/top)."""

    def __init__(self, items: list) -> None:
        self._items = items

    def __aiter__(self):
        self._it = iter(self._items)
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration


def _build_mock_reddit(subreddit_mock: MagicMock) -> MagicMock:
    reddit = MagicMock()
    reddit.subreddit = AsyncMock(return_value=subreddit_mock)
    reddit.close = AsyncMock()
    return reddit


@pytest.mark.asyncio
async def test_reddit_fetch_filters_by_since_and_maps_fields():
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=1)

    fresh = _make_submission(
        "abc",
        "Fresh SaaS pain",
        created_utc=now.timestamp(),
        score=42,
        selftext="I wish there was a tool for X",
        permalink="/r/SaaS/comments/abc/fresh/",
    )
    old = _make_submission(
        "old",
        "Old post",
        created_utc=(now - timedelta(days=10)).timestamp(),
        score=100,
    )

    subreddit_mock = MagicMock()
    subreddit_mock.top = MagicMock(return_value=_AsyncIter([fresh, old]))
    subreddit_mock.new = MagicMock(return_value=_AsyncIter([fresh, old]))

    reddit_mock = _build_mock_reddit(subreddit_mock)

    src = RedditSource(
        name="reddit_saas",
        params={"subreddits": ["SaaS"], "listing": "top", "time_filter": "week"},
    )

    with patch("src.sources.reddit.asyncpraw.Reddit", return_value=reddit_mock), patch(
        "src.sources.reddit.settings"
    ) as st:
        st.REDDIT_CLIENT_ID = "id"
        st.REDDIT_CLIENT_SECRET = "secret"
        st.REDDIT_USER_AGENT = "ua"
        posts = await src.fetch(since)

    assert len(posts) == 1
    p = posts[0]
    assert p.external_id == "abc"
    assert p.engagement == 42
    assert p.content == "I wish there was a tool for X"
    assert str(p.url) == "https://www.reddit.com/r/SaaS/comments/abc/fresh/"
    assert p.source_name == "reddit_saas"
    reddit_mock.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_reddit_link_post_content_fallback():
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=7)

    link_post = _make_submission(
        "lnk",
        "Cool launch",
        created_utc=now.timestamp(),
        score=10,
        selftext="",
        url="https://producthunt.com/x",
        permalink="/r/SideProject/comments/lnk/cool/",
        is_self=False,
    )

    subreddit_mock = MagicMock()
    subreddit_mock.new = MagicMock(return_value=_AsyncIter([link_post]))

    reddit_mock = _build_mock_reddit(subreddit_mock)

    src = RedditSource(
        name="reddit_sideproject",
        params={"subreddits": ["SideProject"], "listing": "new"},
    )

    with patch("src.sources.reddit.asyncpraw.Reddit", return_value=reddit_mock), patch(
        "src.sources.reddit.settings"
    ) as st:
        st.REDDIT_CLIENT_ID = "id"
        st.REDDIT_CLIENT_SECRET = "secret"
        st.REDDIT_USER_AGENT = "ua"
        posts = await src.fetch(since)

    assert len(posts) == 1
    assert posts[0].content == "Cool launch https://producthunt.com/x"


@pytest.mark.asyncio
async def test_reddit_no_credentials_returns_empty():
    src = RedditSource(name="reddit_saas", params={"subreddits": ["SaaS"]})

    with patch("src.sources.reddit.settings") as st:
        st.REDDIT_CLIENT_ID = ""
        st.REDDIT_CLIENT_SECRET = ""
        st.REDDIT_USER_AGENT = "ua"
        posts = await src.fetch(datetime.now(timezone.utc) - timedelta(days=1))

    assert posts == []


@pytest.mark.asyncio
async def test_reddit_subreddit_error_does_not_break_others():
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=1)

    good = _make_submission(
        "ok", "Good", created_utc=now.timestamp(), score=5, selftext="text"
    )

    ok_sub = MagicMock()
    ok_sub.new = MagicMock(return_value=_AsyncIter([good]))

    async def subreddit_side_effect(name: str):
        if name == "bad":
            raise RuntimeError("403 Forbidden")
        return ok_sub

    reddit_mock = MagicMock()
    reddit_mock.subreddit = AsyncMock(side_effect=subreddit_side_effect)
    reddit_mock.close = AsyncMock()

    src = RedditSource(
        name="reddit_multi",
        params={"subreddits": ["bad", "good"], "listing": "new"},
    )

    with patch("src.sources.reddit.asyncpraw.Reddit", return_value=reddit_mock), patch(
        "src.sources.reddit.settings"
    ) as st:
        st.REDDIT_CLIENT_ID = "id"
        st.REDDIT_CLIENT_SECRET = "secret"
        st.REDDIT_USER_AGENT = "ua"
        posts = await src.fetch(since)

    assert len(posts) == 1
    assert posts[0].external_id == "ok"
    reddit_mock.close.assert_awaited_once()