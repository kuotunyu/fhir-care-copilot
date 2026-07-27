"""list_allergies 單元測試(fixture 資料,見 tests/data/fixtures/README 說明)。

**fixture 刻意涵蓋真實語料沒有的組合。** 實測 subset_100:100 位病患中 14 位有
AllergyIntolerance、共 60 筆,但其中**藥物過敏 0 筆、high criticality 0 筆、
reaction 0 筆、refuted 0 筆**——全是 low criticality 的食物/環境過敏原。

也就是說,只靠真實資料跑,這個工具處理「盤尼西林過敏、高危險、有呼吸困難反應」
的那條路徑一次都不會被執行到。而那正是這個工具存在的理由。
"""

from __future__ import annotations

from fhir_copilot.store import LocalBundleFHIRStore
from fhir_copilot.tools import ListAllergiesInput, ToolErrorCode, list_allergies
from tests.conftest import AMY_ID, BEN_ID


def _by_display(store: LocalBundleFHIRStore, patient_id: str) -> dict[str, object]:
    result = list_allergies(store, ListAllergiesInput(patient_id=patient_id))
    return {a.display: a for a in result.allergies}


def test_unknown_patient_is_structured_error(store: LocalBundleFHIRStore) -> None:
    result = list_allergies(store, ListAllergiesInput(patient_id="nope"))

    assert result.ok is False
    assert result.error == ToolErrorCode.PATIENT_NOT_FOUND
    assert result.allergies == []


def test_patient_without_allergies_returns_empty_not_error(store: LocalBundleFHIRStore) -> None:
    """Ben 沒有過敏紀錄——那是**可驗證的事實**,不是查詢失敗。

    ok=True + 空清單,與 ok=False 是兩件完全不同的事(tools/base.py 的語意定義)。
    在過敏這件事上尤其重要:「查過,沒有」才能支持「可以開這個藥」。
    """
    result = list_allergies(store, ListAllergiesInput(patient_id=BEN_ID))

    assert result.ok is True
    assert result.error is None
    assert result.allergies == []
    assert result.evidence == []


def test_returns_every_record_with_evidence(store: LocalBundleFHIRStore) -> None:
    result = list_allergies(store, ListAllergiesInput(patient_id=AMY_ID))

    assert result.ok is True
    assert len(result.allergies) == 5
    assert len(result.evidence) == 5
    assert all(e.resource_type == "AllergyIntolerance" for e in result.evidence)


class TestDoesNotFilterByStatus:
    """**這是這個工具與其他資料工具最重要的差異。**

    conditions/medications 只回 active,因為「已解決的診斷」不是目前的診斷。
    過敏不一樣:inactive 的意思是「目前不認為有風險」,不是「這件事沒發生過」;
    refuted 的意思是「查過、確認沒有」,那與「沒有紀錄」是兩件事。

    在「不能給他什麼」這個問題上,漏掉一筆與多給一筆的代價完全不對稱。
    """

    def test_inactive_record_is_returned_and_labelled(self, store: LocalBundleFHIRStore) -> None:
        allergies = _by_display(store, AMY_ID)

        grass = allergies["Allergy to grass pollen"]
        assert grass.clinical_status == "inactive"  # type: ignore[attr-defined]

    def test_refuted_record_is_returned_and_labelled(self, store: LocalBundleFHIRStore) -> None:
        allergies = _by_display(store, AMY_ID)

        sulfa = allergies["Allergy to sulfonamide"]
        assert sulfa.verification_status == "refuted"  # type: ignore[attr-defined]
        assert sulfa.clinical_status == "active"  # type: ignore[attr-defined]

    def test_evidence_points_at_the_unfiltered_field(self, store: LocalBundleFHIRStore) -> None:
        """evidence 指向 clinicalStatus——**那正是沒有被過濾掉的那一欄**,
        值得讓人逐筆核對「為什麼這筆也回來了」。"""
        result = list_allergies(store, ListAllergiesInput(patient_id=AMY_ID))

        fields = {e.field for e in result.evidence}
        values = {e.value for e in result.evidence}
        assert fields == {"clinicalStatus"}
        assert values == {"active", "inactive"}


class TestClinicallyImportantFields:
    """真實語料一次都測不到的那些路徑。"""

    def test_medication_allergy_with_high_criticality(self, store: LocalBundleFHIRStore) -> None:
        penicillin = _by_display(store, AMY_ID)["Allergy to penicillin"]

        assert penicillin.categories == ["medication"]  # type: ignore[attr-defined]
        assert penicillin.criticality == "high"  # type: ignore[attr-defined]
        assert penicillin.type == "allergy"  # type: ignore[attr-defined]

    def test_reaction_manifestations_are_surfaced(self, store: LocalBundleFHIRStore) -> None:
        """「會怎樣」跟「對什麼過敏」一樣重要:蕁麻疹與呼吸困難是不同等級的事。"""
        penicillin = _by_display(store, AMY_ID)["Allergy to penicillin"]

        assert penicillin.reactions == ["Wheal", "Dyspnea"]  # type: ignore[attr-defined]

    def test_intolerance_is_distinguished_from_allergy(self, store: LocalBundleFHIRStore) -> None:
        """乳糖不耐不是免疫反應,把它講成「過敏」會誤導臨床判斷。"""
        lactose = _by_display(store, AMY_ID)["Lactose intolerance"]

        assert lactose.type == "intolerance"  # type: ignore[attr-defined]
        assert lactose.verification_status == "unconfirmed"  # type: ignore[attr-defined]

    def test_record_without_reaction_returns_empty_list_not_none(
        self, store: LocalBundleFHIRStore
    ) -> None:
        peanuts = _by_display(store, AMY_ID)["Allergy to peanuts"]

        assert peanuts.reactions == []  # type: ignore[attr-defined]
        assert peanuts.criticality == "low"  # type: ignore[attr-defined]
