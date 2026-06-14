import React from 'react'

interface Props {
  width: number
  height: number
  fps: number
  codec: string
}

export function ResolutionBadge({ width, height, fps, codec }: Props) {
  const label =
    height >= 2160 ? '4K' :
    height >= 1440 ? '1440p' :
    height >= 1080 ? '1080p' :
    height >= 720  ? '720p'  :
    height >= 480  ? '480p'  : `${height}p`

  return (
    <div
      style={{
        fontSize: 11,
        color: 'rgba(255,255,255,0.7)',
        background: 'rgba(0,0,0,0.5)',
        padding: '2px 6px',
        borderRadius: 3,
        fontFamily: 'monospace',
        whiteSpace: 'nowrap',
        userSelect: 'none',
      }}
      title={`${width}×${height} · ${fps.toFixed(2)} fps · ${codec}`}
    >
      {label} · {fps.toFixed(0)} fps
    </div>
  )
}
