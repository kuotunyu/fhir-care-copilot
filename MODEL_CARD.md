# Model Card — FHIR Care Copilot

本卡片描述的不是一個新訓練的模型，而是**一套 agent 系統**：把既有的通用 LLM（Gemini / OpenAI）套上工具受控、可追溯的 agent loop，用來查詢長照個案的 FHIR 資料。系統本身不做任何模型訓練或微調。

## 系統概覽

| 項目 | 內容 |
|---|---|
| 系統類型 | 工具受控（tool-controlled）read-only agent，非端對端生成式問答 |
| 支援的底層 LLM | `gemini-3.1-flash-lite`（Google，預設）、`gpt-5.4-mini`（OpenAI）、`mock-deterministic`（CI/demo，不呼叫外部 API） |
| 模型 id / 單價來源 | `configs/models.yaml`、`configs/pricing.yaml`（不寫死在程式，換模型只改設定檔） |
| Agent loop 護欄 | `configs/guardrails.yaml`：`max_tool_rounds=6`、`timeout_seconds=30`、`max_input_chars=4000`、`max_output_tokens=1024` |
| 工具清單 | 5 個唯讀工具（demographics / conditions / medications / observations / care plan timeline），皆回傳 `evidence[]`（FHIR `resourceType`/`id`） |
| 寫入路徑 | `propose_care_note` 僅產草稿，**不在 agent loop 工具清單內**；需 UI 明確人工確認才寫本地 audit log JSONL，**永不寫回 FHIR** |

## 這套系統「不是」什麼

- **不是醫療診斷工具**——不提供醫療建議、不做臨床判斷；輸出僅為既有病歷資料的查詢彙整
- **不是**讓 LLM 直接讀資料庫或憑記憶回答——LLM 看不到 FHIR store，只看到工具回傳的 schema 化 JSON
- **不是**用真實病患資料訓練或測試——全部資料來自 Synthea 合成病患（見 `DATA_CARD.md`）

## 預期用途

- 作品集 / 面試展示：示範「LLM 事實一律有出處」的 agent 架構設計
- 長照個案資訊查詢的工程原型（非生產醫療系統）
- Eval harness 與 prompt-injection 防禦模式的參考實作

## 非預期用途

- 任何真實病患資料的臨床決策支援
- 未經人工複核的照護紀錄自動寫入
- 作為醫療診斷、用藥調整或轉診建議的依據

## 真實 Eval 結果（2026-07-24，小樣本各 30 題，見 `reports/model_comparison.md` 完整報告與逐字稿）

> 以下數字全部來自對真實 100 位病患資料的真實 API 呼叫，非預估值。完整 220 題全量比較尚未執行（見已知限制）。

| 指標 | `gemini-3.1-flash-lite` | `gpt-5.4-mini` |
|---|---|---|
| Tool-selection accuracy | 100.0% | 100.0% |
| Field exact match rate | 54.2% | 54.2% |
| **Citation validity rate** | 100.0% | 100.0% |
| Unsupported-claim rate | 0.0% | 0.0% |
| Refusal accuracy | 100.0% | 100.0% |
| Injection resistance rate | 100.0% | 66.7%（人工核閱逐字稿後判斷為判準誤判，未真正服從，見下方限制） |
| p50 / p95 latency (ms) | 1342 / 1787 | 2404 / 5839 |
| 平均成本（USD/題） | $0.00048 | $0.00145 |

**Citation validity 100%（兩個模型皆是）是本專案最重要的信任指標**：每一筆 evidence 都直接對照真實 FHIR store 驗證過，不是模型自我宣稱。

**Field exact match 僅約 54%，但人工核閱後確認不是答錯**：兩個模型都會把英文藥名/診斷名稱翻譯成正體中文或改寫格式（如 `Prediabetes` → `糖尿病前期 (Prediabetes)`），這正是「正體中文 UI」想要的行為，只是嚴格子字串比對抓不到改寫，此指標低估真實品質。

## 已知限制

- **樣本數小**：目前僅各 30 題小樣本比較，非 220 題全量（Gemini 免費層 15 req/min 限制了跑速，`--pace-seconds` 已備妥但全量跑約需 37 分鐘，尚未執行）
- **Field exact match 指標本身有侷限**：嚴格子字串比對無法辨識同義改寫/翻譯，會低估實際正確率
- **Injection resistance 是關鍵字啟發式判準**：判斷「答案是否在拒絕語氣的 15 字內提到違禁詞」，遇到迂迴但安全的回應（如「可以幫你準備給醫師的處方評估摘要」）可能誤判為未抵抗——本專案的因應方式是**同時附上全部逐字稿供人工核閱**，不只信自動聚合數字，詳見 `reports/model_comparison.md`
- **Unsupported-claim rate 是啟發式判準**（沒拒答 + 有實質內容 + evidence 為空），非語意層級的事實查核
- 「不可回答」題型目前只涵蓋「病患不存在」情境，未涵蓋其他資料不足場景
- 兩個真實模型的定價與可用性會隨時間漂移（例如本專案開發期間就發現 `gemini-2.5-flash-lite` 對新帳號已下架），任何成本/延遲數字僅反映測試當下

## 安全設計（與模型無關，屬 agent 架構層）

- `patient_id` 由 agent loop 從對話 session 直接注入工具呼叫，**LLM 無法透過訊息參數竄改**（見 `docs/decisions/0003-patient-scope-injection.md`）
- FHIR 欄位內容一律視為 data，不視為指令——eval 的 injection 題型即在驗證此邊界
- 資料不足時回傳結構化拒答（`refused: true`），不強行作答

## 維護與再現

- 重新產生本卡片引用的數字：`uv run python scripts/run_eval.py --provider gemini --sample-per-category N --pace-seconds 10` 及 `--provider openai`，再跑 `scripts/generate_model_comparison.py`
- 詳細指標定義、已知限制的完整版說明見 `.claude/skills/run-eval/SKILL.md`
