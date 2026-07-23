"""propose_care_note / confirm_and_log 單元測試(PLAN.md M3)。"""

import json
from pathlib import Path

from fhir_copilot.care_notes import (
    ProposeCareNoteInput,
    confirm_and_log,
    propose_care_note,
)
from fhir_copilot.store import LocalBundleFHIRStore
from fhir_copilot.tools import READ_ONLY_TOOLS, TOOLS_BY_NAME
from fhir_copilot.tools.base import ToolErrorCode
from tests.conftest import AMY_ID


def test_propose_returns_draft_without_writing_anything(store: LocalBundleFHIRStore) -> None:
    result = propose_care_note(
        store, ProposeCareNoteInput(patient_id=AMY_ID, note_text="今日狀況穩定。")
    )

    assert result.ok is True
    assert result.draft is not None
    assert result.draft.patient_id == AMY_ID
    assert result.draft.note_text == "今日狀況穩定。"
    assert result.draft.proposed_at  # 有填時間戳記


def test_propose_unknown_patient_returns_structured_error(
    store: LocalBundleFHIRStore,
) -> None:
    result = propose_care_note(store, ProposeCareNoteInput(patient_id="no-such", note_text="x"))

    assert result.ok is False
    assert result.error == ToolErrorCode.PATIENT_NOT_FOUND
    assert result.draft is None


def test_confirm_and_log_appends_jsonl(store: LocalBundleFHIRStore, tmp_path: Path) -> None:
    audit_log = tmp_path / "care_notes.jsonl"
    result = propose_care_note(
        store, ProposeCareNoteInput(patient_id=AMY_ID, note_text="第一筆記錄")
    )
    assert result.draft is not None

    confirmed = confirm_and_log(result.draft, audit_log_path=audit_log)

    assert confirmed.confirmed_at
    lines = audit_log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    logged = json.loads(lines[0])
    assert logged["patient_id"] == AMY_ID
    assert logged["note_text"] == "第一筆記錄"


def test_confirm_and_log_appends_not_overwrites(
    store: LocalBundleFHIRStore, tmp_path: Path
) -> None:
    audit_log = tmp_path / "care_notes.jsonl"
    for text in ("第一筆", "第二筆"):
        draft = propose_care_note(
            store, ProposeCareNoteInput(patient_id=AMY_ID, note_text=text)
        ).draft
        assert draft is not None
        confirm_and_log(draft, audit_log_path=audit_log)

    lines = audit_log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["note_text"] == "第一筆"
    assert json.loads(lines[1])["note_text"] == "第二筆"


def test_propose_care_note_is_not_reachable_from_read_only_agent_loop() -> None:
    """安全邊界(ADR 0001):propose_care_note 不在唯讀問答 loop 的工具清單裡,
    不會被對話中的 LLM 意外觸發——它是給 M4 UI 直接呼叫的獨立動作路徑。"""
    names = {spec.name for spec in READ_ONLY_TOOLS}
    assert "propose_care_note" not in names
    assert "propose_care_note" not in TOOLS_BY_NAME
