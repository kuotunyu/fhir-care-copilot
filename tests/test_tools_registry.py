"""工具登錄檢查:安全邊界的機械驗證(ADR 0001)。"""

from typing import cast

from fhir_copilot.store.base import FHIRStore
from fhir_copilot.tools import READ_ONLY_TOOLS, TOOLS_BY_NAME

_WRITE_ISH_WORDS = ("write", "update", "delete", "create", "propose", "save")


def test_registry_has_exactly_five_patient_data_tools() -> None:
    """會去查病患資料的工具**恰好五個**。

    這個數字是安全邊界的一部分,不是統計:allowlist 就是 agent 能做的事的
    全集。多一個就是多一條資料出口,應該有人在 code review 時看到這一行變動。

    2026-07-26 新增 ``report_out_of_scope`` 時,這條測試從「總共五個」改成
    「查資料的五個」——**新增的那個一筆資料都不查**(見 tools/out_of_scope.py),
    所以資料出口的數量沒有改變。改測試的理由要寫在這裡,不是默默把 5 改成 6。
    """
    data_tools = [spec for spec in READ_ONLY_TOOLS if spec.queries_patient_data]
    assert len(data_tools) == 5
    assert set(TOOLS_BY_NAME) == {spec.name for spec in READ_ONLY_TOOLS}


def test_the_only_non_data_tool_is_the_out_of_scope_declaration() -> None:
    """不查資料的工具只准有那一個。

    ``queries_patient_data=False`` 是個方便的旗標,但它也是個後門:任何人都能
    加一個「不查資料」的工具進 allowlist 而不被上面那條測試擋到。所以這裡逐一
    點名——要再加一個,得先改這行,而改這行會被看見。
    """
    non_data = [spec.name for spec in READ_ONLY_TOOLS if not spec.queries_patient_data]
    assert non_data == ["report_out_of_scope"]


def test_the_out_of_scope_tool_returns_no_evidence() -> None:
    """它不查資料,就不該產生任何證據——否則拒答會掛著不支持它的 evidence。"""
    from fhir_copilot.tools.out_of_scope import ReportOutOfScopeInput, report_out_of_scope

    # 傳 None 進去也不會炸,正好說明它一次都沒碰 store
    result = report_out_of_scope(
        cast("FHIRStore", None), ReportOutOfScopeInput(patient_id="p", missing_information="x")
    )
    assert result.evidence == []
    assert result.out_of_scope is True


def test_no_write_like_tool_names_registered() -> None:
    """安全邊界的機械檢查:write 類工具不該出現在唯讀 allowlist 裡(ADR 0001)。"""
    for spec in READ_ONLY_TOOLS:
        lowered = spec.name.lower()
        assert not any(word in lowered for word in _WRITE_ISH_WORDS), spec.name
