"""Read/write per-video JSON manifests (source of truth)."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import List, Optional

from ..config import settings
from ..models import Manifest


def _path(video_id: str) -> Path:
    return settings.manifests_dir / f"{video_id}.json"


def save(manifest: Manifest) -> None:
    # Atomic write (temp file + os.replace) so the streaming proxy and the
    # refresher never observe a half-written manifest.
    p = _path(manifest.video_id)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    os.replace(tmp, p)


def load(video_id: str) -> Optional[Manifest]:
    p = _path(video_id)
    if not p.exists():
        return None
    return Manifest.model_validate_json(p.read_text(encoding="utf-8"))


def delete(video_id: str) -> bool:
    p = _path(video_id)
    if p.exists():
        p.unlink()
        return True
    return False


def all_ids() -> List[str]:
    return [p.stem for p in settings.manifests_dir.glob("*.json")]
