"""故障注入場景表:每種下游故障下,服務實際上會怎樣。

    uv run python scripts/run_fault_injection.py

**這個腳本要回答的核心問題**:Phase 3 宣稱「熔斷的目的是讓 provider 掛掉時
不要把 threadpool 佔滿,健康檢查仍然排得進去」。那句話原本只有單元測試支持,
而單元測試裡不存在「40 個 threadpool slot 被卡死的請求佔滿」這個情境。

作法:每個場景都一邊用固定併發打 ``/api/chat``,一邊以固定速率打 ``/api/health``,
兩者的延遲分開記錄。**如果健康檢查在 provider 掛掉時被拖慢,就代表那個宣稱是假的。**

場景一律用 mock provider 的注入旋鈕,不打真的 provider——故障注入要能重跑,
而且不該花錢。
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from fhir_copilot.ops.config import load_ops
from run_loadtest import (
    REPO_ROOT,
    find_k6,
    first_patient_id,
    start_backend,
    wait_for_health,
    write_permissive_ops,
)

logger = logging.getLogger("run_fault_injection")

K6_SCRIPT = REPO_ROOT / "scripts" / "loadtest" / "faults.js"
DEFAULT_OUT_DIR = REPO_ROOT / "reports" / "loadtest"


@dataclass
class Scenario:
    key: str
    title: str
    expectation: str
    env: dict[str, str] = field(default_factory=dict)
    ops_overrides: dict[str, Any] = field(default_factory=dict)
    # mock 的延遲必須從 load_test 區塊改,不能只設環境變數——start_backend 會
    # 用 ops.yaml 的值覆寫掉環境變數。第一次跑就踩到:設了 3000ms 卻量到 605ms。
    load_test_overrides: dict[str, Any] = field(default_factory=dict)


SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        key="healthy",
        title="一切正常(對照組)",
        expectation="chat 正常回答;health 快速。這一列是其餘場景的比較基準",
    ),
    Scenario(
        key="provider_down",
        title="provider 持續失敗(100%)",
        expectation="chat 回結構化拒答(HTTP 200 + refused)、熔斷開啟後快速失敗;"
        "**health 不該被拖慢**",
        env={"FHIR_COPILOT_MOCK_FAILURE_RATE": "1.0"},
    ),
    Scenario(
        key="provider_flaky",
        title="provider 間歇失敗(50%)",
        expectation="重試吸收掉一部分失敗;成功率高於 50%,但延遲因退避而上升",
        env={"FHIR_COPILOT_MOCK_FAILURE_RATE": "0.5", "FHIR_COPILOT_MOCK_FAILURE_SEED": "20260725"},
    ),
    Scenario(
        key="provider_slow_no_breaker",
        title="provider 極慢(3 秒),熔斷閾值調到極高",
        expectation="**這是沒有熔斷的對照組**:provider 沒有失敗、只是很慢,"
        "所以熔斷不會開;請求全部卡在 provider 上把 threadpool 佔滿",
        load_test_overrides={"mock_latency_ms": 3000},
        ops_overrides={"failure_threshold": 1_000_000},
    ),
    Scenario(
        key="audit_db_down",
        title="稽核資料庫連不上",
        expectation="health 回 degraded 而不是死掉;chat fail closed 回 503;唯讀端點不受影響",
        env={"DATABASE_URL": "postgresql://copilot:copilot@127.0.0.1:59999/nonexistent"},
    ),
)


def run_scenario(
    scenario: Scenario, *, k6: str, out_dir: Path, chat_vus: int, duration_seconds: int
) -> dict[str, Any]:
    ops = load_ops()
    if scenario.ops_overrides:
        ops = ops.model_copy(
            update={"resilience": ops.resilience.model_copy(update=scenario.ops_overrides)}
        )
    if scenario.load_test_overrides:
        ops = ops.model_copy(
            update={"load_test": ops.load_test.model_copy(update=scenario.load_test_overrides)}
        )
    override_path = out_dir / "_ops-fault.yaml"
    summary_path = out_dir / "_k6-fault-summary.json"

    backend_env = dict(os.environ)
    backend_env.update(scenario.env)
    # 每個場景都從乾淨的環境開始——上一個場景的注入不該漏到下一個
    for name in ("FHIR_COPILOT_MOCK_FAILURE_RATE", "FHIR_COPILOT_MOCK_LATENCY_MS", "DATABASE_URL"):
        if name not in scenario.env:
            backend_env.pop(name, None)

    old_environ = dict(os.environ)
    os.environ.clear()
    os.environ.update(backend_env)
    try:
        write_permissive_ops(ops, override_path)
        backend = start_backend(ops, override_path)
        try:
            wait_for_health(f"http://{ops.load_test.host}:{ops.load_test.port}")
            base_url = f"http://{ops.load_test.host}:{ops.load_test.port}"
            patient_id = first_patient_id(base_url)

            env = dict(os.environ)
            env.update(
                {
                    "BASE_URL": base_url,
                    "PATIENT_ID": patient_id,
                    "CHAT_VUS": str(chat_vus),
                    "DURATION": f"{duration_seconds}s",
                    "SUMMARY_OUT": summary_path.name,
                }
            )
            result = subprocess.run(
                [k6, "run", "--quiet", str(K6_SCRIPT)],
                env=env,
                cwd=summary_path.parent,
                capture_output=True,
            )
            if result.returncode != 0:
                raise SystemExit(
                    f"k6 失敗({scenario.key}):\n{result.stderr.decode('utf-8', 'replace')}"
                )
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        finally:
            backend.terminate()
            try:
                backend.wait(timeout=15)
            except subprocess.TimeoutExpired:
                backend.kill()
    finally:
        os.environ.clear()
        os.environ.update(old_environ)
        summary_path.unlink(missing_ok=True)
        override_path.unlink(missing_ok=True)

    return extract(scenario, summary)


def extract(scenario: Scenario, summary: dict[str, Any]) -> dict[str, Any]:
    metrics: dict[str, Any] = summary.get("metrics", {})

    def trend(name: str, stat: str) -> float:
        return float(metrics.get(name, {}).get("values", {}).get(stat, float("nan")))

    def rate(name: str) -> float:
        return float(metrics.get(name, {}).get("values", {}).get("rate", 0.0))

    def count(name: str) -> float:
        return float(metrics.get(name, {}).get("values", {}).get("count", 0))

    return {
        "key": scenario.key,
        "title": scenario.title,
        "expectation": scenario.expectation,
        "chat": {
            "p50_ms": trend("chat_duration", "p(50)"),
            "p95_ms": trend("chat_duration", "p(95)"),
            "requests": count("chat_duration"),
            "refused_rate": rate("chat_refused"),
            "http_error_rate": rate("chat_failed"),
        },
        "health": {
            "p50_ms": trend("health_duration", "p(50)"),
            "p95_ms": trend("health_duration", "p(95)"),
            "p99_ms": trend("health_duration", "p(99)"),
            "max_ms": trend("health_duration", "max"),
            "requests": count("health_duration"),
        },
    }


def build_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# 故障注入場景表",
        "",
        f"產生時間:{payload['generated_at']}",
        "",
        "每個場景都**一邊用固定併發打 `/api/chat`,一邊以固定速率打 `/api/health`**,",
        "兩者的延遲分開記錄。故障一律用 mock provider 的注入旋鈕,不打真的 provider。",
        "",
        f"參數:chat 併發 {payload['chat_vus']}、每個場景 {payload['duration_seconds']} 秒、",
        "health 固定 5 req/s。uvicorn 單一 worker(與 Dockerfile 的 CMD 一致)。",
        "",
        "## 為什麼要這樣量",
        "",
        "熔斷的目的不是省錢,是**不要讓一個壞掉的下游把 threadpool 佔滿**。",
        "七個端點全是同步 `def`,跑在 anyio threadpool 的 40 個 slot 上——provider 掛掉時",
        "每個請求都佔住一個 slot 直到逾時,佔滿之後連 `/api/health` 都排不進去,",
        "而**監控會在服務其實還活著的時候誤判成整台死亡**。",
        "",
        "所以這張表真正要看的欄位是「health p95/p99」:如果它在 provider 掛掉時仍然很小,",
        "那句宣稱才算有證據。",
        "",
        "## 結果",
        "",
        "| 場景 | chat p50 | chat p95 | chat 拒答率 | chat HTTP 錯誤 "
        "| **health p95** | **health p99** | health max |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in payload["scenarios"]:
        c, h = row["chat"], row["health"]
        lines.append(
            f"| {row['title']} | {c['p50_ms']:.0f} ms | {c['p95_ms']:.0f} ms "
            f"| {c['refused_rate'] * 100:.0f}% | {c['http_error_rate'] * 100:.0f}% "
            f"| **{h['p95_ms']:.1f} ms** | **{h['p99_ms']:.1f} ms** | {h['max_ms']:.0f} ms |"
        )

    lines += ["", "## 各場景的預期行為", ""]
    for row in payload["scenarios"]:
        lines.append(f"- **{row['title']}**:{row['expectation']}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--chat-vus", type=int, default=32)
    parser.add_argument("--duration", type=int, default=30)
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    k6 = find_k6()

    rows = []
    for index, scenario in enumerate(SCENARIOS, start=1):
        logger.info("[%d/%d] %s", index, len(SCENARIOS), scenario.title)
        rows.append(
            run_scenario(
                scenario,
                k6=k6,
                out_dir=args.out_dir,
                chat_vus=args.chat_vus,
                duration_seconds=args.duration,
            )
        )

    payload: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "chat_vus": args.chat_vus,
        "duration_seconds": args.duration,
        "scenarios": rows,
    }
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    (args.out_dir / f"fault-injection-{stamp}.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (args.out_dir / f"fault-injection-{stamp}.md").write_text(
        build_markdown(payload), encoding="utf-8"
    )
    logger.info("已輸出 %s", args.out_dir / f"fault-injection-{stamp}.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
