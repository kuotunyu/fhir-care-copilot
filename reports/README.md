# reports/

`scripts/run_eval.py` 與 `scripts/run_loadtest.py` 的輸出(PLAN.md M5/M6 與營運層
Phase 0)。**這些檔案會進 git**——是可展示的成果,不是暫存資料。

- `eval_results.json` — mock provider 跑完整 220 題的結果(每題判準 + 彙總指標)
- `eval_gemini.json`（M6）— Gemini 真實 API 30 題小樣本
- `eval_openai.json`（M6）— OpenAI 真實 API 30 題小樣本
- `model_comparison.md`（M6）— 由 `scripts/generate_model_comparison.py` 從上面兩份
  JSON 產生的比較報告,一頁式
- `loadtest/`（營運層 Phase 0）— k6 併發矩陣的原始 summary JSON 與 markdown 摘要。
  數字只涵蓋**服務層**(FastAPI + 工具執行 + FHIR store),用 mock provider
  以固定延遲模擬,**不含真實 LLM 供應商延遲**

跑法見各 script 的 docstring,或 `.claude/skills/run-eval/SKILL.md`。
