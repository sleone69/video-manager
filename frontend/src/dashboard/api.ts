/** Dashboard API client */

const BASE = ''

export type JobStatus =
  | 'queued'
  | 'probing'
  | 'chunking'
  | 'uploading'
  | 'finalising'
  | 'done'
  | 'error'

export interface JobProgress {
  job_id: string
  status: JobStatus
  video_id: string | null
  message: string
  total_chunks: number
  uploaded_chunks: number
  error: string | null
  bytes_per_sec: number | null
  eta_sec: number | null
  created_at: string
  updated_at: string
}

export interface VideoSummary {
  video_id: string
  name: string
  description: string
  duration_sec: number
  width: number | null
  height: number | null
  fps: number | null
  codec: string | null
  upload_date: string
}

export async function listJobs(): Promise<JobProgress[]> {
  const res = await fetch(`${BASE}/api/uploads`)
  if (!res.ok) throw new Error(`listJobs failed: ${res.status}`)
  return res.json()
}

export async function getJob(jobId: string): Promise<JobProgress> {
  const res = await fetch(`${BASE}/api/uploads/${jobId}`)
  if (!res.ok) throw new Error(`getJob failed: ${res.status}`)
  return res.json()
}

export async function listVideos(page = 1, perPage = 50): Promise<VideoSummary[]> {
  const res = await fetch(`${BASE}/api/videos?page=${page}&per_page=${perPage}`)
  if (!res.ok) throw new Error(`listVideos failed: ${res.status}`)
  const body = await res.json()
  // API returns { data: [...], pagination: {...} }
  return Array.isArray(body) ? body : (body.data ?? [])
}

export async function deleteVideo(videoId: string): Promise<void> {
  const res = await fetch(`${BASE}/api/videos/${videoId}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(`deleteVideo failed: ${res.status}`)
}

export async function startUpload(formData: FormData): Promise<{ job_id: string; video_id: string }> {
  const res = await fetch(`${BASE}/api/uploads`, { method: 'POST', body: formData })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`Upload failed: ${res.status} – ${text}`)
  }
  return res.json()
}

export async function cancelJob(jobId: string): Promise<void> {
  const res = await fetch(`${BASE}/api/uploads/${jobId}`, { method: 'DELETE' })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`Cancel failed: ${res.status} – ${text}`)
  }
}
