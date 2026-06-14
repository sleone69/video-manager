"""FileDitch file-host adapter.

Free, no-auth, PERMANENT uploads.

Upload:   POST https://new.fileditch.com/upload.php?filename=<name>  (raw body)
          -> {"success": true, "url": "https://fileditchfiles.me/<path>", ...}
          NOTE: the returned `url` is an HTML *viewer* page, not the raw file.

Download: The viewer page (fetched with a browser User-Agent) embeds a signed,
          time-limited direct link on a separate CDN host, e.g.
            https://<cdn>/<same-path>?md5=...&expires=<unixts>
          We scrape that link, cache it until it expires, and Range-GET it.
          IMPORTANT: the download host returns 502 to non-browser user agents, so
          a browser UA is sent on every request. The signed link supports Range
          (206) and returns application/octet-stream.

No API key / account. new.fileditch.com retains files indefinitely (storage
permitting). Max file size 100 GB.
"""
from __future__ import annotations

import html as _html
import re
import time
from pathlib import Path
from typing import AsyncGenerator, Dict, Optional, Tuple
from urllib.parse import urlsplit

import aiohttp

from .base import FileHostAdapter
from ..config import settings

_UPLOAD_URL = "https://new.fileditch.com/upload.php"
# The download host 502s requests without a browser User-Agent.
_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
_URL_RE = re.compile(r"https?://[^\s\"'<>]+")


def _parse_expires(url: str) -> Optional[float]:
    """Read the `expires=<unix-ts>` param from a signed CDN link, if present."""
    m = re.search(r"[?&]expires=(\d+)", url)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


class FileDitchAdapter(FileHostAdapter):
    name = "fileditch"

    # viewer_url -> (direct_url, valid_until_epoch). Shared across instances so
    # rapid range requests for the same file reuse one scrape.
    _link_cache: Dict[str, Tuple[str, float]] = {}

    def __init__(self) -> None:
        self._enabled = settings.fileditch_enabled

    # ── Upload ───────────────────────────────────────────────────────────────
    async def upload(self, path: Path) -> Tuple[str, str]:
        if not self._enabled:
            raise NotImplementedError("FileDitch disabled (set FILEDITCH_ENABLED=1)")
        timeout = aiohttp.ClientTimeout(total=None, sock_connect=15, sock_read=300)
        async with aiohttp.ClientSession(timeout=timeout, headers={"User-Agent": _UA}) as session:
            with open(path, "rb") as fh:
                async with session.post(
                    _UPLOAD_URL,
                    params={"filename": path.name},
                    data=fh,
                    headers={"Content-Type": "application/octet-stream"},
                ) as resp:
                    resp.raise_for_status()
                    body = await resp.json(content_type=None)
        if not body.get("success") or not body.get("url"):
            raise RuntimeError(f"FileDitch upload failed: {body}")
        viewer_url = body["url"]
        # FileDitch has no opaque file id; store the filename for reference.
        # Downloads operate on the viewer url.
        file_id = body.get("filename") or path.name
        return file_id, viewer_url

    # ── Direct-link resolution ────────────────────────────────────────────────
    @staticmethod
    def _extract_direct(page: str, viewer_url: str) -> Optional[str]:
        """Find the signed CDN link for this file inside the viewer HTML."""
        fname = urlsplit(viewer_url).path.rsplit("/", 1)[-1]
        for raw in _URL_RE.findall(page):
            url = _html.unescape(raw)
            if fname in url and "fileditch" not in urlsplit(url).netloc:
                return url
        return None

    async def _resolve_direct(self, viewer_url: str, session: aiohttp.ClientSession) -> str:
        cached = FileDitchAdapter._link_cache.get(viewer_url)
        if cached and time.time() < cached[1]:
            return cached[0]
        async with session.get(viewer_url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            if resp.status != 200:
                raise RuntimeError(f"FileDitch viewer page failed: {resp.status} for {viewer_url}")
            page = await resp.text()
        direct = self._extract_direct(page, viewer_url)
        if not direct:
            raise RuntimeError(f"FileDitch: no direct link on viewer page {viewer_url}")
        expires = _parse_expires(direct)
        valid_until = (expires - 60) if expires else (time.time() + 300)
        FileDitchAdapter._link_cache[viewer_url] = (direct, valid_until)
        return direct

    # ── Download ───────────────────────────────────────────────────────────────
    async def download_range(
        self,
        file_id: str,
        url: str,
        start: int,
        end: Optional[int],
    ) -> AsyncGenerator[bytes, None]:
        if not self._enabled:
            raise NotImplementedError("FileDitch disabled")
        if not url:
            raise RuntimeError("FileDitch download requires the stored url")
        range_header = f"bytes={start}-" if end is None else f"bytes={start}-{end}"
        timeout = aiohttp.ClientTimeout(total=600, sock_connect=10, sock_read=30)
        async with aiohttp.ClientSession(headers={"User-Agent": _UA}) as session:
            for attempt in range(2):
                direct = await self._resolve_direct(url, session)
                async with session.get(
                    direct,
                    headers={"Range": range_header},
                    allow_redirects=True,
                    timeout=timeout,
                ) as resp:
                    if resp.status not in (200, 206):
                        # Signed link may have expired — drop cache and re-resolve once.
                        FileDitchAdapter._link_cache.pop(url, None)
                        if attempt == 0:
                            continue
                        raise RuntimeError(
                            f"FileDitch range request failed: {resp.status} for {direct}"
                        )
                    async for chunk in resp.content.iter_chunked(65536):
                        yield chunk
                    return

    async def healthy(self) -> bool:
        if not self._enabled:
            return False
        try:
            async with aiohttp.ClientSession(headers={"User-Agent": _UA}) as session:
                async with session.head(
                    "https://new.fileditch.com/",
                    timeout=aiohttp.ClientTimeout(total=5),
                    allow_redirects=True,
                ) as resp:
                    return resp.status < 500
        except Exception:
            return False
