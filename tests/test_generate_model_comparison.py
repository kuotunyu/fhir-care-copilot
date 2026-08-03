"""generate_model_comparison.py 的 build_markdown() 單元測試(不需要真實 eval 檔案)。"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import generate_model_comparison as gmc  # noqa: E402


def _fake_run(
    provider: str,
    model_id: str,
    *,
    injection_resisted: bool,
    full_eval: bool = False,
    new_metric_schema: bool = False,
) -> dict:  # type: ignore[type-arg]
    metrics = {
        "total_cases": 1,
        "tool_selection_accuracy": 1.0,
        "field_exact_match_rate": 0.5,
        "citation_validity_rate": 1.0,
        "unsupported_claim_rate": 0.0,
        "refusal_accuracy": 1.0,
        "injection_resistance_rate": 1.0 if injection_resisted else 0.0,
        "p50_latency_ms": 100.0,
        "p95_latency_ms": 200.0,
        "average_cost_usd": 0.001,
        "total_cost_usd": 0.001,
    }
    if new_metric_schema:
        metrics.update(
            {
                "reference_integrity_rate": 1.0,
                "evidence_coverage_rate": 0.8,
                "answer_without_evidence_rate": 0.2,
            }
        )
    return {
        "generated_at": "2026-01-01T00:00:00+00:00",
        "provider": provider,
        "model_id": model_id,
        "full_eval": full_eval,
        "n_cases_requested": 220 if full_eval else 1,
        "n_cases_completed": 220 if full_eval else 1,
        "metrics": metrics,
        "results": [
            {
                "case_id": "injection-000",
                "category": "injection",
                "patient_id": "p1",
                "question": "測試問題",
                "answer": "我不能這麼做。",
                "refused": False,
                "expected_refused": False,
                "tool_selection_correct": None,
                "field_match": None,
                "citation_valid": True,
                "unsupported_claim": None,
                "refusal_correct": True,
                "injection_resisted": injection_resisted,
                "latency_ms": 100,
                "estimated_cost_usd": 0.001,
            }
        ],
    }


def test_build_markdown_includes_key_sections_and_real_numbers() -> None:
    runs = [
        _fake_run("gemini", "gemini-3.1-flash-lite", injection_resisted=True),
        _fake_run("openai", "gpt-5.4-mini", injection_resisted=False),
    ]

    markdown = gmc.build_markdown(runs)

    assert "# 模型比較報告" in markdown
    assert "gemini-3.1-flash-lite" in markdown
    assert "gpt-5.4-mini" in markdown
    assert "100.0%" in markdown  # citation validity
    assert "手動核閱" in markdown
    assert "測試問題" in markdown
    assert "自動判準:抵抗住" in markdown
    assert "自動判準:未抵抗住" in markdown


def test_new_metric_schema_reports_measured_semantics() -> None:
    runs = [
        _fake_run(
            "mock",
            "mock-deterministic",
            injection_resisted=True,
            new_metric_schema=True,
        )
    ]

    markdown = gmc.build_markdown(runs)

    assert "Reference integrity rate" in markdown
    assert "Evidence coverage rate" in markdown
    assert "Answer-without-evidence rate" in markdown
    assert "逐句" in markdown
    assert "grounding" in markdown


def test_legacy_metric_schema_is_explicit_and_does_not_invent_new_numbers() -> None:
    markdown = gmc.build_markdown(
        [_fake_run("mock", "mock-deterministic", injection_resisted=True)]
    )

    assert "Reference integrity rate" in markdown
    assert "Evidence coverage rate" in markdown
    assert "n/a" in markdown
    assert "Legacy citation validity rate (deprecated)" in markdown
    assert "既有 committed raw results" in markdown


def test_full_three_model_report_has_no_fixed_model_count_or_small_sample_claim() -> None:
    runs = [
        _fake_run("gemini", "gemini-3.1", injection_resisted=True, full_eval=True),
        _fake_run("openai", "gpt-mini", injection_resisted=True, full_eval=True),
        _fake_run("openai", "gpt-nano", injection_resisted=True, full_eval=True),
    ]

    markdown = gmc.build_markdown(runs)

    assert "兩個模型" not in markdown
    assert "小樣本" not in markdown
    assert "三個模型" in markdown


def test_build_markdown_single_run_does_not_crash() -> None:
    runs = [_fake_run("mock", "mock-deterministic", injection_resisted=True)]
    markdown = gmc.build_markdown(runs)
    assert "mock-deterministic" in markdown
