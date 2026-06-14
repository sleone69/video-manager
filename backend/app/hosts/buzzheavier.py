"""Buzzheavier file-host adapter.

API docs: https://buzzheavier.com
Auth:     Authorization: Bearer {account_id}

Upload:   PUT https://w.buzzheavier.com/{parentId}/{filename}
          or  PUT https://w.buzzheavier.com/{filename}  (anonymous/root)
Download: The URL returned in the upload response is a direct CDN link
          that supports Range requests.
"""
from __future__ import annotations

import base64
from pathlib import Path
from typing import AsyncGenerator, Optional, Tuple

import aiohttp

from .base import FileHostAdapter
from ..config import settings

_UPLOAD_BASE = "https://w.buzzheavier.com"
_API_BASE = "https://buzzheavier.com/api"


class BuzzheavierAdapter(FileHostAdapter):
    name = "buzzheavier"
    chunk_upload = False  # uploads whole-video parts, not fMP4 chunks

    def __init__(self) -> None:
        self._account_id = settings.buzzheavier_account_id
        self._folder_id = settings.buzzheavier_folder_id

    def _headers(self) -> dict:
        if not self._account_id:
            raise RuntimeError(
                "Buzzheavier not configured. Set BUZZHEAVIER_ACCOUNT_ID in .env"
            )
        return {"Authorization": f"Bearer {self._account_id}"}

    async def upload(self, path: Path) -> Tuple[str, str]:
        headers = self._headers()
        # Build upload URL: /{folderId}/{filename} if folder set, else /{filename}
        name = path.name
        if self._folder_id:
            upload_url = f"{_UPLOAD_BASE}/{self._folder_id}/{name}"
        else:
            upload_url = f"{_UPLOAD_BASE}/{name}"

        async with aiohttp.ClientSession() as session:
            async with session.put(
                upload_url,
                data=open(path, "rb"),
                headers=headers,
            ) as resp:
                resp.raise_for_status()
                body = await resp.json(content_type=None)

        # API returns {"code": 200, "data": {"id": "...", "downloadPage": "...", ...}}
        data = body.get("data") or {}
        file_id = str(data.get("id", ""))
        download_url = (
            data.get("downloadPage")
            or data.get("url")
            or (f"https://buzzheavier.com/{file_id}" if file_id else "")
        )
        if not file_id:
            raise RuntimeError(f"Buzzheavier upload response missing file id: {body}")
        return file_id, download_url

    async def download_range(
        self,
        file_id: str,
        url: str,
        start: int,
        end: Optional[int],
    ) -> AsyncGenerator[bytes, None]:
        range_header = f"bytes={start}-" if end is None else f"bytes={start}-{end}"
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                headers={**self._headers(), "Range": range_header},
                allow_redirects=True,
            ) as resp:
                if resp.status not in (200, 206):
                    raise RuntimeError(
                        f"Buzzheavier range request failed: {resp.status} for {url}"
                    )
                async for chunk in resp.content.iter_chunked(65536):
                    yield chunk

    async def healthy(self) -> bool:
        if not self._account_id:
            return False
        try:
            timeout = aiohttp.ClientTimeout(total=5)
            async with aiohttp.ClientSession() as session:
                # Check credentials against the main API
                async with session.get(
                    f"{_API_BASE}/account",
                    headers=self._headers(),
                    timeout=timeout,
                ) as resp:
                    if resp.status != 200:
                        return False
                # Also verify the upload server is reachable (HEAD on the base URL)
                try:
                    async with session.head(
                        _UPLOAD_BASE,
                        timeout=timeout,
                        allow_redirects=True,
                    ) as uresp:
                        return uresp.status < 500
                except Exception:
                    # Upload server unreachable from this network
                    return False
        except Exception:
            return False
