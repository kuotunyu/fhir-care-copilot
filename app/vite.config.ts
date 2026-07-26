import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  test: {
    // 元件測試需要 DOM。測試檔與被測程式碼放在一起(src/**/*.test.*),
    // 這樣 `tsc -b` 會一併型別檢查它們——測試自己的型別錯誤不該只在跑起來時才發現。
    environment: 'jsdom',
    setupFiles: ['./src/test-setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    css: false,
  },
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
