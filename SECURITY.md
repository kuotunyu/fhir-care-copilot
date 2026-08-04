# Security Boundary

FHIR Care Copilot 是使用 Synthea 合成資料的非臨床工程展示，不是處理真實病歷的
production healthcare system。以下矩陣描述應用程式本身的 persistence/retention 邊界；
專案不內建 retention scheduler 或自動刪除服務。

## Authentication and patient scope

- `REQUIRE_AUTH=true` 時，chat、care-note 與 patient-bearing GET routes 要求 API key；
  health 永遠公開，provider metadata 也保持公開。
- API key 只提供 caller authentication。目前沒有 patient entitlement、RBAC、tenant
  isolation 或 SMART-on-FHIR，因此不是 patient-level authorization。
- Patient ID 由 client 選擇；agent loop 再以 server value 注入 tool call。這能防止模型
  自行指定或跨越 patient scope，但不能替代 user-to-patient authorization。
- Public demo 的資料政策是 Synthea-only；程式可設定其他 FHIR data directory，所以這是
  repository／deployment policy，不是自動辨識或阻擋真實資料的 architecture guarantee。

### Browser API key lifetime

- 前端只把使用者輸入的 API key 保留在目前頁面的記憶體；不寫入 `localStorage`、
  `sessionStorage` 或 cookie，重新整理或關閉頁面後即清除。
- 舊版可能留下的 `localStorage` 項目會在模組初始化時以 best effort 移除；前端不會讀取
  或沿用該值，也不會把 API key 放進 build-time bundle。
- 這項設計縮短瀏覽器端留存時間，但不是 XSS 防護。同源惡意程式碼仍可能在頁面開啟期間
  讀取應用程式狀態或攔截帶有 API key 的請求。

## Log, trace and audit retention matrix

| 儲存面 | 應用程式是否持久化 | Demo 預設 | 保留／刪除責任 |
|---|---|---|---|
| stdout/application logs | 否；只寫 stdout | 由目前 terminal/container runtime 暫存 | 執行平台或部署者設定收集、輪替與刪除 |
| OpenTelemetry traces | exporter 未設定時不持久化；可選擇送到外部 collector | Compose `dev` profile 的 Jaeger 沒有 persistent volume | Collector／Jaeger 營運者設定 retention；停用或移除其儲存 |
| Committed trace sample | 是；只允許 synthetic、redacted sample | 隨 git history 保存 | Repository owner review 後以一般版本變更移除；不得提交 request text 或完整 patient id |
| JSONL care-note audit | 是；append-only local file | 未設定 Postgres 時使用；container filesystem 沒有 audit volume | 部署者保護檔案、備份並依政策刪除；應用程式沒有 TTL |
| Postgres care-note audit | 是；append-only table | 只有 Compose `db` profile／`DATABASE_URL` 啟用時使用 | Database owner 設定備份、保留與經授權的刪除；應用程式沒有 TTL |

Hash chain 提供 tamper evidence，不是不可刪除保證，也不能阻止有完整寫入權限的人重算
整條 chain。Care-note audit 會保存原始 synthetic patient id 與 note text，因此不得把真實
病歷送入公開 demo。

## Observability data boundary

- `patient_id` 在 log/trace 中使用 process-local random key 的 HMAC pseudonym；它只在同一
  process 生命週期內穩定。
- Question、note text、model-controlled text 與 provider exception message 不記原文。
- 外部 `X-Request-ID` 只有符合 `[A-Za-z0-9._-]{1,64}` 才沿用，其他值在進入
  response header、log、trace 或 audit 前由 server 重建。
- 第三方 SDK logger 預設為 WARNING；提高其 log level 可能輸出未經本專案審查的內容。

這些控制只支援 synthetic demo 邊界，不構成醫療、隱私或法規認證。
