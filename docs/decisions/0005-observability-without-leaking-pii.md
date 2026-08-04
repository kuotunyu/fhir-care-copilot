# ADR 0005：可觀測性的取捨——先確保不外洩，再確保看得到

- 狀態：Accepted
- 日期：2026-07-25
- 相關：[ADR 0004](0004-ops-controls-from-domain.md)（控制項從領域推導）、營運層 Phase 2

## 背景

營運層 Phase 2 要加日誌、tracing 與指標。這件事有一個很容易被忽略的性質：

**它是把資料從記憶體搬到別的地方去。** 原本病患資料只在一次請求的生命週期裡存在，
加了可觀測性之後，它可能被寫進檔案、送到 collector、留在別人的儲存空間、
出現在儀表板上、被備份。

所以這個 Phase 的第一命題不是「看得到什麼」，而是**「什麼不准流出去」**。
加了 tracing 卻讓病患姓名進 log，比不加 tracing 還糟。

## 決策

### 1. 遮蔽用白名單，不用黑名單

預設什麼都不記，只記明確判斷過安全的東西：

| 資料 | 處置 |
|---|---|
| `patient_id` | process-local random key 的 HMAC 短參考。同一 process 可關聯；公開 patient id 清單不足以離線重算 |
| `question`、`note_text` | **只記長度**。使用者可能在自由文字裡打進任何東西 |
| 病患姓名、性別、生日 | **完全不記**。工具回傳值整包不進日誌，只記「呼叫了哪個工具、成功與否、幾筆 evidence」 |
| model-controlled text／provider exception message | **不記原文**。只記是否存在、長度、call stage、exception type 與固定 refusal reason |
| `X-Request-ID` | 僅接受 `[A-Za-z0-9._-]{1,64}`；其他值由 server 以 UUID 取代後才進 header/log/trace/audit |

黑名單（「把姓名遮掉」）永遠會漏，因為列不完所有會出現姓名的地方。

### 2. 遮蔽必須有 grep 斷言，不能只是宣稱

`tests/test_pii_redaction.py` 實際跑完整條請求（chat + summary + care-note propose/confirm），
把**所有**日誌與 span 輸出抓下來，對 fixture 病患的真實值做 grep。
斷言病患姓名、原始 note_text、原始問題、完整 `patient_id` 都不在裡面。

那份測試裡有一條 `test_the_run_actually_produced_output`：先斷言真的捕捉到日誌與 span。
沒有它的話，「輸出是空的」也會讓每一條 grep 斷言通過——**一個永遠是綠的測試比沒有測試更危險**。

### 3. 只輸出內容由自己決定的日誌

上面那份測試第一次跑就抓到一個真實洩漏，而且不是我們寫的程式碼造成的：

```
{"logger": "httpx2", "message": "HTTP Request: GET .../api/patients/<真實 patient_id>/summary"}
```

根因是 `configure_logging()` 接管了 root logger，**等於連帶接管了所有第三方函式庫的輸出**，
而那些內容我們控制不了。正式環境同樣有這條路徑：Gemini／OpenAI SDK 內部都用 httpx。

修法：第三方函式庫預設只讓 WARNING 以上通過。真正的錯誤仍然看得到，
例行的請求記錄則不再流出來。除錯時可用 `FHIR_COPILOT_THIRD_PARTY_LOG_LEVEL=DEBUG` 打開，
但那是**明確的決定**，不是預設就把不受控的內容寫出去。

### 4. 指標與 span 的路徑標籤一律用 route 樣板

`/api/patients/{patient_id}/summary` 的原始路徑裡就有病患 id。用原始路徑當標籤會同時
造成兩個問題：cardinality 無上限（Prometheus 撐爆）、以及**病患識別碼被寫進指標**——
那是它最不該去的地方之一，因為指標會被 scrape、儲存、在儀表板上顯示。

`tests/test_pii_redaction.py` 有一條斷言鎖住這個決定，免得日後有人「順手」把 `url.path` 加回去。

### 5. 不用 `opentelemetry-instrumentation-fastapi`

只裝 `opentelemetry-sdk` + OTLP exporter。理由：request id 本來就需要自己的 middleware，
HTTP root span 順手在同一處建即可。auto-instrumentation 會多帶五、六個套件並對框架
做 monkeypatch——為了一個 span 不划算，也和這個專案「可審查、不堆技術」的調性相反。

代價誠實記錄：span 的命名與屬性要自己對齊 OTel semantic conventions
（已照 `http.request.method` / `http.route` / `http.response.status_code` 命名）。

### 6. tracing 模組自己持有 TracerProvider，不搶全域單例

OTel 的 `set_tracer_provider` 只吃第一次呼叫，之後會被忽略。那會讓測試沒辦法換掉
exporter——而 PII 斷言測試正是要把 span 導到暫存檔才驗得了。span 的父子關係走的是
context API 而非 provider，所以自己持有不影響巢狀結構。

### 7. agent loop 只加 span，不改任何行為

provider 呼叫的 span 由 `ops/instrumented_provider.py` 在外面包——`Provider` 是
`typing.Protocol` 且無狀態，所以 loop 分辨不出被包過，**`agent/loop.py` 因此不用動**。

唯一需要碰 loop 的是工具那一層的 span，因為工具是在 `_execute_tool_calls` 的迴圈裡
被派發的，外面包不到。那裡**只加 span**：不改控制流程、不改任何 guardrail 值、
不改拒答條件。OTel 未設定時是 NoOpTracer，開銷接近零。

### 8. `/metrics` 不套 Phase 1 的守門

scrape 是每 15 秒一次的自動流量。套上 API key 認證與限流會直接把它打壞——
不只是要帶 API key 的問題，還會被限流當成異常流量擋掉。

但完全開放會讓任何人看到當日花費與流量，所以留一個**可選的** `FHIR_COPILOT_METRICS_TOKEN`：
沒設就開放（demo 預設，維持「少一個環境變數也能跑」），有設才要求 Bearer token。

老實說這是這個 Phase 裡理由最弱的控制項——按 ADR 0004 自己的標準，
「合成資料 demo 洩漏今天花了 0.003 美元」並不嚴重。留著是因為成本極低（約 10 行），
而且部署到真的會花錢的環境時有個門可以關。

### 9. 可觀測性必須有消費端

**產出 metrics 卻沒人讀、產出 trace 卻沒地方看，只是換個形式的堆技術。** 所以兩種都要：

- **可以自己跑起來看**：`docker compose --profile dev up` 起 Jaeger（`profiles: ["dev"]`，
  正式 image 完全不含它——它是獨立容器，Dockerfile 不知道它存在）
- **不跑任何東西也看得到**：`reports/traces/` 有 commit 進 repo 的完整 trace JSON

## 已知限制（誠實記錄）

- **沒有 Jaeger UI 的截圖**。這台開發機的瀏覽器 pane 無法 compositing，截不了圖。
  已改用 commit 進 repo 的 trace JSON 當證據，並實測驗證過 Jaeger 真的收得到
  （service 列表出現 `fhir-care-copilot`、trace 查詢回傳 5 個 span 且父子關係正確）。
- 日誌目前只有 stdout。集中式日誌收集不在這個 Phase 的範圍。
- `patient_id` pseudonym 的 HMAC key 是 process-local random key，不跨 restart／worker
  穩定。這是刻意限制關聯範圍；若部署需要跨 process 關聯，必須由受控 secret manager
  提供 deployment key，不能把 key 寫進 repo。
- 本專案不實作 retention scheduler；各儲存面的預設 persistence 與刪除責任集中列在
  [`SECURITY.md`](../../SECURITY.md)。

## 後果

- 之後任何新的日誌或 span 屬性，都要先問「這個值會不會是病患資料」。
- PII 斷言測試是這條線的守門員：新增輸出路徑時，如果它沒紅，要先確認它真的涵蓋了新路徑。
- 效能代價要量出來（Phase 0 基線 → 加上可觀測性後的對照），不是加完就宣稱沒影響。
