"""get_patient_demographics 單元測試。"""

from fhir_copilot.store import LocalBundleFHIRStore
from fhir_copilot.tools import GetPatientDemographicsInput, get_patient_demographics
from fhir_copilot.tools.base import ToolErrorCode
from tests.conftest import AMY_ID


def test_returns_demographics_with_evidence(store: LocalBundleFHIRStore) -> None:
    result = get_patient_demographics(store, GetPatientDemographicsInput(patient_id=AMY_ID))

    assert result.ok is True
    assert result.error is None
    assert result.demographics is not None
    assert result.demographics.name == "Amy002 Fixture001"
    assert result.demographics.gender == "female"
    assert result.demographics.birth_date == "1948-03-15"
    assert len(result.evidence) == 3
    assert all(e.resource_type == "Patient" and e.resource_id == AMY_ID for e in result.evidence)


def test_unknown_patient_returns_structured_error(store: LocalBundleFHIRStore) -> None:
    result = get_patient_demographics(store, GetPatientDemographicsInput(patient_id="no-such"))

    assert result.ok is False
    assert result.error == ToolErrorCode.PATIENT_NOT_FOUND
    assert result.demographics is None
    assert result.evidence == []
