"""Streamtape streaming proxy.

GET /api/stream/st/{video_id}
    Range-aware proxy that stitches Streamtape parts into one virtual stream.

How it works
------------
The player treats all parts as one continuous byte stream:
    virtual offset 0 … (part0.byte_size - 1)           → part 0
    virtual offset part0.byte_size … (sum[:2] - 1)     → part 1
    …

When the browser sends `Range: bytes=X-Y`, the proxy:
  1. Finds which part contains byte X.
  2. Converts X to a local offset within that part.
  3. Fetches a download ticket for that part.
  4. Proxies a range request on the CDN URL returned by the ticket.

Multiple parts are NOT stitched in a single response — the response covers
only bytes up to the end of the current part (inclusive) and sets
Content-Range accordingly.  The browser's <video> element seamlessly requests
the next range, which lands in the next part, and so on.

Ticket caching
--------------
Download tickets are cached per file_id.  If a CDN request fails with a
non-2xx status we invalidate the cache and retry once (the ticket URL may
have expired in the meantime).
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from ..hosts.streamtape import StreamtapeAdapter
from ..models import StreamtapePart
from ..storage import load as load_manifest

log = logging.getLogger(__name__)
router = APIRouter(prefix="/stream/st", tags=["streamtape"])

_CHUNK_SIZE = 65536  # bytes per yield from the upstream response


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_range(header: Optional[str], total: int):
    """Return (start, end) — end may be None for open-ended Range."""
    if not header:
        return 0, None
    header = header.strip()
    if not header.startswith("bytes="):
        return 0, None
    rng = header[6:]
    if "-" not in rng:
        return 0, None
    lo, hi = rng.split("-", 1)
    start = int(lo) if lo else 0
    end = int(hi) if hi else None
    return start, end


def _part_for_offset(parts: list[StreamtapePart], virtual_offset: int):
    """Return (part, local_offset) for a given virtual byte offset."""
    cumulative = 0
    for part in parts:
        if virtual_offset < cumulative + part.byte_size:
            return part, virtual_offset - cumulative
        cumulative += part.byte_size
    # Offset is at or beyond total — serve the last byte of the last part
    last = parts[-1]
    return last, last.byte_size - 1


def _total_size(parts: list[StreamtapePart]) -> int:
    return sum(p.byte_size for p in parts)


# ── Route ─────────────────────────────────────────────────────────────────────

@router.get("/{video_id}")
async def streamtape_proxy(video_id: str, request: Request):
    manifest = load_manifest(video_id)
    if not manifest:
        raise HTTPException(status_code=404, detail="Video not found")

    parts = sorted(manifest.streamtape_parts, key=lambda p: p.index)
    if not parts:
        raise HTTPException(
            status_code=404,
            detail="This video has no Streamtape parts. Use the standard chunk endpoint.",
        )

    total = _total_size(parts)
    range_header = request.headers.get("range")
    virtual_start, virtual_end_req = _parse_range(range_header, total)

    # Clamp and resolve which part virtual_start falls into
    virtual_start = max(0, min(virtual_start, total - 1))
    part, local_start = _part_for_offset(parts, virtual_start)

    # How many bytes can we serve from this part?
    part_remaining = part.byte_size - local_start
    # If a specific end was requested, honour it only if it fits in this part
    if virtual_end_req is not None:
        virtual_end_req = min(virtual_end_req, total - 1)
        requested_in_part = virtual_end_req - virtual_start
        local_end = local_start + min(requested_in_part, part_remaining - 1)
    else:
        local_end = part.byte_size - 1

    # virtual end = virtual_start + (local_end - local_start)
    virtual_end = virtual_start + (local_end - local_start)

    adapter = StreamtapeAdapter()

    async def _generate():
        async for chunk in adapter.download_range(
            part.file_id, "", local_start, local_end
        ):
            yield chunk

    status_code = 206 if range_header else 200
    headers = {
        "Content-Type": "video/mp4",
        "Accept-Ranges": "bytes",
        "Content-Length": str(local_end - local_start + 1),
        "Content-Range": f"bytes {virtual_start}-{virtual_end}/{total}",
    }
    return StreamingResponse(
        _generate(),
        status_code=status_code,
        headers=headers,
        media_type="video/mp4",
    )
