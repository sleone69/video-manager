"""Embed router — serves the standalone player iframe page."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from ..storage import load as load_manifest

router = APIRouter(prefix="/embed", tags=["embed"])

_PLAYER_TEMPLATE = """\
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>{name}</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  html,body{{width:100%;height:100%;background:#000;overflow:hidden}}
  #root{{width:100%;height:100%}}
</style>
</head>
<body>
<div id="root"></div>
<script>
  window.__VM_CONFIG__ = {{
    apiBase: "{api_base}",
    videoId: "{video_id}",
    embedMode: true
  }};
</script>
<script type="module" src="{player_js}"></script>
</body>
</html>
"""


def _player_js() -> str:
    """Dynamically resolve the hashed Vite bundle filename."""
    try:
        from ..main import _get_player_js  # noqa: PLC0415
        return _get_player_js()
    except Exception:
        return "/static/assets/index.js"


@router.get("/{video_id}", response_class=HTMLResponse)
async def embed_player(video_id: str):
    manifest = load_manifest(video_id)
    if not manifest:
        raise HTTPException(status_code=404, detail="Video not found")

    html = _PLAYER_TEMPLATE.format(
        name=manifest.name,
        video_id=video_id,
        api_base="",  # relative — works for same-origin
        player_js=_player_js(),
    )
    return HTMLResponse(content=html)
