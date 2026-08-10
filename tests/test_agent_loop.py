"""Agent loop 整合測試:guardrails、evidence、拒答、回應契約。"""

from collections.abc import Sequence
from typing import Any

import pytest

from fhir_copilot.agent.loop import _dedupe_evidence, answer_question
from fhir_copilot.agent.response import RefusalReason
from fhir_copilot.config import Guardrails, load_pricing
from fhir_copilot.ops.resilience import ProviderUnavailableError
from fhir_copilot.providers.base import ProviderStep, RequestedToolCall, ToolCallOutcome
from fhir_copilot.providers.mock import MockProvider
from fhir_copilot.store import LocalBundleFHIRStore
from fhir_copilot.tools.base import Evidence
from fhir_copilot.tools.registry import READ_ONLY_TOOLS
from tests.conftest import AMY_ID, BEN_ID


@pytest.fixture
def guardrails() -> Guardrails:
    return Guardrails(
        max_tool_rounds=6, timeout_seconds=30, max_input_chars=4000, max_output_tokens=1024
    )


@pytest.fixture
def pricing() -> dict[str, Any]:
    return load_pricing()


class _LoopingProvider:
    """測試用 stub:永遠要求再呼叫一次工具,不給 final_answer——用來測 max_tool_rounds。"""

    model_id = "mock-deterministic"

    def start(
        self, *, system_prompt: str, user_message: str, tool_specs: Sequence[Any]
    ) -> ProviderStep:
        del system_prompt, user_message, tool_specs
        return self._loop_step()

    def continue_with_tool_results(
        self, state: Any, outcomes: Sequence[ToolCallOutcome]
    ) -> ProviderStep:
        del state, outcomes
        return self._loop_step()

    @staticmethod
    def _loop_step() -> ProviderStep:
        call = RequestedToolCall(call_id="c", tool_name="get_patient_demographics", arguments={})
        return ProviderStep(
            state=None, tool_calls=(call,), final_answer=None, input_tokens=0, output_tokens=0
        )


class _NoToolProvider:
    """一次工具都不呼叫,直接給最終答案——模型「憑記憶回答」時的形狀。"""

    model_id = "mock-deterministic"

    def __init__(self, answer: str = "他目前在服用 Metformin 500mg。") -> None:
        self._answer = answer

    def start(
        self, *, system_prompt: str, user_message: str, tool_specs: Sequence[Any]
    ) -> ProviderStep:
        del system_prompt, user_message, tool_specs
        return ProviderStep(
            state=None,
            tool_calls=(),
            final_answer=self._answer,
            input_tokens=100,
            output_tokens=20,
        )

    def continue_with_tool_results(
        self, state: Any, outcomes: Sequence[ToolCallOutcome]
    ) -> ProviderStep:  # pragma: no cover - 不會被呼叫到
        raise AssertionError("不該走到這裡")


class _UnknownToolThenAnswerProvider:
    """先喊一個不存在的工具,再直接給答案。

    「模型要求了工具」不等於「查過資料」——未知工具的 handler 根本沒跑。
    """

    model_id = "mock-deterministic"

    def start(
        self, *, system_prompt: str, user_message: str, tool_specs: Sequence[Any]
    ) -> ProviderStep:
        del system_prompt, user_message, tool_specs
        call = RequestedToolCall(call_id="c", tool_name="list_hospital_admissions", arguments={})
        return ProviderStep(
            state=None, tool_calls=(call,), final_answer=None, input_tokens=10, output_tokens=5
        )

    def continue_with_tool_results(
        self, state: Any, outcomes: Sequence[ToolCallOutcome]
    ) -> ProviderStep:
        del state, outcomes
        return ProviderStep(
            state=None,
            tool_calls=(),
            final_answer="他上次住院是 2019 年。",
            input_tokens=10,
            output_tokens=5,
        )


class _OutOfScopeProvider:
    """呼叫 report_out_of_scope 宣告查不到,然後(如果還讓它講的話)硬答。

    第二段刻意寫成硬答:要證明的是 loop **在宣告當下就停**,不會讓模型把
    「我無法查閱⋯」或任何編造內容送到使用者面前。
    """

    model_id = "mock-deterministic"

    def __init__(self, missing_information: str = "保險給付範圍") -> None:
        self._missing_information = missing_information

    def start(
        self, *, system_prompt: str, user_message: str, tool_specs: Sequence[Any]
    ) -> ProviderStep:
        del system_prompt, user_message, tool_specs
        call = RequestedToolCall(
            call_id="c",
            tool_name="report_out_of_scope",
            arguments={"missing_information": self._missing_information},
        )
        return ProviderStep(
            state=None, tool_calls=(call,), final_answer=None, input_tokens=40, output_tokens=8
        )

    def continue_with_tool_results(
        self, state: Any, outcomes: Sequence[ToolCallOutcome]
    ) -> ProviderStep:  # pragma: no cover - 不該被呼叫到
        raise AssertionError("宣告超出範圍之後不該再問模型")


class TestReportOutOfScope:
    """「病患存在,但問的是六個資料工具都涵蓋不到的東西」。

    2026-07-26 用真實模型實測(gemini-3.1-flash-lite,問保險給付範圍),
    在這個工具存在之前實際發生的是:

        模型呼叫工具 → 拿到不相關資料 → 回答「我無法查閱保險資訊」
        → refused=False,而且掛著 3 筆與答案無關的 evidence

    回答內容是對的,契約是錯的。下游分辨不出「查了而且答出來」與
    「查了但答不出來」,而那兩件事該做的下一步完全不同。

    判斷「模型是不是在拒答」如果靠解析回答文字,就回到啟發式判準——
    eval 的 judge 在這件事上改過五次還是不穩。給模型一個工具去宣告,
    把判斷問題變成結構問題。
    """

    def test_declaration_becomes_a_structured_refusal(
        self, store: LocalBundleFHIRStore, guardrails: Guardrails, pricing: dict[str, Any]
    ) -> None:
        result = answer_question(
            provider=_OutOfScopeProvider(),
            store=store,
            patient_id=AMY_ID,
            question="他的保險給付範圍包含哪些項目?",
            guardrails=guardrails,
            pricing=pricing,
        )

        assert result.refused is True
        assert result.limitations is not None
        assert "超出可查詢的資料範圍" in result.limitations

    def test_no_evidence_is_attached_to_a_refusal(
        self, store: LocalBundleFHIRStore, guardrails: Guardrails, pricing: dict[str, Any]
    ) -> None:
        """拒答不可以掛著證據。**那正是修掉的那個 bug 的形狀**:
        一句「我答不出來」配上三筆不支持它的 evidence。"""
        result = answer_question(
            provider=_OutOfScopeProvider(),
            store=store,
            patient_id=AMY_ID,
            question="他的保險給付範圍包含哪些項目?",
            guardrails=guardrails,
            pricing=pricing,
        )

        assert result.evidence == []

    def test_tokens_already_spent_are_billed(
        self, store: LocalBundleFHIRStore, guardrails: Guardrails, pricing: dict[str, Any]
    ) -> None:
        result = answer_question(
            provider=_OutOfScopeProvider(),
            store=store,
            patient_id=AMY_ID,
            question="他的保險給付範圍包含哪些項目?",
            guardrails=guardrails,
            pricing=pricing,
        )

        assert result.input_tokens == 40
        assert result.output_tokens == 8

    def test_the_tool_never_touches_the_store(self) -> None:
        """它是唯讀的,而且比唯讀更嚴格——完全不碰 store(ADR 0001 的邊界沒放寬)。"""
        from fhir_copilot.tools.out_of_scope import ReportOutOfScopeInput, report_out_of_scope

        class _ExplodingStore:
            def __getattr__(self, name: str) -> Any:
                raise AssertionError(f"這個工具不該碰 store(存取了 {name})")

        result = report_out_of_scope(
            _ExplodingStore(),
            ReportOutOfScopeInput(patient_id=AMY_ID, missing_information="保險給付"),
        )

        assert result.out_of_scope is True
        assert result.evidence == []

    def test_coverage_sentence_lists_only_data_tools(self) -> None:
        """拒答訊息裡「目前能查的是⋯」不該把 report_out_of_scope 也列進去
        ——它一筆資料都查不到,列進去是誤導。"""
        from fhir_copilot.agent.loop import _coverage_sentence

        sentence = _coverage_sentence()
        for spec in READ_ONLY_TOOLS:
            if spec.queries_patient_data:
                assert spec.description in sentence
            else:
                assert spec.description not in sentence

    def test_model_controlled_missing_information_is_logged_as_shape_only(
        self,
        store: LocalBundleFHIRStore,
        guardrails: Guardrails,
        pricing: dict[str, Any],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        secret = f"Amy002 asked: {AMY_ID} 的完整問題"

        with caplog.at_level("INFO", logger="fhir_copilot.agent.loop"):
            answer_question(
                provider=_OutOfScopeProvider(secret),
                store=store,
                patient_id=AMY_ID,
                question="測試問題",
                guardrails=guardrails,
                pricing=pricing,
            )

        assert secret not in caplog.text
        record = next(r for r in caplog.records if r.message == "模型宣告問題超出工具涵蓋範圍")
        assert vars(record)["missing_information_present"] is True
        assert vars(record)["missing_information_length"] == len(secret)
        assert not hasattr(record, "missing_information")


class _UnavailableProvider:
    model_id = "mock-deterministic"

    def __init__(self, secret: str) -> None:
        self._secret = secret

    def start(
        self, *, system_prompt: str, user_message: str, tool_specs: Sequence[Any]
    ) -> ProviderStep:
        del system_prompt, user_message, tool_specs
        raise ProviderUnavailableError(self._secret)

    def continue_with_tool_results(
        self, state: Any, outcomes: Sequence[ToolCallOutcome]
    ) -> ProviderStep:  # pragma: no cover - start 已失敗
        raise AssertionError("不該走到這裡")


def test_provider_exception_message_is_not_logged(
    store: LocalBundleFHIRStore,
    guardrails: Guardrails,
    pricing: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = f"SDK response leaked {AMY_ID} Amy002"

    with caplog.at_level("WARNING", logger="fhir_copilot.agent.loop"):
        result = answer_question(
            provider=_UnavailableProvider(secret),
            store=store,
            patient_id=AMY_ID,
            question="測試問題",
            guardrails=guardrails,
            pricing=pricing,
        )

    assert result.refusal_reason is RefusalReason.PROVIDER_UNAVAILABLE
    assert secret not in caplog.text
    record = next(r for r in caplog.records if r.message == "provider 不可用,轉為結構化拒答")
    assert vars(record)["call"] == "start"
    assert vars(record)["error_type"] == "ProviderUnavailableError"
    assert vars(record)["refusal_reason"] == RefusalReason.PROVIDER_UNAVAILABLE.value
    assert not hasattr(record, "error_message")


class TestRefusalReason:
    """每一種拒答都要帶得出**機器可讀**的原因。

    2026-07-27 重跑 injection eval 時,20 題全部拒答、``limitations`` 全是同一句話
    ——於是分不出是模型主動宣告查不到,還是它根本沒呼叫工具被攔下來。那是兩件
    很不一樣的事,而「100% 抵抗率」沒有這個區分就是個講不清楚的數字。

    ``limitations`` 給人看,``refusal_reason`` 給程式看,與營運層的
    ``detail``/``error_code`` 是同一個模式。
    """

    def test_input_too_long(
        self, store: LocalBundleFHIRStore, guardrails: Guardrails, pricing: dict[str, Any]
    ) -> None:
        result = answer_question(
            provider=MockProvider(),
            store=store,
            patient_id=AMY_ID,
            question="他" * (guardrails.max_input_chars + 1),
            guardrails=guardrails,
            pricing=pricing,
        )
        assert result.refusal_reason == RefusalReason.INPUT_TOO_LONG

    def test_patient_not_found(
        self, store: LocalBundleFHIRStore, guardrails: Guardrails, pricing: dict[str, Any]
    ) -> None:
        result = answer_question(
            provider=MockProvider(),
            store=store,
            patient_id="nonexistent-patient",
            question="他目前有在吃什麼藥?",
            guardrails=guardrails,
            pricing=pricing,
        )
        assert result.refusal_reason == RefusalReason.PATIENT_NOT_FOUND

    def test_max_tool_rounds(
        self, store: LocalBundleFHIRStore, guardrails: Guardrails, pricing: dict[str, Any]
    ) -> None:
        result = answer_question(
            provider=_LoopingProvider(),
            store=store,
            patient_id=AMY_ID,
            question="他目前有在吃什麼藥?",
            guardrails=guardrails,
            pricing=pricing,
        )
        assert result.refusal_reason == RefusalReason.MAX_TOOL_ROUNDS

    def test_no_tool_call(
        self, store: LocalBundleFHIRStore, guardrails: Guardrails, pricing: dict[str, Any]
    ) -> None:
        result = answer_question(
            provider=_NoToolProvider(),
            store=store,
            patient_id=AMY_ID,
            question="他上次住院是什麼時候?",
            guardrails=guardrails,
            pricing=pricing,
        )
        assert result.refusal_reason == RefusalReason.NO_TOOL_CALL

    def test_out_of_scope(
        self, store: LocalBundleFHIRStore, guardrails: Guardrails, pricing: dict[str, Any]
    ) -> None:
        result = answer_question(
            provider=_OutOfScopeProvider(),
            store=store,
            patient_id=AMY_ID,
            question="他的保險給付範圍包含哪些項目?",
            guardrails=guardrails,
            pricing=pricing,
        )
        assert result.refusal_reason == RefusalReason.OUT_OF_SCOPE

    def test_the_two_new_guardrails_are_distinguishable(
        self, store: LocalBundleFHIRStore, guardrails: Guardrails, pricing: dict[str, Any]
    ) -> None:
        """**這條就是那個觀測盲區。** 兩者的 limitations 對使用者刻意一致,
        但 refusal_reason 必須分得出來,否則量測時講不出 100% 是怎麼來的。"""
        kwargs: dict[str, Any] = {
            "store": store,
            "patient_id": AMY_ID,
            "guardrails": guardrails,
            "pricing": pricing,
        }
        no_tool = answer_question(provider=_NoToolProvider(), question="X?", **kwargs)
        declared = answer_question(provider=_OutOfScopeProvider(), question="Y?", **kwargs)

        assert no_tool.limitations == declared.limitations  # 給人看的一樣
        assert no_tool.refusal_reason != declared.refusal_reason  # 給程式看的不一樣

    def test_successful_answer_has_no_reason(
        self, store: LocalBundleFHIRStore, guardrails: Guardrails, pricing: dict[str, Any]
    ) -> None:
        result = answer_question(
            provider=MockProvider(),
            store=store,
            patient_id=AMY_ID,
            question="他目前有在吃什麼藥?",
            guardrails=guardrails,
            pricing=pricing,
        )
        assert result.refused is False
        assert result.refusal_reason is None


class TestRequireToolCallBeforeAnswer:
    """「病患存在,但問的東西六個資料工具都涵蓋不到」——在此之前這個情況沒有結構保護。

    專案的核心宣稱是「LLM 不憑記憶回答病患事實」,但那件事**只寫在 system prompt
    裡**。模型不照做時,回應契約標的是 refused=false、evidence=[],外觀上跟
    「查了資料而且答出來了」完全一樣。

    判準刻意是「有沒有真的執行過工具」,不是「有沒有拿到 evidence」——
    後者會把 test_valid_empty_result_is_not_a_refusal 那種正確答案一起擋掉。
    """

    def test_answer_without_any_tool_call_is_refused(
        self, store: LocalBundleFHIRStore, guardrails: Guardrails, pricing: dict[str, Any]
    ) -> None:
        result = answer_question(
            provider=_NoToolProvider(),
            store=store,
            patient_id=AMY_ID,
            question="他上次住院是什麼時候?",
            guardrails=guardrails,
            pricing=pricing,
        )

        assert result.refused is True
        assert result.evidence == []
        # 模型編出來的內容不可以出現在回應裡
        assert "Metformin" not in result.answer
        assert result.limitations is not None
        assert "超出可查詢的資料範圍" in result.limitations

    def test_refusal_names_what_is_actually_queryable(
        self, store: LocalBundleFHIRStore, guardrails: Guardrails, pricing: dict[str, Any]
    ) -> None:
        """拒答要告訴使用者「那什麼查得到」,而且那句話是從 registry 生成的。"""
        result = answer_question(
            provider=_NoToolProvider(),
            store=store,
            patient_id=AMY_ID,
            question="他上次住院是什麼時候?",
            guardrails=guardrails,
            pricing=pricing,
        )

        assert result.limitations is not None
        for spec in READ_ONLY_TOOLS:
            if spec.queries_patient_data:
                assert spec.description in result.limitations

    def test_already_spent_tokens_are_still_billed(
        self, store: LocalBundleFHIRStore, guardrails: Guardrails, pricing: dict[str, Any]
    ) -> None:
        """拒答不代表沒花錢。那一次 provider 呼叫真的發生了,成本要照算。"""
        result = answer_question(
            provider=_NoToolProvider(),
            store=store,
            patient_id=AMY_ID,
            question="他上次住院是什麼時候?",
            guardrails=guardrails,
            pricing=pricing,
        )

        assert result.input_tokens == 100
        assert result.output_tokens == 20

    def test_requesting_an_unknown_tool_does_not_count_as_consulting_data(
        self, store: LocalBundleFHIRStore, guardrails: Guardrails, pricing: dict[str, Any]
    ) -> None:
        result = answer_question(
            provider=_UnknownToolThenAnswerProvider(),
            store=store,
            patient_id=AMY_ID,
            question="他上次住院是什麼時候?",
            guardrails=guardrails,
            pricing=pricing,
        )

        assert result.refused is True
        assert "2019" not in result.answer

    def test_can_be_switched_off_to_reproduce_earlier_eval_numbers(
        self, store: LocalBundleFHIRStore, pricing: dict[str, Any]
    ) -> None:
        """reports/ 底下的 eval 數字是在這道護欄之前量的。關掉才重現得出來。"""
        relaxed = Guardrails(
            max_tool_rounds=6,
            timeout_seconds=30,
            max_input_chars=4000,
            max_output_tokens=1024,
            require_tool_call_before_answer=False,
        )
        result = answer_question(
            provider=_NoToolProvider(),
            store=store,
            patient_id=AMY_ID,
            question="他上次住院是什麼時候?",
            guardrails=relaxed,
            pricing=pricing,
        )

        assert result.refused is False
        assert "Metformin" in result.answer

    def test_normal_answers_are_untouched(
        self, store: LocalBundleFHIRStore, guardrails: Guardrails, pricing: dict[str, Any]
    ) -> None:
        """對照組:有呼叫工具的正常問答不受這道護欄影響。"""
        result = answer_question(
            provider=MockProvider(),
            store=store,
            patient_id=AMY_ID,
            question="他目前有在吃什麼藥?",
            guardrails=guardrails,
            pricing=pricing,
        )

        assert result.refused is False
        assert len(result.evidence) >= 1


def test_answers_with_evidence_and_zero_cost_via_mock(
    store: LocalBundleFHIRStore, guardrails: Guardrails, pricing: dict[str, Any]
) -> None:
    result = answer_question(
        provider=MockProvider(),
        store=store,
        patient_id=AMY_ID,
        question="他目前有在吃什麼藥?",
        guardrails=guardrails,
        pricing=pricing,
    )

    assert result.refused is False
    assert "Metformin" in result.answer
    assert len(result.evidence) >= 1
    assert all(e.resource_type == "MedicationRequest" for e in result.evidence)
    assert result.model == "mock-deterministic"
    assert result.estimated_cost_usd == 0.0
    assert result.latency_ms >= 0


def test_mock_allergy_query_returns_allergy_evidence(
    store: LocalBundleFHIRStore, guardrails: Guardrails, pricing: dict[str, Any]
) -> None:
    result = answer_question(
        provider=MockProvider(),
        store=store,
        patient_id=AMY_ID,
        question="他有藥物過敏嗎?",
        guardrails=guardrails,
        pricing=pricing,
    )

    assert result.refused is False
    assert result.evidence
    assert all(e.resource_type == "AllergyIntolerance" for e in result.evidence)


@pytest.mark.parametrize(
    "question",
    [
        "他的保險給付範圍是什麼?",
        "請根據他的用藥建議治療劑量",
    ],
)
def test_mock_unsupported_questions_are_structured_refusals(
    question: str,
    store: LocalBundleFHIRStore,
    guardrails: Guardrails,
    pricing: dict[str, Any],
) -> None:
    result = answer_question(
        provider=MockProvider(),
        store=store,
        patient_id=AMY_ID,
        question=question,
        guardrails=guardrails,
        pricing=pricing,
    )

    assert result.refused is True
    assert result.refusal_reason == RefusalReason.OUT_OF_SCOPE
    assert result.evidence == []


def test_valid_empty_result_is_not_a_refusal(
    store: LocalBundleFHIRStore, guardrails: Guardrails, pricing: dict[str, Any]
) -> None:
    """Ben 存在但沒有照護計畫——這是合法的空結果,不該觸發拒答(M2 的設計語意)。"""
    result = answer_question(
        provider=MockProvider(),
        store=store,
        patient_id=BEN_ID,
        question="他的照護計畫是什麼?",
        guardrails=guardrails,
        pricing=pricing,
    )

    assert result.refused is False
    assert "沒有照護計畫" in result.answer


def test_unknown_patient_is_structured_refusal(
    store: LocalBundleFHIRStore, guardrails: Guardrails, pricing: dict[str, Any]
) -> None:
    result = answer_question(
        provider=MockProvider(),
        store=store,
        patient_id="no-such-patient",
        question="他的基本資料是什麼?",
        guardrails=guardrails,
        pricing=pricing,
    )

    assert result.refused is True
    assert result.evidence == []
    assert result.limitations is not None


def test_llm_cannot_smuggle_a_different_patient_id_via_tool_arguments(
    store: LocalBundleFHIRStore, guardrails: Guardrails, pricing: dict[str, Any]
) -> None:
    """ADR 0003:即使工具參數帶了別的 patient_id,loop 也一律用注入的那個。"""

    class _InjectingProvider:
        model_id = "mock-deterministic"

        def start(
            self, *, system_prompt: str, user_message: str, tool_specs: Sequence[Any]
        ) -> ProviderStep:
            del system_prompt, user_message, tool_specs
            call = RequestedToolCall(
                call_id="c",
                tool_name="get_patient_demographics",
                arguments={"patient_id": "some-other-patient-the-llm-made-up"},
            )
            return ProviderStep(
                state=None, tool_calls=(call,), final_answer=None, input_tokens=0, output_tokens=0
            )

        def continue_with_tool_results(
            self, state: Any, outcomes: Sequence[ToolCallOutcome]
        ) -> ProviderStep:
            del state
            return ProviderStep(
                state=None,
                tool_calls=(),
                final_answer=outcomes[0].output["demographics"]["name"],
                input_tokens=0,
                output_tokens=0,
            )

    result = answer_question(
        provider=_InjectingProvider(),
        store=store,
        patient_id=AMY_ID,
        question="姓名?",
        guardrails=guardrails,
        pricing=pricing,
    )

    assert result.refused is False
    assert result.answer == "Amy002 Fixture001"


def test_input_too_long_is_refused_before_any_tool_call(
    store: LocalBundleFHIRStore, pricing: dict[str, Any]
) -> None:
    guardrails = Guardrails(
        max_tool_rounds=6, timeout_seconds=30, max_input_chars=10, max_output_tokens=1024
    )

    result = answer_question(
        provider=MockProvider(),
        store=store,
        patient_id=AMY_ID,
        question="這個問題超過十個字元長度上限了喔",
        guardrails=guardrails,
        pricing=pricing,
    )

    assert result.refused is True
    assert result.input_tokens == 0
    assert result.output_tokens == 0


def test_max_tool_rounds_guardrail_stops_infinite_loop(
    store: LocalBundleFHIRStore, pricing: dict[str, Any]
) -> None:
    guardrails = Guardrails(
        max_tool_rounds=1, timeout_seconds=30, max_input_chars=4000, max_output_tokens=1024
    )

    result = answer_question(
        provider=_LoopingProvider(),
        store=store,
        patient_id=AMY_ID,
        question="問題",
        guardrails=guardrails,
        pricing=pricing,
    )

    assert result.refused is True
    assert "輪數" in (result.limitations or "")


def test_timeout_guardrail_trips(store: LocalBundleFHIRStore, pricing: dict[str, Any]) -> None:
    guardrails = Guardrails(
        max_tool_rounds=100, timeout_seconds=0, max_input_chars=4000, max_output_tokens=1024
    )

    result = answer_question(
        provider=_LoopingProvider(),
        store=store,
        patient_id=AMY_ID,
        question="問題",
        guardrails=guardrails,
        pricing=pricing,
    )

    assert result.refused is True
    assert "時間" in (result.limitations or "")


def test_dedupe_evidence_removes_exact_duplicates_preserving_order() -> None:
    e1 = Evidence(
        resource_type="Condition", resource_id="1", field="clinicalStatus", value="active"
    )
    e2 = Evidence(
        resource_type="Condition", resource_id="2", field="clinicalStatus", value="active"
    )
    deduped = _dedupe_evidence([e1, e2, e1])

    assert deduped == [e1, e2]
