"""Abstract base for file-host upload adapters."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncGenerator, Optional, Tuple
from pathlib import Path


class FileHostAdapter(ABC):
    """
    Contract every file-host adapter must implement.

    upload(path)           → (file_id, public_url)
    download_range(file_id, start, end) → async byte generator
    healthy()              → bool  (quick reachability check)
    """

    name: str  # must be set on each subclass
    # Set to False on adapters that handle whole-video parts (e.g. Streamtape,
    # Buzzheavier) so they are excluded from the fMP4 chunk upload loop.
    chunk_upload: bool = True

    @abstractmethod
    async def upload(self, path: Path) -> Tuple[str, str]:
        """Upload a file. Returns (file_id, public_url)."""

    @abstractmethod
    async def download_range(
        self,
        file_id: str,
        url: str,
        start: int,
        end: Optional[int],
    ) -> AsyncGenerator[bytes, None]:
        """
        Stream bytes [start, end] (inclusive, like HTTP Range).
        If end is None, stream to EOF.
        """
        # make this an async generator at the protocol level
        raise NotImplementedError
        yield  # pragma: no cover

    @abstractmethod
    async def healthy(self) -> bool:
        """Return True if the host is reachable and credentials are valid."""
