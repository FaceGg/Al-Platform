import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Backend target is overridable for e2e runs where port 8000 is occupied.
const apiProxyTarget = process.env.VITE_API_PROXY_TARGET || 'http://localhost:8000'
const wsProxyTarget = apiProxyTarget.replace(/^http/, 'ws')

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: apiProxyTarget, changeOrigin: true },
      '/ws': { target: wsProxyTarget, ws: true },
    },
  },
})
