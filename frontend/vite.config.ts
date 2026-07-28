import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  base: './',
  build: {
    outDir: '../ailab/web/static',
    emptyOutDir: true,
  },
  server: {
    proxy: {
      // ws: true also proxies the shell/log WebSocket endpoints in dev.
      '/api': { target: 'http://localhost:11500', ws: true },
    },
  },
})
