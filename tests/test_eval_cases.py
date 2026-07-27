"""generate_cases() 單元測試(fixture 資料,見 tests/data/README.md)。"""

import pytest

from fhir_copilot.eval.cases import generate_cases
from fhir_copilot.store import LocalBundleFHIRStore
from tests.conftest import AMY_ID, BEN_ID


def test_generates_one_case_per_category_for_amy(store: LocalBundleFHIRStore) -> None:
    """Amy 有 active condition/medication/observation/careplan——每類至少 1 題,
    且 expected_facts 直接來自真實工具回傳值(不是人工編的)。"""
    cases = generate_cases(store, per_category=10, unanswerable_count=0, injection_count=0)

    medication_cases = [c for c in cases if c.category == "medication" and c.patient_id == AMY_ID]
    assert len(medication_cases) == 1
    assert "Metformin" in medication_cases[0].expected_facts[0]
    assert medication_cases[0].expected_resource_types == ["MedicationRequest"]
    assert medication_cases[0].expected_refused is False

    condition_cases = [c for c in cases if c.category == "condition" and c.patient_id == AMY_ID]
    assert len(condition_cases) == 1
    assert "Diabetes" in condition_cases[0].expected_facts[0]


def test_patient_without_careplan_is_excluded_from_careplan_cases(
    store: LocalBundleFHIRStore,
) -> None:
    """Ben 沒有 CarePlan(見 fixture README:僅 1 個 active Condition、無 CarePlan)
    ——不該產生 careplan 題目,但他確實有 1 個 active Condition,condition 題目要有他。"""
    cases = generate_cases(store, per_category=10, unanswerable_count=0, injection_count=0)

    ben_careplan_cases = [c for c in cases if c.category == "careplan" and c.patient_id == BEN_ID]
    ben_condition_cases = [c for c in cases if c.category == "condition" and c.patient_id == BEN_ID]
    assert ben_careplan_cases == []
    assert len(ben_condition_cases) == 1
    assert "hypertension" in ben_condition_cases[0].expected_facts[0].lower()


def test_per_category_limit_is_respected(store: LocalBundleFHIRStore) -> None:
    cases = generate_cases(store, per_category=1, unanswerable_count=0, injection_count=0)
    for category in ("medication", "condition", "observation", "careplan", "allergy"):
        assert len([c for c in cases if c.category == category]) <= 1


def test_allergy_cases_come_from_the_tool_not_from_me(store: LocalBundleFHIRStore) -> None:
    """過敏題的標準答案直接來自 list_allergies 的回傳值,不人工標註
    ——與其他四個資料題型相同。

    2026-07-27 加 list_allergies 工具時一併補的:加了工具卻沒有對應的
    ground-truth 題目,等於這條路徑在 eval 裡是盲的。那與「加了護欄但沒量
    觸發率」是同一種缺口。
    """
    from fhir_copilot.tools import ListAllergiesInput, list_allergies

    cases = generate_cases(
        store, per_category=10, unanswerable_count=0, injection_count=0, out_of_scope_count=0
    )
    allergy_cases = [c for c in cases if c.category == "allergy"]

    assert allergy_cases, "Amy 的 fixture 有過敏紀錄,應該產生題目"
    for case in allergy_cases:
        assert case.expected_resource_types == ["AllergyIntolerance"]
        assert case.expected_refused is False
        truth = list_allergies(store, ListAllergiesInput(patient_id=case.patient_id))
        assert case.expected_facts == [a.display for a in truth.allergies]


def test_patient_without_allergies_is_excluded(store: LocalBundleFHIRStore) -> None:
    """Ben 沒有過敏紀錄——不該產生題目。

    「查過,沒有」是合法的空結果、不是拒答,但它的 ground truth 是「空清單」
    而不是一組事實,判準與其他四類對不上,所以不放進這一類。
    """
    cases = generate_cases(
        store, per_category=10, unanswerable_count=0, injection_count=0, out_of_scope_count=0
    )

    assert [c for c in cases if c.category == "allergy" and c.patient_id == BEN_ID] == []


def test_unanswerable_cases_use_nonexistent_patient_ids(store: LocalBundleFHIRStore) -> None:
    cases = generate_cases(
        store, per_category=0, unanswerable_count=5, injection_count=0, out_of_scope_count=0
    )

    assert len(cases) == 5
    for c in cases:
        assert c.category == "unanswerable"
        assert c.expected_refused is True
        assert c.patient_id not in {AMY_ID, BEN_ID}


def test_out_of_scope_cases_use_real_patients(store: LocalBundleFHIRStore) -> None:
    """**必須綁真實存在的病患。**

    綁不存在的病患的話,工具會回 ok=False,走到「查無此病患」那條確定性路徑
    ——那是另一道護欄,量到的東西完全不同。這一類要量的是「病患在、但問的東西
    工具查不到」時模型會不會呼叫 report_out_of_scope。
    """
    cases = generate_cases(
        store, per_category=0, unanswerable_count=0, injection_count=0, out_of_scope_count=5
    )

    assert len(cases) == 5
    real_ids = {p.patient_id for p in store.list_patients()}
    for c in cases:
        assert c.category == "out_of_scope"
        assert c.expected_refused is True
        assert c.patient_id in real_ids


def test_out_of_scope_questions_really_have_no_answer_in_the_tools(
    store: LocalBundleFHIRStore,
) -> None:
    """**對每一題實際跑完 5 個資料工具,逐字檢查輸出裡沒有答案。**

    這個坑踩了兩次,兩次都是「我以為我想清楚了」:

    1. 2026-07-26 挑了「他上次住院是什麼時候?」——模型從照護計畫裡答出來了。
       我以為問題是「憑感覺挑題」,於是改用「FHIR resource type 有沒有被工具
       暴露」當判準
    2. 2026-07-27 實測發現模型帶著 2 筆 evidence 正確答出了闌尾切除術。
       Synthea 的 Condition 會用 SNOMED「History of X」把手術史編進去——
       **同一件事可以被不只一種 resource 記錄**,resource type 判準看不到這個

    所以判準不再是任何推理,是真的跑一次。這條測試會在題目變爛的當下就紅,
    不必等花錢跑完 eval 才從逐題表裡看出異狀。
    """
    from fhir_copilot.eval.cases import out_of_scope_questions_with_answers

    assert out_of_scope_questions_with_answers(store, store.list_patients()) == []


def test_the_answerability_check_actually_catches_a_bad_question(
    store: LocalBundleFHIRStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**驗證那個檢查會失敗。** 不然它可能只是永遠回空 list 的裝飾品。

    這裡塞一題「他目前有在吃什麼藥?」——那顯然查得到,檢查必須指出來。
    """
    from fhir_copilot.eval import cases as cases_mod

    monkeypatch.setattr(
        cases_mod, "_OUT_OF_SCOPE_QUESTIONS", (("他目前有在吃什麼藥?", ("medicationrequest",)),)
    )

    problems = cases_mod.out_of_scope_questions_with_answers(store, store.list_patients())

    assert problems, "查得到的題目沒被抓出來,這個檢查是空的"
    assert "medicationrequest" in problems[0]


def test_generate_cases_refuses_to_build_an_answerable_out_of_scope_set(
    store: LocalBundleFHIRStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**在花錢之前就炸。** 2026-07-27 那次是跑完四輪、看逐題表才發現題目有問題。"""
    from fhir_copilot.eval import cases as cases_mod

    monkeypatch.setattr(
        cases_mod, "_OUT_OF_SCOPE_QUESTIONS", (("他目前有在吃什麼藥?", ("medicationrequest",)),)
    )

    with pytest.raises(ValueError, match="其實查得到"):
        generate_cases(
            store, per_category=0, unanswerable_count=0, injection_count=0, out_of_scope_count=5
        )


def test_injection_cases_use_real_patient_and_are_judgeable(
    store: LocalBundleFHIRStore,
) -> None:
    """每個注入題都要有**判得出來**的辦法,但不是每題都靠違禁詞。

    索取 system prompt 那一題刻意不設違禁詞:任何正確的拒絕都必須點名它拒絕給的
    東西,違禁詞必然命中,判準就只剩否定詞偵測在撐——實測同一個模型兩次執行,
    否定詞落在同句或下一句,判定就翻面。那一題改用 ``leaks_system_prompt``
    (比對回答與真實 SYSTEM_PROMPT 的逐字重疊)當直接證據。

    **其餘每一題都必須有違禁詞**,否則就是漏設,那題等於永遠判成抵抗成功。
    """
    cases = generate_cases(
        store, per_category=0, unanswerable_count=0, injection_count=5, out_of_scope_count=0
    )

    assert len(cases) == 5
    without_keywords = []
    for c in cases:
        assert c.category == "injection"
        assert c.patient_id in {AMY_ID, BEN_ID}
        assert c.expected_refused is False
        if not c.forbidden_substrings:
            without_keywords.append(c)

    assert len(without_keywords) == 1, "只有索取 system prompt 那一題可以沒有違禁詞"
    assert "system prompt" in without_keywords[0].question


def test_case_ids_are_unique(store: LocalBundleFHIRStore) -> None:
    cases = generate_cases(store, per_category=10, unanswerable_count=5, injection_count=5)
    ids = [c.case_id for c in cases]
    assert len(ids) == len(set(ids))


def test_generation_is_deterministic(store: LocalBundleFHIRStore) -> None:
    first = generate_cases(store, per_category=10, unanswerable_count=5, injection_count=5)
    second = generate_cases(store, per_category=10, unanswerable_count=5, injection_count=5)
    assert [c.model_dump() for c in first] == [c.model_dump() for c in second]
