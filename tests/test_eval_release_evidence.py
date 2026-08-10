"""Release eval 證據:品質門檻與不含病患內容的 provenance。"""

from pathlib import Path

from fhir_copilot.eval.evidence import (
    build_eval_provenance,
    eval_quality_gate_failures,
    sha256_tree,
)


def test_sha256_tree_is_deterministic_and_content_sensitive(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "b.json").write_text('{"value": 2}\n', encoding="utf-8")
    (data_dir / "a.json").write_text('{"value": 1}\n', encoding="utf-8")

    first = sha256_tree(data_dir, "*.json")
    second = sha256_tree(data_dir, "*.json")
    (data_dir / "a.json").write_text('{"value": 3}\n', encoding="utf-8")

    assert first == second
    assert len(first) == 64
    assert sha256_tree(data_dir, "*.json") != first


def test_build_eval_provenance_records_git_data_and_config_hashes(tmp_path: Path) -> None:
    data_dir = tmp_path / "fixtures"
    config_dir = tmp_path / "configs"
    data_dir.mkdir()
    config_dir.mkdir()
    (data_dir / "patient.json").write_text("{}\n", encoding="utf-8")
    (config_dir / "guardrails.yaml").write_text("max_tool_rounds: 6\n", encoding="utf-8")

    provenance = build_eval_provenance(
        repo_root=tmp_path,
        data_dir=data_dir,
        git_sha="a" * 40,
    )

    assert provenance == {
        "schema": "release-eval-v1",
        "git_sha": "a" * 40,
        "data_sha256": sha256_tree(data_dir, "*.json"),
        "config_sha256": sha256_tree(config_dir, "*.yaml"),
    }


def test_eval_quality_gate_accepts_complete_safe_mock_run() -> None:
    failures = eval_quality_gate_failures(
        requested=34,
        completed=34,
        metrics={
            "tool_selection_accuracy": 1.0,
            "reference_integrity_rate": 1.0,
            "evidence_coverage_rate": 1.0,
            "answer_without_evidence_rate": 0.0,
            "out_of_scope_refusal_rate": 1.0,
        },
    )

    assert failures == []


def test_eval_quality_gate_reports_partial_and_unsafe_run() -> None:
    failures = eval_quality_gate_failures(
        requested=34,
        completed=33,
        metrics={
            "tool_selection_accuracy": 0.9,
            "reference_integrity_rate": 1.0,
            "evidence_coverage_rate": 1.0,
            "answer_without_evidence_rate": 0.1,
            "out_of_scope_refusal_rate": 0.0,
        },
    )

    assert "completed 33/34 cases" in failures
    assert any("tool_selection_accuracy" in failure for failure in failures)
    assert any("answer_without_evidence_rate" in failure for failure in failures)
    assert any("out_of_scope_refusal_rate" in failure for failure in failures)
