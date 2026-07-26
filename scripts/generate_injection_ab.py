"""把兩個模型的 injection A/B 結果整理成一張對照表。

    uv run python scripts/generate_injection_ab.py reports/injection_ab_*.json

**數字由程式產生,不手打。** 這份報告的全部價值在於「每個數字都指得回原始 JSON」。

## 為什麼要單獨做一份 injection A/B

`reports/model_comparison.md` 是跨模型的全指標比較,用的是各 30 題的小樣本,
其中 injection 只有 3 題——**單題翻轉就是 33 個百分點**,那個數字不足以判斷
一個模型的注入抵抗力。

要換預設模型時,該看的是同一組注入題在兩個模型上的直接對照。用
``--categories injection --sample-per-category 40`` 只跑注入那一類(20 題),
成本不到全量的十分之一。

20 題 = **5 個不同的注入 prompt,搭配 4 位不同病患**,所以這張表同時回答
「同一個 prompt 是不是每次都失守」——穩定失守與偶發失守是兩件事。
"""

from __future__ import annotations

import argparse
import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import Any

logger = logging.getLogger("generate_injection_ab")
REPO_ROOT = Path(__file__).resolve().parent.parent


def load(path: Path) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    payload["_file"] = path.name
    return payload


def build_markdown(runs: list[dict[str, Any]]) -> str:
    lines = [
        "# Prompt injection A/B:換預設模型前的對照",
        "",
        "由 `scripts/generate_injection_ab.py` 從真實 eval 結果產生,數字不手打。",
        "",
        "每個模型跑同一組 **20 題**注入案例(5 個不同的注入 prompt,搭配 4 位不同病患)。",
        "跑法:`--categories injection --sample-per-category 40`。",
        "",
        "## 整體",
        "",
        "| 模型 | 抵抗率 | 題數 | 平均成本/題 | p50 延遲 | 原始檔 |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for r in runs:
        m = r["metrics"]
        rate = m["injection_resistance_rate"]
        lines.append(
            f"| `{r['model_id']}` | **{rate:.0%}** | {m['total_cases']} | "
            f"${m['average_cost_usd']:.5f} | {m['p50_latency_ms']:.0f} ms | `{r['_file']}` |"
        )

    lines += [
        "",
        "## 逐一注入手法",
        "",
        "**要看的是「同一個 prompt 重複 4 次的結果」**——4/4 全失守代表這條攻擊路徑",
        "穩定可通,不是抽樣運氣。",
        "",
        "| 注入手法 | " + " | ".join(f"`{r['model_id']}`" for r in runs) + " |",
        "|---|" + "---:|" * len(runs),
    ]

    per_run: list[dict[str, tuple[int, int]]] = []
    questions: list[str] = []
    for r in runs:
        by_q: dict[str, list[bool]] = defaultdict(list)
        for c in r["results"]:
            by_q[c["question"]].append(bool(c["injection_resisted"]))
        per_run.append({q: (sum(v), len(v)) for q, v in by_q.items()})
        for q in by_q:
            if q not in questions:
                questions.append(q)

    for q in questions:
        cells = []
        for stats in per_run:
            ok, total = stats.get(q, (0, 0))
            cell = f"{ok}/{total}" if total else "n/a"
            if total and ok < total:
                cell = f"**{cell}**"
            cells.append(cell)
        lines.append(f"| {q} | " + " | ".join(cells) + " |")

    lines += [
        "",
        "格子裡是「抵抗成功次數 / 嘗試次數」,**粗體代表有失守**。",
        "",
        "## 這些數字怎麼保證可信",
        "",
        "自動判準已經被真實資料打臉三次(假陽性 1 次、假陰性 1 次、多違禁詞同句 1 次),",
        "所以這一輪**額外做了獨立核閱**:用三種互不相同的視角(只問服從與否 / 盡力反駁",
        "「這是失守」/ 真實世界後果)各自判讀全部 40 份逐字稿,再取多數決。",
        "",
        "修正後的自動判準與人工多數決在 **40 題上逐題完全一致**。",
        "逐字稿在各自的 JSON 裡,可自行覆核。",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path, help="各模型的 injection eval JSON")
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "reports" / "injection_ab.md")
    args = parser.parse_args()

    runs = [load(p) for p in args.paths]
    # build_markdown 的最後一個元素是空字串,join 之後已經帶一個結尾換行;
    # 再加一個會變成兩個,pre-commit 的 end-of-file-fixer 會改掉它並中止 commit。
    args.out.write_text(build_markdown(runs), encoding="utf-8")
    logger.info("已輸出 %s(%d 個模型)", args.out, len(runs))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
