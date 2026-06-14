"""Standalone expiry refresher.

Run as a separate process from the repo root:

    python -m backend.app.refresher --once          # single pass over all videos
    python -m backend.app.refresher --interval 21600 # loop every 6h (default)
    python -m backend.app.refresher --video <id> --dry-run

See policy.py for per-host expiry windows and service.py for the engine.
"""
from .service import refresh_video, run_once, run_forever  # noqa: F401

__all__ = ["refresh_video", "run_once", "run_forever"]
