"""LocalBundleFHIRStore 單元測試(fixture 結構見 tests/data/README.md)。"""

import json
from pathlib import Path
from typing import Any

import pytest

from fhir_copilot.store import LocalBundleFHIRStore, UnknownPatientError
from tests.conftest import AMY_ID, BEN_ID, FIXTURES_DIR


def _minimal_patient_bundle(patient_id: str, family: str, given: str) -> dict[str, Any]:
    return {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": [
            {
                "resource": {
                    "resourceType": "Patient",
                    "id": patient_id,
                    "name": [{"family": family, "given": [given]}],
                }
            }
        ],
    }


class TestIndex:
    def test_lists_only_patient_bundles(self, store: LocalBundleFHIRStore) -> None:
        """hospitalInformation/practitionerInformation/非 bundle 檔案都要被跳過。"""
        summaries = store.list_patients()
        assert [s.patient_id for s in summaries] == [AMY_ID, BEN_ID]

    def test_summary_fields(self, store: LocalBundleFHIRStore) -> None:
        amy = next(s for s in store.list_patients() if s.patient_id == AMY_ID)
        assert amy.name == "Amy002 Fixture001"
        assert amy.gender == "female"
        assert amy.birth_date == "1948-03-15"
        assert amy.source_file == "Amy002_Fixture001_a1000000.json"

    def test_missing_dir_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            LocalBundleFHIRStore(FIXTURES_DIR / "no_such_dir")

    def test_non_utf8_file_is_skipped_not_fatal(self, tmp_path: Path) -> None:
        """M1 審查發現的 HIGH 嚴重度 bug 迴歸測試:非 UTF-8 檔案曾經讓整個 store
        初始化直接炸掉(UnicodeDecodeError 不是 OSError/JSONDecodeError 的子類別,
        沒被 _build_index 的 except 接住),而不是照設計跳過該檔、繼續索引其他病患。"""
        (tmp_path / "good_patient.json").write_text(
            json.dumps(_minimal_patient_bundle("good-1", "Good", "Patient")), encoding="utf-8"
        )
        (tmp_path / "bad_encoding.json").write_bytes(b"\xff\xfe not valid utf-8 bytes")

        store = LocalBundleFHIRStore(tmp_path)

        assert [s.patient_id for s in store.list_patients()] == ["good-1"]

    def test_duplicate_patient_id_keeps_first_file_in_sorted_order(self, tmp_path: Path) -> None:
        (tmp_path / "a_first.json").write_text(
            json.dumps(_minimal_patient_bundle("dup-1", "First", "X")), encoding="utf-8"
        )
        (tmp_path / "b_second.json").write_text(
            json.dumps(_minimal_patient_bundle("dup-1", "Second", "X")), encoding="utf-8"
        )

        store = LocalBundleFHIRStore(tmp_path)
        summaries = store.list_patients()

        assert len(summaries) == 1
        assert summaries[0].source_file == "a_first.json"
        assert summaries[0].name == "X First"

    def test_duplicate_warning_omits_patient_id_and_filename(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        patient_id = "synthetic-sensitive-patient-id"
        second_filename = "b_synthetic_sensitive_name.json"
        (tmp_path / "a_first.json").write_text(
            json.dumps(_minimal_patient_bundle(patient_id, "First", "Synthetic")), encoding="utf-8"
        )
        (tmp_path / second_filename).write_text(
            json.dumps(_minimal_patient_bundle(patient_id, "Second", "Synthetic")), encoding="utf-8"
        )

        with caplog.at_level("WARNING", logger="fhir_copilot.store.local"):
            LocalBundleFHIRStore(tmp_path)

        assert "重複的病患 Patient.id" in caplog.text
        assert patient_id not in caplog.text
        assert second_filename not in caplog.text


class TestGetPatient:
    def test_returns_patient_resource(self, store: LocalBundleFHIRStore) -> None:
        patient = store.get_patient(AMY_ID)
        assert patient["resourceType"] == "Patient"
        assert patient["id"] == AMY_ID

    def test_unknown_patient_raises(self, store: LocalBundleFHIRStore) -> None:
        with pytest.raises(UnknownPatientError):
            store.get_patient("no-such-patient")


class TestGetResources:
    def test_conditions(self, store: LocalBundleFHIRStore) -> None:
        conditions = store.get_resources(AMY_ID, "Condition")
        assert len(conditions) == 2
        statuses = {c["clinicalStatus"]["coding"][0]["code"] for c in conditions}
        assert statuses == {"active", "resolved"}

    def test_medication_requests_cover_both_status_conventions(
        self, store: LocalBundleFHIRStore
    ) -> None:
        """sep2019 樣本用 stopped、v3.4.0+ 用 completed —— 兩種都必須拿得到。"""
        amy_statuses = {m["status"] for m in store.get_resources(AMY_ID, "MedicationRequest")}
        ben_statuses = {m["status"] for m in store.get_resources(BEN_ID, "MedicationRequest")}
        assert amy_statuses == {"active", "stopped"}
        assert ben_statuses == {"active", "completed"}

    def test_unknown_type_returns_empty_list(self, store: LocalBundleFHIRStore) -> None:
        assert store.get_resources(AMY_ID, "DiagnosticReport") == []

    def test_unknown_patient_raises(self, store: LocalBundleFHIRStore) -> None:
        with pytest.raises(UnknownPatientError):
            store.get_resources("no-such-patient", "Condition")


class TestResolveReference:
    def test_urn_uuid_resolves_medication_reference(self, store: LocalBundleFHIRStore) -> None:
        """v3.4.0+/US Core 慣例:medicationReference → bundle 內 Medication resource。"""
        completed = next(
            m
            for m in store.get_resources(BEN_ID, "MedicationRequest")
            if m["status"] == "completed"
        )
        ref = completed["medicationReference"]["reference"]
        medication = store.resolve_reference(BEN_ID, ref)
        assert medication is not None
        assert medication["resourceType"] == "Medication"
        assert medication["code"]["coding"][0]["code"] == "197361"

    def test_type_id_reference_resolves(self, store: LocalBundleFHIRStore) -> None:
        resolved = store.resolve_reference(
            BEN_ID, "Medication/b2000000-0000-0000-0000-000000000002"
        )
        assert resolved is not None
        assert resolved["resourceType"] == "Medication"

    def test_urn_uuid_practitioner_reference_resolves(self, store: LocalBundleFHIRStore) -> None:
        """實測下載的 1K 樣本中最主要的模式:Practitioner 內嵌在 bundle 內、
        用 urn:uuid 正常解析(M1 審查用真實資料校正過)。"""
        encounter = store.get_resources(AMY_ID, "Encounter")[0]
        ref = encounter["participant"][0]["individual"]["reference"]
        assert ref.startswith("urn:uuid:")
        practitioner = store.resolve_reference(AMY_ID, ref)
        assert practitioner is not None
        assert practitioner["resourceType"] == "Practitioner"

    def test_conditional_search_url_returns_none(self, store: LocalBundleFHIRStore) -> None:
        """防禦性行為:conditional search URL 形式的參照容忍、不 raise——
        這個形式在實測下載的 1K 樣本中沒有出現過,是給其他版本/設定的
        Synthea 輸出用的保險,不是這裡的 fixture 資料本身長這樣。"""
        ref = "Practitioner?identifier=http://hl7.org/fhir/sid/us-npi|9999999999"
        assert store.resolve_reference(AMY_ID, ref) is None

    def test_contained_resource_reference_returns_none(self, store: LocalBundleFHIRStore) -> None:
        """`#` 開頭的 contained resource 參照——真實資料裡只出現在
        ExplanationOfBenefit(M1 審查發現),目前沒有工具讀它,一律回傳 None。"""
        assert store.resolve_reference(AMY_ID, "#referral") is None

    def test_unresolvable_and_empty_references_return_none(
        self, store: LocalBundleFHIRStore
    ) -> None:
        assert store.resolve_reference(AMY_ID, "urn:uuid:not-in-bundle") is None
        assert store.resolve_reference(AMY_ID, "Medication/not-in-bundle") is None
        assert store.resolve_reference(AMY_ID, "") is None
