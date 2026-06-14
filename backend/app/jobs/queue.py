"""In-process async job queue with progress tracking."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Callable, Coroutine, Dict, Any, Optional

from ..models import JobProgress, JobStatus
from ..db import get_conn

log = logging.getLogger(__name__)


# In-memory store (survives process lifetime; lost on restart intentionally for
# simplicity – durable state lives in the manifest JSON + SQLite).
_jobs: Dict[str, JobProgress] = {}
# Cancellation events: set() to signal the running task to stop.
_cancel_events: Dict[str, asyncio.Event] = {}


def get_job(job_id: str) -> Optional[JobProgress]:
    return _jobs.get(job_id)


def list_jobs(limit: int = 100) -> list[JobProgress]:
    """Return recent jobs from SQLite (includes jobs from previous server runs)."""
    conn = get_conn()
    rows = conn.execute(
        """
        SELECT job_id, status, video_id, message, total_chunks,
               uploaded_chunks, error, bytes_per_sec, eta_sec, created_at, updated_at
        FROM jobs
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    conn.close()
    result = []
    for row in rows:
        # Prefer in-memory version (has live status)
        if row["job_id"] in _jobs:
            result.append(_jobs[row["job_id"]])
        else:
            result.append(
                JobProgress(
                    job_id=row["job_id"],
                    status=row["status"],
                    video_id=row["video_id"],
                    message=row["message"] or "",
                    total_chunks=row["total_chunks"] or 0,
                    uploaded_chunks=row["uploaded_chunks"] or 0,
                    error=row["error"],
                    bytes_per_sec=row["bytes_per_sec"],
                    eta_sec=row["eta_sec"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                )
            )
    return result


def _persist(job: JobProgress) -> None:
    conn = get_conn()
    conn.execute(
        """
        INSERT INTO jobs (job_id, status, video_id, message, total_chunks,
                          uploaded_chunks, error, bytes_per_sec, eta_sec,
                          created_at, updated_at)
        VALUES (:job_id,:status,:video_id,:message,:total_chunks,
                :uploaded_chunks,:error,:bytes_per_sec,:eta_sec,
                :created_at,:updated_at)
        ON CONFLICT(job_id) DO UPDATE SET
            status=excluded.status, video_id=excluded.video_id,
            message=excluded.message, total_chunks=excluded.total_chunks,
            uploaded_chunks=excluded.uploaded_chunks, error=excluded.error,
            bytes_per_sec=excluded.bytes_per_sec, eta_sec=excluded.eta_sec,
            updated_at=excluded.updated_at
        """,
        {
            "job_id": job.job_id,
            "status": job.status.value,
            "video_id": job.video_id,
            "message": job.message,
            "total_chunks": job.total_chunks,
            "uploaded_chunks": job.uploaded_chunks,
            "error": job.error,
            "bytes_per_sec": job.bytes_per_sec,
            "eta_sec": job.eta_sec,
            "created_at": job.created_at.isoformat(),
            "updated_at": job.updated_at.isoformat(),
        },
    )
    conn.commit()
    conn.close()


def cancel_job(job_id: str) -> bool:
    """Signal a running job to cancel.  Returns True if the job existed and was cancellable."""
    job = _jobs.get(job_id)
    if not job:
        return False
    terminal = {JobStatus.done, JobStatus.error}
    if job.status in terminal:
        return False
    # Signal the task
    ev = _cancel_events.get(job_id)
    if ev:
        ev.set()
    # Mark immediately so the API reflects the change before the task notices
    update_job(job, status=JobStatus.error, error="Cancelled by user",
               bytes_per_sec=None, eta_sec=None)
    return True


def is_cancelled(job_id: str) -> bool:
    """Check whether a cancel has been requested for this job."""
    ev = _cancel_events.get(job_id)
    return ev is not None and ev.is_set()


def update_job(job: JobProgress, **kwargs) -> JobProgress:
    for k, v in kwargs.items():
        setattr(job, k, v)
    job.updated_at = datetime.utcnow()
    _jobs[job.job_id] = job
    _persist(job)
    return job


async def enqueue(
    job_id: str,
    coro_factory: Callable[["JobProgress"], Coroutine[Any, Any, None]],
    _existing_job: Optional["JobProgress"] = None,
) -> JobProgress:
    """Create (or reuse) a job record and schedule the coroutine in the background.

    Pass ``_existing_job`` when resuming an interrupted job so the existing
    DB row and in-memory state are reused rather than overwritten.
    """
    if _existing_job is not None:
        job = _existing_job
        _jobs[job_id] = job
        # Don't _persist here – DB row already exists and was loaded by caller
    else:
        job = JobProgress(job_id=job_id)
        _jobs[job_id] = job
        _persist(job)

    async def _run():
        try:
            await coro_factory(job)
        except Exception as exc:
            log.exception("Job %s failed", job_id)
            update_job(job, status=JobStatus.error, error=str(exc))
        finally:
            _cancel_events.pop(job_id, None)

    _cancel_events[job_id] = asyncio.Event()
    asyncio.create_task(_run())
    return job
