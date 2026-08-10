"""MockProvider:deterministic、不打任何外部 API。

CI 與離線開發的預設 provider(configs/models.yaml `default_provider: mock`)。
不是「假裝聰明的 LLM」——只依問題關鍵字選一個唯讀工具、執行一輪、把
deterministic tool 回傳的結構化結果組成文字答案,讓整條 agent loop
(guardrails、evidence、拒答、cost=0)可以在沒有金鑰的情況下被完整測試。

可設定延遲(``FHIR_COPILOT_MOCK_LATENCY_MS``,預設 0):負載測試需要模擬真實
provider 的網路延遲,否則 ``/api/chat`` 快得不真實,量到的併發行為與正式環境
無關。**預設 0 時行為與沒有這個參數時完全相同**——這個旋鈕只在量測時才打開。
"""

from __future__ import annotations

import os
import random
import time
from collections.abc import Sequence
from typing import Any

from fhir_copilot.providers.base import ProviderStep, RequestedToolCall, ToolCallOutcome
from fhir_copilot.tools.registry import ToolSpec

_LATENCY_ENV = "FHIR_COPILOT_MOCK_LATENCY_MS"
_FAILURE_RATE_ENV = "FHIR_COPILOT_MOCK_FAILURE_RATE"
_FAILURE_SEED_ENV = "FHIR_COPILOT_MOCK_FAILURE_SEED"


class MockProviderFailure(RuntimeError):
    """注入的 provider 失敗(故障注入用)。

    訊息刻意含 "timeout" 字樣,好讓 ops/resilience.py 的 is_retryable 判定為
    可重試——注入的目的就是要走完整條重試與熔斷路徑。
    """

    def __init__(self) -> None:
        super().__init__("injected mock provider failure (simulated timeout)")


# 依序比對;第一個命中的關鍵字決定要呼叫的工具
_REFUSAL_KEYWORDS = (
    "建議治療",
    "治療建議",
    "建議用藥",
    "用藥建議",
    "建議劑量",
    "治療劑量",
    "開藥",
    "開立處方",
    "診斷我",
    "recommend treatment",
    "recommend medication",
    "prescribe",
    "dosage advice",
)
_KEYWORD_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("過敏", "allergy", "allergies", "intolerance", "不耐"), "list_allergies"),
    (("藥", "medication", "用藥"), "list_active_medications"),
    (("照護計畫", "careplan", "care plan"), "get_care_plan_timeline"),
    (("診斷", "condition", "疾病", "病症"), "list_active_conditions"),
    (
        ("觀察", "檢驗", "檢查", "生命徵象", "血壓", "體重", "observation", "vital", "lab"),
        "get_recent_observations",
    ),
    (("基本資料", "demographics", "姓名", "性別", "出生"), "get_patient_demographics"),
)
_DEFAULT_TOOL = "report_out_of_scope"
_OUT_OF_SCOPE_REASON = "deterministic mock 未涵蓋此問題"

_NOT_FOUND_TEXT = "查無此病患資料,無法回答。"


def _select_tool(user_message: str) -> str:
    lowered = user_message.lower()
    if any(keyword in lowered for keyword in _REFUSAL_KEYWORDS):
        return "report_out_of_scope"
    for keywords, tool_name in _KEYWORD_RULES:
        if any(kw.lower() in lowered for kw in keywords):
            return tool_name
    return _DEFAULT_TOOL


def _estimate_tokens(text: str) -> int:
    # 粗估(mock 定價為 0,數字只是給 UI 展示用);中英文混雜,不用真 tokenizer
    return max(1, len(text) // 4)


def _render_demographics(output: dict[str, Any]) -> str:
    d = output.get("demographics")
    if not d:
        return _NOT_FOUND_TEXT
    gender = d.get("gender") or "未記錄"
    birth_date = d.get("birth_date") or "未記錄"
    return f"病患姓名:{d['name']},性別:{gender},出生日期:{birth_date}。"


def _render_conditions(output: dict[str, Any]) -> str:
    if not output.get("ok"):
        return _NOT_FOUND_TEXT
    conditions = output.get("conditions") or []
    if not conditions:
        return "目前沒有生效中(active)的診斷記錄。"
    names = "、".join(c["display"] for c in conditions)
    return f"目前生效中的診斷:{names}。"


def _render_medications(output: dict[str, Any]) -> str:
    if not output.get("ok"):
        return _NOT_FOUND_TEXT
    medications = output.get("medications") or []
    if not medications:
        return "目前沒有生效中(active)的用藥記錄。"
    names = "、".join(m["display"] for m in medications)
    return f"目前生效中的用藥:{names}。"


def _render_allergies(output: dict[str, Any]) -> str:
    if not output.get("ok"):
        return _NOT_FOUND_TEXT
    allergies = output.get("allergies") or []
    if not allergies:
        return "目前沒有過敏或不耐紀錄。"
    parts = [
        f"{item['display']}"
        f"(clinical_status={item.get('clinical_status') or '未記錄'},"
        f"verification_status={item.get('verification_status') or '未記錄'})"
        for item in allergies
    ]
    return "過敏與不耐紀錄:" + "、".join(parts) + "。"


def _render_observations(output: dict[str, Any]) -> str:
    if not output.get("ok"):
        return _NOT_FOUND_TEXT
    observations = output.get("observations") or []
    if not observations:
        return "查無符合條件的觀察值記錄。"
    parts = [
        f"{o['display']}:{o['value_display'] or '無數值'}({o['effective_date'] or '日期未記錄'})"
        for o in observations
    ]
    return "最近的觀察值:" + "、".join(parts) + "。"


def _render_care_plans(output: dict[str, Any]) -> str:
    if not output.get("ok"):
        return _NOT_FOUND_TEXT
    care_plans = output.get("care_plans") or []
    if not care_plans:
        return "目前沒有照護計畫記錄。"
    parts = [
        f"{cp['display']}({cp['status']},{cp['period_start'] or '?'} 起,"
        f"活動:{'、'.join(cp['activities']) or '無'})"
        for cp in care_plans
    ]
    return "照護計畫時間軸:" + "、".join(parts) + "。"


_RENDERERS: dict[str, Any] = {
    "get_patient_demographics": _render_demographics,
    "list_active_conditions": _render_conditions,
    "list_active_medications": _render_medications,
    "list_allergies": _render_allergies,
    "get_recent_observations": _render_observations,
    "get_care_plan_timeline": _render_care_plans,
}


def _resolve_latency_ms(latency_ms: int | None) -> int:
    """明確傳入優先;否則讀環境變數;都沒有就 0(不延遲)。"""
    if latency_ms is not None:
        return max(0, latency_ms)
    raw = os.environ.get(_LATENCY_ENV)
    if not raw:
        return 0
    try:
        return max(0, int(raw))
    except ValueError:
        # 設錯值不該讓服務起不來——這是量測用的旋鈕,不是安全邊界
        return 0


def _resolve_failure_rate(failure_rate: float | None) -> float:
    """0.0 = 永不失敗(預設,行為與沒有這個功能時相同)。"""
    if failure_rate is not None:
        return min(1.0, max(0.0, failure_rate))
    raw = os.environ.get(_FAILURE_RATE_ENV)
    if not raw:
        return 0.0
    try:
        return min(1.0, max(0.0, float(raw)))
    except ValueError:
        return 0.0


def _resolve_seed(seed: int | None) -> int | None:
    if seed is not None:
        return seed
    raw = os.environ.get(_FAILURE_SEED_ENV)
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


class MockProvider:
    """deterministic mock;``model_id`` 對應 configs/pricing.yaml 的 0 元項目。"""

    def __init__(
        self,
        *,
        model_id: str = "mock-deterministic",
        latency_ms: int | None = None,
        failure_rate: float | None = None,
        failure_seed: int | None = None,
    ) -> None:
        self.model_id = model_id
        # 每次「provider 呼叫」各睡這麼久。agent loop 一輪問答會呼叫兩次
        # (start + continue_with_tool_results),所以端到端延遲約為兩倍。
        self.latency_ms = _resolve_latency_ms(latency_ms)
        # 故障注入(Phase 3):預設 0.0 = 永不失敗,行為與沒有這個功能時相同。
        # 給定 seed 時失敗序列可重現——故障注入場景要能重跑才有意義。
        self.failure_rate = _resolve_failure_rate(failure_rate)
        self._random = random.Random(_resolve_seed(failure_seed))

    def _sleep(self) -> None:
        if self.latency_ms > 0:
            time.sleep(self.latency_ms / 1000)

    def _maybe_fail(self) -> None:
        if self.failure_rate > 0 and self._random.random() < self.failure_rate:
            raise MockProviderFailure

    def start(
        self, *, system_prompt: str, user_message: str, tool_specs: Sequence[ToolSpec]
    ) -> ProviderStep:
        del system_prompt  # mock 不需要
        self._sleep()
        self._maybe_fail()
        tool_name = _select_tool(user_message)
        arguments = (
            {"missing_information": _OUT_OF_SCOPE_REASON}
            if tool_name == "report_out_of_scope"
            else {}
        )
        call = RequestedToolCall(call_id="mock-call-1", tool_name=tool_name, arguments=arguments)
        return ProviderStep(
            state=None,
            tool_calls=(call,),
            final_answer=None,
            input_tokens=_estimate_tokens(user_message),
            output_tokens=0,
        )

    def continue_with_tool_results(
        self, state: Any, outcomes: Sequence[ToolCallOutcome]
    ) -> ProviderStep:
        del state
        self._sleep()
        self._maybe_fail()
        if not outcomes:
            answer = "沒有可用的工具結果,無法回答。"
        else:
            outcome = outcomes[0]
            renderer = _RENDERERS.get(outcome.tool_name)
            answer = renderer(outcome.output) if renderer else "不支援的工具,無法回答。"
        return ProviderStep(
            state=None,
            tool_calls=(),
            final_answer=answer,
            input_tokens=0,
            output_tokens=_estimate_tokens(answer),
        )
