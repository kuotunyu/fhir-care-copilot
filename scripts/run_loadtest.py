"""負載測試 runner:起後端 → 跑 k6 併發矩陣 → 輸出 reports/loadtest/。

    uv run python scripts/run_loadtest.py --label baseline

量到的是**服務層 overhead**:FastAPI + 路由 + 工具執行 + FHIR store 查詢。
``/api/chat`` 走 mock provider 加固定延遲(``FHIR_COPILOT_MOCK_LATENCY_MS``),
**不含真實 LLM 供應商的延遲**——那是另一軌,要用真 provider 少量取樣另外量。

所有參數出自 ``configs/ops.yaml`` 的 ``load_test`` 區塊。Phase 0 基線與之後的
對照必須用同一組參數,否則兩組數字不可比。
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import yaml

from fhir_copilot.ops.config import OpsConfig, load_ops

logger = logging.getLogger("run_loadtest")

REPO_ROOT = Path(__file__).resolve().parent.parent
K6_SCRIPT = REPO_ROOT / "scripts" / "loadtest" / "api.js"
DEFAULT_OUT_DIR = REPO_ROOT / "reports" / "loadtest"

# k6 的 percentile key 名稱;summaryTrendStats 決定它們存不存在
_PERCENTILES = ("p(50)", "p(95)", "p(99)")


def find_k6() -> str:
    """找 k6 執行檔。winget 安裝後 PATH 要開新 shell 才生效,所以補上預設路徑。"""
    found = shutil.which("k6")
    if found:
        return found
    fallback = Path(r"C:\Program Files\k6\k6.exe")
    if fallback.is_file():
        return str(fallback)
    raise SystemExit("找不到 k6。安裝:winget install --id GrafanaLabs.k6 -e")


def http_get_json(url: str, timeout: float = 10.0) -> Any:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def wait_for_health(base_url: str, attempts: int = 60) -> float:
    """等後端起來;回傳第一個成功請求的耗時(含 store 索引的冷啟動成本)。"""
    for i in range(attempts):
        started = time.monotonic()
        try:
            http_get_json(f"{base_url}/api/health")
        except (urllib.error.URLError, OSError, TimeoutError):
            time.sleep(1.0)
            continue
        elapsed_ms = (time.monotonic() - started) * 1000
        logger.info("後端就緒(第 %d 次嘗試,首次 /api/health 耗時 %.1f ms)", i + 1, elapsed_ms)
        return elapsed_ms
    raise SystemExit(f"後端在 {attempts} 秒內沒有起來:{base_url}")


def first_patient_id(base_url: str) -> str:
    payload = http_get_json(f"{base_url}/api/patients")
    patients = payload["patients"]
    if not patients:
        raise SystemExit("資料目錄裡沒有病患,無法測 summary/chat 端點")
    patient_id: str = patients[0]["patient_id"]
    return patient_id


def measure_cold_summary(base_url: str, patient_id: str) -> float:
    """量第一次 /api/patients/{id}/summary 的耗時(bundle 尚未進 LRU 快取)。"""
    started = time.monotonic()
    http_get_json(f"{base_url}/api/patients/{patient_id}/summary", timeout=60.0)
    return (time.monotonic() - started) * 1000


def warmup(base_url: str, patient_id: str, n: int) -> None:
    """先打幾次把冷啟動成本付掉,不讓它汙染階梯上的第一格。"""
    for _ in range(n):
        http_get_json(f"{base_url}/api/health")
        http_get_json(f"{base_url}/api/patients")
        http_get_json(f"{base_url}/api/patients/{patient_id}/summary", timeout=60.0)
    logger.info("warmup 完成(%d 輪)", n)


def write_permissive_ops(ops: OpsConfig, path: Path) -> Path:
    """產生一份「限流與預算高到不可能觸發」的 ops.yaml 給受測後端用。

    要量的是**守門的成本**(每個請求都要解析 header、比對金鑰、扣 token、
    估算成本),不是**守門拒絕流量的行為**。用正式速率跑負載測試的話,
    量到的會是一整片 429,那不是 overhead,那是限流在工作。

    `load_test` 區塊原樣帶過去,所以基線與對照的量測參數不可能分岔。
    """
    data = ops.model_dump()
    data["rate_limit"]["requests_per_minute"] = 100_000_000
    data["rate_limit"]["burst"] = 100_000_000
    data["budget"]["daily_limit_usd"] = 1_000_000.0
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


def start_backend(ops: OpsConfig, ops_override_path: Path) -> subprocess.Popen[bytes]:
    cfg = ops.load_test
    env = dict(os.environ)
    env["FHIR_COPILOT_PROVIDER"] = "mock"
    env["FHIR_COPILOT_MOCK_LATENCY_MS"] = str(cfg.mock_latency_ms)
    env["FHIR_COPILOT_OPS_CONFIG"] = str(write_permissive_ops(ops, ops_override_path))
    # 認證維持關閉:量的是守門程式碼本身的成本,所有請求都會走完整條守門路徑
    # (解析 header → 沒有金鑰 → anonymous → 扣 token → 估算成本),
    # 不需要真的帶金鑰才算數。
    env.pop("FHIR_COPILOT_API_KEYS", None)
    env.pop("FHIR_COPILOT_REQUIRE_AUTH", None)
    # 與 Dockerfile CMD 一致:單一 worker、無 --reload
    command = [
        sys.executable,
        "-m",
        "uvicorn",
        "fhir_copilot.api.app:app",
        "--host",
        cfg.host,
        "--port",
        str(cfg.port),
        "--log-level",
        "warning",
    ]
    logger.info("啟動後端:%s(mock latency %d ms)", " ".join(command[-6:]), cfg.mock_latency_ms)
    return subprocess.Popen(command, env=env, cwd=REPO_ROOT)


def run_k6(
    *,
    k6: str,
    base_url: str,
    target: str,
    patient_id: str,
    vus: int,
    duration_seconds: int,
    summary_path: Path,
) -> dict[str, Any]:
    env = dict(os.environ)
    env.update(
        {
            "BASE_URL": base_url,
            "TARGET": target,
            "PATIENT_ID": patient_id,
            "VUS": str(vus),
            "DURATION": f"{duration_seconds}s",
            # k6 在 script 的工作目錄寫檔,所以給它一個相對於 repo root 的路徑
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
        stderr = result.stderr.decode("utf-8", errors="replace")
        raise SystemExit(f"k6 失敗(target={target}, vus={vus}):\n{stderr}")
    parsed: dict[str, Any] = json.loads(summary_path.read_text(encoding="utf-8"))
    return parsed


def extract_metrics(summary: dict[str, Any]) -> dict[str, float]:
    """從 k6 summary 取出這份報表要記錄的欄位。"""
    metrics: dict[str, Any] = summary.get("metrics", {})
    duration_values: dict[str, Any] = metrics.get("http_req_duration", {}).get("values", {})
    reqs_values: dict[str, Any] = metrics.get("http_reqs", {}).get("values", {})
    failed_values: dict[str, Any] = metrics.get("http_req_failed", {}).get("values", {})

    out: dict[str, float] = {}
    for key in _PERCENTILES:
        out[key] = float(duration_values.get(key, float("nan")))
    out["min"] = float(duration_values.get("min", float("nan")))
    out["max"] = float(duration_values.get("max", float("nan")))
    out["requests"] = float(reqs_values.get("count", 0))
    out["rps"] = float(reqs_values.get("rate", 0.0))
    out["error_rate"] = float(failed_values.get("rate", 0.0))
    return out


def median_of(runs: list[dict[str, float]], key: str) -> float:
    return statistics.median(run[key] for run in runs)


def aggregate(runs: list[dict[str, float]]) -> dict[str, float]:
    """同一組合重跑 N 次 → 每個欄位取中位數(單次跑到系統雜訊的機率較高)。"""
    return {key: median_of(runs, key) for key in runs[0]}


def build_markdown(payload: dict[str, Any]) -> str:
    cfg: dict[str, Any] = payload["config"]
    lines: list[str] = [
        f"# 負載測試:{payload['label']}",
        "",
        f"產生時間:{payload['generated_at']}",
        "",
        "## 這組數字是什麼(以及不是什麼)",
        "",
        "量的是**服務層 overhead**:FastAPI + 路由 + 工具執行 + FHIR store 查詢。",
        "",
        f"`/api/chat` 走 mock provider,每次 provider 呼叫固定延遲 "
        f"**{cfg['mock_latency_ms']} ms**;agent loop 一輪問答呼叫兩次,"
        f"所以端到端延遲的理論下限約 **{cfg['mock_latency_ms'] * 2} ms**。",
        "",
        "**這組數字不含真實 LLM 供應商的延遲。** 真實端到端延遲是另一軌,",
        "要用真 provider 少量取樣另外量,兩者不可混用。",
        "",
        "## 執行環境",
        "",
        "- uvicorn worker 數:1(與 Dockerfile 的 CMD 一致)",
        "- 端點 handler 全部是同步 `def`,由 anyio threadpool 執行(預設上限 40)",
        f"- 資料集:{payload['dataset']}",
        f"- 每格量測時間 {cfg['duration_seconds']}s,重跑 {cfg['repeats']} 次取各百分位數的中位數",
        "",
        "## 冷啟動",
        "",
        f"- 首次 `/api/health`(含 store 建索引):**{payload['cold_start']['health_ms']:.0f} ms**",
        f"- 首次 `/api/patients/{{id}}/summary`(bundle 尚未進 LRU 快取):"
        f"**{payload['cold_start']['summary_ms']:.0f} ms**",
        "",
        "階梯上的數字都是 warmup 之後量的,不含上面兩個冷啟動成本。",
        "",
    ]

    for target in cfg["targets"]:
        lines.append(f"## {target}")
        lines.append("")
        lines.append("| 併發 | p50 (ms) | p95 (ms) | p99 (ms) | max (ms) | RPS | 錯誤率 | 樣本數 |")
        lines.append("|---:|---:|---:|---:|---:|---:|---:|---:|")
        for vus in cfg["concurrency_ladder"]:
            row: dict[str, float] = payload["results"][target][str(vus)]
            lines.append(
                f"| {vus} | {row['p(50)']:.1f} | {row['p(95)']:.1f} | {row['p(99)']:.1f} "
                f"| {row['max']:.1f} | {row['rps']:.1f} | {row['error_rate'] * 100:.2f}% "
                f"| {int(row['requests'])} |"
            )
        lines.append("")

    lines.extend(
        [
            "## 怎麼讀",
            "",
            "- 低併發的 `/api/chat` 樣本數本來就少(每次請求至少 "
            f"{cfg['mock_latency_ms'] * 2} ms),該格的 p99 是小樣本估計,",
            "  表格附了樣本數就是為了讓這件事看得見,不要當成穩定的尾延遲。",
            "- 併發拉高之後如果 p99 開始遠離 p50,通常是 threadpool 排隊而不是單次處理變慢。",
            "- 受測後端跑在「限流與預算調到不可能觸發」的設定下:要量的是守門的**成本**"
            "(每個請求都要解析 header、比對金鑰、扣 token、估算成本),",
            "  不是守門**拒絕流量**的行為。用正式速率跑的話量到的會是一整片 429。",
            "- `/api/health`、`/api/patients`、`/api/summary` 不受守門保護,"
            "在對照時等於內建的控制組——它們的數字應該幾乎不動。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--label",
        default="baseline",
        help="這次量測的標籤,會成為輸出檔名的一部分(預設 baseline)",
    )
    parser.add_argument(
        "--config", type=Path, default=None, help="ops.yaml 路徑(預設 configs/ops.yaml)"
    )
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument(
        "--ladder",
        default=None,
        help="只跑指定的併發階梯(逗號分隔,例如 1,8,64);省略則跑 ops.yaml 的完整階梯",
    )
    args = parser.parse_args()

    ops = load_ops(args.config)
    cfg = ops.load_test
    if args.ladder:
        cfg = cfg.model_copy(
            update={"concurrency_ladder": [int(v) for v in args.ladder.split(",")]}
        )
    k6 = find_k6()
    base_url = f"http://{cfg.host}:{cfg.port}"
    logger.info("k6:%s", k6)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    backend = start_backend(ops, args.out_dir / "_ops-loadtest.yaml")
    try:
        cold_health_ms = wait_for_health(base_url)
        patient_id = first_patient_id(base_url)
        cold_summary_ms = measure_cold_summary(base_url, patient_id)
        logger.info("首次 summary 耗時 %.1f ms", cold_summary_ms)
        warmup(base_url, patient_id, cfg.warmup_requests)

        summary_path = args.out_dir / "_k6-summary.json"
        results: dict[str, dict[str, dict[str, float]]] = {}
        total = len(cfg.targets) * len(cfg.concurrency_ladder) * cfg.repeats
        done = 0
        for target in cfg.targets:
            results[target] = {}
            for vus in cfg.concurrency_ladder:
                runs: list[dict[str, float]] = []
                for _ in range(cfg.repeats):
                    summary = run_k6(
                        k6=k6,
                        base_url=base_url,
                        target=target,
                        patient_id=patient_id,
                        vus=vus,
                        duration_seconds=cfg.duration_seconds,
                        summary_path=summary_path,
                    )
                    runs.append(extract_metrics(summary))
                    done += 1
                    logger.info("[%d/%d] %s c%d 完成", done, total, target, vus)
                results[target][str(vus)] = aggregate(runs)
    finally:
        backend.terminate()
        try:
            backend.wait(timeout=15)
        except subprocess.TimeoutExpired:
            backend.kill()
        logger.info("後端已停止")
        # 中途失敗時也要清掉,不然這兩個暫存檔會留在會進 git 的 reports/ 底下
        (args.out_dir / "_k6-summary.json").unlink(missing_ok=True)
        (args.out_dir / "_ops-loadtest.yaml").unlink(missing_ok=True)

    stamp = datetime.now(UTC).strftime("%Y%m%d")
    payload: dict[str, Any] = {
        "label": args.label,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "dataset": os.environ.get("FHIR_COPILOT_DATA_DIR", "data/processed/subset_100"),
        "config": cfg.model_dump(),
        "cold_start": {"health_ms": cold_health_ms, "summary_ms": cold_summary_ms},
        "results": results,
    }
    json_path = args.out_dir / f"{args.label}-{stamp}.json"
    md_path = args.out_dir / f"{args.label}-{stamp}.md"
    # 結尾補換行:這兩份報表會進 git,而 pre-commit 的 end-of-file-fixer 會去修
    # 沒有結尾換行的檔案——hook 一改檔案就會中止 commit,每次產出報表都要卡一次
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    md_path.write_text(build_markdown(payload), encoding="utf-8")
    logger.info("已輸出 %s", json_path)
    logger.info("已輸出 %s", md_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
