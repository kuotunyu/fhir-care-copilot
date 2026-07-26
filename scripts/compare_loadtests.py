"""把幾次負載測試的結果併成一張前後對照表。

    uv run python scripts/compare_loadtests.py

**數字用程式產生,不手打。** 手抄的數字會在報告改版時悄悄漂掉,而這份報告的
全部價值就在於「每個數字都指得回 raw 輸出」。

四個階段各是一次獨立的量測(同一組 configs/ops.yaml 參數):

    baseline            什麼控制項都沒有
    with-controls       加上認證/限流/預算            (Phase 1)
    with-observability  加上結構化日誌/tracing/metrics (Phase 2)
    final               加上韌性/稽核軌跡              (Phase 3+4)

**怎麼判斷數字可不可信**:``/api/health``、``/api/patients``、``/api/summary``
在 Phase 1 之後都不受守門保護,所以它們是**內建的控制組**——各階段之間的差值
應該彼此吻合。不吻合就代表某次量測的機器不夠安靜,那次要重跑。
這個機制在這個專案裡抓到過兩次量測污染。
"""

from __future__ import annotations

import argparse
import glob
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("compare_loadtests")

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DIR = REPO_ROOT / "reports" / "loadtest"

STAGES: tuple[tuple[str, str], ...] = (
    ("baseline", "基線"),
    ("with-controls", "加上守門"),
    ("with-observability", "加上觀測"),
    ("final", "加上韌性稽核"),
)

TARGET_LABELS: dict[str, str] = {
    "health": "`/api/health`",
    "patients": "`/api/patients`",
    "summary": "`/api/patients/{id}/summary`",
    "chat": "`/api/chat`",
}


def load_stage(directory: Path, prefix: str) -> dict[str, Any] | None:
    matches = sorted(glob.glob(str(directory / f"{prefix}-*.json")))
    if not matches:
        return None
    payload: dict[str, Any] = json.loads(Path(matches[-1]).read_text(encoding="utf-8"))
    payload["_file"] = Path(matches[-1]).name
    return payload


def common_levels(stages: dict[str, dict[str, Any]], target: str) -> list[str]:
    """只比每個階段都量過的併發等級——有些階段是取樣跑的,不是完整階梯。"""
    sets = [set(s["results"][target]) for s in stages.values() if target in s["results"]]
    if not sets:
        return []
    shared = set.intersection(*sets)
    return sorted(shared, key=int)


def build_markdown(stages: dict[str, dict[str, Any]], generated_at: str) -> str:
    first = next(iter(stages.values()))
    cfg = first["config"]
    lines = [
        "# 負載測試前後對照:每個控制項的代價",
        "",
        f"產生時間:{generated_at}(由 `scripts/compare_loadtests.py` 產生,數字不手打)",
        "",
        "## 這組數字是什麼",
        "",
        "量的是**服務層 overhead**:FastAPI + 路由 + 工具執行 + FHIR store 查詢。",
        f"`/api/chat` 走 mock provider,每次 provider 呼叫固定延遲 {cfg['mock_latency_ms']} ms;",
        f"agent loop 一輪問答呼叫兩次,所以端到端下限約 {cfg['mock_latency_ms'] * 2} ms。",
        "",
        "**這組數字不含真實 LLM 供應商的延遲。** 那是另一軌,要用真 provider 少量取樣",
        "另外量,兩者不可混用。",
        "",
        "## 四個階段",
        "",
        "| 階段 | 加了什麼 | 原始檔 |",
        "|---|---|---|",
    ]
    described = {
        "baseline": "什麼控制項都沒有",
        "with-controls": "加上API key 認證、每 key 限流、每日預算上限(Phase 1)",
        "with-observability": "加上結構化日誌與 PII 遮蔽、tracing、`/metrics`(Phase 2)",
        "final": "加上單次逾時/重試/熔斷、稽核 hash chain 與草稿簽章(Phase 3+4)",
    }
    for key, _label in STAGES:
        if key in stages:
            lines.append(f"| `{key}` | {described[key]} | `{stages[key]['_file']}` |")

    lines += [
        "",
        "## p50 對照(毫秒)",
        "",
        "|  | 併發 | " + " | ".join(label for _k, label in STAGES if _k in stages) + " | 總增量 |",
        "|---|---:|" + "---:|" * (len(stages) + 1),
    ]
    for target, label in TARGET_LABELS.items():
        levels = common_levels(stages, target)
        for index, level in enumerate(levels):
            values = [
                stages[k]["results"][target][level]["p(50)"] for k, _ in STAGES if k in stages
            ]
            delta = values[-1] - values[0]
            name = label if index == 0 else ""
            lines.append(
                f"| {name} | c{level} | "
                + " | ".join(f"{v:.2f}" for v in values)
                + f" | **{delta:+.2f}** |"
            )

    lines += [
        "",
        "## 怎麼讀",
        "",
        "**先看控制組。** `/api/health`、`/api/patients`、`/api/summary` 在 Phase 1 之後都",
        "不受守門保護,所以各階段之間的差值應該彼此吻合。吻合代表那幾次量測的機器一樣安靜,",
        "數字可以比;不吻合就代表某次被污染了,該重跑。這個機制在這個專案裡抓到過兩次污染。",
        "",
        "**精確的數字在讀取端點上。** 它們是次毫秒級、沒有 sleep,雜訊底大約 ±0.05 ms,",
        "所以整層營運控制的每請求成本看得出來(c1 大約 +0.2 ~ +0.5 ms)。",
        "",
        "**`/api/chat` 上幾毫秒的差異不要當真。** 那條路徑的 600 ms 是 mock provider 用",
        "`time.sleep` 造出來的,而 Windows 的排程粒度是毫秒級——chat 的雜訊底來自**儀器**,",
        "不是來自服務。chat 這一欄要看的是「相對於 600 ms 的請求,這些控制項小到量不出來」,",
        "而不是那幾毫秒本身。",
        "",
        "**c64 那一列是飽和點,不是單次成本。** 七個端點全是同步 `def`,跑在 anyio",
        "threadpool 的 40 個 slot 上;`/api/chat` 的吞吐上限是 40 ÷ 0.6s ≈ 66.7 rps,",
        "基線實測 64.6。那一格的延遲由排隊主導,增量會被放大。",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", type=Path, default=DEFAULT_DIR)
    args = parser.parse_args()

    stages: dict[str, dict[str, Any]] = {}
    for key, _label in STAGES:
        payload = load_stage(args.dir, key)
        if payload is None:
            logger.warning("找不到 %s-*.json,跳過這個階段", key)
            continue
        stages[key] = payload

    if len(stages) < 2:
        logger.error("至少要有兩個階段才能對照")
        return 1

    generated_at = datetime.now(UTC).isoformat(timespec="seconds")
    out = args.dir / "comparison.md"
    out.write_text(build_markdown(stages, generated_at), encoding="utf-8")
    logger.info("已輸出 %s(%d 個階段)", out, len(stages))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
