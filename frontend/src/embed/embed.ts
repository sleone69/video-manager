/**
 * embed.ts — Embed helper script.
 *
 * Drop this into any HTML page to mount a VideoManager player inside an iframe:
 *
 *   <div data-vm-player data-video-id="abc123" data-width="100%" data-height="480px"></div>
 *   <script src="https://your-server/static/embed.js" async></script>
 *
 * The script finds every [data-vm-player] div, creates an <iframe> pointing to
 * /embed/{videoId}, and inserts it inside that div.
 */

(function () {
  const API_BASE =
    (document.currentScript as HTMLScriptElement | null)?.src.replace(/\/static\/embed\.js.*/, '') ?? ''

  function mount(container: HTMLElement) {
    const videoId = container.getAttribute('data-video-id')
    if (!videoId) {
      console.warn('[VideoManager] data-vm-player element missing data-video-id', container)
      return
    }
    const width = container.getAttribute('data-width') ?? '100%'
    const height = container.getAttribute('data-height') ?? '480px'

    const iframe = document.createElement('iframe')
    iframe.src = `${API_BASE}/embed/${videoId}`
    iframe.width = width
    iframe.height = height
    iframe.style.border = 'none'
    iframe.allow = 'fullscreen'
    iframe.allowFullscreen = true
    iframe.setAttribute('loading', 'lazy')

    container.innerHTML = ''
    container.appendChild(iframe)
  }

  function init() {
    document.querySelectorAll<HTMLElement>('[data-vm-player]').forEach(mount)
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init)
  } else {
    init()
  }
})()
