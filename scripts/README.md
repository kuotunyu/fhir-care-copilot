# scripts/

- `download_or_generate_synthea.py`（M1）— 下載官方 1K FHIR R4 樣本 + `--subset N`
  子集化（預設 100，deterministic 檔名排序）；`--generate --seed S --population P` 可用
  Java 17+ 固定 seed 本地生成；`--verify-only` 重新驗證現有子集
- `run_eval.py`（M5）— eval CLI：題目生成、跑 agent loop、算指標、預算守門
  （跑前估算超過上限即中止；執行中累計實際花費，超過即提前停止）
- `generate_model_comparison.py`（M6）— 把兩份 eval JSON 整理成
  `reports/model_comparison.md` 的一頁式比較報告
- `run_loadtest.py`（營運層 Phase 0）— 起後端、跑 k6 併發矩陣、收 summary，
  輸出到 `reports/loadtest/`
- `loadtest/`（營運層 Phase 0）— k6 腳本
- `publish_to_hf.py`（M7）— 發布到 Hugging Face Docker Space，**預設 dry-run**，
  要加 `--execute` 才會真的呼叫 HF API
- `git-hooks/`（M0）— repo 內建 git hooks（`just hooks` 啟用，勿用 `pre-commit install`）
