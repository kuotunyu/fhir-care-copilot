"""工具登錄檢查:安全邊界的機械驗證(ADR 0001)。"""

from fhir_copilot.tools import READ_ONLY_TOOLS, TOOLS_BY_NAME

_WRITE_ISH_WORDS = ("write", "update", "delete", "create", "propose", "save")


def test_registry_has_exactly_five_read_only_tools() -> None:
    assert len(READ_ONLY_TOOLS) == 5
    assert set(TOOLS_BY_NAME) == {spec.name for spec in READ_ONLY_TOOLS}


def test_no_write_like_tool_names_registered() -> None:
    """安全邊界的機械檢查:write 類工具不該出現在唯讀 allowlist 裡(ADR 0001)。"""
    for spec in READ_ONLY_TOOLS:
        lowered = spec.name.lower()
        assert not any(word in lowered for word in _WRITE_ISH_WORDS), spec.name
