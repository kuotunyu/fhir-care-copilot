"""每 key 限流(營運層 Phase 1)。

限流是**公平性**控制:一個呼叫者不該把服務吃光。它與每日預算上限
(帳號保護)是兩件不同的事,分別測。
"""

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from fhir_copilot.api import dependencies
from fhir_copilot.api.app import create_app
from fhir_copilot.ops.ratelimit import TokenBucketLimiter
from tests.conftest import AMY_ID, FIXTURES_DIR, clear_ops_env, write_ops_config

HEADER = "X-API-Key"
KEY_A = "key-aaa"
KEY_B = "key-bbb"

ClientFactory = Callable[..., TestClient]


@pytest.fixture
def make_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[ClientFactory]:
    clients: list[TestClient] = []

    def factory(*, requests_per_minute: int, burst: int) -> TestClient:
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
        monkeypatch.setenv("FHIR_COPILOT_API_KEYS", f"a:{KEY_A},b:{KEY_B}")
        dependencies.reset_caches()
        client = TestClient(create_app())
        clients.append(client)
        return client

    yield factory
    for client in clients:
        client.close()
    dependencies.reset_caches()


def chat(client: TestClient, key: str) -> Any:
    return client.post(
        "/api/chat",
        json={"patient_id": AMY_ID, "question": "他在吃什麼藥?"},
        headers={HEADER: key},
    )


class TestTokenBucket:
    """先單獨測演算法,再測它接進 HTTP 之後的行為。"""

    def test_burst_is_allowed_then_blocked(self) -> None:
        limiter = TokenBucketLimiter(requests_per_minute=60, burst=3)

        assert [limiter.acquire("x") for _ in range(3)] == [None, None, None]
        assert limiter.acquire("x") is not None

    def test_retry_after_is_at_least_one_second(self) -> None:
        """``Retry-After`` 回 0 等於叫呼叫者立刻重試,那不是有意義的建議。"""
        limiter = TokenBucketLimiter(requests_per_minute=60, burst=1)
        limiter.acquire("x")

        retry_after = limiter.acquire("x")

        assert retry_after is not None
        assert retry_after >= 1

    def test_identities_have_independent_buckets(self) -> None:
        limiter = TokenBucketLimiter(requests_per_minute=60, burst=1)
        limiter.acquire("a")

        assert limiter.acquire("b") is None

    def test_tokens_refill_over_time(self, monkeypatch: pytest.MonkeyPatch) -> None:
        limiter = TokenBucketLimiter(requests_per_minute=60, burst=1)
        clock = [1000.0]
        monkeypatch.setattr(limiter, "_now", lambda: clock[0])
        limiter.acquire("x")
        assert limiter.acquire("x") is not None

        clock[0] += 2.0  # 60 rpm = 每秒回填 1 個 token

        assert limiter.acquire("x") is None

    def test_rejects_nonsensical_configuration(self) -> None:
        with pytest.raises(ValueError):
            TokenBucketLimiter(requests_per_minute=0, burst=1)


class TestOverHttp:
    def test_exceeding_the_limit_returns_429_with_retry_after(
        self, make_client: ClientFactory
    ) -> None:
        client = make_client(requests_per_minute=60, burst=2)

        first = chat(client, KEY_A)
        second = chat(client, KEY_A)
        third = chat(client, KEY_A)

        assert first.status_code == 200
        assert second.status_code == 200
        assert third.status_code == 429
        body = third.json()
        assert body["error_code"] == "rate_limited"
        assert body["retry_after_seconds"] >= 1
        assert third.headers["Retry-After"] == str(body["retry_after_seconds"])
        assert isinstance(body["detail"], str)

    def test_each_key_has_its_own_budget_of_requests(self, make_client: ClientFactory) -> None:
        """一把 key 把自己的額度用光,不該影響另一把。"""
        client = make_client(requests_per_minute=60, burst=1)

        assert chat(client, KEY_A).status_code == 200
        assert chat(client, KEY_A).status_code == 429
        assert chat(client, KEY_B).status_code == 200

    def test_health_is_never_rate_limited(self, make_client: ClientFactory) -> None:
        """健康檢查被限流擋住的話,監控會在服務還活著的時候誤報死亡。"""
        client = make_client(requests_per_minute=60, burst=1)
        chat(client, KEY_A)
        chat(client, KEY_A)  # 這一發已經被擋

        for _ in range(5):
            assert client.get("/api/health").status_code == 200

    def test_care_note_endpoints_are_rate_limited_too(self, make_client: ClientFactory) -> None:
        client = make_client(requests_per_minute=60, burst=1)

        first = client.post(
            "/api/care-notes/propose",
            json={"patient_id": AMY_ID, "note_text": "測試"},
            headers={HEADER: KEY_A},
        )
        second = client.post(
            "/api/care-notes/propose",
            json={"patient_id": AMY_ID, "note_text": "測試"},
            headers={HEADER: KEY_A},
        )

        assert first.status_code == 200
        assert second.status_code == 429
