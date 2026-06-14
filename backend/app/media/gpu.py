"""GPU hardware-acceleration detection for ffmpeg."""
from __future__ import annotations

import asyncio
import shutil
from enum import Enum


class HWAccel(str, Enum):
    nvenc = "nvenc"   # NVIDIA CUDA
    vaapi = "vaapi"   # Intel/AMD VA-API (Linux)
    cpu = "cpu"       # Software fallback


async def detect() -> HWAccel:
    """
    Probe available hardware encoders and return the best one.
    For lossless chunk splitting we use -c copy so no encoder is actually
    invoked, but we still detect GPU presence for potential future use
    (e.g. thumbnail generation or transcoding).
    """
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg not found in PATH")

    # Check NVENC
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-hide_banner", "-encoders",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    encoders = stdout.decode(errors="replace")

    if "h264_nvenc" in encoders or "hevc_nvenc" in encoders:
        return HWAccel.nvenc

    if "h264_vaapi" in encoders or "hevc_vaapi" in encoders:
        return HWAccel.vaapi

    return HWAccel.cpu
