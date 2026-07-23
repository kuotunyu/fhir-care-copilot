"""get_recent_observations 單元測試(valueQuantity / component / 類別篩選 / limit)。"""

from fhir_copilot.store import LocalBundleFHIRStore
from fhir_copilot.tools import GetRecentObservationsInput, get_recent_observations
from fhir_copilot.tools.base import ToolErrorCode
from tests.conftest import AMY_ID, BEN_ID


def test_sorted_most_recent_first(store: LocalBundleFHIRStore) -> None:
    """Amy 有 4 筆 Observation:2024-11(體重、居住狀況,同日)、2025-03(A1c、血壓,同日)——
    最新的排最前。"""
    result = get_recent_observations(store, GetRecentObservationsInput(patient_id=AMY_ID))

    assert result.ok is True
    assert len(result.observations) == 4
    dates = [o.effective_date for o in result.observations]
    assert all(d is not None for d in dates)
    assert dates == sorted(dates, key=lambda d: d or "", reverse=True)


def test_limit_truncates(store: LocalBundleFHIRStore) -> None:
    result = get_recent_observations(store, GetRecentObservationsInput(patient_id=AMY_ID, limit=1))

    assert result.ok is True
    assert len(result.observations) == 1


def test_value_string_observation_is_not_silently_dropped(store: LocalBundleFHIRStore) -> None:
    """M2 審查發現:valueString(如居住狀況)之前完全沒處理,value_display 會靜默變 None,
    跟「真的沒資料」無法區分——這對長照個案是會漏掉「居無定所」這種事實的安全性問題。"""
    result = get_recent_observations(
        store, GetRecentObservationsInput(patient_id=AMY_ID, category="social-history")
    )

    assert result.ok is True
    assert len(result.observations) == 1
    assert result.observations[0].display == "Housing status"
    assert result.observations[0].value_display == "Patient is homeless"


def test_category_filter(store: LocalBundleFHIRStore) -> None:
    result = get_recent_observations(
        store, GetRecentObservationsInput(patient_id=AMY_ID, category="laboratory")
    )

    assert result.ok is True
    assert len(result.observations) == 1
    assert "A1c" in result.observations[0].display or "Hemoglobin" in result.observations[0].display


def test_component_based_blood_pressure_value_display(store: LocalBundleFHIRStore) -> None:
    result = get_recent_observations(
        store, GetRecentObservationsInput(patient_id=AMY_ID, category="vital-signs")
    )

    bp = next(o for o in result.observations if "Blood Pressure" in o.display)
    assert bp.value_display is not None
    assert "138" in bp.value_display
    assert "84" in bp.value_display


def test_simple_quantity_value_display(store: LocalBundleFHIRStore) -> None:
    result = get_recent_observations(store, GetRecentObservationsInput(patient_id=BEN_ID))

    assert result.ok is True
    assert len(result.observations) == 1
    assert result.observations[0].value_display == "72 /min"


def test_unknown_patient_returns_structured_error(store: LocalBundleFHIRStore) -> None:
    result = get_recent_observations(store, GetRecentObservationsInput(patient_id="no-such"))

    assert result.ok is False
    assert result.error == ToolErrorCode.PATIENT_NOT_FOUND
    assert result.observations == []
