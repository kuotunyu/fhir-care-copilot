# scripts/

- `download_or_generate_synthea.py`（M1，已完成）— 下載官方 1K FHIR R4 樣本 + `--subset N`
  子集化（預設 100，deterministic 檔名排序）；`--generate --seed S --population P` 可用
  Java 17+ 固定 seed 本地生成；`--verify-only` 重新驗證現有子集
- `git-hooks/`（M0）— repo 內建 git hooks（`just hooks` 啟用，勿用 `pre-commit install`）

預計腳本（隨 milestone 建立）：
- eval CLI（M5–M6）— case 生成、執行、預算守門、報告產出
- `publish_to_hf.py`（M7）— 發布到 Hugging Face Docker Space,**預設 dry-run**
