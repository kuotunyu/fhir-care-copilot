"""get_care_plan_timeline 單元測試(含「找到病患但清單為空」的合法空結果)。"""

from fhir_copilot.store import LocalBundleFHIRStore
from fhir_copilot.tools import GetCarePlanTimelineInput, get_care_plan_timeline
from fhir_copilot.tools.base import ToolErrorCode
from tests.conftest import AMY_ID, BEN_ID


def test_amy_care_plan_with_activities(store: LocalBundleFHIRStore) -> None:
    result = get_care_plan_timeline(store, GetCarePlanTimelineInput(patient_id=AMY_ID))

    assert result.ok is True
    assert len(result.care_plans) == 1
    plan = result.care_plans[0]
    assert plan.status == "active"
    assert plan.period_start == "2015-06-01T09:00:00+08:00"
    assert set(plan.activities) == {"Diabetic diet", "Exercise therapy"}
    assert len(result.evidence) == 1


def test_patient_found_but_no_care_plans_is_valid_empty_not_error(
    store: LocalBundleFHIRStore,
) -> None:
    """Ben 存在但沒有 CarePlan——ok=True 加空 list,不是 insufficient 錯誤。"""
    result = get_care_plan_timeline(store, GetCarePlanTimelineInput(patient_id=BEN_ID))

    assert result.ok is True
    assert result.error is None
    assert result.care_plans == []


def test_unknown_patient_returns_structured_error(store: LocalBundleFHIRStore) -> None:
    result = get_care_plan_timeline(store, GetCarePlanTimelineInput(patient_id="no-such"))

    assert result.ok is False
    assert result.error == ToolErrorCode.PATIENT_NOT_FOUND
    assert result.care_plans == []
