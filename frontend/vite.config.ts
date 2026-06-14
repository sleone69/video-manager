import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Main player app (full SPA) + dashboard
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
      '/embed': 'http://localhost:8000',
    },
  },
  build: {
    outDir: 'dist',
    manifest: true,
    rollupOptions: {
      input: {
        main: 'index.html',
        dashboard: 'dashboard.html',
      },
    },
  },
})
