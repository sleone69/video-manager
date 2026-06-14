"""
Startup resume / clear logic for interrupted upload jobs.

Called from the FastAPI lifespan on every server start.

  Normal start  → resume all jobs whose status is not 'done'/'error'
  --clear-pending → mark them all as 'error' and delete their checkpoints/temp files
"""
from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path
from typing import Optional

from .queue import _jobs, update_job, enqueue
from .upload_job import run_upload_job
from ..config import settings
from ..db import get_conn, load_all_checkpoints, clear_checkpoints
from ..models import JobProgress, JobStatus, VideoMeta

log = logging.getLogger(__name__)

_RESUMABLE = {"queued", "probing", "chunking", "uploading", "finalising"}


def clear_pending_jobs() -> int:
    """
    Mark all non-terminal jobs as 'error' and remove their temp data.
    Returns the number of jobs cleared.
    """
    conn = get_conn()
    rows = conn.execute(
        "SELECT job_id, video_id FROM jobs WHERE status IN ({})".format(
            ",".join("?" * len(_RESUMABLE))
        ),
        list(_RESUMABLE),
    ).fetchall()
    conn.close()

    for row in rows:
        job_id = row["job_id"]
        video_id = row["video_id"]
        log.info("Clearing pending job %s (video_id=%s)", job_id, video_id)
        clear_checkpoints(job_id)
        if video_id:
            tmp = settings.temp_dir / video_id
            if tmp.exists():
                shutil.rmtree(tmp, ignore_errors=True)
        # Update status in DB
        conn2 = get_conn()
        conn2.execute(
            "UPDATE jobs SET status='error', error='Cleared on startup', updated_at=datetime('now') WHERE job_id=?",
            (job_id,),
        )
        conn2.commit()
        conn2.close()

    return len(rows)


async def resume_pending_jobs() -> int:
    """
    Re-enqueue all interrupted upload jobs found in the DB.
    Jobs with missing temp files or missing meta checkpoint are marked as error.
    Returns the number of jobs resumed.
    """
    conn = get_conn()
    rows = conn.execute(
        "SELECT job_id, video_id, status, message, total_chunks, uploaded_chunks, created_at, updated_at "
        "FROM jobs WHERE status IN ({})".format(",".join("?" * len(_RESUMABLE))),
        list(_RESUMABLE),
    ).fetchall()
    conn.close()

    resumed = 0
    for row in rows:
        job_id = row["job_id"]
        video_id = row["video_id"]
        log.info("Found interrupted job %s (status=%s, video_id=%s)", job_id, row["status"], video_id)

        checkpoints = load_all_checkpoints(job_id)
        meta_cp = checkpoints.get("meta")

        if not meta_cp:
            log.warning("Job %s has no meta checkpoint – cannot resume; marking error", job_id)
            _mark_error(job_id, "No meta checkpoint; cannot resume after restart")
            continue

        # video_id may be stored in the meta checkpoint (fallback for old rows
        # created before the router started persisting it immediately).
        if not video_id:
            video_id = meta_cp.get("video_id")

        # Last-resort fallback: scan temp dirs and match by source-file mtime
        # vs job created_at.  Handles jobs created before video_id was persisted.
        if not video_id:
            video_id = _infer_video_id_from_mtime(row["created_at"], meta_cp)
            if video_id:
                log.info("Job %s: inferred video_id=%s from mtime match", job_id, video_id)
                # Patch the DB so future restarts don't need the scan
                conn2 = get_conn()
                conn2.execute("UPDATE jobs SET video_id=? WHERE job_id=?", (video_id, job_id))
                conn2.commit()
                conn2.close()
                meta_cp["video_id"] = video_id
                from ..db import save_checkpoint as _sc
                _sc(job_id, "meta", meta_cp)

        if not video_id:
            log.warning("Job %s has no video_id – marking error", job_id)
            _mark_error(job_id, "No video_id recorded; cannot resume")
            continue

        source_suffix = meta_cp.get("source_suffix", ".mp4")
        thumb_suffix = meta_cp.get("thumb_suffix")

        tmp_dir = settings.temp_dir / video_id
        video_path = tmp_dir / f"source{source_suffix}"
        thumb_path: Optional[Path] = (tmp_dir / f"thumbnail{thumb_suffix}") if thumb_suffix else None

        if not video_path.exists():
            log.warning("Job %s source file missing (%s) – cannot resume; marking error", job_id, video_path)
            _mark_error(job_id, f"Source file {video_path.name} missing; cannot resume")
            clear_checkpoints(job_id)
            continue

        # Rebuild in-memory job object
        job = JobProgress(
            job_id=job_id,
            status=JobStatus(row["status"]),
            video_id=video_id,
            message=row["message"] or "Resuming after restart…",
            total_chunks=row["total_chunks"] or 0,
            uploaded_chunks=row["uploaded_chunks"] or 0,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
        _jobs[job_id] = job

        meta = VideoMeta(
            name=meta_cp["name"],
            description=meta_cp.get("description", ""),
            star_ids=meta_cp.get("star_ids", []),
        )

        log.info("Resuming job %s (video_id=%s)", job_id, video_id)

        async def _job_coro(_job, j=job, vp=video_path, tp=thumb_path, m=meta, vid=video_id):
            await run_upload_job(job=j, video_path=vp, thumb_path=tp, meta=m, video_id=vid)

        await enqueue(job_id, _job_coro, _existing_job=job)
        resumed += 1

    return resumed


def _mark_error(job_id: str, reason: str) -> None:
    conn = get_conn()
    conn.execute(
        "UPDATE jobs SET status='error', error=?, updated_at=datetime('now') WHERE job_id=?",
        (reason, job_id),
    )
    conn.commit()
    conn.close()


def _infer_video_id_from_mtime(created_at: str, meta_cp: dict) -> Optional[str]:
    """
    Scan settings.temp_dir for a subdirectory whose source file mtime is within
    5 seconds of the job's created_at.  Returns the directory name (video_id) or None.
    """
    import os
    from datetime import timezone

    try:
        # Parse created_at – may be ISO string with or without 'T'
        from datetime import datetime as _dt
        ts_str = created_at.replace("T", " ").split(".")[0]
        job_ts = _dt.strptime(ts_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
    except Exception:
        return None

    source_suffix = meta_cp.get("source_suffix", ".mp4")
    tmp = settings.temp_dir
    if not tmp.exists():
        return None

    best: Optional[str] = None
    best_delta = 5.0  # 5-second tolerance

    for entry in tmp.iterdir():
        if not entry.is_dir():
            continue
        src = entry / f"source{source_suffix}"
        if not src.exists():
            continue
        try:
            mtime = src.stat().st_mtime
            delta = abs(mtime - job_ts)
            if delta < best_delta:
                best_delta = delta
                best = entry.name
        except OSError:
            continue

    return best
