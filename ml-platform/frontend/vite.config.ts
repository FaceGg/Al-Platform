import { fileURLToPath } from 'node:url'
import { searchForWorkspaceRoot } from 'vite'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Backend target is overridable for e2e runs where port 8000 is occupied.
// 默认用显式 IPv4：uvicorn e2e 实例只绑 127.0.0.1，而 localhost 在部分环境
// 优先解析为 ::1（IPv6），代理会静默连不上后端（登录停留 /login）。
const apiProxyTarget = process.env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8000'
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
