"""跑 eval case,含預算守門(PLAN.md M5:預設 $5 上限,跑前估算、超過即停)。"""

from __future__ import annotations

import logging
import time

from fhir_copilot.agent.loop import answer_question
from fhir_copilot.config import Guardrails, ModelPricing, estimate_cost_usd
from fhir_copilot.eval.cases import EvalCase
from fhir_copilot.eval.metrics import EvalResult, evaluate_case
from fhir_copilot.providers.base import Provider
from fhir_copilot.store.base import FHIRStore

logger = logging.getLogger(__name__)

# 粗估每題平均 token 數(供跑前預算估算;實際數字依題目與模型而異)
_ESTIMATED_INPUT_TOKENS_PER_CASE = 2000
_ESTIMATED_OUTPUT_TOKENS_PER_CASE = 300


class BudgetExceededError(RuntimeError):
    """跑前估算的成本超過預算上限。"""


def estimate_total_cost_usd(n_cases: int, model_id: str, pricing: dict[str, ModelPricing]) -> float:
    return n_cases * estimate_cost_usd(
        model_id, _ESTIMATED_INPUT_TOKENS_PER_CASE, _ESTIMATED_OUTPUT_TOKENS_PER_CASE, pricing
    )


def run_eval(
    *,
    cases: list[EvalCase],
    provider: Provider,
    store: FHIRStore,
    guardrails: Guardrails,
    pricing: dict[str, ModelPricing],
    budget_usd: float = 5.0,
    pace_seconds: float = 0.0,
) -> list[EvalResult]:
    """跑前先估算總成本,超過預算直接 raise,不花一毛錢;執行中累計實際花費,
    超過預算就提前停止(剩餘題目不跑),回傳目前已完成的結果。

    ``pace_seconds``:每題之間的固定延遲(實測發現 Gemini 免費層速率限制是
    15 requests/min,單題若含多輪工具呼叫很容易撞到——真的要打線上模型時
    自己傳一個夠保守的值,不設就完全不 pace)。
    """
    estimated = estimate_total_cost_usd(len(cases), provider.model_id, pricing)
    if estimated > budget_usd:
        raise BudgetExceededError(
            f"預估成本 ${estimated:.4f}(共 {len(cases)} 題)超過預算上限 ${budget_usd:.2f}"
            f"——請減少題數或調高 budget_usd"
        )
    logger.info("預估成本 $%.4f(共 %d 題,預算上限 $%.2f)", estimated, len(cases), budget_usd)

    results: list[EvalResult] = []
    running_cost = 0.0
    for i, case in enumerate(cases):
        if running_cost >= budget_usd:
            logger.warning(
                "已達預算上限($%.4f >= $%.2f),提前停止,剩餘 %d 題未執行",
                running_cost,
                budget_usd,
                len(cases) - len(results),
            )
            break
        if i > 0 and pace_seconds > 0:
            time.sleep(pace_seconds)
        try:
            response = answer_question(
                provider=provider,
                store=store,
                patient_id=case.patient_id,
                question=case.question,
                guardrails=guardrails,
                pricing=pricing,
            )
        except Exception as exc:
            # **已經跑完的題目不能丟掉。** 2026-07-26 跑全量時主金鑰的每日配額用完
            # (429 RESOURCE_EXHAUSTED),例外一路冒出去,整個 run 直接崩掉——
            # 幾十分鐘的真實 API 呼叫全部白花。
            #
            # 這裡的處理方式和上面「預算超支就提前停」完全一致:停下來、保留已完成
            # 的結果、把原因記清楚。**中止不等於作廢。**
            logger.warning(
                "第 %d 題發生無法繼續的錯誤,提前停止並保留已完成的 %d 題:%s",
                i + 1,
                len(results),
                exc,
            )
            break
        running_cost += response.estimated_cost_usd
        results.append(evaluate_case(store, case, response))

    logger.info("完成 %d/%d 題,實際花費 $%.4f", len(results), len(cases), running_cost)
    return results
