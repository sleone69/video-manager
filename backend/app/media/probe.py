"""ffprobe-based video metadata extraction."""
from __future__ import annotations

import asyncio
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


@dataclass
class VideoInfo:
    duration_sec: float
    width: int
    height: int
    fps: float
    codec: str
    mse_codec: str       # e.g. 'avc1.640028, mp4a.40.2' for MSE SourceBuffer
    bitrate_kbps: Optional[int]
    size_bytes: int
    # Keyframe timestamps (seconds) – used for chunk boundary planning
    keyframe_times: List[float]


async def probe(path: Path) -> VideoInfo:
    if not shutil.which("ffprobe"):
        raise RuntimeError("ffprobe not found in PATH")

    # General stream info
    proc = await asyncio.create_subprocess_exec(
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_streams",
        "-show_format",
        str(path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {stderr.decode(errors='replace')}")

    info = json.loads(stdout)
    video_stream = next(
        (s for s in info.get("streams", []) if s.get("codec_type") == "video"),
        None,
    )
    if not video_stream:
        raise ValueError(f"No video stream found in {path}")

    fmt = info.get("format", {})
    duration_sec = float(fmt.get("duration") or video_stream.get("duration", 0))
    size_bytes = int(fmt.get("size") or path.stat().st_size)
    bitrate = fmt.get("bit_rate")
    bitrate_kbps = int(bitrate) // 1000 if bitrate else None

    # FPS
    fps_str = video_stream.get("avg_frame_rate") or video_stream.get("r_frame_rate", "0/1")
    try:
        num, den = fps_str.split("/")
        fps = float(num) / float(den) if float(den) else 0.0
    except Exception:
        fps = 0.0

    # Build proper MSE codec string
    audio_stream = next(
        (s for s in info.get("streams", []) if s.get("codec_type") == "audio"), None
    )
    mse_codec = _build_mse_codec(video_stream, audio_stream)

    return VideoInfo(
        duration_sec=duration_sec,
        width=int(video_stream.get("width", 0)),
        height=int(video_stream.get("height", 0)),
        fps=fps,
        codec=video_stream.get("codec_name", "unknown"),
        mse_codec=mse_codec,
        bitrate_kbps=bitrate_kbps,
        size_bytes=size_bytes,
        keyframe_times=[],  # populated separately via extract_keyframes()
    )


def _build_mse_codec(video_stream: dict, audio_stream: Optional[dict]) -> str:
    """
    Build the MIME codec string required for MSE SourceBuffer.addSourceBuffer().

    H.264 avc1 format: avc1.PPCCLL
      PP = profile_idc (hex)
      CC = constraint flags (hex)
      LL = level (hex)
    """
    video_codec = "avc1.640028"  # safe default: High Profile Level 4.0

    codec_name = video_stream.get("codec_name", "")
    if codec_name == "h264":
        profile = video_stream.get("profile", "").lower()
        level = int(video_stream.get("level", 40))  # ffprobe gives 40 for Level 4.0

        profile_map = {
            "high": (0x64, 0x00),
            "high 10": (0x6E, 0x00),
            "main": (0x4D, 0x40),
            "baseline": (0x42, 0xE0),
            "constrained baseline": (0x42, 0xE0),
        }
        profile_idc, constraint = profile_map.get(profile, (0x64, 0x00))
        video_codec = f"avc1.{profile_idc:02X}{constraint:02X}{level:02X}"

    elif codec_name == "hevc":
        video_codec = "hvc1.1.6.L120.90"
    elif codec_name == "vp9":
        video_codec = "vp09.00.50.08"
    elif codec_name == "av1":
        video_codec = "av01.0.08M.08"

    # Audio codec
    audio_codec = ""
    if audio_stream:
        acodec = audio_stream.get("codec_name", "")
        if acodec == "aac":
            audio_codec = "mp4a.40.2"
        elif acodec == "mp3":
            audio_codec = "mp4a.69"
        elif acodec == "opus":
            audio_codec = "opus"
        elif acodec == "ac3":
            audio_codec = "ac-3"

    if audio_codec:
        return f'{video_codec}, {audio_codec}'
    return video_codec


async def extract_keyframes(path: Path) -> List[float]:
    """Public wrapper — call this separately from probe() so the job can
    show its own progress message for this slow step."""
    return await _keyframe_times(path)


async def _keyframe_times(path: Path) -> List[float]:
    """Extract keyframe timestamps from the container packet index (no decode).

    Uses -show_packets which reads packet flags directly from the MP4/MKV index
    without invoking the video decoder — O(total_packets) I/O but zero decode cost.
    Output is streamed line-by-line to avoid buffering 100K+ lines in memory.
    """
    proc = await asyncio.create_subprocess_exec(
        "ffprobe",
        "-v", "quiet",
        "-select_streams", "v:0",
        "-show_packets",
        "-show_entries", "packet=pts_time,flags",
        "-of", "csv=print_section=0",
        str(path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    times: List[float] = []
    assert proc.stdout is not None
    async for raw in proc.stdout:
        line = raw.decode(errors="replace").strip()
        parts = line.split(",")
        # csv: pts_time,flags — keyframe packets have 'K' in flags field
        if len(parts) >= 2 and "K" in parts[1]:
            try:
                times.append(float(parts[0]))
            except ValueError:
                pass
    await proc.wait()
    return times
