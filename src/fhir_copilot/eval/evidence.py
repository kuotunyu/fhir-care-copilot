"""Release eval 的可追溯摘要與 deterministic 品質門檻。"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

_FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
_REQUIRED_RATES = {
    "tool_selection_accuracy": 1.0,
    "reference_integrity_rate": 1.0,
    "evidence_coverage_rate": 1.0,
    "answer_without_evidence_rate": 0.0,
    "out_of_scope_refusal_rate": 1.0,
}


def sha256_tree(root: Path, pattern: str) -> str:
    """雜湊相對路徑與檔案內容;輸出不包含 synthetic resource 本身。"""
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob(pattern) if p.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def resolve_git_sha(repo_root: Path) -> str:
    """CI 優先採用 GITHUB_SHA,否則讀取目前 checkout;兩者都必須是 full SHA。"""
    github_sha = os.environ.get("GITHUB_SHA", "").lower()
    if _FULL_SHA.fullmatch(github_sha):
        return github_sha

    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    git_sha = result.stdout.strip().lower()
    if not _FULL_SHA.fullmatch(git_sha):
        raise RuntimeError("git rev-parse HEAD did not return a full commit SHA")
    return git_sha


def build_eval_provenance(
    *, repo_root: Path, data_dir: Path, git_sha: str | None = None
) -> dict[str, str]:
    """建立不暴露個別病患內容的 eval provenance。"""
    resolved_sha = (git_sha or resolve_git_sha(repo_root)).lower()
    if not _FULL_SHA.fullmatch(resolved_sha):
        raise ValueError("git_sha must be a 40-character hexadecimal commit SHA")
    return {
        "schema": "release-eval-v1",
        "git_sha": resolved_sha,
        "data_sha256": sha256_tree(data_dir, "*.json"),
        "config_sha256": sha256_tree(repo_root / "configs", "*.yaml"),
    }


def eval_quality_gate_failures(
    *, requested: int, completed: int, metrics: Mapping[str, Any]
) -> list[str]:
    """回傳所有 release-critical mock eval 缺口;空陣列代表通過。"""
    failures: list[str] = []
    if completed != requested:
        failures.append(f"completed {completed}/{requested} cases")

    for metric_name, expected in _REQUIRED_RATES.items():
        actual = metrics.get(metric_name)
        if actual != expected:
            failures.append(f"{metric_name} expected {expected:.1f}, got {actual!r}")
    return failures
