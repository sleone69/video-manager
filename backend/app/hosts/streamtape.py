"""Streamtape file-host adapter.

API base: https://api.streamtape.com
Auth:     ?login={login}&key={key} on every request.

Unlike other hosts, Streamtape is NOT used for fMP4 chunks.
Instead full video parts (≤8 GB each) are uploaded here and streamed via
the Streamtape proxy router which stitches them into a single seekable stream.

Upload flow
-----------
1. GET /file/ul?login=…&key=…  →  {"result": {"url": "...", "valid_until": "…"}}
2. POST the file (multipart/form-data, field name "file1") to that URL
3. Response: {"result": {"id": "…", "name": "…", …}} – we store "id" as file_id

Download flow (for proxy)
--------------------------
1. GET /file/dlticket?file=…&login=…&key=…  →  {"result": {"ticket": "…", "wait_time": N}}
2. Sleep wait_time seconds (usually 0 for API users)
3. GET /file/dl?file=…&ticket=…             →  {"result": {"url": "…"}}
4. Range-GET the returned URL
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import AsyncGenerator, Dict, Optional, Tuple

import aiohttp

from .base import FileHostAdapter
from ..config import settings

log = logging.getLogger(__name__)

_BASE = "https://api.streamtape.com"

# Cache download URLs per file_id so we don't re-generate tickets on every
# range request within the same proxy call.
_dl_url_cache: Dict[str, str] = {}


class StreamtapeAdapter(FileHostAdapter):
    name = "streamtape"
    chunk_upload = False  # uploads whole-video parts, not fMP4 chunks

    def __init__(self) -> None:
        self._login = settings.streamtape_login
        self._key = settings.streamtape_key
        self._folder_id = settings.streamtape_folder_id

    def _auth(self) -> dict:
        if not self._login or not self._key:
            raise RuntimeError(
                "Streamtape not configured. Set STREAMTAPE_LOGIN and STREAMTAPE_KEY in .env"
            )
        return {"login": self._login, "key": self._key}

    async def upload(self, path: Path) -> Tuple[str, str]:
        """Upload a file, return (file_id, watch_url)."""
        params = self._auth()
        if self._folder_id:
            params["folder"] = self._folder_id

        async with aiohttp.ClientSession() as session:
            # Step 1: get upload URL
            async with session.get(f"{_BASE}/file/ul", params=params) as resp:
                resp.raise_for_status()
                body = await resp.json()
            if body.get("status") != 200:
                raise RuntimeError(f"Streamtape upload URL failed: {body}")
            upload_url = body["result"]["url"]

            # Step 2: upload file
            data = aiohttp.FormData()
            data.add_field(
                "file1",
                open(path, "rb"),
                filename=path.name,
                content_type="application/octet-stream",
            )
            async with session.post(upload_url, data=data) as resp:
                resp.raise_for_status()
                # Streamtape's upload CDN returns JSON with Content-Type
                # application/octet-stream — pass content_type=None to accept it.
                body = await resp.json(content_type=None)

        if body.get("status") != 200:
            raise RuntimeError(f"Streamtape upload POST failed: {body}")

        file_id = body["result"]["id"]
        watch_url = f"https://streamtape.com/v/{file_id}/{path.name}"
        return file_id, watch_url

    async def _get_download_url(self, file_id: str) -> str:
        """Get a one-time direct download URL via ticket."""
        if file_id in _dl_url_cache:
            return _dl_url_cache[file_id]

        params = {**self._auth(), "file": file_id}
        async with aiohttp.ClientSession() as session:
            # Ticket
            async with session.get(f"{_BASE}/file/dlticket", params=params) as resp:
                resp.raise_for_status()
                body = await resp.json()
            if body.get("status") != 200:
                raise RuntimeError(f"Streamtape dlticket failed: {body}")
            ticket = body["result"]["ticket"]
            wait = int(body["result"].get("wait_time", 0))
            if wait > 0:
                await asyncio.sleep(wait)

            # Download link
            async with session.get(
                f"{_BASE}/file/dl",
                params={"file": file_id, "ticket": ticket},
            ) as resp:
                resp.raise_for_status()
                body = await resp.json()

        if body.get("status") != 200:
            raise RuntimeError(f"Streamtape dl failed: {body}")

        dl_url = body["result"]["url"]
        # Cache briefly — tickets are single-use but the URL they return is
        # usually reusable for a short window.
        _dl_url_cache[file_id] = dl_url
        return dl_url

    def invalidate_cache(self, file_id: str) -> None:
        _dl_url_cache.pop(file_id, None)

    async def download_range(
        self,
        file_id: str,
        url: str,
        start: int,
        end: Optional[int],
    ) -> AsyncGenerator[bytes, None]:
        range_header = f"bytes={start}-" if end is None else f"bytes={start}-{end}"
        retries = 2
        for attempt in range(retries):
            try:
                dl_url = await self._get_download_url(file_id)
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        dl_url,
                        headers={"Range": range_header},
                        allow_redirects=True,
                    ) as resp:
                        if resp.status not in (200, 206):
                            # Ticket URL may have expired — invalidate and retry
                            self.invalidate_cache(file_id)
                            if attempt < retries - 1:
                                continue
                            raise RuntimeError(
                                f"Streamtape range request failed: {resp.status}"
                            )
                        async for chunk in resp.content.iter_chunked(65536):
                            yield chunk
                return
            except RuntimeError:
                if attempt < retries - 1:
                    self.invalidate_cache(file_id)
                else:
                    raise

    async def healthy(self) -> bool:
        if not self._login or not self._key:
            return False
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{_BASE}/account/info",
                    params=self._auth(),
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    body = await resp.json()
                    return body.get("status") == 200
        except Exception:
            return False
