"""FastAPI app factory:掛 /api 路由,並在 app/dist 存在時 serve 前端靜態檔。"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from fhir_copilot.api.routes import router
from fhir_copilot.ops.errors import OpsRejection

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
FRONTEND_DIST = REPO_ROOT / "app" / "dist"


def create_app() -> FastAPI:
    app = FastAPI(
        title="FHIR Care Copilot",
        description="可追溯、工具受控、預設唯讀的長照個案查詢 agent(合成資料展示,非醫療診斷工具)",
    )

    @app.exception_handler(OpsRejection)
    async def _handle_ops_rejection(request: Request, exc: OpsRejection) -> JSONResponse:
        """營運層的拒絕 → 結構化 JSON,不是 500。

        ``detail`` 保持人類可讀的字串(前端 app/src/api.ts 直接拿它顯示),
        ``error_code`` 之類的結構化欄位放同一層——用 dict 塞進 detail 會讓前端
        顯示 [object Object]。
        """
        del request
        return JSONResponse(status_code=exc.status_code, content=exc.body(), headers=exc.headers())

    app.include_router(router)

    if FRONTEND_DIST.is_dir():
        # html=True:找不到對應檔案時退回 index.html,讓前端的 client-side routing 正常運作
        app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")

    return app


app = create_app()
