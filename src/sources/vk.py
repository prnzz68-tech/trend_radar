# src/sources/vk.py
from datetime import datetime, timezone
from typing import Any

import asyncio
import structlog
import vk_api

from src.schemas.post import RawPost
from src.settings import settings
from src.sources.base import BaseSource

log = structlog.get_logger(__name__)


class VkSource(BaseSource):
    """
    Коннектор VK через vk_api.

    params:
      groups: list[str | int] - домены или id пабликов
      limit: int              - сколько постов запрашивать на группу (default 50)
    """

    type = "vk"

    def __init__(self, name: str, params: dict[str, Any]) -> None:
        self.name = name
        self.params = params
        self.groups: list[str | int] = params.get("groups", []) or []
        self.limit: int = int(params.get("limit", 50))

    async def fetch(self, since: datetime) -> list[RawPost]:
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)

        if not settings.VK_ACCESS_TOKEN:
            log.error("vk.no_token", source=self.name)
            return []

        if not self.groups:
            log.warning("vk.no_groups", source=self.name)
            return []

        try:
            vk = await asyncio.to_thread(self._build_client)
        except Exception:
            log.exception("vk.client_failed", source=self.name)
            return []

        results: list[RawPost] = []
        for group in self.groups:
            try:
                group_posts = await asyncio.to_thread(self._fetch_group, vk, group)
            except Exception:
                log.exception("vk.group_failed", source=self.name, group=group)
                continue

            for item in group_posts:
                try:
                    post = self._item_to_post(item, group)
                except Exception as e:
                    log.warning(
                        "vk.entry_parse_failed",
                        source=self.name,
                        group=group,
                        error=str(e),
                    )
                    continue

                if post is None:
                    continue
                if post.published_at <= since:
                    continue
                results.append(post)

        log.info("vk.fetched", source=self.name, count=len(results))
        return results

    @staticmethod
    def _build_client() -> Any:
        session = vk_api.VkApi(token=settings.VK_ACCESS_TOKEN)
        return session.get_api()

    def _fetch_group(self, vk: Any, group: str | int) -> list[dict[str, Any]]:
        params = self._wall_get_params(group)
        response = vk.wall.get(count=self.limit, **params)
        items = response.get("items", []) if isinstance(response, dict) else []
        return [item for item in items if isinstance(item, dict)]

    @staticmethod
    def _wall_get_params(group: str | int) -> dict[str, Any]:
        value = str(group).strip()
        if value.startswith("https://vk.com/"):
            value = value.rstrip("/").rsplit("/", 1)[-1]
        value = value.lstrip("@")

        if value.lstrip("-").isdigit():
            group_id = int(value)
            owner_id = group_id if group_id < 0 else -group_id
            return {"owner_id": owner_id}

        return {"domain": value}

    def _item_to_post(self, item: dict[str, Any], group: str | int) -> RawPost | None:
        post_id = item.get("id")
        owner_id = item.get("owner_id")
        if post_id is None or owner_id is None:
            return None

        timestamp = item.get("date")
        if timestamp is None:
            log.warning("vk.no_pubdate", source=self.name, group=group, id=post_id)
            return None

        text = (item.get("text") or "").strip()
        if not text:
            return None

        published_at = datetime.fromtimestamp(int(timestamp), tz=timezone.utc)
        engagement = (
            self._count_metric(item, "likes")
            + self._count_metric(item, "comments")
            + self._count_metric(item, "reposts")
        )
        external_id = f"{owner_id}_{post_id}"
        url = f"https://vk.com/wall{external_id}"

        return RawPost(
            source_name=self.name,
            external_id=external_id,
            url=url,
            title=self._title_from_text(text, group),
            author=str(owner_id),
            content=text,
            published_at=published_at,
            rating=None,
            engagement=engagement,
            raw={
                "group": group,
                "id": post_id,
                "owner_id": owner_id,
                "likes": item.get("likes"),
                "comments": item.get("comments"),
                "reposts": item.get("reposts"),
                "views": item.get("views"),
            },
        )

    @staticmethod
    def _count_metric(item: dict[str, Any], key: str) -> int:
        value = item.get(key)
        if not isinstance(value, dict):
            return 0
        count = value.get("count")
        return int(count) if count is not None else 0

    @staticmethod
    def _title_from_text(text: str, group: str | int) -> str:
        first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
        if not first_line:
            return f"VK post from {group}"
        if len(first_line) <= 120:
            return first_line
        return f"{first_line[:117].rstrip()}..."
