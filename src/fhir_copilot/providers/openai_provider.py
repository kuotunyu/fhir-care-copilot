"""OpenAI gpt-5.4-mini adapter(Responses API,手動 function calling)。

官方建議新專案用 Responses API(PLAN.md §7)。用 ``previous_response_id``
串接多輪,不必自己重組完整 input 陣列。provider instance 無狀態,對話狀態
透過 ``state``(``_OpenAIState``)顯式傳遞。

未對工具參數 schema 開 ``strict``:strict mode 要求每個欄位都在 ``required``
裡(不能有預設值/選填欄位),跟我們用 pydantic 產生的 schema(``category``/
``limit`` 有預設值)不符;仍保有 ``additionalProperties: false``
(來自 pydantic ``extra="forbid"``)做基本防呆。
"""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, cast

from openai import OpenAI

from fhir_copilot.providers.base import ProviderStep, RequestedToolCall, ToolCallOutcome
from fhir_copilot.tools.registry import ToolSpec, llm_facing_schema


@dataclass
class _OpenAIState:
    previous_response_id: str | None
    tool_specs: tuple[ToolSpec, ...]


def _build_tools(tool_specs: Sequence[ToolSpec]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "name": spec.name,
            "description": spec.description,
            "parameters": llm_facing_schema(spec),
        }
        for spec in tool_specs
    ]


def _extract_step(response: Any, tool_specs: tuple[ToolSpec, ...]) -> ProviderStep:
    usage = response.usage
    input_tokens = (usage.input_tokens if usage else None) or 0
    output_tokens = (usage.output_tokens if usage else None) or 0

    tool_calls = tuple(
        RequestedToolCall(
            call_id=item.call_id,
            tool_name=item.name,
            arguments=json.loads(item.arguments) if item.arguments else {},
        )
        for item in response.output
        if getattr(item, "type", None) == "function_call"
    )
    state = _OpenAIState(previous_response_id=response.id, tool_specs=tool_specs)
    if tool_calls:
        return ProviderStep(
            state=state,
            tool_calls=tool_calls,
            final_answer=None,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
    return ProviderStep(
        state=state,
        tool_calls=(),
        final_answer=response.output_text or "(模型未提供文字回答)",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


class OpenAIProvider:
    """OpenAI adapter(Responses API)。``model_id`` 由呼叫端(通常是
    providers.factory.make_provider,從 configs/models.yaml 讀入)決定,
    不寫死在這裡——換模型只要改設定檔。"""

    def __init__(self, *, model_id: str = "gpt-5.4-mini", api_key: str | None = None) -> None:
        self.model_id = model_id
        key = api_key or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("OPENAI_API_KEY 未設定,無法建立 OpenAIProvider")
        self._client = OpenAI(api_key=key)

    def start(
        self, *, system_prompt: str, user_message: str, tool_specs: Sequence[ToolSpec]
    ) -> ProviderStep:
        specs = tuple(tool_specs)
        # OpenAI SDK 的 typed overload 不接受泛型 dict,即使結構完全符合
        # FunctionToolParam(已對照 SDK 型別驗證過)——用 cast 避開,不放寬其他型別檢查
        response = self._client.responses.create(
            model=self.model_id,
            instructions=system_prompt,
            input=user_message,
            tools=cast(Any, _build_tools(specs)),
        )
        return _extract_step(response, specs)

    def continue_with_tool_results(
        self, state: Any, outcomes: Sequence[ToolCallOutcome]
    ) -> ProviderStep:
        input_items = [
            {
                "type": "function_call_output",
                "call_id": outcome.call_id,
                "output": json.dumps(outcome.output, ensure_ascii=False),
            }
            for outcome in outcomes
        ]
        response = self._client.responses.create(
            model=self.model_id,
            previous_response_id=state.previous_response_id,
            input=cast(Any, input_items),
            tools=cast(Any, _build_tools(state.tool_specs)),
        )
        return _extract_step(response, state.tool_specs)
