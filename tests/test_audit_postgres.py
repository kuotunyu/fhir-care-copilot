"""Postgres 稽核後端的整合測試。

**需要真的資料庫**:沒有 ``DATABASE_URL`` 就整組跳過。這不是「測不到就算了」——
沒有 DB 的環境(例如 HF Space、或只想跑單元測試的開發者)本來就跑檔案模式,
而檔案模式的行為由 ``test_audit_trail.py`` 涵蓋。CI 有一個帶 Postgres service
的 job 專門跑這一組。

本機要跑:

    docker compose --profile db up -d postgres
    DATABASE_URL=postgresql://copilot:copilot@localhost:5432/copilot \\
        uv run pytest tests/test_audit_postgres.py
"""

import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor

import pytest

from fhir_copilot.ops.audit import verify_chain

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="沒有 DATABASE_URL——Postgres 整合測試需要真的資料庫"
)


@pytest.fixture
def sink() -> Iterator[object]:
    from fhir_copilot.ops.audit.postgres import PostgresAuditSink

    instance = PostgresAuditSink(DATABASE_URL)
    # 每個測試從乾淨的表開始。**只有測試會 truncate**——正式路徑上這張表
    # 沒有任何 delete/update 的入口。
    import psycopg

    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute("TRUNCATE care_note_audit")
        cur.execute("TRUNCATE daily_budget")
        conn.commit()
    yield instance


def append(sink: object, note_text: str) -> object:
    return sink.append(  # type: ignore[attr-defined]
        patient_id="patient-1",
        note_text=note_text,
        proposed_at="2026-07-25T00:00:00+00:00",
        confirmed_at="2026-07-25T00:00:01+00:00",
        actor="tester",
        request_id="req-1",
    )


class TestPostgresChain:
    def test_appends_build_a_valid_chain(self, sink: object) -> None:
        for i in range(5):
            append(sink, f"第 {i} 筆")

        records = sink.read_all()  # type: ignore[attr-defined]

        assert len(records) == 5
        assert verify_chain(records).ok is True

    def test_tampering_in_the_database_is_detected(self, sink: object) -> None:
        """驗收條件之一。這裡是**直接改資料庫**——模擬有資料庫存取權的人動手腳,
        那正是「檔案可能被改」升級成 Postgres 之後仍然要防的情境。"""
        import psycopg

        for i in range(4):
            append(sink, f"第 {i} 筆")

        with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE care_note_audit SET note_text = %s WHERE sequence = %s",
                ("被偷偷改掉的內容", 2),
            )
            conn.commit()

        result = verify_chain(sink.read_all())  # type: ignore[attr-defined]

        assert result.ok is False
        assert any("第 3 列" in problem for problem in result.problems)

    def test_deleting_a_row_in_the_database_is_detected(self, sink: object) -> None:
        import psycopg

        for i in range(4):
            append(sink, f"第 {i} 筆")

        with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM care_note_audit WHERE sequence = 1")
            conn.commit()

        assert verify_chain(sink.read_all()).ok is False  # type: ignore[attr-defined]


class TestPostgresConcurrency:
    def test_concurrent_appends_do_not_fork_the_chain(self, sink: object) -> None:
        """這是 Postgres 模式相對於檔案模式的核心價值:**跨連線**的併發安全。

        沒有交易內的 FOR UPDATE 鎖住鏈尾的話,兩個同時進來的寫入會讀到同一列
        當作前一列,產生兩列 prev_hash 相同的紀錄——筆數是對的,但鏈已經分叉。
        """
        total = 40
        with ThreadPoolExecutor(max_workers=12) as pool:
            list(pool.map(lambda i: append(sink, f"併發第 {i} 筆"), range(total)))

        records = sink.read_all()  # type: ignore[attr-defined]

        assert len(records) == total
        assert [r.sequence for r in records] == list(range(total))
        assert verify_chain(records).ok is True


class TestPersistentBudget:
    def test_budget_survives_a_new_instance(self, sink: object) -> None:
        """Phase 1 的計數重啟就歸零。接上 DB 之後不該再這樣。"""
        from fhir_copilot.ops.audit.postgres import PostgresAuditSink
        from fhir_copilot.ops.budget import DailyBudget

        first = DailyBudget(daily_limit_usd=1.0, store=sink)  # type: ignore[arg-type]
        first.record(0.25)

        # 模擬服務重啟:全新的 budget 物件、全新的連線
        second = DailyBudget(daily_limit_usd=1.0, store=PostgresAuditSink(DATABASE_URL))

        assert second.spent_today_usd() == pytest.approx(0.25)
        assert second.is_persistent is True

    def test_concurrent_records_do_not_lose_spend(self, sink: object) -> None:
        """用「先讀再寫」實作的話,併發下會漏記——兩個請求都讀到同一個舊值。"""
        from fhir_copilot.ops.budget import DailyBudget

        budget = DailyBudget(daily_limit_usd=1000.0, store=sink)  # type: ignore[arg-type]

        with ThreadPoolExecutor(max_workers=12) as pool:
            list(pool.map(lambda _: budget.record(0.01), range(50)))

        assert budget.spent_today_usd() == pytest.approx(0.5, abs=1e-6)
