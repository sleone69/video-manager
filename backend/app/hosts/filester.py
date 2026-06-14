"""Filester file-host adapter.

API base:  https://u1.filester.me
Auth:      Authorization: Bearer <api_key>

⚠ WARNING: Filester auto-deletes files after 45 days without views/downloads.
   A keep-alive background task should periodically touch stored file URLs
   to prevent deletion (TODO: implement in jobs/keepalive.py).
"""
from __future__ import annotations

from pathlib import Path
from typing import AsyncGenerator, Optional, Tuple

import aiohttp

from .base import FileHostAdapter
from ..config import settings


class FilesterAdapter(FileHostAdapter):
    name = "filester"

    # In-memory cache: slug → (cdn_url, expires_at_monotonic)
    _token_cache: dict = {}

    def __init__(self) -> None:
        self._api_key = settings.filester_api_key
        self._base = settings.filester_base_url.rstrip("/")
        self._folder_id = settings.filester_folder_id

    def _headers(self) -> dict:
        if not self._api_key:
            raise RuntimeError("FILESTER_API_KEY is not configured")
        return {"Authorization": f"Bearer {self._api_key}"}

    async def upload(self, path: Path) -> Tuple[str, str]:
        extra_headers = dict(self._headers())
        if self._folder_id:
            extra_headers["X-Folder-ID"] = self._folder_id

        data = aiohttp.FormData()
        data.add_field(
            "file",
            open(path, "rb"),
            filename=path.name,
            content_type="application/octet-stream",
        )

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self._base}/api/v1/upload",
                data=data,
                headers=extra_headers,
            ) as resp:
                resp.raise_for_status()
                body = await resp.json()

        if not body.get("success"):
            raise RuntimeError(f"Filester upload failed: {body}")

        file_id = str(body["file_id"])
        # Construct the download URL from slug or fall back to file_id
        slug = body.get("slug") or file_id
        url = body.get("url") or f"https://filester.me/d/{slug}"
        return file_id, url

    async def _resolve_cdn_url(self, file_id: str, slug: str) -> str:
        """
        Get a short-lived direct CDN URL via the public download token API.
        Flow (discovered from page JS):
          POST /api/public/download {"file_slug": slug}
          → {"download_url": "/d/<token>", ...}
          → CDN URL: https://cache1.filester.me/d/<token>?download=true
        Tokens are valid 30 min (expires_in: 1800); cache to avoid extra requests.
        Falls back to authenticated API on any error.
        """
        import time as _time

        CDN_HOSTS = [
            "https://cache1.filester.me",
            "https://cache6.filester.me",
            "https://cn1.filester.me",
        ]

        # Check cache
        cached = FilesterAdapter._token_cache.get(slug)
        if cached and _time.monotonic() < cached[1]:
            return cached[0]

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "https://filester.me/api/public/download",
                    json={"file_slug": slug},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 200:
                        body = await resp.json(content_type=None)
                        if body.get("success") and body.get("download_url"):
                            path = body["download_url"]
                            cdn_url = f"{CDN_HOSTS[0]}{path}?download=true"
                            expires = body.get("expires_in", 1800)
                            FilesterAdapter._token_cache[slug] = (
                                cdn_url,
                                _time.monotonic() + expires - 60,  # 1-min margin
                            )
                            return cdn_url
        except Exception:
            pass
        # Fallback: authenticated file-info endpoint
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self._base}/api/v1/file/{file_id}",
                    headers=self._headers(),
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 200:
                        body = await resp.json()
                        if body.get("success"):
                            return (
                                body["data"].get("download_url")
                                or body["data"].get("url")
                                or f"https://cache1.filester.me/d/{slug}"
                            )
        except Exception:
            pass
        return f"https://cache1.filester.me/d/{slug}"

    async def download_range(
        self,
        file_id: str,
        url: str,
        start: int,
        end: Optional[int],
    ) -> AsyncGenerator[bytes, None]:
        # Extract the slug from the stored landing-page URL (filester.me/d/<slug>)
        slug = url.rstrip("/").split("/")[-1] if url else file_id
        # Resolve a real CDN URL via the public download token API
        cdn_url = await self._resolve_cdn_url(file_id, slug)
        range_header = f"bytes={start}-" if end is None else f"bytes={start}-{end}"

        async with aiohttp.ClientSession() as session:
            async with session.get(
                cdn_url,
                headers={"Range": range_header},
                allow_redirects=True,
                timeout=aiohttp.ClientTimeout(total=300, sock_connect=10, sock_read=30),
            ) as resp:
                if resp.status not in (200, 206):
                    raise RuntimeError(
                        f"Filester CDN range request failed: {resp.status} for {cdn_url}"
                    )
                async for chunk in resp.content.iter_chunked(65536):
                    yield chunk

    async def healthy(self) -> bool:
        if not self._api_key:
            return False
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self._base}/api/v1/account",
                    headers=self._headers(),
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    body = await resp.json()
                    return bool(body.get("success"))
        except Exception:
            return False
