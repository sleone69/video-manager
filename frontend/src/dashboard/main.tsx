import React from 'react'
import ReactDOM from 'react-dom/client'
import { Dashboard } from './Dashboard'

const style = document.createElement('style')
style.textContent = `
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #0d0d1a; color: #e0e0e0; }
  @keyframes spin { to { transform: rotate(360deg); } }
`
document.head.appendChild(style)

function mount() {
  const container = document.getElementById('dashboard-root')
  if (!container) {
    // Should not happen, but recover gracefully
    const div = document.createElement('div')
    div.id = 'dashboard-root'
    document.body.appendChild(div)
  }
  ReactDOM.createRoot(document.getElementById('dashboard-root')!).render(
    <React.StrictMode>
      <Dashboard />
    </React.StrictMode>,
  )
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', mount)
} else {
  mount()
}
