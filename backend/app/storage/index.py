"""Sync a Manifest into the SQLite index."""
from __future__ import annotations

from ..db import get_conn
from ..models import Manifest


def upsert(manifest: Manifest) -> None:
    conn = get_conn()
    res = manifest.resolution
    conn.execute(
        """
        INSERT INTO videos (video_id, name, description, duration_sec,
                            width, height, fps, codec, upload_date, manifest_path)
        VALUES (:video_id, :name, :description, :duration_sec,
                :width, :height, :fps, :codec, :upload_date, :manifest_path)
        ON CONFLICT(video_id) DO UPDATE SET
            name=excluded.name,
            description=excluded.description,
            duration_sec=excluded.duration_sec,
            width=excluded.width,
            height=excluded.height,
            fps=excluded.fps,
            codec=excluded.codec,
            upload_date=excluded.upload_date,
            manifest_path=excluded.manifest_path
        """,
        {
            "video_id": manifest.video_id,
            "name": manifest.name,
            "description": manifest.description,
            "duration_sec": manifest.duration_sec,
            "width": res.width if res else None,
            "height": res.height if res else None,
            "fps": res.fps if res else None,
            "codec": res.codec if res else None,
            "upload_date": manifest.upload_date.isoformat(),
            "manifest_path": f"{manifest.video_id}.json",
        },
    )
    # rebuild star links – only for star IDs that exist in the stars catalog
    conn.execute("DELETE FROM video_stars WHERE video_id=?", (manifest.video_id,))
    if manifest.star_ids:
        placeholders = ",".join("?" * len(manifest.star_ids))
        existing = {
            row[0]
            for row in conn.execute(
                f"SELECT star_id FROM stars WHERE star_id IN ({placeholders})",
                manifest.star_ids,
            ).fetchall()
        }
        for sid in manifest.star_ids:
            if sid in existing:
                conn.execute(
                    "INSERT OR IGNORE INTO video_stars (video_id, star_id) VALUES (?, ?)",
                    (manifest.video_id, sid),
                )
    conn.commit()
    conn.close()


def remove(video_id: str) -> None:
    conn = get_conn()
    conn.execute("DELETE FROM videos WHERE video_id=?", (video_id,))
    conn.commit()
    conn.close()
