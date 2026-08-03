"""request ID 與 ``/metrics``(營運層 Phase 2)。

PII 的部分在 ``tests/test_pii_redaction.py``,那是這個 Phase 最重要的一條線。
這裡測的是可觀測性本身能不能用:同一個請求串不串得起來、指標吐不吐得出來。
"""

import json
import logging
import re
from collections.abc import Callable, Iterator
from io import StringIO
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from fhir_copilot.api import dependencies
from fhir_copilot.api.app import create_app
from fhir_copilot.ops import metrics as metrics_module
from fhir_copilot.ops import middleware as middleware_module
from fhir_copilot.ops import tracing
from fhir_copilot.ops.logging import JsonFormatter
from fhir_copilot.ops.middleware import REQUEST_ID_HEADER
from tests.conftest import AMY_ID, FIXTURES_DIR, clear_ops_env, write_ops_config

ClientFactory = Callable[..., TestClient]


@pytest.fixture
def make_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[ClientFactory]:
    clients: list[TestClient] = []

    def factory(
        *, metrics_token: str | None = None, requests_per_minute: int = 600, burst: int = 600
    ) -> TestClient:
        monkeypatch.setenv("FHIR_COPILOT_DATA_DIR", str(FIXTURES_DIR))
        monkeypatch.setenv("FHIR_COPILOT_PROVIDER", "mock")
        monkeypatch.setenv("FHIR_COPILOT_AUDIT_LOG_PATH", str(tmp_path / "care_notes.jsonl"))
        clear_ops_env(monkeypatch)
        monkeypatch.setenv(
            "FHIR_COPILOT_OPS_CONFIG",
            str(
                write_ops_config(
                    tmp_path / "ops.yaml", requests_per_minute=requests_per_minute, burst=burst
                )
            ),
        )
        monkeypatch.delenv(metrics_module.METRICS_TOKEN_ENV, raising=False)
        if metrics_token is not None:
            monkeypatch.setenv(metrics_module.METRICS_TOKEN_ENV, metrics_token)
        dependencies.reset_caches()
        client = TestClient(create_app())
        clients.append(client)
        return client

    yield factory
    for client in clients:
        client.close()
    tracing.reset_for_tests()
    dependencies.reset_caches()


def captured_logs(client: TestClient, make_request: Callable[[], Any]) -> list[dict[str, Any]]:
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.addHandler(handler)
    try:
        make_request()
    finally:
        root.removeHandler(handler)
    return [json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]


class TestRequestId:
    def test_response_carries_a_request_id(self, make_client: ClientFactory) -> None:
        response = make_client().get("/api/health")

        assert response.headers[REQUEST_ID_HEADER]

    def test_incoming_request_id_is_reused(self, make_client: ClientFactory) -> None:
        """呼叫端帶進來的 id 要沿用,才能跨服務串起同一條鏈。"""
        response = make_client().get("/api/health", headers={REQUEST_ID_HEADER: "trace-me-123"})

        assert response.headers[REQUEST_ID_HEADER] == "trace-me-123"

    @pytest.mark.parametrize(
        "malicious",
        (
            "line1\nline2",
            '{"patient":"Amy002"}',
            "x" * 65,
            "病患識別碼",
            "contains spaces",
        ),
    )
    def test_invalid_request_id_is_replaced(self, malicious: str) -> None:
        normalize = getattr(middleware_module, "normalize_request_id", lambda value: value)
        normalized = normalize(malicious)

        assert normalized != malicious
        assert re.fullmatch(r"[A-Za-z0-9._-]{1,64}", normalized)

    def test_invalid_request_id_is_not_echoed_to_response_or_logs(
        self, make_client: ClientFactory
    ) -> None:
        malicious = '{"patient":"Amy002"}'
        client = make_client()
        response_holder: list[Any] = []

        lines = captured_logs(
            client,
            lambda: response_holder.append(
                client.get("/api/health", headers={REQUEST_ID_HEADER: malicious})
            ),
        )

        response_id = response_holder[0].headers[REQUEST_ID_HEADER]
        assert response_id != malicious
        assert re.fullmatch(r"[A-Za-z0-9._-]{1,64}", response_id)
        assert malicious not in json.dumps(lines, ensure_ascii=False)

    def test_every_log_line_of_one_request_shares_the_id(self, make_client: ClientFactory) -> None:
        """同一個請求的所有日誌行帶同一個 id——這是事後查案唯一的線索。"""
        client = make_client()

        lines = captured_logs(
            client,
            lambda: client.post(
                "/api/chat",
                json={"patient_id": AMY_ID, "question": "他在吃什麼藥?"},
                headers={REQUEST_ID_HEADER: "one-request"},
            ),
        )

        ours = [line for line in lines if line["logger"].startswith("fhir_copilot")]
        assert ours, "沒有捕捉到應用程式自己的日誌"
        assert {line["request_id"] for line in ours} == {"one-request"}

    def test_separate_requests_get_separate_ids(self, make_client: ClientFactory) -> None:
        client = make_client()

        first = client.get("/api/health").headers[REQUEST_ID_HEADER]
        second = client.get("/api/health").headers[REQUEST_ID_HEADER]

        assert first != second


class TestMetricsEndpoint:
    def test_exposes_the_documented_metrics(self, make_client: ClientFactory) -> None:
        client = make_client()
        client.post("/api/chat", json={"patient_id": AMY_ID, "question": "他在吃什麼藥?"})

        body = client.get("/metrics").text

        assert "fhir_copilot_http_requests_total" in body
        assert "fhir_copilot_http_request_duration_seconds" in body
        assert "fhir_copilot_provider_errors_total" in body
        assert "fhir_copilot_refusals_total" in body
        assert "fhir_copilot_budget_spent_usd_today" in body

    def test_route_label_uses_the_template_not_the_raw_path(
        self, make_client: ClientFactory
    ) -> None:
        """原始路徑含 patient_id:那會同時炸掉 cardinality 並把病患識別碼寫進指標。"""
        client = make_client()
        client.get(f"/api/patients/{AMY_ID}/summary")

        body = client.get("/metrics").text

        assert "/api/patients/{patient_id}/summary" in body
        assert AMY_ID not in body

    def test_refusals_are_counted(self, make_client: ClientFactory) -> None:
        client = make_client()
        client.post("/api/chat", json={"patient_id": "no-such-patient", "question": "藥?"})

        body = client.get("/metrics").text

        assert 'fhir_copilot_refusals_total{reason="資料不足或查無此病患,無法回答。"} 1.0' in body

    def test_ops_rejections_are_counted(self, make_client: ClientFactory) -> None:
        """真的把限流打到 429,再確認計數器有跳——只斷言「指標名稱存在」
        是驗不到接線的,那種測試永遠是綠的。"""
        client = make_client(requests_per_minute=60, burst=1)
        body_json = {"patient_id": AMY_ID, "question": "他在吃什麼藥?"}

        assert client.post("/api/chat", json=body_json).status_code == 200
        assert client.post("/api/chat", json=body_json).status_code == 429

        body = client.get("/metrics").text

        assert 'fhir_copilot_ops_rejections_total{error_code="rate_limited"} 1.0' in body

    def test_is_not_rate_limited_or_authenticated_by_default(
        self, make_client: ClientFactory
    ) -> None:
        """scrape 是每 15 秒一次的自動流量;套上 Phase 1 的守門會直接打壞它。"""
        client = make_client()

        for _ in range(30):
            assert client.get("/metrics").status_code == 200


class TestMetricsToken:
    def test_open_when_no_token_is_configured(self, make_client: ClientFactory) -> None:
        assert make_client().get("/metrics").status_code == 200

    def test_requires_bearer_token_when_configured(self, make_client: ClientFactory) -> None:
        client = make_client(metrics_token="scrape-me")

        assert client.get("/metrics").status_code == 401
        assert client.get("/metrics", headers={"Authorization": "Bearer wrong"}).status_code == 401
        ok = client.get("/metrics", headers={"Authorization": "Bearer scrape-me"})
        assert ok.status_code == 200

    def test_rejects_non_bearer_schemes(self, make_client: ClientFactory) -> None:
        client = make_client(metrics_token="scrape-me")

        response = client.get("/metrics", headers={"Authorization": "Basic scrape-me"})

        assert response.status_code == 401


class TestStaticFilesDoNotSwallowMetrics:
    def test_metrics_is_registered_before_the_catch_all_mount(
        self, make_client: ClientFactory
    ) -> None:
        """``StaticFiles`` 掛在 "/" 是 catch-all。註冊順序錯了 /metrics 會被它吃掉,
        而且症狀是回 404 或前端 index.html——不會有任何錯誤訊息提示原因。"""
        response = make_client().get("/metrics")

        assert response.status_code == 200
        assert "fhir_copilot_http_requests_total" in response.text
