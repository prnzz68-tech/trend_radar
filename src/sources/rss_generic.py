# src/sources/rss_generic.py
import asyncio
import hashlib
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import feedparser
import structlog
from bs4 import BeautifulSoup

from src.schemas.post import RawPost
from src.sources.base import BaseSource
from src.utils.http import fetch_bytes

log = structlog.get_logger(__name__)

# hnrss кладёт метрики в описание: "Points: 123", "Comments: 45"
_POINTS_RE = re.compile(r"Points:\s*(\d+)", re.IGNORECASE)
_COMMENTS_RE = re.compile(r"Comments:\s*(\d+)", re.IGNORECASE)


class RssGenericSource(BaseSource):
    """Универсальный RSS/Atom-коннектор. Читает произвольный фид по params.url."""

    type = "rss_generic"

    def __init__(self, name: str, params: dict[str, Any]) -> None:
        self.name = name
        self.params = params
        self.url: str = params["url"]

    async def fetch(self, since: datetime) -> list[RawPost]:
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)

        try:
            body = await fetch_bytes(self.url)
        except Exception:
            log.exception("rss.fetch_failed", source=self.name, url=self.url)
            return []

        parsed = await asyncio.to_thread(feedparser.parse, body)

        results: list[RawPost] = []
        for entry in parsed.entries:
            try:
                post = self._entry_to_post(entry)
            except Exception as e:
                log.warning("rss.entry_parse_failed", source=self.name, error=str(e))
                continue

            if post is None:
                continue
            if post.published_at <= since:
                continue
            results.append(post)

        log.info("rss.fetched", source=self.name, url=self.url, count=len(results))
        return results

    def _entry_to_post(self, entry: Any) -> RawPost | None:
        url = entry.get("link")
        if not url:
            return None

        external_id = entry.get("id") or self._hash_url(url)

        published_at = self._parse_pubdate(entry)
        if published_at is None:
            log.warning("rss.no_pubdate", source=self.name, url=url)
            return None

        title = (entry.get("title") or "").strip()
        author = entry.get("author") or None

        raw_content = ""
        if "content" in entry and entry.content:
            raw_content = entry.content[0].get("value", "") or ""
        if not raw_content:
            raw_content = entry.get("summary", "") or ""

        content = self._clean_html(raw_content)
        engagement = self._extract_engagement(raw_content)

        return RawPost(
            source_name=self.name,
            external_id=str(external_id),
            url=url,
            title=title,
            author=author,
            content=content,
            published_at=published_at,
            rating=None,
            engagement=engagement,
            raw={
                "id": entry.get("id"),
                "tags": [t.get("term") for t in entry.get("tags", []) if t.get("term")],
                "summary": entry.get("summary"),
            },
        )

    @staticmethod
    def _hash_url(url: str) -> str:
        return hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]

    @staticmethod
    def _clean_html(raw: str) -> str:
        if not raw:
            return ""
        # html.parser — встроенный, не требует lxml.
        text = BeautifulSoup(raw, "html.parser").get_text(separator=" ", strip=True)
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _extract_engagement(raw: str) -> int | None:
        # hnrss отдаёт Points/Comments в описании; иначе метрики нет.
        m = _POINTS_RE.search(raw)
        if m:
            return int(m.group(1))
        m = _COMMENTS_RE.search(raw)
        if m:
            return int(m.group(1))
        return None

    @staticmethod
    def _parse_pubdate(entry: Any) -> datetime | None:
        raw = entry.get("published") or entry.get("updated")
        if not raw:
            return None
        try:
            dt = parsedate_to_datetime(raw)
        except Exception:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)