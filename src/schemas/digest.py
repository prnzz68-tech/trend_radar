from datetime import datetime
from pydantic import BaseModel


class PostWithScore(BaseModel):
    post_id: int
    title: str
    url: str
    summary: str
    category: str
    topics: list[str]
    relevance_score: int
    rating: int | None
    engagement: int | None = None     # Этап 1
    problem: str | None = None        # Этап 1
    opportunity: str | None = None    # Этап 1
    source_name: str
    published_at: datetime


class DigestInput(BaseModel):
    period_start: datetime
    period_end: datetime
    posts: list[PostWithScore]
    profile: str


class DigestOutput(BaseModel):
    content_md: str