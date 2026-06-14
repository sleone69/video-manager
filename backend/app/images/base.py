"""Abstract base for image-host adapters."""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict


class ImageHostAdapter(ABC):
    name: str

    @abstractmethod
    async def upload(self, path: Path) -> Dict[str, str]:
        """Upload image. Returns a dict with at least {"url": "..."}."""
