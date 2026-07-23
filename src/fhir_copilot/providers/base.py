"""LLM provider adapter 介面(M3)。

Provider 只負責「規劃要呼叫哪些工具」與「根據工具結果組出最終答案」;它不會
直接碰 FHIRStore——工具由 agent loop 執行後,結果才餵回 provider。狀態
(對話歷史)透過 ``state`` 顯式傳遞,不是藏在 provider instance 裡,讓同一個
provider instance 可以安全地被多個問題重複使用。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from fhir_copilot.tools.registry import ToolSpec


@dataclass(frozen=True)
class RequestedToolCall:
    """LLM 要求呼叫的工具(名稱 + 已解析的參數 dict,不含 patient_id)。"""

    call_id: str
    tool_name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolCallOutcome:
    """工具實際執行完的結果,要餵回 LLM 的下一輪。"""

    call_id: str
    tool_name: str
    output: dict[str, Any]


@dataclass(frozen=True)
class ProviderStep:
    """provider 單輪呼叫的結果:``final_answer`` 為 None 代表還要呼叫工具。"""

    state: Any
    tool_calls: tuple[RequestedToolCall, ...]
    final_answer: str | None
    input_tokens: int
    output_tokens: int


class Provider(Protocol):
    """LLM provider 介面;agent loop 依此驅動多輪 tool-calling。"""

    model_id: str

    def start(
        self, *, system_prompt: str, user_message: str, tool_specs: Sequence[ToolSpec]
    ) -> ProviderStep:
        """開始回答一個新問題。"""
        ...

    def continue_with_tool_results(
        self, state: Any, outcomes: Sequence[ToolCallOutcome]
    ) -> ProviderStep:
        """把上一輪工具執行結果餵回去,取得下一輪結果。"""
        ...
