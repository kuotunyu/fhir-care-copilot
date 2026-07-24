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
