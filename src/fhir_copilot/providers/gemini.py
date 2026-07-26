"""Gemini adapter(google-genai SDK,手動 function calling)。

模型 id 由 configs/models.yaml 決定,不寫死在這裡(PLAN.md §8)。這個決定被
現實驗證過兩次:2026-07-19 查證時預設是 gemini-2.5-flash-lite,7/24 實測發現
它對這把金鑰「已對新使用者下架」(404),改用 gemini-3.1-flash-lite;7/26 再
換到 gemini-3.5-flash-lite 並重跑 eval。

**7/26 那次順帶挖出一個潛伏的 adapter bug**:工具結果原本用 ``role="tool"``
送回去,3.1 容忍了它,3.5 直接回 ``400 INVALID_ARGUMENT: Role 'tool' is not
supported``。正確角色是 ``user``——工具結果在 Gemini 的模型裡屬於使用者這一側。
兩個模型都吃 ``user``,所以那不是遷就新模型,是把一直以來的錯改對。
回歸測試在 ``tests/test_providers_gemini.py``(用假 client,不打 API)。

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


_DEFAULT_MODEL_ID = "gemini-3.5-flash-lite"  # 與 configs/models.yaml 的 gemini.model_id 一致


class GeminiProvider:
    """Gemini adapter(google-genai)。``model_id`` 由呼叫端(通常是
    providers.factory.make_provider,從 configs/models.yaml 讀入)決定,
    不寫死在這裡——換模型只要改設定檔。"""

    def __init__(
        self,
        *,
        model_id: str = _DEFAULT_MODEL_ID,
        api_key: str | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self.model_id = model_id
        key = api_key or os.environ.get("GEMINI_API_KEY")
        if not key:
            raise RuntimeError("GEMINI_API_KEY 未設定,無法建立 GeminiProvider")
        # 單次呼叫逾時下在 SDK 的 HTTP client:那是真的中止請求。在外層用執行緒
        # 包 timeout 只能「不等它」,底層連線還在跑、執行緒也殺不掉,等於把逾時
        # 變成 threadpool 洩漏(而 threadpool 飽和正是 Phase 0 量到的瓶頸)。
        # 值出自 configs/ops.yaml 的 resilience.provider_timeout_seconds。
        http_options = (
            types.HttpOptions(timeout=int(timeout_seconds * 1000))
            if timeout_seconds is not None
            else None
        )
        self._client = genai.Client(api_key=key, http_options=http_options)

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
        # **function response 的角色是 "user" 不是 "tool"。** Gemini API 的合法角色
        # 裡沒有 tool——工具結果在它的模型裡屬於「使用者這一側送進來的東西」。
        # gemini-3.1-flash-lite 容忍了 "tool",3.5 直接回
        # `400 INVALID_ARGUMENT: Role 'tool' is not supported`。
        # 那個容忍是運氣不是正確,別再靠它。
        history.append(types.Content(role="user", parts=response_parts))

        config = types.GenerateContentConfig(
            tools=[_build_tool(state.tool_specs)],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        response = self._client.models.generate_content(
            model=self.model_id, contents=history, config=config
        )
        return _extract_step(response, history, state.tool_specs)
