"""Expiry-refresher engine.

For each video manifest, two passes per chunk:

1. VERIFY — fetch 1 byte from every chunk location. This (a) detects dead/expired
   links and (b) resets idle-deletion timers on hosts that reap unviewed files,
   acting as a keep-alive. Updates ``last_verified_at`` and ``expires_at``.

2. REPAIR — when a chunk has fewer than ``replica_count`` healthy copies (a link
   died or it was under-replicated), re-download the bytes from a surviving healthy
   copy and re-upload to additional hosts, rewriting the manifest's ChunkLocation
   (file_id / url) in place. The manifest is the backend source of truth, so the
   streaming proxy immediately serves the new URLs.

The manifest is saved atomically (storage.save -> temp + os.replace).
"""
from __future__ import annotations

import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from ..config import settings
from ..hosts import registry
from ..models import ChunkLocation, LocationStatus
from ..storage import all_ids, load, upsert
from ..storage.manifest_store import save as save_manifest
from .policy import estimate_expiry

log = logging.getLogger(__name__)


# ── Low-level host operations (reuse the existing adapters) ─────────────────────

async def _verify_location(loc: ChunkLocation) -> bool:
    """True if a single byte can be fetched. Doubles as a keep-alive touch."""
    try:
        adapter = registry.get(loc.host)
    except KeyError:
        return False
    if not loc.file_id and not loc.url:
        return False
    try:
        agen = adapter.download_range(loc.file_id, loc.url, 0, 0)
    except Exception:
        return False
    found = False
    try:
        async for _ in agen:
            found = True
            break
    except NotImplementedError:
        return False
    except Exception as exc:
        log.debug("verify %s/%s failed: %s", loc.host, loc.file_id, exc)
        return False
    finally:
        try:
            await agen.aclose()
        except Exception:
            pass
    return found


async def _download_chunk(loc: ChunkLocation, dest: Path) -> None:
    adapter = registry.get(loc.host)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("wb") as fh:
        async for data in adapter.download_range(loc.file_id, loc.url, 0, None):
            fh.write(data)


async def _upload_copy(host: str, path: Path) -> Optional[ChunkLocation]:
    try:
        adapter = registry.get(host)
    except KeyError:
        return None
    try:
        file_id, url = await adapter.upload(path)
    except Exception as exc:
        log.warning("re-upload to %s failed: %s", host, exc)
        return None
    now = datetime.utcnow()
    return ChunkLocation(
        host=host, file_id=file_id, url=url, status=LocationStatus.ok,
        uploaded_at=now, last_verified_at=now, expires_at=estimate_expiry(host, now),
    )


# ── Per-video refresh ───────────────────────────────────────────────────────────

async def refresh_video(
    video_id: str,
    *,
    replica_count: Optional[int] = None,
    dry_run: bool = False,
) -> dict:
    replica = replica_count or max(1, settings.replica_count)
    manifest = load(video_id)
    if not manifest:
        return {"video_id": video_id, "error": "not found"}

    now = datetime.utcnow()
    fill_order = [a.name for a in registry.upload_adapters()]  # chunk-capable, priority order
    tmp_root = settings.temp_dir / f"refresh_{video_id}"
    stats = {
        "video_id": video_id, "chunks": len(manifest.chunks),
        "verified": 0, "dead": 0, "repaired": 0, "unrepairable": 0,
    }

    for chunk in manifest.chunks:
        healthy: List[ChunkLocation] = []
        for loc in chunk.locations:
            alive = await _verify_location(loc)
            loc.last_verified_at = now
            stats["verified"] += 1
            if alive:
                loc.status = LocationStatus.ok
                loc.expires_at = estimate_expiry(loc.host, now)
                healthy.append(loc)
            else:
                loc.status = LocationStatus.failed
                stats["dead"] += 1

        deficit = replica - len(healthy)

        # Enough healthy copies: drop dead ones, keep order.
        if deficit <= 0:
            chunk.locations = healthy
            continue

        # Under-replicated. Need a healthy source to copy from.
        if not healthy:
            log.error("[%s] chunk %d has no healthy copy — cannot refresh", video_id, chunk.index)
            stats["unrepairable"] += 1
            continue  # keep original locations so we don't lose the (possibly recoverable) ids

        if dry_run:
            log.info("[%s] chunk %d would add %d copy(ies)", video_id, chunk.index, deficit)
            chunk.locations = healthy
            continue

        used = {l.host for l in healthy}
        targets = [h for h in fill_order if h not in used][:deficit]
        added: List[ChunkLocation] = []
        if targets:
            tmp_path = tmp_root / (chunk.filename or f"chunk_{chunk.index:04d}.mp4")
            try:
                await _download_chunk(healthy[0], tmp_path)
                for host in targets:
                    new_loc = await _upload_copy(host, tmp_path)
                    if new_loc:
                        added.append(new_loc)
                        log.info("[%s] chunk %d: re-uploaded to %s (%s)",
                                 video_id, chunk.index, host, new_loc.file_id)
            except Exception as exc:
                log.warning("[%s] chunk %d: refresh download/upload failed: %s",
                            video_id, chunk.index, exc)
            finally:
                try:
                    if tmp_path.exists():
                        tmp_path.unlink()
                except OSError:
                    pass

        chunk.locations = healthy + added
        stats["repaired" if added else "unrepairable"] += 1

    if tmp_root.exists():
        shutil.rmtree(tmp_root, ignore_errors=True)

    # Persist updated verification timestamps / new locations.
    if not dry_run:
        save_manifest(manifest)
        upsert(manifest)
    return stats


# ── Orchestration ─────────────────────────────────────────────────────────────

async def run_once(
    video_ids: Optional[List[str]] = None,
    *,
    replica_count: Optional[int] = None,
    dry_run: bool = False,
) -> List[dict]:
    ids = video_ids or all_ids()
    results: List[dict] = []
    for vid in ids:
        try:
            s = await refresh_video(vid, replica_count=replica_count, dry_run=dry_run)
        except Exception as exc:
            log.exception("refresh failed for %s", vid)
            s = {"video_id": vid, "error": str(exc)}
        results.append(s)
        log.info("refreshed %s: %s", vid, s)
    return results


async def run_forever(
    interval_sec: Optional[int] = None,
    *,
    replica_count: Optional[int] = None,
) -> None:
    import asyncio

    interval = interval_sec or settings.refresh_interval_sec
    while True:
        log.info("refresher pass starting…")
        await run_once(replica_count=replica_count)
        log.info("refresher pass done; sleeping %ds", interval)
        await asyncio.sleep(interval)
