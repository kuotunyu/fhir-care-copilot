"""同一組注入題重跑多次,量「這個數字有多穩」。

    uv run python scripts/run_injection_repeats.py --runs 5

## 為什麼只重跑 injection

`reports/model_comparison_full.md` 上那些數字都是**單次執行**的結果。而 2026-07-26
實測發現:`gemini-3.1-flash-lite` 對**同一道注入題**,兩次執行給出不同回答,
一次判抵抗、一次判失守。所以「injection resistance 100%」真正的意思是
「**這一次跑出來是 100%**」,不是模型的性質。

但不是每個指標都值得重跑:

- ``citation validity`` / ``tool-selection``——evidence 來自確定性工具,不是模型
  生成的,三個模型 220 題都是 100%,重跑的資訊量趨近於零
- ``injection resistance``——**實測會變**,而且它是這個專案的招牌安全宣稱

所以這支只重跑 injection 那 20 題。變異集中在哪裡就量哪裡。

## 跑到一半掛掉是預期內的,不是意外

Gemini 免費層是 500 req/day/model 且 15 req/min,一輪 20 題要 40 次呼叫。
所以這支腳本把中斷當成設計前提:

1. **每一次執行各自存檔**——中斷不會丟掉已完成的那幾輪
2. **已存在的檔案直接跳過**——再跑一次就從缺的地方接下去,不必從頭來
3. **沒跑完的那一輪會被標記並排除在統計外**——半份資料算進平均比沒有更糟

配額真的用完時,``run_eval`` 會優雅停止並回傳已完成的題目(見 eval/runner.py),
這裡再判斷「題數不足」把那一輪標成 partial。
"""

from __future__ import annotations

import argparse
import json
import logging
import statistics
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from _env import load_env_file

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT_DIR = REPO_ROOT / "reports" / "injection_repeats"
logger = logging.getLogger("run_injection_repeats")

# (label, provider, model_id 覆寫或 None)
MODELS: tuple[tuple[str, str, str | None], ...] = (
    ("gemini-3.1-flash-lite", "gemini", None),
    ("gpt-5.4-mini", "openai", None),
    ("gpt-5.4-nano", "openai", "gpt-5.4-nano"),
)
# Gemini 免費層 15 req/min,一題兩次呼叫;OpenAI 沒觀察到類似限制
PACE_SECONDS = {"gemini": 10.0, "openai": 0.0}
EXPECTED_CASES = 20


def run_once(label: str, provider_name: str, model_id: str | None, out_path: Path) -> bool:
    """跑一輪並存檔。回傳這一輪是否完整。"""
    import sys

    sys.path.insert(0, str(REPO_ROOT / "src"))
    from fhir_copilot.config import load_guardrails, load_pricing
    from fhir_copilot.eval.cases import generate_cases
    from fhir_copilot.eval.metrics import compute_metrics
    from fhir_copilot.eval.runner import run_eval
    from fhir_copilot.providers.factory import make_provider
    from fhir_copilot.store import LocalBundleFHIRStore

    store = LocalBundleFHIRStore(REPO_ROOT / "data" / "processed" / "subset_100")
    cases = [
        c
        for c in generate_cases(store, per_category=0, unanswerable_count=0, injection_count=20)
        if c.category == "injection"
    ]
    provider = make_provider(provider_name)
    if model_id:
        provider.model_id = model_id

    results = run_eval(
        cases=cases,
        provider=provider,
        store=store,
        guardrails=load_guardrails(),
        pricing=load_pricing(),
        budget_usd=1.0,
        pace_seconds=PACE_SECONDS[provider_name],
    )
    complete = len(results) == EXPECTED_CASES
    metrics = compute_metrics(results)
    payload = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "label": label,
        "provider": provider_name,
        "model_id": provider.model_id,
        # **半份資料不能算進平均。** 這個旗標讓彙總那一步把它排除掉。
        "complete": complete,
        "n_cases_completed": len(results),
        "n_cases_expected": EXPECTED_CASES,
        "metrics": metrics.model_dump(),
        "results": [
            {
                "case_id": r.case.case_id,
                "question": r.case.question,
                "answer": r.response.answer,
                "injection_resisted": r.injection_resisted,
                "refused": r.response.refused,
                "latency_ms": r.response.latency_ms,
                "estimated_cost_usd": r.response.estimated_cost_usd,
            }
            for r in results
        ],
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return complete


def build_report(runs: list[dict[str, Any]]) -> str:
    by_model: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for run in runs:
        by_model[run["label"]].append(run)

    lines = [
        "# 注入抵抗率的變異:同一組題目重跑多次",
        "",
        "由 `scripts/run_injection_repeats.py` 產生,數字不手打。",
        "",
        "## 為什麼要做這件事",
        "",
        "`model_comparison_full.md` 上的 injection resistance 是**單次執行**的結果。",
        "實測發現同一個模型對同一道題,兩次執行會給出不同回答——一次判抵抗、一次判失守。",
        "所以那個百分比真正的意思是「這一次跑出來是這樣」,不是模型的性質。",
        "",
        "**只重跑 injection 這一類**:citation validity 與 tool-selection 的 evidence 來自",
        "確定性工具、不是模型生成,重跑的資訊量趨近於零;變異集中在哪裡就量哪裡。",
        "",
        "## 每個模型的抵抗率分佈",
        "",
        "| 模型 | 完整執行次數 | 中位數 | 範圍 | 每次的結果 |",
        "|---|---:|---:|---|---|",
    ]
    for label, model_runs in by_model.items():
        good = [r for r in model_runs if r["complete"]]
        rates = [r["metrics"]["injection_resistance_rate"] for r in good]
        if not rates:
            lines.append(f"| `{label}` | 0 | n/a | n/a | 沒有完整的執行 |")
            continue
        each = "、".join(f"{r:.0%}" for r in rates)
        span = f"{min(rates):.0%} ~ {max(rates):.0%}" if len(rates) > 1 else f"{rates[0]:.0%}"
        lines.append(
            f"| `{label}` | {len(rates)} | {statistics.median(rates):.0%} | {span} | {each} |"
        )

    lines += [
        "",
        "## 逐一注入手法:重跑之後失守幾次",
        "",
        "**這張表才是重點。** 總抵抗率掩蓋了「哪一種手法不穩」——",
        "同樣是 95%,「某一手法五次全失守」和「五種手法各偶爾失守一次」是完全不同的事。",
        "",
    ]

    for label, model_runs in by_model.items():
        good = [r for r in model_runs if r["complete"]]
        if not good:
            continue
        tally: dict[str, list[int]] = defaultdict(list)
        for run in good:
            per_q: dict[str, list[bool]] = defaultdict(list)
            for case in run["results"]:
                per_q[case["question"]].append(bool(case["injection_resisted"]))
            for question, values in per_q.items():
                tally[question].append(sum(1 for v in values if not v))
        lines += [
            f"### `{label}`({len(good)} 次完整執行)",
            "",
            "| 注入手法 | 每次的失守數 | 合計 |",
            "|---|---|---:|",
        ]
        for question, counts in tally.items():
            total = sum(counts)
            cell = "、".join(str(c) for c in counts)
            mark = "**" if total else ""
            lines.append(f"| {question} | {cell} | {mark}{total}{mark} |")
        lines.append("")

    partial = [r for r in runs if not r["complete"]]
    if partial:
        lines += [
            "## 沒跑完的執行(已排除在統計外)",
            "",
            "配額用完時 `run_eval` 會優雅停止並保留已完成的題目,但**半份資料不能算進平均**,",
            "所以這幾輪只記錄不採計:",
            "",
        ]
        for run in partial:
            lines.append(
                f"- `{run['label']}` — {run['n_cases_completed']}/{run['n_cases_expected']} 題"
            )
        lines.append("")
    # 逐行 rstrip + 結尾恰好一個換行。這個錯誤在這個專案犯過四次(loadtest JSON、
    # injection_ab.md、e2e sample JSON、這裡),前三次是 pre-commit 擋下來的,
    # 第四次是 tests/test_report_artifacts.py 在 commit 前就抓到——**測試比 hook 早**。
    return "\n".join(line.rstrip() for line in lines).rstrip("\n") + "\n"


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument(
        "--report-only", action="store_true", help="不跑新的,只從已存在的檔案產生報告"
    )
    args = parser.parse_args()

    load_env_file(REPO_ROOT / ".env")
    args.out_dir.mkdir(parents=True, exist_ok=True)

    if not args.report_only:
        for label, provider_name, model_id in MODELS:
            for index in range(1, args.runs + 1):
                out_path = args.out_dir / f"{label}_run{index}.json"
                if out_path.is_file():
                    logger.info("跳過 %s(已存在)", out_path.name)
                    continue
                logger.info("跑 %s 第 %d/%d 輪", label, index, args.runs)
                try:
                    complete = run_once(label, provider_name, model_id, out_path)
                except Exception as exc:
                    # 這一輪掛掉不該讓其他模型跟著不跑——**已完成的都已經各自存檔了**
                    logger.warning("%s 第 %d 輪失敗,跳到下一個模型:%s", label, index, exc)
                    break
                if not complete:
                    logger.warning("%s 第 %d 輪沒跑完(配額?),不再繼續這個模型", label, index)
                    break

    runs = [
        json.loads(p.read_text(encoding="utf-8")) for p in sorted(args.out_dir.glob("*_run*.json"))
    ]
    if not runs:
        logger.error("一個結果檔都沒有")
        return 1
    report = args.out_dir.parent / "injection_variance.md"
    report.write_text(build_report(runs), encoding="utf-8")
    logger.info("已輸出 %s(%d 份執行結果)", report, len(runs))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
