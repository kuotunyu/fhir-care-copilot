import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // 開發模式(npm run dev)把 /api 轉給本機 FastAPI(uvicorn --port 8000),
      // 正式環境是同一個 FastAPI process serve 前端靜態檔,不需要 proxy。
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
