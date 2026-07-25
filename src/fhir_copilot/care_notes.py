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

from fhir_copilot.ops.audit.signing import sign_draft, verify_draft
from fhir_copilot.ops.audit.sinks import AuditSink
from fhir_copilot.store.base import FHIRStore, UnknownPatientError
from fhir_copilot.tools.base import ToolErrorCode

DEFAULT_AUDIT_LOG_PATH = Path("audit_log") / "care_notes.jsonl"


class DraftSignatureError(ValueError):
    """草稿的簽章驗不過——它不是這個系統產生的,或內容被改過。"""


class ProposeCareNoteInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    patient_id: str
    note_text: str


class CareNoteDraft(BaseModel):
    """草稿。``signature`` 證明它是這個系統產生的。

    沒有簽章的話,通過認證的呼叫者仍然可以送出從來沒有經過 ``propose`` 的內容
    (包括自己編的 ``proposed_at``)——防竄改鏈會忠實地保護一筆**一開始就是假的**
    紀錄。認證回答的是「是誰打進來的」,不是「這份草稿是不是這個系統產生的」。
    """

    model_config = ConfigDict(strict=True)

    patient_id: str
    note_text: str
    proposed_at: str
    signature: str


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

    proposed_at = datetime.now(UTC).isoformat()
    draft = CareNoteDraft(
        patient_id=params.patient_id,
        note_text=params.note_text,
        proposed_at=proposed_at,
        signature=sign_draft(
            patient_id=params.patient_id, note_text=params.note_text, proposed_at=proposed_at
        ),
    )
    return ProposeCareNoteResult(ok=True, draft=draft)


class ConfirmedCareNote(BaseModel):
    model_config = ConfigDict(strict=True)

    patient_id: str
    note_text: str
    proposed_at: str
    confirmed_at: str


def confirm_and_log(
    draft: CareNoteDraft,
    *,
    sink: AuditSink,
    actor: str = "unknown",
    request_id: str = "-",
) -> ConfirmedCareNote:
    """UI 明確確認後才呼叫。**先驗簽,再寫入**,且永遠不寫回 FHIR。

    寫入走 ``AuditSink``:append-only、帶 hash chain、併發安全。
    後端是 Postgres 還是 JSONL 由有沒有 ``DATABASE_URL`` 決定,這裡不需要知道。
    """
    if not verify_draft(
        patient_id=draft.patient_id,
        note_text=draft.note_text,
        proposed_at=draft.proposed_at,
        signature=draft.signature,
    ):
        raise DraftSignatureError("草稿簽章驗證失敗")

    confirmed_at = datetime.now(UTC).isoformat()
    sink.append(
        patient_id=draft.patient_id,
        note_text=draft.note_text,
        proposed_at=draft.proposed_at,
        confirmed_at=confirmed_at,
        actor=actor,
        request_id=request_id,
    )
    return ConfirmedCareNote(
        patient_id=draft.patient_id,
        note_text=draft.note_text,
        proposed_at=draft.proposed_at,
        confirmed_at=confirmed_at,
    )
