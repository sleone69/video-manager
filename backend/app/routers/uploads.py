"""Upload router — ingest video + thumbnail and start background job."""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from ..config import settings
from ..jobs import enqueue, get_job, list_jobs, run_upload_job, cancel_job
from ..jobs.queue import update_job as _update_job
from ..models import JobProgress, VideoMeta

router = APIRouter(prefix="/uploads", tags=["uploads"])

_CHUNK = 1 * 1024 * 1024  # 1 MB write chunks


async def _save_upload(upload: UploadFile, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("wb") as fh:
        while data := await upload.read(_CHUNK):
            fh.write(data)


@router.post("", status_code=202)
async def start_upload(
    video: UploadFile = File(..., description="Raw video file"),
    thumbnail: Optional[UploadFile] = File(None, description="Thumbnail image"),
    name: str = Form(...),
    description: str = Form(""),
    star_ids: str = Form("", description="Comma-separated star IDs"),
):
    """
    Accept a video (+ optional thumbnail) and metadata, save to temp storage,
    then kick off an async upload job.

    Returns 202 Accepted with a job_id for progress polling.
    """
    video_id = uuid.uuid4().hex
    job_id = uuid.uuid4().hex

    # Save uploaded files to temp dir
    tmp = settings.temp_dir / video_id
    tmp.mkdir(parents=True, exist_ok=True)

    suffix = Path(video.filename or "video.mp4").suffix or ".mp4"
    video_path = tmp / f"source{suffix}"
    await _save_upload(video, video_path)

    thumb_path: Optional[Path] = None
    if thumbnail and thumbnail.filename:
        thumb_suffix = Path(thumbnail.filename).suffix or ".jpg"
        thumb_path = tmp / f"thumbnail{thumb_suffix}"
        await _save_upload(thumbnail, thumb_path)

    meta = VideoMeta(
        name=name,
        description=description,
        star_ids=[s.strip() for s in star_ids.split(",") if s.strip()],
    )

    async def _job_coro(job: JobProgress):
        await run_upload_job(
            job=job,
            video_path=video_path,
            thumb_path=thumb_path,
            meta=meta,
            video_id=video_id,
        )

    job = await enqueue(job_id, _job_coro)
    # Record video_id immediately so the resume logic can find the temp dir
    # even if the server restarts before the job completes.
    _update_job(job, video_id=video_id)
    return {"job_id": job_id, "video_id": video_id}


@router.get("", response_model=list[JobProgress])
async def list_upload_jobs(limit: int = 100):
    """Return all upload jobs (most recent first)."""
    return list_jobs(limit=limit)


@router.delete("/{job_id}", status_code=200)
async def cancel_upload(job_id: str):
    """Cancel a running or queued upload job."""
    # Try in-memory cancel first
    cancelled = cancel_job(job_id)
    if not cancelled:
        # Job may only exist in DB (e.g. already done/error) – check
        all_jobs = list_jobs(limit=10000)
        job = next((j for j in all_jobs if j.job_id == job_id), None)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        if job.status in ("done", "error"):
            raise HTTPException(status_code=409, detail=f"Job already {job.status}")
    return {"job_id": job_id, "cancelled": True}


@router.get("/{job_id}", response_model=JobProgress)
async def get_upload_progress(job_id: str):
    """Poll progress of a running or completed upload job."""
    job = get_job(job_id)
    if not job:
        # In-memory cache is empty after restart; fall back to DB via list_jobs
        all_jobs = list_jobs(limit=10000)
        job = next((j for j in all_jobs if j.job_id == job_id), None)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job
