# src/sources/registry.py

from src.sources.base import BaseSource
from src.sources.habr import HabrSource
from src.sources.producthunt import ProductHuntSource
from src.sources.reddit import RedditSource
from src.sources.rss_generic import RssGenericSource
from src.sources.telegram import TelegramSource
from src.sources.vk import VkSource
from src.sources.youtube import YouTubeSource

SOURCE_TYPES: dict[str, type[BaseSource]] = {
    "habr": HabrSource,
    "rss_generic": RssGenericSource,
    "reddit": RedditSource,
    "producthunt": ProductHuntSource,
    "vk": VkSource,
    "telegram": TelegramSource,
    "youtube": YouTubeSource,
}


def build_source(config: dict) -> BaseSource:
    """
    config = {"name": "...", "type": "habr", "enabled": true, "params": {...}}
    """
    type_ = config["type"]
    if type_ not in SOURCE_TYPES:
        raise ValueError(f"Unknown source type: {type_}")
    cls = SOURCE_TYPES[type_]
    return cls(name=config["name"], params=config.get("params", {}) or {})
