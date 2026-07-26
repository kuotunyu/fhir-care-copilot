# FHIR Care Copilot 任務指令(沒裝 just 也可直接執行右側的 uv 指令)

# Windows 上 just 預設會去找 sh 執行每條指令,但一般 Windows PowerShell 環境
# 沒有內建 sh(只有裝 Git for Windows 才有,且不一定在 PATH 上)——改用系統
# 內建的 powershell.exe,不依賴額外安裝。recipe body 一律避免用 `&&` 串指令
# (Windows PowerShell 5.1 不支援 `&&`;下面前端相關 recipe 改用 npm --prefix
# 取代 `cd app && ...`,原因見那幾條 recipe 上的註解)。
set windows-shell := ["powershell.exe", "-NoLogo", "-Command"]

default: check

# 建立/同步開發環境
sync:
    uv sync

# 跑測試
test:
    uv run pytest

# Lint
lint:
    uv run ruff check .
    uv run ruff format --check .

# 自動修 lint + 排版
fmt:
    uv run ruff check --fix .
    uv run ruff format .

# 型別檢查
typecheck:
    uv run mypy

# lint + typecheck + test 一次跑完
check: lint typecheck test

# pre-commit 全檔跑一次
precommit:
    uv run pre-commit run --all-files

# 啟用 repo 內建 git hooks(勿用 pre-commit install,見 ADR 0002)
hooks:
    git config core.hooksPath scripts/git-hooks

# 產生 README 的介面截圖(需要 `uv sync --extra screenshots` 與
# `uv run playwright install chromium`)。先 build 前端,否則截到空白頁。
screenshots: frontend-build
    uv run python scripts/capture_screenshots.py

# ---- 營運層:Postgres 稽核後端 ----

# 對**真的** Postgres 跑稽核軌跡的整合測試(等同 CI 的 postgres job)。
#
# 為什麼要有這條:`just check` 沒有 DATABASE_URL,這一組會被靜靜跳過。
# **「N skipped」不是綠燈,是「這幾件事還沒測」**——改過 ops/audit/postgres.py
# 之後只跑 `just check` 就宣稱通過,等於沒測到唯一會用它的那條路徑。
# 這條 recipe 存在的理由是一次真實的回歸:建表改成惰性之後本機全綠,CI 上
# 六個測試全掛。
check-db:
    docker compose --profile db up -d --wait postgres
    $env:DATABASE_URL = "postgresql://copilot:copilot@localhost:5432/copilot"; uv run pytest tests/test_audit_postgres.py -v
    $env:DATABASE_URL = "postgresql://copilot:copilot@localhost:5432/copilot"; uv run python scripts/verify_audit_chain.py

# 收掉本機的測試資料庫
check-db-down:
    docker compose --profile db down -v

# ---- 營運層:負載測試 ----

# 負載測試基線(需要 k6:winget install --id GrafanaLabs.k6 -e)。
# 自己起一個 uvicorn、跑完 configs/ops.yaml 定義的整個併發矩陣、輸出到
# reports/loadtest/。約需 30 分鐘,期間機器盡量不要跑別的東西。
loadtest-baseline:
    uv run python scripts/run_loadtest.py --label baseline

# 加完控制項之後的對照組。**必須用同一份 configs/ops.yaml**,否則兩組數字不可比。
loadtest-final:
    uv run python scripts/run_loadtest.py --label final

# 故障注入場景表:五個場景各自一邊打爆 /api/chat、一邊固定速率打 /api/health。
# 要看的是 health——它被拖慢就代表 threadpool 被佔滿了。約需 5 分鐘。
loadtest-faults:
    uv run python scripts/run_fault_injection.py

# 把已有的四個階段併成一張前後對照表。數字由程式產生,不手打。
loadtest-compare:
    uv run python scripts/compare_loadtests.py

# ---- M4:前端(app/) ----

# 前端裝依賴(用 --prefix 而非 cd app:just 預設每行是獨立殼層呼叫,
# cd 不會延續到下一行,--prefix 才能真正跨殼層可靠切換目錄)
frontend-install:
    npm --prefix app install

# 前端開發伺服器(port 5173,自動把 /api proxy 到本機 8000 的 FastAPI)
frontend-dev:
    npm --prefix app run dev

# 前端 production build(輸出 app/dist,給 FastAPI serve)
frontend-build:
    npm --prefix app run build

# 前端單元測試(vitest + @testing-library/react)
frontend-test:
    npm --prefix app run test

# 前端全套:lint + 單元測試 + build(build 含 tsc -b 的型別檢查)
# 刻意**不掛進 `just check`**——後端的 check 要能在沒裝 node_modules 的機器上跑完,
# 而且它是 pre-commit 會用到的路徑。前端要驗就明確跑這一條,CI 兩邊都跑。
frontend-check: frontend-test
    npm --prefix app run lint
    npm --prefix app run build

# 後端開發伺服器(port 8000;先跑過一次 frontend-build 的話會一併 serve 前端)
backend-dev:
    uv run uvicorn fhir_copilot.api.app:app --reload --port 8000

# 一行指令啟動:build 前端 + 用同一個 process serve 前端與 API(port 8000)
run: frontend-build
    uv run uvicorn fhir_copilot.api.app:app --port 8000
