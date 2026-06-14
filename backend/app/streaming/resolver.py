"""
Timestamp → chunk resolver.

Given an absolute playback timestamp (seconds), returns:
  - which chunk index covers it
  - the timestamp relative to that chunk's start (for MSE currentTime)
  - the approximate byte offset within the chunk (for HTTP Range hints)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from ..models import Chunk


@dataclass
class ResolvedPosition:
    chunk_index: int
    chunk_start_sec: float
    chunk_end_sec: float
    offset_sec: float          # seconds from chunk start
    approx_byte_offset: int    # estimated byte offset within chunk


def resolve(timestamp: float, chunks: List[Chunk]) -> Optional[ResolvedPosition]:
    """
    Find the chunk covering *timestamp* and compute the intra-chunk offset.
    Returns None if timestamp is out of range.
    """
    if not chunks:
        return None

    for chunk in sorted(chunks, key=lambda c: c.index):
        if chunk.start_sec <= timestamp <= chunk.end_sec:
            chunk_duration = chunk.end_sec - chunk.start_sec
            offset_sec = timestamp - chunk.start_sec
            frac = (offset_sec / chunk_duration) if chunk_duration > 0 else 0.0
            byte_offset = int(chunk.byte_size * frac)
            return ResolvedPosition(
                chunk_index=chunk.index,
                chunk_start_sec=chunk.start_sec,
                chunk_end_sec=chunk.end_sec,
                offset_sec=offset_sec,
                approx_byte_offset=byte_offset,
            )

    # Clamp to last chunk if timestamp is at/past end
    last = max(chunks, key=lambda c: c.index)
    if timestamp >= last.start_sec:
        return ResolvedPosition(
            chunk_index=last.index,
            chunk_start_sec=last.start_sec,
            chunk_end_sec=last.end_sec,
            offset_sec=max(0.0, timestamp - last.start_sec),
            approx_byte_offset=0,
        )

    return None
