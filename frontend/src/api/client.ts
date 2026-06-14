/** Backend API client. */

const BASE = (window as any).__VM_CONFIG__?.apiBase ?? ''

export interface Resolution {
  width: number
  height: number
  fps: number
  codec: string
  bitrate_kbps?: number
}

export interface StreamChunk {
  index: number
  start_sec: number
  end_sec: number
  byte_size: number
  hosts: string[]
}

export interface StreamtapePart {
  index: number
  file_id: string
  start_sec: number
  end_sec: number
  byte_size: number
  filename: string
}

export interface Thumbnail {
  gdrive?: { url: string; file_id: string }
  jpgsu?: { url: string }
}

export interface StreamManifest {
  video_id: string
  name: string
  description: string
  duration_sec: number
  resolution: Resolution | null
  mse_codec: string          // e.g. 'avc1.640028, mp4a.40.2'
  thumbnail: Thumbnail
  star_ids: string[]
  chunks: StreamChunk[]
  streamtape_parts: StreamtapePart[]
}

export async function fetchManifest(videoId: string): Promise<StreamManifest> {
  const res = await fetch(`${BASE}/api/stream/${videoId}/manifest`)
  if (!res.ok) throw new Error(`Manifest fetch failed: ${res.status}`)
  return res.json()
}

/** Build the URL for a chunk byte-range fetch (backend proxy). */
export function chunkUrl(videoId: string, chunkIndex: number): string {
  return `${BASE}/api/stream/${videoId}/chunk/${chunkIndex}`
}

/** Build the URL for the Streamtape virtual stream proxy (browser Range requests). */
export function streamtapeProxyUrl(videoId: string): string {
  return `${BASE}/api/stream/st/${videoId}`
}
