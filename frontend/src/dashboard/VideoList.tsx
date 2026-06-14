import React from 'react'
import { type VideoSummary } from './api'

interface Props {
  videos: VideoSummary[]
  onDelete: (videoId: string) => void
}

function fmtDur(sec: number) {
  const h = Math.floor(sec / 3600)
  const m = Math.floor((sec % 3600) / 60)
  const s = Math.floor(sec % 60)
  if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
  return `${m}:${String(s).padStart(2, '0')}`
}

export function VideoList({ videos, onDelete }: Props) {
  if (videos.length === 0) {
    return <div style={styles.empty}>No videos uploaded yet.</div>
  }

  return (
    <div style={styles.list}>
      {videos.map(v => (
        <div key={v.video_id} style={styles.row}>
          <div style={styles.thumb}>
            <a href={`/embed/${v.video_id}`} target="_blank" rel="noreferrer">
              <div style={styles.thumbPlaceholder}>▶</div>
            </a>
          </div>
          <div style={styles.info}>
            <a
              href={`/embed/${v.video_id}`}
              target="_blank"
              rel="noreferrer"
              style={styles.title}
            >
              {v.name}
            </a>
            <div style={styles.subRow}>
              {v.width && v.height && (
                <span style={styles.tag}>{v.width}×{v.height}</span>
              )}
              {v.fps && <span style={styles.tag}>{v.fps.toFixed(2)} fps</span>}
              {v.codec && <span style={styles.tag}>{v.codec.toUpperCase()}</span>}
              <span style={styles.tag}>{fmtDur(v.duration_sec)}</span>
              <span style={styles.tagMuted}>
                {new Date(v.upload_date).toLocaleDateString()}
              </span>
            </div>
            {v.description && (
              <div style={styles.desc}>{v.description}</div>
            )}
          </div>
          <div style={styles.actions}>
            <a
              href={`/embed/${v.video_id}`}
              target="_blank"
              rel="noreferrer"
              style={styles.watchBtn}
            >
              Watch
            </a>
            <button
              style={styles.deleteBtn}
              onClick={() => {
                if (confirm(`Delete "${v.name}"?`)) onDelete(v.video_id)
              }}
            >
              Delete
            </button>
          </div>
        </div>
      ))}
    </div>
  )
}

const styles: Record<string, React.CSSProperties> = {
  list: {
    display: 'flex',
    flexDirection: 'column',
    gap: 10,
  },
  empty: {
    color: '#555',
    fontSize: 14,
    padding: '20px 0',
    textAlign: 'center',
  },
  row: {
    display: 'flex',
    gap: 14,
    background: '#1a1a2e',
    border: '1px solid #2a2a3e',
    borderRadius: 10,
    padding: '12px 14px',
    alignItems: 'flex-start',
  },
  thumb: {
    flexShrink: 0,
  },
  thumbPlaceholder: {
    width: 64,
    height: 40,
    background: '#0f0f1e',
    border: '1px solid #2a2a3e',
    borderRadius: 6,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontSize: 18,
    color: '#4f9aff',
    textDecoration: 'none',
    cursor: 'pointer',
  },
  info: {
    flex: 1,
    minWidth: 0,
    display: 'flex',
    flexDirection: 'column',
    gap: 5,
  },
  title: {
    fontSize: 15,
    fontWeight: 600,
    color: '#e0e0e0',
    textDecoration: 'none',
    whiteSpace: 'nowrap',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
  },
  subRow: {
    display: 'flex',
    gap: 6,
    flexWrap: 'wrap',
  },
  tag: {
    background: '#232340',
    border: '1px solid #2a2a4e',
    borderRadius: 4,
    padding: '1px 6px',
    fontSize: 11,
    color: '#9ab',
  },
  tagMuted: {
    fontSize: 11,
    color: '#555',
  },
  desc: {
    fontSize: 12,
    color: '#666',
    whiteSpace: 'nowrap',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
  },
  actions: {
    display: 'flex',
    flexDirection: 'column',
    gap: 6,
    alignItems: 'flex-end',
    flexShrink: 0,
  },
  watchBtn: {
    background: '#4f9aff',
    color: '#fff',
    border: 'none',
    borderRadius: 6,
    padding: '5px 12px',
    fontSize: 12,
    fontWeight: 600,
    textDecoration: 'none',
    cursor: 'pointer',
  },
  deleteBtn: {
    background: 'transparent',
    color: '#ef4444',
    border: '1px solid #3a1212',
    borderRadius: 6,
    padding: '4px 10px',
    fontSize: 12,
    cursor: 'pointer',
  },
}
