"""可信任的稽核軌跡(營運層 Phase 4)。

「這份稽核軌跡值得信任」需要**同時**回答三件事,這個檔案分成三個對應的區塊:

1. **進來時是真的嗎** —— ``TestDraftSignature``
2. **進去後沒被改嗎** —— ``TestTamperEvidence``
3. **併發下不會遺失嗎** —— ``TestConcurrency``

只做其中兩件,會得到兩個各自不完整的機制:只有防竄改鏈的話,得到的是
「一條防竄改的鏈,但鏈上第一環可能一開始就是假的」。
"""

import json
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from fhir_copilot.api import dependencies
from fhir_copilot.api.app import create_app
from fhir_copilot.care_notes import (
    CareNoteDraft,
    DraftSignatureError,
    ProposeCareNoteInput,
    confirm_and_log,
    propose_care_note,
)
from fhir_copilot.ops.audit import JsonlAuditSink, verify_chain
from fhir_copilot.ops.audit.chain import GENESIS_HASH, build_record
from fhir_copilot.ops.audit.signing import sign_draft, verify_draft
from fhir_copilot.ops.audit.sinks import resolve_audit_sink
from fhir_copilot.store import LocalBundleFHIRStore
from tests.conftest import AMY_ID, FIXTURES_DIR, clear_ops_env, write_ops_config

ClientFactory = Callable[..., TestClient]


def append(sink: JsonlAuditSink, note_text: str, sequence_hint: int = 0) -> Any:
    del sequence_hint
    return sink.append(
        patient_id=AMY_ID,
        note_text=note_text,
        proposed_at="2026-07-25T00:00:00+00:00",
        confirmed_at="2026-07-25T00:00:01+00:00",
        actor="tester",
        request_id="req-1",
    )


class TestDraftSignature:
    """進來時是真的嗎。

    認證回答的是「是誰打進來的」,不是「這份草稿是不是這個系統產生的」——
    一個通過認證的呼叫者仍然可以送出從來沒有經過 propose 的內容。
    """

    def test_propose_returns_a_signed_draft(self, store: LocalBundleFHIRStore) -> None:
        result = propose_care_note(store, ProposeCareNoteInput(patient_id=AMY_ID, note_text="x"))

        assert result.draft is not None
        assert result.draft.signature
        assert verify_draft(
            patient_id=result.draft.patient_id,
            note_text=result.draft.note_text,
            proposed_at=result.draft.proposed_at,
            signature=result.draft.signature,
        )

    @pytest.mark.parametrize("field", ["patient_id", "note_text", "proposed_at"])
    def test_tampering_with_any_field_invalidates_the_signature(
        self, store: LocalBundleFHIRStore, field: str
    ) -> None:
        """簽章必須涵蓋草稿的**全部**欄位。漏簽任何一個,那個欄位就可以被換掉——
        例如只簽 patient_id 的話,note_text 可以被改成任意內容再拿原簽章送出。"""
        result = propose_care_note(store, ProposeCareNoteInput(patient_id=AMY_ID, note_text="原始"))
        assert result.draft is not None
        tampered = result.draft.model_copy(update={field: "竄改後的值"})

        assert not verify_draft(
            patient_id=tampered.patient_id,
            note_text=tampered.note_text,
            proposed_at=tampered.proposed_at,
            signature=tampered.signature,
        )

    def test_forged_draft_is_rejected_before_anything_is_written(self, tmp_path: Path) -> None:
        """這是 Phase 4 存在的第一個理由:沒有這一關,防竄改鏈會忠實地保護
        一筆一開始就是假的紀錄。"""
        sink = JsonlAuditSink(tmp_path / "audit.jsonl")
        forged = CareNoteDraft(
            patient_id=AMY_ID,
            note_text="病患已於今日出院",
            proposed_at="2020-01-01T00:00:00+00:00",
            signature="a" * 64,
        )

        with pytest.raises(DraftSignatureError):
            confirm_and_log(forged, sink=sink)

        assert sink.read_all() == []  # 什麼都沒寫進去

    def test_signature_is_stable_for_the_same_content(self) -> None:
        first = sign_draft(patient_id="p", note_text="n", proposed_at="t")
        second = sign_draft(patient_id="p", note_text="n", proposed_at="t")

        assert first == second


class TestTamperEvidence:
    """進去後沒被改嗎。"""

    def test_clean_chain_verifies(self, tmp_path: Path) -> None:
        sink = JsonlAuditSink(tmp_path / "audit.jsonl")
        for i in range(5):
            append(sink, f"第 {i} 筆")

        result = verify_chain(sink.read_all())

        assert result.ok is True
        assert result.total == 5

    def test_first_record_links_to_genesis(self, tmp_path: Path) -> None:
        sink = JsonlAuditSink(tmp_path / "audit.jsonl")
        record = append(sink, "第一筆")

        assert record.prev_hash == GENESIS_HASH
        assert record.sequence == 0

    def test_editing_a_row_is_detected_and_located(self, tmp_path: Path) -> None:
        """驗收條件:手動竄改任一列 → 驗證程式能偵測**並指出是哪一列**。"""
        path = tmp_path / "audit.jsonl"
        sink = JsonlAuditSink(path)
        for i in range(5):
            append(sink, f"第 {i} 筆")

        lines = path.read_text(encoding="utf-8").splitlines()
        row = json.loads(lines[2])
        row["note_text"] = "被偷偷改掉的內容"
        lines[2] = json.dumps(row, ensure_ascii=False)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        result = verify_chain(sink.read_all())

        assert result.ok is False
        assert any("第 3 列" in problem and "內容被改過" in problem for problem in result.problems)

    def test_deleting_a_row_is_detected(self, tmp_path: Path) -> None:
        """刪除是最容易被忽略的竄改方式——單看剩下的每一列都完全正確。"""
        path = tmp_path / "audit.jsonl"
        sink = JsonlAuditSink(path)
        for i in range(5):
            append(sink, f"第 {i} 筆")

        lines = path.read_text(encoding="utf-8").splitlines()
        del lines[2]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        result = verify_chain(sink.read_all())

        assert result.ok is False
        assert any("接不上前一列" in problem for problem in result.problems)

    def test_reordering_rows_is_detected(self, tmp_path: Path) -> None:
        path = tmp_path / "audit.jsonl"
        sink = JsonlAuditSink(path)
        for i in range(4):
            append(sink, f"第 {i} 筆")

        lines = path.read_text(encoding="utf-8").splitlines()
        lines[1], lines[2] = lines[2], lines[1]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        result = verify_chain(sink.read_all())

        assert result.ok is False

    def test_recomputing_the_whole_chain_is_not_detected(self, tmp_path: Path) -> None:
        """**誠實記錄這個機制的極限。**

        有寫入權限的人可以把整條鏈重算一次,驗證就會通過。要防這個需要把鏈尾
        定期送到這個系統改不到的地方(外部時間戳、另一個帳號的儲存體)。
        把這件事寫成測試,是為了讓「我們知道這個限制」變成可執行的紀錄,
        而不是只寫在文件裡的一句話。
        """
        path = tmp_path / "audit.jsonl"
        sink = JsonlAuditSink(path)
        for i in range(3):
            append(sink, f"第 {i} 筆")

        rebuilt = []
        prev = GENESIS_HASH
        for i in range(3):
            record = build_record(
                sequence=i,
                prev_hash=prev,
                patient_id=AMY_ID,
                note_text="整段重寫的內容",
                proposed_at="2026-07-25T00:00:00+00:00",
                confirmed_at="2026-07-25T00:00:01+00:00",
                actor="attacker",
                request_id="forged",
            )
            rebuilt.append(record)
            prev = record.row_hash
        path.write_text("\n".join(r.model_dump_json() for r in rebuilt) + "\n", encoding="utf-8")

        assert verify_chain(sink.read_all()).ok is True  # 驗證通過——這是已知限制


class TestConcurrency:
    """併發下不會遺失嗎。

    原本的實作是 ``open("a")`` 加兩次獨立的 write、沒有 flush、沒有任何鎖,
    而 handler 跑在 threadpool 的多個 worker thread 上。
    """

    def test_concurrent_appends_do_not_lose_records(self, tmp_path: Path) -> None:
        sink = JsonlAuditSink(tmp_path / "audit.jsonl")
        total = 50

        with ThreadPoolExecutor(max_workers=16) as pool:
            list(pool.map(lambda i: append(sink, f"併發第 {i} 筆"), range(total)))

        records = sink.read_all()
        assert len(records) == total

    def test_concurrent_appends_produce_a_valid_chain(self, tmp_path: Path) -> None:
        """光是「沒遺失」不夠——併發下若兩個寫入拿到同一個 prev_hash,
        筆數會是對的,但鏈已經分叉了。"""
        sink = JsonlAuditSink(tmp_path / "audit.jsonl")

        with ThreadPoolExecutor(max_workers=16) as pool:
            list(pool.map(lambda i: append(sink, f"併發第 {i} 筆"), range(50)))

        result = verify_chain(sink.read_all())

        assert result.ok is True, result.summary()

    def test_sequences_are_unique_and_contiguous(self, tmp_path: Path) -> None:
        sink = JsonlAuditSink(tmp_path / "audit.jsonl")

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda i: append(sink, f"第 {i} 筆"), range(30)))

        sequences = [r.sequence for r in sink.read_all()]
        assert sequences == list(range(30))


class TestOptionalDatabase:
    """必須可選:拔掉 DATABASE_URL 服務仍能啟動並退回檔案模式。

    這是這個 Phase 最重要的驗收條件——它是專案能當 demo、能上 HF Space 的前提。
    """

    def test_falls_back_to_jsonl_without_database_url(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DATABASE_URL", raising=False)

        sink = resolve_audit_sink(tmp_path / "audit.jsonl")

        assert sink.backend == "jsonl"

    def test_missing_driver_fails_loudly_instead_of_silently_using_files(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """設定了 DATABASE_URL 但沒裝 postgres extra 時要**炸掉**,不能默默退回檔案。

        默默降級會讓人以為紀錄進了資料庫,其實在檔案裡——稽核軌跡的位置不能靠猜。

        這個測試同時守住另一件事:CI 的 check job 為了讓 mypy 看得到 psycopg 而
        安裝了 extra,所以「沒裝 extra 會怎樣」在那個環境下驗不到。這裡用假的
        import 失敗把那條路徑補回來。
        """
        import builtins

        monkeypatch.setenv("DATABASE_URL", "postgresql://x/y")
        real_import = builtins.__import__

        def fail_on_psycopg(name: str, *args: Any, **kwargs: Any) -> Any:
            if name.startswith("psycopg") or name.endswith("audit.postgres"):
                raise ImportError("No module named 'psycopg'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fail_on_psycopg)
        monkeypatch.delitem(
            __import__("sys").modules, "fhir_copilot.ops.audit.postgres", raising=False
        )

        with pytest.raises(RuntimeError, match="postgres extra"):
            resolve_audit_sink(tmp_path / "audit.jsonl")

    def test_empty_database_url_is_treated_as_unset(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """空字串是設定檔常見的「我沒有要設定」寫法(docker-compose 的
        ``${DATABASE_URL:-}``),不該被當成一個真的連線字串。"""
        monkeypatch.setenv("DATABASE_URL", "   ")

        assert resolve_audit_sink(tmp_path / "audit.jsonl").backend == "jsonl"


@pytest.fixture
def make_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[ClientFactory]:
    clients: list[TestClient] = []

    def factory() -> TestClient:
        monkeypatch.setenv("FHIR_COPILOT_DATA_DIR", str(FIXTURES_DIR))
        monkeypatch.setenv("FHIR_COPILOT_PROVIDER", "mock")
        monkeypatch.setenv("FHIR_COPILOT_AUDIT_LOG_PATH", str(tmp_path / "care_notes.jsonl"))
        monkeypatch.delenv("DATABASE_URL", raising=False)
        clear_ops_env(monkeypatch)
        monkeypatch.setenv("FHIR_COPILOT_OPS_CONFIG", str(write_ops_config(tmp_path / "ops.yaml")))
        dependencies.reset_caches()
        client = TestClient(create_app())
        clients.append(client)
        return client

    yield factory
    for client in clients:
        client.close()
    dependencies.reset_caches()


class TestOverHttp:
    def test_full_propose_confirm_flow_writes_a_verifiable_record(
        self, make_client: ClientFactory, tmp_path: Path
    ) -> None:
        client = make_client()

        proposed = client.post(
            "/api/care-notes/propose", json={"patient_id": AMY_ID, "note_text": "訪視記錄"}
        )
        assert proposed.status_code == 200
        draft = proposed.json()["draft"]
        assert draft["signature"]

        confirmed = client.post("/api/care-notes/confirm", json={"draft": draft})
        assert confirmed.status_code == 200

        records = JsonlAuditSink(tmp_path / "care_notes.jsonl").read_all()
        assert len(records) == 1
        assert records[0].note_text == "訪視記錄"
        assert records[0].actor == "anonymous"
        assert records[0].request_id  # 串得回是哪一次請求
        assert verify_chain(records).ok is True

    def test_forged_draft_is_rejected_with_400_not_500(
        self, make_client: ClientFactory, tmp_path: Path
    ) -> None:
        """client 送了無效的東西,不是伺服器壞掉。"""
        client = make_client()

        response = client.post(
            "/api/care-notes/confirm",
            json={
                "draft": {
                    "patient_id": AMY_ID,
                    "note_text": "偽造的記錄",
                    "proposed_at": "2020-01-01T00:00:00+00:00",
                    "signature": "b" * 64,
                }
            },
        )

        assert response.status_code == 400
        assert JsonlAuditSink(tmp_path / "care_notes.jsonl").read_all() == []

    def test_health_reports_the_audit_backend(self, make_client: ClientFactory) -> None:
        """三種降級狀態都要在 /api/health 看得到,不能靠猜。"""
        body = make_client().get("/api/health").json()

        assert body["audit_backend"] == "jsonl"
        assert body["budget_persistent"] is False
        assert body["draft_signing_key_configured"] is False
