"""
Lossless video chunker using ffmpeg.

Strategy
--------
* Uses ``-c copy`` (stream-copy) — truly lossless, no re-encode.
* Splits at keyframe boundaries closest to 500 MB intervals so each chunk
  is independently decodable as a fragmented MP4 (fMP4).
* Outputs fragmented MP4 (``-movflags frag_keyframe+empty_moov+faststart``)
  for seamless MSE/SourceBuffer appending in the browser.

Chunk boundary calculation
--------------------------
Given a list of keyframe timestamps and the total file size we estimate
a byte-size per second and pick the keyframe just before each 500 MB boundary.
This keeps chunks ≤ ~500 MB while preserving seekability.
"""
from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from .probe import VideoInfo
from ..config import settings

FRAG_FLAGS = "frag_keyframe+empty_moov+faststart+default_base_moof"


@dataclass
class ChunkResult:
    index: int
    path: Path
    start_sec: float
    end_sec: float
    byte_size: int
    filename: str


async def chunk_video(
    source: Path,
    output_dir: Path,
    video_info: VideoInfo,
) -> List[ChunkResult]:
    """
    Split *source* into ≤500 MB lossless fMP4 chunks.
    Returns list of ChunkResult (one per chunk) in order.
    """
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg not found in PATH")

    output_dir.mkdir(parents=True, exist_ok=True)

    boundaries = _compute_boundaries(video_info)

    results: List[ChunkResult] = []
    for i, (start, end) in enumerate(boundaries):
        out_path = output_dir / f"chunk_{i:04d}.mp4"
        await _extract_chunk(source, out_path, start, end)
        byte_size = out_path.stat().st_size
        results.append(
            ChunkResult(
                index=i,
                path=out_path,
                start_sec=start,
                end_sec=end if end is not None else video_info.duration_sec,
                byte_size=byte_size,
                filename=out_path.name,
            )
        )

    return results


def _compute_boundaries(
    info: VideoInfo,
) -> List[tuple]:
    """
    Return list of (start_sec, end_sec | None) pairs.
    end_sec=None means "to end of file".
    """
    if not info.keyframe_times or info.duration_sec == 0:
        return [(0.0, None)]

    target_bytes = settings.chunk_size_bytes
    bytes_per_sec = info.size_bytes / info.duration_sec

    boundaries: List[tuple] = []
    segment_start = 0.0
    accumulated = 0.0
    prev_kf = 0.0

    for kf in sorted(info.keyframe_times):
        if kf <= segment_start:
            prev_kf = kf
            continue
        # accumulate incremental bytes since the previous keyframe
        accumulated += (kf - prev_kf) * bytes_per_sec
        prev_kf = kf
        if accumulated >= target_bytes:
            boundaries.append((segment_start, kf))
            segment_start = kf
            prev_kf = kf
            accumulated = 0.0

    # Final segment
    boundaries.append((segment_start, None))
    return boundaries


async def _extract_chunk(
    source: Path,
    output: Path,
    start: float,
    end: Optional[float],
) -> None:
    cmd = [
        "ffmpeg",
        "-y",
        "-ss", str(start),
    ]
    if end is not None:
        cmd += ["-to", str(end)]
    cmd += [
        "-i", str(source),
        "-c", "copy",           # lossless stream copy
        "-movflags", FRAG_FLAGS,
        "-avoid_negative_ts", "make_zero",
        str(output),
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg chunking failed for segment {start}-{end}:\n"
            + stderr.decode(errors="replace")[-2000:]
        )
