"""Gofile file-host adapter.

API base:  https://upload.gofile.io  (upload)
           https://api.gofile.io     (management)
Auth:      Authorization: Bearer <api_key>
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import AsyncGenerator, Optional, Tuple

import aiohttp

from .base import FileHostAdapter
from ..config import settings

UPLOAD_URL = "https://upload.gofile.io/uploadfile"
API_BASE = "https://api.gofile.io"


class GofileAdapter(FileHostAdapter):
    name = "gofile"

    def __init__(self) -> None:
        # Accept GOFILE_TOKEN or legacy GOFILE_API_KEY
        self._token = settings._gofile_token
        self._account_id = settings.gofile_account_id
        # GOFILE_FOLDER_ID takes priority; fall back to GOFILE_ACCOUNT_ID root folder
        self._folder_id = settings.gofile_folder_id
        # Cached root folder UUID (fetched once from /accounts/{id})
        self._root_folder: Optional[str] = None

    def _headers(self) -> dict:
        if not self._token:
            raise RuntimeError(
                "Gofile token not configured. Set GOFILE_TOKEN (or GOFILE_API_KEY) in .env"
            )
        return {"Authorization": f"Bearer {self._token}"}

    async def _get_folder_id(self) -> Optional[str]:
        """Return the configured folder ID, or resolve the account root folder."""
        if self._folder_id:
            return self._folder_id
        if self._root_folder:
            return self._root_folder
        if not self._account_id:
            return None  # upload without folderId — gofile will use a guest folder
        # Fetch root folder UUID from account info
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{API_BASE}/accounts/{self._account_id}",
                    headers=self._headers(),
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    body = await resp.json()
                    if body.get("status") == "ok":
                        self._root_folder = body["data"].get("rootFolder")
                        return self._root_folder
        except Exception:
            pass
        return None

    async def upload(self, path: Path) -> Tuple[str, str]:
        folder_id = await self._get_folder_id()

        data = aiohttp.FormData()
        data.add_field(
            "file",
            open(path, "rb"),  # noqa: WPS515 – closed by aiohttp after send
            filename=path.name,
        )
        if folder_id:
            data.add_field("folderId", folder_id)

        async with aiohttp.ClientSession() as session:
            async with session.post(
                UPLOAD_URL, data=data, headers=self._headers()
            ) as resp:
                resp.raise_for_status()
                body = await resp.json()

        if body.get("status") != "ok":
            raise RuntimeError(f"Gofile upload failed: {body}")

        file_data = body["data"]
        file_id = file_data["id"]

        # Create a direct link so the proxy can byte-range it without the
        # HTML download page in the way.
        direct_url = await self._create_direct_link(file_id)
        return file_id, direct_url

    async def _create_direct_link(self, content_id: str) -> str:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{API_BASE}/contents/{content_id}/directlinks",
                json={},
                headers=self._headers(),
            ) as resp:
                if resp.status == 200 or resp.status == 201:
                    body = await resp.json()
                    if body.get("status") == "ok":
                        return body["data"]["link"]
        # Fallback: return the standard download URL (may require premium for
        # range requests, but at least works for full downloads)
        return f"https://gofile.io/d/{content_id}"

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
            ) as resp:
                if resp.status not in (200, 206):
                    raise RuntimeError(
                        f"Gofile range request failed: {resp.status} for {url}"
                    )
                async for chunk in resp.content.iter_chunked(65536):
                    yield chunk

    async def healthy(self) -> bool:
        if not self._token:
            return False
        try:
            async with aiohttp.ClientSession() as session:
                if self._account_id:
                    url = f"{API_BASE}/accounts/{self._account_id}"
                else:
                    # No account ID — just try a lightweight call
                    url = f"{API_BASE}/accounts/getid"
                async with session.get(
                    url,
                    headers=self._headers(),
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    body = await resp.json()
                    return body.get("status") == "ok"
        except Exception:
            return False
