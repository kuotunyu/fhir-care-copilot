"""FastAPI app factory:掛 /api 路由,並在 app/dist 存在時 serve 前端靜態檔。"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from fhir_copilot.api.routes import router

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
FRONTEND_DIST = REPO_ROOT / "app" / "dist"


def create_app() -> FastAPI:
    app = FastAPI(
        title="FHIR Care Copilot",
        description="可追溯、工具受控、預設唯讀的長照個案查詢 agent(合成資料展示,非醫療診斷工具)",
    )
    app.include_router(router)

    if FRONTEND_DIST.is_dir():
        # html=True:找不到對應檔案時退回 index.html,讓前端的 client-side routing 正常運作
        app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")

    return app


app = create_app()
