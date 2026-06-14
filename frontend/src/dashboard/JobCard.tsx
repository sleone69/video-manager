import React, { useEffect, useRef, useState } from 'react'
import { cancelJob, getJob, type JobProgress, type JobStatus } from './api'

interface Props {
  initial: JobProgress
}

const STATUS_COLOR: Record<JobStatus, string> = {
  queued: '#888',
  probing: '#a78bfa',
  chunking: '#f59e0b',
  uploading: '#3b82f6',
  finalising: '#06b6d4',
  done: '#22c55e',
  error: '#ef4444',
}

const STATUS_LABEL: Record<JobStatus, string> = {
  queued: 'Queued',
  probing: 'Probing',
  chunking: 'Chunking',
  uploading: 'Uploading',
  finalising: 'Finalising',
  done: 'Done',
  error: 'Error',
}

function fmt(iso: string) {
  return new Date(iso).toLocaleTimeString()
}

function fmtSpeed(bps: number): string {
  if (bps >= 1_048_576) return `${(bps / 1_048_576).toFixed(1)} MB/s`
  if (bps >= 1024) return `${(bps / 1024).toFixed(0)} KB/s`
  return `${bps.toFixed(0)} B/s`
}

function fmtEta(sec: number): string {
  if (sec < 60) return `${sec}s`
  if (sec < 3600) return `${Math.floor(sec / 60)}m ${sec % 60}s`
  return `${Math.floor(sec / 3600)}h ${Math.floor((sec % 3600) / 60)}m`
}

export function JobCard({ initial }: Props) {
  const [job, setJob] = useState<JobProgress>(initial)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const [cancelling, setCancelling] = useState(false)
  const done = job.status === 'done' || job.status === 'error'

  useEffect(() => {
    if (done) return
    const poll = async () => {
      try {
        const fresh = await getJob(job.job_id)
        setJob(fresh)
        if (fresh.status !== 'done' && fresh.status !== 'error') {
          timerRef.current = setTimeout(poll, 1500)
        }
      } catch {
        timerRef.current = setTimeout(poll, 3000)
      }
    }
    timerRef.current = setTimeout(poll, 1500)
    return () => { if (timerRef.current) clearTimeout(timerRef.current) }
  }, [job.job_id, done])

  // Sync when parent passes a refreshed initial (e.g. from list_jobs)
  useEffect(() => {
    if (initial.updated_at > job.updated_at) setJob(initial)
  }, [initial])

  const handleCancel = async () => {
    if (!window.confirm('Cancel this upload job?')) return
    setCancelling(true)
    try {
      await cancelJob(job.job_id)
      setJob(j => ({ ...j, status: 'error', error: 'Cancelled by user' }))
    } catch (e: any) {
      alert(e.message)
    } finally {
      setCancelling(false)
    }
  }

  const pct = job.total_chunks > 0
    ? Math.round((job.uploaded_chunks / job.total_chunks) * 100)
    : (job.status === 'done' ? 100 : 0)

  const barColor = STATUS_COLOR[job.status]

  return (
    <div style={styles.card}>
      <div style={styles.cardTop}>
        <span
          style={{ ...styles.badge, background: barColor + '22', color: barColor, borderColor: barColor + '55' }}
        >
          {STATUS_LABEL[job.status]}
        </span>
        <span style={styles.meta}>
          {job.video_id && (
            <a
              href={`/embed/${job.video_id}`}
              target="_blank"
              rel="noreferrer"
              style={styles.link}
            >
              Watch
            </a>
          )}
          {!done && (
            <button
              onClick={handleCancel}
              disabled={cancelling}
              style={styles.cancelBtn}
              title="Cancel job"
            >
              {cancelling ? '⋯' : '✕ Cancel'}
            </button>
          )}
          <span style={styles.time}>{fmt(job.created_at)}</span>
        </span>
      </div>

      <div style={styles.message}>{job.message || STATUS_LABEL[job.status]}</div>

      {/* Progress bar */}
      <div style={styles.barTrack}>
        <div
          style={{
            ...styles.barFill,
            width: `${pct}%`,
            background: barColor,
            transition: 'width 0.4s ease',
          }}
        />
      </div>

      <div style={styles.pctRow}>
        <span>
          {job.total_chunks > 0
            ? `${job.uploaded_chunks} / ${job.total_chunks} chunks (${pct}%)`
            : `${pct}%`}
        </span>
        <span style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
          {job.status === 'uploading' && job.bytes_per_sec != null && (
            <span style={{ color: '#4f9aff', fontWeight: 600 }}>
              {fmtSpeed(job.bytes_per_sec)}
            </span>
          )}
          {job.status === 'uploading' && job.eta_sec != null && (
            <span style={{ color: '#94a3b8' }}>
              ETA {fmtEta(job.eta_sec)}
            </span>
          )}
          {!done && <span style={styles.spinner}>⟳</span>}
        </span>
      </div>

      {job.error && <div style={styles.errMsg}>{job.error}</div>}

      <div style={styles.jobId}>Job {job.job_id.slice(0, 8)}…</div>
    </div>
  )
}

const styles: Record<string, React.CSSProperties> = {
  card: {
    background: '#1a1a2e',
    border: '1px solid #2a2a3e',
    borderRadius: 10,
    padding: '14px 16px',
    display: 'flex',
    flexDirection: 'column',
    gap: 8,
  },
  cardTop: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  badge: {
    fontSize: 11,
    fontWeight: 700,
    padding: '2px 8px',
    borderRadius: 99,
    border: '1px solid',
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  meta: {
    display: 'flex',
    gap: 10,
    alignItems: 'center',
  },
  link: {
    color: '#4f9aff',
    fontSize: 12,
    textDecoration: 'none',
  },
  cancelBtn: {
    background: 'none',
    border: '1px solid #ef444455',
    color: '#ef4444',
    borderRadius: 5,
    fontSize: 11,
    fontWeight: 600,
    padding: '2px 8px',
    cursor: 'pointer',
  },
  time: {
    fontSize: 11,
    color: '#666',
  },
  message: {
    fontSize: 13,
    color: '#ccc',
    minHeight: 18,
  },
  barTrack: {
    height: 6,
    background: '#2a2a3e',
    borderRadius: 99,
    overflow: 'hidden',
  },
  barFill: {
    height: '100%',
    borderRadius: 99,
    minWidth: 4,
  },
  pctRow: {
    display: 'flex',
    justifyContent: 'space-between',
    fontSize: 12,
    color: '#888',
  },
  spinner: {
    display: 'inline-block',
    animation: 'spin 1s linear infinite',
    color: '#4f9aff',
    fontSize: 14,
  },
  errMsg: {
    background: '#3a0000',
    border: '1px solid #6b0000',
    color: '#ff6060',
    fontSize: 12,
    padding: '6px 10px',
    borderRadius: 6,
  },
  jobId: {
    fontSize: 10,
    color: '#444',
  },
}
