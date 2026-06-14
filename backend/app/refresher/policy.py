"""Per-host expiry policy for the refresher.

Free file hosts typically delete files that go untouched for a while. We estimate
an expiry timestamp = last_activity + idle window. The refresher's verify pass
fetches a byte from every copy, which both detects dead links AND counts as
activity (resetting the idle timer) on hosts that expire unviewed files.

Values are conservative estimates; tune per real-world observation. ``None`` means
"no known idle-based deletion" (treated as persistent).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

# Idle-deletion windows (days). None = persistent / unknown-but-stable.
HOST_IDLE_DAYS = {
    "fileditch": None, # new.fileditch.com keeps files indefinitely (no scheduled expiry)
    "filester": 45,    # documented: auto-deletes after 45 days without views/downloads
    "gofile": 10,      # free tier reaps inactive files
    "pixeldrain": 60,  # conservative estimate for free idle deletion
    "cyberfile": None,
    "buzzheavier": None,
    "streamtape": None,
}


def idle_days(host: str) -> Optional[int]:
    return HOST_IDLE_DAYS.get(host)


def estimate_expiry(host: str, last_activity: datetime) -> Optional[datetime]:
    """Estimated deletion time given the last activity (upload or verify)."""
    days = HOST_IDLE_DAYS.get(host)
    if not days or last_activity is None:
        return None
    return last_activity + timedelta(days=days)
