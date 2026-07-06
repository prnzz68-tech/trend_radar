# src/db/repository.py

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, func, update, insert, and_, not_, exists
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import (
    Source,
    Post,
    PostScore,
    Digest,
    DigestPost,
    DeliveryLog,
)
from src.schemas.post import RawPost, PostForScoring
from src.schemas.digest import PostWithScore
from src.schemas.score import PostScore as PostScoreSchema

async def upsert_source(
    session: AsyncSession,
    name: str,
    type_: str,
    config: dict[str, Any],
) -> int:
    stmt = (
        pg_insert(Source)
        .values(name=name, type=type_, config_json=config, is_active=True)
        .on_conflict_do_update(
            index_elements=[Source.name],
            set_={"type": type_, "config_json": config, "is_active": True},
        )
        .returning(Source.id)
    )
    result = await session.execute(stmt)
    await session.commit()
    return int(result.scalar_one())


async def upsert_posts(
    session: AsyncSession,
    source_id: int,
    posts: list[RawPost],
) -> int:
    if not posts:
        return 0

    rows = []
    for p in posts:
        published = p.published_at
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        rows.append(
            {
                "source_id": source_id,
                "external_id": p.external_id,
                "url": str(p.url),
                "title": p.title,
                "author": p.author,
                "content": p.content,
                "published_at": published,
                "rating": p.rating,
                "engagement": p.engagement,   # Этап 1
                "raw_json": p.raw,
            }
        )

    stmt = pg_insert(Post).values(rows)
    stmt = stmt.on_conflict_do_nothing(index_elements=["source_id", "external_id"])
    result = await session.execute(stmt)
    await session.commit()
    return result.rowcount or 0


async def get_last_collected_at(session: AsyncSession, source_id: int) -> datetime | None:
    stmt = select(func.max(Post.collected_at)).where(Post.source_id == source_id)
    result = await session.execute(stmt)
    value = result.scalar_one_or_none()
    if value and value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value



async def get_unscored_posts(
    session: AsyncSession, limit: int
) -> list[PostForScoring]:
    """Посты без любой записи в post_scores. MVP: без учёта модели."""
    stmt = (
        select(
            Post.id, Post.title, Post.content, Post.author,
            Source.name, Post.engagement,   # Этап 1
        )
        .join(Source, Source.id == Post.source_id)
        .outerjoin(PostScore, PostScore.post_id == Post.id)
        .where(PostScore.id.is_(None))
        .order_by(Post.published_at.desc())
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()
    return [
        PostForScoring(
            id=row[0],
            title=row[1],
            content=row[2] or "",
            author=row[3],
            source_name=row[4],
            engagement=row[5],
        )
        for row in rows
    ]


async def save_score(
    session: AsyncSession,
    post_id: int,
    score: PostScoreSchema,
    model: str,
    tokens: int,
) -> None:
    obj = PostScore(
        post_id=post_id,
        relevance_score=score.relevance_score,
        category=score.category,
        summary=score.summary,
        problem=score.problem,            # Этап 1
        opportunity=score.opportunity,    # Этап 1
        topics=score.topics,
        model=model,
        tokens_used=tokens,
    )
    session.add(obj)
    await session.flush()



async def get_posts_for_digest(
    session: AsyncSession,
    period_start: datetime,
    period_end: datetime,
    min_relevance: int,
    exclude_delivered: bool,
) -> list[PostWithScore]:
    stmt = (
        select(Post, PostScore, Source.name)
        .join(PostScore, PostScore.post_id == Post.id)
        .join(Source, Source.id == Post.source_id)
        .where(
            and_(
                PostScore.relevance_score >= min_relevance,
                Post.published_at >= period_start,
                Post.published_at <= period_end,
            )
        )
    )
    if exclude_delivered:
        stmt = stmt.where(
            not_(exists().where(DeliveryLog.post_id == Post.id))
        )

    rows = (await session.execute(stmt)).all()
    result: list[PostWithScore] = []
    for post, score, source_name in rows:
        result.append(
            PostWithScore(
                post_id=post.id,
                title=post.title,
                url=str(post.url),
                summary=score.summary,
                category=score.category,
                topics=list(score.topics or []),
                relevance_score=score.relevance_score,
                rating=post.rating,
                engagement=post.engagement,         # Этап 1
                problem=score.problem,              # Этап 1
                opportunity=score.opportunity,      # Этап 1
                source_name=source_name,
                published_at=post.published_at,
            )
        )
    return result


async def save_digest(
    session: AsyncSession,
    content_md: str,
    period_start: datetime,
    period_end: datetime,
    post_ids: list[int],
    is_manual: bool,
) -> int:
    digest = Digest(
        period_start=period_start,
        period_end=period_end,
        content_md=content_md,
        is_manual=is_manual,
    )
    session.add(digest)
    await session.flush()  # получить digest.id

    for pid in post_ids:
        session.add(DigestPost(digest_id=digest.id, post_id=pid))

    await session.commit()
    return digest.id




async def get_digest(session: AsyncSession, digest_id: int) -> tuple[str, list[int]]:
    digest = await session.get(Digest, digest_id)
    if digest is None:
        raise ValueError(f"Digest {digest_id} not found")
    rows = await session.execute(
        select(DigestPost.post_id).where(DigestPost.digest_id == digest_id)
    )
    post_ids = [r[0] for r in rows.all()]
    return digest.content_md, post_ids


async def mark_digest_delivered(
    session: AsyncSession, digest_id: int, post_ids: list[int]
) -> None:
    now = datetime.now(timezone.utc)
    await session.execute(
        update(Digest).where(Digest.id == digest_id).values(sent_at=now)
    )
    if post_ids:
        await session.execute(
            insert(DeliveryLog),
            [
                {"post_id": pid, "digest_id": digest_id, "sent_at": now}
                for pid in post_ids
            ],
        )
    await session.commit()


async def get_status_stats(session: AsyncSession) -> dict:
    posts_total = (await session.execute(select(func.count(Post.id)))).scalar_one()
    posts_scored = (await session.execute(select(func.count(PostScore.id)))).scalar_one()
    last_collected = (await session.execute(select(func.max(Post.collected_at)))).scalar_one()
    last_sent = (await session.execute(select(func.max(Digest.sent_at)))).scalar_one()
    digests_sent = (
        await session.execute(
            select(func.count(Digest.id)).where(Digest.sent_at.is_not(None))
        )
    ).scalar_one()
    return {
        "posts_total": posts_total,
        "posts_scored": posts_scored,
        "last_collected_at": last_collected,
        "last_digest_sent_at": last_sent,
        "digests_sent_count": digests_sent,
    }