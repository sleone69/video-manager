# VideoManager

A self-hosted video manager that splits videos into lossless fMP4 chunks, uploads them to multiple file hosts simultaneously, and streams them back via an MSE-based YouTube-style player.

## Requirements

- Python 3.12+
- Node.js 18+
- ffmpeg + ffprobe in PATH

```bash
# Ubuntu / Debian
sudo apt install ffmpeg
```

---

## Setup

### 1. Clone and create a virtual environment

```bash
git clone <repo>
cd video-manager
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install Python dependencies

```bash
pip install -r backend/requirements.txt
```

### 3. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and fill in your credentials:

| Variable | Description |
|---|---|
| `PIXELDRAIN_API_KEY` | Pixeldrain API key |
| `FILESTER_API_KEY` | Filester API key |
| `CYBERFILE_USERNAME` | Cyberfile username |
| `CYBERFILE_PASSWORD` | Cyberfile password |
| `GOFILE_TOKEN` | Gofile API token (optional) |
| `GOFILE_ACCOUNT_ID` | Gofile account ID (optional) |
| `STREAMTAPE_LOGIN` | Streamtape API/FTP username (from Account Settings) |
| `STREAMTAPE_KEY` | Streamtape API/FTP password (from Account Settings) |
| `STREAMTAPE_FOLDER_ID` | Optional Streamtape folder to upload parts into |
| `BUZZHEAVIER_ACCOUNT_ID` | Buzzheavier account ID (used as Bearer token) |
| `BUZZHEAVIER_FOLDER_ID` | Optional Buzzheavier directory ID to upload into |
| `STREAM_HOST_PRIORITY` | JSON array, e.g. `["pixeldrain","filester","cyberfile"]` |
| `CHUNK_SIZE_BYTES` | fMP4 chunk size in bytes (default `6291456` = 6 MB; 4–8 MB recommended) |
| `REPLICA_COUNT` | Host copies kept per chunk (default `2`). Fewer = faster uploads; the refresher maintains this count |
| `UPLOAD_CONCURRENCY` | How many chunks upload at once (default `3`) |
| `UPLOAD_PART_SIZE_BYTES` | Browser→backend upload part size (default `50331648` = 48 MB; kept under Cloudflare's tunnel cap) |
| `STREAMTAPE_ENABLED` | `true` to also upload whole-video Streamtape parts (default `false`; slow — re-uploads the whole video) |
| `STREAMTAPE_PART_SIZE_BYTES` | Max bytes per Streamtape part (default `8589934592` = 8 GB) |
| `REFRESH_INTERVAL_SEC` | Expiry-refresher loop interval (default `21600` = 6 h) |
| `REFRESH_MARGIN_DAYS` | Re-upload this many days before estimated host expiry (default `7`) |
| `CLOUDFLARE_TUNNEL_ENABLED` | Auto-start a `cloudflared` tunnel at boot to expose the app publicly (default `true`) |
| `CLOUDFLARE_TUNNEL_TARGET` | Local address the tunnel forwards to (default `http://127.0.0.1:8000`) |
| `CLOUDFLARE_TUNNEL_TOKEN` | Optional named-tunnel token (stable hostname); blank = ephemeral quick tunnel |

### 4. Build the frontend

```bash
cd frontend
npm install
npm run build
cd ..
```

---

## Running

Always run from the **project root** (`video-manager/`) with the virtual environment active.

```bash
source .venv/bin/activate
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload
```

| URL | Description |
|---|---|
| `http://localhost:8000/dashboard` | Upload dashboard |
| `http://localhost:8000/embed/{videoId}` | Video player |
| `http://localhost:8000/docs` | Interactive API docs |

### Startup flags

```bash
# Discard all interrupted jobs instead of resuming them
CLEAR_PENDING_JOBS=1 uvicorn backend.app.main:app --reload
```

---

## Uploading a video

### Via dashboard

Open `http://localhost:8000/dashboard`, drag-and-drop a video, fill in the name, and click **Upload**.

### Via API

```bash
curl -X POST http://localhost:8000/api/uploads \
  -F "video=@/path/to/video.mp4" \
  -F "name=My Video" \
  -F "description=Optional description" \
  -F "thumbnail=@/path/to/thumb.jpg"
```

Response:
```json
{ "job_id": "abc123", "video_id": "def456" }
```

Poll upload progress:
```bash
curl http://localhost:8000/api/uploads/abc123
```

Cancel an upload:
```bash
curl -X DELETE http://localhost:8000/api/uploads/abc123
```

---

## How it works

### Standard chunk streaming (MSE)

1. The video is saved to `data/tmp/{videoId}/`
2. ffprobe extracts keyframe timestamps and bitrate
3. ffmpeg splits the video into small lossless fMP4 chunks at keyframe boundaries (`CHUNK_SIZE_BYTES`)
4. Each chunk is uploaded to a **`REPLICA_COUNT`-host replica set** (default 2), and multiple chunks upload concurrently (`UPLOAD_CONCURRENCY`)
5. A JSON manifest is written to `data/manifests/{videoId}.json` and indexed in `data/index.sqlite`
6. The player fetches the manifest, then **streams each chunk and appends slices progressively** via MSE — so playback starts before a whole chunk downloads — keeping 3 chunks prefetched and cached in memory so seeks never re-download

### Streamtape streaming (optional)

When `STREAMTAPE_ENABLED=true` (and `STREAMTAPE_LOGIN` / `STREAMTAPE_KEY` are set), an additional upload step runs after the standard chunk upload. **It is off by default** because it re-uploads the entire video as parts on top of the fMP4 chunks:

1. The original video is split into ≤8 GB regular MP4 parts at keyframe boundaries
2. Each part is uploaded sequentially to Streamtape and its `file_id` is stored in the manifest
3. The backend exposes a virtual stream proxy at `/api/stream/st/{videoId}` that stitches all parts into one continuous seekable HTTP stream using download tickets + Range requests on Streamtape's CDN

### Supported hosts

| Host | Upload | Streaming | Notes |
|---|---|---|---|
| FileDitch | ✅ | ✅ Range requests | **No auth, permanent retention** — used as the priority anchor copy |
| Pixeldrain | ✅ | ✅ Range requests | Recommended for streaming |
| Filester | ✅ | ✅ CDN range requests | |
| Cyberfile | ✅ | ✅ Download token | |
| Gofile | ✅ | ⚠ Limited | No range support without premium |
| Streamtape | ✅ Parts | ✅ Backend proxy | Full-video parts, not chunks |
| Buzzheavier | ✅ | ✅ CDN range | Upload server may be geo-restricted |

---

## Player: Streamtape mode

The player has two streaming modes, switchable at runtime:

| Mode | Label | How it works |
|---|---|---|
| **MSE** (default) | *(no label)* | Backend proxies 30 MB fMP4 chunks through configured hosts; seeks load chunks on demand |
| **Streamtape** | **ST** button | `<video src>` points at `/api/stream/st/{videoId}`; browser sends Range requests; backend maps byte offsets to Streamtape parts via download tickets |

### How to switch

1. Open the player at `http://localhost:8000/embed/{videoId}`
2. Hover over the video to reveal the controls bar
3. If the video was uploaded with Streamtape credentials active, an **ST** button appears in the bottom-right of the controls (next to the quality badge and fullscreen button)
4. Click **ST** to switch to Streamtape streaming — the button turns orange to indicate the active mode
5. Click **ST** again to switch back to standard MSE chunk streaming

> **Note:** The **ST** button is only shown when the video's manifest contains Streamtape parts (`streamtape_parts` list is non-empty). Videos uploaded before Streamtape credentials were configured will not show the button.

### Seeking in Streamtape mode

Seeking works natively — the browser sends `Range: bytes=X-Y` headers to the proxy. The proxy:
1. Calculates which Streamtape part the requested byte offset falls in
2. Fetches a download ticket for that part
3. Makes a range request on the CDN URL returned by the ticket
4. Streams the bytes back to the browser

Ticket URLs are cached per part so rapid seeks within the same part do not regenerate tickets. If the CDN URL expires, the cache is invalidated and the ticket is refreshed automatically.

### Resume on restart

Interrupted uploads are automatically resumed on the next server start. Each phase (probe → chunk → per-chunk upload → Streamtape parts → thumbnail) is checkpointed to SQLite. To discard all pending jobs instead, start with `CLEAR_PENDING_JOBS=1`.

---

## Keeping uploads alive (expiry refresher)

Free hosts delete files that go untouched (e.g. **Filester after 45 days idle**; Gofile/Pixeldrain reap inactive
files). The **expiry refresher** is a standalone program that prevents link rot. For each chunk copy it:

1. **Verifies** the link by fetching 1 byte — this detects dead links *and* resets the host's idle-deletion timer
   (a keep-alive).
2. **Repairs** under-replicated chunks: if a chunk has fewer than `REPLICA_COUNT` live copies, it re-downloads the
   chunk from a surviving copy and re-uploads it to another host, **rewriting the URL/file-id in the manifest** so
   the player immediately uses the fresh copy.

Run it as a separate process (from the project root, venv active):

```bash
# one pass over all videos
python -m backend.app.refresher --once

# run forever, one pass every 6h (REFRESH_INTERVAL_SEC)
python -m backend.app.refresher

# preview actions without uploading, or target one video
python -m backend.app.refresher --once --dry-run
python -m backend.app.refresher --video <videoId>
```

Schedule it with cron/systemd, e.g. every 6 hours:

```cron
0 */6 * * * cd /path/to/video-manager && .venv/bin/python -m backend.app.refresher --once >> data/refresher.log 2>&1
```

> Tune host expiry windows in `backend/app/refresher/policy.py`. Set the keep-alive interval comfortably shorter
> than the shortest host window (e.g. run every few days for Gofile's ~10-day window).

---

## Public access (Cloudflare Tunnel)

The app can expose itself over a public HTTPS URL using **Cloudflare Tunnel**, started automatically right after
the backend boots — no separate process to manage.

**Prerequisite:** install the `cloudflared` binary and make sure it's in `PATH`:

```bash
curl -fsSL https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 \
  -o /usr/local/bin/cloudflared && sudo chmod +x /usr/local/bin/cloudflared
```

On startup the server logs the public URL (also available at `GET /api/tunnel`):

```
Cloudflare tunnel is live: https://<random-words>.trycloudflare.com
  dashboard: https://<random-words>.trycloudflare.com/dashboard
```

- **Quick tunnel** (default, free, no account): leave `CLOUDFLARE_TUNNEL_TOKEN` blank — you get a fresh random
  `*.trycloudflare.com` URL each run.
- **Named tunnel** (stable hostname): set `CLOUDFLARE_TUNNEL_TOKEN` from the Cloudflare Zero Trust dashboard.
- Disable with `CLOUDFLARE_TUNNEL_ENABLED=false`.

**Uploads through the tunnel** work out of the box: Cloudflare's free plan caps request bodies at ~100 MB, so the
dashboard uploads in **chunks** — it slices the file into `UPLOAD_PART_SIZE_BYTES` (48 MB) parts, uploads each as
its own request, and the backend reassembles them before processing. Multi-GB videos upload fine over the tunnel.
(The single-shot `POST /api/uploads` is still available for local/CLI use.)

> ⚠ **Security:** the app has **no authentication** — a tunnel makes the dashboard (uploads/deletes) reachable
> by anyone who has the URL. Only enable it when you intend public access, or put auth in front first.

---

## Project structure

```
video-manager/
├── backend/
│   ├── app/
│   │   ├── main.py          # FastAPI app, lifespan, static files
│   │   ├── tunnel.py        # Cloudflare Tunnel (auto-expose at startup)
│   │   ├── config.py        # Settings from .env
│   │   ├── models/          # Pydantic models (Manifest, StreamtapePart, …)
│   │   ├── db/              # SQLite schema, checkpoints
│   │   ├── hosts/           # File host adapters (pixeldrain, filester, streamtape, …)
│   │   ├── jobs/            # Async queue, upload orchestration, resume
│   │   ├── media/           # ffprobe, ffmpeg chunker, video splitter (for ST parts)
│   │   ├── routers/         # FastAPI route handlers
│   │   ├── refresher/       # Standalone expiry monitor (verify keep-alive + re-upload)
│   │   ├── storage/         # Manifest save/load, SQLite index
│   │   └── streaming/       # Chunk proxy + Streamtape virtual-stream proxy
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── player/          # MSE player (VideoPlayer, useChunkStream, SeekBar)
│   │   └── dashboard/       # Upload dashboard (JobCard, VideoList, UploadForm)
│   ├── index.html           # Player entry
│   ├── dashboard.html       # Dashboard entry
│   └── vite.config.ts
├── data/
│   ├── manifests/           # Per-video JSON manifests
│   ├── index.sqlite         # Video index + job state
│   └── tmp/                 # Temp files during upload (auto-cleaned on success)
└── .env                     # Your credentials (never commit this)
```
