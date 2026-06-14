"""
End-to-end video upload job orchestration with per-phase checkpoints.

Checkpoint phases (stored in job_checkpoints table):
  meta           – VideoMeta + source/thumb suffixes (saved immediately)
  video_info     – ffprobe result (saved after probe)
  chunks_created – list of ChunkResult metadata (saved after chunking)
  chunk_{N}      – list of ChunkLocation dicts for chunk N (saved after upload)

On restart the job runner loads all checkpoints and skips completed phases.
"""
from __future__ import annotations

import asyncio
import logging
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .queue import update_job, is_cancelled
from ..config import settings
from ..db import save_checkpoint, load_checkpoint, load_all_checkpoints, clear_checkpoints
from ..hosts.registry import upload_adapters
from ..images.gdrive import GDriveAdapter
from ..images.jpgsu import JpgSuAdapter
from ..media.probe import probe, extract_keyframes, VideoInfo
from ..media.chunker import chunk_video, ChunkResult
from ..media.splitter import split_video, PartResult
from ..models import (
    Chunk, ChunkLocation, JobProgress, JobStatus,
    LocationStatus, Manifest, Resolution, StreamtapePart, Thumbnail, VideoMeta,
)
from ..storage import save as save_manifest, upsert as index_manifest

log = logging.getLogger(__name__)


# ── Public entry point ────────────────────────────────────────────────────────

async def run_upload_job(
    job: JobProgress,
    video_path: Path,
    thumb_path: Optional[Path],
    meta: VideoMeta,
    video_id: str,
) -> None:
    """Run (or resume) an upload job, checkpointing every major phase.

    Temp files are NOT cleaned up on error/interrupt so the job can be resumed.
    They are removed only on successful completion.
    """
    chunk_dir = settings.temp_dir / video_id
    # Persist meta + file suffixes immediately so resume can reconstruct context
    if load_checkpoint(job.job_id, "meta") is None:
        save_checkpoint(job.job_id, "meta", {
            "name": meta.name,
            "description": meta.description,
            "star_ids": meta.star_ids,
            "video_id": video_id,
            "source_suffix": video_path.suffix,
            "thumb_suffix": thumb_path.suffix if thumb_path else None,
        })
    await _run(job, video_path, thumb_path, meta, video_id, chunk_dir)



# ── Internal ──────────────────────────────────────────────────────────────────

async def _run(
    job: JobProgress,
    video_path: Path,
    thumb_path: Optional[Path],
    meta: VideoMeta,
    video_id: str,
    chunk_dir: Path,
) -> None:
    checkpoints: Dict[str, Any] = load_all_checkpoints(job.job_id)

    # ── 1. Probe ──────────────────────────────────────────────────────────
    if "video_info" in checkpoints:
        log.info("[%s] Restoring probe from checkpoint", video_id)
        info = _deserialize_video_info(checkpoints["video_info"])
    else:
        update_job(job, status=JobStatus.probing, message="Probing video metadata…")
        info = await probe(video_path)
        log.info("[%s] Probe done: %.1fs %dx%d", video_id, info.duration_sec, info.width, info.height)

        # Keyframe extraction is a separate slow step — show its own message
        update_job(job, status=JobStatus.probing, message="Extracting keyframe index…")
        info.keyframe_times = await extract_keyframes(video_path)
        log.info("[%s] Keyframe extraction done: %d keyframes", video_id, len(info.keyframe_times))

        save_checkpoint(job.job_id, "video_info", _serialize_video_info(info))

    # ── 2. Chunk ──────────────────────────────────────────────────────────
    if "chunks_created" in checkpoints:
        log.info("[%s] Restoring chunk list from checkpoint", video_id)
        chunk_results = _deserialize_chunks(checkpoints["chunks_created"], chunk_dir)
        missing = [cr for cr in chunk_results if not cr.path.exists()]
        if missing:
            log.warning("[%s] %d chunk file(s) missing; re-chunking…", video_id, len(missing))
            chunk_results = await _do_chunk(job, video_path, chunk_dir, info)
            save_checkpoint(job.job_id, "chunks_created", _serialize_chunk_list(chunk_results))
            # Invalidate stale per-chunk upload checkpoints
            stale = [k for k in checkpoints if k.startswith("chunk_") and k != "chunks_created"]
            if stale:
                from ..db import get_conn
                conn = get_conn()
                conn.executemany(
                    "DELETE FROM job_checkpoints WHERE job_id=? AND phase=?",
                    [(job.job_id, k) for k in stale],
                )
                conn.commit()
                conn.close()
            checkpoints = load_all_checkpoints(job.job_id)
    else:
        chunk_results = await _do_chunk(job, video_path, chunk_dir, info)
        save_checkpoint(job.job_id, "chunks_created", _serialize_chunk_list(chunk_results))
        log.info("[%s] Chunking done: %d chunks", video_id, len(chunk_results))

    update_job(job, total_chunks=len(chunk_results))

    # ── 3. Upload chunks to a host replica set (concurrent across chunks) ──
    update_job(job, status=JobStatus.uploading, message="Uploading chunks to hosts…")
    adapters = upload_adapters()
    replica = max(1, settings.replica_count)

    # Restore chunks already uploaded (resume).
    locations_by_index: Dict[int, List[ChunkLocation]] = {}
    for cr in chunk_results:
        phase = f"chunk_{cr.index}"
        if phase in checkpoints:
            locations_by_index[cr.index] = [ChunkLocation(**loc) for loc in checkpoints[phase]]

    total = len(chunk_results)
    done_count = len(locations_by_index)
    if done_count:
        update_job(job, uploaded_chunks=done_count,
                   message=f"Resuming upload — {done_count}/{total} chunks already done")

    start_wall = time.monotonic()
    uploaded_bytes = 0
    sem = asyncio.Semaphore(max(1, settings.upload_concurrency))
    progress_lock = asyncio.Lock()

    async def _upload_one(cr: ChunkResult) -> None:
        nonlocal done_count, uploaded_bytes
        if cr.index in locations_by_index:
            return
        async with sem:
            if is_cancelled(job.job_id):
                return
            locations = await _upload_chunk(cr, adapters, video_id, replica)
            save_checkpoint(
                job.job_id, f"chunk_{cr.index}",
                [loc.model_dump(mode="json") for loc in locations],
            )
            async with progress_lock:
                locations_by_index[cr.index] = locations
                done_count += 1
                uploaded_bytes += cr.byte_size
                elapsed = time.monotonic() - start_wall
                bps = (uploaded_bytes / elapsed) if elapsed > 0 else None
                remaining_bytes = sum(
                    c.byte_size for c in chunk_results if c.index not in locations_by_index
                )
                eta = int(remaining_bytes / bps) if (bps and remaining_bytes) else None
                update_job(
                    job, uploaded_chunks=done_count, bytes_per_sec=bps, eta_sec=eta,
                    message=f"Uploaded {done_count}/{total} chunks",
                )

    await asyncio.gather(*[_upload_one(cr) for cr in chunk_results])

    if is_cancelled(job.job_id):
        log.info("[%s] Job cancelled during chunk upload", video_id)
        return  # job status already set to error by cancel_job()

    manifest_chunks: List[Chunk] = [
        Chunk(
            index=cr.index,
            start_sec=cr.start_sec,
            end_sec=cr.end_sec,
            byte_size=cr.byte_size,
            filename=cr.filename,
            locations=locations_by_index.get(cr.index, []),
        )
        for cr in chunk_results
    ]

    # ── 4. Upload Streamtape parts (opt-in; off by default) ──────────────────
    st_parts: List[StreamtapePart] = []
    if settings.streamtape_enabled and settings.streamtape_login and settings.streamtape_key:
        if "streamtape_parts" in checkpoints:
            st_parts = [StreamtapePart(**p) for p in checkpoints["streamtape_parts"]]
            log.info("[%s] Restored %d Streamtape part(s) from checkpoint", video_id, len(st_parts))
        else:
            st_parts = await _upload_streamtape_parts(job, video_path, chunk_dir, info, video_id)
            save_checkpoint(job.job_id, "streamtape_parts", [p.model_dump() for p in st_parts])
            log.info("[%s] Uploaded %d Streamtape part(s)", video_id, len(st_parts))

    # ── 5. Upload thumbnail ───────────────────────────────────────────────
    update_job(job, status=JobStatus.finalising, message="Uploading thumbnail…")
    thumbnail = Thumbnail()
    if thumb_path and thumb_path.exists():
        thumbnail = await _upload_thumbnail(thumb_path)

    # ── 6. Assemble + persist manifest ─────────────────────────────────────────
    manifest = Manifest(
        video_id=video_id,
        name=meta.name,
        description=meta.description,
        duration_sec=info.duration_sec,
        resolution=Resolution(
            width=info.width,
            height=info.height,
            fps=info.fps,
            codec=info.codec,
            mse_codec=info.mse_codec,
            bitrate_kbps=info.bitrate_kbps,
        ),
        star_ids=meta.star_ids,
        thumbnail=thumbnail,
        chunks=manifest_chunks,
        streamtape_parts=st_parts,
    )
    save_manifest(manifest)
    index_manifest(manifest)

    update_job(job, status=JobStatus.done, video_id=video_id,
               bytes_per_sec=None, eta_sec=None, message="Upload complete")
    log.info("[%s] job done – %d chunks on %d host(s), %d Streamtape part(s)",
             video_id, len(manifest_chunks), len(adapters), len(st_parts))

    # ── 7. Cleanup temp files + checkpoints on success ─────────────────────────
    clear_checkpoints(job.job_id)
    _cleanup_temp(chunk_dir, video_path, thumb_path)


async def _do_chunk(
    job: JobProgress,
    video_path: Path,
    chunk_dir: Path,
    info: VideoInfo,
) -> List[ChunkResult]:
    update_job(job, status=JobStatus.chunking, message="Splitting into chunks…")
    return await chunk_video(source=video_path, output_dir=chunk_dir, video_info=info)


def _cleanup_temp(chunk_dir: Path, video_path: Path, thumb_path: Optional[Path]) -> None:
    if chunk_dir.exists():
        shutil.rmtree(chunk_dir, ignore_errors=True)
    if video_path.exists():
        video_path.unlink(missing_ok=True)
    if thumb_path and thumb_path.exists():
        thumb_path.unlink(missing_ok=True)


# ── Serialization helpers ─────────────────────────────────────────────────────

def _serialize_video_info(info: VideoInfo) -> dict:
    return {
        "duration_sec": info.duration_sec,
        "width": info.width,
        "height": info.height,
        "fps": info.fps,
        "codec": info.codec,
        "mse_codec": info.mse_codec,
        "bitrate_kbps": info.bitrate_kbps,
        "size_bytes": info.size_bytes,
        "keyframe_times": info.keyframe_times,
    }


def _deserialize_video_info(data: dict) -> VideoInfo:
    return VideoInfo(
        duration_sec=data["duration_sec"],
        width=data["width"],
        height=data["height"],
        fps=data["fps"],
        codec=data["codec"],
        mse_codec=data["mse_codec"],
        bitrate_kbps=data.get("bitrate_kbps"),
        size_bytes=data["size_bytes"],
        keyframe_times=data["keyframe_times"],
    )


def _serialize_chunk_list(chunk_results: List[ChunkResult]) -> list:
    return [
        {
            "index": cr.index,
            "filename": cr.filename,
            "start_sec": cr.start_sec,
            "end_sec": cr.end_sec,
            "byte_size": cr.byte_size,
        }
        for cr in chunk_results
    ]


def _deserialize_chunks(data: list, chunk_dir: Path) -> List[ChunkResult]:
    return [
        ChunkResult(
            index=item["index"],
            path=chunk_dir / item["filename"],
            start_sec=item["start_sec"],
            end_sec=item["end_sec"],
            byte_size=item["byte_size"],
            filename=item["filename"],
        )
        for item in data
    ]


# ── Chunk upload ──────────────────────────────────────────────────────────────

async def _upload_chunk(
    cr: ChunkResult,
    adapters,
    video_id: str,
    replica: int,
) -> List[ChunkLocation]:
    """Upload a chunk to ``replica`` hosts (priority order), trying further hosts
    only to make up for failures. Returns the successful ChunkLocations."""
    async def _try_upload(adapter) -> Optional[ChunkLocation]:
        try:
            file_id, url = await adapter.upload(cr.path)
            log.info("  [%s] chunk %d → %s (%s)", video_id, cr.index, adapter.name, file_id)
            return ChunkLocation(
                host=adapter.name, file_id=file_id, url=url,
                status=LocationStatus.ok, uploaded_at=datetime.utcnow(),
            )
        except NotImplementedError:
            return None
        except Exception as exc:
            log.warning("  [%s] chunk %d → %s failed: %s", video_id, cr.index, adapter.name, exc)
            return None

    locations: List[ChunkLocation] = []
    i = 0
    while len(locations) < replica and i < len(adapters):
        need = replica - len(locations)
        batch = adapters[i:i + need]
        i += len(batch)
        for r in await asyncio.gather(*[_try_upload(a) for a in batch]):
            if r is not None:
                locations.append(r)
    if not locations:
        log.error("[%s] chunk %d: all hosts failed — no copies stored", video_id, cr.index)
    return locations


# ── Thumbnail ─────────────────────────────────────────────────────────────────

async def _upload_thumbnail(thumb_path: Path) -> Thumbnail:
    gdrive_info = None
    jpgsu_info = None
    try:
        gdrive_info = await GDriveAdapter().upload(thumb_path)
    except NotImplementedError:
        pass
    except Exception as exc:
        log.warning("GDrive thumbnail upload failed: %s", exc)
    try:
        jpgsu_info = await JpgSuAdapter().upload(thumb_path)
    except NotImplementedError:
        pass
    except Exception as exc:
        log.warning("jpg.su thumbnail upload failed: %s", exc)
    return Thumbnail(gdrive=gdrive_info, jpgsu=jpgsu_info)


# ── Streamtape part upload ─────────────────────────────────────────────────────

async def _upload_streamtape_parts(
    job: JobProgress,
    video_path: Path,
    chunk_dir: Path,
    info: VideoInfo,
    video_id: str,
) -> List[StreamtapePart]:
    """Split the source video and upload each part to Streamtape."""
    from ..hosts.streamtape import StreamtapeAdapter

    update_job(job, status=JobStatus.uploading, message="Splitting video for Streamtape…")
    parts_dir = chunk_dir / "st_parts"
    part_size = settings.streamtape_part_size_bytes

    part_results = await split_video(video_path, parts_dir, info, part_size)
    adapter = StreamtapeAdapter()
    st_parts: List[StreamtapePart] = []

    for pr in part_results:
        update_job(
            job,
            message=f"Uploading Streamtape part {pr.index + 1}/{len(part_results)} ({pr.filename})…",
        )
        try:
            file_id, _ = await adapter.upload(pr.path)
            st_parts.append(
                StreamtapePart(
                    index=pr.index,
                    file_id=file_id,
                    start_sec=pr.start_sec,
                    end_sec=pr.end_sec,
                    byte_size=pr.byte_size,
                    filename=pr.filename,
                )
            )
            log.info(
                "[%s] Streamtape part %d → %s", video_id, pr.index, file_id
            )
        except Exception as exc:
            log.warning(
                "[%s] Streamtape part %d upload failed: %s — skipping", video_id, pr.index, exc
            )

    return st_parts

