# src/sources/producthunt.py
from datetime import datetime, timezone
from typing import Any

import structlog

from src.schemas.post import RawPost
from src.settings import settings
from src.sources.base import BaseSource
from src.utils.http import post_json

log = structlog.get_logger(__name__)

PRODUCTHUNT_GRAPHQL_URL = "https://api.producthunt.com/v2/api/graphql"

_POSTS_QUERY = """
query ProductHuntPosts($first: Int!, $topic: String) {
  posts(first: $first, topic: $topic) {
    edges {
      node {
        id
        name
        tagline
        description
        votesCount
        url
        slug
        createdAt
        featuredAt
      }
    }
  }
}
"""


class ProductHuntSource(BaseSource):
    """
    Коннектор Product Hunt через GraphQL API.

    params:
      topic: str   - slug топика Product Hunt, например developer-tools
      limit: int   - сколько запусков запрашивать (default 20)
    """

    type = "producthunt"

    def __init__(self, name: str, params: dict[str, Any]) -> None:
        self.name = name
        self.params = params
        self.topic: str | None = params.get("topic") or None
        self.limit: int = int(params.get("limit", 20))

    async def fetch(self, since: datetime) -> list[RawPost]:
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)

        if not settings.PRODUCTHUNT_TOKEN:
            log.error("producthunt.no_token", source=self.name)
            return []

        try:
            payload = await self._request_posts()
        except Exception:
            log.exception("producthunt.fetch_failed", source=self.name, topic=self.topic)
            return []

        errors = payload.get("errors")
        if errors:
            log.error("producthunt.api_errors", source=self.name, errors=errors)
            return []

        edges = (
            payload.get("data", {})
            .get("posts", {})
            .get("edges", [])
        )

        results: list[RawPost] = []
        for edge in edges:
            node = edge.get("node") if isinstance(edge, dict) else None
            if not node:
                continue

            try:
                post = self._node_to_post(node)
            except Exception as e:
                log.warning(
                    "producthunt.entry_parse_failed",
                    source=self.name,
                    topic=self.topic,
                    error=str(e),
                )
                continue

            if post is None:
                continue
            if post.published_at <= since:
                continue
            results.append(post)

        log.info(
            "producthunt.fetched",
            source=self.name,
            topic=self.topic,
            count=len(results),
        )
        return results

    async def _request_posts(self) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {settings.PRODUCTHUNT_TOKEN}",
            "Content-Type": "application/json",
        }
        payload = {
            "query": _POSTS_QUERY,
            "variables": {
                "first": self.limit,
                "topic": self.topic,
            },
        }
        response = await post_json(
            PRODUCTHUNT_GRAPHQL_URL,
            headers=headers,
            json=payload,
        )
        return response if isinstance(response, dict) else {}

    def _node_to_post(self, node: dict[str, Any]) -> RawPost | None:
        external_id = node.get("id")
        if not external_id:
            return None

        published_at = self._parse_datetime(
            node.get("featuredAt") or node.get("createdAt")
        )
        if published_at is None:
            log.warning("producthunt.no_pubdate", source=self.name, id=external_id)
            return None

        title = (node.get("name") or "").strip()
        tagline = (node.get("tagline") or "").strip()
        description = (node.get("description") or "").strip()
        content = "\n\n".join(part for part in (tagline, description) if part)

        url = node.get("url") or self._fallback_url(node.get("slug"))
        if not url:
            return None

        votes_count = node.get("votesCount")
        engagement = int(votes_count) if votes_count is not None else None

        return RawPost(
            source_name=self.name,
            external_id=str(external_id),
            url=url,
            title=title,
            author=None,
            content=content,
            published_at=published_at,
            rating=None,
            engagement=engagement,
            raw={
                "id": external_id,
                "topic": self.topic,
                "slug": node.get("slug"),
                "votesCount": votes_count,
                "tagline": tagline,
                "description": description,
                "featuredAt": node.get("featuredAt"),
                "createdAt": node.get("createdAt"),
            },
        )

    @staticmethod
    def _fallback_url(slug: str | None) -> str | None:
        if not slug:
            return None
        return f"https://www.producthunt.com/posts/{slug}"

    @staticmethod
    def _parse_datetime(raw: str | None) -> datetime | None:
        if not raw:
            return None
        normalized = raw.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
