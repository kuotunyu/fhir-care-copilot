"""同一組題目重跑多次,量「這個數字有多穩」。

    uv run python scripts/run_repeat_eval.py --category injection --runs 3
    uv run python scripts/run_repeat_eval.py --category out_of_scope --runs 3 \
        --models gemini-3.1-flash-lite

(原名 ``run_injection_repeats.py``。2026-07-27 新增 out_of_scope 題型時一般化並改名
——一支叫「injection repeats」的腳本跑 out-of-scope 題目,名字就開始說謊了。)

## 為什麼只重跑這兩類

``reports/model_comparison_full.md`` 上那些數字都是**單次執行**的結果。而 2026-07-26
實測發現:``gemini-3.1-flash-lite`` 對**同一道注入題**,兩次執行給出不同回答,
一次判抵抗、一次判失守。所以「injection resistance 100%」真正的意思是
「**這一次跑出來是 100%**」,不是模型的性質。

但不是每個指標都值得重跑:

- ``citation validity`` / ``tool-selection``——evidence 來自確定性工具,不是模型
  生成的,三個模型 220 題都是 100%,重跑的資訊量趨近於零
- ``unanswerable``——病患不存在時工具回 ``ok=False``,拒答是確定性的,不會變
- ``injection`` / ``out_of_scope``——**實測會變**,而且它們量的都是模型的行為

所以這支只跑這兩類。變異集中在哪裡就量哪裡。

## 兩類量的是不同的東西

- ``injection``——夾帶指令時模型會不會服從(``injection_resistance_rate``)
- ``out_of_scope``——病患存在、但問的東西 5 個資料工具都查不到時,模型會不會
  呼叫 ``report_out_of_scope``(``out_of_scope_refusal_rate``)。這一類的護欄
  2026-07-26 才做,機制有確定性測試,但**觸發率要靠這裡量出來**

## 跑到一半掛掉是預期內的,不是意外

Gemini 免費層是 500 req/day/model 且 15 req/min,一輪 20 題要 40 次呼叫。
所以這支腳本把中斷當成設計前提:

1. **每一次執行各自存檔**——中斷不會丟掉已完成的那幾輪
2. **只跳過「完整」的檔案**——半份的會重跑覆蓋掉。原本是「檔案存在就跳過」,
   2026-07-27 實測踩到:一輪在第 11 題撞上 503,留下 10/20 的檔案,再跑一次
   就被跳過,於是永遠湊不出完整的一輪
3. **沒跑完的那一輪會被標記並排除在統計外**——半份資料算進平均比沒有更糟
4. **不完整就重試**(``--max-attempts``,預設 3)。原本把「沒跑完」一律當成配額
   用完就放棄整個模型,但 503 過載是暫時性的、重試就好——兩種失敗不該混為一談
"""

from __future__ import annotations

import argparse
import json
import logging
import statistics
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from _env import load_env_file

REPO_ROOT = Path(__file__).resolve().parent.parent
REPORTS_DIR = REPO_ROOT / "reports"
logger = logging.getLogger("run_repeat_eval")

# (label, provider, model_id 覆寫或 None)
MODELS: tuple[tuple[str, str, str | None], ...] = (
    ("gemini-3.1-flash-lite", "gemini", None),
    ("gpt-5.4-mini", "openai", None),
    ("gpt-5.4-nano", "openai", "gpt-5.4-nano"),
)
# Gemini 免費層 15 req/min,一題兩次呼叫;OpenAI 沒觀察到類似限制
PACE_SECONDS = {"gemini": 10.0, "openai": 0.0}
EXPECTED_CASES = 20

# 每一類要看的主指標,以及該類「這一題判失敗」的定義。
# 放在同一個地方,免得報表的標題與實際算的東西分岔。
CATEGORY_SPEC: dict[str, dict[str, str]] = {
    "injection": {
        "metric": "injection_resistance_rate",
        "metric_label": "注入抵抗率",
        "failure_label": "失守數",
        "title": "注入抵抗率的變異:同一組題目重跑多次",
    },
    "out_of_scope": {
        "metric": "out_of_scope_refusal_rate",
        "metric_label": "正確拒答率",
        "failure_label": "沒拒答數",
        "title": "超出範圍時的拒答率:同一組題目重跑多次",
    },
}


def _case_failed(category: str, case: dict[str, Any]) -> bool:
    """這一題算不算「沒做到該做的事」。"""
    if category == "injection":
        return not case["injection_resisted"]
    return not case["refused"]


def run_once(
    category: str, label: str, provider_name: str, model_id: str | None, out_path: Path
) -> bool:
    """跑一輪並存檔。回傳這一輪是否完整。"""
    import sys

    sys.path.insert(0, str(REPO_ROOT / "src"))
    from fhir_copilot.config import load_guardrails, load_pricing
    from fhir_copilot.eval.cases import generate_cases
    from fhir_copilot.eval.metrics import compute_metrics
    from fhir_copilot.eval.runner import run_eval
    from fhir_copilot.providers.factory import make_provider
    from fhir_copilot.store import LocalBundleFHIRStore
    from fhir_copilot.tools.registry import READ_ONLY_TOOLS

    store = LocalBundleFHIRStore(REPO_ROOT / "data" / "processed" / "subset_100")
    guardrails = load_guardrails()
    counts = {
        "per_category": 0,
        "unanswerable_count": 0,
        "injection_count": EXPECTED_CASES if category == "injection" else 0,
        "out_of_scope_count": EXPECTED_CASES if category == "out_of_scope" else 0,
    }
    cases = [c for c in generate_cases(store, **counts) if c.category == category]
    provider = make_provider(provider_name)
    if model_id:
        provider.model_id = model_id

    results = run_eval(
        cases=cases,
        provider=provider,
        store=store,
        guardrails=guardrails,
        pricing=load_pricing(),
        budget_usd=1.0,
        pace_seconds=PACE_SECONDS[provider_name],
    )
    complete = len(results) == EXPECTED_CASES
    metrics = compute_metrics(results)
    payload = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "category": category,
        "label": label,
        "provider": provider_name,
        "model_id": provider.model_id,
        # **哪一組護欄之下量的。** 2026-07-26 之前的執行結果檔沒有這個欄位,
        # 彙總時會被歸到「舊護欄」那一組——把兩組混在一起平均就是假比較,
        # 而那正是這次要避免的:新數字要能對得回舊數字,不是取代它。
        "guardrails": {
            "require_tool_call_before_answer": guardrails.require_tool_call_before_answer,
            "has_out_of_scope_tool": any(not spec.queries_patient_data for spec in READ_ONLY_TOOLS),
        },
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
                "limitations": r.response.limitations,
                "injection_resisted": r.injection_resisted,
                "refused": r.response.refused,
                # **哪一道護欄擋下來的。** 沒有這個欄位的話,20 題全部拒答時
                # 分不出模型是主動宣告查不到、還是根本沒呼叫工具被攔下來。
                "refusal_reason": r.response.refusal_reason,
                "n_evidence": len(r.response.evidence),
                "latency_ms": r.response.latency_ms,
                "estimated_cost_usd": r.response.estimated_cost_usd,
            }
            for r in results
        ],
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return complete


def _is_complete_run(path: Path) -> bool:
    """這個結果檔是不是一輪完整的執行(壞掉或半份都算不是)。"""
    if not path.is_file():
        return False
    try:
        return bool(json.loads(path.read_text(encoding="utf-8")).get("complete"))
    except (OSError, json.JSONDecodeError):
        return False


def _run_with_retries(
    category: str,
    label: str,
    provider_name: str,
    model_id: str | None,
    out_path: Path,
    max_attempts: int,
) -> bool:
    """跑一輪,不完整就重試。回傳最後有沒有拿到完整的一輪。

    **原本這裡把「沒跑完」一律當成配額用完就放棄整個模型。** 那個判斷對配額是對的
    (耗盡時重試沒用,要等隔天),但 2026-07-27 實測撞到的是
    ``503 UNAVAILABLE: This model is currently experiencing high demand``
    ——暫時性過載,重試就好,結果卻讓整組 out_of_scope 量測一輪都沒跑成。

    這裡不去猜是哪一種:**重試幾次,連續失敗才放棄**。配額真的用完時每次都會在
    第一題就失敗,幾秒內就耗完 attempts,代價很小;暫時性故障則救得回來。
    """
    for attempt in range(1, max_attempts + 1):
        logger.info(
            "跑 %s / %s → %s(第 %d/%d 次嘗試)",
            category,
            label,
            out_path.name,
            attempt,
            max_attempts,
        )
        try:
            if run_once(category, label, provider_name, model_id, out_path):
                return True
            logger.warning("%s 沒跑完(可能是配額或暫時性故障)", out_path.name)
        except Exception as exc:
            logger.warning("%s 這次嘗試失敗:%s", out_path.name, exc)
        if attempt < max_attempts:
            wait = 30 * attempt
            logger.info("等 %d 秒再試", wait)
            time.sleep(wait)
    return False


_COHORT_NEW = "新護欄(2026-07-27 起)"
_COHORT_OLD = "舊護欄(2026-07-26 之前)"


def _cohort(run: dict[str, Any]) -> str:
    """這一輪是在哪一組護欄之下跑的。

    2026-07-26 之前的結果檔沒有 ``guardrails`` 欄位——**缺欄位就是舊的**,
    不要當成「未知」丟掉,也不要跟新的混在一起平均。
    """
    guardrails = run.get("guardrails") or {}
    return _COHORT_NEW if guardrails.get("require_tool_call_before_answer") else _COHORT_OLD


def build_report(category: str, runs: list[dict[str, Any]]) -> str:
    spec = CATEGORY_SPEC[category]
    by_model: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for run in runs:
        by_model[(_cohort(run), run["label"])].append(run)

    lines = [
        f"# {spec['title']}",
        "",
        "由 `scripts/run_repeat_eval.py` 產生,數字不手打。",
        "",
        "## 為什麼要做這件事",
        "",
        "`model_comparison_full.md` 上那些數字是**單次執行**的結果。",
        "實測發現同一個模型對同一道題,兩次執行會給出不同回答。",
        "所以那個百分比真正的意思是「這一次跑出來是這樣」,不是模型的性質。",
        "",
        f"## 每個模型的{spec['metric_label']}分佈",
        "",
        f"| 護欄 | 模型 | 完整執行次數 | 中位數 | 範圍 | 每次的{spec['metric_label']} |",
        "|---|---|---:|---:|---|---|",
    ]
    for (cohort, label), model_runs in sorted(by_model.items()):
        good = [r for r in model_runs if r["complete"]]
        rates = [
            r["metrics"][spec["metric"]]
            for r in good
            if r["metrics"].get(spec["metric"]) is not None
        ]
        if not rates:
            lines.append(f"| {cohort} | `{label}` | 0 | n/a | n/a | 沒有完整的執行 |")
            continue
        each = "、".join(f"{r:.0%}" for r in rates)
        span = f"{min(rates):.0%} ~ {max(rates):.0%}" if len(rates) > 1 else f"{rates[0]:.0%}"
        lines.append(
            f"| {cohort} | `{label}` | {len(rates)} | {statistics.median(rates):.0%} "
            f"| {span} | {each} |"
        )

    lines += [
        "",
        "## 逐題:重跑之後失敗幾次",
        "",
        "**這張表才是重點。** 總百分比掩蓋了「哪一種情況不穩」——",
        "同樣是 95%,「某一題五次全錯」和「五題各偶爾錯一次」是完全不同的事。",
        "",
    ]

    for (cohort, label), model_runs in sorted(by_model.items()):
        good = [r for r in model_runs if r["complete"]]
        if not good:
            continue
        tally: dict[str, list[int]] = defaultdict(list)
        for run in good:
            per_q: dict[str, list[bool]] = defaultdict(list)
            for case in run["results"]:
                per_q[case["question"]].append(_case_failed(category, case))
            for question, values in per_q.items():
                tally[question].append(sum(1 for v in values if v))
        lines += [
            f"### {cohort} — `{label}`({len(good)} 次完整執行)",
            "",
            f"| 題目 | 每次的{spec['failure_label']} | 合計 |",
            "|---|---|---:|",
        ]
        for question, counts in tally.items():
            total = sum(counts)
            cell = "、".join(str(c) for c in counts)
            mark = "**" if total else ""
            lines.append(f"| {question} | {cell} | {mark}{total}{mark} |")
        lines.append("")

    # **這個百分比是怎麼來的。** 沒有這一段的話,「100%」讀起來像模型的性質,
    # 實際上可能整組都是護欄擋下來的。refusal_reason 是 2026-07-27 才加的欄位,
    # 更早的執行結果沒有——只統計有的那些,並標明樣本數。
    with_reason = [r for r in runs if r["complete"] and "refusal_reason" in r["results"][0]]
    if with_reason:
        tally_reason: dict[str, int] = defaultdict(int)
        for run in with_reason:
            for case in run["results"]:
                tally_reason[case["refusal_reason"] or "(沒拒答)"] += 1
        total_cases = sum(tally_reason.values())
        lines += [
            "## 拒答是哪一道護欄擋下來的",
            "",
            f"依 `refusal_reason` 統計,涵蓋 {len(with_reason)} 次執行 / {total_cases} 題。",
            "**這一段決定上面那個百分比怎麼讀**——整組都是護欄擋下來的話,那個數字",
            "衡量的是護欄,不是模型,拿來比較不同模型就沒有意義了。",
            "",
            "| refusal_reason | 題數 | 佔比 |",
            "|---|---:|---:|",
        ]
        for reason, count in sorted(tally_reason.items(), key=lambda kv: -kv[1]):
            lines.append(f"| `{reason}` | {count} | {count / total_cases:.0%} |")
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
    # 逐行 rstrip + 結尾恰好一個換行。這個錯誤在這個專案犯過四次,
    # 由 tests/test_report_artifacts.py 守著。
    return "\n".join(line.rstrip() for line in lines).rstrip("\n") + "\n"


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--category", choices=sorted(CATEGORY_SPEC), default="injection")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument(
        "--models",
        nargs="*",
        default=None,
        help="只跑這些 label(預設全部)。額度有限時用來鎖定單一模型。",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=3,
        help="同一輪最多嘗試幾次。暫時性故障(503 過載)重試就好,配額用完則每次都會"
        "在第一題失敗、幾秒內耗完,兩者不必分開判斷。",
    )
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument(
        "--tag",
        default="",
        help="加進檔名的標記,例如 --tag guarded 會存成 <model>_guarded_run1.json。"
        "用途是讓**改了護欄之後的重跑**與舊結果放在同一個目錄(報表才對得起來),"
        "同時不會被「已存在就跳過」誤判成跑過了。放不同目錄的話報表只看得到一半。",
    )
    parser.add_argument(
        "--report-only", action="store_true", help="不跑新的,只從已存在的檔案產生報告"
    )
    args = parser.parse_args()

    load_env_file(REPO_ROOT / ".env")
    out_dir = args.out_dir or REPORTS_DIR / f"{args.category}_repeats"
    out_dir.mkdir(parents=True, exist_ok=True)
    models = [m for m in MODELS if args.models is None or m[0] in args.models]
    if not models:
        logger.error("--models 沒有對到任何模型;可選:%s", ", ".join(m[0] for m in MODELS))
        return 1

    if not args.report_only:
        for label, provider_name, model_id in models:
            for index in range(1, args.runs + 1):
                suffix = f"_{args.tag}" if args.tag else ""
                out_path = out_dir / f"{label}{suffix}_run{index}.json"
                # **只跳過「完整」的那些。** 半途中斷的檔案本來就被排除在統計外,
                # 留著它只會讓下次重跑誤以為這一輪跑過了。2026-07-27 實測踩到:
                # out_of_scope 第 1 輪在第 11 題撞上 503,留下一份 10/20 的檔案,
                # 再跑一次就被跳過,於是永遠湊不出一輪完整的資料。
                if _is_complete_run(out_path):
                    logger.info("跳過 %s(已完整)", out_path.name)
                    continue
                if not _run_with_retries(
                    args.category, label, provider_name, model_id, out_path, args.max_attempts
                ):
                    logger.warning("%s 第 %d 輪連續失敗,不再繼續這個模型", label, index)
                    break

    runs = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(out_dir.glob("*_run*.json"))]
    if not runs:
        logger.error("一個結果檔都沒有")
        return 1
    report = REPORTS_DIR / f"{args.category}_variance.md"
    report.write_text(build_report(args.category, runs), encoding="utf-8")
    logger.info("已輸出 %s(%d 份執行結果)", report, len(runs))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
