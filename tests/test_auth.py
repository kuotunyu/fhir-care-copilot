"""API key 認證(營運層 Phase 1)。

領域理由:``/api/chat`` 每次呼叫都花真錢,而端點原本完全開放。

這裡鎖住三件事:哪些端點受保護、哪些永遠不受保護、以及沒設定金鑰時的降級行為。
"""

import json
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fhir_copilot.api import dependencies
from fhir_copilot.api.app import create_app
from tests.conftest import AMY_ID, FIXTURES_DIR, clear_ops_env, write_ops_config

VALID_KEY = "test-key-aaa"
HEADER = "X-API-Key"

ClientFactory = Callable[..., TestClient]


@pytest.fixture
def make_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[ClientFactory]:
    clients: list[TestClient] = []

    def factory(*, api_keys: str | None = None, require_auth: bool = False) -> TestClient:
        monkeypatch.setenv("FHIR_COPILOT_DATA_DIR", str(FIXTURES_DIR))
        monkeypatch.setenv("FHIR_COPILOT_PROVIDER", "mock")
        monkeypatch.setenv("FHIR_COPILOT_AUDIT_LOG_PATH", str(tmp_path / "care_notes.jsonl"))
        clear_ops_env(monkeypatch)
        monkeypatch.setenv("FHIR_COPILOT_OPS_CONFIG", str(write_ops_config(tmp_path / "ops.yaml")))
        if api_keys is not None:
            monkeypatch.setenv("FHIR_COPILOT_API_KEYS", api_keys)
        if require_auth:
            monkeypatch.setenv("FHIR_COPILOT_REQUIRE_AUTH", "true")
        dependencies.reset_caches()
        client = TestClient(create_app())
        clients.append(client)
        return client

    yield factory
    for client in clients:
        client.close()
    dependencies.reset_caches()


def as_text(body: object) -> str:
    """把回應 JSON 攤成字串,用來斷言某個值「完全沒有出現在裡面」。"""
    return json.dumps(body, ensure_ascii=False)


class TestRequireAuthEnabled:
    def test_missing_key_is_rejected(self, make_client: ClientFactory) -> None:
        client = make_client(api_keys=f"demo:{VALID_KEY}", require_auth=True)

        response = client.post("/api/chat", json={"patient_id": AMY_ID, "question": "藥?"})

        assert response.status_code == 401
        body = response.json()
        assert body["error_code"] == "missing_api_key"
        # detail 必須是字串:前端 api.ts 直接拿它顯示,塞 dict 會變 [object Object]
        assert isinstance(body["detail"], str)

    def test_wrong_key_is_rejected(self, make_client: ClientFactory) -> None:
        client = make_client(api_keys=f"demo:{VALID_KEY}", require_auth=True)

        response = client.post(
            "/api/chat",
            json={"patient_id": AMY_ID, "question": "藥?"},
            headers={HEADER: "not-the-key"},
        )

        assert response.status_code == 401
        assert response.json()["error_code"] == "invalid_api_key"

    def test_valid_key_is_accepted(self, make_client: ClientFactory) -> None:
        client = make_client(api_keys=f"demo:{VALID_KEY}", require_auth=True)

        response = client.post(
            "/api/chat",
            json={"patient_id": AMY_ID, "question": "他在吃什麼藥?"},
            headers={HEADER: VALID_KEY},
        )

        assert response.status_code == 200
        assert response.json()["refused"] is False

    def test_requiring_auth_without_any_key_configured_fails_closed(
        self, make_client: ClientFactory
    ) -> None:
        """設定矛盾時擋下來,不是放行。

        明確要求認證卻沒有任何金鑰可用是設定錯誤;這種情況 fail open 等於
        「以為有保護,其實沒有」,比直接壞掉危險得多。
        """
        client = make_client(require_auth=True)

        response = client.post("/api/chat", json={"patient_id": AMY_ID, "question": "藥?"})

        assert response.status_code == 401


class TestDemoModeFallback:
    """沒設環境變數服務也要能跑——與 provider 缺金鑰自動退回 mock 同一個哲學。"""

    def test_no_keys_configured_lets_everything_through(self, make_client: ClientFactory) -> None:
        client = make_client()

        response = client.post(
            "/api/chat", json={"patient_id": AMY_ID, "question": "他在吃什麼藥?"}
        )

        assert response.status_code == 200

    def test_wrong_key_is_still_rejected_even_in_demo_mode(
        self, make_client: ClientFactory
    ) -> None:
        """有設定金鑰時,帶錯金鑰一律 401,不默默降級成匿名。

        呼叫者帶了金鑰就表示他想認證;默默當成匿名放行只會讓人搞不清楚
        自己到底有沒有通過認證。
        """
        client = make_client(api_keys=f"demo:{VALID_KEY}")

        response = client.post(
            "/api/chat",
            json={"patient_id": AMY_ID, "question": "藥?"},
            headers={HEADER: "wrong"},
        )

        assert response.status_code == 401


class TestWhichEndpointsAreProtected:
    def test_health_is_never_authenticated(self, make_client: ClientFactory) -> None:
        """健康檢查被認證擋住的話,它就不再是健康檢查了。"""
        client = make_client(api_keys=f"demo:{VALID_KEY}", require_auth=True)

        response = client.get("/api/health")

        assert response.status_code == 200

    def test_health_reports_auth_state(self, make_client: ClientFactory) -> None:
        client = make_client(api_keys=f"demo:{VALID_KEY},ops:other", require_auth=True)

        body = client.get("/api/health").json()

        assert body["auth_required"] is True
        assert body["api_key_count"] == 2
        # 金鑰本身永遠不出現在回應裡——只回數量
        assert VALID_KEY not in as_text(body)

    def test_health_reports_demo_mode_when_auth_is_off(self, make_client: ClientFactory) -> None:
        body = make_client().get("/api/health").json()

        assert body["auth_required"] is False
        assert body["api_key_count"] == 0

    @pytest.mark.parametrize("path", ["/api/patients", f"/api/patients/{AMY_ID}/summary"])
    def test_patient_bearing_read_endpoints_require_valid_key_when_auth_is_enabled(
        self, make_client: ClientFactory, path: str
    ) -> None:
        """Patient-bearing read routes 與 chat 使用相同 authentication boundary。"""
        client = make_client(api_keys=f"demo:{VALID_KEY}", require_auth=True)

        assert client.get(path).status_code == 401
        assert client.get(path, headers={HEADER: "wrong"}).status_code == 401
        assert client.get(path, headers={HEADER: VALID_KEY}).status_code == 200

    def test_providers_remains_public(self, make_client: ClientFactory) -> None:
        client = make_client(api_keys=f"demo:{VALID_KEY}", require_auth=True)

        assert client.get("/api/providers").status_code == 200

    @pytest.mark.parametrize("path", ["/api/patients", f"/api/patients/{AMY_ID}/summary"])
    def test_patient_bearing_read_endpoints_remain_public_when_auth_is_disabled(
        self, make_client: ClientFactory, path: str
    ) -> None:
        client = make_client(api_keys=f"demo:{VALID_KEY}")

        assert client.get(path).status_code == 200
        assert client.get(path, headers={HEADER: "wrong"}).status_code == 200

    def test_care_note_endpoints_are_protected(self, make_client: ClientFactory) -> None:
        """care-note 不花錢,但它是唯一會寫入的路徑,所以一樣要認證。"""
        client = make_client(api_keys=f"demo:{VALID_KEY}", require_auth=True)

        propose = client.post(
            "/api/care-notes/propose", json={"patient_id": AMY_ID, "note_text": "測試"}
        )
        confirm = client.post(
            "/api/care-notes/confirm",
            json={"draft": {"patient_id": AMY_ID, "note_text": "測試", "proposed_at": "x"}},
        )

        assert propose.status_code == 401
        assert confirm.status_code == 401
