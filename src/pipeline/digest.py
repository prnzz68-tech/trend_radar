# src/pipeline/digest.py

from datetime import datetime, timedelta, timezone
from pathlib import Path

import structlog

from src.db.engine import AsyncSessionLocal as async_session
from src.db.repository import get_posts_for_digest, save_digest
from src.llm.digest_builder import build_digest
from src.schemas.digest import DigestInput

logger = structlog.get_logger(__name__)

PROFILE_PATH = Path("config/prompts/user_profile.md")


async def run_digest(
    days: int = 7,
    min_relevance: int = 6,
    exclude_delivered: bool = True,
    is_manual: bool = False,
) -> int | None:
    period_end = datetime.now(timezone.utc)
    period_start = period_end - timedelta(days=days)

    async with async_session() as session:
        posts = await get_posts_for_digest(
            session=session,
            period_start=period_start,
            period_end=period_end,
            min_relevance=min_relevance,
            exclude_delivered=exclude_delivered,
        )

    if not posts:
        logger.info("nothing_to_digest", days=days, min_relevance=min_relevance)
        return None

    profile = PROFILE_PATH.read_text(encoding="utf-8")
    digest_input = DigestInput(
        period_start=period_start,
        period_end=period_end,
        posts=posts,
        profile=profile,
    )

    logger.info("digest_start", posts_count=len(posts))
    output = await build_digest(digest_input)

    async with async_session() as session:
        digest_id = await save_digest(
            session=session,
            content_md=output.content_md,
            period_start=period_start,
            period_end=period_end,
            post_ids=[p.post_id for p in posts],
            is_manual=is_manual,
        )

    logger.info("digest_saved", digest_id=digest_id, posts=len(posts))
    return digest_id