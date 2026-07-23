"""list_active_conditions 單元測試。"""

from fhir_copilot.store import LocalBundleFHIRStore
from fhir_copilot.tools import ListActiveConditionsInput, list_active_conditions
from fhir_copilot.tools.base import ToolErrorCode
from tests.conftest import AMY_ID, BEN_ID


def test_only_active_condition_returned_resolved_excluded(store: LocalBundleFHIRStore) -> None:
    """Amy 有 1 個 active(糖尿病)+ 1 個 resolved(咽炎)——resolved 不該出現。"""
    result = list_active_conditions(store, ListActiveConditionsInput(patient_id=AMY_ID))

    assert result.ok is True
    assert len(result.conditions) == 1
    assert "Diabetes" in result.conditions[0].display
    assert result.conditions[0].code_system == "http://snomed.info/sct"
    assert len(result.evidence) == 1
    assert result.evidence[0].resource_type == "Condition"


def test_patient_with_condition_returns_it(store: LocalBundleFHIRStore) -> None:
    result = list_active_conditions(store, ListActiveConditionsInput(patient_id=BEN_ID))

    assert result.ok is True
    assert len(result.conditions) == 1
    assert "hypertension" in result.conditions[0].display.lower()


def test_unknown_patient_returns_structured_error(store: LocalBundleFHIRStore) -> None:
    result = list_active_conditions(store, ListActiveConditionsInput(patient_id="no-such"))

    assert result.ok is False
    assert result.error == ToolErrorCode.PATIENT_NOT_FOUND
    assert result.conditions == []
