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

## 可觀測性(營運層 Phase 2)

| 動作 | 指令 |
|---|---|
| 起 Jaeger(dev-only) | `docker compose --profile dev up -d jaeger` → <http://localhost:16686> |
| 送 trace 過去 | 應用程式設 `OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318` |
| 產生 commit 用的 trace 樣本 | `uv run python scripts/export_trace_sample.py` |
| 看指標 | `curl http://localhost:8000/metrics` |

**踩過的坑**:

- Jaeger 的 trace 查詢 API **一定要帶時間範圍**,`?service=X&limit=5` 會回 0 筆,
  要寫成 `?service=X&limit=5&lookback=1h`。service 列表(`/api/services`)有東西
  就代表 span 真的送到了,不要因為 trace 查詢是空的就以為沒收到
- `configure_logging()` 接管 root logger 等於**連帶接管所有第三方函式庫的輸出**,
  而那些內容我們控制不了。PII 斷言測試第一次跑就抓到 httpx 把含 `patient_id` 的
  URL 記進日誌——第三方 logger 預設已壓到 WARNING,除錯時才用
  `FHIR_COPILOT_THIRD_PARTY_LOG_LEVEL=DEBUG` 打開
- 指標與 span 的路徑標籤**一律用 route 樣板**(`/api/patients/{patient_id}/summary`),
  用原始路徑會同時炸掉 cardinality 並把病患 id 寫進指標
- `/metrics` 必須在 `app.mount("/")` **之前**註冊,否則會被 `StaticFiles` 的
  catch-all 吃掉,而且症狀只是回 404 或前端首頁,不會有任何提示

## 稽核軌跡(營運層 Phase 4)

| 動作 | 指令 |
|---|---|
| 起 Postgres(db-only profile) | `docker compose --profile db up -d postgres` |
| 跑 Postgres 整合測試 | `DATABASE_URL=postgresql://copilot:copilot@localhost:5432/copilot uv run pytest tests/test_audit_postgres.py` |
| 驗證稽核鏈 | `uv run python scripts/verify_audit_chain.py`(exit 1 = 有問題) |
| 裝 postgres extra | `uv sync --extra postgres` |

**踩過的坑**:

- **`SELECT ... FOR UPDATE` 鎖不住「還沒出現的列」。** 用它鎖鏈尾看起來合理,
  但兩個併發 append 會各自鎖住同一列、然後都插入 `N+1` → 主鍵衝突;表是空的時候
  更徹底(沒有列可鎖)。要用 `pg_advisory_xact_lock` 鎖「append 這個動作」。
  **這個 bug 用 mock 測不到,一定要對真的 Postgres 跑**
- 沒有 `DATABASE_URL` 時 Postgres 測試會整組 skip——看到 `6 skipped` 是正常的,
  不是測試壞了
- `docker compose up` 預設**不會重建 image**。改了程式之後要 `--build`,
  否則會拿到舊的 image 而症狀是「新欄位不見了」

## 故障注入(營運層 Phase 3)

用 mock provider 的失敗率驗證重試、熔斷與結構化拒答:

```
FHIR_COPILOT_MOCK_FAILURE_RATE=1.0   # 100% 失敗
FHIR_COPILOT_MOCK_FAILURE_SEED=42    # 失敗序列可重現
```

**踩過的坑**:

- **逾時要下在 SDK,不要在外層包執行緒。** 包執行緒只能「不等它」,底層 HTTP 還在跑、
  執行緒殺不掉,等於把逾時變成 threadpool 洩漏——而 threadpool 飽和正是 Phase 0
  量到的瓶頸,那會讓事情更糟不是更好
- **`OpenAI` 的內建 `max_retries` 要關掉**(設 0),否則它會和外層的退避疊在一起,
  實際重試次數與間隔都算不出來
- **測熔斷要用腳本化的成功/失敗序列,不要用機率**。熔斷行為取決於失敗的**順序**,
  用隨機值會得到時好時壞的測試
- 包裝順序是 `ResilientProvider(InstrumentedProvider(真 provider))`。反過來的話
  trace 上只看得到最後一次嘗試,重試變成看不見的成本

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
