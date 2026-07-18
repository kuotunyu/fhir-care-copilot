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
