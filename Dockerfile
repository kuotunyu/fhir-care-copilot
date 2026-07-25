# ---- Stage 1:前端 build(Vite production build) ----
FROM node:24-slim AS frontend-builder
WORKDIR /build/app
COPY app/package.json app/package-lock.json ./
RUN npm ci
COPY app/ ./
RUN npm run build

# ---- Stage 2:Python runtime ----
FROM python:3.13-slim AS runtime

# HF Docker Space 要求以 UID 1000 執行,且 WORKDIR 要在 COPY 前設好(PLAN.md §7 查證)
RUN useradd -m -u 1000 user
WORKDIR /app
RUN chown user:user /app

# 官方建議的 uv 安裝方式:直接從 uv 的 distroless image 複製執行檔
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

ENV HOME=/home/user \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

# uv sync 會把本專案自己(pyproject.toml 的 [project])一併建置成套件,
# hatchling 需要讀到 README.md(readme 欄位)與 src/fhir_copilot/(packages 欄位)
# 才能成功 build——三者必須在 uv sync 之前一起複製進來,不能只複製
# pyproject.toml/uv.lock 就先跑 sync(本機用 tmp 目錄重現過,少了 src/ 會直接
# build 失敗:「Readme file does not exist」)。
COPY --chown=user pyproject.toml uv.lock README.md ./
COPY --chown=user src/ ./src/
RUN uv sync --locked --no-dev

COPY --chown=user configs/ ./configs/
COPY --chown=user scripts/ ./scripts/
COPY --chown=user --from=frontend-builder /build/app/dist ./app/dist

USER user

# build 時先下載一份 100 位病患的 demo 資料,烤進 image——沒有 API 金鑰時
# provider 會自動退回 mock demo mode(見 src/fhir_copilot/api/dependencies.py),
# 訪客一開容器就能看到真實(合成)資料,不用等 runtime 才下載
#
# 這裡直接用 venv 裡的 python(PATH 已指向 /app/.venv/bin),不走 `uv run`,理由有二:
# 1. 上面的 uv sync 是以 root 執行的,會把 uv cache 建在 root 名下;切成 USER user
#    之後 `uv run` 要寫同一個 cache 會 Permission denied(實測 exit code 2)
# 2. `uv run` 預設會補齊 dev 依賴——那會把 pytest/mypy/ruff 裝進正式 image
RUN python scripts/download_or_generate_synthea.py --subset 100 \
    && rm -rf data/raw

ENV FHIR_COPILOT_DATA_DIR=/app/data/processed/subset_100

# HF Docker Space 預設對外埠是 7860(PLAN.md §7 查證)
EXPOSE 7860

# 同樣直接用 venv 裡的 uvicorn,不走 `uv run`:容器啟動時不該再嘗試解析依賴、
# 不該需要網路,也不該把 dev 依賴補進來。環境已經由 uv sync --locked --no-dev 定死。
CMD ["uvicorn", "fhir_copilot.api.app:app", "--host", "0.0.0.0", "--port", "7860"]
