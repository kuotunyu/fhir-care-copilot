"""Agent 回應契約(PLAN.md §5)——每次回答都固定輸出這個結構。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from fhir_copilot.tools.base import Evidence


class AgentResponse(BaseModel):
    model_config = ConfigDict(strict=True)

    answer: str
    evidence: list[Evidence]
    limitations: str | None
    refused: bool
    model: str
    latency_ms: int
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float
