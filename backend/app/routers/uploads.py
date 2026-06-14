"""Upload router — ingest video + thumbnail and start background job.

Two ingest paths:
  * POST /uploads                  – single multipart request (CLI / localhost).
  * POST /uploads/init + PUT parts – chunked upload: the browser slices the file
    into sub-100 MB parts so uploads work through the Cloudflare tunnel. The
    backend stages parts then reassembles them in the background.
"""
from __future__ import annotations

import asyncio
import json
import shutil
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse

from ..config import settings
from ..jobs import enqueue, get_job, list_jobs, run_upload_job, cancel_job
from ..jobs.queue import update_job as _update_job
from ..models import JobProgress, VideoMeta

router = APIRouter(prefix="/uploads", tags=["uploads"])

_CHUNK = 1 * 1024 * 1024  # 1 MB write chunks
_SESSION_META = "upload_session.json"  # chunked-upload session sidecar file


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


# ── Chunked upload (large files / Cloudflare tunnel) ───────────────────────────

@router.post("/init", status_code=201)
async def init_chunked_upload(body: dict):
    """Begin a chunked upload. Returns an ``upload_id`` and the part size the
    client should slice the file into (kept under Cloudflare's request-body cap)."""
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    suffix = Path(body.get("filename") or "video.mp4").suffix or ".mp4"
    raw_stars = body.get("star_ids") or []
    if isinstance(raw_stars, str):
        star_ids = [s.strip() for s in raw_stars.split(",") if s.strip()]
    else:
        star_ids = [str(s).strip() for s in raw_stars if str(s).strip()]

    video_id = uuid.uuid4().hex
    tmp = settings.temp_dir / video_id
    (tmp / "parts").mkdir(parents=True, exist_ok=True)
    meta = {
        "video_id": video_id,
        "name": name,
        "description": body.get("description", ""),
        "star_ids": star_ids,
        "source_suffix": suffix,
        "thumb_suffix": None,
    }
    (tmp / _SESSION_META).write_text(json.dumps(meta))
    return {"upload_id": video_id, "video_id": video_id, "part_size": settings.upload_part_size_bytes}


@router.put("/{upload_id}/part/{index}")
async def upload_part(upload_id: str, index: int, request: Request):
    """Receive one raw file part and stream it straight to disk."""
    parts = settings.temp_dir / upload_id / "parts"
    if not parts.is_dir():
        raise HTTPException(status_code=404, detail="Unknown or expired upload_id")
    if index < 0:
        raise HTTPException(status_code=400, detail="bad part index")
    dest = parts / f"part_{index:06d}"
    size = 0
    with dest.open("wb") as fh:
        async for chunk in request.stream():
            fh.write(chunk)
            size += len(chunk)
    return {"index": index, "bytes": size}


@router.post("/{upload_id}/thumbnail")
async def upload_session_thumbnail(upload_id: str, request: Request, filename: str = "thumbnail.jpg"):
    tmp = settings.temp_dir / upload_id
    meta_path = tmp / _SESSION_META
    if not meta_path.exists():
        raise HTTPException(status_code=404, detail="Unknown or expired upload_id")
    suffix = Path(filename).suffix or ".jpg"
    dest = tmp / f"thumbnail{suffix}"
    with dest.open("wb") as fh:
        async for chunk in request.stream():
            fh.write(chunk)
    meta = json.loads(meta_path.read_text())
    meta["thumb_suffix"] = suffix
    meta_path.write_text(json.dumps(meta))
    return {"ok": True}


def _assemble_parts(part_files: list[Path], source: Path) -> None:
    """Concatenate parts into the source file, freeing each part as we go."""
    with source.open("wb") as out:
        for p in part_files:
            with p.open("rb") as fh:
                shutil.copyfileobj(fh, out, length=_CHUNK)
            p.unlink(missing_ok=True)


@router.post("/{upload_id}/complete", status_code=202)
async def complete_chunked_upload(upload_id: str, body: dict):
    """Validate the uploaded parts, then reassemble + start the job in the
    background (returns immediately so the tunnel's response timeout isn't hit)."""
    tmp = settings.temp_dir / upload_id
    meta_path = tmp / _SESSION_META
    if not meta_path.exists():
        raise HTTPException(status_code=404, detail="Unknown or expired upload_id")
    meta = json.loads(meta_path.read_text())

    parts_dir = tmp / "parts"
    found = sorted(parts_dir.glob("part_*")) if parts_dir.is_dir() else []
    if not found:
        raise HTTPException(status_code=400, detail="no parts uploaded")
    total_parts = int(body.get("total_parts") or 0)
    if total_parts and total_parts != len(found):
        raise HTTPException(status_code=400, detail=f"expected {total_parts} parts, found {len(found)}")
    # Require contiguous indices 0..N-1.
    expected = [parts_dir / f"part_{i:06d}" for i in range(len(found))]
    missing = [p.name for p in expected if not p.exists()]
    if missing:
        raise HTTPException(status_code=400, detail=f"missing parts: {missing[:5]}")

    source = tmp / f"source{meta['source_suffix']}"
    thumb_path: Optional[Path] = None
    if meta.get("thumb_suffix"):
        tp = tmp / f"thumbnail{meta['thumb_suffix']}"
        if tp.exists():
            thumb_path = tp

    video_meta = VideoMeta(
        name=meta["name"], description=meta.get("description", ""), star_ids=meta.get("star_ids", []),
    )
    video_id = meta["video_id"]
    job_id = uuid.uuid4().hex

    async def _job_coro(job: JobProgress):
        _update_job(job, video_id=video_id, message="Reassembling uploaded parts…")
        # Concatenation is blocking I/O — run it off the event loop.
        await asyncio.get_event_loop().run_in_executor(None, _assemble_parts, expected, source)
        shutil.rmtree(parts_dir, ignore_errors=True)
        meta_path.unlink(missing_ok=True)
        await run_upload_job(
            job=job, video_path=source, thumb_path=thumb_path, meta=video_meta, video_id=video_id,
        )

    job = await enqueue(job_id, _job_coro)
    _update_job(job, video_id=video_id, message="Reassembling uploaded parts…")
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
