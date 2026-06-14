"""jpg.su image adapter STUB.

jpg.su only exposes a client-side JS widget (pup.js); there is no documented
server-side REST API for programmatic uploads from a backend.

TODO: If jpg.su publishes a server API, implement upload() here.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict

from .base import ImageHostAdapter


class JpgSuAdapter(ImageHostAdapter):
    name = "jpgsu"

    async def upload(self, path: Path) -> Dict[str, str]:
        raise NotImplementedError(
            "jpg.su has no server-side upload API. "
            "Implement when an API becomes available."
        )
