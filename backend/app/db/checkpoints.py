"""Checkpoint CRUD helpers for resumable upload jobs."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, Optional

from .database import get_conn


def save_checkpoint(job_id: str, phase: str, data: Any) -> None:
    """Upsert a checkpoint for the given job+phase."""
    conn = get_conn()
    conn.execute(
        """
        INSERT INTO job_checkpoints (job_id, phase, data, created_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(job_id, phase) DO UPDATE SET data=excluded.data, created_at=excluded.created_at
        """,
        (job_id, phase, json.dumps(data), datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()


def load_checkpoint(job_id: str, phase: str) -> Optional[Any]:
    """Return deserialized checkpoint data or None if not found."""
    conn = get_conn()
    row = conn.execute(
        "SELECT data FROM job_checkpoints WHERE job_id=? AND phase=?",
        (job_id, phase),
    ).fetchone()
    conn.close()
    return json.loads(row["data"]) if row else None


def load_all_checkpoints(job_id: str) -> Dict[str, Any]:
    """Return all checkpoints for a job as {phase: data}."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT phase, data FROM job_checkpoints WHERE job_id=?",
        (job_id,),
    ).fetchall()
    conn.close()
    return {row["phase"]: json.loads(row["data"]) for row in rows}


def clear_checkpoints(job_id: str) -> None:
    """Delete all checkpoints for a completed/failed job."""
    conn = get_conn()
    conn.execute("DELETE FROM job_checkpoints WHERE job_id=?", (job_id,))
    conn.commit()
    conn.close()
