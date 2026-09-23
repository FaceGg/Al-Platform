import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5174,
    proxy: { '/portal': { target: 'http://localhost:8444', changeOrigin: true } },
  },
  test: { environment: "jsdom", setupFiles: "./src/test-setup.ts" },
})
