"""匯出一條完整請求的 trace 成 JSON,存進 reports/traces/。

    uv run python scripts/export_trace_sample.py

**為什麼要有這個東西**:可觀測性必須有消費端。Jaeger(``docker compose
--profile dev up``)是「可以自己跑起來看」,這份 JSON 是「不跑任何東西也看得到」——
它 commit 進 repo,任何人翻開就知道這個服務的 trace 長什麼樣、鏈路有幾層。

走 ``TestClient`` 而不是另起一個伺服器:請求一樣會經過完整的 ASGI stack
(middleware、路由、agent loop、工具、provider),所以 span 是真的,而且不必
處理埠號與等待就緒。

**PII**:span 屬性受 ``ops.redaction`` 的規則管——這份要進 git 的檔案裡
不會有病患姓名、問題內容或完整 patient_id。``tests/test_pii_redaction.py``
會實際 grep 驗證這件事。
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from fhir_copilot.ops import tracing

logger = logging.getLogger("export_trace_sample")

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT_DIR = REPO_ROOT / "reports" / "traces"
REAL_DATA_DIR = REPO_ROOT / "data" / "processed" / "subset_100"
FIXTURES_DIR = REPO_ROOT / "tests" / "data" / "fixtures"

QUESTION = "他目前有在吃什麼藥?"


def pick_data_dir() -> Path:
    """有實際下載的 100 位 Synthea 合成病患就用它,否則退回 committed fixtures。

    fixtures 也能產出結構完全相同的 trace,所以沒有 data/ 的人一樣跑得出來。
    """
    return REAL_DATA_DIR if REAL_DATA_DIR.is_dir() else FIXTURES_DIR


def pick_patient_with_medications(client: Any) -> str:
    """挑一位有生效中用藥的病患。

    隨便挑第一位的話,樣本很可能落在「這位病患沒有生效中用藥」的空結果上——
    那是正確行為(ok=True 但清單為空),但當作展示 trace 的樣本沒有說服力,
    因為看不到 evidence 真的被帶出來。
    """
    patients = client.get("/api/patients").json()["patients"]
    for patient in patients[:20]:
        summary = client.get(f"/api/patients/{patient['patient_id']}/summary").json()
        if summary["medications"]:
            return str(patient["patient_id"])
    return str(patients[0]["patient_id"])


def spans_for_chat_trace(spans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """只留 ``POST /api/chat`` 那條 trace 上的 span,依開始時間排序。"""
    roots = [span for span in spans if span["name"] == "POST /api/chat"]
    if not roots:
        return sorted(spans, key=lambda span: span["start_time"] or 0)
    trace_id = roots[-1]["trace_id"]
    selected = [span for span in spans if span["trace_id"] == trace_id]
    return sorted(selected, key=lambda span: span["start_time"] or 0)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    spans_path = args.out_dir / "_spans.jsonl"
    spans_path.unlink(missing_ok=True)

    data_dir = pick_data_dir()
    os.environ["FHIR_COPILOT_DATA_DIR"] = str(data_dir)
    os.environ["FHIR_COPILOT_PROVIDER"] = "mock"
    os.environ[tracing.TRACE_FILE_ENV] = str(spans_path)
    # 這份要進 git,不要讓開發機碰巧設定的金鑰或認證影響輸出
    for name in ("FHIR_COPILOT_API_KEYS", "FHIR_COPILOT_REQUIRE_AUTH"):
        os.environ.pop(name, None)

    tracing.reset_for_tests()

    from fastapi.testclient import TestClient

    from fhir_copilot.api import dependencies
    from fhir_copilot.api.app import create_app

    dependencies.reset_caches()
    with TestClient(create_app()) as client:
        patient_id = pick_patient_with_medications(client)
        response = client.post("/api/chat", json={"patient_id": patient_id, "question": QUESTION})
        response.raise_for_status()
        answer = response.json()
    tracing.flush()

    all_spans = [
        json.loads(line)
        for line in spans_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    spans_path.unlink(missing_ok=True)

    # 只留這一次 chat 的 trace。挑病患用的那幾個請求也會產生 span(而且第一個
    # 還帶著建索引的冷啟動時間),留在樣本裡只會讓讀的人以為那是問答的一部分。
    spans = spans_for_chat_trace(all_spans)

    payload: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "what_this_is": (
            "一次 POST /api/chat 的完整 trace。四層鏈路:HTTP → agent loop → "
            "每次工具執行 → 每次 provider 呼叫。span 屬性經過 PII 遮蔽,"
            "不含病患姓名、問題內容或完整 patient_id。"
        ),
        "dataset": data_dir.name,
        "provider": "mock(固定延遲 0ms;真實 provider 的延遲不在這份樣本裡)",
        "question_length": len(QUESTION),
        "answer_summary": {
            "refused": answer["refused"],
            "evidence_count": len(answer["evidence"]),
            "latency_ms": answer["latency_ms"],
        },
        "span_count": len(spans),
        "spans": spans,
    }

    stamp = datetime.now(UTC).strftime("%Y%m%d")
    out_path = args.out_dir / f"chat-{stamp}.json"
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    logger.info("已輸出 %s(%d 個 span)", out_path, len(spans))
    for span in spans:
        logger.info("  %-28s %s ms", span["name"], span["duration_ms"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
