"""Cyberfile file-host adapter.

API base:  https://api.cyberfile.me/api/v2
Auth:      POST /authorize → access_token + account_id (valid 1 hour idle)

⚠ Cyberfile does NOT support chunked upload; max 1 GB per file.
  Since our chunks are ≤500 MB this is fine, but the token must be
  refreshed when it expires.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import AsyncGenerator, Optional, Tuple

import aiohttp

from .base import FileHostAdapter
from ..config import settings


class CyberfileAdapter(FileHostAdapter):
    name = "cyberfile"

    def __init__(self) -> None:
        self._base = settings.cyberfile_base_url.rstrip("/")
        self._username = settings.cyberfile_username
        self._password = settings.cyberfile_password
        self._folder_id = settings.cyberfile_folder_id
        # Cached session credentials
        self._access_token: Optional[str] = None
        self._account_id: Optional[str] = None
        self._token_ts: float = 0.0
        self._TOKEN_TTL = 3000  # 50 min < 1 h idle expiry

    async def _ensure_token(self) -> Tuple[str, str]:
        if (
            self._access_token
            and self._account_id
            and (time.monotonic() - self._token_ts) < self._TOKEN_TTL
        ):
            return self._access_token, self._account_id

        if not self._username or not self._password:
            raise RuntimeError("CYBERFILE_USERNAME / CYBERFILE_PASSWORD not configured")

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self._base}/authorize",
                data={"username": self._username, "password": self._password},
            ) as resp:
                resp.raise_for_status()
                body = await resp.json()

        if body.get("_status") != "success":
            raise RuntimeError(f"Cyberfile auth failed: {body}")

        self._access_token = body["data"]["access_token"]
        self._account_id = body["data"]["account_id"]
        self._token_ts = time.monotonic()
        return self._access_token, self._account_id

    async def upload(self, path: Path) -> Tuple[str, str]:
        token, account_id = await self._ensure_token()

        data = aiohttp.FormData()
        data.add_field("access_token", token)
        data.add_field("account_id", account_id)
        if self._folder_id:
            data.add_field("folder_id", self._folder_id)
        data.add_field(
            "upload_file",
            open(path, "rb"),
            filename=path.name,
            content_type="application/octet-stream",
        )

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self._base}/file/upload", data=data
            ) as resp:
                resp.raise_for_status()
                body = await resp.json()

        if body.get("_status") != "success":
            raise RuntimeError(f"Cyberfile upload failed: {body}")

        file_info = body["data"][0]
        file_id = file_info["file_id"]
        url = file_info["url"]
        return file_id, url

    async def _get_download_url(self, file_id: str) -> str:
        token, account_id = await self._ensure_token()
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self._base}/file/download",
                data={
                    "access_token": token,
                    "account_id": account_id,
                    "file_id": file_id,
                },
            ) as resp:
                resp.raise_for_status()
                body = await resp.json()
        if body.get("_status") != "success":
            raise RuntimeError(f"Cyberfile download URL failed: {body}")
        return body["data"]["download_url"]

    async def download_range(
        self,
        file_id: str,
        url: str,
        start: int,
        end: Optional[int],
    ) -> AsyncGenerator[bytes, None]:
        dl_url = await self._get_download_url(file_id)
        range_header = f"bytes={start}-" if end is None else f"bytes={start}-{end}"
        async with aiohttp.ClientSession() as session:
            async with session.get(
                dl_url,
                headers={"Range": range_header},
                allow_redirects=True,
            ) as resp:
                if resp.status not in (200, 206):
                    raise RuntimeError(
                        f"Cyberfile range request failed: {resp.status}"
                    )
                async for chunk in resp.content.iter_chunked(65536):
                    yield chunk

    async def healthy(self) -> bool:
        if not self._username or not self._password:
            return False
        try:
            await self._ensure_token()
            return True
        except Exception:
            return False
