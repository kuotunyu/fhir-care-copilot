"""generate_cases() 單元測試(fixture 資料,見 tests/data/README.md)。"""

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
    for category in ("medication", "condition", "observation", "careplan"):
        assert len([c for c in cases if c.category == category]) <= 1


def test_unanswerable_cases_use_nonexistent_patient_ids(store: LocalBundleFHIRStore) -> None:
    cases = generate_cases(store, per_category=0, unanswerable_count=5, injection_count=0)

    assert len(cases) == 5
    for c in cases:
        assert c.category == "unanswerable"
        assert c.expected_refused is True
        assert c.patient_id not in {AMY_ID, BEN_ID}


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
    cases = generate_cases(store, per_category=0, unanswerable_count=0, injection_count=5)

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
