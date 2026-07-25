"""每日成本上限(營運層 Phase 1)。

領域理由:``/api/chat`` 每次呼叫都花真錢。會被燒光的是**同一個 API 帳號的額度**,
所以這個計數是全域的,不是每個 key 各算各的(那是限流在管的公平性問題)。

沿用 ``eval/runner.py`` 的兩層守門語彙:跑前估算超過就擋、不花錢;執行中累計實際花費。
"""

from collections.abc import Callable, Iterator
from functools import lru_cache
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from fhir_copilot.api import dependencies
from fhir_copilot.api.app import create_app
from fhir_copilot.config import ModelPricing
from fhir_copilot.ops.budget import DailyBudget
from tests.conftest import AMY_ID, FIXTURES_DIR, clear_ops_env, write_ops_config

ClientFactory = Callable[..., TestClient]


@pytest.fixture
def make_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[ClientFactory]:
    clients: list[TestClient] = []

    def factory(*, daily_limit_usd: float = 1.0) -> TestClient:
        monkeypatch.setenv("FHIR_COPILOT_DATA_DIR", str(FIXTURES_DIR))
        monkeypatch.setenv("FHIR_COPILOT_PROVIDER", "mock")
        monkeypatch.setenv("FHIR_COPILOT_AUDIT_LOG_PATH", str(tmp_path / "care_notes.jsonl"))
        clear_ops_env(monkeypatch)
        monkeypatch.setenv(
            "FHIR_COPILOT_OPS_CONFIG",
            str(write_ops_config(tmp_path / "ops.yaml", daily_limit_usd=daily_limit_usd)),
        )
        dependencies.reset_caches()
        client = TestClient(create_app())
        clients.append(client)
        return client

    yield factory
    for client in clients:
        client.close()
    dependencies.reset_caches()


def chat(client: TestClient) -> Any:
    return client.post("/api/chat", json={"patient_id": AMY_ID, "question": "他在吃什麼藥?"})


class TestDailyBudgetUnit:
    def test_starts_empty(self) -> None:
        assert DailyBudget(daily_limit_usd=1.0).spent_today_usd() == 0.0

    def test_accumulates_actual_spend(self) -> None:
        budget = DailyBudget(daily_limit_usd=1.0)

        budget.record(0.01)
        budget.record(0.02)

        assert budget.spent_today_usd() == pytest.approx(0.03)

    def test_would_exceed_accounts_for_the_pending_request(self) -> None:
        """看的是「這一發打下去會不會超過」,不是「已經超過了沒」——
        後者等於允許最後一次請求無上限地超支。"""
        budget = DailyBudget(daily_limit_usd=1.0)
        budget.record(0.99)

        assert budget.would_exceed(0.005) is False
        assert budget.would_exceed(0.5) is True

    def test_resets_when_the_utc_day_rolls_over(self, monkeypatch: pytest.MonkeyPatch) -> None:
        budget = DailyBudget(daily_limit_usd=1.0)
        budget.record(0.5)

        monkeypatch.setattr(DailyBudget, "_today", staticmethod(lambda: "2099-01-01"))

        assert budget.spent_today_usd() == 0.0

    def test_seconds_until_reset_is_positive(self) -> None:
        assert DailyBudget.seconds_until_utc_midnight() >= 1


class TestOverHttp:
    def test_exceeding_the_budget_returns_429_not_500(self, make_client: ClientFactory) -> None:
        """預算用完是「已知的、預期內的」拒絕,不是伺服器壞了。"""
        client = make_client(daily_limit_usd=1.0)
        dependencies.get_budget().record(5.0)  # 模擬今天已經花掉 5 美元

        response = chat(client)

        assert response.status_code == 429
        body = response.json()
        assert body["error_code"] == "budget_exceeded"
        assert body["limit_usd"] == 1.0
        assert body["spent_usd"] == pytest.approx(5.0)
        assert isinstance(body["detail"], str)
        assert response.headers["Retry-After"] == str(body["retry_after_seconds"])

    def test_rejection_happens_before_any_provider_call(self, make_client: ClientFactory) -> None:
        """擋下來的請求不該產生任何花費——與 eval runner 的前置估算同一個原則。"""
        client = make_client(daily_limit_usd=1.0)
        budget = dependencies.get_budget()
        budget.record(5.0)

        chat(client)

        assert budget.spent_today_usd() == pytest.approx(5.0)  # 沒有再增加

    def test_actual_cost_is_recorded_after_a_successful_chat(
        self, make_client: ClientFactory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """驗證「回應的實際成本有被記進計數」這條接線。

        mock provider 的成本固定是 0 元,單看數字看不出有沒有記,
        所以直接攔截 record 看它有沒有被呼叫、被呼叫時拿到什麼。
        """
        client = make_client()
        recorded: list[float] = []
        monkeypatch.setattr(dependencies.get_budget(), "record", recorded.append)

        response = chat(client)

        assert response.status_code == 200
        assert recorded == [response.json()["estimated_cost_usd"]]

    def test_health_reports_budget_state(self, make_client: ClientFactory) -> None:
        client = make_client(daily_limit_usd=2.5)
        dependencies.get_budget().record(0.25)

        body = client.get("/api/health").json()

        assert body["budget_limit_usd"] == 2.5
        assert body["budget_spent_usd_today"] == pytest.approx(0.25)
        # 記憶體計數會在重啟時歸零,所以必須讓看的人知道是從何時起算
        assert body["budget_counting_since"]

    def test_missing_price_raises_instead_of_silently_costing_zero(
        self, make_client: ClientFactory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """單價缺了就炸,不要默默當 0 元。

        成本算不出來比程式炸還危險——默默當 0 元會讓預算上限變成裝飾品。
        這是 config.estimate_cost_usd 的既有哲學,守門這一層不准把它 catch 掉。
        """
        client = make_client()
        # 替身要保留 lru_cache 的介面:reset_caches() 會對它呼叫 cache_clear()
        empty_pricing = lru_cache(lambda: dict[str, ModelPricing]())
        monkeypatch.setattr(dependencies, "get_pricing", empty_pricing)

        with pytest.raises(KeyError):
            chat(client)
