"""FastAPI 路由整合測試(mock provider,tests/data/fixtures 資料)。"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fhir_copilot.api import dependencies
from fhir_copilot.api.app import create_app
from tests.conftest import AMY_ID, FIXTURES_DIR


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("FHIR_COPILOT_DATA_DIR", str(FIXTURES_DIR))
    monkeypatch.setenv("FHIR_COPILOT_PROVIDER", "mock")
    monkeypatch.setenv("FHIR_COPILOT_AUDIT_LOG_PATH", str(tmp_path / "care_notes.jsonl"))
    dependencies.reset_caches()
    with TestClient(create_app()) as test_client:
        yield test_client
    dependencies.reset_caches()


def test_health_reports_demo_mode(client: TestClient) -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["provider"] == "mock"
    assert body["demo_mode"] is True
    assert body["patient_count"] == 2


def test_list_patients_returns_fixture_patients(client: TestClient) -> None:
    response = client.get("/api/patients")

    assert response.status_code == 200
    patient_ids = {p["patient_id"] for p in response.json()["patients"]}
    assert patient_ids == {AMY_ID, "b2000000-0000-0000-0000-000000000001"}


def test_patient_summary_known_patient(client: TestClient) -> None:
    response = client.get(f"/api/patients/{AMY_ID}/summary")

    assert response.status_code == 200
    body = response.json()
    assert body["demographics"]["name"] == "Amy002 Fixture001"
    assert len(body["conditions"]) == 1  # 只有 active,resolved 不算
    assert len(body["medications"]) == 1
    assert len(body["care_plans"]) == 1


def test_patient_summary_unknown_patient_returns_404(client: TestClient) -> None:
    response = client.get("/api/patients/no-such-patient/summary")
    assert response.status_code == 404


def test_chat_returns_agent_response_with_evidence(client: TestClient) -> None:
    response = client.post(
        "/api/chat", json={"patient_id": AMY_ID, "question": "他目前有在吃什麼藥?"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["refused"] is False
    assert "Metformin" in body["answer"]
    assert len(body["evidence"]) >= 1
    assert body["model"] == "mock-deterministic"
    assert body["estimated_cost_usd"] == 0.0


def test_chat_unknown_patient_is_refused_not_http_error(client: TestClient) -> None:
    """拒答是正常的 200 回應(refused=True),不是 HTTP 錯誤——這是應用層語意,
    不是失敗的請求。"""
    response = client.post(
        "/api/chat", json={"patient_id": "no-such-patient", "question": "他叫什麼名字?"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["refused"] is True
    assert body["evidence"] == []


def test_propose_and_confirm_care_note_flow(client: TestClient, tmp_path: Path) -> None:
    propose_response = client.post(
        "/api/care-notes/propose", json={"patient_id": AMY_ID, "note_text": "今日狀況穩定"}
    )
    assert propose_response.status_code == 200
    draft = propose_response.json()["draft"]
    assert draft["patient_id"] == AMY_ID

    confirm_response = client.post("/api/care-notes/confirm", json={"draft": draft})
    assert confirm_response.status_code == 200
    confirmed = confirm_response.json()
    assert confirmed["note_text"] == "今日狀況穩定"

    audit_log = tmp_path / "care_notes.jsonl"
    assert audit_log.exists()
    assert len(audit_log.read_text(encoding="utf-8").splitlines()) == 1


def test_propose_care_note_unknown_patient_returns_404(client: TestClient) -> None:
    response = client.post(
        "/api/care-notes/propose", json={"patient_id": "no-such", "note_text": "x"}
    )
    assert response.status_code == 404


def test_list_providers_returns_configured_model_ids(client: TestClient) -> None:
    response = client.get("/api/providers")

    assert response.status_code == 200
    body = response.json()
    assert body["mock"] == "mock-deterministic"
    assert body["gemini"] == "gemini-3.1-flash-lite"
    assert body["openai"] == "gpt-5.4-mini"
