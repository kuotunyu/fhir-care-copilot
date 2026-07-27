"""list_allergies:病患的過敏與不耐紀錄(FHIR AllergyIntolerance)。

## 為什麼這個工具與其他四個不同:它**不過濾** clinicalStatus

``list_active_conditions`` 與 ``list_active_medications`` 都只回傳 active 的項目
——已解決的診斷不是「目前的診斷」,停用的藥不是「目前在吃的藥」,過濾是對的。

**過敏不一樣。** 一筆 ``clinicalStatus: inactive`` 的過敏紀錄,意思是「目前不認為
有風險」,不是「這件事沒發生過」。把它濾掉,呼叫端就再也看不到它曾經存在——
而在「不能給他什麼」這個問題上,漏掉一筆的代價與多給一筆完全不對稱。

所以這裡回傳全部,並把 ``clinical_status`` 與 ``verification_status`` 一起交出去,
讓呼叫端自己判斷。``verification_status: refuted``(已被否定)尤其重要:那是
「查過了、確認沒有」,與「沒有紀錄」是兩件事。

## 這份合成資料展示不了最重要的用途

實測 subset_100:100 位病患中 14 位有紀錄,共 60 筆,**其中藥物過敏 0 筆**
——全是食物與環境過敏原(黴菌、花粉、動物皮屑、帶殼海鮮、花生、乳膠)。
而且 Synthea 這份 sep2019 樣本把黴菌/花粉/皮屑全標成 ``category: food``,
那是資料瑕疵(環境過敏原不是食物),不是解析錯誤。

**所以這個工具補上的是能力,不是「已支援藥物過敏檢查」的展示。**
換一份含藥物過敏的資料就能展示,但目前這份不行——見 DATA_CARD.md。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from fhir_copilot.fhir_utils import coding_system_code, coding_text
from fhir_copilot.store.base import FHIRStore, JsonDict, UnknownPatientError
from fhir_copilot.tools.base import Evidence, ToolErrorCode, resource_evidence


class ListAllergiesInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    patient_id: str


class AllergySummary(BaseModel):
    model_config = ConfigDict(strict=True)

    display: str
    code_system: str | None
    code_value: str | None
    # allergy(免疫反應)vs intolerance(非免疫,如乳糖不耐)——臨床處置不同
    type: str | None
    # food / medication / environment / biologic。可能有多個。
    categories: list[str] = []
    # low / high / unable-to-assess:會不會致命
    criticality: str | None
    clinical_status: str | None
    verification_status: str | None
    recorded_date: str | None
    # 實際發生過的反應表現(蕁麻疹、呼吸困難⋯)。這份資料裡多半是空的。
    reactions: list[str] = []


class ListAllergiesResult(BaseModel):
    model_config = ConfigDict(strict=True)

    ok: bool
    error: Literal[ToolErrorCode.PATIENT_NOT_FOUND] | None = None
    allergies: list[AllergySummary] = []
    evidence: list[Evidence] = []


def _status_code(resource: JsonDict, field: str) -> str | None:
    coding = (resource.get(field) or {}).get("coding") or []
    if not coding:
        return None
    code = coding[0].get("code")
    return str(code) if code else None


def _reaction_labels(record: JsonDict) -> list[str]:
    labels: list[str] = []
    for reaction in record.get("reaction") or []:
        for manifestation in reaction.get("manifestation") or []:
            text = coding_text(manifestation)
            if text:
                labels.append(text)
    return labels


def list_allergies(store: FHIRStore, params: ListAllergiesInput) -> ListAllergiesResult:
    try:
        store.get_patient(params.patient_id)
    except UnknownPatientError:
        return ListAllergiesResult(ok=False, error=ToolErrorCode.PATIENT_NOT_FOUND)

    allergies: list[AllergySummary] = []
    evidence: list[Evidence] = []
    for record in store.get_resources(params.patient_id, "AllergyIntolerance"):
        code = record.get("code")
        system, value = coding_system_code(code)
        categories = [str(c) for c in (record.get("category") or [])]
        clinical_status = _status_code(record, "clinicalStatus")
        allergies.append(
            AllergySummary(
                display=coding_text(code) or "(未知過敏原)",
                code_system=system,
                code_value=value,
                type=record.get("type"),
                categories=categories,
                criticality=record.get("criticality"),
                clinical_status=clinical_status,
                verification_status=_status_code(record, "verificationStatus"),
                recorded_date=record.get("recordedDate"),
                reactions=_reaction_labels(record),
            )
        )
        # evidence 指向 clinicalStatus:這一欄決定呼叫端該怎麼看待這筆紀錄,
        # 而且它是**沒有被過濾掉**的那一欄,值得讓人逐筆核對
        evidence.append(resource_evidence(record, "clinicalStatus", clinical_status))

    return ListAllergiesResult(ok=True, allergies=allergies, evidence=evidence)
