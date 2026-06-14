import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Embed bundle: produces a single embed.js that mounts the player via an iframe helper
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: 'dist-embed',
    lib: {
      entry: 'src/embed/embed.ts',
      name: 'VideoManagerEmbed',
      fileName: 'embed',
      formats: ['iife'],
    },
    rollupOptions: {
      external: [],
    },
  },
})
