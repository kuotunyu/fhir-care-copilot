"""FHIR resource 小工具函式(store 與 tools 共用)。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # **只在型別檢查時 import,執行時不 import。**
    #
    # `fhir_copilot.store.base` 這一行會先跑 `store/__init__.py`,而它 import
    # `store.local`,`store.local` 又 import 回這裡——一個真正的循環。它一直沒炸
    # 只是因為進入點剛好都是先碰到 `tools.base`;2026-07-27 加一個字母序排在
    # 前面的工具模組(allergies)就把進入點換掉,ImportError 立刻出現。
    #
    # JsonDict 只是型別別名、只出現在標註裡,而這個檔案有 `from __future__
    # import annotations`,所以標註是字串、執行期不需要這個名字。
    from fhir_copilot.store.base import JsonDict

# 缺值/無法解析時的排序墊底值(必須是 timezone-aware,才能跟真實 FHIR dateTime 比較)
_MISSING_DATETIME_SORT_KEY = datetime.min.replace(tzinfo=UTC)


def patient_display_name(patient: JsonDict) -> str:
    """從 Patient.name 取顯示名(偏好 use=official)。"""
    names = patient.get("name") or []
    if not names:
        return "(unnamed)"
    chosen = next((n for n in names if n.get("use") == "official"), names[0])
    given = " ".join(chosen.get("given") or [])
    family = chosen.get("family") or ""
    full = f"{given} {family}".strip()
    return full or "(unnamed)"


def coding_text(codeable_concept: JsonDict | None) -> str | None:
    """取 CodeableConcept 的顯示文字:優先 text,其次第一個 coding.display,再其次 coding.code。"""
    if not codeable_concept:
        return None
    text = codeable_concept.get("text")
    if text:
        return str(text)
    codings = codeable_concept.get("coding") or []
    if codings:
        first = codings[0]
        display = first.get("display") or first.get("code")
        return str(display) if display else None
    return None


def coding_system_code(codeable_concept: JsonDict | None) -> tuple[str | None, str | None]:
    """取第一個 coding 的 (system, code)。"""
    if not codeable_concept:
        return None, None
    codings = codeable_concept.get("coding") or []
    if not codings:
        return None, None
    first = codings[0]
    system = first.get("system")
    code = first.get("code")
    return (str(system) if system else None), (str(code) if code else None)


def datetime_sort_key(value: str | None) -> datetime:
    """把 FHIR dateTime 字串轉成可比較的 datetime,供「依時間排序」使用。

    直接比字串在混用不同 UTC 位移時會排錯——已在真實 Synthea 資料驗證此假設
    會被打破(同一病患跨年份的 Observation/CarePlan 時間戳記混用 -04:00/-05:00,
    M2 審查發現字串排序在此情況下順序會與實際時間相反)。缺值或無法解析一律
    回傳墊底值,不炸、且排序時自然落到最前或最後(視 reverse 而定)。
    """
    if not value:
        return _MISSING_DATETIME_SORT_KEY
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return _MISSING_DATETIME_SORT_KEY
