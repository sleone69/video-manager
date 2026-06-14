"""
Range-aware streaming proxy with transparent source failover.

GET /api/stream/{video_id}/manifest   → StreamManifest JSON
GET /api/stream/{video_id}/chunk/{i}  → proxied bytes (with HTTP Range support)

Failover
--------
The chunk's locations are tried in stream_host_priority order.
If one host fails mid-stream the proxy closes that connection, opens
the next host, and re-sends the same Range header, continuing from the
same byte position. The browser's MSE implementation sees continuous
bytes and continues buffering.

A 502 Bad Gateway is returned only when ALL locations for a chunk fail.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from ..hosts.registry import stream_adapters_for_chunk
from ..models import StreamChunk, StreamManifest
from ..storage import load as load_manifest
from ..config import settings

log = logging.getLogger(__name__)
router = APIRouter(prefix="/stream", tags=["stream"])


# ── Manifest endpoint ─────────────────────────────────────────────────────────

@router.get("/{video_id}/manifest", response_model=StreamManifest)
async def get_stream_manifest(video_id: str):
    manifest = load_manifest(video_id)
    if not manifest:
        raise HTTPException(status_code=404, detail="Video not found")

    priority = settings.stream_host_priority
    stream_chunks = []
    for chunk in sorted(manifest.chunks, key=lambda c: c.index):
        ok_hosts = [
            loc.host for loc in chunk.locations if loc.status == "ok"
        ]
        # Sort by priority
        sorted_hosts = sorted(
            ok_hosts,
            key=lambda h: priority.index(h) if h in priority else len(priority),
        )
        stream_chunks.append(
            StreamChunk(
                index=chunk.index,
                start_sec=chunk.start_sec,
                end_sec=chunk.end_sec,
                byte_size=chunk.byte_size,
                hosts=sorted_hosts,
            )
        )

    return StreamManifest(
        video_id=manifest.video_id,
        name=manifest.name,
        description=manifest.description,
        duration_sec=manifest.duration_sec,
        resolution=manifest.resolution,
        mse_codec=manifest.resolution.mse_codec if manifest.resolution else "avc1.640028, mp4a.40.2",
        thumbnail=manifest.thumbnail,
        star_ids=manifest.star_ids,
        chunks=stream_chunks,
        streamtape_parts=manifest.streamtape_parts,
    )


# ── Chunk proxy endpoint ──────────────────────────────────────────────────────

@router.get("/{video_id}/chunk/{chunk_index}")
async def stream_chunk(
    video_id: str,
    chunk_index: int,
    request: Request,
):
    manifest = load_manifest(video_id)
    if not manifest:
        raise HTTPException(status_code=404, detail="Video not found")

    # Find the requested chunk
    chunk = next(
        (c for c in manifest.chunks if c.index == chunk_index), None
    )
    if not chunk:
        raise HTTPException(status_code=404, detail="Chunk not found")

    # Parse Range header
    range_header = request.headers.get("range")
    start_byte, end_byte = _parse_range(range_header, chunk.byte_size)

    # Build ordered list of (adapter, location) to try
    ok_locations = {loc.host: loc for loc in chunk.locations if loc.status == "ok"}
    adapters = stream_adapters_for_chunk(list(ok_locations.keys()))

    if not adapters:
        raise HTTPException(status_code=502, detail="No available hosts for this chunk")

    # Try each host in order
    for adapter in adapters:
        loc = ok_locations[adapter.name]
        try:
            gen = adapter.download_range(loc.file_id, loc.url, start_byte, end_byte)
            content_length = (end_byte - start_byte + 1) if end_byte is not None else (chunk.byte_size - start_byte)
            status_code = 206 if range_header else 200
            headers = {
                "Content-Type": "video/mp4",
                "Accept-Ranges": "bytes",
                "Content-Length": str(content_length),
                "X-Source-Host": adapter.name,
            }
            if range_header and end_byte is not None:
                headers["Content-Range"] = (
                    f"bytes {start_byte}-{end_byte}/{chunk.byte_size}"
                )

            return StreamingResponse(
                _failover_stream(gen, adapter, start_byte, end_byte, content_length, adapters, ok_locations),
                status_code=status_code,
                media_type="video/mp4",
                headers=headers,
            )
        except NotImplementedError:
            continue
        except Exception as exc:
            log.warning(
                "Host %s failed before stream started for chunk %d: %s",
                adapter.name, chunk_index, exc,
            )
            continue

    raise HTTPException(status_code=502, detail="All hosts failed for this chunk")


async def _failover_stream(gen, current_adapter, start, end, expected_bytes, all_adapters, loc_map):
    """
    Yield bytes from gen; on failure OR premature EOF transparently switch to
    the next adapter from the same byte position.
    """
    delivered = 0
    remaining_adapters = list(all_adapters)
    if current_adapter in remaining_adapters:
        remaining_adapters.remove(current_adapter)

    active_gen = gen
    while True:
        try:
            async for chunk_bytes in active_gen:
                delivered += len(chunk_bytes)
                yield chunk_bytes

            # Check for premature EOF: host closed connection before sending all bytes.
            # This happens when Pixeldrain rate-limits and then drops the connection.
            if delivered < expected_bytes:
                raise RuntimeError(
                    f"{current_adapter.name} short read: got {delivered}/{expected_bytes} bytes"
                )
            return  # done
        except Exception as exc:
            log.warning(
                "Host %s failed after %d/%d bytes: %s",
                current_adapter.name, delivered, expected_bytes, exc,
            )
            # Try next adapter starting from where we left off
            resume_start = start + delivered
            resume_expected = expected_bytes - delivered
            switched = False
            for next_adapter in remaining_adapters:
                if next_adapter.name not in loc_map:
                    continue
                next_loc = loc_map[next_adapter.name]
                try:
                    log.info("Failing over to %s at byte %d", next_adapter.name, resume_start)
                    active_gen = next_adapter.download_range(
                        next_loc.file_id, next_loc.url, resume_start, end
                    )
                    current_adapter = next_adapter
                    expected_bytes = resume_expected
                    start = resume_start
                    delivered = 0
                    remaining_adapters.remove(next_adapter)
                    switched = True
                    break
                except Exception:
                    continue
            if not switched:
                log.error("All hosts exhausted, %d/%d bytes delivered", start + delivered - start, expected_bytes)
                return


def _parse_range(header: Optional[str], total: int):
    """Parse 'Range: bytes=start-end' → (start, end|None)."""
    if not header or not header.startswith("bytes="):
        return 0, None
    try:
        rng = header[6:]
        parts = rng.split("-")
        start = int(parts[0]) if parts[0] else 0
        end = int(parts[1]) if len(parts) > 1 and parts[1] else None
        return start, end
    except ValueError:
        return 0, None
