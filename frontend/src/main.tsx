import React from 'react'
import ReactDOM from 'react-dom/client'
import { VideoPlayer } from './player/VideoPlayer'

// Config injected by the embed page HTML or the SPA
const cfg = (window as any).__VM_CONFIG__ ?? {}
const videoId: string = cfg.videoId ?? new URLSearchParams(location.search).get('v') ?? ''

if (!videoId) {
  document.getElementById('root')!.textContent = 'No video ID provided.'
} else {
  ReactDOM.createRoot(document.getElementById('root')!).render(
    <React.StrictMode>
      <VideoPlayer videoId={videoId} />
    </React.StrictMode>,
  )
}
