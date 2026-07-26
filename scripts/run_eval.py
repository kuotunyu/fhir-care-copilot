"""Eval CLI(PLAN.md M5/M6):自動產生題目、跑 agent loop、算指標、預算守門。

小樣本(預設,每類別 6 題,約 30 題):
    uv run python scripts/run_eval.py --provider mock
    uv run python scripts/run_eval.py --provider gemini

完整題庫(~220 題):
    uv run python scripts/run_eval.py --provider openai --full-eval

預設預算上限 $5 美元;跑前先估算,超過直接中止不花錢;執行中累計實際花費,
超過就提前停止(結果只包含已完成的題目)。
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

logger = logging.getLogger("run-eval")


def _fmt_rate(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.1%}"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--provider", default="mock", choices=["mock", "gemini", "openai"])
    parser.add_argument("--data-dir", default=str(REPO_ROOT / "data" / "processed" / "subset_100"))
    parser.add_argument(
        "--full-eval", action="store_true", help="用完整題庫(~220 題);預設用小樣本快速跑"
    )
    parser.add_argument(
        "--sample-per-category", type=int, default=6, help="小樣本模式每個題型的題數(預設 6)"
    )
    parser.add_argument("--budget-usd", type=float, default=5.0, help="預算上限,美元(預設 5)")
    parser.add_argument(
        "--pace-seconds",
        type=float,
        default=0.0,
        help="每題之間的延遲秒數(打真實 API 時用,避免撞到速率限制;預設不 pace)",
    )
    parser.add_argument(
        "--model-id",
        default="",
        help=(
            "覆寫 configs/models.yaml 的 model_id,只影響這一次執行。"
            "用途是同一個 provider 下的 A/B 對照(例如比較新舊版模型),"
            "不必為了跑一次比較就改設定檔。單價仍必須在 pricing.yaml 裡"
        ),
    )
    parser.add_argument(
        "--categories",
        default="",
        help=(
            "只跑指定題型(逗號分隔,如 injection 或 medication,condition);預設全跑。"
            "判準改了要重新量某一個維度時,不必為此把整份題庫重跑一遍"
        ),
    )
    parser.add_argument("--out", default=str(REPO_ROOT / "reports" / "eval_results.json"))
    args = parser.parse_args()

    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    sys.path.insert(0, str(REPO_ROOT / "src"))
    from fhir_copilot.config import load_guardrails, load_pricing
    from fhir_copilot.eval import BudgetExceededError, compute_metrics, generate_cases, run_eval
    from fhir_copilot.providers.factory import make_provider
    from fhir_copilot.store import LocalBundleFHIRStore

    store = LocalBundleFHIRStore(args.data_dir)
    guardrails = load_guardrails()
    pricing = load_pricing()
    provider = make_provider(args.provider)
    if args.model_id:
        # provider 物件無狀態,model_id 只是傳給 SDK 的字串,直接覆寫是安全的。
        # 缺單價時 estimate_cost_usd 會 raise——那是刻意的,不能默默當 0 元。
        logger.info("覆寫 model_id:%s -> %s", provider.model_id, args.model_id)
        provider.model_id = args.model_id

    if args.full_eval:
        cases = generate_cases(store)
    else:
        n = args.sample_per_category
        cases = generate_cases(
            store,
            per_category=n,
            unanswerable_count=max(2, n // 2),
            injection_count=max(2, n // 2),
        )
    if args.categories:
        wanted = {c.strip() for c in args.categories.split(",") if c.strip()}
        unknown = wanted - {c.category for c in cases}
        if unknown:
            raise SystemExit(f"未知的題型:{sorted(unknown)}")
        cases = [c for c in cases if c.category in wanted]

    logger.info(
        "產生 %d 題(full_eval=%s,provider=%s,categories=%s)",
        len(cases),
        args.full_eval,
        args.provider,
        args.categories or "全部",
    )

    try:
        results = run_eval(
            cases=cases,
            provider=provider,
            store=store,
            guardrails=guardrails,
            pricing=pricing,
            budget_usd=args.budget_usd,
            pace_seconds=args.pace_seconds,
        )
    except BudgetExceededError as exc:
        print(f"預算超限,中止,沒有花任何錢:{exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    metrics = compute_metrics(results)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "provider": args.provider,
        "model_id": provider.model_id,
        "full_eval": args.full_eval,
        "n_cases_requested": len(cases),
        "n_cases_completed": len(results),
        "metrics": metrics.model_dump(),
        "results": [
            {
                "case_id": r.case.case_id,
                "category": r.case.category,
                "patient_id": r.case.patient_id,
                "question": r.case.question,
                "answer": r.response.answer,
                "refused": r.response.refused,
                "expected_refused": r.case.expected_refused,
                "tool_selection_correct": r.tool_selection_correct,
                "field_match": r.field_match,
                "citation_valid": r.citation_valid,
                "unsupported_claim": r.unsupported_claim,
                "refusal_correct": r.refusal_correct,
                "injection_resisted": r.injection_resisted,
                "latency_ms": r.response.latency_ms,
                "estimated_cost_usd": r.response.estimated_cost_usd,
            }
            for r in results
        ],
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("寫入 %s", out_path)

    print(
        f"\n=== {args.provider}({provider.model_id}) eval 結果({len(results)}/{len(cases)} 題) ==="
    )
    print(f"tool-selection accuracy: {_fmt_rate(metrics.tool_selection_accuracy)}")
    print(f"field exact match rate:  {_fmt_rate(metrics.field_exact_match_rate)}")
    print(f"citation validity rate:  {_fmt_rate(metrics.citation_validity_rate)}")
    print(f"unsupported claim rate:  {_fmt_rate(metrics.unsupported_claim_rate)}")
    print(f"refusal accuracy:        {_fmt_rate(metrics.refusal_accuracy)}")
    print(f"injection resistance:    {_fmt_rate(metrics.injection_resistance_rate)}")
    print(f"p50 / p95 latency (ms):  {metrics.p50_latency_ms:.0f} / {metrics.p95_latency_ms:.0f}")
    print(
        f"avg / total cost (USD):  ${metrics.average_cost_usd:.5f} / ${metrics.total_cost_usd:.4f}"
    )


if __name__ == "__main__":
    main()
