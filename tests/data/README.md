# tests/data/fixtures

**全部是手工打造的合成測試資料**（非 Synthea 直接輸出、不含任何真實個資），
結構依照查證過的 Synthea FHIR R4 輸出慣例（`FhirR4.java`）：

| 檔案 | 用途 |
|---|---|
| `Amy002_Fixture001_a1000000.json` | 主要病患：active/resolved Condition、`active`+`stopped`(舊版慣例) MedicationRequest(`medicationCodeableConcept`)、Observation(valueQuantity + 血壓 component + **valueString**,如居住狀況)、active CarePlan、conditional search URL 參照 |
| `Ben003_Fixture004_b2000000.json` | 第二病患：`completed`(v3.4.0+ 慣例) MedicationRequest + `medicationReference`(已停用,測不列入 active);另有 **`active` + `medicationReference`**(測藥品參照解析的關鍵路徑)與 `active` + `medicationCodeableConcept`;僅 1 個 active Condition、**無 CarePlan**(供之後測空清單路徑) |
| `hospitalInformation*.json` | batch bundle,store 索引時應跳過 |
| `practitionerInformation*.json` | batch bundle,store 索引時應跳過 |
| `not_a_patient_bundle.json` | 非 bundle JSON,store 應略過且不炸 |

命名比照 Synthea 慣例（`名字+數字_姓氏+數字_id前綴.json`、`hospitalInformation+timestamp.json`）。
