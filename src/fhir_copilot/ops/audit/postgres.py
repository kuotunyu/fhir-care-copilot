"""Postgres 稽核後端。

**這裡只放稽核軌跡與預算計數,FHIR 資料不進資料庫**(ADR 0001)。
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
import time
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


class AuditBackendUnavailableError(RuntimeError):
    """資料庫連不上。**不是**「稽核紀錄寫壞了」,是「現在寫不進去」。"""


class PostgresAuditSink:
    backend = "postgres"

    def __init__(self, url: str, *, connect_timeout: int = 5) -> None:
        # **刻意不在建構時連線。** 資料庫暫時不可用不該讓整個服務起不來——
        # 尤其不該讓 /api/health 跟著死掉:那樣監控只會看到「連不上」,
        # 分不出「服務死了」與「資料庫死了」,而這兩件事的處理方式完全不同。
        self._url = url
        self._connect_timeout = connect_timeout
        self._lock = threading.Lock()
        self._migrated = False
        # 可用性探測的狀態。探測**在背景執行緒做**,見 is_available()。
        #
        # 探測用**另一把鎖**:背景探測會呼叫 ensure_ready(),而那裡持有 _lock
        # 長達整個連線逾時。共用同一把鎖的話,健康檢查會卡在鎖上等探測結束——
        # 實測那讓一次健康檢查花了 8.9 秒,等於背景探測完全白做。
        self._probe_lock = threading.Lock()
        self._available = False
        self._probed_once = threading.Event()
        self._probe_running = False
        self._probed_at = 0.0

    def _connect(self) -> psycopg.Connection[dict[str, Any]]:
        return psycopg.connect(
            self._url, row_factory=dict_row, connect_timeout=self._connect_timeout
        )

    def ensure_ready(self) -> None:
        """建表。正式路徑上由每個資料庫操作**惰性**呼叫,連不上就拋
        ``AuditBackendUnavailableError``。

        **刻意是公開方法**:建表在建構時做的話,資料庫暫時不可用會讓整個服務起不來
        (見 ``__init__``),但「什麼時候建表」不該因此變成一件說不清楚的事。
        留一個明確的入口,讓測試與 migration 工具可以主動把 schema 準備好,
        而不是靠某個操作順便建。
        """
        if self._migrated:
            return
        with self._lock:
            if self._migrated:
                return
            try:
                with self._connect() as conn, conn.cursor() as cur:
                    for version, statements in MIGRATIONS:
                        cur.execute(statements)
                        cur.execute(
                            "INSERT INTO schema_version (version) VALUES (%s) "
                            "ON CONFLICT DO NOTHING",
                            (version,),
                        )
                    conn.commit()
            except psycopg.Error as exc:
                raise AuditBackendUnavailableError(f"稽核資料庫連不上:{exc}") from exc
            self._migrated = True
            logger.info("稽核資料表已就緒(schema v%d)", SCHEMA_VERSION)

    def _probe(self) -> None:
        try:
            self.ensure_ready()
            available = True
        except (AuditBackendUnavailableError, psycopg.Error):
            available = False
        self._available = available
        self._probed_at = time.monotonic()
        self._probe_running = False
        self._probed_once.set()

    def is_available(self, *, refresh_seconds: float = 5.0, first_probe_wait: float = 1.0) -> bool:
        """給 ``/api/health`` 用:回報資料庫現在通不通,**不拋例外也不阻塞**。

        **為什麼探測要在背景做**:連不上的資料庫會讓 ``psycopg.connect`` 等滿
        連線逾時,而且它對每一個解析出來的位址各等一次(``::1`` 與 ``127.0.0.1``
        就是兩次)。實測第一次呼叫花了 **10.4 秒**——一個要 10 秒才回應的健康檢查
        本身就是壞的:監控會逾時,然後回報服務死亡,正好是這個修正要避免的事。

        所以:探測丟到背景執行緒,呼叫端立刻拿到**上一次的結果**。
        只有 process 剛啟動、還沒有任何結果時,才短暫等一下(``first_probe_wait``),
        避免第一次健康檢查回報一個純粹是初始值的答案。
        """
        now = time.monotonic()
        with self._probe_lock:
            stale = now - self._probed_at >= refresh_seconds
            if stale and not self._probe_running:
                self._probe_running = True
                threading.Thread(target=self._probe, daemon=True).start()

        if not self._probed_once.is_set():
            # 只在完全還沒探測過時等一下下;等不到就先回 False(保守),
            # 下一次呼叫就會拿到真正的結果
            self._probed_once.wait(timeout=first_probe_wait)
        return self._available

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
        self.ensure_ready()
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
        self.ensure_ready()
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(f"SELECT {_COLUMNS} FROM care_note_audit ORDER BY sequence")
            return [AuditRecord.model_validate(row) for row in cur.fetchall()]

    # ---- 每日預算的持久化(Phase 1 的計數原本重啟就歸零)----

    def budget_spent(self, day: str) -> float:
        self.ensure_ready()
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT spent_usd FROM daily_budget WHERE day = %s", (day,))
            row = cur.fetchone()
            return float(row["spent_usd"]) if row else 0.0

    def budget_add(self, day: str, amount: float) -> float:
        """原子累加。用 ``ON CONFLICT DO UPDATE`` 而不是「先讀再寫」——
        後者在併發下會漏記(兩個請求都讀到同一個舊值)。"""
        self.ensure_ready()
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
