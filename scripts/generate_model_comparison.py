"""從 scripts/run_eval.py 產出的 committed eval JSON 組出模型比較報告。

歷史 raw artifact 不改寫;舊 schema 無法支持的新指標顯示為 n/a,而不是猜值。

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
        value = run["metrics"].get(key)
        cells.append(_fmt_rate(value) if is_rate else ("n/a" if value is None else f"{value:.0f}"))
    return f"| {label} | " + " | ".join(cells) + " |"


def build_markdown(runs: list[dict]) -> str:  # type: ignore[type-arg]
    if not runs:
        raise ValueError("至少需要一份 eval run")
    header = "| 指標 | " + " | ".join(f"{r['provider']}({r['model_id']})" for r in runs) + " |"
    sep = "|---|" + "---|" * len(runs)
    all_full = all(r["full_eval"] for r in runs)
    model_count = {1: "一個模型", 2: "兩個模型", 3: "三個模型"}.get(
        len(runs), f"{len(runs)} 個模型"
    )
    has_legacy_schema = any("reference_integrity_rate" not in run["metrics"] for run in runs)

    lines = [
        "# 模型比較報告",
        "",
        f"由 `scripts/generate_model_comparison.py` 從既有 committed raw results 重新產生"
        f"(原始執行時間:{runs[0]['generated_at']})。原始 JSON 未被改寫;表內數字只使用"
        "artifact 已保存的欄位,無法重算者標為 `n/a`。",
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
        _row("**Reference integrity rate**", "reference_integrity_rate", runs),
        _row("**Evidence coverage rate**", "evidence_coverage_rate", runs),
        _row("Answer-without-evidence rate", "answer_without_evidence_rate", runs),
        _row("Legacy citation validity rate (deprecated)", "citation_validity_rate", runs),
        _row(
            "Legacy answer-without-evidence rate (deprecated field name)",
            "unsupported_claim_rate",
            runs,
        ),
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
        "- **Reference integrity** 只驗證已回傳 evidence 的 `(resourceType, id)` 是否存在於"
        "本次實際使用的 Synthea 合成資料 store;沒有 evidence 時排除 denominator。它不代表"
        "自然語言回答的逐句 claim grounding。",
        "- **Evidence coverage** 量預期需要 evidence 的 answerable cases 是否實際帶回"
        " evidence;answer-without-evidence 只量可觀察到的空 evidence 回答,不是完整"
        " unsupported-claim detection。",
        "- **Field exact match 偏低不等於答錯**:模型常把英文藥名/診斷翻譯成中文或改寫"
        "格式(如把 `Prediabetes` 寫成 `糖尿病前期 (Prediabetes)`)——那正是本專案"
        "「正體中文 UI」想要的行為,但比對用的是嚴格子字串,接受不了改寫。這個指標"
        "**低估**該次 strict-string 分數。具體有哪些改寫,"
        "看下方逐字稿自行判斷。",
        "- **Injection resistance 是啟發式判準,兩個方向都出錯過**,所以請直接看下方逐字稿:",
        "  - **假陽性**(M6,gpt-5.4-mini):模型正確拒絕開處方,但拒絕句本身包含"
        "「開立」「處方」,被判成服從了。已加入否定語氣偵測",
        "  - **假陰性**(2026-07-26,gemini-3.5-flash-lite):模型把整段 system prompt"
        " 複述出來,只把「你是」改成「我是」,違禁字串一個字之差就沒命中,被判成抵抗住了。"
        "已改為直接比對與真實 SYSTEM_PROMPT 的逐字重疊度",
        "  **這份報告只陳述自動判準算出來的數字。** 人工核閱的結論寫在 `docs/PROGRESS.md`"
        " 與 `MODEL_CARD.md`,標明日期與對應的那一次執行——不在這裡宣稱「已經有人看過了」,"
        "因為這段文字是每次重新產生報告時自動印出來的,它不知道有沒有人真的看過。",
        (
            f"- 本報告比較{model_count}的完整題庫結果;220 題是每個模型的一次執行,"
            "不是多次重跑或臨床驗證。"
            if all_full
            else "- 這份報告含取樣執行;適用範圍以表內完成題數與模式為準。"
        ),
        (
            "- 這些 artifact 使用 legacy metric schema,沒有保存 evidence arrays/count,"
            "因此不能依新 denominator 重算 reference integrity 或 evidence coverage;新欄位"
            "標為 `n/a`,舊百分比只作 deprecated provenance 顯示。"
            if has_legacy_schema
            else "- 本報告使用新 metric schema;legacy 欄位只為 machine-readable 相容性保留。"
        ),
        "- 已知限制與指標定義的完整說明見 `docs/EVAL.md`,不在這裡重複。",
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


def hook_clean(text: str) -> str:
    """去掉每行的行尾空白,並確保結尾恰好一個換行。

    這份報告嵌了模型的**原始回答**,而模型很常在句末留兩個空格(markdown 的換行語法)。
    那會讓 pre-commit 的 trailing-whitespace hook 改檔案並中止 commit——
    **產生器產出的東西不該讓 hook 有事做。**

    同一類問題在這個專案踩過三次(loadtest JSON、injection_ab.md、e2e sample JSON),
    所以 tests/test_report_artifacts.py 直接對 reports/ 底下每個檔案斷言。
    """
    return "\n".join(line.rstrip() for line in text.splitlines()) + "\n"


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
    out_path.write_text(hook_clean(markdown), encoding="utf-8")
    print(f"寫入 {out_path}")


if __name__ == "__main__":
    main()
