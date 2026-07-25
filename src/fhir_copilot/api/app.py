"""FastAPI app factory:掛 /api 路由與可觀測性,並在 app/dist 存在時 serve 前端靜態檔。"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from fhir_copilot.api.dependencies import get_metrics
from fhir_copilot.api.routes import router
from fhir_copilot.ops import metrics as metrics_module
from fhir_copilot.ops.errors import OpsRejection
from fhir_copilot.ops.logging import configure_logging
from fhir_copilot.ops.middleware import ObservabilityMiddleware
from fhir_copilot.ops.tracing import configure_tracing

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
FRONTEND_DIST = REPO_ROOT / "app" / "dist"


def create_app() -> FastAPI:
    configure_logging()
    configure_tracing()
    metrics = get_metrics()

    app = FastAPI(
        title="FHIR Care Copilot",
        description="可追溯、工具受控、預設唯讀的長照個案查詢 agent(合成資料展示,非醫療診斷工具)",
    )
    app.add_middleware(ObservabilityMiddleware, metrics=metrics)

    @app.exception_handler(OpsRejection)
    async def _handle_ops_rejection(request: Request, exc: OpsRejection) -> JSONResponse:
        """營運層的拒絕 → 結構化 JSON,不是 500。

        ``detail`` 保持人類可讀的字串(前端 app/src/api.ts 直接拿它顯示),
        ``error_code`` 之類的結構化欄位放同一層——用 dict 塞進 detail 會讓前端
        顯示 [object Object]。
        """
        del request
        metrics.rejections.labels(exc.error_code).inc()
        return JSONResponse(status_code=exc.status_code, content=exc.body(), headers=exc.headers())

    @app.get("/metrics", include_in_schema=False)
    def prometheus_metrics(request: Request) -> Response:
        """Prometheus scrape 端點。

        **刻意不掛 Phase 1 的守門**:scrape 是每 15 秒一次的自動流量,套上
        API key 認證與限流會直接把它打壞。改用可選的 metrics token
        (沒設就開放,見 ops/metrics.py 的說明)。
        """
        if not metrics_module.token_is_valid(request.headers.get("Authorization")):
            return Response(status_code=401, content="metrics token 無效或未提供\n")
        metrics.budget_spent.set(_budget_spent_today())
        return Response(content=metrics.render(), media_type=metrics_module.CONTENT_TYPE)

    app.include_router(router)

    # StaticFiles 掛在 "/" 是 catch-all,一定要最後掛——在它之前註冊的路由
    # (含上面的 /metrics)才不會被它吃掉
    if FRONTEND_DIST.is_dir():
        # html=True:找不到對應檔案時退回 index.html,讓前端的 client-side routing 正常運作
        app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")

    return app


def _budget_spent_today() -> float:
    from fhir_copilot.api.dependencies import get_budget

    return get_budget().spent_today_usd()


app = create_app()
