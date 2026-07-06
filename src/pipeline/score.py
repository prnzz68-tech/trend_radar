# src/pipeline/score.py

import asyncio

import structlog

from src.db.engine import AsyncSessionLocal as async_session_factory
from src.db.repository import get_unscored_posts, save_score
from src.llm.scorer import score_post
from src.schemas.post import PostForScoring
from src.settings import settings

log = structlog.get_logger(__name__)

_CONCURRENCY = 5


async def _process_one(
    post: PostForScoring,
    sem: asyncio.Semaphore,
) -> tuple[int, int | None, Exception | None]:
    """Возвращает (post_id, tokens|None, error|None). LLM-вызов вне БД-сессии."""
    async with sem:
        try:
            score, tokens = await score_post(post)
        except Exception as e:
            log.exception("score.failed", post_id=post.id, error=str(e))
            return post.id, None, e

        try:
            async with async_session_factory() as session:
                await save_score(
                    session, post.id, score, settings.OPENAI_MODEL_SCORE, tokens
                )
                await session.commit()
        except Exception as e:
            log.exception("score.save_failed", post_id=post.id, error=str(e))
            return post.id, None, e

        return post.id, tokens, None


async def run_score(limit: int = 50) -> dict:
    async with async_session_factory() as session:
        posts = await get_unscored_posts(session, limit)

    if not posts:
        log.info("score.no_posts")
        return {"processed": 0, "failed": 0, "total_tokens": 0}

    log.info("score.start", count=len(posts))
    sem = asyncio.Semaphore(_CONCURRENCY)
    results = await asyncio.gather(*(_process_one(p, sem) for p in posts))

    processed = sum(1 for _, _, err in results if err is None)
    failed = sum(1 for _, _, err in results if err is not None)
    total_tokens = sum(t or 0 for _, t, _ in results)

    log.info(
        "score.done",
        processed=processed,
        failed=failed,
        total_tokens=total_tokens,
    )
    return {"processed": processed, "failed": failed, "total_tokens": total_tokens}