import { fileURLToPath } from 'node:url'
import { searchForWorkspaceRoot } from 'vite'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Backend target is overridable for e2e runs where port 8000 is occupied.
const apiProxyTarget = process.env.VITE_API_PROXY_TARGET || 'http://localhost:8000'
const wsProxyTarget = apiProxyTarget.replace(/^http/, 'ws')

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // 允许画布「操作手册」弹窗 ?raw 导入仓库级 docs 手册（位于 frontend 根之外）
    fs: { allow: [searchForWorkspaceRoot(process.cwd()), fileURLToPath(new URL('../docs', import.meta.url))] },
    proxy: {
      '/api': { target: apiProxyTarget, changeOrigin: true },
      '/ws': { target: wsProxyTarget, ws: true },
    },
  },
})
