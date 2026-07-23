"""照護記錄草稿與確認寫入(PLAN.md M3)。

安全邊界(ADR 0001):``propose_care_note`` 只組出草稿,不寫任何東西,也刻意
**不在**唯讀 agent loop 的工具 allowlist 裡(``tools/registry.py``
``READ_ONLY_TOOLS``)——它是獨立於問答對話的動作路徑,供 M4 UI 的「產生照護
記錄草稿」流程直接呼叫,不會被問答用的 LLM 在對話中意外觸發。使用者在 UI
明確按下確認後,才呼叫 ``confirm_and_log`` 寫進本地 audit log(JSONL),
且**永不寫回 FHIR**——FHIRStore 介面本身就沒有任何 write 方法,結構上不可能。
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from fhir_copilot.store.base import FHIRStore, UnknownPatientError
from fhir_copilot.tools.base import ToolErrorCode

DEFAULT_AUDIT_LOG_PATH = Path("audit_log") / "care_notes.jsonl"


class ProposeCareNoteInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    patient_id: str
    note_text: str


class CareNoteDraft(BaseModel):
    model_config = ConfigDict(strict=True)

    patient_id: str
    note_text: str
    proposed_at: str


class ProposeCareNoteResult(BaseModel):
    model_config = ConfigDict(strict=True)

    ok: bool
    error: Literal[ToolErrorCode.PATIENT_NOT_FOUND] | None = None
    draft: CareNoteDraft | None = None


def propose_care_note(store: FHIRStore, params: ProposeCareNoteInput) -> ProposeCareNoteResult:
    """只組出草稿,不寫任何東西——連 audit log 都不碰。"""
    try:
        store.get_patient(params.patient_id)
    except UnknownPatientError:
        return ProposeCareNoteResult(ok=False, error=ToolErrorCode.PATIENT_NOT_FOUND)

    draft = CareNoteDraft(
        patient_id=params.patient_id,
        note_text=params.note_text,
        proposed_at=datetime.now(UTC).isoformat(),
    )
    return ProposeCareNoteResult(ok=True, draft=draft)


class ConfirmedCareNote(BaseModel):
    model_config = ConfigDict(strict=True)

    patient_id: str
    note_text: str
    proposed_at: str
    confirmed_at: str


def confirm_and_log(
    draft: CareNoteDraft, *, audit_log_path: Path = DEFAULT_AUDIT_LOG_PATH
) -> ConfirmedCareNote:
    """UI 明確確認後才呼叫。附加寫入本地 audit log(JSONL),不覆蓋既有紀錄,
    且永遠不寫回 FHIR。"""
    confirmed = ConfirmedCareNote(
        patient_id=draft.patient_id,
        note_text=draft.note_text,
        proposed_at=draft.proposed_at,
        confirmed_at=datetime.now(UTC).isoformat(),
    )
    audit_log_path.parent.mkdir(parents=True, exist_ok=True)
    with audit_log_path.open("a", encoding="utf-8") as f:
        f.write(confirmed.model_dump_json())
        f.write("\n")
    return confirmed
