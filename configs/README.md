# configs/

模型 id、API 單價、agent loop 護欄、營運層參數等**全部放這裡，不寫死在程式**（PLAN.md §8/§10）。

- `models.yaml`（M3）— provider/模型 id 對應（mock/gemini/openai）
- `pricing.yaml`（M3）— 各模型每 1M tokens 單價（成本估算用；價格會漂移，改這裡即可）
- `guardrails.yaml`（M3）— 單次對話在 agent loop 內的行為：max tool rounds、loop 累計逾時、
  輸入長度上限
- `ops.yaml`（營運層 Phase 0/1）— 服務對外的營運行為：API key header 名稱、每 key 限流速率、
  每日成本上限、負載測試參數

`guardrails.yaml` 與 `ops.yaml` 刻意分開：前者管「一次問答在 loop 裡能做什麼」，後者管
「這個服務對外要怎麼被安全地營運」。兩者的變更理由不同，混在一起會分不清楚改一個值會影響什麼。

**兩份檔案都刻意不重複列「清單」**——工具 allowlist 的權威來源是
`src/fhir_copilot/tools/registry.py` 的 `READ_ONLY_TOOLS`，受保護端點的權威來源是
`src/fhir_copilot/api/routes.py` 上掛了哪個 dependency。設定檔與程式碼各說各話時，
沒有人知道哪一份才算數。

**金鑰永遠不進這些檔案**，只從環境變數來（見 `.env.example`）。
