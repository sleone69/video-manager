import React, { useCallback, useEffect, useRef, useState } from 'react'
import { listJobs, listVideos, deleteVideo, type JobProgress, type VideoSummary } from './api'
import { UploadForm } from './UploadForm'
import { JobCard } from './JobCard'
import { VideoList } from './VideoList'

export function Dashboard() {
  const [jobs, setJobs] = useState<JobProgress[]>([])
  const [videos, setVideos] = useState<VideoSummary[]>([])
  const [loadingVideos, setLoadingVideos] = useState(true)
  const [videoError, setVideoError] = useState<string | null>(null)
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const fetchJobs = useCallback(async () => {
    try {
      const fresh = await listJobs()
      setJobs(fresh)
    } catch {
      // non-critical
    }
  }, [])

  const fetchVideos = useCallback(async () => {
    setVideoError(null)
    try {
      const vids = await listVideos()
      setVideos(vids)
    } catch (err: any) {
      setVideoError(err.message)
    } finally {
      setLoadingVideos(false)
    }
  }, [])

  // Poll jobs every 2s while any are active
  useEffect(() => {
    fetchJobs()
    fetchVideos()

    const tick = async () => {
      await fetchJobs()
      const active = jobs.some(j => j.status !== 'done' && j.status !== 'error')
      pollRef.current = setTimeout(tick, active ? 1500 : 4000)
    }
    pollRef.current = setTimeout(tick, 2000)
    return () => { if (pollRef.current) clearTimeout(pollRef.current) }
  }, [])

  // Re-fetch videos after any job transitions to done
  const prevDoneCount = useRef(0)
  useEffect(() => {
    const doneCount = jobs.filter(j => j.status === 'done').length
    if (doneCount > prevDoneCount.current) {
      fetchVideos()
    }
    prevDoneCount.current = doneCount
  }, [jobs])

  const handleJobStarted = useCallback((job: JobProgress) => {
    setJobs(prev => [job, ...prev])
  }, [])

  const handleDelete = useCallback(async (videoId: string) => {
    try {
      await deleteVideo(videoId)
      setVideos(prev => prev.filter(v => v.video_id !== videoId))
    } catch (err: any) {
      alert(`Delete failed: ${err.message}`)
    }
  }, [])

  const activeJobs = jobs.filter(j => j.status !== 'done' && j.status !== 'error')
  const finishedJobs = jobs.filter(j => j.status === 'done' || j.status === 'error')

  return (
    <div style={styles.root}>
      <header style={styles.header}>
        <div style={styles.headerInner}>
          <span style={styles.logo}>📹 Video Manager</span>
          <span style={styles.headerRight}>
            <a href="/" style={styles.headerLink}>Player</a>
          </span>
        </div>
      </header>

      <main style={styles.main}>
        {/* Left column: upload + jobs */}
        <div style={styles.left}>
          <section style={styles.card}>
            <UploadForm onJobStarted={handleJobStarted} />
          </section>

          {activeJobs.length > 0 && (
            <section style={styles.section}>
              <h2 style={styles.sectionTitle}>
                Active Jobs <span style={styles.badge}>{activeJobs.length}</span>
              </h2>
              <div style={styles.jobList}>
                {activeJobs.map(j => (
                  <JobCard key={j.job_id} initial={j} />
                ))}
              </div>
            </section>
          )}

          {finishedJobs.length > 0 && (
            <section style={styles.section}>
              <h2 style={styles.sectionTitle}>Recent Jobs</h2>
              <div style={styles.jobList}>
                {finishedJobs.slice(0, 10).map(j => (
                  <JobCard key={j.job_id} initial={j} />
                ))}
              </div>
            </section>
          )}
        </div>

        {/* Right column: video library */}
        <div style={styles.right}>
          <section style={styles.section}>
            <div style={styles.sectionHead}>
              <h2 style={styles.sectionTitle}>
                Library <span style={styles.badge}>{videos.length}</span>
              </h2>
              <button style={styles.refreshBtn} onClick={fetchVideos}>↻ Refresh</button>
            </div>
            {loadingVideos ? (
              <div style={styles.loading}>Loading…</div>
            ) : videoError ? (
              <div style={styles.error}>{videoError}</div>
            ) : (
              <VideoList videos={videos} onDelete={handleDelete} />
            )}
          </section>
        </div>
      </main>
    </div>
  )
}

const styles: Record<string, React.CSSProperties> = {
  root: {
    minHeight: '100vh',
    background: '#0d0d1a',
    color: '#e0e0e0',
    fontFamily: '"Inter", "Segoe UI", system-ui, sans-serif',
  },
  header: {
    background: '#0f0f1f',
    borderBottom: '1px solid #1e1e3a',
    padding: '0 24px',
    position: 'sticky',
    top: 0,
    zIndex: 10,
  },
  headerInner: {
    maxWidth: 1400,
    margin: '0 auto',
    height: 52,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  logo: {
    fontSize: 16,
    fontWeight: 700,
    color: '#fff',
    letterSpacing: -0.3,
  },
  headerRight: {
    display: 'flex',
    gap: 16,
    alignItems: 'center',
  },
  headerLink: {
    color: '#4f9aff',
    fontSize: 13,
    textDecoration: 'none',
  },
  main: {
    maxWidth: 1400,
    margin: '0 auto',
    padding: '24px',
    display: 'grid',
    gridTemplateColumns: '400px 1fr',
    gap: 24,
    alignItems: 'start',
  },
  left: {
    display: 'flex',
    flexDirection: 'column',
    gap: 20,
  },
  right: {
    display: 'flex',
    flexDirection: 'column',
    gap: 20,
  },
  card: {
    background: '#141428',
    border: '1px solid #2a2a3e',
    borderRadius: 12,
    padding: '20px',
  },
  section: {
    display: 'flex',
    flexDirection: 'column',
    gap: 12,
  },
  sectionHead: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  sectionTitle: {
    margin: 0,
    fontSize: 16,
    fontWeight: 600,
    color: '#e0e0e0',
    display: 'flex',
    alignItems: 'center',
    gap: 8,
  },
  badge: {
    background: '#232340',
    color: '#8888cc',
    fontSize: 11,
    padding: '1px 7px',
    borderRadius: 99,
    fontWeight: 700,
  },
  jobList: {
    display: 'flex',
    flexDirection: 'column',
    gap: 10,
  },
  refreshBtn: {
    background: 'transparent',
    border: '1px solid #2a2a3e',
    color: '#888',
    borderRadius: 6,
    padding: '4px 10px',
    fontSize: 12,
    cursor: 'pointer',
  },
  loading: {
    color: '#555',
    fontSize: 14,
    padding: '20px 0',
    textAlign: 'center',
  },
  error: {
    background: '#3a0000',
    border: '1px solid #6b0000',
    color: '#ff6060',
    fontSize: 13,
    padding: '10px 14px',
    borderRadius: 8,
  },
}
