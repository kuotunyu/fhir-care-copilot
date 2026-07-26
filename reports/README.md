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
- `injection_ab.md` + `injection_ab_<model>.json`（M6）— 兩個 Gemini 版本在**同一組
  20 題**注入案例上的直接對照(5 種手法,搭配 4 位病患)。存在的理由:30 題小樣本裡
  injection 只有 3 題,單題翻轉就是 33 個百分點,不足以決定換不換預設模型。
  由 `scripts/generate_injection_ab.py` 產生
- `traces/`（營運層 Phase 2）— 一次完整 `POST /api/chat` 的 OpenTelemetry trace。
  存在的理由是「可觀測性必須有消費端」:Jaeger 要 `docker compose --profile dev up`
  才看得到,這份 JSON **不跑任何東西也看得到**。span 屬性經過 PII 遮蔽,
  不含病患姓名、問題內容或完整 `patient_id`(`tests/test_pii_redaction.py` 會實際 grep 驗證)

跑法見各 script 的 docstring,或 `.claude/skills/run-eval/SKILL.md`。
