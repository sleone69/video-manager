/**
 * VideoPlayer — YouTube-style MSE player.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react'
import { fetchManifest, streamtapeProxyUrl, type StreamManifest } from '../api/client'
import { useChunkStream } from './useChunkStream'
import { SeekBar } from './controls/SeekBar'

interface Props {
  videoId: string
}

// ── SVG icons ─────────────────────────────────────────────────────────────────
const SZ = 22

function IconPlay() {
  return (
    <svg width={SZ} height={SZ} viewBox="0 0 24 24" fill="currentColor">
      <polygon points="5,3 19,12 5,21" />
    </svg>
  )
}
function IconPause() {
  return (
    <svg width={SZ} height={SZ} viewBox="0 0 24 24" fill="currentColor">
      <rect x="5" y="3" width="4" height="18" rx="1" />
      <rect x="15" y="3" width="4" height="18" rx="1" />
    </svg>
  )
}
function IconSkipBack() {
  return (
    <svg width={SZ} height={SZ} viewBox="0 0 24 24" fill="currentColor">
      <path d="M12 5V1L7 6l5 5V7c3.31 0 6 2.69 6 6s-2.69 6-6 6-6-2.69-6-6H4c0 4.42 3.58 8 8 8s8-3.58 8-8-3.58-8-8-8z"/>
      <text x="10" y="14" fontSize="5" textAnchor="middle" fill="currentColor">10</text>
    </svg>
  )
}
function IconSkipFwd() {
  return (
    <svg width={SZ} height={SZ} viewBox="0 0 24 24" fill="currentColor">
      <path d="M12 5V1l5 5-5 5V7c-3.31 0-6 2.69-6 6s2.69 6 6 6 6-2.69 6-6h2c0 4.42-3.58 8-8 8s-8-3.58-8-8 3.58-8 8-8z"/>
      <text x="14" y="14" fontSize="5" textAnchor="middle" fill="currentColor">10</text>
    </svg>
  )
}
function IconVolume({ level }: { level: number }) {
  if (level === 0) {
    return (
      <svg width={SZ} height={SZ} viewBox="0 0 24 24" fill="currentColor">
        <path d="M16.5 12A4.5 4.5 0 0 0 14 7.97v2.21l2.45 2.45c.03-.2.05-.41.05-.63zm2.5 0c0 .94-.2 1.82-.54 2.64l1.51 1.51C20.63 14.91 21 13.5 21 12c0-4.28-2.99-7.86-7-8.77v2.06c2.89.86 5 3.54 5 6.71zM4.27 3L3 4.27 7.73 9H3v6h4l5 5v-6.73l4.25 4.25c-.67.52-1.42.93-2.25 1.18v2.06c1.38-.31 2.63-.95 3.69-1.81L19.73 21 21 19.73l-9-9L4.27 3zM12 4L9.91 6.09 12 8.18V4z"/>
      </svg>
    )
  }
  if (level < 0.5) {
    return (
      <svg width={SZ} height={SZ} viewBox="0 0 24 24" fill="currentColor">
        <path d="M18.5 12c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM5 9v6h4l5 5V4L9 9H5z"/>
      </svg>
    )
  }
  return (
    <svg width={SZ} height={SZ} viewBox="0 0 24 24" fill="currentColor">
      <path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3A4.5 4.5 0 0 0 14 7.97v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z"/>
    </svg>
  )
}
function IconFullscreen() {
  return (
    <svg width={SZ} height={SZ} viewBox="0 0 24 24" fill="currentColor">
      <path d="M7 14H5v5h5v-2H7v-3zm-2-4h2V7h3V5H5v5zm12 7h-3v2h5v-5h-2v3zM14 5v2h3v3h2V5h-5z"/>
    </svg>
  )
}
function IconExitFullscreen() {
  return (
    <svg width={SZ} height={SZ} viewBox="0 0 24 24" fill="currentColor">
      <path d="M5 16h3v3h2v-5H5v2zm3-8H5v2h5V5H8v3zm6 11h2v-3h3v-2h-5v5zm2-11V5h-2v5h5V8h-3z"/>
    </svg>
  )
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatTime(sec: number): string {
  const s = Math.floor(sec)
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const ss = s % 60
  if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(ss).padStart(2, '0')}`
  return `${m}:${String(ss).padStart(2, '0')}`
}

function qualityLabel(height: number) {
  if (height >= 2160) return '4K'
  if (height >= 1440) return '1440p'
  if (height >= 1080) return '1080p'
  if (height >= 720) return '720p'
  if (height >= 480) return '480p'
  return `${height}p`
}

// ── Component ─────────────────────────────────────────────────────────────────

export function VideoPlayer({ videoId }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  const [manifest, setManifest] = useState<StreamManifest | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  // stMode = true → use Streamtape backend proxy; false → use MSE chunk streaming
  const [stMode, setStMode] = useState(false)
  const hasSTParts = (manifest?.streamtape_parts?.length ?? 0) > 0

  const [playing, setPlaying] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [pendingSeekTime, setPendingSeekTime] = useState<number | null>(null)
  const [duration, setDuration] = useState(0)
  const [volume, setVolume] = useState(1)
  const [muted, setMuted] = useState(false)
  const [bufferedRanges, setBufferedRanges] = useState<{ start: number; end: number }[]>([])
  const [controlsVisible, setControlsVisible] = useState(true)
  const [isFullscreen, setIsFullscreen] = useState(false)
  const [showVolumeSlider, setShowVolumeSlider] = useState(false)
  const [flashIcon, setFlashIcon] = useState<'play' | 'pause' | null>(null)
  const [ended, setEnded] = useState(false)

  const hideTimer = useRef<ReturnType<typeof setTimeout>>()
  const volumeAreaRef = useRef<HTMLDivElement>(null)
  const flashTimer = useRef<ReturnType<typeof setTimeout>>()

  const { buffering, error: streamError } = useChunkStream({ manifest: stMode ? null : manifest, videoRef })

  // ── Streamtape native src ──────────────────────────────────────────────
  // Only touch video.src in ST mode. In MSE mode, useChunkStream owns video.src
  // (it sets it to a MediaSource blob URL). Removing it here after useChunkStream
  // sets it would destroy the MediaSource connection and stop chunk downloads.
  useEffect(() => {
    const v = videoRef.current
    if (!v || !manifest || !stMode) return
    v.src = streamtapeProxyUrl(manifest.video_id)
    v.load()
  }, [stMode, manifest])

  // ── Load manifest ──────────────────────────────────────────────────────
  useEffect(() => {
    fetchManifest(videoId)
      .then(setManifest)
      .catch(e => setLoadError(String(e)))
  }, [videoId])

  // ── Video event listeners ──────────────────────────────────────────────
  useEffect(() => {
    const v = videoRef.current
    if (!v) return

    const onPlay = () => { setPlaying(true); setEnded(false) }
    const onPause = () => setPlaying(false)
    const onEnded = () => { setPlaying(false); setEnded(true) }
    const onSeeked = () => setPendingSeekTime(null)
    const onTimeUpdate = () => {
      setCurrentTime(v.currentTime)
      // Update buffered ranges
      const ranges: { start: number; end: number }[] = []
      for (let i = 0; i < v.buffered.length; i++) {
        ranges.push({ start: v.buffered.start(i), end: v.buffered.end(i) })
      }
      setBufferedRanges(ranges)
    }
    const onDurationChange = () => {
      const d = v.duration
      setDuration(isFinite(d) && d > 0 ? d : (manifest?.duration_sec ?? 0))
    }
    const onVolumeChange = () => { setVolume(v.volume); setMuted(v.muted) }

    v.addEventListener('play', onPlay)
    v.addEventListener('pause', onPause)
    v.addEventListener('ended', onEnded)
    v.addEventListener('seeked', onSeeked)
    v.addEventListener('timeupdate', onTimeUpdate)
    v.addEventListener('durationchange', onDurationChange)
    v.addEventListener('volumechange', onVolumeChange)
    return () => {
      v.removeEventListener('play', onPlay)
      v.removeEventListener('pause', onPause)
      v.removeEventListener('ended', onEnded)
      v.removeEventListener('seeked', onSeeked)
      v.removeEventListener('timeupdate', onTimeUpdate)
      v.removeEventListener('durationchange', onDurationChange)
      v.removeEventListener('volumechange', onVolumeChange)
    }
  }, [manifest])

  // ── Fullscreen tracking ────────────────────────────────────────────────
  useEffect(() => {
    const onChange = () => setIsFullscreen(!!document.fullscreenElement)
    document.addEventListener('fullscreenchange', onChange)
    return () => document.removeEventListener('fullscreenchange', onChange)
  }, [])

  // ── Auto-hide controls ─────────────────────────────────────────────────
  const scheduleHide = useCallback(() => {
    clearTimeout(hideTimer.current)
    hideTimer.current = setTimeout(() => setControlsVisible(false), 3000)
  }, [])

  const showControls = useCallback(() => {
    setControlsVisible(true)
    if (playing) scheduleHide()
    else clearTimeout(hideTimer.current)
  }, [playing, scheduleHide])

  useEffect(() => {
    if (playing) scheduleHide()
    else { setControlsVisible(true); clearTimeout(hideTimer.current) }
  }, [playing, scheduleHide])

  // ── Keyboard shortcuts ─────────────────────────────────────────────────
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA') return
      const v = videoRef.current
      if (!v) return
      switch (e.key) {
        case ' ':
        case 'k':
          e.preventDefault()
          v.paused ? v.play() : v.pause()
          break
        case 'ArrowLeft':
          e.preventDefault()
          v.currentTime = Math.max(0, v.currentTime - 5)
          break
        case 'ArrowRight': {
          e.preventDefault()
          const cap = (isFinite(v.duration) && v.duration > 0) ? v.duration : (manifest?.duration_sec ?? 0)
          v.currentTime = Math.min(cap, v.currentTime + 5)
          break
        }
        case 'ArrowUp':
          e.preventDefault()
          v.volume = Math.min(1, v.volume + 0.1)
          break
        case 'ArrowDown':
          e.preventDefault()
          v.volume = Math.max(0, v.volume - 0.1)
          break
        case 'm':
          v.muted = !v.muted
          break
        case 'f':
          toggleFullscreen()
          break
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])

  // ── Actions ────────────────────────────────────────────────────────────
  const flash = (icon: 'play' | 'pause') => {
    setFlashIcon(icon)
    clearTimeout(flashTimer.current)
    flashTimer.current = setTimeout(() => setFlashIcon(null), 600)
  }

  const togglePlay = useCallback(() => {
    const v = videoRef.current
    if (!v) return
    if (v.paused) { v.play(); flash('play') }
    else { v.pause(); flash('pause') }
  }, [])

  const skip = (delta: number) => {
    const v = videoRef.current
    if (!v) return
    // v.duration is Infinity in MSE – use totalDuration (manifest-based) as cap
    const cap = (isFinite(v.duration) && v.duration > 0) ? v.duration : totalDuration
    v.currentTime = Math.max(0, Math.min(cap, v.currentTime + delta))
  }

  const seek = useCallback((t: number) => {
    const v = videoRef.current
    if (!v) return
    setPendingSeekTime(t)
    v.currentTime = t
  }, [])

  const toggleMute = () => {
    const v = videoRef.current
    if (!v) return
    v.muted = !v.muted
  }

  const changeVolume = (val: number) => {
    const v = videoRef.current
    if (!v) return
    v.volume = val
    if (val > 0) v.muted = false
  }

  const toggleFullscreen = () => {
    const el = containerRef.current
    if (!el) return
    if (!document.fullscreenElement) el.requestFullscreen()
    else document.exitFullscreen()
  }

  const replay = () => {
    const v = videoRef.current
    if (!v) return
    v.currentTime = 0
    v.play()
  }

  // ── Render ─────────────────────────────────────────────────────────────
  if (loadError) {
    return (
      <div style={{ background: '#000', color: '#f66', padding: 24, fontFamily: 'system-ui', fontSize: 14 }}>
        ⚠ Failed to load video: {loadError}
      </div>
    )
  }

  const res = manifest?.resolution
  // Use manifest duration as ground truth; v.duration is Infinity in MSE until endOfStream
  const totalDuration = (isFinite(duration) && duration > 0) ? duration : (manifest?.duration_sec ?? 0)
  // While waiting for chunks to load after a seek, show the target position
  // so the thumb doesn't snap back to the old time during buffering.
  const displayTime = pendingSeekTime ?? currentTime
  const effectiveVolume = muted ? 0 : volume

  return (
    <div
      ref={containerRef}
      tabIndex={0}
      onMouseMove={showControls}
      onMouseLeave={() => playing && setControlsVisible(false)}
      style={{
        position: 'relative',
        background: '#000',
        width: '100%',
        aspectRatio: res ? `${res.width}/${res.height}` : '16/9',
        maxHeight: '100dvh',
        overflow: 'hidden',
        userSelect: 'none',
        cursor: controlsVisible ? 'default' : 'none',
        outline: 'none',
        fontFamily: '"YouTube Noto", Roboto, Arial, system-ui, sans-serif',
      }}
    >
      {/* Video */}
      <video
        ref={videoRef}
        style={{ width: '100%', height: '100%', display: 'block', objectFit: 'contain' }}
        playsInline
        onClick={togglePlay}
      />

      {/* Buffering spinner */}
      {buffering && (
        <div style={overlay}>
          <div style={spinnerStyle} />
          <style>{`@keyframes vm-spin{to{transform:rotate(360deg)}}`}</style>
        </div>
      )}

      {/* Center flash icon */}
      {flashIcon && (
        <div style={{ ...overlay, pointerEvents: 'none', animation: 'vm-flash 0.6s ease-out forwards' }}>
          <style>{`
            @keyframes vm-flash {
              0%   { opacity: 1; transform: scale(1); }
              60%  { opacity: 0.5; transform: scale(1.5); }
              100% { opacity: 0; transform: scale(2); }
            }
          `}</style>
          <div style={{
            width: 72, height: 72, borderRadius: '50%',
            background: 'rgba(0,0,0,0.5)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            color: '#fff',
          }}>
            {flashIcon === 'play' ? <IconPlay /> : <IconPause />}
          </div>
        </div>
      )}

      {/* Controls overlay */}
      <div
        style={{
          position: 'absolute', inset: 0,
          display: 'flex', flexDirection: 'column',
          justifyContent: 'flex-end',
          opacity: controlsVisible || !playing ? 1 : 0,
          transition: 'opacity 0.25s ease',
          pointerEvents: controlsVisible || !playing ? 'auto' : 'none',
        }}
      >
        {/* Top gradient + title */}
        <div style={{
          position: 'absolute', top: 0, left: 0, right: 0,
          background: 'linear-gradient(to bottom, rgba(0,0,0,0.75) 0%, transparent 100%)',
          padding: '14px 16px 40px',
          pointerEvents: 'none',
        }}>
          {manifest?.name && (
            <div style={{ color: '#fff', fontSize: 15, fontWeight: 500, textShadow: '0 1px 3px rgba(0,0,0,0.8)', maxWidth: '70%', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {manifest.name}
            </div>
          )}
        </div>

        {/* Error banner */}
        {streamError && (
          <div style={{ color: '#ff6b6b', fontSize: 12, padding: '4px 16px', background: 'rgba(0,0,0,0.8)' }}>
            {streamError}
          </div>
        )}

        {/* Bottom gradient bar */}
        <div style={{
          background: 'linear-gradient(to top, rgba(0,0,0,0.85) 0%, rgba(0,0,0,0.4) 60%, transparent 100%)',
          padding: '32px 12px 10px',
          display: 'flex', flexDirection: 'column', gap: 4,
        }}>
          {/* Seek bar row */}
          <div style={{ display: 'flex', alignItems: 'center', padding: '0 4px' }}>
            <SeekBar
              currentTime={displayTime}
              duration={totalDuration}
              bufferedRanges={bufferedRanges}
              onSeek={seek}
            />
          </div>

          {/* Controls row */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 4, padding: '2px 4px' }}>
            {/* Play / Pause / Replay */}
            <button onClick={togglePlay} style={btn} title={ended ? 'Replay' : playing ? 'Pause (k)' : 'Play (k)'}>
              {ended ? (
                <svg width={SZ} height={SZ} viewBox="0 0 24 24" fill="currentColor">
                  <path d="M12 5V1L7 6l5 5V7c3.31 0 6 2.69 6 6s-2.69 6-6 6-6-2.69-6-6H4c0 4.42 3.58 8 8 8s8-3.58 8-8-3.58-8-8-8z"/>
                </svg>
              ) : playing ? <IconPause /> : <IconPlay />}
            </button>

            {/* Skip -10 */}
            <button onClick={() => skip(-10)} style={btn} title="Back 10s (←)">
              <svg width={SZ} height={SZ} viewBox="0 0 24 24" fill="currentColor">
                <path d="M12 5V1L7 6l5 5V7c3.31 0 6 2.69 6 6s-2.69 6-6 6-6-2.69-6-6H4c0 4.42 3.58 8 8 8s8-3.58 8-8-3.58-8-8-8z"/>
                <text x="12" y="15.5" fontSize="6" textAnchor="middle" fontWeight="bold">10</text>
              </svg>
            </button>

            {/* Skip +10 */}
            <button onClick={() => skip(10)} style={btn} title="Forward 10s (→)">
              <svg width={SZ} height={SZ} viewBox="0 0 24 24" fill="currentColor">
                <path d="M12 5V1l5 5-5 5V7c-3.31 0-6 2.69-6 6s2.69 6 6 6 6-2.69 6-6h2c0 4.42-3.58 8-8 8s-8-3.58-8-8 3.58-8 8-8z"/>
                <text x="12" y="15.5" fontSize="6" textAnchor="middle" fontWeight="bold">10</text>
              </svg>
            </button>

            {/* Volume area */}
            <div
              ref={volumeAreaRef}
              style={{ display: 'flex', alignItems: 'center', gap: 6 }}
              onMouseEnter={() => setShowVolumeSlider(true)}
              onMouseLeave={() => setShowVolumeSlider(false)}
            >
              <button onClick={toggleMute} style={btn} title="Mute (m)">
                <IconVolume level={effectiveVolume} />
              </button>

              {/* Volume slider */}
              <div style={{
                width: showVolumeSlider ? 72 : 0,
                overflow: 'hidden',
                transition: 'width 0.2s ease',
                display: 'flex', alignItems: 'center',
              }}>
                <input
                  type="range"
                  min={0} max={1} step={0.02}
                  value={effectiveVolume}
                  onChange={e => changeVolume(parseFloat(e.target.value))}
                  style={volumeSliderStyle}
                  title={`Volume ${Math.round(effectiveVolume * 100)}%`}
                />
              </div>
            </div>

            {/* Time display */}
            <span style={{
              color: '#fff',
              fontSize: 13,
              fontWeight: 400,
              letterSpacing: 0.2,
              fontVariantNumeric: 'tabular-nums',
              marginLeft: 4,
              whiteSpace: 'nowrap',
            }}>
              {formatTime(displayTime)}
              <span style={{ color: 'rgba(255,255,255,0.55)', margin: '0 4px' }}>/</span>
              {formatTime(totalDuration)}
            </span>

            <div style={{ flexGrow: 1 }} />

            {/* Quality badge */}
            {res && (
              <div
                title={`${res.width}×${res.height} · ${res.fps.toFixed(2)} fps · ${res.codec.toUpperCase()}`}
                style={{
                  fontSize: 11,
                  fontWeight: 700,
                  color: 'rgba(255,255,255,0.75)',
                  background: 'rgba(255,255,255,0.12)',
                  border: '1px solid rgba(255,255,255,0.15)',
                  padding: '2px 7px',
                  borderRadius: 3,
                  letterSpacing: 0.3,
                  cursor: 'default',
                }}
              >
                {qualityLabel(res.height)}
              </div>
            )}

            {/* Streamtape mode toggle — only shown when ST parts are available */}
            {hasSTParts && (
              <button
                onClick={() => setStMode(m => !m)}
                title={stMode ? 'Switch to MSE chunk streaming' : 'Switch to Streamtape streaming'}
                style={{
                  ...btn,
                  fontSize: 10,
                  fontWeight: 700,
                  padding: '3px 7px',
                  letterSpacing: 0.3,
                  background: stMode ? 'rgba(255,100,0,0.35)' : 'rgba(255,255,255,0.10)',
                  border: stMode ? '1px solid rgba(255,140,0,0.6)' : '1px solid rgba(255,255,255,0.15)',
                  borderRadius: 3,
                  color: stMode ? '#ffa040' : 'rgba(255,255,255,0.75)',
                }}
              >
                ST
              </button>
            )}

            {/* Fullscreen */}
            <button onClick={toggleFullscreen} style={btn} title={isFullscreen ? 'Exit fullscreen (f)' : 'Fullscreen (f)'}>
              {isFullscreen ? <IconExitFullscreen /> : <IconFullscreen />}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Styles ────────────────────────────────────────────────────────────────────

const overlay: React.CSSProperties = {
  position: 'absolute', inset: 0,
  display: 'flex', alignItems: 'center', justifyContent: 'center',
  pointerEvents: 'none',
  zIndex: 10,
}

const spinnerStyle: React.CSSProperties = {
  width: 44,
  height: 44,
  border: '3px solid rgba(255,255,255,0.15)',
  borderTopColor: '#fff',
  borderRadius: '50%',
  animation: 'vm-spin 0.75s linear infinite',
}

const btn: React.CSSProperties = {
  background: 'none',
  border: 'none',
  color: '#fff',
  cursor: 'pointer',
  padding: '6px',
  borderRadius: 4,
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  lineHeight: 0,
  transition: 'background 0.15s',
  flexShrink: 0,
}

const volumeSliderStyle: React.CSSProperties = {
  WebkitAppearance: 'none',
  appearance: 'none',
  width: 68,
  height: 3,
  borderRadius: 3,
  background: 'rgba(255,255,255,0.3)',
  outline: 'none',
  cursor: 'pointer',
  accentColor: '#fff',
}

