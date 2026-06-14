"""FastAPI application entry point."""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import shutil
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .db import init_db
from .jobs.resume import clear_pending_jobs, resume_pending_jobs
from .routers import uploads, videos, stars, embed
from .streaming.proxy import router as stream_router
from .streaming.streamtape_proxy import router as st_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s – %(message)s",
)
log = logging.getLogger(__name__)


# Locate the built frontend dist directory (works whether running from repo
# root or from backend/)
_HERE = Path(__file__).parent
_DIST = _HERE.parent.parent / "frontend" / "dist"


def _get_player_js() -> str:
    """Read Vite's manifest to find the hashed JS entry filename for the main player."""
    manifest_path = _DIST / ".vite" / "manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text())
            # Prefer the index.html entry (main player, not dashboard)
            if "index.html" in manifest:
                return "/static/" + manifest["index.html"]["file"]
            # Fallback: first entry whose src is index.html
            for _key, info in manifest.items():
                if info.get("isEntry") and info.get("src", "").endswith("index.html"):
                    return "/static/" + info["file"]
        except Exception:
            pass
    # Fallback: glob for any main-*.js in assets/
    matches = list((_DIST / "assets").glob("main-*.js"))
    if matches:
        return "/static/assets/" + matches[0].name
    return "/static/assets/index.js"


async def _run_refresher_loop():
    """Background expiry refresher: wait an initial delay, then loop forever."""
    try:
        await asyncio.sleep(settings.refresh_initial_delay_sec)
        from .refresher import run_forever
        await run_forever()
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("In-app refresher crashed; restart the server to resume it")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    init_db()
    _check_deps()

    # Honour --clear-pending CLI flag OR CLEAR_PENDING_JOBS=1 env var
    want_clear = settings.clear_pending_jobs or "--clear-pending" in sys.argv
    if want_clear:
        n = clear_pending_jobs()
        log.info("Cleared %d pending job(s) on startup (--clear-pending)", n)
    else:
        n = await resume_pending_jobs()
        if n:
            log.info("Resumed %d interrupted job(s)", n)

    # Optionally run the expiry refresher in-process on a schedule (in addition to
    # the standalone `python -m backend.app.refresher`).
    refresher_task = None
    if settings.refresh_in_app:
        refresher_task = asyncio.create_task(_run_refresher_loop())
        log.info("In-app expiry refresher scheduled (every %ds, first pass in %ds)",
                 settings.refresh_interval_sec, settings.refresh_initial_delay_sec)

    log.info("VideoManager API ready")
    yield
    # Shutdown
    if refresher_task is not None:
        refresher_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await refresher_task


def _check_deps():
    missing = [cmd for cmd in ("ffmpeg", "ffprobe") if not shutil.which(cmd)]
    if missing:
        log.warning("Missing system dependencies: %s – chunking will not work", missing)
    else:
        log.info("ffmpeg + ffprobe found ✓")


app = FastAPI(
    title=settings.app_title,
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

# ── CORS ──────────────────────────────────────────────────────────────────────
origins = [o.strip() for o in settings.cors_origins.split(",")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Range", "Content-Length", "X-Source-Host"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
prefix = settings.api_prefix
app.include_router(uploads.router, prefix=prefix)
app.include_router(videos.router, prefix=prefix)
app.include_router(stars.router, prefix=prefix)
app.include_router(stream_router, prefix=prefix)
app.include_router(st_router, prefix=prefix)
app.include_router(embed.router)   # /embed/{id} – no api prefix


# ── Static files (built frontend) ────────────────────────────────────────────
if _DIST.exists():
    # Mount the whole dist/ at /static (used by embed player) AND
    # mount dist/assets/ at /assets so the built HTML's absolute /assets/... refs work.
    app.mount("/static", StaticFiles(directory=str(_DIST)), name="static")
    _DIST_ASSETS = _DIST / "assets"
    if _DIST_ASSETS.exists():
        app.mount("/assets", StaticFiles(directory=str(_DIST_ASSETS)), name="assets")
    log.info("Serving frontend from %s", _DIST)
else:
    log.warning("Frontend dist not found at %s – run 'npm run build' in frontend/", _DIST)


# ── Dashboard SPA ─────────────────────────────────────────────────────────────
@app.get("/dashboard", include_in_schema=False)
async def dashboard():
    """Serve the built dashboard SPA."""
    dashboard_html = _DIST / "dashboard.html"
    if dashboard_html.exists():
        return FileResponse(str(dashboard_html))
    return {"error": "Dashboard not built. Run 'npm run build' in frontend/."}


# ── Health ────────────────────────────────────────────────────────────────────
@app.get("/api/health", tags=["health"])
async def health():
    return {"status": "ok"}
