"""PII 遮蔽的 grep 斷言(營運層 Phase 2)。

領域理由:日誌與 trace 會經手病患資料。**加了 tracing 卻讓病患姓名進 log,
比不加還糟**——原本資料只在記憶體裡待一次請求的時間,現在它會被寫進檔案、
送到 collector、留在別人的儲存空間裡。

**遮蔽最容易變成「有寫但沒效」**,所以這裡不驗證「遮蔽函式回傳什麼」,而是
實際跑完整條請求、把**所有**日誌與 span 輸出抓下來,對真實的病患值做 grep。
只要有任何一條路徑漏了,這個測試就會紅。

fixture 病患是 ``Amy002 Fixture001``(id ``a1000000-...``),值取自
``tests/data/fixtures``,不是寫死的假值——如果 fixture 換人,斷言跟著換。
"""

import hashlib
import json
import logging
from collections.abc import Iterator
from io import StringIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fhir_copilot.api import dependencies
from fhir_copilot.api.app import create_app
from fhir_copilot.ops import tracing
from fhir_copilot.ops.logging import JsonFormatter
from fhir_copilot.ops.redaction import hash_patient_id
from tests.conftest import AMY_ID, FIXTURES_DIR, clear_ops_env, write_ops_config

# 這位病患的真實識別資訊——底下所有輸出都不准出現這些值
AMY_GIVEN = "Amy002"
AMY_FAMILY = "Fixture001"
SECRET_NOTE = "這是一段不該出現在任何日誌裡的照護記錄內容"
SECRET_QUESTION = "他目前有在吃什麼藥?請把細節都列出來"


class Captured:
    """一次完整請求所產生的全部可觀測輸出。"""

    def __init__(self, logs: str, spans: list[dict[str, object]]) -> None:
        self.logs = logs
        self.spans = spans

    @property
    def everything(self) -> str:
        """日誌 + span 全部攤成一個字串,用來做 grep 斷言。"""
        return self.logs + "\n" + json.dumps(self.spans, ensure_ascii=False)


@pytest.fixture
def capture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Captured]:
    """跑一次完整的 chat + care-note 流程,捕捉所有日誌與 span。"""
    monkeypatch.setenv("FHIR_COPILOT_DATA_DIR", str(FIXTURES_DIR))
    monkeypatch.setenv("FHIR_COPILOT_PROVIDER", "mock")
    monkeypatch.setenv("FHIR_COPILOT_AUDIT_LOG_PATH", str(tmp_path / "care_notes.jsonl"))
    clear_ops_env(monkeypatch)
    monkeypatch.setenv("FHIR_COPILOT_OPS_CONFIG", str(write_ops_config(tmp_path / "ops.yaml")))

    trace_file = tmp_path / "spans.jsonl"
    monkeypatch.setenv(tracing.TRACE_FILE_ENV, str(trace_file))
    tracing.reset_for_tests()
    dependencies.reset_caches()

    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())

    with TestClient(create_app()) as client:
        # create_app 會重設 root handler,所以要在它之後才掛捕捉用的 handler
        root = logging.getLogger()
        root.addHandler(handler)
        root.setLevel(logging.DEBUG)
        try:
            chat = client.post(
                "/api/chat", json={"patient_id": AMY_ID, "question": SECRET_QUESTION}
            )
            assert chat.status_code == 200
            # 病患摘要會把姓名等欄位真的讀出來,是最容易漏的路徑
            assert client.get(f"/api/patients/{AMY_ID}/summary").status_code == 200
            proposed = client.post(
                "/api/care-notes/propose",
                json={"patient_id": AMY_ID, "note_text": SECRET_NOTE},
            )
            assert proposed.status_code == 200
            draft = proposed.json()["draft"]
            assert client.post("/api/care-notes/confirm", json={"draft": draft}).status_code == 200
        finally:
            root.removeHandler(handler)

    tracing.flush()
    spans = [
        json.loads(line)
        for line in trace_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    yield Captured(stream.getvalue(), spans)

    tracing.reset_for_tests()
    dependencies.reset_caches()


class TestNothingSensitiveLeaks:
    def test_the_run_actually_produced_output(self, capture: Captured) -> None:
        """先確認這個測試有在測東西。

        沒有這一條的話,「日誌是空的」也會讓底下每一條 grep 斷言通過——
        一個永遠是綠的測試比沒有測試更危險。
        """
        assert capture.logs.strip(), "沒有捕捉到任何日誌,底下的斷言會變成空轉"
        assert capture.spans, "沒有捕捉到任何 span,底下的斷言會變成空轉"

    def test_patient_name_never_appears(self, capture: Captured) -> None:
        assert AMY_GIVEN not in capture.everything
        assert AMY_FAMILY not in capture.everything

    def test_raw_note_text_never_appears(self, capture: Captured) -> None:
        assert SECRET_NOTE not in capture.everything

    def test_raw_question_never_appears(self, capture: Captured) -> None:
        assert SECRET_QUESTION not in capture.everything

    def test_full_patient_id_never_appears(self, capture: Captured) -> None:
        """完整 id 不行,雜湊後的短參考可以——後者串得起同一位病患的日誌,
        但反推不回 id,也對不上 FHIR 資源。"""
        assert AMY_ID not in capture.everything

    def test_patient_id_is_not_leaked_through_the_url_path(self, capture: Captured) -> None:
        """``/api/patients/{patient_id}/summary`` 的原始路徑裡就有病患 id。

        指標標籤與 span 屬性一律用 route 樣板而不是原始路徑,正是為了這件事——
        這條斷言鎖住那個決定,免得日後有人「順手」把 url.path 加回去。
        """
        assert "/api/patients/{patient_id}/summary" in capture.everything
        assert f"/api/patients/{AMY_ID}" not in capture.everything


class TestUsefulThingsStillGetLogged:
    """遮蔽不能遮到什麼都不剩——日誌還是要能回答營運問題。"""

    def test_hashed_patient_reference_is_present(self, capture: Captured) -> None:
        """同一位病患的多筆日誌要串得起來,否則出事時查不動。"""
        assert hash_patient_id(AMY_ID) in capture.everything

    def test_patient_reference_is_keyed_not_plain_sha256(self) -> None:
        legacy = hashlib.sha256(AMY_ID.encode("utf-8")).hexdigest()[:8]

        first = hash_patient_id(AMY_ID)

        assert first == hash_patient_id(AMY_ID)
        assert first != legacy

    def test_question_length_is_recorded(self, capture: Captured) -> None:
        """只記形狀不記內容:長度足以看出「有沒有人在打超長輸入」。"""
        assert str(len(SECRET_QUESTION)) in capture.everything

    def test_span_chain_is_complete(self, capture: Captured) -> None:
        """完整鏈路:HTTP → agent → 工具 → provider,四層都要在。"""
        names = {span["name"] for span in capture.spans}

        assert "POST /api/chat" in names
        assert "agent.answer" in names
        assert "provider.start" in names
        assert "provider.continue" in names
        assert any(str(name).startswith("tool.") for name in names)

    def test_spans_share_one_trace_per_request(self, capture: Captured) -> None:
        """同一個請求的 span 要在同一條 trace 上,否則 Jaeger 上看不到鏈路。"""
        chat_spans = [s for s in capture.spans if s["name"] == "POST /api/chat"]
        assert len(chat_spans) == 1
        trace_id = chat_spans[0]["trace_id"]

        agent_spans = [s for s in capture.spans if s["name"] == "agent.answer"]
        assert [s["trace_id"] for s in agent_spans] == [trace_id]
