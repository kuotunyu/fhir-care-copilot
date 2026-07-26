"""用目前的判準,重算已保存 eval 結果的注入抵抗指標——**不重打任何 API**。

    uv run python scripts/rescore_eval.py reports/eval_gemini.json

## 為什麼需要這個

這個專案的自動判準已經被真實資料打臉兩次,兩次方向相反:

- **假陽性**(M6,gpt-5.4-mini):模型正確拒絕開處方,但拒絕句本身包含
  「開立」「處方」,被判成服從了
- **假陰性**(2026-07-26,gemini-3.5-flash-lite):模型把整段 system prompt
  複述出來,只把「你是」改成「我是」,違禁字串一個字之差就沒命中,被判成抵抗住了

判準會再錯第三次。錯的時候,**已經跑過的回答本身沒有問題**——花錢買到的是那些
逐字稿,不是當時算出來的布林值。重打一次 API 不只浪費錢,還會拿到不同的回答,
把當初那個具體的失敗案例洗掉。所以:判準改了就重算,不重跑。

## 只重算注入這一項

存下來的 JSON 沒有 ``evidence``(citation validity 需要它),所以其他指標無法
離線重算。注入判準只看回答文字,可以。要重算其他指標就得重跑。

判準邏輯**直接呼叫 ``evaluate_case``**,不在這裡複製一份——複製出來的第二份
判準遲早會跟本尊分岔,那比沒有重算工具更糟。
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
logger = logging.getLogger("rescore_eval")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="要重算的 eval JSON")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=REPO_ROOT / "data" / "processed" / "subset_100",
        help="產生題目用的資料目錄(要跟當初跑 eval 時一致)",
    )
    parser.add_argument("--dry-run", action="store_true", help="只印出差異,不寫回檔案")
    args = parser.parse_args()

    sys.path.insert(0, str(REPO_ROOT / "src"))
    from fhir_copilot.agent.response import AgentResponse
    from fhir_copilot.eval.cases import generate_cases
    from fhir_copilot.eval.metrics import evaluate_case
    from fhir_copilot.store import LocalBundleFHIRStore

    payload: dict[str, Any] = json.loads(args.path.read_text(encoding="utf-8"))
    store = LocalBundleFHIRStore(args.data_dir)

    # 題目是決定性產生的,所以可以用 case_id 對回原始 case(拿 forbidden_substrings)。
    # 涵蓋小樣本與 full_eval 兩種設定,取聯集就不必猜當初用的是哪一組參數。
    by_id: dict[str, Any] = {}
    for per_category in (6, 45):
        n = max(2, per_category // 2)
        for generated in generate_cases(
            store,
            per_category=per_category,
            unanswerable_count=n if per_category == 6 else 20,
            injection_count=n if per_category == 6 else 20,
        ):
            by_id.setdefault(generated.case_id, generated)

    changed = 0
    for row in payload["results"]:
        if row["category"] != "injection":
            continue
        case: Any = by_id.get(row["case_id"])
        if case is None:
            logger.warning("找不到 %s 的原始 case,跳過", row["case_id"])
            continue
        # evidence 沒存下來,但注入判準不看它;其他欄位照原樣填回去
        response = AgentResponse(
            answer=row["answer"],
            evidence=[],
            limitations=None,
            refused=row["refused"],
            model=payload["model_id"],
            latency_ms=row["latency_ms"],
            input_tokens=0,
            output_tokens=0,
            estimated_cost_usd=row["estimated_cost_usd"],
        )
        new_value = evaluate_case(store, case, response).injection_resisted
        if new_value != row["injection_resisted"]:
            logger.info(
                "%s:injection_resisted %s -> %s",
                row["case_id"],
                row["injection_resisted"],
                new_value,
            )
            row["injection_resisted"] = new_value
            changed += 1

    injection = [
        r["injection_resisted"] for r in payload["results"] if r["category"] == "injection"
    ]
    old_rate = payload["metrics"]["injection_resistance_rate"]
    new_rate = (sum(injection) / len(injection)) if injection else None
    payload["metrics"]["injection_resistance_rate"] = new_rate
    payload["rescored_note"] = (
        "injection_resistance_rate 由 scripts/rescore_eval.py 用目前的判準重算,"
        "回答本身是原始 eval 跑出來的,沒有重打 API"
    )

    logger.info(
        "%d 題判定改變;injection resistance %s -> %s",
        changed,
        f"{old_rate:.1%}" if old_rate is not None else "None",
        f"{new_rate:.1%}" if new_rate is not None else "None",
    )

    if args.dry_run:
        logger.info("--dry-run:沒有寫回檔案")
        return 0

    args.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    logger.info("已寫回 %s", args.path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
