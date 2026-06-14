/**
 * Timestamp → chunk resolution (mirrors backend streaming/resolver.py).
 *
 * Given an absolute playback time and the ordered chunk list from the manifest,
 * returns which chunk covers that time and the intra-chunk offset.
 */

import type { StreamChunk } from '../api/client'

export interface ResolvedPosition {
  chunkIndex: number
  chunkStartSec: number
  chunkEndSec: number
  offsetSec: number       // seconds from chunk start
  approxByteOffset: number
}

export function resolve(
  timestamp: number,
  chunks: StreamChunk[],
): ResolvedPosition | null {
  if (!chunks.length) return null

  const sorted = [...chunks].sort((a, b) => a.index - b.index)

  for (const chunk of sorted) {
    if (timestamp >= chunk.start_sec && timestamp <= chunk.end_sec) {
      const duration = chunk.end_sec - chunk.start_sec
      const offsetSec = timestamp - chunk.start_sec
      const frac = duration > 0 ? offsetSec / duration : 0
      return {
        chunkIndex: chunk.index,
        chunkStartSec: chunk.start_sec,
        chunkEndSec: chunk.end_sec,
        offsetSec,
        approxByteOffset: Math.floor(chunk.byte_size * frac),
      }
    }
  }

  // Clamp to last chunk
  const last = sorted[sorted.length - 1]
  if (timestamp >= last.start_sec) {
    return {
      chunkIndex: last.index,
      chunkStartSec: last.start_sec,
      chunkEndSec: last.end_sec,
      offsetSec: Math.max(0, timestamp - last.start_sec),
      approxByteOffset: 0,
    }
  }

  return null
}
