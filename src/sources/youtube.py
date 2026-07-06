# src/sources/youtube.py
import asyncio
from datetime import datetime, timezone
from typing import Any

import structlog
from googleapiclient.discovery import build
from youtube_transcript_api import YouTubeTranscriptApi

from src.schemas.post import RawPost
from src.settings import settings
from src.sources.base import BaseSource

log = structlog.get_logger(__name__)

YOUTUBE_VIDEO_URL = "https://www.youtube.com/watch?v={video_id}"


class YouTubeSource(BaseSource):
    """
    Коннектор YouTube через YouTube Data API + youtube-transcript-api.

    params:
      channel_ids: list[str] - id каналов YouTube
      limit: int             - сколько новых видео запрашивать на канал (default 20)
    """

    type = "youtube"

    def __init__(self, name: str, params: dict[str, Any]) -> None:
        self.name = name
        self.params = params
        self.channel_ids: list[str] = params.get("channel_ids", []) or []
        self.limit: int = int(params.get("limit", 20))

    async def fetch(self, since: datetime) -> list[RawPost]:
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)

        if not settings.YOUTUBE_API_KEY:
            log.error("youtube.no_api_key", source=self.name)
            return []

        if not self.channel_ids:
            log.warning("youtube.no_channels", source=self.name)
            return []

        try:
            youtube = await asyncio.to_thread(self._build_client)
        except Exception:
            log.exception("youtube.client_failed", source=self.name)
            return []

        results: list[RawPost] = []
        for channel_id in self.channel_ids:
            try:
                video_ids = await asyncio.to_thread(
                    self._fetch_channel_video_ids,
                    youtube,
                    channel_id,
                )
                video_items = await asyncio.to_thread(
                    self._fetch_video_details,
                    youtube,
                    video_ids,
                )
            except Exception:
                log.exception(
                    "youtube.channel_failed",
                    source=self.name,
                    channel_id=channel_id,
                )
                continue

            for item in video_items:
                try:
                    post = await self._video_to_post(item, channel_id)
                except Exception as e:
                    log.warning(
                        "youtube.entry_parse_failed",
                        source=self.name,
                        channel_id=channel_id,
                        error=str(e),
                    )
                    continue

                if post is None:
                    continue
                if post.published_at <= since:
                    continue
                results.append(post)

        log.info("youtube.fetched", source=self.name, count=len(results))
        return results

    @staticmethod
    def _build_client() -> Any:
        return build(
            "youtube",
            "v3",
            developerKey=settings.YOUTUBE_API_KEY,
            cache_discovery=False,
        )

    def _fetch_channel_video_ids(self, youtube: Any, channel_id: str) -> list[str]:
        response = (
            youtube.search()
            .list(
                part="id",
                channelId=channel_id,
                maxResults=self.limit,
                order="date",
                type="video",
            )
            .execute()
        )
        ids: list[str] = []
        for item in response.get("items", []):
            video_id = item.get("id", {}).get("videoId")
            if video_id:
                ids.append(str(video_id))
        return ids

    @staticmethod
    def _fetch_video_details(
        youtube: Any,
        video_ids: list[str],
    ) -> list[dict[str, Any]]:
        if not video_ids:
            return []
        response = (
            youtube.videos()
            .list(
                part="snippet,statistics",
                id=",".join(video_ids),
            )
            .execute()
        )
        return [item for item in response.get("items", []) if isinstance(item, dict)]

    async def _video_to_post(
        self,
        item: dict[str, Any],
        channel_id: str,
    ) -> RawPost | None:
        video_id = item.get("id")
        if not video_id:
            return None

        snippet = item.get("snippet", {})
        if not isinstance(snippet, dict):
            return None

        published_at = self._parse_datetime(snippet.get("publishedAt"))
        if published_at is None:
            log.warning("youtube.no_pubdate", source=self.name, video_id=video_id)
            return None

        title = (snippet.get("title") or "").strip()
        description = (snippet.get("description") or "").strip()
        transcript = await self._fetch_transcript(video_id)
        content = self._build_content(description, transcript)

        statistics = item.get("statistics", {})
        views = statistics.get("viewCount") if isinstance(statistics, dict) else None

        return RawPost(
            source_name=self.name,
            external_id=str(video_id),
            url=YOUTUBE_VIDEO_URL.format(video_id=video_id),
            title=title,
            author=snippet.get("channelTitle"),
            content=content,
            published_at=published_at,
            rating=None,
            engagement=int(views) if views is not None else None,
            raw={
                "id": video_id,
                "channel_id": channel_id,
                "channelTitle": snippet.get("channelTitle"),
                "description": description,
                "has_transcript": bool(transcript),
                "statistics": statistics,
            },
        )

    async def _fetch_transcript(self, video_id: str) -> str:
        try:
            return await asyncio.to_thread(self._fetch_transcript_sync, video_id)
        except Exception as e:
            log.warning(
                "youtube.transcript_unavailable",
                source=self.name,
                video_id=video_id,
                error=str(e),
            )
            return ""

    @staticmethod
    def _fetch_transcript_sync(video_id: str) -> str:
        if hasattr(YouTubeTranscriptApi, "get_transcript"):
            snippets = YouTubeTranscriptApi.get_transcript(
                video_id,
                languages=["ru", "en"],
            )
            return YouTubeSource._join_transcript_snippets(snippets)

        api = YouTubeTranscriptApi()
        fetched = api.fetch(video_id, languages=["ru", "en"])
        snippets = fetched.to_raw_data() if hasattr(fetched, "to_raw_data") else fetched
        return YouTubeSource._join_transcript_snippets(snippets)

    @staticmethod
    def _join_transcript_snippets(snippets: Any) -> str:
        return " ".join(
            str(part.get("text", "")).strip()
            for part in snippets
            if isinstance(part, dict) and part.get("text")
        ).strip()

    @staticmethod
    def _build_content(description: str, transcript: str) -> str:
        parts: list[str] = []
        if description:
            parts.append(description)
        if transcript:
            parts.append(transcript)
        return "\n\n".join(parts)

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
