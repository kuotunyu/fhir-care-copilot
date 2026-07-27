"""Eval harness:自動產生題目、跑 agent loop、算指標、預算守門。"""

from fhir_copilot.eval.cases import EvalCase, generate_cases
from fhir_copilot.eval.metrics import EvalMetrics, EvalResult, compute_metrics, evaluate_case
from fhir_copilot.eval.runner import BudgetExceededError, estimate_total_cost_usd, run_eval

__all__ = [
    "BudgetExceededError",
    "EvalCase",
    "EvalMetrics",
    "EvalResult",
    "compute_metrics",
    "estimate_total_cost_usd",
    "evaluate_case",
    "generate_cases",
    "run_eval",
]
