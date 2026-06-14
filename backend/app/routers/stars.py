"""Stars catalog router (CRUD)."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException

from ..db import get_conn
from ..models import Star, StarCreate, StarUpdate

router = APIRouter(prefix="/stars", tags=["stars"])


def _row_to_star(row) -> Star:
    return Star(
        star_id=row["star_id"],
        name=row["name"],
        image_url=row["image_url"],
        bio=row["bio"],
        created_at=row["created_at"],
    )


@router.get("", response_model=List[Star])
async def list_stars():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM stars ORDER BY name").fetchall()
    conn.close()
    return [_row_to_star(r) for r in rows]


@router.post("", response_model=Star, status_code=201)
async def create_star(body: StarCreate):
    star_id = uuid.uuid4().hex
    now = datetime.utcnow().isoformat()
    conn = get_conn()
    conn.execute(
        "INSERT INTO stars (star_id,name,image_url,bio,created_at) VALUES (?,?,?,?,?)",
        (star_id, body.name, body.image_url, body.bio, now),
    )
    conn.commit()
    conn.close()
    return Star(star_id=star_id, name=body.name, image_url=body.image_url, bio=body.bio)


@router.get("/{star_id}", response_model=Star)
async def get_star(star_id: str):
    conn = get_conn()
    row = conn.execute("SELECT * FROM stars WHERE star_id=?", (star_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Star not found")
    return _row_to_star(row)


@router.patch("/{star_id}", response_model=Star)
async def update_star(star_id: str, body: StarUpdate):
    conn = get_conn()
    row = conn.execute("SELECT * FROM stars WHERE star_id=?", (star_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Star not found")

    updated = dict(row)
    if body.name is not None:
        updated["name"] = body.name
    if body.image_url is not None:
        updated["image_url"] = body.image_url
    if body.bio is not None:
        updated["bio"] = body.bio

    conn.execute(
        "UPDATE stars SET name=?,image_url=?,bio=? WHERE star_id=?",
        (updated["name"], updated["image_url"], updated["bio"], star_id),
    )
    conn.commit()
    conn.close()
    return Star(**updated)


@router.delete("/{star_id}", status_code=204)
async def delete_star(star_id: str):
    conn = get_conn()
    if not conn.execute("SELECT 1 FROM stars WHERE star_id=?", (star_id,)).fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail="Star not found")
    conn.execute("DELETE FROM stars WHERE star_id=?", (star_id,))
    conn.commit()
    conn.close()
