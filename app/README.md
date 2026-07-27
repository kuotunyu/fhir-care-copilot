# app/ — 照護工作台前端

React + Vite + TypeScript：病患選擇器、病歷時間軸（診斷/用藥/觀察值/照護計畫）、
個案問答（含證據抽屜、cost/latency badge、拒答狀態）。正體中文 UI（專有名詞保留原文）、
鍵盤可操作（`:focus-visible` 樣式、`<details>`/表單原生語意）、手機可瀏覽（已用行動裝置尺寸實測）。

設計語彙：「溫暖病歷夾」——奶油紙色背景、深松石綠為主色、赤陶橘為互動強調色，
紅色只保留給拒答/錯誤狀態；標題用 Fraunces 襯線字、內文用 Work Sans、數字用 JetBrains Mono。
支援亮/暗色主題（`prefers-color-scheme` + `data-theme` 覆寫）。

## 開發

```bash
npm install
npm run dev      # port 5173,vite.config.ts 已把 /api proxy 到本機 8000 的 FastAPI
```

另開一個終端機跑後端：`uv run uvicorn fhir_copilot.api.app:app --reload --port 8000`
（或用 repo 根目錄的 `just backend-dev`）。

## Production build

```bash
npm run build     # 輸出 app/dist,FastAPI(src/fhir_copilot/api/app.py)會自動 serve
```

或直接在 repo 根目錄跑 `just run`：build 前端 + 用同一個 FastAPI process(port 8000)
serve 前端與 `/api`，一行指令啟動。

`node_modules/`、`dist/` 已 gitignore。
