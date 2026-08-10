# FHIR Care Copilot：安全型 AI Application Case Study

> 非臨床技術展示。所有畫面與測試資料皆來自 Synthea 合成病患，不是真實病歷。

## 一分鐘摘要

FHIR Care Copilot 是一個預設唯讀的長照個案查詢工作台。它把 React、FastAPI、LLM agent loop、嚴格 schema 的資料工具、FHIR store adapter 與稽核軌跡放在一條可檢查的資料路徑上。重點不是讓模型「知道更多」，而是把模型能選擇的工具、參數與失敗行為限制在明確邊界內。

本專案只使用 [Synthea 合成資料](../DATA_CARD.md)，不含真實個資，也沒有做臨床驗證。以下內容描述的是可由文件、測試與報告核對的工程控制，不把測試通過解讀成臨床可用性。

## 問題不是「讓模型看資料」，而是限制它只能看哪一位病患

Caller 在每次 API request 中把 `patient_id` 與 `question` 分開提供給 FastAPI。FastAPI 讓該 request 的 `patient_id` 保持在 model-facing tool arguments 之外；agent loop 到 tool dispatch 時才注入它，並覆蓋模型輸出的任何衝突值。這只限制模型不能跨越 caller 選定的 patient scope；它不限制 caller 能選哪位病患，也不構成 entitlement、authorization 或 tenant isolation。

目前的 API key 只做 caller authentication。系統尚未提供 user-to-patient entitlement、RBAC、tenant isolation 或 SMART-on-FHIR，因此不能把 patient scope 或 API authentication 稱為 patient-level authorization。這項區分在 [MODEL_CARD](../MODEL_CARD.md) 與 [SECURITY](../SECURITY.md) 都有明確記錄。

## 真實資料流與信任邊界

1. React 前端送出選定病患與自然語言問題；FastAPI 分開持有 `patient_id` 與 `question`。
2. Agent loop 只把去除 `patient_id` 的 tool schema 交給 LLM。模型看不到底層 FHIR bundle，也沒有介面自行選擇病患。
3. 模型可選擇的只有 allowlist 內的唯讀查詢工具（或宣告超出範圍的工具）及非病患參數；write 工具不在 allowlist。
4. 工具執行前，loop 才把 server-held `patient_id` 注入呼叫；即使 provider 回傳的 arguments 夾帶另一個 id，也會被伺服器端值覆蓋。
5. FHIR store 回傳 schema 化結果與 `evidence[]` references，模型再組合回答，前端則呈現答案與可展開的 FHIR `resourceType/id`。

因此模型能決定「用哪個允許的工具、帶哪些非病患參數」，但不能改寫注入的 patient scope。完整決策與對應測試見 [ADR 0003](decisions/0003-patient-scope-injection.md)。

## 三個最重要的工程決策

### 1. server-injected patient scope

Caller 在每次 API request 中把 `patient_id` 與 `question` 分開提供給 FastAPI。FastAPI 讓該 request 的 `patient_id` 保持在 model-facing tool arguments 之外；agent loop 到 tool dispatch 時才注入它，並覆蓋模型輸出的任何衝突值。這縮小了 prompt injection 能影響的介面。這只限制模型不能跨越 caller 選定的 patient scope；它不限制 caller 能選哪位病患，也不構成 entitlement、authorization 或 tenant isolation。

### 2. tool-controlled retrieval 與嚴格 schema

LLM 不直接查資料庫，只能透過 allowlisted、Pydantic 嚴格 schema 的唯讀工具取得結構化 FHIR 資料；未執行任何工具就作答時，agent loop 會走結構化拒答。資料工具與 `report_out_of_scope` 把「查得到什麼」與「查不到時怎麼回」變成可測試介面，而不是只靠 system prompt。

這仍不代表所有自然語言回答都正確：provider 可能選錯工具、錯誤改寫工具結果，或未走預期的拒答路徑。模型與判準的已知限制集中記錄在 [MODEL_CARD](../MODEL_CARD.md)。

### 3. reference integrity 不等於 claim grounding

FHIR store 的結構化結果會附 evidence references。現有 reference integrity 只檢查已回傳的 `(resourceType, id)` 是否存在於該次使用的 Synthea store；沒有 evidence 的回答不會憑空成為通過。這項 existence check **不代表自然語言回答已逐句 grounded**，也不是完整的 claim-level 事實查核。

因此證據抽屜能讓審查者回到指定 FHIR resource，但不能單靠 reference 的存在，推論回答中每一句都由該 resource 支持。指標語意與歷史欄位限制見 [完整模型比較報告](../reports/model_comparison_full.md)。

## 證據：我量了什麼，也誠實標出沒量到什麼

歷史 paid-provider 結果維持原始 provenance：Gemini、OpenAI mini、OpenAI nano 各有一次完整 220-case run，共三組歷史執行；它們沒有因後續 metric 定義調整而重跑、補值或重新標籤。舊 artifact 沒保存新 reference integrity denominator 所需的 evidence arrays/count，所以新版欄位保留 `n/a`，不從 legacy citation 指標反推 claim grounding。原始摘要、逐字稿與判準限制都在 [model_comparison_full.md](../reports/model_comparison_full.md)。

Prompt injection 另有多次重跑 artifact；單次百分比並不穩定，且機械判準曾出現假陽性與假陰性。這些重跑分佈與未完成執行的排除規則保留在 [injection_variance.md](../reports/injection_variance.md)，不是把歷史結果重跑後包裝成新的臨床結論。

服務層負載測試使用固定延遲的 mock provider，量 FastAPI、路由、工具、FHIR store 與工程控制的 overhead，不含外部 LLM latency；兩條量測軌不可混用。完整控制組、飽和點與儀器雜訊說明見 [loadtest/comparison.md](../reports/loadtest/comparison.md)。

CI 另有 CPU-only deterministic mock quality gate：要求 synthetic fixture 題目全數完成，tool selection、reference integrity、evidence coverage 與 out-of-scope refusal 達到既定門檻，且不得產生無 evidence 的資料回答。每次報告同時記錄 git SHA、synthetic data SHA-256 與 config SHA-256；這些 provenance 只追溯工程輸入版本，不把 mock 分數包裝成 paid-provider 或臨床結果。實作與門檻可直接核對 [workflow](../.github/workflows/ci.yml)、[eval CLI](../scripts/run_eval.py) 與 [tests](../tests/test_eval_release_evidence.py)。

沒有量到、也不宣稱的項目包括：完整 claim-level grounding、真實世界病患資料表現、臨床安全性、臨床效益，以及多租戶授權正確性。

## Failure paths 與可觀測性

以下是工程控制及其可核對邊界，不是臨床 readiness 的證明：

| 風險 | 已交付的工程控制 | 邊界與降級方式 |
|---|---|---|
| 未認證或高頻呼叫 | 可選 API key auth、per-caller rate limit、每日 budget | 啟用 auth 時無效 key 回 401；超速或超預算回 429。Auth 不等於 patient-level authorization（[tests](../tests/test_auth.py)、[rate limit](../tests/test_rate_limit.py)、[budget](../tests/test_budget.py)）。 |
| Logs/traces 洩漏資料 | `patient_id` 使用 process-local keyed HMAC pseudonym；自由文字只記形狀、姓名不記錄，並清洗 request id | 這是 PII-safe logs/traces 的應用層邊界；collector 的 retention 仍由部署者管理（[test](../tests/test_pii_redaction.py)、[SECURITY](../SECURITY.md)）。 |
| Provider timeout、429 或持續失敗 | SDK-level timeout、指數 retry、circuit breaker；重試成本計入 budget | 熔斷時停止呼叫 provider 並回結構化拒答；它保護服務資源，不證明回答品質（[test](../tests/test_resilience.py)、[README failure paths](../README.md#失敗處理邊界)）。 |
| Audit backend 不可用 | 未設定 `DATABASE_URL` 時使用 append-only JSONL；設定 Postgres 但資料庫不可達時標記 audit unavailable | `/api/health` 回 `degraded`，唯讀端點維持；`/api/chat` 以 503 fail closed。JSONL 沒有 container audit volume，Postgres/collector retention 也不是應用自動處理（[README failure paths](../README.md#失敗處理邊界)）。 |
| 容器或依賴狀態不明 | Docker image 內建 `/api/health` healthcheck；CI 執行 image build 與 container smoke | Health 回應揭露 demo/provider/audit 狀態；健康檢查與 CI 測試都只是工程運作證據，不是臨床驗證（[GitHub Actions run 30883804380](https://github.com/kuotunyu/fhir-care-copilot/actions/runs/30883804380)）。 |

## 為什麼保持 modular monolith

目前一個 deployable 內保留清楚的模組邊界：FastAPI orchestration、agent loop、tool registry、FHIRStore interface、provider adapter、audit backend。對這個唯讀、單一工作台範圍，這讓 scope 注入、工具執行、evidence 與 failure path 能沿同一條 request path 被測試與追查。

拆成 microservices 不會自動改善 authorization、grounding 或臨床驗證，反而會新增跨服務身分傳遞、網路失敗與部署協調等尚未量測的問題。因此這個版本保留 modular monolith，並以介面隔離可能替換的 store、provider 與 audit backend；不是宣稱此拓樸適合所有規模。

## 刻意不做的事

- **不提供 tenant isolation 或 patient-level authorization**：只有 caller authentication 與 server-injected patient scope。
- **不宣稱 complete claim-level grounding**：reference integrity 是 reference existence check。
- **不做 clinical validation**：Synthea 是合成病患資料，測試與 CI 不代表臨床 readiness。
- **不 write-back to FHIR**：care-note propose/confirm 只進 append-only audit；沒有任何路徑寫回 FHIR store。
- **不把歷史結果當新結果**：三次 220-case paid-provider runs 與多次 prompt-injection artifacts 僅連結既有 committed evidence，不重跑、不補算、不改標籤。

## 五分鐘審查路徑

1. **看資料流與安全邊界**：[README architecture](../README.md#系統架構與請求時序) → [README security boundaries](../README.md#安全邊界機制)。
2. **看模型行為與指標限制**：[MODEL_CARD](../MODEL_CARD.md) → [完整歷史報告](../reports/model_comparison_full.md)。
3. **看 patient scope 的精確實作決策**：[ADR 0003](decisions/0003-patient-scope-injection.md)。
4. **看 authentication、retention 與 synthetic-only 邊界**：[SECURITY](../SECURITY.md) → [DATA_CARD](../DATA_CARD.md)。
5. **看可重現的交付證據**：[GitHub Actions run 30883804380](https://github.com/kuotunyu/fhir-care-copilot/actions/runs/30883804380) → [公開 mock demo](https://huggingface.co/spaces/steven0226/fhir-care-copilot)。公開頁面應以 `/api/health` 回傳的 `provider=mock`、`model_id=mock-deterministic` 與 `demo_mode=true` 確認目前確實在無付費呼叫的 demo mode。
