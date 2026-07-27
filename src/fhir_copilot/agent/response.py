"""Agent 回應契約——每次回答都固定輸出這個結構。"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from fhir_copilot.tools.base import Evidence


class RefusalReason(StrEnum):
    """拒答的**機器可讀**原因。

    ``limitations`` 是給人看的一句話,``refusal_reason`` 是給程式看的代碼——
    與營運層的 ``error_code``/``detail`` 是同一個模式(見 ops/errors.py)。

    為什麼需要它:2026-07-27 重跑 injection eval 時,20 題全部拒答、
    ``limitations`` 全是同一句話,於是**分不出是哪一道護欄觸發的**——模型主動
    宣告查不到,和模型根本沒呼叫工具被攔下來,是兩件很不一樣的事。當時那兩個
    常數刻意設成同一個字串(「對使用者來說是同一件事」),對使用者確實是,
    但對「這個 100% 是怎麼來的」這個問題就成了觀測盲區。
    """

    INPUT_TOO_LONG = "input_too_long"
    PATIENT_NOT_FOUND = "patient_not_found"
    MAX_TOOL_ROUNDS = "max_tool_rounds"
    TIMEOUT = "timeout"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    # 模型一次工具都沒執行就給出最終答案(require_tool_call_before_answer)
    NO_TOOL_CALL = "no_tool_call"
    # 模型自己呼叫 report_out_of_scope 宣告現有工具涵蓋不到
    OUT_OF_SCOPE = "out_of_scope"


class AgentResponse(BaseModel):
    model_config = ConfigDict(strict=True)

    answer: str
    evidence: list[Evidence]
    limitations: str | None
    refused: bool
    # 沒拒答時是 None。拒答時必定有值——「為什麼拒答」不該只存在於日誌裡。
    refusal_reason: RefusalReason | None = None
    model: str
    latency_ms: int
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float
