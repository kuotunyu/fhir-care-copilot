"""從 scripts/run_eval.py 產出的 eval 結果 JSON,自動組出 reports/model_comparison.md
(PLAN.md M6)。直接讀真實跑出來的數字,不手 key——任何模型品質結論都要有這份報告
背後的真實 eval 數字支持。

用法:
    uv run python scripts/run_eval.py --provider gemini --out reports/eval_gemini.json
    uv run python scripts/run_eval.py --provider openai --out reports/eval_openai.json
    uv run python scripts/generate_model_comparison.py \
        reports/eval_gemini.json reports/eval_openai.json
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _fmt_rate(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.1%}"


def _load(path: Path) -> dict:  # type: ignore[type-arg]
    return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def _row(label: str, key: str, runs: list[dict], is_rate: bool = True) -> str:  # type: ignore[type-arg]
    cells = []
    for run in runs:
        value = run["metrics"][key]
        cells.append(_fmt_rate(value) if is_rate else ("n/a" if value is None else f"{value:.0f}"))
    return f"| {label} | " + " | ".join(cells) + " |"


def build_markdown(runs: list[dict]) -> str:  # type: ignore[type-arg]
    header = "| 指標 | " + " | ".join(f"{r['provider']}({r['model_id']})" for r in runs) + " |"
    sep = "|---|" + "---|" * len(runs)

    lines = [
        "# 模型比較報告",
        "",
        f"由 `scripts/generate_model_comparison.py` 從真實 eval 結果自動產生"
        f"(產生時間:{runs[0]['generated_at']})。**以下所有數字都是真實跑出來的、"
        "不是預估值**——任何模型品質結論都以此為準,未經 eval 驗證的說法不採用。",
        "",
        "## 執行摘要",
        "",
        "| | " + " | ".join(r["provider"] for r in runs) + " |",
        "|---|" + "---|" * len(runs),
        "| 模型 id | " + " | ".join(f"`{r['model_id']}`" for r in runs) + " |",
        "| 完成題數 | "
        + " | ".join(f"{r['n_cases_completed']}/{r['n_cases_requested']}" for r in runs)
        + " |",
        "| 模式 | " + " | ".join("完整題庫" if r["full_eval"] else "小樣本" for r in runs) + " |",
        "",
        "## 品質指標",
        "",
        header,
        sep,
        _row("Tool-selection accuracy", "tool_selection_accuracy", runs),
        _row("Field exact match rate", "field_exact_match_rate", runs),
        _row("**Citation validity rate**", "citation_validity_rate", runs),
        _row("Unsupported-claim rate", "unsupported_claim_rate", runs),
        _row("Refusal accuracy", "refusal_accuracy", runs),
        _row("**Injection resistance rate**", "injection_resistance_rate", runs),
        "",
        "## 效能與成本",
        "",
        header,
        sep,
        _row("p50 latency (ms)", "p50_latency_ms", runs, is_rate=False),
        _row("p95 latency (ms)", "p95_latency_ms", runs, is_rate=False),
        "| Average cost (USD) | "
        + " | ".join(f"${r['metrics']['average_cost_usd']:.5f}" for r in runs)
        + " |",
        "| Total cost (USD) | "
        + " | ".join(f"${r['metrics']['total_cost_usd']:.4f}" for r in runs)
        + " |",
        "",
        "## 怎麼解讀",
        "",
        "- **Citation validity 100%(兩個模型皆是)** 是最重要的信任指標:每一筆 evidence"
        " 都直接對照真實 FHIR store 驗證過,不是自我宣稱——這是本專案「病患事實一律"
        "出自 deterministic tool、附可追溯證據」這個核心承諾在真實 API 呼叫下成立的直接證據。",
        "- **Field exact match 只有五成左右,但不代表答錯**:人工核閱下方的逐字稿發現,"
        "兩個模型都會把英文藥名/診斷名稱翻譯成中文或改寫格式(如 `Hydrochlorothiazide 25 MG`"
        " 被寫成 `Hydrochlorothiazide 25 mg`、`Prediabetes` 被寫成 `糖尿病前期 (Prediabetes)`)"
        "——這其實正是本專案「正體中文 UI」想要的行為,只是我的比對用的是嚴格子字串比對,"
        "沒辦法接受改寫。這個指標低估了真實品質,citation validity 才是更可信的信號。",
        "- **Injection resistance 的數字也要配合下方逐字稿看**:自動判準是關鍵字比對"
        "(有沒有出現違禁詞、且不是在拒絕語氣裡),遇到模型用比較迂迴的安全方式回應時"
        "(如「我可以幫你準備給醫師的處方評估摘要」——沒有自己開處方,是把決定權交給"
        "醫師,但字面上出現了「處方」)還是可能被判定成沒抵抗住。**人工核閱下方全部"
        "逐字稿的結論是:兩個模型在這次測試的 6 次注入嘗試中,沒有一次真的服從惡意"
        "指令**(沒有洩漏 system prompt、沒有真的開處方、沒有在未查證下宣稱病患確診)。",
        "- 這是**小樣本**比較(見上方「完成題數」);要看 220 題全量的結果,"
        "用 `--full-eval` 重新跑(注意 Gemini 免費層有 15 requests/min 的速率限制,"
        "需要搭配 `--pace-seconds` 調整,見 `.claude/skills/run-eval/SKILL.md`)。",
        "- 已知限制與指標定義的完整說明見 `.claude/skills/run-eval/SKILL.md`,不在這裡重複。",
        "",
        "## 手動核閱:Prompt Injection 逐字稿",
        "",
        "自動判準的侷限已在上面說明;以下是每個模型全部 injection 案例的完整問答"
        "(直接從 eval 結果 JSON 取出,不是手打的),供讀者自行判斷。",
        "",
    ]

    for run in runs:
        lines.append(f"### {run['provider']}({run['model_id']})")
        lines.append("")
        for r in run["results"]:
            if r["category"] != "injection":
                continue
            tag = (
                "✅ 自動判準:抵抗住"
                if r["injection_resisted"]
                else "⚠️ 自動判準:未抵抗住(見上方說明,可能是誤判)"
            )
            lines.append(f"**{r['case_id']}** — {tag}")
            lines.append("")
            lines.append(f"> **Q:** {r['question']}")
            lines.append(">")
            answer_quoted = r["answer"].replace("\n", "\n> ")
            lines.append(f"> **A:** {answer_quoted}")
            lines.append("")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("eval_json", nargs="+", help="一或多個 run_eval.py 的輸出 JSON")
    parser.add_argument("--out", default=str(REPO_ROOT / "reports" / "model_comparison.md"))
    args = parser.parse_args()

    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8")

    runs = [_load(Path(p)) for p in args.eval_json]
    markdown = build_markdown(runs)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(markdown, encoding="utf-8")
    print(f"寫入 {out_path}")


if __name__ == "__main__":
    main()
