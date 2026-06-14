# CLAUDE.md — VideoManager

## ⚠️ Read the knowledge graph FIRST

Before exploring the codebase, load **`docs/knowledge-graph/graph.json`** (and
`docs/knowledge-graph/README.md` for diagrams). It is a maintained map of every module, its role, exports,
dependencies, the data model, the API surface, the end-to-end flows, and known issues.

**Workflow that saves time/tokens:**
1. Answer "what does X do / where does Y live / what depends on Z" from `graph.json` — do **not** re-read source
   to rediscover this.
2. Open an actual source file **only** when you need exact code to edit it.
3. After editing code, **update `graph.json` in the same change** (see its `meta.maintenance_protocol` and the
   checklist in `docs/knowledge-graph/README.md`). The graph must never drift from the code.

## What this is

Self-hosted FastAPI (Python 3.12) + React/Vite app. It splits a video **losslessly** (`ffmpeg -c copy`, original
quality) into keyframe-aligned **fMP4 chunks**, **fans them out to multiple free file hosts**, writes a per-video
**JSON manifest** (source of truth; SQLite is a derived index), and streams chunks back through a **range-aware
proxy** into a custom **MSE player**. Optional **Streamtape** path uploads whole-video parts served by a separate
stitching proxy.

## Run / build

```bash
# backend (from repo root, .venv active; needs ffmpeg + ffprobe in PATH)
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload
# discard interrupted jobs instead of resuming:  CLEAR_PENDING_JOBS=1 uvicorn ...

# frontend
cd frontend && npm install && npm run build      # emits frontend/dist
```

Key URLs: `/dashboard` (upload + library), `/embed/{video_id}` (player), `/api/docs` (Swagger).
Config lives in `.env` (see `.env.example`). **Never commit `.env`** — it holds host credentials.

## Layout (see graph.json → modules for detail)

- `backend/app/` — `main.py` (app+lifespan), `config.py`, `models/`, `db/`, `jobs/` (queue + upload
  orchestration + resume), `media/` (probe/chunker/splitter), `hosts/` (one adapter per file host + registry),
  `images/` (thumbnail hosts), `storage/` (manifests + SQLite index), `routers/`, `streaming/` (proxy +
  Streamtape proxy).
- `frontend/src/` — `player/` (MSE engine `useChunkStream` + UI `VideoPlayer`), `dashboard/`, `api/`.
- `data/` — `manifests/` (source of truth), `index.sqlite`, `tmp/` (per-job working files, kept for resume).

## Conventions / gotchas

- **Manifests are the source of truth**; SQLite `videos` is rebuilt from them via `storage/index.py`.
- Upload jobs are **checkpointed per phase** (`job_checkpoints` table) and **resume on restart**. Temp files in
  `data/tmp/{video_id}/` are deleted only on success.
- Host adapters implement `FileHostAdapter` (`upload`, `download_range`, `healthy`, `chunk_upload` flag). Missing
  credentials → the adapter is excluded from the pool.
- Match the surrounding code style (no formatter config committed). This is **not** a git repo yet.
- Open performance/durability gaps are tracked in `graph.json → known_issues` (upload fan-out, whole-chunk
  player fetch, no cache, no expiry refresh). Consult them before optimizing so you don't re-derive the analysis.
