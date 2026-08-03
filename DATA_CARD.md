# Data Card — Synthea 合成病患資料

## 資料來源

**全部資料皆為 [Synthea](https://github.com/synthetichealth/synthea)（MITRE）產生的合成（synthetic）病患資料，不含任何真實病患資訊。**

| 項目 | 內容 |
|---|---|
| 來源 | Synthea 官方 versioned sample data，`synthea_sample_data_fhir_r4_sep2019.zip`（~1,000 位合成病患，FHIR R4） |
| 下載網址 | `https://synthetichealth.github.io/synthea-sample-data/downloads/synthea_sample_data_fhir_r4_sep2019.zip`（85,042,887 bytes；SHA-256 `a6fc595d9c0f4c646746af42f861b5a12d03c856af158dd837c764dfb81b66f8`，下載時 fail closed） |
| 本地使用子集 | `scripts/download_or_generate_synthea.py --subset 100` 從 1,000 位中子集化出 100 位（`data/processed/subset_100/`），供開發與 eval 使用；亦支援 Java 17+ 時本地生成任意數量 |
| 授權 | **Apache-2.0**（與 Synthea 專案本身一致，GitHub API 已確認） |
| 引用 | Walonoski J, Kramer M, Nichols J, Quina A, Moesel C, Hall D, Duffett C, Dube K, Gallagher T, McLachlan S. *Synthea: An approach, method, and software mechanism for generating synthetic patients and the synthetic electronic health care record.* Journal of the American Medical Informatics Association. 2018;25(3):230-238. https://doi.org/10.1093/jamia/ocx079（機器可讀版見 `CITATION.cff`） |

## 為什麼用合成資料

長照個案查詢系統若用真實病患資料開發、測試、甚至部署到公開展示環境，會直接涉及 PHI（受保護健康資訊）與嚴重的隱私/法規風險。Synthea 用統計模型與臨床路徑規則產生**統計上合理但完全虛構**的病患與病歷，讓工程開發、UI 展示、eval 都能在不涉及任何真人資料的前提下進行。公開 demo 與 committed artifacts 的資料政策是 **Synthea-only**；程式本身仍可設定任意 FHIR data directory，因此這是明確的專案／發布邊界，不是自動阻止真實資料載入的架構保證。

## 資料結構（FHIR R4 Bundle）

- 每位病患一個 JSON 檔案 = 一個 `Bundle`（`type: "transaction"`），第一個 entry 是 `Patient`，其餘資源大致依 Encounter 時序排列
- 涵蓋的資源型別：`Patient`、`Condition`、`MedicationRequest`（部分含 `Medication`）、`Observation`、`CarePlan`、`Encounter`、`Practitioner`、`Organization`、`ExplanationOfBenefit` 等
- Bundle 內互相參照使用 `urn:uuid:` fullUrl；經對完整 1,000 位 Synthea 合成病患樣本（190 萬筆 reference 欄位）逐一掃描驗證：**Practitioner / Organization 皆內嵌在病患 bundle 內、可正常解析**（僅 `ExplanationOfBenefit` 內的 `#` 開頭 contained-resource 參照無法解析，因無工具讀取該資源）
- 附帶的 `hospitalInformation*.json` / `practitionerInformation*.json` 是機構層級的 `batch` bundle，非病患資料，載入時略過

### 已知的資料版本差異與瑕疵（實測發現，寫入 parser 的相容邏輯）

| 現象 | 說明 | 因應 |
|---|---|---|
| `MedicationRequest.status` 版本差異 | 已結束的用藥：sep2019 樣本（pre-v3.4.0）用 `stopped`，新版用 `completed` | parser 同時接受 `active`/`stopped`/`completed` |
| 藥品編碼兩種形式 | 多數用 `medicationCodeableConcept`（RxNorm），部分用 `medicationReference` 指向 bundle 內 `Medication` resource | 兩種都處理，並各自附上對應 evidence |
| `Observation.value[x]` 四種形式 | `valueQuantity`（多數）、`valueCodeableConcept`、多 `component[]`（如血壓）、`valueString`（social-history 類別，如居住/受虐狀況——對長照個案查詢特別重要） | 四種皆處理；漏接 `valueString` 曾導致工具靜默回傳 `None`，與「真的沒資料」無法區分，已在 M2 審查修正 |
| 時區位移不一致 | 同一病患跨年份的 `effectiveDateTime`/`period.start` 會混用 `-04:00`/`-05:00`（日光節約時間），直接比字串排序會與實際時間相反 | 一律 parse 成 `datetime` 再比較時間先後，不比字串（`fhir_utils.datetime_sort_key`） |
| 極少數 category code 誤植 | `Left ventricular Ejection fraction` 的 `category` 誤植為單數 `vital-sign`（標準應為複數 `vital-signs`），19,550 筆觀測值中僅 5 筆 | 上游資料的極少數不一致，記錄但不修正（非本專案資料，不擅自竄改） |
| `AllergyIntolerance.category` 全部標成 `food` | **完整 1,000 位樣本的 567 筆過敏紀錄，一筆不漏全是 `category: food`**——包括「乳膠過敏」21 筆與「蜂毒過敏」24 筆。黴菌/花粉/動物皮屑至少沾得上「環境」的邊，乳膠與蜂毒連勉強都說不上 | 原樣回傳並附 evidence，不擅自改寫；但**任何依 `category` 篩選的邏輯在這份資料上都不可信**，這一點寫進 `tools/allergies.py` |

### `AllergyIntolerance` 的覆蓋缺口（2026-07-27 新增工具、2026-07-28 掃完整樣本）

`list_allergies` 工具是為了補「查得到用藥、查不到過敏」這個產品缺口而加的。但**這份合成資料展示不了它最重要的用途**——而且這不是子集抽樣的問題，是整份資料的性質：

| | 100 位子集 | **完整 1,000 位樣本** |
|---|---|---|
| 有過敏紀錄的病患 | 14 | 143 |
| 過敏紀錄總數 | 60 筆 | **567 筆** |
| **藥物過敏（`category: medication`）** | 0 | **0** |
| `criticality: high` 或 `unable-to-assess` | 0 | **0** |
| 含 `reaction`（實際反應表現） | 0 | **0** |
| `type: intolerance`（非免疫反應） | 0 | **0** |
| `verificationStatus: refuted` | 0 | **0** |

567 筆全部是 `food` / `allergy` / `low` 的組合。過敏原分佈：黴菌 77、動物皮屑 73、草花粉 64、樹花粉 61、塵蟎 57、帶殼海鮮 53、堅果 26、魚 25、花生 24、蜂毒 24、乳膠 21、乳製品 20、蛋 20、小麥 17、大豆 5。

也就是說：**「開藥前檢查藥物過敏」這個 `AllergyIntolerance` 最核心的臨床用途，用這份資料一次都示範不了**，換一個子集也沒用。

工具本身處理得了那些情況（藥物類別、高危險度、反應表現、`intolerance`、已被否定的紀錄），但那些路徑只有 `tests/data/fixtures/` 裡手工打造的合成病患走得到——fixture 刻意補上 Synthea 樣本未涵蓋的組合，見 `tests/test_tools_allergies.py`。

**沒有為了讓 demo 好看而補資料。** 這個專案對上游資料的立場是「記錄但不修正，不擅自竄改」（上表 `vital-sign` 單複數誤植那一列即是先例）。分得清「工具能力」與「資料涵蓋」比展示得漂亮重要。

### 想看藥物過敏：用本地生成，不要動這份樣本

**新版 Synthea 產得出這份 sep2019 樣本缺的東西。** 實測（`--generate --seed 20260728 --population 200`，Java 17.0.16）：

| | sep2019 樣本（1,000 位） | 本地生成（200 位） |
|---|---|---|
| `category` | food **567（100%）** | environment 206 / food 55 / **medication 22** |
| `type` | allergy 567 | allergy 279 / **intolerance 4** |
| 含 `reaction` | **0** | **117** |
| 反應表現 | — | Eruption of skin 58、Wheal 49、Dyspnea 31、**Anaphylaxis 24**… |
| 藥物過敏原 | — | Aspirin、Lisinopril |

而且 `category` 分類正確了——黴菌/花粉/皮屑歸 `environment`，不再全塞進 `food`。

**`list_allergies` 零改動就讀得出來**（實測，不是只掃原始 JSON）：

```
Aspirin       type=allergy      cat=['medication'] reactions=['Abdominal pain (finding)']
Lisinopril    type=intolerance  cat=['medication']
Shellfish     type=allergy      cat=['food']       reactions=['Dyspnea', 'Eruption of skin', ...]
```

跑法（**不會覆蓋 `data/processed`，輸出到 `data/raw/generated/`**）：

```bash
uv run python scripts/download_or_generate_synthea.py --generate --seed 20260728 --population 200
```

**但預設仍然是下載 sep2019 樣本，不改。** `reports/` 底下每一個數字都是用那份資料量出來的——換掉預設等於讓 220 題 eval（三個模型）、四階段負載測試、截圖、端到端取樣全部作廢。本地生成是**額外的選項**，不是替代。

> **生成資料還有一個瑕疵沒修**：283 筆全部 `criticality: low`，**包括那 24 筆過敏性休克（Anaphylaxis）**。臨床上過敏性休克絕不是低危險。所以「用生成資料就能完整示範」也不成立——`criticality: high` 的路徑仍然只有 `tests/data/fixtures/` 的手工病患走得到。

## 隱私與合規聲明

- 資料為統計合成，不對應任何真實個人；不構成 PHI/PII
- 專案硬規則仍**以「彷彿是真資料」的紀律處理**：`data/raw`、`data/processed` 皆在 `.gitignore`、不進版控；部署環境的資料是 build time 另外下載/生成，不含在原始碼中
- 系統設計上 LLM 完全看不到底層資料庫，只能透過 schema 化、附證據的工具回傳值間接取得資訊——即使未來換上真實資料源，這層邊界仍然成立（但**本專案本身承諾永遠只用合成資料**，任何真實資料的使用需要完全不同的合規審查，不在本專案範疇內）

## 已知限制

- 樣本量：本地開發與 eval 預設用 100 位病患子集，非完整 1,000 位；資料多樣性（罕見病、多重共病組合）不保證覆蓋真實臨床分布的長尾
- sep2019 樣本版本較舊（pre-v3.4.0），部分欄位慣例與 Synthea 最新版不同（已於上表列出因應方式）
- `--generate` 的可選本地生成路徑仍從 Synthea `releases/latest` 取得 JAR；它不參與 Docker demo build，也不作為 committed evaluation provenance
- Synthea 的合成邏輯基於統計模型與公開臨床路徑規則，**不等同真實世界病患的病程真實性**，僅適合工程開發與展示用途，不可作為任何醫學研究或流行病學結論的資料來源
