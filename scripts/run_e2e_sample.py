"""端到端取樣:打真的 LLM 供應商,量**含供應商延遲**的完整 HTTP 往返。

    uv run python scripts/run_e2e_sample.py --provider gemini --samples 30

## 這是第二軌,不是負載測試

`run_loadtest.py` 量的是**服務層 overhead**:mock provider 固定延遲、k6 打滿併發,
目的是問「這些營運控制每個請求多花幾毫秒」。那一軌**不含真實供應商延遲**。

這一支量的是另一件事:一個真實使用者按下送出之後,到底要等多久、花多少錢。

**所以它刻意不是負載測試。** 真的 provider 有速率限制(Gemini 免費層 15 req/min),
把併發拉高只會量到一整片 429——那不是延遲,那是限流在工作。這裡走**單一連線、
固定間隔、少量取樣**,量的是延遲的真實量級,不是吞吐上限。

兩軌的數字**不可混用**,報表與 README 都要標清楚是哪一軌。

## 量到的三個數字為什麼要分開看

- ``http_ms``:從送出 HTTP 請求到收到回應(使用者真正感受到的)
- ``agent_ms``:API 自己回報的 agent loop 耗時(``latency_ms`` 欄位)
- 兩者相減:FastAPI + 路由 + 營運層在**真實情境**下的實際佔比

第三個是這支腳本存在的主要理由——服務層 overhead 在 mock 上量到是零點幾毫秒,
但那是相對於一個假的 600 ms。放進真實的一兩秒裡,它到底佔多少比例,要這樣才看得出來。
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT_DIR = REPO_ROOT / "reports"
logger = logging.getLogger("run_e2e_sample")

QUESTIONS = (
    "這位個案目前生效中的診斷有哪些?",
    "他現在有在吃什麼藥?",
    "最近的生命徵象量測結果如何?",
    "目前的照護計畫有哪些項目?",
)


def load_env_file(path: Path) -> None:
    """把 .env 讀進環境變數。

    專案的程式碼**刻意不讀 .env**(secret 只從環境變數來),但這支腳本是給人
    互動式跑的,每次手動 export 一長串太容易忘。已經在環境裡的值優先。
    """
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def http_json(url: str, payload: dict[str, Any] | None = None, timeout: float = 120.0) -> Any:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"} if data else {},
        method="POST" if data else "GET",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def wait_for_health(base_url: str, attempts: int = 60) -> dict[str, Any]:
    for _ in range(attempts):
        try:
            payload: dict[str, Any] = http_json(f"{base_url}/api/health", timeout=5.0)
            return payload
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            time.sleep(0.5)
    raise SystemExit("後端沒有在時限內起來")


def start_backend(provider: str, port: int) -> subprocess.Popen[bytes]:
    env = dict(os.environ)
    env["FHIR_COPILOT_PROVIDER"] = provider
    # 認證關閉、限流與預算放寬:量的是延遲,不是守門拒絕流量的行為。
    # (守門程式碼本身仍然每個請求都會走過,和 run_loadtest.py 一致。)
    env.pop("FHIR_COPILOT_API_KEYS", None)
    env.pop("FHIR_COPILOT_REQUIRE_AUTH", None)
    command = [
        sys.executable,
        "-m",
        "uvicorn",
        "fhir_copilot.api.app:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--log-level",
        "warning",
    ]
    logger.info("啟動後端(provider=%s, port=%d)", provider, port)
    return subprocess.Popen(command, env=env, cwd=REPO_ROOT)


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = (len(ordered) - 1) * pct
    lo, hi = int(k), min(int(k) + 1, len(ordered) - 1)
    if lo == hi:
        return ordered[lo]
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def _retry_section(payload: dict[str, Any]) -> list[str]:
    """拒答與長尾要單獨講清楚,不能混進「供應商延遲」裡。

    真實跑的時候撞到供應商速率限制,韌性層會重試——**那些秒數是重試的退避,
    不是供應商的延遲**。混在一起報等於把自己的重試算成上游很慢。
    """
    s = payload["summary"]
    refused = [x for x in payload["samples"] if x["refused"]]
    slow = [x for x in payload["samples"] if x["http_ms"] > 5000]
    if not refused and not slow:
        return [
            "## 重試與拒答",
            "",
            "這次取樣沒有任何請求超過 5 秒,也沒有任何結構化拒答——",
            "沒有撞到供應商的速率限制,所以上面的延遲分布是乾淨的供應商延遲。",
            "",
        ]
    lines = [
        "## 重試與拒答:上面的長尾是誰造成的",
        "",
        f"{len(slow)}/{s['samples']} 筆超過 5 秒,{len(refused)}/{s['samples']} 筆回結構化拒答。",
        "",
        "**那些秒數是韌性層的重試退避,不是供應商的延遲。** 打真的免費層很容易撞到",
        "速率限制,單次呼叫失敗後會指數退避重試;重試用完才走 Phase 3 的結構化拒答",
        "(HTTP 200 + `refused`,不是 500)。",
        "",
        "| # | 端到端 | agent | input tokens | 拒答 |",
        "|---:|---:|---:|---:|---|",
    ]
    for x in sorted(slow, key=lambda r: -r["http_ms"]):
        lines.append(
            f"| {x['index']} | {x['http_ms']:.0f} ms | {x['agent_ms']} ms | "
            f"{x['input_tokens']} | {'**是**' if x['refused'] else '否'} |"
        )
    lines += [
        "",
        "`input tokens = 0` 代表那次呼叫**完全沒有回來過**(連 usage 都沒拿到),",
        "重試全部用完。這是韌性層在真實條件下運作的直接證據——不是故障注入測試,",
        "是實際打上游時自己撞到的。",
        "",
        f"**所以上表的 p95/p99 要這樣讀**:p50({s['http_p50']:.0f} ms)是供應商的真實延遲,",
        "p95 以上主要由重試退避主導。要看乾淨的延遲分布,用更保守的 `--pace-seconds` 重跑。",
        "",
    ]
    return lines


def build_markdown(payload: dict[str, Any]) -> str:
    s = payload["summary"]
    lines = [
        "# 端到端取樣:含真實供應商延遲",
        "",
        f"產生時間:{payload['generated_at']}(由 `scripts/run_e2e_sample.py` 產生,數字不手打)",
        "",
        "## 這一軌量什麼",
        "",
        "一個真實使用者按下送出之後要等多久、花多少錢。**含真實 LLM 供應商的延遲。**",
        "",
        "跟 `reports/loadtest/` 那一軌**不可混用**:那邊用 mock provider 固定延遲 + k6 併發,",
        "量的是營運控制的每請求成本;這邊單一連線、固定間隔、少量取樣,量的是真實延遲量級。",
        "",
        "**刻意不是負載測試**:真的 provider 有速率限制,併發拉高只會量到一整片 429。",
        "",
        "## 設定",
        "",
        "| 項目 | 值 |",
        "|---|---|",
        f"| provider | `{payload['provider']}` |",
        f"| model_id | `{payload['model_id']}` |",
        f"| 取樣數 | {s['samples']} |",
        f"| 每次間隔 | {payload['pace_seconds']} 秒 |",
        "| 併發 | 1(單一連線循序送出) |",
        f"| 病患資料 | {payload['patient_count']} 位 |",
        "",
        "## 結果",
        "",
        "| 指標 | p50 | p95 | p99 | 最大 |",
        "|---|---:|---:|---:|---:|",
        f"| **端到端 HTTP** | {s['http_p50']:.0f} ms | {s['http_p95']:.0f} ms | "
        f"{s['http_p99']:.0f} ms | {s['http_max']:.0f} ms |",
        f"| agent loop(API 自報) | {s['agent_p50']:.0f} ms | {s['agent_p95']:.0f} ms | "
        f"{s['agent_p99']:.0f} ms | {s['agent_max']:.0f} ms |",
        "",
        "| 項目 | 值 |",
        "|---|---:|",
        f"| 平均成本/題 | ${s['avg_cost_usd']:.5f} |",
        f"| 總花費 | ${s['total_cost_usd']:.4f} |",
        f"| 平均 input / output tokens | {s['avg_input_tokens']:.0f} / "
        f"{s['avg_output_tokens']:.0f} |",
        f"| 拒答數 | {s['refused']} / {s['samples']} |",
        f"| 冷啟動(第一次,已排除) | {payload['cold_start_ms']:.0f} ms |",
        "",
        "## 服務層在真實情境下佔多少",
        "",
        f"**{s['overhead_p50']:.1f} ms**(逐筆差值的中位數;範圍 "
        f"{s['overhead_min']:.1f} ~ {s['overhead_max']:.1f} ms),",
        f"約佔端到端的 {s['overhead_p50'] / s['http_p50'] * 100:.2f}%。",
        "",
        "**這裡算的是每一筆的 `http_ms - agent_ms` 再取中位數,不是「兩個 p50 相減」。**",
        "百分位不能相減——p50 的差不是差的 p50,那樣算會把兩條分布各自的長尾混進來。",
        "這個差值是 FastAPI + 路由 + 整層營運控制(認證/限流/預算/日誌/tracing/",
        "熔斷/稽核)在真實請求裡的實際佔比。mock 那一軌量到的是零點幾毫秒,",
        "但那是相對於一個人造的 600 ms;放進真實的一兩秒裡才看得出比例。",
        "",
        *_retry_section(payload),
        "## 已知限制",
        "",
        f"- **樣本只有 {s['samples']} 次**,不是穩定性測試。p99 在這個樣本數下是粗估",
        "- 供應商延遲會隨時段、區域、帳號層級變動,這是**測試當下**的量級,不是保證",
        "- 併發 1,所以看不到排隊行為;吞吐上限那件事在 `reports/loadtest/` 那一軌",
        "- 問題只有四種輪流,不涵蓋全部題型(那是 eval 的工作,見 `reports/model_comparison.md`)",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", default="gemini", choices=["gemini", "openai", "mock"])
    parser.add_argument("--samples", type=int, default=30)
    parser.add_argument(
        "--pace-seconds",
        type=float,
        default=10.0,
        help="每次請求之間的間隔。Gemini 免費層 15 req/min,一次問答含兩次呼叫,10 秒是保守值",
    )
    parser.add_argument("--port", type=int, default=8123)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args()

    load_env_file(REPO_ROOT / ".env")
    base_url = f"http://127.0.0.1:{args.port}"
    args.out_dir.mkdir(parents=True, exist_ok=True)

    backend = start_backend(args.provider, args.port)
    try:
        health = wait_for_health(base_url)
        if health.get("demo_mode") and args.provider != "mock":
            raise SystemExit(
                f"後端退回 demo mode(provider={health.get('provider')})——"
                "金鑰沒讀到。這一軌要打真的供應商才有意義,中止。"
            )
        model_id = health["model_id"]
        patients = http_json(f"{base_url}/api/patients")
        patient_ids = [p["patient_id"] for p in patients["patients"]]
        logger.info(
            "provider=%s model=%s 病患 %d 位", health["provider"], model_id, len(patient_ids)
        )

        # 冷啟動單獨量一次再丟掉:第一次會付掉 store 索引與連線建立的成本,
        # 混進樣本裡會讓 p95/p99 變成在講冷啟動,不是在講供應商延遲。
        cold_start = time.perf_counter()
        http_json(
            f"{base_url}/api/chat",
            {"patient_id": patient_ids[0], "question": QUESTIONS[0]},
        )
        cold_start_ms = (time.perf_counter() - cold_start) * 1000
        logger.info("冷啟動 %.0f ms(不計入樣本)", cold_start_ms)

        samples: list[dict[str, Any]] = []
        for i in range(args.samples):
            time.sleep(args.pace_seconds)
            patient_id = patient_ids[i % len(patient_ids)]
            question = QUESTIONS[i % len(QUESTIONS)]
            started = time.perf_counter()
            body = http_json(
                f"{base_url}/api/chat", {"patient_id": patient_id, "question": question}
            )
            http_ms = (time.perf_counter() - started) * 1000
            samples.append(
                {
                    "index": i,
                    "patient_id": patient_id,
                    "question": question,
                    "http_ms": http_ms,
                    "agent_ms": body["latency_ms"],
                    "input_tokens": body["input_tokens"],
                    "output_tokens": body["output_tokens"],
                    "estimated_cost_usd": body["estimated_cost_usd"],
                    "refused": body["refused"],
                    "evidence_count": len(body["evidence"]),
                }
            )
            logger.info(
                "[%d/%d] http %.0f ms | agent %d ms | $%.5f",
                i + 1,
                args.samples,
                http_ms,
                body["latency_ms"],
                body["estimated_cost_usd"],
            )

        http_ms_values = [s["http_ms"] for s in samples]
        agent_ms_values = [float(s["agent_ms"]) for s in samples]
        costs = [s["estimated_cost_usd"] for s in samples]
        # 逐筆相減再取百分位。**不能拿兩條分布的 p50 相減**——那不是同一件事。
        overheads = [s["http_ms"] - float(s["agent_ms"]) for s in samples]
        payload: dict[str, Any] = {
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "provider": args.provider,
            "model_id": model_id,
            "pace_seconds": args.pace_seconds,
            "patient_count": len(patient_ids),
            "cold_start_ms": cold_start_ms,
            "summary": {
                "samples": len(samples),
                "http_p50": percentile(http_ms_values, 0.50),
                "http_p95": percentile(http_ms_values, 0.95),
                "http_p99": percentile(http_ms_values, 0.99),
                "http_max": max(http_ms_values),
                "agent_p50": percentile(agent_ms_values, 0.50),
                "agent_p95": percentile(agent_ms_values, 0.95),
                "agent_p99": percentile(agent_ms_values, 0.99),
                "agent_max": max(agent_ms_values),
                "avg_cost_usd": statistics.fmean(costs),
                "total_cost_usd": sum(costs),
                "overhead_p50": percentile(overheads, 0.50),
                "overhead_p95": percentile(overheads, 0.95),
                "overhead_min": min(overheads),
                "overhead_max": max(overheads),
                "avg_input_tokens": statistics.fmean(s["input_tokens"] for s in samples),
                "avg_output_tokens": statistics.fmean(s["output_tokens"] for s in samples),
                "refused": sum(1 for s in samples if s["refused"]),
            },
            "samples": samples,
        }

        stem = f"e2e_sample_{args.provider}"
        json_path = args.out_dir / f"{stem}.json"
        md_path = args.out_dir / f"{stem}.md"
        # 結尾要有**恰好一個**換行:pre-commit 的 end-of-file-fixer 會改掉不合規的檔案
        # 並中止 commit。這個坑在這個專案踩過三次了(loadtest JSON、injection_ab.md、
        # 這裡),所以 tests/test_report_artifacts.py 有測試守著。
        json_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        md_path.write_text(build_markdown(payload), encoding="utf-8")
        logger.info("已輸出 %s 與 %s", json_path, md_path)
        logger.info(
            "端到端 p50 %.0f ms / agent p50 %.0f ms / 服務層 %.1f ms / 總花費 $%.4f",
            payload["summary"]["http_p50"],
            payload["summary"]["agent_p50"],
            payload["summary"]["http_p50"] - payload["summary"]["agent_p50"],
            payload["summary"]["total_cost_usd"],
        )
        return 0
    finally:
        backend.terminate()
        try:
            backend.wait(timeout=15)
        except subprocess.TimeoutExpired:
            backend.kill()


if __name__ == "__main__":
    raise SystemExit(main())
