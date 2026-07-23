"""list_active_medications 單元測試(涵蓋新舊版 status 慣例與兩種藥品編碼形式)。"""

from fhir_copilot.store import LocalBundleFHIRStore
from fhir_copilot.tools import ListActiveMedicationsInput, list_active_medications
from fhir_copilot.tools.base import ToolErrorCode
from tests.conftest import AMY_ID, BEN_ID


def test_amy_only_active_medication_returned_stopped_excluded(
    store: LocalBundleFHIRStore,
) -> None:
    """Amy 的 acetaminophen 是舊版 'stopped' 慣例——必須被排除,只剩 active 的 metformin。"""
    result = list_active_medications(store, ListActiveMedicationsInput(patient_id=AMY_ID))

    assert result.ok is True
    assert len(result.medications) == 1
    assert "Metformin" in result.medications[0].display
    assert result.medications[0].code_system == "http://www.nlm.nih.gov/research/umls/rxnorm"


def test_ben_active_medications_resolve_both_coding_forms(store: LocalBundleFHIRStore) -> None:
    """Ben 有 4 筆 MedicationRequest:completed(排除)、active+medicationCodeableConcept、
    active+medicationReference(關鍵路徑)——active 的兩筆都要正確解析出藥名。"""
    result = list_active_medications(store, ListActiveMedicationsInput(patient_id=BEN_ID))

    assert result.ok is True
    displays = {m.display for m in result.medications}
    assert displays == {
        "Hydrochlorothiazide 25 MG Oral Tablet",
        "Lisinopril 10 MG Oral Tablet",
    }


def test_medication_reference_path_evidence_cites_the_medication_resource(
    store: LocalBundleFHIRStore,
) -> None:
    """M2 審查發現:medicationReference 解析出的藥名,evidence 之前只指向
    MedicationRequest(只證明了 status=active,證不到藥名本身)——現在必須也
    引用實際含有藥名的 Medication resource。"""
    result = list_active_medications(store, ListActiveMedicationsInput(patient_id=BEN_ID))

    # Hydrochlorothiazide(medicationCodeableConcept,自成一體)只需 1 筆 evidence;
    # Lisinopril(medicationReference)需要 2 筆:MedicationRequest.status + Medication.code
    assert len(result.evidence) == 3
    medication_resource_evidence = [e for e in result.evidence if e.resource_type == "Medication"]
    assert len(medication_resource_evidence) == 1
    assert medication_resource_evidence[0].field == "code"
    assert medication_resource_evidence[0].value == "Lisinopril 10 MG Oral Tablet"


def test_unknown_patient_returns_structured_error(store: LocalBundleFHIRStore) -> None:
    result = list_active_medications(store, ListActiveMedicationsInput(patient_id="no-such"))

    assert result.ok is False
    assert result.error == ToolErrorCode.PATIENT_NOT_FOUND
    assert result.medications == []
