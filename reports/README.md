# reports/

`scripts/run_eval.py`、`scripts/run_loadtest.py` 與 `scripts/run_fault_injection.py`
的輸出(PLAN.md M5/M6 與營運層 Phase 0/2/5)。**這些檔案會進 git**——是可展示的成果,
不是暫存資料。

- `eval_results.json` — mock provider 跑完整 220 題的結果(每題判準 + 彙總指標)
- `eval_gemini.json`（M6）— Gemini 真實 API 30 題小樣本
- `eval_openai.json`（M6）— OpenAI 真實 API 30 題小樣本
- `model_comparison.md`（M6）— 由 `scripts/generate_model_comparison.py` 從上面兩份
  JSON 產生的比較報告,一頁式
- `loadtest/`（營運層 Phase 0/5）— k6 併發矩陣的原始 summary JSON 與 markdown 摘要。
  數字只涵蓋**服務層**(FastAPI + 工具執行 + FHIR store),用 mock provider
  以固定延遲模擬,**不含真實 LLM 供應商延遲**。四個階段(`baseline`、`with-controls`、
  `with-observability`、`final`)各一次獨立量測,`comparison.md` 是由
  `scripts/compare_loadtests.py` 從那四份 JSON 產生的對照表;
  `fault-injection-*.md` 是五個故障場景的結果
- `eval_gemini_full.json` / `eval_openai_full.json` / `eval_openai_nano_full.json`（M6）—
  三個模型各跑**完整 220 題**的結果;`model_comparison_full.md` 是三欄對照表
- `e2e_sample_<provider>.{json,md}`（M6/營運層 Phase 5）— 端到端取樣:含真實供應商延遲的
  完整 HTTP 往返。**與 `loadtest/` 那一軌不可混用**——那邊量控制項的每請求成本
  (mock + k6 併發),這邊量真實延遲量級(真 provider、單一連線、固定間隔)
- `injection_ab.md` + `injection_ab_<model>.json`（M6）— 兩個 Gemini 版本在**同一組
  20 題**注入案例上的直接對照(5 種手法,搭配 4 位病患)。存在的理由:30 題小樣本裡
  injection 只有 3 題,單題翻轉就是 33 個百分點,不足以決定換不換預設模型。
  由 `scripts/generate_injection_ab.py` 產生
- `eval_allergy_<model>.json`（2026-07-27）— 過敏題型（14 題）三個模型各一份，
  隨 `list_allergies` 工具一起加的題型。**這三份的價值在逐字稿而不在百分比**：
  field exact match 是 71.4 / 71.4 / 42.9%，但 16 題失配全部逐字讀完後沒有一筆
  答錯、漏掉或編造，差別只在把 `Allergy to grass pollen` 寫成「草花粉過敏」。
  我另外寫的第二個機械判準也判錯了（敗在純中文寫法）——**兩個判準都誤導，
  靠逐字稿定案**，這正是這些 JSON 要進 git 的理由
- `injection_variance.md` + `injection_repeats/`（2026-07-26/27）— 同一組 20 題注入案例
  **重跑多次**的分佈。存在的理由:單次執行的百分比不可靠——實測同一個模型對同一道題,
  兩次執行會給出不同回答。報表依**護欄版本**分成兩組(檔案裡的 `guardrails` 欄位;
  沒有那個欄位的就是 2026-07-26 之前跑的),新舊數字並列而不是互相取代
- `out_of_scope_variance.md` + `out_of_scope_repeats/`（2026-07-27）— 「病患存在但
  5 個資料工具都查不到」時的正確拒答率。這一類量的是**模型會不會呼叫
  `report_out_of_scope`**,不是護欄接沒接好(那是確定性的,見 `unanswerable`)。
  兩份都由 `scripts/run_repeat_eval.py` 產生
- `traces/`（營運層 Phase 2）— 一次完整 `POST /api/chat` 的 OpenTelemetry trace。
  存在的理由是「可觀測性必須有消費端」:Jaeger 要 `docker compose --profile dev up`
  才看得到,這份 JSON **不跑任何東西也看得到**。span 屬性經過 PII 遮蔽,
  不含病患姓名、問題內容或完整 `patient_id`(`tests/test_pii_redaction.py` 會實際 grep 驗證)

跑法見各 script 的 docstring,或 [`docs/EVAL.md`](../docs/EVAL.md)
(題目怎麼產生、六項指標怎麼算、哪些判準不可靠)。
