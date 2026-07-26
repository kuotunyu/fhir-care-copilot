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

# 後端開發伺服器(port 8000;先跑過一次 frontend-build 的話會一併 serve 前端)
backend-dev:
    uv run uvicorn fhir_copilot.api.app:app --reload --port 8000

# 一行指令啟動:build 前端 + 用同一個 process serve 前端與 API(port 8000)
run: frontend-build
    uv run uvicorn fhir_copilot.api.app:app --port 8000
