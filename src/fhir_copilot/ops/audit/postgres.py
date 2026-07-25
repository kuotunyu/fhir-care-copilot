"""Postgres 稽核後端。

**這裡只放稽核軌跡與預算計數,FHIR 資料不進資料庫**(ADR 0001 / PLAN.md §3.1)。
「LLM 物理上拿不到資料庫、每個臨床事實都經過確定性工具」是這個專案的核心賣點,
把 FHIR 塞進 DB 會把那條線弄糊。

**append-only 靠三件事一起**:

1. 資料表沒有 UPDATE/DELETE 的路徑(這個模組不提供,也不該有人加)
2. hash chain(在 ``chain`` 模組)讓事後的改動留下痕跡
3. 寫入時在交易內鎖住鏈尾,所以併發 append 不會拿到同一個 ``prev_hash``

第 3 點用 **advisory lock**(``pg_advisory_xact_lock``),不是 ``SELECT ... FOR UPDATE``。

**為什麼 FOR UPDATE 不夠**(實測踩到的):``FOR UPDATE`` 只鎖住**已經存在的那一列**,
擋不住「另一個交易在它後面插入新列」。兩個併發的 append 各自鎖住同一個鏈尾,
先完成的插入 sequence=N+1,後完成的醒來時手上還是舊的鏈尾,也插 N+1 →
主鍵衝突。表是空的時候更徹底:沒有列可鎖,所有交易一起衝 sequence=0。

advisory lock 鎖的是「append 這個動作」而不是某一列,所以新列插進來也擋得住。
代價是所有 append 完全序列化——對稽核軌跡這種低頻寫入完全可以接受,
而且**鏈本來就是線性的**,序列化不是限制,是它的本質。

**migration 用版本化 SQL 不用 alembic**:一張表、一次 migration。為此引進整套
migration 框架講不出領域理由(ADR 0004 的標準)。之後 schema 真的開始演化時再換,
那時候才有理由。
"""

from __future__ import annotations

import logging
import threading
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fhir_copilot.ops.audit.chain import GENESIS_HASH, AuditRecord, build_record

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

# 版本化 SQL。加新版本時往下追加,不要改既有的——已經跑過的 migration 改了
# 也不會重跑,只會讓新舊環境的 schema 不一致。
MIGRATIONS: tuple[tuple[int, str], ...] = (
    (
        1,
        """
        CREATE TABLE IF NOT EXISTS care_note_audit (
            sequence      BIGINT PRIMARY KEY,
            patient_id    TEXT        NOT NULL,
            note_text     TEXT        NOT NULL,
            proposed_at   TEXT        NOT NULL,
            confirmed_at  TEXT        NOT NULL,
            actor         TEXT        NOT NULL,
            request_id    TEXT        NOT NULL,
            prev_hash     CHAR(64)    NOT NULL,
            row_hash      CHAR(64)    NOT NULL UNIQUE,
            written_at    TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE TABLE IF NOT EXISTS daily_budget (
            day        DATE             PRIMARY KEY,
            spent_usd  DOUBLE PRECISION NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS schema_version (
            version    INTEGER     PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """,
    ),
)

_COLUMNS = (
    "sequence, patient_id, note_text, proposed_at, confirmed_at, "
    "actor, request_id, prev_hash, row_hash"
)

# advisory lock 的 key。任意常數,只要全服務一致即可;取自資料表名稱的雜湊,
# 讓它與別的 advisory lock 撞號的機率極低。
_APPEND_LOCK_KEY = 0x_CA4E_A0D1


class PostgresAuditSink:
    backend = "postgres"

    def __init__(self, url: str) -> None:
        self._url = url
        self._lock = threading.Lock()
        self._migrate()

    def _connect(self) -> psycopg.Connection[dict[str, Any]]:
        return psycopg.connect(self._url, row_factory=dict_row)

    def _migrate(self) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            for version, statements in MIGRATIONS:
                cur.execute(statements)
                cur.execute(
                    "INSERT INTO schema_version (version) VALUES (%s) ON CONFLICT DO NOTHING",
                    (version,),
                )
            conn.commit()
        logger.info("稽核資料表已就緒(schema v%d)", SCHEMA_VERSION)

    def append(
        self,
        *,
        patient_id: str,
        note_text: str,
        proposed_at: str,
        confirmed_at: str,
        actor: str,
        request_id: str,
    ) -> AuditRecord:
        with self._connect() as conn, conn.cursor() as cur:
            # 鎖「append 這個動作」而不是某一列——見模組 docstring:FOR UPDATE
            # 擋不住新列插進來,實測會在併發下撞主鍵。鎖在交易結束時自動釋放。
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (_APPEND_LOCK_KEY,))
            cur.execute(f"SELECT {_COLUMNS} FROM care_note_audit ORDER BY sequence DESC LIMIT 1")
            last = cur.fetchone()
            record = build_record(
                sequence=(last["sequence"] + 1) if last else 0,
                prev_hash=last["row_hash"] if last else GENESIS_HASH,
                patient_id=patient_id,
                note_text=note_text,
                proposed_at=proposed_at,
                confirmed_at=confirmed_at,
                actor=actor,
                request_id=request_id,
            )
            cur.execute(
                f"INSERT INTO care_note_audit ({_COLUMNS}) "
                "VALUES (%(sequence)s, %(patient_id)s, %(note_text)s, %(proposed_at)s, "
                "%(confirmed_at)s, %(actor)s, %(request_id)s, %(prev_hash)s, %(row_hash)s)",
                record.model_dump(),
            )
            conn.commit()
            return record

    def read_all(self) -> list[AuditRecord]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(f"SELECT {_COLUMNS} FROM care_note_audit ORDER BY sequence")
            return [AuditRecord.model_validate(row) for row in cur.fetchall()]

    # ---- 每日預算的持久化(Phase 1 的計數原本重啟就歸零)----

    def budget_spent(self, day: str) -> float:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT spent_usd FROM daily_budget WHERE day = %s", (day,))
            row = cur.fetchone()
            return float(row["spent_usd"]) if row else 0.0

    def budget_add(self, day: str, amount: float) -> float:
        """原子累加。用 ``ON CONFLICT DO UPDATE`` 而不是「先讀再寫」——
        後者在併發下會漏記(兩個請求都讀到同一個舊值)。"""
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO daily_budget (day, spent_usd) VALUES (%s, %s) "
                "ON CONFLICT (day) DO UPDATE SET spent_usd = daily_budget.spent_usd + %s "
                "RETURNING spent_usd",
                (day, amount, amount),
            )
            row = cur.fetchone()
            conn.commit()
            return float(row["spent_usd"]) if row else 0.0
