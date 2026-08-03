# ADR 0001：專案範圍與安全邊界

- **狀態**：Accepted
- **日期**:2026-07-19
- **相關**:[ADR 0003](0003-patient-scope-injection.md)(病患範圍與 injection 邊界)、[ADR 0004](0004-ops-controls-from-domain.md)(營運層控制項)

## 背景

FHIR Care Copilot 是作品級展示專案：以 LLM agent 查詢長照個案的 FHIR R4 資料。
醫療領域 + LLM 的組合有明確風險（幻覺、越權存取、injection、隱私），因此範圍與邊界必須在寫第一行程式前就定死。

## 決策

### 1. 只用合成資料（synthetic-only）

- 資料唯一來源：Synthea 官方樣本或本地固定 seed 生成（皆 Apache-2.0）
- repo、測試 fixture、文件截圖、部署環境**永不出現真實病患資料**
- **PII/PHI 假設**：本專案假設所有資料皆為合成、不受 HIPAA/個資法約束；但工程紀律上仍以「彷彿是真資料」處理（資料目錄 gitignore、不放 log、不外傳），作為可遷移到真實場景的示範

### 2. 預設唯讀（read-only default）

- Agent loop 的工具 allowlist 中**不存在任何 write 類工具**——不是「擋下來」，是「根本不註冊」
- 唯一的寫入路徑：Backend `propose_care_note` 產生簽章草稿 → client 明確呼叫 `confirm` → 寫入 audit log；React confirmation UI 尚未實作
- audit log 永不寫回 FHIR store；FHIRStore interface 刻意不提供 write 方法

### 3. LLM 與資料的隔離

- LLM 看不到資料庫、看不到原始 bundle；只看到工具回傳的 schema 化結果
- 每個病患事實必附 `evidence[]`（FHIR resourceType/id）；無證據的敘述視為 unsupported claim（eval 指標之一）
- 資料不足、超出工具能力 → 結構化拒答（`refused: true`），不得靠模型記憶補答

### 4. Prompt injection 邊界

- **威脅**：FHIR 欄位內容（如 note、名稱）或使用者輸入中夾帶指令，誘導 agent 越權、洩漏 system prompt、或輸出未經證據支持的內容
- **對策**：
  - 工具回傳值一律是嚴格 schema 的結構化資料，欄位內容視為 data 而非指令
  - loop 護欄：max tool rounds、timeout、輸入長度上限、工具 allowlist
  - eval 內建 injection 題型（在合成資料欄位中植入指令），refusal accuracy 為必測指標
- **不宣稱**完全防禦；已知殘餘風險記入 README 已知限制

### 5. 人工確認點（human-in-the-loop）

| 動作 | 確認方式 |
|---|---|
| care note 草稿 → audit log | Backend confirm API 驗證簽章後才儲存；React confirmation UI 尚未實作 |
| 發布到 Hugging Face | `scripts/publish_to_hf.py` 預設 dry-run，需明確 flag 才真的上傳 |
| 超過 eval 預算（預設 $5） | 跑前估算 + 途中累計，超過即停，需人工調高上限才續跑 |

### 6. Threat model 摘要

| 威脅 | 資產 | 對策 |
|---|---|---|
| 模型幻覺病患事實 | 回答正確性 | 工具強制 + evidence 必附 + unsupported-claim eval |
| Prompt injection(資料/輸入夾帶指令) | 越權行為、輸出污染 | §4;write 工具不存在,injection eval |
| API key 洩漏 | 金鑰 | .env gitignore、Space Secrets、pre-commit detect-private-key |
| 誤把輸出當醫療建議 | 使用者安全 | UI 與文件明示非診斷工具;拒答機制 |
| 成本失控 | API 帳單 | 預算守門、cost badge、mock provider |

## 不做的事（non-goals）

- 不提供診斷、用藥、治療建議
- 不寫回任何 FHIR server
- 不做使用者帳號/權限系統（demo 為公開唯讀合成資料）
- 不宣稱 production-ready 的醫療合規（HIPAA/ISO 27001 等）
