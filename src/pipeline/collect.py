
# src/pipeline/collect.py

from datetime import datetime, timedelta, timezone
from pathlib import Path

import structlog
import yaml

from src.db.engine import AsyncSessionLocal as async_session_maker
from src.db.repository import (
    get_last_collected_at,
    upsert_posts,
    upsert_source,
)
from src.schemas.post import RawPost
from src.sources.registry import build_source

log = structlog.get_logger(__name__)

CONFIG_PATH = Path("config/sources.yaml")
COLD_START_WINDOW = timedelta(days=7)


def _load_sources_config() -> list[dict]:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("sources", []) or []


def apply_filters(
    posts: list[RawPost], filters: dict, *, source: str
) -> list[RawPost]:
    """Общие фильтры уровня ядра.

    - min_rating: отсеивает посты с rating < порога. Если rating is None — пропускается.
    - min_engagement: отсеивает посты с engagement < порога. Если engagement is None — пропускается.
    """
    if not filters:
        return posts

    min_rating = filters.get("min_rating")
    min_engagement = filters.get("min_engagement")

    if min_rating is None and min_engagement is None:
        return posts

    kept: list[RawPost] = []
    dropped_rating = 0
    dropped_engagement = 0

    for post in posts:
        if min_rating is not None and post.rating is not None and post.rating < min_rating:
            dropped_rating += 1
            continue
        if (
            min_engagement is not None
            and post.engagement is not None
            and post.engagement < min_engagement
        ):
            dropped_engagement += 1
            continue
        kept.append(post)

    log.info(
        "collect.filtered",
        source=source,
        before=len(posts),
        after=len(kept),
        dropped_by_rating=dropped_rating,
        dropped_by_engagement=dropped_engagement,
        min_rating=min_rating,
        min_engagement=min_engagement,
    )
    return kept


async def run_collect() -> dict[str, int]:
    stats: dict[str, int] = {}
    sources_cfg = _load_sources_config()
    now = datetime.now(timezone.utc)

    for cfg in sources_cfg:
        name = cfg.get("name")
        if not name:
            log.warning("collect.source_skipped_no_name", cfg=cfg)
            continue
        if not cfg.get("enabled", True):
            log.info("collect.source_disabled", source=name)
            continue

        try:
            async with async_session_maker() as session:
                source_id = await upsert_source(
                    session, name=name, type_=cfg["type"], config=cfg.get("params", {}) or {}
                )
                last = await get_last_collected_at(session, source_id)

            since = max(last, now - COLD_START_WINDOW) if last else now - COLD_START_WINDOW

            source = build_source(cfg)
            posts = await source.fetch(since)

            filters = cfg.get("filters", {}) or {}
            posts = apply_filters(posts, filters, source=name)

            async with async_session_maker() as session:
                new_count = await upsert_posts(session, source_id, posts)

            stats[name] = new_count
            log.info("collect.done", source=name, found=len(posts), new=new_count)

        except Exception:
            log.exception("collect.source_failed", source=name)
            stats[name] = 0
            continue

    return stats