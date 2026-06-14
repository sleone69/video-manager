"""CLI entry point for the expiry refresher.

    python -m backend.app.refresher --once
    python -m backend.app.refresher --interval 21600
    python -m backend.app.refresher --once --video <id> --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import logging

from ..config import settings
from .service import run_forever, run_once


def main() -> None:
    p = argparse.ArgumentParser(
        prog="python -m backend.app.refresher",
        description="VideoManager expiry refresher — verifies chunk copies, keeps them "
                    "alive, and re-uploads to maintain the replica count.",
    )
    p.add_argument("--once", action="store_true", help="run a single pass then exit")
    p.add_argument("--interval", type=int, default=settings.refresh_interval_sec,
                   help="seconds between passes in loop mode (default from settings)")
    p.add_argument("--video", action="append", dest="videos", metavar="ID",
                   help="limit to this video id (repeatable)")
    p.add_argument("--replica", type=int, default=None, help="override replica count")
    p.add_argument("--dry-run", action="store_true",
                   help="report planned actions without downloading/uploading")
    p.add_argument("--quiet", action="store_true", help="only log warnings and errors")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s – %(message)s",
    )

    if args.once or args.videos or args.dry_run:
        asyncio.run(run_once(args.videos, replica_count=args.replica, dry_run=args.dry_run))
    else:
        asyncio.run(run_forever(args.interval, replica_count=args.replica))


if __name__ == "__main__":
    main()
