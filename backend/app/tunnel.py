"""Cloudflare Tunnel integration.

Exposes the locally-running app over a public HTTPS URL using `cloudflared`,
started from the FastAPI lifespan right after the backend boots.

Modes
-----
* Quick tunnel (default, free, no account): ``cloudflared tunnel --url <target>``
  → a random ``https://<name>.trycloudflare.com`` URL, surfaced at startup and via
  ``GET /api/tunnel``.
* Named tunnel: set ``CLOUDFLARE_TUNNEL_TOKEN`` → ``cloudflared tunnel run --token …``
  → uses the hostname configured in the Cloudflare Zero Trust dashboard
  (requires a Cloudflare account + a domain).

Requires the ``cloudflared`` binary in PATH (or set ``CLOUDFLARED_BIN``). If it is
missing, a clear warning is logged and the server continues normally.

⚠ Security: this app has no authentication — a tunnel makes the dashboard
(uploads/deletes) publicly reachable. Disable with ``CLOUDFLARE_TUNNEL_ENABLED=false``.
"""
from __future__ import annotations

import asyncio
import logging
import re
import shutil
from typing import Optional

from .config import settings

log = logging.getLogger(__name__)

_TRYCLOUDFLARE_RE = re.compile(r"https://[-a-z0-9]+\.trycloudflare\.com")

# Live tunnel state (read by the /api/tunnel endpoint).
_state = {"enabled": False, "running": False, "mode": None, "url": None}


def get_tunnel_status() -> dict:
    return dict(_state)


async def _read_output(proc: "asyncio.subprocess.Process", named: bool) -> None:
    """Drain cloudflared's merged output; surface the public URL when it appears."""
    assert proc.stdout is not None
    try:
        async for raw in proc.stdout:
            line = raw.decode(errors="replace").rstrip()
            if not line:
                continue
            if not named and _state["url"] is None:
                m = _TRYCLOUDFLARE_RE.search(line)
                if m:
                    _state["url"] = m.group(0)
                    log.info("─" * 72)
                    log.info("Cloudflare tunnel is live: %s", m.group(0))
                    log.info("  dashboard: %s/dashboard", m.group(0))
                    log.info("─" * 72)
            # cloudflared tags its own level (INF/WRN/ERR). Only surface real
            # errors; INF/WRN (incl. benign ICMP/UDP-buffer notices) go to debug.
            if re.search(r"\bERR\b", line) or "level=error" in line.lower():
                log.warning("cloudflared: %s", line)
            else:
                log.debug("cloudflared: %s", line)
    except Exception:
        pass
    finally:
        _state["running"] = False


async def start_tunnel() -> Optional["asyncio.subprocess.Process"]:
    """Start cloudflared if enabled. Returns the process, or None if not started."""
    _state.update(enabled=settings.cloudflare_tunnel_enabled, running=False, mode=None, url=None)
    if not settings.cloudflare_tunnel_enabled:
        return None

    binary = shutil.which(settings.cloudflared_bin) or shutil.which("cloudflared")
    if not binary:
        log.warning(
            "Cloudflare tunnel enabled but `cloudflared` not found in PATH. Install it "
            "(https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/) "
            "or set CLOUDFLARE_TUNNEL_ENABLED=false."
        )
        return None

    token = settings.cloudflare_tunnel_token
    if token:
        cmd = [binary, "tunnel", "--no-autoupdate", "run", "--token", token]
        named = True
        log.info("Starting named Cloudflare tunnel…")
    else:
        cmd = [binary, "tunnel", "--no-autoupdate", "--url", settings.cloudflare_tunnel_target]
        named = False
        log.info("Starting Cloudflare quick tunnel → %s …", settings.cloudflare_tunnel_target)

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,  # merge so we catch the URL wherever it logs
        )
    except Exception as exc:
        log.warning("Failed to start cloudflared: %s", exc)
        return None

    _state.update(running=True, mode="named" if named else "quick")
    asyncio.create_task(_read_output(proc, named))
    return proc


async def stop_tunnel(proc: Optional["asyncio.subprocess.Process"]) -> None:
    _state.update(running=False)
    if proc is None or proc.returncode is not None:
        return
    try:
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
    except ProcessLookupError:
        pass
    log.info("Cloudflare tunnel stopped")
