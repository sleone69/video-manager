"""Pixeldrain file-host adapter.

API base:  https://pixeldrain.com/api
Auth:      HTTP Basic, username="" password=<api_key>

⚠ Free-tier rate-limits: range requests get captcha when downloads > 3× views.
  Recommend: (a) use a premium key, or (b) keep this adapter lower in
  stream_host_priority so it is only tried after Gofile/Filester/Cyberfile.
  pixeldrain_priority in config defaults to 3 (lowest priority).
"""
from __future__ import annotations

import base64
from pathlib import Path
from typing import AsyncGenerator, Optional, Tuple

import aiohttp

from .base import FileHostAdapter
from ..config import settings

API_BASE = "https://pixeldrain.com/api"


class PixeldrainAdapter(FileHostAdapter):
    name = "pixeldrain"

    def __init__(self) -> None:
        self._api_key = settings.pixeldrain_api_key

    def _auth(self) -> aiohttp.BasicAuth:
        if not self._api_key:
            raise RuntimeError("PIXELDRAIN_API_KEY is not configured")
        # username is intentionally empty; key goes in password
        return aiohttp.BasicAuth(login="", password=self._api_key)

    async def upload(self, path: Path) -> Tuple[str, str]:
        auth = self._auth()
        # Use PUT /file/{name} — raw body, no multipart overhead
        async with aiohttp.ClientSession() as session:
            with open(path, "rb") as fh:
                async with session.put(
                    f"{API_BASE}/file/{path.name}",
                    data=fh,
                    auth=auth,
                    headers={"Content-Type": "application/octet-stream"},
                ) as resp:
                    if resp.status not in (200, 201):
                        text = await resp.text()
                        raise RuntimeError(
                            f"Pixeldrain upload failed: {resp.status} {text}"
                        )
                    body = await resp.json()

        file_id = body["id"]
        url = f"https://pixeldrain.com/api/file/{file_id}"
        return file_id, url

    async def download_range(
        self,
        file_id: str,
        url: str,
        start: int,
        end: Optional[int],
    ) -> AsyncGenerator[bytes, None]:
        range_header = f"bytes={start}-" if end is None else f"bytes={start}-{end}"
        download_url = f"{API_BASE}/file/{file_id}"
        # sock_read=30 ensures a stalled connection raises ServerTimeoutError
        # quickly enough for the proxy to fail over to another host, rather than
        # hanging at Pixeldrain's free-tier rate limit for minutes.
        timeout = aiohttp.ClientTimeout(total=600, sock_connect=10, sock_read=30)
        async with aiohttp.ClientSession() as session:
            async with session.get(
                download_url,
                headers={"Range": range_header},
                auth=self._auth(),
                allow_redirects=True,
                timeout=timeout,
            ) as resp:
                if resp.status not in (200, 206):
                    body = await resp.json(content_type=None)
                    raise RuntimeError(
                        f"Pixeldrain range request failed: {resp.status} "
                        f"{body.get('value', '')}"
                    )
                async for chunk in resp.content.iter_chunked(65536):
                    yield chunk

    async def healthy(self) -> bool:
        if not self._api_key:
            return False
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{API_BASE}/user",
                    auth=self._auth(),
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    return resp.status == 200
        except Exception:
            return False
