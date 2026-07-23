# Data Card — Synthea 合成病患資料

## 資料來源

**全部資料皆為 [Synthea](https://github.com/synthetichealth/synthea)（MITRE）產生的合成（synthetic）病患資料，不含任何真實病患資訊。**

| 項目 | 內容 |
|---|---|
| 來源 | Synthea 官方 sample data，`synthea_sample_data_fhir_r4_sep2019.zip`（~1,000 位合成病患，FHIR R4） |
| 下載網址 | `https://synthetichealth.github.io/synthea-sample-data/downloads/synthea_sample_data_fhir_r4_sep2019.zip`（已驗證 HTTP 200，85,042,887 bytes；官方 `synthea.mitre.org` 網域會擋 bot，一律走 `github.io` 直連） |
| 本地使用子集 | `scripts/download_or_generate_synthea.py --subset 100` 從 1,000 位中子集化出 100 位（`data/processed/subset_100/`），供開發與 eval 使用；亦支援 Java 17+ 時本地生成任意數量 |
| 授權 | **Apache-2.0**（與 Synthea 專案本身一致，GitHub API 已確認） |
| 引用 | Walonoski J, Kramer M, Nichols J, Quina A, Moesel C, Hall D, Duffett C, Dube K, Gallagher T, McLachlan S. *Synthea: An approach, method, and software mechanism for generating synthetic patients and the synthetic electronic health care record.* Journal of the American Medical Informatics Association. 2018;25(3):230-238. https://doi.org/10.1093/jamia/ocx079（機器可讀版見 `CITATION.cff`） |

## 為什麼用合成資料

長照個案查詢系統若用真實病患資料開發、測試、甚至部署到公開展示環境，會直接涉及 PHI（受保護健康資訊）與嚴重的隱私/法規風險。Synthea 用統計模型與臨床路徑規則產生**統計上合理但完全虛構**的病患與病歷，讓工程開發、UI 展示、eval 都能在不涉及任何真人資料的前提下進行。**本專案的部署環境（含任何公開 demo）永遠不會、也不能出現真實病患資料**——這是架構層的保證，不是操作上的承諾。

## 資料結構（FHIR R4 Bundle）

- 每位病患一個 JSON 檔案 = 一個 `Bundle`（`type: "transaction"`），第一個 entry 是 `Patient`，其餘資源大致依 Encounter 時序排列
- 涵蓋的資源型別：`Patient`、`Condition`、`MedicationRequest`（部分含 `Medication`）、`Observation`、`CarePlan`、`Encounter`、`Practitioner`、`Organization`、`ExplanationOfBenefit` 等
- Bundle 內互相參照使用 `urn:uuid:` fullUrl；經對真實 1,000 位病患樣本（190 萬筆 reference 欄位）逐一掃描驗證：**Practitioner / Organization 皆內嵌在病患 bundle 內、可正常解析**（僅 `ExplanationOfBenefit` 內的 `#` 開頭 contained-resource 參照無法解析，因無工具讀取該資源）
- 附帶的 `hospitalInformation*.json` / `practitionerInformation*.json` 是機構層級的 `batch` bundle，非病患資料，載入時略過

### 已知的資料版本差異與瑕疵（實測發現，寫入 parser 的相容邏輯）

| 現象 | 說明 | 因應 |
|---|---|---|
| `MedicationRequest.status` 版本差異 | 已結束的用藥：sep2019 樣本（pre-v3.4.0）用 `stopped`，新版用 `completed` | parser 同時接受 `active`/`stopped`/`completed` |
| 藥品編碼兩種形式 | 多數用 `medicationCodeableConcept`（RxNorm），部分用 `medicationReference` 指向 bundle 內 `Medication` resource | 兩種都處理，並各自附上對應 evidence |
| `Observation.value[x]` 四種形式 | `valueQuantity`（多數）、`valueCodeableConcept`、多 `component[]`（如血壓）、`valueString`（social-history 類別，如居住/受虐狀況——對長照個案查詢特別重要） | 四種皆處理；漏接 `valueString` 曾導致工具靜默回傳 `None`，與「真的沒資料」無法區分，已在 M2 審查修正 |
| 時區位移不一致 | 同一病患跨年份的 `effectiveDateTime`/`period.start` 會混用 `-04:00`/`-05:00`（日光節約時間），直接比字串排序會與實際時間相反 | 一律 parse 成 `datetime` 再比較時間先後，不比字串（`fhir_utils.datetime_sort_key`） |
| 極少數 category code 誤植 | `Left ventricular Ejection fraction` 的 `category` 誤植為單數 `vital-sign`（標準應為複數 `vital-signs`），19,550 筆觀測值中僅 5 筆 | 上游資料的極少數不一致，記錄但不修正（非本專案資料，不擅自竄改） |

## 隱私與合規聲明

- 資料為統計合成，不對應任何真實個人；不構成 PHI/PII
- 專案硬規則仍**以「彷彿是真資料」的紀律處理**：`data/raw`、`data/processed` 皆在 `.gitignore`、不進版控；部署環境的資料是 build time 另外下載/生成，不含在原始碼中
- 系統設計上 LLM 完全看不到底層資料庫，只能透過 schema 化、附證據的工具回傳值間接取得資訊——即使未來換上真實資料源，這層邊界仍然成立（但**本專案本身承諾永遠只用合成資料**，任何真實資料的使用需要完全不同的合規審查，不在本專案範疇內）

## 已知限制

- 樣本量：本地開發與 eval 預設用 100 位病患子集，非完整 1,000 位；資料多樣性（罕見病、多重共病組合）不保證覆蓋真實臨床分布的長尾
- sep2019 樣本版本較舊（pre-v3.4.0），部分欄位慣例與 Synthea 最新版不同（已於上表列出因應方式）
- Synthea 的合成邏輯基於統計模型與公開臨床路徑規則，**不等同真實世界病患的病程真實性**，僅適合工程開發與展示用途，不可作為任何醫學研究或流行病學結論的資料來源
