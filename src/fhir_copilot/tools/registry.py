"""工具登錄:供 M3 agent loop 組 tool-calling 宣告與分派呼叫。

刻意只登錄唯讀工具(ADR 0001)——write 類工具(如 M3 的 propose_care_note)
不會出現在這裡,agent loop 的 allowlist 就是這份清單,做不到的事根本呼叫不到。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from fhir_copilot.store.base import FHIRStore
from fhir_copilot.tools.careplan import GetCarePlanTimelineInput, get_care_plan_timeline
from fhir_copilot.tools.conditions import ListActiveConditionsInput, list_active_conditions
from fhir_copilot.tools.demographics import (
    GetPatientDemographicsInput,
    get_patient_demographics,
)
from fhir_copilot.tools.medications import ListActiveMedicationsInput, list_active_medications
from fhir_copilot.tools.observations import GetRecentObservationsInput, get_recent_observations


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_model: type[BaseModel]
    handler: Callable[[FHIRStore, Any], BaseModel]


READ_ONLY_TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="get_patient_demographics",
        description="取得病患基本資料(姓名/性別/出生日期)",
        input_model=GetPatientDemographicsInput,
        handler=get_patient_demographics,
    ),
    ToolSpec(
        name="list_active_conditions",
        description="列出病患目前生效中(clinicalStatus=active)的診斷",
        input_model=ListActiveConditionsInput,
        handler=list_active_conditions,
    ),
    ToolSpec(
        name="list_active_medications",
        description="列出病患目前生效中(status=active)的用藥",
        input_model=ListActiveMedicationsInput,
        handler=list_active_medications,
    ),
    ToolSpec(
        name="get_recent_observations",
        description="取得病患最近的觀察值(生命徵象/檢驗結果等),可依類別篩選並限制筆數",
        input_model=GetRecentObservationsInput,
        handler=get_recent_observations,
    ),
    ToolSpec(
        name="get_care_plan_timeline",
        description="取得病患照護計畫時間軸",
        input_model=GetCarePlanTimelineInput,
        handler=get_care_plan_timeline,
    ),
)

TOOLS_BY_NAME: dict[str, ToolSpec] = {spec.name: spec for spec in READ_ONLY_TOOLS}


def llm_facing_schema(spec: ToolSpec) -> dict[str, Any]:
    """給 LLM 看的 tool-calling JSON schema——拿掉 ``patient_id``。

    安全邊界(ADR 0003):使用者選定的病患由 agent loop 直接注入工具呼叫,
    LLM 不能透過工具參數指定或竄改要查詢的病患。這裡把 ``patient_id`` 從
    LLM 看得到的 schema 中拿掉,讓它連「選錯病患」的選項都沒有。
    """
    schema: dict[str, Any] = spec.input_model.model_json_schema()
    properties = dict(schema.get("properties", {}))
    properties.pop("patient_id", None)
    schema["properties"] = properties
    required = schema.get("required", [])
    schema["required"] = [name for name in required if name != "patient_id"]
    return schema
