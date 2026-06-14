"""Pydantic schemas shared across the application."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


# ── Enums ──────────────────────────────────────────────────────────────────────

class HostName(str, Enum):
    fileditch = "fileditch"
    gofile = "gofile"
    filester = "filester"
    cyberfile = "cyberfile"
    pixeldrain = "pixeldrain"
    turbocr = "turbocr"       # stub
    jpgsu = "jpgsu"           # stub (image host also used here for video)


class LocationStatus(str, Enum):
    ok = "ok"
    failed = "failed"
    pending = "pending"


class JobStatus(str, Enum):
    queued = "queued"
    probing = "probing"
    chunking = "chunking"
    uploading = "uploading"
    finalising = "finalising"
    done = "done"
    error = "error"


# ── Building blocks ────────────────────────────────────────────────────────────

class Resolution(BaseModel):
    width: int
    height: int
    fps: float
    codec: str
    mse_codec: str = "avc1.640028, mp4a.40.2"  # proper MSE SourceBuffer codec string
    bitrate_kbps: Optional[int] = None


class ChunkLocation(BaseModel):
    host: str
    file_id: str
    url: str
    status: LocationStatus = LocationStatus.ok
    # Expiry tracking — populated by the upload job and the refresher. Optional so
    # manifests written before this feature still load.
    uploaded_at: Optional[datetime] = None
    last_verified_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None


class Chunk(BaseModel):
    index: int
    start_sec: float
    end_sec: float
    byte_size: int
    filename: str          # original chunk filename (for reference)
    locations: List[ChunkLocation] = Field(default_factory=list)


class Thumbnail(BaseModel):
    jpgsu: Optional[Dict[str, str]] = None   # {"url": "..."}
    gdrive: Optional[Dict[str, str]] = None  # {"url": "...", "file_id": "..."}


class StreamtapePart(BaseModel):
    """One Streamtape video part (full-copy slice, not an fMP4 chunk)."""
    index: int
    file_id: str           # Streamtape file ID returned after upload
    start_sec: float       # video timestamp where this part begins
    end_sec: float         # video timestamp where this part ends
    byte_size: int         # actual file size after split
    filename: str          # part filename (part_0000.mp4, …)


# ── Top-level manifest ────────────────────────────────────────────────

class Manifest(BaseModel):
    video_id: str
    name: str
    description: str = ""
    duration_sec: float = 0.0
    resolution: Optional[Resolution] = None
    upload_date: datetime = Field(default_factory=datetime.utcnow)
    star_ids: List[str] = Field(default_factory=list)
    thumbnail: Thumbnail = Field(default_factory=Thumbnail)
    chunks: List[Chunk] = Field(default_factory=list)
    streamtape_parts: List[StreamtapePart] = Field(default_factory=list)


# ── Stars ─────────────────────────────────────────────────────────────────────

class Star(BaseModel):
    star_id: str
    name: str
    image_url: Optional[str] = None
    bio: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class StarCreate(BaseModel):
    name: str
    image_url: Optional[str] = None
    bio: Optional[str] = None


class StarUpdate(BaseModel):
    name: Optional[str] = None
    image_url: Optional[str] = None
    bio: Optional[str] = None


# ── Jobs ──────────────────────────────────────────────────────────────────────

class JobProgress(BaseModel):
    job_id: str
    status: JobStatus = JobStatus.queued
    video_id: Optional[str] = None
    message: str = ""
    total_chunks: int = 0
    uploaded_chunks: int = 0
    error: Optional[str] = None
    bytes_per_sec: Optional[float] = None   # current upload throughput
    eta_sec: Optional[int] = None           # estimated seconds to completion
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ── Upload request metadata ────────────────────────────────────────────────────

class VideoMeta(BaseModel):
    name: str
    description: str = ""
    star_ids: List[str] = Field(default_factory=list)


# ── Stream manifest (sent to player) ─────────────────────────────────────────

class StreamChunk(BaseModel):
    index: int
    start_sec: float
    end_sec: float
    byte_size: int
    # Hosts are listed in priority order; player/proxy picks the first live one
    hosts: List[str]


class StreamManifest(BaseModel):
    video_id: str
    name: str
    description: str
    duration_sec: float
    resolution: Optional[Resolution]
    mse_codec: str = "avc1.640028, mp4a.40.2"  # convenience field for the player
    thumbnail: Thumbnail
    star_ids: List[str]
    chunks: List[StreamChunk]
    streamtape_parts: List[StreamtapePart] = Field(default_factory=list)
