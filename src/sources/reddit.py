# src/sources/reddit.py
from datetime import datetime, timezone
from typing import Any

import asyncpraw
import structlog

from src.schemas.post import RawPost
from src.settings import settings
from src.sources.base import BaseSource

log = structlog.get_logger(__name__)

_ALLOWED_LISTINGS = {"new", "top"}
_ALLOWED_TIME_FILTERS = {"hour", "day", "week", "month", "year", "all"}


class RedditSource(BaseSource):
    """
    Коннектор Reddit через asyncpraw.

    params:
      subreddits: list[str]   — список сабреддитов (без r/)
      listing: "new" | "top"  — тип выборки (default "new")
      time_filter: str        — для listing=top (hour/day/week/month/year/all), default "week"
      limit: int              — сколько постов запрашивать на сабреддит (default 50)
    """

    type = "reddit"

    def __init__(self, name: str, params: dict[str, Any]) -> None:
        self.name = name
        self.params = params
        self.subreddits: list[str] = params.get("subreddits", []) or []

        listing = (params.get("listing") or "new").lower()
        if listing not in _ALLOWED_LISTINGS:
            log.warning("reddit.bad_listing", source=name, listing=listing)
            listing = "new"
        self.listing = listing

        time_filter = (params.get("time_filter") or "week").lower()
        if time_filter not in _ALLOWED_TIME_FILTERS:
            log.warning("reddit.bad_time_filter", source=name, time_filter=time_filter)
            time_filter = "week"
        self.time_filter = time_filter

        self.limit: int = int(params.get("limit", 50))

    async def fetch(self, since: datetime) -> list[RawPost]:
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)

        if not settings.REDDIT_CLIENT_ID or not settings.REDDIT_CLIENT_SECRET:
            log.error("reddit.no_credentials", source=self.name)
            return []

        if not self.subreddits:
            log.warning("reddit.no_subreddits", source=self.name)
            return []

        reddit = asyncpraw.Reddit(
            client_id=settings.REDDIT_CLIENT_ID,
            client_secret=settings.REDDIT_CLIENT_SECRET,
            user_agent=settings.REDDIT_USER_AGENT,
        )

        results: list[RawPost] = []
        try:
            for sub_name in self.subreddits:
                try:
                    sub_posts = await self._fetch_subreddit(reddit, sub_name, since)
                    results.extend(sub_posts)
                except Exception:
                    # Ошибка по одному сабреддиту — логируем и продолжаем.
                    log.exception(
                        "reddit.subreddit_failed", source=self.name, subreddit=sub_name
                    )
                    continue
        finally:
            await reddit.close()

        log.info("reddit.fetched", source=self.name, count=len(results))
        return results

    async def _fetch_subreddit(
        self, reddit: "asyncpraw.Reddit", sub_name: str, since: datetime
    ) -> list[RawPost]:
        subreddit = await reddit.subreddit(sub_name)

        if self.listing == "top":
            submissions = subreddit.top(time_filter=self.time_filter, limit=self.limit)
        else:
            submissions = subreddit.new(limit=self.limit)

        posts: list[RawPost] = []
        async for submission in submissions:
            try:
                post = self._submission_to_post(submission, sub_name)
            except Exception as e:
                log.warning(
                    "reddit.entry_parse_failed",
                    source=self.name,
                    subreddit=sub_name,
                    error=str(e),
                )
                continue

            if post is None:
                continue
            if post.published_at <= since:
                continue
            posts.append(post)

        return posts

    def _submission_to_post(self, submission: Any, sub_name: str) -> RawPost | None:
        external_id = submission.id
        if not external_id:
            return None

        published_at = datetime.fromtimestamp(
            submission.created_utc, tz=timezone.utc
        )

        title = (submission.title or "").strip()
        author = str(submission.author) if submission.author else None

        # content: selftext для текстовых постов, иначе title + url (ссылочный пост).
        selftext = (submission.selftext or "").strip()
        if selftext:
            content = selftext
        else:
            content = f"{title} {submission.url or ''}".strip()

        return RawPost(
            source_name=self.name,
            external_id=str(external_id),
            url=f"https://www.reddit.com{submission.permalink}",
            title=title,
            author=author,
            content=content,
            published_at=published_at,
            rating=None,
            engagement=int(submission.score) if submission.score is not None else None,
            raw={
                "subreddit": sub_name,
                "id": external_id,
                "num_comments": getattr(submission, "num_comments", None),
                "is_self": getattr(submission, "is_self", None),
                "link_url": submission.url,
            },
        )