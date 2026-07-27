"""LocalBundleFHIRStore — 讀取本地 Synthea FHIR R4 JSON bundles。

Synthea 輸出結構(已查證,2026-07-24 用真實 100 位病患資料校正過):
- 每位病患一個 JSON = 一個 transaction Bundle,第一個 entry 是 Patient
- bundle 內互相參照用 ``urn:uuid:<id>`` fullUrl
- 實測下載的 1K sep2019 樣本中,Practitioner/Organization 都內嵌在病患 bundle
  內、用 urn:uuid 就能解析(掃描全部 1,280 個 patient bundle、190 萬筆
  reference 欄位,0 筆是 conditional search URL);``resolve_reference`` 對
  含 ``?`` 的參照回傳 None 是**防禦性保留**(可能出現在其他版本/設定的
  Synthea 輸出),不是這份資料實際會走到的路徑
- 真正無法解析的參照是 ``#`` 開頭的 contained resource 參照(只出現在
  ExplanationOfBenefit,例如 ``referral: "#referral"``,指向同一個 resource
  自己的 ``contained[]`` 陣列)——目前一律回傳 None,因為沒有任何 M2 工具
  會讀 ExplanationOfBenefit
- 同目錄的 ``hospitalInformation*.json`` / ``practitionerInformation*.json``
  是 batch bundle、非病患資料 → 跳過
"""

from __future__ import annotations

import json
import logging
from collections import OrderedDict
from collections.abc import Iterator
from pathlib import Path

from fhir_copilot.fhir_utils import patient_display_name
from fhir_copilot.store.base import JsonDict, PatientSummary, UnknownPatientError

logger = logging.getLogger(__name__)

_SKIP_PREFIXES = ("hospitalInformation", "practitionerInformation")
# bundle 可能數 MB;只快取最近使用的幾個,避免 1K 病患全載進記憶體
_MAX_CACHED_BUNDLES = 8


class LocalBundleFHIRStore:
    """讀取單一目錄下的 Synthea FHIR R4 patient bundles(唯讀)。

    初始化時掃描目錄建立病患索引(檔案各讀一次後釋放);
    存取時才載入 bundle,並以小型 LRU 快取。
    回傳的 resource 為快取內的原始 dict,呼叫端不得就地修改。
    """

    def __init__(self, data_dir: str | Path) -> None:
        self._data_dir = Path(data_dir)
        if not self._data_dir.is_dir():
            raise FileNotFoundError(f"資料目錄不存在:{self._data_dir}")
        self._files: dict[str, Path] = {}
        self._summaries: dict[str, PatientSummary] = {}
        self._cache: OrderedDict[str, JsonDict] = OrderedDict()
        self._build_index()

    # ---- 索引 ----

    def _build_index(self) -> None:
        for path in sorted(self._data_dir.glob("*.json")):
            if path.name.startswith(_SKIP_PREFIXES):
                continue
            try:
                bundle = _load_json(path)
            except (OSError, ValueError) as exc:
                # ValueError 涵蓋 json.JSONDecodeError,也涵蓋非 UTF-8 檔案觸發的
                # UnicodeDecodeError(M1 審查發現:原本只接 OSError/JSONDecodeError,
                # 一個非 UTF-8 的壞檔會讓整個 store 初始化直接炸,而不是跳過該檔)
                logger.warning("跳過無法解析的檔案 %s:%s", path.name, exc)
                continue
            patient = _first_patient(bundle)
            if patient is None:
                logger.warning("跳過非 patient bundle 檔案:%s", path.name)
                continue
            patient_id = str(patient.get("id") or "")
            if not patient_id:
                logger.warning("跳過缺少 Patient.id 的檔案:%s", path.name)
                continue
            if patient_id in self._files:
                logger.warning("重複的病患 id %s(%s),保留先前的檔案", patient_id, path.name)
                continue
            self._files[patient_id] = path
            self._summaries[patient_id] = PatientSummary(
                patient_id=patient_id,
                name=patient_display_name(patient),
                gender=patient.get("gender"),
                birth_date=patient.get("birthDate"),
                source_file=path.name,
            )
        logger.info("已索引 %d 位病患(%s)", len(self._files), self._data_dir)

    # ---- FHIRStore protocol ----

    def list_patients(self) -> list[PatientSummary]:
        return sorted(self._summaries.values(), key=lambda s: (s.name, s.patient_id))

    def get_patient(self, patient_id: str) -> JsonDict:
        bundle = self._load_bundle(patient_id)
        patient = _first_patient(bundle)
        if patient is None:  # 索引時已驗證過,理論上不會發生
            raise UnknownPatientError(patient_id)
        return patient

    def get_resources(self, patient_id: str, resource_type: str) -> list[JsonDict]:
        bundle = self._load_bundle(patient_id)
        return [r for r in _iter_resources(bundle) if r.get("resourceType") == resource_type]

    def resolve_reference(self, patient_id: str, reference: str) -> JsonDict | None:
        if not reference:
            return None
        if "?" in reference:
            # conditional search URL(如 Practitioner?identifier=...)——防禦性保留,
            # 供其他版本/設定的 Synthea 輸出使用;實測下載的 1K 樣本裡沒有出現過
            return None
        if reference.startswith("#"):
            # contained resource 參照(指向同一 resource 自己的 contained[] 陣列),
            # 真實資料裡只出現在 ExplanationOfBenefit——目前沒有工具讀它,不展開解析
            return None
        bundle = self._load_bundle(patient_id)
        if reference.startswith("urn:uuid:"):
            for entry in bundle.get("entry") or []:
                if entry.get("fullUrl") == reference:
                    resource = entry.get("resource")
                    return resource if isinstance(resource, dict) else None
            return None
        rtype, sep, rid = reference.partition("/")
        if sep and rid:
            for resource in _iter_resources(bundle):
                if resource.get("resourceType") == rtype and resource.get("id") == rid:
                    return resource
        return None

    # ---- 內部 ----

    def _load_bundle(self, patient_id: str) -> JsonDict:
        if patient_id not in self._files:
            raise UnknownPatientError(patient_id)
        cached = self._cache.get(patient_id)
        if cached is not None:
            self._cache.move_to_end(patient_id)
            return cached
        bundle = _load_json(self._files[patient_id])
        self._cache[patient_id] = bundle
        if len(self._cache) > _MAX_CACHED_BUNDLES:
            self._cache.popitem(last=False)
        return bundle


def _load_json(path: Path) -> JsonDict:
    # 明確指定 UTF-8:Windows 預設 locale 編碼是 cp950(ADR 0002 同族問題)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise json.JSONDecodeError("top-level JSON 不是 object", path.name, 0)
    return data


def _iter_resources(bundle: JsonDict) -> Iterator[JsonDict]:
    for entry in bundle.get("entry") or []:
        resource = entry.get("resource")
        if isinstance(resource, dict):
            yield resource


def _first_patient(bundle: JsonDict) -> JsonDict | None:
    if bundle.get("resourceType") != "Bundle":
        return None
    for resource in _iter_resources(bundle):
        if resource.get("resourceType") == "Patient":
            return resource
    return None
