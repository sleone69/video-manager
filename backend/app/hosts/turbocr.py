"""turbo.cr adapter STUB.

turbo.cr only exposes a browser-based popup uploader (/upload/api) and an
iframe embed (/embed/{id}). There is no documented server-side REST API for
programmatic uploads. This stub raises NotImplementedError so the registry
skips it gracefully.

TODO: If turbo.cr ever publishes an API, implement upload() and
      download_range() here following the same pattern as the other adapters.
"""
from __future__ import annotations

from pathlib import Path
from typing import AsyncGenerator, Optional, Tuple

from .base import FileHostAdapter


class TurboCRAdapter(FileHostAdapter):
    name = "turbocr"

    async def upload(self, path: Path) -> Tuple[str, str]:
        raise NotImplementedError(
            "turbo.cr has no server-side upload API. "
            "Implement when an API becomes available."
        )

    async def download_range(
        self,
        file_id: str,
        url: str,
        start: int,
        end: Optional[int],
    ) -> AsyncGenerator[bytes, None]:
        raise NotImplementedError("turbo.cr adapter is a stub.")
        yield  # pragma: no cover

    async def healthy(self) -> bool:
        return False
