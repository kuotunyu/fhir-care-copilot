# scripts/

- `download_or_generate_synthea.py`（M1）— 下載官方 1K FHIR R4 樣本 + `--subset N`
  子集化（預設 100，deterministic 檔名排序）；`--generate --seed S --population P` 可用
  Java 17+ 固定 seed 本地生成；`--verify-only` 重新驗證現有子集
- `run_eval.py`（M5）— eval CLI：題目生成、跑 agent loop、算指標、預算守門
  （跑前估算超過上限即中止；執行中累計實際花費，超過即提前停止）
- `generate_model_comparison.py`（M6）— 把兩份 eval JSON 整理成
  `reports/model_comparison.md` 的一頁式比較報告
- `rescore_eval.py`（M6）— 用**目前**的判準重算已保存 eval 結果的注入指標,
  **不重打 API**。判準已經被真實資料打臉三次,錯的時候該重算的是判定、不是重買逐字稿
- `generate_injection_ab.py`（M6）— 把兩個模型的 injection A/B 整理成對照表
  （`reports/injection_ab.md`）。換預設模型前用它決定要不要換
- `run_e2e_sample.py`（M6/營運層 Phase 5）— **第二軌**:打真的供應商,量含供應商延遲的
  完整 HTTP 往返。刻意**不是**負載測試——真 provider 有速率限制,併發拉高只會量到
  一整片 429。走單一連線、固定間隔、少量取樣
- `capture_screenshots.py`（M7）— 產生 README 的介面截圖,**由程式產生不手動截**。
  自己起後端(mock provider)、走完固定操作流程、存進 `docs/screenshots/`。
  順便驗 375px 無橫向溢位(M4 的驗收條件)。需要 `uv sync --extra screenshots`
  與 `uv run playwright install chromium`
- `run_loadtest.py`（營運層 Phase 0）— 起後端、跑 k6 併發矩陣、收 summary，
  輸出到 `reports/loadtest/`
- `verify_audit_chain.py`（營運層 Phase 4）— 掃描稽核軌跡的 hash chain，
  壞掉時**指出是哪一列**；exit code 1 方便接進 cron 或 CI。有 `DATABASE_URL`
  就驗 Postgres，沒有就驗 JSONL
- `run_fault_injection.py`（營運層 Phase 5）— 五個故障場景，每個場景一邊用固定併發打
  `/api/chat`、一邊以固定速率打 `/api/health`，兩者延遲分開記錄。**要看的是 health**——
  它被拖慢就代表 threadpool 被佔滿了
- `compare_loadtests.py`（營運層 Phase 5）— 把四個階段的負載測試 JSON 併成一張前後
  對照表（`reports/loadtest/comparison.md`）。**數字由程式產生，不手打**
- `loadtest/`（營運層 Phase 0/5）— k6 腳本（`api.js` 併發矩陣、`faults.js` 故障注入）
- `export_trace_sample.py`（營運層 Phase 2）— 跑一次完整 `POST /api/chat`，把 trace
  匯出成 JSON 存進 `reports/traces/`（commit 進 repo 的可觀測性證據）
- `publish_to_hf.py`（M7）— 發布到 Hugging Face Docker Space，**預設 dry-run**，
  要加 `--execute` 才會真的呼叫 HF API
- `git-hooks/`（M0）— repo 內建 git hooks（`just hooks` 啟用，勿用 `pre-commit install`）
