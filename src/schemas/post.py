# schemas/post.py

from datetime import datetime

from pydantic import BaseModel, HttpUrl


class RawPost(BaseModel):
    source_name: str
    external_id: str
    url: HttpUrl
    title: str
    author: str | None = None
    content: str = ""
    published_at: datetime
    rating: int | None = None
    engagement: int | None = None   # Этап 1: универсальная вовлечённость
    raw: dict = {}


class PostForScoring(BaseModel):
    id: int
    title: str
    content: str
    author: str | None
    source_name: str
    engagement: int | None = None   # Этап 1: прокидываем в промпт скоринга