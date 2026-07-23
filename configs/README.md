# configs/

模型 id、API 單價、agent loop 護欄參數等**全部放這裡，不寫死在程式**（PLAN.md §8/§10）。

- `models.yaml`（M3）— provider/模型 id 對應（mock/gemini/openai）
- `pricing.yaml`（M3）— 各模型每 1M tokens 單價（成本估算用；價格會漂移，改這裡即可）
- `guardrails.yaml`（M3）— max tool rounds、timeout、輸入長度上限；工具 allowlist 的權威來源
  是 `src/fhir_copilot/tools/registry.py`，這裡不重複列，避免兩邊各說各話
