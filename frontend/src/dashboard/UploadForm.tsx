import React, { useCallback, useRef, useState } from 'react'
import { type JobProgress } from './api'

interface Props {
  onJobStarted: (job: JobProgress) => void
}

/** POST with XHR so we get upload progress events. */
function xhrUpload(
  url: string,
  formData: FormData,
  onProgress: (pct: number, loaded: number, total: number) => void,
): Promise<{ job_id: string; video_id: string }> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', url)
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress((e.loaded / e.total) * 100, e.loaded, e.total)
    }
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(JSON.parse(xhr.responseText))
      } else {
        reject(new Error(`Upload failed: ${xhr.status} – ${xhr.responseText}`))
      }
    }
    xhr.onerror = () => reject(new Error('Network error during upload'))
    xhr.send(formData)
  })
}

export function UploadForm({ onJobStarted }: Props) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [videoFile, setVideoFile] = useState<File | null>(null)
  const [thumbnailFile, setThumbnailFile] = useState<File | null>(null)
  const [uploading, setUploading] = useState(false)
  const [uploadPct, setUploadPct] = useState(0)
  const [uploadLoaded, setUploadLoaded] = useState(0)
  const [uploadTotal, setUploadTotal] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [drag, setDrag] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setDrag(false)
    const file = e.dataTransfer.files[0]
    if (file) setVideoFile(file)
  }, [])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!videoFile || !name.trim()) return
    setError(null)
    setUploading(true)
    setUploadPct(0)
    setUploadLoaded(0)
    setUploadTotal(videoFile.size)
    try {
      const fd = new FormData()
      fd.append('video', videoFile)
      fd.append('name', name.trim())
      fd.append('description', description.trim())
      if (thumbnailFile) fd.append('thumbnail', thumbnailFile)
      const { job_id } = await xhrUpload(
        '/api/uploads',
        fd,
        (pct, loaded, total) => {
          setUploadPct(pct)
          setUploadLoaded(loaded)
          setUploadTotal(total)
        },
      )
      // bootstrap the job card immediately
      onJobStarted({
        job_id,
        status: 'queued',
        video_id: null,
        message: 'Queued',
        total_chunks: 0,
        uploaded_chunks: 0,
        error: null,
        bytes_per_sec: null,
        eta_sec: null,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      })
      setName('')
      setDescription('')
      setVideoFile(null)
      setThumbnailFile(null)
      if (fileRef.current) fileRef.current.value = ''
    } catch (err: any) {
      setError(err.message ?? 'Unknown error')
    } finally {
      setUploading(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} style={styles.form}>
      <h2 style={styles.sectionTitle}>Upload Video</h2>

      {/* Drop zone */}
      <div
        style={{ ...styles.dropZone, ...(drag ? styles.dropZoneActive : {}) }}
        onDragOver={e => { e.preventDefault(); setDrag(true) }}
        onDragLeave={() => setDrag(false)}
        onDrop={handleDrop}
        onClick={() => fileRef.current?.click()}
      >
        {videoFile ? (
          <span style={styles.fileName}>📁 {videoFile.name} ({(videoFile.size / 1e6).toFixed(1)} MB)</span>
        ) : (
          <span style={styles.dropHint}>Drop video file here or <u>click to browse</u></span>
        )}
        <input
          ref={fileRef}
          type="file"
          accept="video/*"
          style={{ display: 'none' }}
          onChange={e => setVideoFile(e.target.files?.[0] ?? null)}
        />
      </div>

      <label style={styles.label}>
        Name *
        <input
          style={styles.input}
          value={name}
          onChange={e => setName(e.target.value)}
          placeholder="Video title"
          required
        />
      </label>

      <label style={styles.label}>
        Description
        <textarea
          style={{ ...styles.input, height: 64, resize: 'vertical' }}
          value={description}
          onChange={e => setDescription(e.target.value)}
          placeholder="Optional description"
        />
      </label>

      <label style={styles.label}>
        Thumbnail (optional)
        <input
          style={styles.input}
          type="file"
          accept="image/*"
          onChange={e => setThumbnailFile(e.target.files?.[0] ?? null)}
        />
      </label>

      {error && <div style={styles.error}>{error}</div>}

      <button
        style={{ ...styles.btn, opacity: uploading || !videoFile || !name.trim() ? 0.5 : 1 }}
        type="submit"
        disabled={uploading || !videoFile || !name.trim()}
      >
        {uploading
          ? uploadPct < 100
            ? `Uploading… ${uploadPct.toFixed(0)}% (${(uploadLoaded / 1e6).toFixed(1)} / ${(uploadTotal / 1e6).toFixed(1)} MB)`
            : 'Processing…'
          : 'Start Upload'}
      </button>
    </form>
  )
}

const styles: Record<string, React.CSSProperties> = {
  form: {
    display: 'flex',
    flexDirection: 'column',
    gap: 12,
  },
  sectionTitle: {
    margin: '0 0 4px',
    fontSize: 18,
    fontWeight: 600,
    color: '#e0e0e0',
  },
  dropZone: {
    border: '2px dashed #444',
    borderRadius: 8,
    padding: '24px 16px',
    textAlign: 'center',
    cursor: 'pointer',
    color: '#aaa',
    transition: 'border-color 0.2s, background 0.2s',
    background: '#1e1e1e',
  },
  dropZoneActive: {
    borderColor: '#4f9aff',
    background: '#162033',
  },
  dropHint: { fontSize: 14 },
  fileName: { fontSize: 14, color: '#7dcfff' },
  label: {
    display: 'flex',
    flexDirection: 'column',
    gap: 4,
    fontSize: 13,
    color: '#bbb',
  },
  input: {
    background: '#1e1e1e',
    border: '1px solid #333',
    borderRadius: 6,
    color: '#e0e0e0',
    padding: '7px 10px',
    fontSize: 13,
    outline: 'none',
  },
  error: {
    background: '#3a1212',
    border: '1px solid #8b2222',
    borderRadius: 6,
    color: '#ff7070',
    padding: '8px 12px',
    fontSize: 13,
  },
  btn: {
    background: '#4f9aff',
    color: '#fff',
    border: 'none',
    borderRadius: 6,
    padding: '10px 20px',
    fontSize: 14,
    fontWeight: 600,
    cursor: 'pointer',
    transition: 'opacity 0.2s',
  },
}
