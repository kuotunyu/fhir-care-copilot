"""Eval harness:自動產生題目、跑 agent loop、算指標、預算守門。"""

from fhir_copilot.eval.cases import EvalCase, generate_cases
from fhir_copilot.eval.evidence import build_eval_provenance, eval_quality_gate_failures
from fhir_copilot.eval.metrics import EvalMetrics, EvalResult, compute_metrics, evaluate_case
from fhir_copilot.eval.runner import BudgetExceededError, estimate_total_cost_usd, run_eval

__all__ = [
    "BudgetExceededError",
    "EvalCase",
    "EvalMetrics",
    "EvalResult",
    "build_eval_provenance",
    "compute_metrics",
    "estimate_total_cost_usd",
    "eval_quality_gate_failures",
    "evaluate_case",
    "generate_cases",
    "run_eval",
]
