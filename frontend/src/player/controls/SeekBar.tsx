import React, { useRef, useState, useCallback, useEffect } from 'react'

interface BufferedRange { start: number; end: number }

interface Props {
  currentTime: number
  duration: number
  bufferedRanges?: BufferedRange[]
  onSeek: (t: number) => void
}

function fmt(sec: number) {
  const s = Math.floor(sec)
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const ss = s % 60
  if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(ss).padStart(2, '0')}`
  return `${m}:${String(ss).padStart(2, '0')}`
}

export function SeekBar({ currentTime, duration, bufferedRanges = [], onSeek }: Props) {
  const trackRef = useRef<HTMLDivElement>(null)
  const [hovering, setHovering] = useState(false)
  const [dragging, setDragging] = useState(false)
  const [dragFrac, setDragFrac] = useState<number | null>(null)  // local drag position
  const [hoverX, setHoverX] = useState(0)      // 0–100
  const [hoverTime, setHoverTime] = useState(0)

  const basePct = duration > 0 ? Math.min(100, (currentTime / duration) * 100) : 0
  // During drag, show the drag fraction immediately instead of the slow currentTime prop
  const pct = dragging && dragFrac !== null ? dragFrac * 100 : basePct
  const active = hovering || dragging

  const fracFromEvent = useCallback((clientX: number) => {
    const rect = trackRef.current?.getBoundingClientRect()
    if (!rect) return 0
    return Math.max(0, Math.min(1, (clientX - rect.left) / rect.width))
  }, [])

  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    const f = fracFromEvent(e.clientX)
    setHoverX(f * 100)
    setHoverTime(isFinite(duration) ? f * duration : 0)
  }, [fracFromEvent, duration])

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    if (!duration || !isFinite(duration)) return
    const f = fracFromEvent(e.clientX)
    setDragFrac(f)
    setHoverX(f * 100)
    setHoverTime(f * duration)
    setDragging(true)

    // Track the live drag fraction via closure ref so onUp can read final value
    let liveFrac = f
    const onMove = (ev: MouseEvent) => {
      liveFrac = fracFromEvent(ev.clientX)
      setDragFrac(liveFrac)
      setHoverX(liveFrac * 100)
      setHoverTime(liveFrac * duration)
    }
    const onUp = () => {
      // Seek only once on release — avoids hammering the stream on every pixel
      if (isFinite(duration)) onSeek(liveFrac * duration)
      setDragging(false)
      setDragFrac(null)
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }, [fracFromEvent, onSeek, duration])

  // Touch support
  const handleTouchStart = useCallback((e: React.TouchEvent) => {
    if (!duration || !isFinite(duration)) return
    const touch = e.touches[0]
    const f = fracFromEvent(touch.clientX)
    setDragFrac(f)
    setHoverX(f * 100)
    setHoverTime(f * duration)
    setDragging(true)

    const onMove = (ev: TouchEvent) => {
      const f2 = fracFromEvent(ev.touches[0].clientX)
      setDragFrac(f2)
      setHoverX(f2 * 100)
      setHoverTime(f2 * duration)
    }
    const onEnd = (ev: TouchEvent) => {
      // Seek only on release
      const lastTouch = ev.changedTouches[0]
      const ff = fracFromEvent(lastTouch.clientX)
      if (isFinite(duration)) onSeek(ff * duration)
      setDragging(false)
      setDragFrac(null)
      window.removeEventListener('touchmove', onMove)
      window.removeEventListener('touchend', onEnd)
    }
    window.addEventListener('touchmove', onMove)
    window.addEventListener('touchend', onEnd)
  }, [fracFromEvent, onSeek, duration])

  return (
    <div
      style={{ position: 'relative', padding: '10px 0', cursor: 'pointer', flexGrow: 1 }}
      onMouseEnter={() => setHovering(true)}
      onMouseLeave={() => setHovering(false)}
      onMouseMove={handleMouseMove}
      onMouseDown={handleMouseDown}
      onTouchStart={handleTouchStart}
    >
      {/* Hover time tooltip */}
      {(hovering || dragging) && duration > 0 && (
        <div style={{
          position: 'absolute',
          bottom: 'calc(100% - 2px)',
          left: `${hoverX}%`,
          transform: 'translateX(-50%)',
          background: 'rgba(28,28,28,0.9)',
          backdropFilter: 'blur(4px)',
          color: '#fff',
          fontSize: 12,
          fontWeight: 600,
          padding: '3px 7px',
          borderRadius: 4,
          whiteSpace: 'nowrap',
          pointerEvents: 'none',
          zIndex: 20,
          letterSpacing: 0.3,
        }}>
          {fmt(hoverTime)}
        </div>
      )}

      {/* Track */}
      <div
        ref={trackRef}
        style={{
          position: 'relative',
          height: active ? 5 : 3,
          background: 'rgba(255,255,255,0.2)',
          borderRadius: 3,
          transition: 'height 0.15s ease',
          overflow: 'visible',
        }}
      >
        {/* Buffered ranges */}
        {bufferedRanges.map((r, i) => (
          <div key={i} style={{
            position: 'absolute',
            left: `${(r.start / duration) * 100}%`,
            width: `${((r.end - r.start) / duration) * 100}%`,
            top: 0, height: '100%',
            background: 'rgba(255,255,255,0.38)',
            borderRadius: 3,
          }} />
        ))}

        {/* Played fill */}
        <div style={{
          position: 'absolute',
          left: 0, top: 0,
          height: '100%',
          width: `${pct}%`,
          background: '#ff0000',
          borderRadius: 3,
          transition: dragging ? 'none' : undefined,
        }} />

        {/* Scrubber thumb */}
        <div style={{
          position: 'absolute',
          left: `${pct}%`,
          top: '50%',
          transform: 'translate(-50%, -50%)',
          width: active ? 13 : 0,
          height: active ? 13 : 0,
          background: '#fff',
          borderRadius: '50%',
          boxShadow: '0 0 4px rgba(0,0,0,0.6)',
          transition: 'width 0.15s ease, height 0.15s ease',
          pointerEvents: 'none',
          zIndex: 5,
        }} />
      </div>
    </div>
  )
}

