"""Videos metadata router."""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query

from ..db import get_conn
from ..models import Manifest
from ..storage import load, delete, all_ids, upsert, remove

router = APIRouter(prefix="/videos", tags=["videos"])


def _row_to_summary(row) -> dict:
    return {
        "video_id": row["video_id"],
        "name": row["name"],
        "description": row["description"],
        "duration_sec": row["duration_sec"],
        "width": row["width"],
        "height": row["height"],
        "fps": row["fps"],
        "codec": row["codec"],
        "upload_date": row["upload_date"],
    }


@router.get("")
async def list_videos(
    search: Optional[str] = Query(None, description="Full-text search on name/description"),
    star_id: Optional[str] = Query(None, description="Filter by star ID"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    conn = get_conn()
    offset = (page - 1) * per_page

    if search:
        rows = conn.execute(
            """
            SELECT v.* FROM videos v
            JOIN videos_fts f ON v.video_id = f.video_id
            WHERE videos_fts MATCH ?
            ORDER BY rank
            LIMIT ? OFFSET ?
            """,
            (search, per_page, offset),
        ).fetchall()
    elif star_id:
        rows = conn.execute(
            """
            SELECT v.* FROM videos v
            JOIN video_stars vs ON v.video_id = vs.video_id
            WHERE vs.star_id = ?
            ORDER BY v.upload_date DESC
            LIMIT ? OFFSET ?
            """,
            (star_id, per_page, offset),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM videos ORDER BY upload_date DESC LIMIT ? OFFSET ?",
            (per_page, offset),
        ).fetchall()

    total = conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
    conn.close()
    return {
        "data": [_row_to_summary(r) for r in rows],
        "pagination": {"page": page, "per_page": per_page, "total": total},
    }


@router.get("/{video_id}", response_model=Manifest)
async def get_video(video_id: str):
    manifest = load(video_id)
    if not manifest:
        raise HTTPException(status_code=404, detail="Video not found")
    return manifest


@router.patch("/{video_id}", response_model=Manifest)
async def update_video(video_id: str, body: dict):
    manifest = load(video_id)
    if not manifest:
        raise HTTPException(status_code=404, detail="Video not found")

    allowed = {"name", "description", "star_ids"}
    for k, v in body.items():
        if k in allowed:
            setattr(manifest, k, v)

    from ..storage.manifest_store import save
    save(manifest)
    upsert(manifest)
    return manifest


@router.delete("/{video_id}", status_code=204)
async def delete_video(video_id: str):
    if not load(video_id):
        raise HTTPException(status_code=404, detail="Video not found")
    delete(video_id)
    remove(video_id)
