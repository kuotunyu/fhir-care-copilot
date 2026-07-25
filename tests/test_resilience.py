"""韌性:單次呼叫重試、熔斷、結構化拒答(營運層 Phase 3)。

領域理由:外部 LLM provider 會超時、會 429、會回垃圾。provider 掛掉時,每個
進來的請求都會等滿單次逾時才失敗;7 個端點全是同步 ``def`` 跑在 40 個
threadpool slot 上,不到 10 秒整個 threadpool 就被卡死的請求佔滿,連
``/api/health`` 都排不進去。熔斷的目的是**壞掉的時候快速失敗**。
"""

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from fhir_copilot.api import dependencies
from fhir_copilot.api.app import create_app
from fhir_copilot.ops.circuit import CircuitBreaker, CircuitOpenError, CircuitState
from fhir_copilot.ops.config import ResilienceConfig
from fhir_copilot.ops.resilience import ProviderUnavailableError, ResilientProvider, is_retryable
from fhir_copilot.providers.base import ProviderStep
from fhir_copilot.providers.mock import MockProvider, MockProviderFailure
from fhir_copilot.tools import READ_ONLY_TOOLS
from tests.conftest import AMY_ID, FIXTURES_DIR, clear_ops_env, write_ops_config

ClientFactory = Callable[..., TestClient]


def make_config(**overrides: Any) -> ResilienceConfig:
    base = {
        "provider_timeout_seconds": 12.0,
        "max_retries": 2,
        "backoff_initial_seconds": 0.001,
        "backoff_multiplier": 2.0,
        "backoff_max_seconds": 0.005,
        "failure_threshold": 3,
        "recovery_seconds": 30.0,
        "half_open_successes": 2,
    }
    base.update(overrides)
    return ResilienceConfig.model_validate(base)


class ScriptedProvider:
    """依腳本決定每次呼叫成功或失敗。

    比 MockProvider 的機率式失敗更適合測狀態機——熔斷的行為取決於**失敗的順序**,
    用隨機值測會得到時好時壞的測試。
    """

    model_id = "mock-deterministic"

    def __init__(self, outcomes: list[bool]) -> None:
        self._outcomes = list(outcomes)
        self.calls = 0

    def _next(self) -> ProviderStep:
        self.calls += 1
        succeed = self._outcomes.pop(0) if self._outcomes else True
        if not succeed:
            raise MockProviderFailure
        return ProviderStep(
            state=None, tool_calls=(), final_answer="ok", input_tokens=1, output_tokens=1
        )

    def start(self, **kwargs: Any) -> ProviderStep:
        return self._next()

    def continue_with_tool_results(self, state: Any, outcomes: Any) -> ProviderStep:
        return self._next()


def wrap(provider: Any, breaker: CircuitBreaker, **config_overrides: Any) -> ResilientProvider:
    return ResilientProvider(provider, make_config(**config_overrides), breaker)


def call(provider: ResilientProvider) -> ProviderStep:
    return provider.start(system_prompt="s", user_message="m", tool_specs=READ_ONLY_TOOLS)


def new_breaker(**overrides: Any) -> CircuitBreaker:
    kwargs: dict[str, Any] = {
        "failure_threshold": 3,
        "recovery_seconds": 30.0,
        "half_open_successes": 2,
    }
    kwargs.update(overrides)
    return CircuitBreaker(**kwargs)


class TestRetryableClassification:
    """把所有例外都重試會做兩件壞事:把必然再失敗的錯誤重打三次(白花錢),
    以及把程式 bug 藏在重試後面看不見。"""

    @pytest.mark.parametrize(
        "exc",
        [
            TimeoutError("boom"),
            ConnectionError("boom"),
            RuntimeError("request timed out"),
            RuntimeError("rate limit exceeded"),
            RuntimeError("upstream returned 503"),
        ],
    )
    def test_transient_failures_are_retryable(self, exc: Exception) -> None:
        assert is_retryable(exc) is True

    @pytest.mark.parametrize(
        "exc",
        [ValueError("invalid schema"), KeyError("missing price"), TypeError("bad argument")],
    )
    def test_deterministic_failures_are_not_retryable(self, exc: Exception) -> None:
        assert is_retryable(exc) is False


class TestRetry:
    def test_retries_then_succeeds(self) -> None:
        provider = ScriptedProvider([False, True])

        step = call(wrap(provider, new_breaker()))

        assert step.final_answer == "ok"
        assert provider.calls == 2

    def test_gives_up_after_max_retries(self) -> None:
        provider = ScriptedProvider([False, False, False, False])

        with pytest.raises(ProviderUnavailableError):
            call(wrap(provider, new_breaker(), max_retries=2))

        assert provider.calls == 3  # 首次 + 2 次重試

    def test_does_not_retry_deterministic_failures(self) -> None:
        """輸入有問題重打三次只是白花錢。"""

        class BadInputProvider(ScriptedProvider):
            def _next(self) -> ProviderStep:
                self.calls += 1
                raise ValueError("invalid schema")

        provider = BadInputProvider([])

        with pytest.raises(ProviderUnavailableError):
            call(wrap(provider, new_breaker()))

        assert provider.calls == 1

    def test_each_retry_reports_cost(self) -> None:
        """重試可能在 provider 端已經產生 token,我們觀測不到——所以每次重試
        都補記一筆估算成本,寧可高估也不要讓一次請求偷偷花三倍錢。"""
        provider = ScriptedProvider([False, False, True])
        charged: list[int] = []
        resilient = ResilientProvider(
            provider, make_config(), new_breaker(), on_retry=lambda: charged.append(1)
        )

        call(resilient)

        assert len(charged) == 2  # 兩次重試各記一筆


class TestCircuitBreaker:
    def test_opens_after_consecutive_failures(self) -> None:
        breaker = new_breaker(failure_threshold=3)
        provider = ScriptedProvider([False] * 20)
        resilient = wrap(provider, breaker, max_retries=0)

        for _ in range(3):
            with pytest.raises(ProviderUnavailableError):
                call(resilient)

        assert breaker.state is CircuitState.OPEN

    def test_open_circuit_fails_fast_without_calling_provider(self) -> None:
        """熔斷的重點:壞掉的時候**不要再打 provider**,否則每個請求都卡滿逾時,
        threadpool 很快就被佔滿(Phase 0 量到的飽和點)。"""
        breaker = new_breaker(failure_threshold=1)
        provider = ScriptedProvider([False] * 20)
        resilient = wrap(provider, breaker, max_retries=0)

        with pytest.raises(ProviderUnavailableError):
            call(resilient)
        calls_after_open = provider.calls

        with pytest.raises(ProviderUnavailableError):
            call(resilient)

        assert provider.calls == calls_after_open  # 完全沒有再打出去

    def test_success_resets_the_failure_streak(self) -> None:
        """看的是**連續**失敗。偶發失敗不該累積成熔斷。"""
        breaker = new_breaker(failure_threshold=3)
        provider = ScriptedProvider([False, True, False, True, False, True])
        resilient = wrap(provider, breaker, max_retries=0)

        for _ in range(3):
            with pytest.raises(ProviderUnavailableError):
                call(resilient)
            call(resilient)

        assert breaker.state is CircuitState.CLOSED

    def test_half_open_after_recovery_window(self, monkeypatch: pytest.MonkeyPatch) -> None:
        breaker = new_breaker(failure_threshold=1, recovery_seconds=30.0)
        clock = [1000.0]
        monkeypatch.setattr(breaker, "_now", lambda: clock[0])
        provider = ScriptedProvider([False, True, True])
        resilient = wrap(provider, breaker, max_retries=0)

        with pytest.raises(ProviderUnavailableError):
            call(resilient)
        after_failure = breaker.state
        clock[0] += 31.0
        call(resilient)  # 探路成功
        after_probe = breaker.state

        assert after_failure is CircuitState.OPEN
        assert after_probe is CircuitState.HALF_OPEN  # 還要再成功一次才關回去

    def test_closes_after_enough_half_open_successes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        breaker = new_breaker(failure_threshold=1, recovery_seconds=30.0, half_open_successes=2)
        clock = [1000.0]
        monkeypatch.setattr(breaker, "_now", lambda: clock[0])
        provider = ScriptedProvider([False, True, True])
        resilient = wrap(provider, breaker, max_retries=0)

        with pytest.raises(ProviderUnavailableError):
            call(resilient)
        clock[0] += 31.0
        call(resilient)
        call(resilient)

        assert breaker.state is CircuitState.CLOSED

    def test_half_open_failure_reopens_immediately(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """探路失敗要立刻回到 open 並重新計時,不能再放第二個請求進去試。"""
        breaker = new_breaker(failure_threshold=1, recovery_seconds=30.0)
        clock = [1000.0]
        monkeypatch.setattr(breaker, "_now", lambda: clock[0])
        provider = ScriptedProvider([False, False])
        resilient = wrap(provider, breaker, max_retries=0)

        with pytest.raises(ProviderUnavailableError):
            call(resilient)
        clock[0] += 31.0
        with pytest.raises(ProviderUnavailableError):
            call(resilient)

        assert breaker.state is CircuitState.OPEN

    def test_half_open_lets_only_one_probe_through(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """半開時放一整批請求出去,會在 provider 還沒好的時候再把它打垮一次——
        這是熔斷器最常見的實作錯誤。"""
        breaker = new_breaker(failure_threshold=1, recovery_seconds=30.0)
        clock = [1000.0]
        monkeypatch.setattr(breaker, "_now", lambda: clock[0])
        breaker.record_failure(CircuitState.CLOSED)
        clock[0] += 31.0

        first = breaker.try_acquire()  # 探路的那一個
        assert first is CircuitState.HALF_OPEN

        with pytest.raises(CircuitOpenError):
            breaker.try_acquire()  # 第二個要被擋下來

    def test_rejects_nonsensical_configuration(self) -> None:
        with pytest.raises(ValueError):
            CircuitBreaker(failure_threshold=0, recovery_seconds=1.0, half_open_successes=1)


class TestMockFailureInjection:
    def test_defaults_to_never_failing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """預設 0.0——行為與沒有這個功能時完全相同。"""
        monkeypatch.delenv("FHIR_COPILOT_MOCK_FAILURE_RATE", raising=False)

        assert MockProvider().failure_rate == 0.0

    def test_always_fails_at_rate_one(self) -> None:
        provider = MockProvider(failure_rate=1.0)

        with pytest.raises(MockProviderFailure):
            provider.start(system_prompt="s", user_message="m", tool_specs=READ_ONLY_TOOLS)

    def test_failure_sequence_is_reproducible_with_a_seed(self) -> None:
        """故障注入場景要能重跑才有意義。"""

        def sequence() -> list[bool]:
            provider = MockProvider(failure_rate=0.5, failure_seed=42)
            results = []
            for _ in range(20):
                try:
                    provider.start(system_prompt="s", user_message="m", tool_specs=READ_ONLY_TOOLS)
                    results.append(True)
                except MockProviderFailure:
                    results.append(False)
            return results

        assert sequence() == sequence()

    def test_injected_failure_is_classified_as_retryable(self) -> None:
        """注入的目的是要走完整條重試與熔斷路徑,所以它必須被判定為可重試。"""
        assert is_retryable(MockProviderFailure()) is True


@pytest.fixture
def make_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[ClientFactory]:
    clients: list[TestClient] = []

    def factory(*, failure_rate: float = 1.0, **ops: Any) -> TestClient:
        monkeypatch.setenv("FHIR_COPILOT_DATA_DIR", str(FIXTURES_DIR))
        monkeypatch.setenv("FHIR_COPILOT_PROVIDER", "mock")
        monkeypatch.setenv("FHIR_COPILOT_AUDIT_LOG_PATH", str(tmp_path / "care_notes.jsonl"))
        monkeypatch.setenv("FHIR_COPILOT_MOCK_FAILURE_RATE", str(failure_rate))
        clear_ops_env(monkeypatch)
        monkeypatch.setenv(
            "FHIR_COPILOT_OPS_CONFIG", str(write_ops_config(tmp_path / "ops.yaml", **ops))
        )
        dependencies.reset_caches()
        client = TestClient(create_app())
        clients.append(client)
        return client

    yield factory
    for client in clients:
        client.close()
    monkeypatch.delenv("FHIR_COPILOT_MOCK_FAILURE_RATE", raising=False)
    dependencies.reset_caches()


class TestOverHttp:
    """provider 壞掉時,使用者拿到的是結構化拒答,不是 500。"""

    def test_provider_failure_is_a_structured_refusal_not_a_500(
        self, make_client: ClientFactory
    ) -> None:
        client = make_client(failure_rate=1.0)

        response = client.post(
            "/api/chat", json={"patient_id": AMY_ID, "question": "他在吃什麼藥?"}
        )

        assert response.status_code == 200
        body = response.json()
        assert body["refused"] is True
        assert body["limitations"] == "AI 服務暫時無法回應,請稍後再試。"
        assert body["evidence"] == []

    def test_circuit_opens_and_metrics_record_it(self, make_client: ClientFactory) -> None:
        """熔斷狀態變化要看得見——否則事後只會看到一片拒答,查不出何時開始壞的。"""
        client = make_client(failure_rate=1.0, failure_threshold=2, max_retries=0)
        body = {"patient_id": AMY_ID, "question": "他在吃什麼藥?"}

        for _ in range(3):
            assert client.post("/api/chat", json=body).status_code == 200

        metrics = client.get("/metrics").text
        assert 'fhir_copilot_circuit_state_changes_total{state="open"} 1.0' in metrics

    def test_retry_cost_is_charged_to_the_budget(
        self, make_client: ClientFactory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """retry 會放大成本。一次請求偷偷花三倍錢是這個 Phase 明列的地雷。

        mock 的單價是 0 元,所以看金額看不出有沒有記——直接攔截 record 數次數。
        失敗率 100% + 2 次重試 = 2 筆重試補記,加上路由層記錄回應本身的成本,
        總共 3 次。
        """
        client = make_client(failure_rate=1.0, max_retries=2)
        charges: list[float] = []
        monkeypatch.setattr(dependencies.get_budget(), "record", charges.append)

        response = client.post(
            "/api/chat", json={"patient_id": AMY_ID, "question": "他在吃什麼藥?"}
        )

        assert response.json()["refused"] is True
        assert len(charges) == 3

    def test_no_retry_means_no_extra_charge(
        self, make_client: ClientFactory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """對照組:沒有重試時就只有回應本身那一筆。沒有這一條的話,
        上面那個 3 也可能是別的東西湊出來的。"""
        client = make_client(failure_rate=0.0)
        charges: list[float] = []
        monkeypatch.setattr(dependencies.get_budget(), "record", charges.append)

        response = client.post(
            "/api/chat", json={"patient_id": AMY_ID, "question": "他在吃什麼藥?"}
        )

        assert response.json()["refused"] is False
        assert len(charges) == 1

    def test_health_still_works_while_the_provider_is_down(
        self, make_client: ClientFactory
    ) -> None:
        """provider 掛掉不該讓健康檢查跟著掛——那會讓監控誤判成整個服務死亡。"""
        client = make_client(failure_rate=1.0)
        client.post("/api/chat", json={"patient_id": AMY_ID, "question": "藥?"})

        assert client.get("/api/health").status_code == 200
        assert client.get("/api/patients").status_code == 200
