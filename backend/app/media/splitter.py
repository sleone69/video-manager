"""Split a video file into parts ≤ a given byte limit (for Streamtape).

Unlike the fMP4 chunker, these parts are regular MP4 files (not fragmented)
because Streamtape serves them through its own player and we need the entire
file to be a valid standalone video.

Strategy
--------
• Use ffprobe keyframe timestamps to find cut points that keep each part
  under the byte limit.
• Cut with ``ffmpeg -c copy`` (lossless, no re-encode).
• The output is standard (non-fragmented) MP4 with ``-movflags +faststart``
  so the moov atom is at the front for HTTP streaming.
"""
from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from .probe import VideoInfo


@dataclass
class PartResult:
    index: int
    path: Path
    start_sec: float
    end_sec: float
    byte_size: int
    filename: str


async def split_video(
    source: Path,
    output_dir: Path,
    video_info: VideoInfo,
    part_size_bytes: int,
) -> List[PartResult]:
    """
    Split *source* into ≤part_size_bytes regular MP4 parts.
    Returns a list of PartResult (one per part) in order.
    """
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg not found in PATH")

    output_dir.mkdir(parents=True, exist_ok=True)
    boundaries = _compute_part_boundaries(video_info, part_size_bytes)

    results: List[PartResult] = []
    for i, (start, end) in enumerate(boundaries):
        out_path = output_dir / f"part_{i:04d}.mp4"
        await _extract_part(source, out_path, start, end)
        byte_size = out_path.stat().st_size
        results.append(
            PartResult(
                index=i,
                path=out_path,
                start_sec=start,
                end_sec=end if end is not None else video_info.duration_sec,
                byte_size=byte_size,
                filename=out_path.name,
            )
        )
    return results


def _compute_part_boundaries(info: VideoInfo, part_size_bytes: int) -> List[tuple]:
    """Return (start_sec, end_sec|None) pairs."""
    if not info.keyframe_times or info.duration_sec == 0:
        return [(0.0, None)]

    bytes_per_sec = info.size_bytes / info.duration_sec
    boundaries: List[tuple] = []
    segment_start = 0.0
    accumulated = 0.0
    prev_kf = 0.0

    for kf in sorted(info.keyframe_times):
        if kf <= segment_start:
            prev_kf = kf
            continue
        accumulated += (kf - prev_kf) * bytes_per_sec
        prev_kf = kf
        if accumulated >= part_size_bytes:
            boundaries.append((segment_start, kf))
            segment_start = kf
            prev_kf = kf
            accumulated = 0.0

    boundaries.append((segment_start, None))
    return boundaries


async def _extract_part(
    source: Path,
    output: Path,
    start: float,
    end: Optional[float],
) -> None:
    cmd = ["ffmpeg", "-y", "-ss", str(start)]
    if end is not None:
        cmd += ["-to", str(end)]
    cmd += [
        "-i", str(source),
        "-c", "copy",
        "-movflags", "+faststart",
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
            f"ffmpeg part split failed for segment {start}-{end}:\n"
            + stderr.decode(errors="replace")[-2000:]
        )
