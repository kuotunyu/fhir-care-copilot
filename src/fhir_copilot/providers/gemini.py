"""Gemini adapter(google-genai SDK,手動 function calling)。

模型 id 由 configs/models.yaml 決定,不寫死在這裡(PLAN.md §8)——2026-07-19
查證時預設是 gemini-2.5-flash-lite,但 2026-07-24 實測發現該模型對這把金鑰
「已對新使用者下架」(呼叫回 404),改用 gemini-3.1-flash-lite(見 PLAN.md §7
記錄的這次現況變化)。

刻意選用 ``client.models.generate_content`` 這條 surface,不是新版 Interactions
API(PLAN.md §7 記錄的決策——文件穩定、範例齊全)。關閉 automatic function
calling,agent loop 自己驅動多輪迴圈(ADR 0001/0003)。provider instance 本身
無狀態,對話歷史透過 ``state``(``_GeminiState``)顯式傳遞,可安全被多個
問題重複使用。
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from google import genai
from google.genai import types

from fhir_copilot.providers.base import ProviderStep, RequestedToolCall, ToolCallOutcome
from fhir_copilot.tools.registry import ToolSpec, llm_facing_schema


@dataclass
class _GeminiState:
    history: list[types.Content] = field(default_factory=list)
    tool_specs: tuple[ToolSpec, ...] = ()


def _build_tool(tool_specs: Sequence[ToolSpec]) -> types.Tool:
    declarations = [
        types.FunctionDeclaration(
            name=spec.name,
            description=spec.description,
            parameters_json_schema=llm_facing_schema(spec),
        )
        for spec in tool_specs
    ]
    return types.Tool(function_declarations=declarations)


def _extract_step(
    response: types.GenerateContentResponse,
    history: list[types.Content],
    tool_specs: tuple[ToolSpec, ...],
) -> ProviderStep:
    usage = response.usage_metadata
    input_tokens = (usage.prompt_token_count if usage else None) or 0
    output_tokens = (usage.candidates_token_count if usage else None) or 0

    calls = response.function_calls or []
    if calls:
        candidates = response.candidates or []
        if candidates and candidates[0].content is not None:
            history = [*history, candidates[0].content]
        tool_calls = tuple(
            RequestedToolCall(
                call_id=call.id or f"gemini-call-{i}",
                tool_name=call.name or "",
                arguments=dict(call.args or {}),
            )
            for i, call in enumerate(calls)
        )
        return ProviderStep(
            state=_GeminiState(history=history, tool_specs=tool_specs),
            tool_calls=tool_calls,
            final_answer=None,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    return ProviderStep(
        state=_GeminiState(history=history, tool_specs=tool_specs),
        tool_calls=(),
        final_answer=response.text or "(模型未提供文字回答)",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


_DEFAULT_MODEL_ID = "gemini-3.1-flash-lite"  # 與 configs/models.yaml 的 gemini.model_id 一致


class GeminiProvider:
    """Gemini adapter(google-genai)。``model_id`` 由呼叫端(通常是
    providers.factory.make_provider,從 configs/models.yaml 讀入)決定,
    不寫死在這裡——換模型只要改設定檔。"""

    def __init__(self, *, model_id: str = _DEFAULT_MODEL_ID, api_key: str | None = None) -> None:
        self.model_id = model_id
        key = api_key or os.environ.get("GEMINI_API_KEY")
        if not key:
            raise RuntimeError("GEMINI_API_KEY 未設定,無法建立 GeminiProvider")
        self._client = genai.Client(api_key=key)

    def start(
        self, *, system_prompt: str, user_message: str, tool_specs: Sequence[ToolSpec]
    ) -> ProviderStep:
        specs = tuple(tool_specs)
        user_content = types.Content(role="user", parts=[types.Part.from_text(text=user_message)])
        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            tools=[_build_tool(specs)],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        response = self._client.models.generate_content(
            model=self.model_id, contents=[user_content], config=config
        )
        return _extract_step(response, [user_content], specs)

    def continue_with_tool_results(
        self, state: Any, outcomes: Sequence[ToolCallOutcome]
    ) -> ProviderStep:
        history = [*state.history]
        response_parts = [
            types.Part.from_function_response(name=outcome.tool_name, response=outcome.output)
            for outcome in outcomes
        ]
        history.append(types.Content(role="tool", parts=response_parts))

        config = types.GenerateContentConfig(
            tools=[_build_tool(state.tool_specs)],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        response = self._client.models.generate_content(
            model=self.model_id, contents=history, config=config
        )
        return _extract_step(response, history, state.tool_specs)
