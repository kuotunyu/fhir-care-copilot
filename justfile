# FHIR Care Copilot 任務指令(沒裝 just 也可直接執行右側的 uv 指令)

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

# 前端裝依賴
frontend-install:
    cd app && npm install

# 前端開發伺服器(port 5173,自動把 /api proxy 到本機 8000 的 FastAPI)
frontend-dev:
    cd app && npm run dev

# 前端 production build(輸出 app/dist,給 FastAPI serve)
frontend-build:
    cd app && npm run build

# 後端開發伺服器(port 8000;先跑過一次 frontend-build 的話會一併 serve 前端)
backend-dev:
    uv run uvicorn fhir_copilot.api.app:app --reload --port 8000

# 一行指令啟動:build 前端 + 用同一個 process serve 前端與 API(port 8000)
run: frontend-build
    uv run uvicorn fhir_copilot.api.app:app --port 8000
