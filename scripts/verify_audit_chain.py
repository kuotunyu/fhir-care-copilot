"""驗證稽核軌跡的 hash chain,壞掉時指出是哪一列。

    uv run python scripts/verify_audit_chain.py
    DATABASE_URL=postgresql://... uv run python scripts/verify_audit_chain.py

沒有 ``DATABASE_URL`` 就驗 JSONL 檔,有就驗 Postgres——與服務本身用同一套解析,
所以「驗證程式看的東西」與「服務寫的東西」不可能分岔。

exit code:0 = 完整,1 = 有問題(方便接進 cron 或 CI)。

**這個程式能證明什麼、不能證明什麼**:它能抓出任何單列的內容改動、刪除、插入
與重排。它抓不出「有寫入權限的人重算了整條鏈」——那需要把鏈尾定期送到這個系統
改不到的地方。這是已知限制,寫在 ADR 0007。
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from fhir_copilot.ops.audit import resolve_audit_sink, verify_chain
from fhir_copilot.ops.audit.sinks import database_url

logger = logging.getLogger("verify_audit_chain")

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_JSONL = REPO_ROOT / "audit_log" / "care_notes.jsonl"


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--jsonl",
        type=Path,
        default=DEFAULT_JSONL,
        help="檔案模式時要驗的 JSONL 路徑(有 DATABASE_URL 時忽略)",
    )
    args = parser.parse_args()

    sink = resolve_audit_sink(args.jsonl)
    source = "Postgres" if database_url() else str(args.jsonl)
    logger.info("後端:%s(%s)", sink.backend, source)

    records = sink.read_all()
    if not records:
        logger.info("稽核軌跡是空的——沒有東西可以驗證。")
        return 0

    result = verify_chain(records)
    logger.info("%s", result.summary())
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
