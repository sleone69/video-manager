/**
 * useChunkStream — MSE chunk streaming hook (sequential downloader).
 *
 * Download model
 * --------------
 * A single async worker downloads chunks one at a time in ascending order.
 * It stays at most PREFETCH_AHEAD chunks ahead of the current playhead;
 * if it gets too far ahead it pauses and waits for `timeupdate` to wake it.
 *
 * On seek the worker is cancelled (generation counter increment + AbortController)
 * and restarted from the chunk that contains the new playhead position.
 *
 * A persistent per-chunk cache means re-seeks never hit the network again.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import type { StreamManifest } from '../api/client'
import { chunkUrl } from '../api/client'
import { resolve } from './seek'

/** Number of chunks to download ahead of the current playback position. */
const PREFETCH_AHEAD = 3

function getMime(manifest: StreamManifest): string {
  const codec = manifest.mse_codec || 'avc1.640028, mp4a.40.2'
  return `video/mp4; codecs="${codec}"`
}

interface UseChunkStreamOptions {
  manifest: StreamManifest | null
  videoRef: React.RefObject<HTMLVideoElement | null>
}

interface UseChunkStreamResult {
  buffering: boolean
  error: string | null
}

export function useChunkStream({
  manifest,
  videoRef,
}: UseChunkStreamOptions): UseChunkStreamResult {
  const [buffering, setBuffering] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const msRef = useRef<MediaSource | null>(null)
  const sbRef = useRef<SourceBuffer | null>(null)
  const currentChunkRef = useRef<number>(0)   // chunk index under the playhead
  const pendingFlushRef = useRef(false)

  // Persistent cache — survives seeks so completed chunks are never re-fetched.
  const chunkCacheRef = useRef<Map<number, ArrayBuffer>>(new Map())

  // Sequential download state
  const nextToFetchRef = useRef<number>(0)       // next chunk index the worker will fetch
  const workerGenRef = useRef<number>(0)          // incremented on each startWorker() call
  const currentFetchAbortRef = useRef<AbortController | null>(null)
  const resumeWorkerRef = useRef<(() => void) | null>(null)  // unblocks a throttle-paused worker

  // Serialised append queue. Each entry is a slice of a chunk; setOffset marks the
  // first slice of a chunk (when the SourceBuffer timestampOffset must be set).
  const queueRef = useRef<{ buf: BufferSource; startSec: number; setOffset: boolean }[]>([])

  // ── Serialised SourceBuffer append ────────────────────────────────────
  const drainQueue = useCallback(() => {
    const sb = sbRef.current
    const ms = msRef.current
    if (!sb || !ms || ms.readyState !== 'open' || sb.updating) return
    if (pendingFlushRef.current) {
      pendingFlushRef.current = false
      try {
        if (sb.buffered.length > 0) {
          sb.remove(0, Infinity)
          return  // wait for updateend to call drainQueue again
        }
      } catch (_) {}
    }
    if (queueRef.current.length === 0) return
    const { buf, startSec, setOffset } = queueRef.current.shift()!
    try {
      // Set the timestamp offset only on the first slice of a chunk. If the parser
      // is unexpectedly mid-segment this throws InvalidStateError; reset with
      // abort() and retry so the slice still appends instead of being dropped.
      if (setOffset) {
        try {
          sb.timestampOffset = startSec
        } catch (_) {
          try { sb.abort() } catch (_) {}
          sb.timestampOffset = startSec
        }
      }
      sb.appendBuffer(buf)
    } catch (e) {
      console.error('appendBuffer error:', e)
    }
  }, [])

  // ── Sequential download worker ─────────────────────────────────────────
  // Each call captures a generation token; if a newer call supersedes it the
  // worker exits cleanly without touching state that belongs to the new one.
  const startWorker = useCallback((fromChunk: number, manifest_: StreamManifest) => {
    // Abort any in-flight fetch from a previous worker generation.
    currentFetchAbortRef.current?.abort()
    currentFetchAbortRef.current = null

    // Unblock a throttle-waiting previous worker so it exits immediately.
    if (resumeWorkerRef.current) {
      resumeWorkerRef.current()
      resumeWorkerRef.current = null
    }

    nextToFetchRef.current = fromChunk
    const myGen = ++workerGenRef.current

    ;(async () => {
      while (true) {
        // Exit if a newer worker has taken over.
        if (workerGenRef.current !== myGen) return

        const idx = nextToFetchRef.current
        if (idx >= manifest_.chunks.length) return

        // Throttle: pause while we are too far ahead of the playhead.
        if (idx > currentChunkRef.current + PREFETCH_AHEAD) {
          await new Promise<void>(resolve => { resumeWorkerRef.current = resolve })
          continue  // re-check gen and idx after waking
        }

        // Generation may have changed while we awaited.
        if (workerGenRef.current !== myGen) return

        const chunkMeta = manifest_.chunks[idx]

        // Cache hit — push to queue immediately, no network needed.
        const cached = chunkCacheRef.current.get(idx)
        if (cached) {
          queueRef.current.push({ buf: cached, startSec: chunkMeta.start_sec, setOffset: true })
          drainQueue()
          nextToFetchRef.current++
          continue
        }

        // Network fetch — one at a time, strictly sequential.
        const ac = new AbortController()
        currentFetchAbortRef.current = ac

        try {
          const res = await fetch(chunkUrl(manifest_.video_id, idx), { signal: ac.signal })
          if (workerGenRef.current !== myGen) return
          if (!res.ok) throw new Error(`HTTP ${res.status}`)

          const reader = res.body?.getReader()
          if (!reader) {
            // No streaming body — fall back to whole-chunk append.
            const buf = await res.arrayBuffer()
            if (workerGenRef.current !== myGen) return
            chunkCacheRef.current.set(idx, buf)
            queueRef.current.push({ buf, startSec: chunkMeta.start_sec, setOffset: true })
            drainQueue()
            nextToFetchRef.current++
            continue
          }

          // Progressive append: feed slices to the SourceBuffer as they arrive so
          // playback can start before the whole chunk has downloaded.
          const slices: Uint8Array[] = []
          let received = 0
          let first = true
          while (true) {
            const { done, value } = await reader.read()
            if (workerGenRef.current !== myGen) { try { await reader.cancel() } catch (_) {} return }
            if (done) break
            if (!value) continue
            slices.push(value)
            received += value.byteLength
            queueRef.current.push({ buf: value, startSec: chunkMeta.start_sec, setOffset: first })
            first = false
            drainQueue()
          }

          // Combine slices and cache the whole chunk so re-seeks never re-fetch.
          const full = new Uint8Array(received)
          let pos = 0
          for (const s of slices) { full.set(s, pos); pos += s.byteLength }
          chunkCacheRef.current.set(idx, full.buffer)
          nextToFetchRef.current++
        } catch (err: any) {
          if (err.name === 'AbortError') return  // cancelled by seek or unmount
          setError(`Chunk ${idx} failed: ${err.message}`)
          return
        } finally {
          if (currentFetchAbortRef.current === ac) currentFetchAbortRef.current = null
        }
      }
    })()
  }, [drainQueue])

  // ── Wire MediaSource on manifest load ─────────────────────────────────
  useEffect(() => {
    const video = videoRef.current
    if (!video || !manifest) return

    const ms = new MediaSource()
    msRef.current = ms
    const objectUrl = URL.createObjectURL(ms)
    video.src = objectUrl

    const onSourceOpen = () => {
      if (isFinite(manifest.duration_sec) && manifest.duration_sec > 0) {
        try { ms.duration = manifest.duration_sec } catch (_) {}
      }

      const mime = getMime(manifest)
      const mimeToUse = MediaSource.isTypeSupported(mime)
        ? mime
        : MediaSource.isTypeSupported(`video/mp4; codecs="${manifest.mse_codec.split(',')[0].trim()}"`)
          ? `video/mp4; codecs="${manifest.mse_codec.split(',')[0].trim()}"`
          : 'video/mp4'

      const sb = ms.addSourceBuffer(mimeToUse)
      sbRef.current = sb
      sb.mode = 'segments'

      sb.addEventListener('updateend', () => {
        drainQueue()
        // Signal end-of-stream once every chunk has been appended.
        if (
          queueRef.current.length === 0 &&
          currentFetchAbortRef.current === null &&
          nextToFetchRef.current >= manifest.chunks.length
        ) {
          try { ms.endOfStream() } catch (_) {}
        }
      })

      currentChunkRef.current = 0
      startWorker(0, manifest)
    }

    ms.addEventListener('sourceopen', onSourceOpen)

    return () => {
      // Cancel the active worker and clean up.
      workerGenRef.current++
      currentFetchAbortRef.current?.abort()
      currentFetchAbortRef.current = null
      if (resumeWorkerRef.current) { resumeWorkerRef.current(); resumeWorkerRef.current = null }

      chunkCacheRef.current.clear()
      ms.removeEventListener('sourceopen', onSourceOpen)
      URL.revokeObjectURL(objectUrl)
      msRef.current = null
      sbRef.current = null
      queueRef.current = []
    }
  }, [manifest]) // eslint-disable-line react-hooks/exhaustive-deps

  // ── Buffering indicator ────────────────────────────────────────────────
  useEffect(() => {
    const video = videoRef.current
    if (!video) return
    const onWaiting = () => setBuffering(true)
    const onResume = () => setBuffering(false)
    video.addEventListener('waiting', onWaiting)
    video.addEventListener('playing', onResume)
    video.addEventListener('canplay', onResume)
    return () => {
      video.removeEventListener('waiting', onWaiting)
      video.removeEventListener('playing', onResume)
      video.removeEventListener('canplay', onResume)
    }
  }, [])

  // ── Playhead tracking: advance currentChunkRef + unblock throttled worker ─
  useEffect(() => {
    const video = videoRef.current
    if (!video || !manifest) return

    const onTimeUpdate = () => {
      const pos = resolve(video.currentTime, manifest.chunks)
      if (pos && pos.chunkIndex > currentChunkRef.current) {
        currentChunkRef.current = pos.chunkIndex
        // Wake the worker if it is paused waiting for the playhead to advance.
        if (resumeWorkerRef.current) {
          const fn = resumeWorkerRef.current
          resumeWorkerRef.current = null
          fn()
        }
      }
    }

    video.addEventListener('timeupdate', onTimeUpdate)
    return () => video.removeEventListener('timeupdate', onTimeUpdate)
  }, [manifest]) // eslint-disable-line react-hooks/exhaustive-deps

  // ── Seek handler ──────────────────────────────────────────────────────
  useEffect(() => {
    const video = videoRef.current
    if (!video || !manifest) return

    const onSeeking = () => {
      const pos = resolve(video.currentTime, manifest.chunks)
      if (!pos) return

      currentChunkRef.current = pos.chunkIndex
      queueRef.current = []

      // The previous chunk may have been only partially appended — progressive
      // slices interrupted by this seek leave the SourceBuffer mid-media-segment.
      // Reset the segment parser to a clean boundary; otherwise the next
      // `sb.timestampOffset = …` (set on the seek-target chunk's first slice)
      // throws InvalidStateError, the append is skipped, and the chunk downloads
      // but never reaches the buffer ("downloads but won't play"). abort() also
      // cancels any in-flight append from the superseded worker.
      const sb = sbRef.current
      const ms = msRef.current
      if (sb && ms && ms.readyState === 'open') {
        try { sb.abort() } catch (_) {}
      }

      // Flush the SourceBuffer only if the target is not already buffered.
      const seekTime = video.currentTime
      let alreadyBuffered = false
      for (let i = 0; i < video.buffered.length; i++) {
        if (seekTime >= video.buffered.start(i) && seekTime <= video.buffered.end(i)) {
          alreadyBuffered = true
          break
        }
      }
      if (!alreadyBuffered) {
        pendingFlushRef.current = true
        drainQueue()  // triggers sb.remove → updateend → drainQueue resumes appends
      }

      // Restart the sequential worker from the seek target chunk.
      startWorker(pos.chunkIndex, manifest)
    }

    video.addEventListener('seeking', onSeeking)
    return () => video.removeEventListener('seeking', onSeeking)
  }, [manifest, drainQueue, startWorker]) // eslint-disable-line react-hooks/exhaustive-deps

  return { buffering, error }
}

