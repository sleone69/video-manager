"""Host adapter registry.

Builds and caches one instance of every enabled adapter.
Adapters whose credentials are missing are excluded from the upload pool
but their class is still importable.
"""
from __future__ import annotations

from typing import Dict, List

from .base import FileHostAdapter
from .fileditch import FileDitchAdapter
from .gofile import GofileAdapter
from .filester import FilesterAdapter
from .cyberfile import CyberfileAdapter
from .pixeldrain import PixeldrainAdapter
from .turbocr import TurboCRAdapter
from .streamtape import StreamtapeAdapter
from .buzzheavier import BuzzheavierAdapter
from ..config import settings

# All known adapters in their default priority order
_ALL_ADAPTERS: List[FileHostAdapter] = [
    FileDitchAdapter(),      # free, no-auth, permanent – best anchor copy
    GofileAdapter(),
    FilesterAdapter(),
    CyberfileAdapter(),
    PixeldrainAdapter(),
    TurboCRAdapter(),        # stub – always reports healthy()=False
    StreamtapeAdapter(),     # part-upload host (not used for fMP4 chunks)
    BuzzheavierAdapter(),
]

_BY_NAME: Dict[str, FileHostAdapter] = {a.name: a for a in _ALL_ADAPTERS}


def get(name: str) -> FileHostAdapter:
    """Return adapter by name. Raises KeyError if unknown."""
    return _BY_NAME[name]


def upload_adapters() -> List[FileHostAdapter]:
    """
    Return adapters used for fMP4 chunk uploads (chunk_upload=True only).
    Streamtape and Buzzheavier are excluded here; they receive whole-video
    parts via _upload_streamtape_parts() in upload_job.py.
    Order follows settings.stream_host_priority where specified,
    remaining adapters appended at the end.
    """
    ordered: List[FileHostAdapter] = []
    seen = set()
    for name in settings.stream_host_priority:
        if name in _BY_NAME and _BY_NAME[name].chunk_upload:
            ordered.append(_BY_NAME[name])
            seen.add(name)
    for adapter in _ALL_ADAPTERS:
        if adapter.name not in seen and adapter.chunk_upload:
            ordered.append(adapter)
    return ordered


def stream_adapters_for_chunk(host_names: List[str]) -> List[FileHostAdapter]:
    """
    Return adapters for the given hosts in stream_host_priority order.
    Unknown or unconfigured host names are silently skipped.
    """
    priority = settings.stream_host_priority
    sorted_names = sorted(
        host_names,
        key=lambda n: priority.index(n) if n in priority else len(priority),
    )
    return [_BY_NAME[n] for n in sorted_names if n in _BY_NAME]
