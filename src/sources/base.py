# src/sources/base.py

from abc import ABC, abstractmethod
from datetime import datetime

from src.schemas.post import RawPost


class BaseSource(ABC):
    name: str
    type: str

    @abstractmethod
    async def fetch(self, since: datetime) -> list[RawPost]:
        ...