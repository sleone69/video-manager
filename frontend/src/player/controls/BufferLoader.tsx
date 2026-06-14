import React from 'react'

export function BufferLoader() {
  return (
    <div
      style={{
        position: 'absolute',
        inset: 0,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'rgba(0,0,0,0.4)',
        zIndex: 10,
        pointerEvents: 'none',
      }}
    >
      <div
        style={{
          width: 48,
          height: 48,
          border: '4px solid rgba(255,255,255,0.2)',
          borderTopColor: '#fff',
          borderRadius: '50%',
          animation: 'vm-spin 0.8s linear infinite',
        }}
      />
      <style>{`
        @keyframes vm-spin { to { transform: rotate(360deg); } }
      `}</style>
    </div>
  )
}
