from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # ── FastAPI ────────────────────────────────────────────────────────────
    app_title: str = "VideoManager API"
    api_prefix: str = "/api"
    # Comma-separated origins allowed for CORS (player & embed pages)
    cors_origins: str = "*"

    # ── Startup ───────────────────────────────────────────────────────────
    # Set to True (or CLEAR_PENDING_JOBS=1 in .env / env) to discard all
    # interrupted jobs on startup instead of resuming them.
    clear_pending_jobs: bool = False

    # ── Storage ───────────────────────────────────────────────────────────
    data_dir: Path = Path("data")

    @property
    def manifests_dir(self) -> Path:
        return self.data_dir / "manifests"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "index.sqlite"

    @property
    def temp_dir(self) -> Path:
        return self.data_dir / "tmp"

    # ── Chunking ──────────────────────────────────────────────────────────
    # Target fMP4 chunk size; the chunker snaps to the nearest keyframe boundary.
    # Smaller = faster playback start + snappier seeks. Override via CHUNK_SIZE_BYTES.
    chunk_size_bytes: int = 6 * 1024 * 1024  # 6 MB target

    # ── Gofile ────────────────────────────────────────────────────────────
    # The API token from https://gofile.io/myProfile
    gofile_token: Optional[str] = None
    gofile_api_key: Optional[str] = None   # legacy alias – use gofile_token
    # Your account root folder ID (shown in Gofile dashboard)
    gofile_account_id: Optional[str] = None
    gofile_folder_id: Optional[str] = None  # optional sub-folder for uploads

    @property
    def _gofile_token(self) -> Optional[str]:
        """Resolve token from either env var name."""
        return self.gofile_token or self.gofile_api_key

    # ── Filester ──────────────────────────────────────────────────────────
    filester_api_key: Optional[str] = None
    filester_base_url: str = "https://u1.filester.me"
    filester_folder_id: Optional[str] = None

    # ── Cyberfile ─────────────────────────────────────────────────────────
    cyberfile_username: Optional[str] = None
    cyberfile_password: Optional[str] = None
    cyberfile_base_url: str = "https://cyberfile.me/api/v2"
    cyberfile_folder_id: Optional[str] = None

    # ── Pixeldrain ────────────────────────────────────────────────────────
    pixeldrain_api_key: Optional[str] = None
    # Priority in failover order (lower = tried first). Pixeldrain free tier
    # rate-limits range requests; set higher number to deprioritise.
    pixeldrain_priority: int = 3

    # ── Google Drive (service account) ───────────────────────────────────
    gdrive_service_account_json: Optional[Path] = None  # path to JSON key
    gdrive_folder_id: Optional[str] = None  # Drive folder for thumbnails

    # ── Turbo.cr (STUB – no server API) ──────────────────────────────────
    turbocr_enabled: bool = False

    # ── jpg.su (STUB – no server API) ────────────────────────────────────
    jpgsu_enabled: bool = False
    # ── Streamtape ──────────────────────────────────────────────────
    # API Login and API Key from Streamtape User Panel → Account Settings
    streamtape_login: Optional[str] = None
    streamtape_key: Optional[str] = None
    streamtape_folder_id: Optional[str] = None  # optional folder for uploads
    # Max bytes per Streamtape part (hard limit is 15 GB; we use 8 GB for safety)
    streamtape_part_size_bytes: int = 8 * 1024 * 1024 * 1024  # 8 GB

    # ── Buzzheavier ────────────────────────────────────────────────
    # Account ID is the Bearer token (shown on buzzheavier.com/account)
    buzzheavier_account_id: Optional[str] = None
    # Optional directory ID to upload into (get from /api/fs)
    buzzheavier_folder_id: Optional[str] = None

    # ── FileDitch ───────────────────────────────────────────────────
    # Free, no-auth, PERMANENT uploads (new.fileditch.com). No credentials needed.
    # Set FILEDITCH_ENABLED=0 to exclude it from the upload pool.
    fileditch_enabled: bool = True
    # ── Enabled hosts (controls upload targets and failover pool) ─────────
    # Ordered list of host names to try during streaming (lower index = higher priority)
    # FileDitch first: it is free, no-auth and permanent, so it makes the best anchor copy.
    stream_host_priority: List[str] = ["fileditch", "gofile", "filester", "cyberfile", "pixeldrain"]

    # ── Upload strategy ───────────────────────────────────────────────────
    # How many host copies to keep per chunk (durability vs upload speed).
    # The expiry refresher maintains this count over time.
    replica_count: int = 2
    # How many chunks to upload concurrently (pipelining across chunks).
    upload_concurrency: int = 3
    # When True, additionally split the whole video into <=part-size parts and
    # upload them to Streamtape (enables the player's ST streaming mode). Note this
    # re-uploads the entire video on top of the fMP4 chunks, so uploads take longer.
    # Requires STREAMTAPE_LOGIN/KEY. Set STREAMTAPE_ENABLED=0 to disable.
    streamtape_enabled: bool = True

    # ── Expiry refresher (backend/app/refresher) ──────────────────────────
    # Seconds between refresher passes when run in loop mode.
    refresh_interval_sec: int = 6 * 3600
    # Re-upload a copy this many days before its estimated host expiry.
    refresh_margin_days: int = 7
    # When True, the API server also runs the refresher on a schedule in-process
    # (in addition to the standalone `python -m backend.app.refresher`).
    refresh_in_app: bool = True
    # Delay before the first in-app refresher pass (avoids hammering hosts on
    # every dev reload / startup).
    refresh_initial_delay_sec: int = 120


settings = Settings()

# Ensure required directories exist at import time
for _d in (
    settings.data_dir,
    settings.manifests_dir,
    settings.temp_dir,
):
    _d.mkdir(parents=True, exist_ok=True)
