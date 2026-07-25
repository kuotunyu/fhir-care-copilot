---
name: dev-loop
description: FHIR Care Copilot 開發迴圈——環境同步、測試、lint、typecheck、pre-commit 指令,以及每個 session/milestone 的收尾 checklist。開始實作、跑測試、或收尾 milestone 時使用。
---

# dev-loop

## 日常指令

| 動作 | just | 直接指令 |
|---|---|---|
| 同步環境 | `just sync` | `uv sync` |
| 測試 | `just test` | `uv run pytest` |
| lint | `just lint` | `uv run ruff check .` + `uv run ruff format --check .` |
| 自動修排版 | `just fmt` | `uv run ruff check --fix .` + `uv run ruff format .` |
| 型別 | `just typecheck` | `uv run mypy` |
| 全套 | `just check` | 上面三項依序 |
| pre-commit | `just precommit` | `uv run pre-commit run --all-files` |
| 啟用 git hooks(一次) | `just hooks` | `git config core.hooksPath scripts/git-hooks` |

**勿用 `pre-commit install`**:它產生的 hook 會把 venv 路徑用 cp950 寫死,在本 repo 的中文路徑下會炸(ADR 0002)。repo 內建 hook 在 `scripts/git-hooks/`,用 `uv run` 不嵌絕對路徑。

注意:Windows 上 `just` 由 winget 安裝(`Casey.Just`),新開的 shell 才吃得到 PATH。

## 容器

| 動作 | 指令 |
|---|---|
| build image | `docker build -t fhir-care-copilot:local .` |
| 起容器(對外 8000) | `docker compose up -d` |
| 驗證 | `curl http://localhost:8000/api/health` → 應回 `demo_mode:true`、`patient_count:100` |
| 收掉 | `docker compose down` |

build 會下載 85 MB Synthea 樣本烤進 image,第一次約數分鐘。

**踩過的坑(2026-07-25 修掉,別再犯)**:

- `.dockerignore` 的 `*.md` 會連 `README.md` 一起排除,而 `pyproject.toml` 的 `readme` 欄位
  需要它才能 build wheel。被 `.dockerignore` 排除的檔案,**即使 `COPY` 明確列名也複製不進去**。
  已加 `!README.md` 例外。
- 容器內**不要用 `uv run`**:`uv sync` 是以 root 跑的,切成 `USER user` 後 `uv run` 會寫不進
  root 建立的 uv cache(Permission denied);而且它會補齊 dev 依賴,把 pytest/mypy 裝進正式 image。
  `ENV PATH` 已指向 `/app/.venv/bin`,直接用 `python` / `uvicorn` 就好。
- **「用等效方式驗證」會系統性地漏掉被繞過的那一層**。上面兩個 bug 都是在臨時目錄重現時
  測不到的(沒有經過 `.dockerignore`、沒有使用者切換)。驗證受阻時除了誠實記錄,
  還要記下**這個替代方式測不到什麼**。

## 負載測試

| 動作 | just | 說明 |
|---|---|---|
| 基線 | `just loadtest-baseline` | 輸出 `reports/loadtest/baseline-<日期>.{json,md}` |
| 對照 | `just loadtest-final` | 加完控制項之後重跑 |

需要 k6:`winget install --id GrafanaLabs.k6 -e`(新 shell 才吃得到 PATH;
`scripts/run_loadtest.py` 有 `C:\Program Files\k6\k6.exe` 的 fallback)。

- 參數全部在 `configs/ops.yaml` 的 `load_test` 區塊。**基線與對照必須用同一組參數**,否則不可比
- 整個矩陣約 30 分鐘,**期間機器不要跑別的東西**(跑測試、build 都會污染 p99)
- 量到的是**服務層**,不含真實 LLM 供應商延遲。兩軌數字在報表與 README 都要標清楚,不可混用

## session 開始

1. 讀 `PLAN.md` §3 checkbox 進度
2. 讀 `docs/PROGRESS.md` 最上面一節(最新)
3. 依 milestone 順序做,不跳關

## session / milestone 收尾 checklist

1. `just check`(或 `uv run pytest` 等)全綠——失敗就修,修不完照實記錄
2. `docs/PROGRESS.md` **最上方**新增一節:日期、做了什麼、**真實測試輸出**、決策/發現、下一步
3. milestone 全部驗收達成才勾 `PLAN.md` §3 checkbox
4. git commit(訊息格式:`M<N>: <摘要>`)
5. 有穩定下來的新流程 → 固化成 `.claude/skills/` 專案 skill
