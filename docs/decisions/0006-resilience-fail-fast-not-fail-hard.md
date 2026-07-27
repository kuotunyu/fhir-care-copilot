# ADR 0006：韌性——壞掉的時候快速失敗，而不是拖著整個服務一起死

- 狀態：Accepted
- 日期：2026-07-25
- 相關：[ADR 0004](0004-ops-controls-from-domain.md)（控制項從領域推導）、營運層 Phase 3

## 背景

外部 LLM provider 會超時、會 429、會回垃圾。在 Phase 3 之前，這個服務對這些狀況
完全沒有防護：`gemini.py` 沒有任何 timeout，`openai_provider.py` 只有 SDK 預設的
`max_retries=2`，兩個 adapter 的行為還不一致。

真正嚴重的是 Phase 0 量出來的那個架構特性：**7 個端點全部是同步 `def`，跑在
anyio threadpool 的 40 個 slot 上**。provider 掛掉時，每個進來的請求都會佔住一個
slot 直到逾時。只要每秒有 4 個請求，不到 10 秒整個 threadpool 就被卡死的請求佔滿——
這時候連 `/api/health` 都排不進去，**監控會在服務其實還活著的時候誤判成整台死亡**。

所以這個 Phase 的命題不是「讓失敗的請求成功」，而是**「不要讓一個壞掉的下游拖垮
整個服務」**。

## 決策

### 1. 單次呼叫逾時下在 SDK，不在外層包執行緒

provider 呼叫是阻塞的。在外層用 `concurrent.futures` 包 timeout 只能做到「不等它」——
底層 HTTP 連線還在跑，而 Python 的執行緒殺不掉。結果是逾時從「釋放資源」變成
**「洩漏資源」**：threadpool slot 被一個已經沒人在等的請求繼續佔著。那正好是上面那個
問題的加速器。

正確作法是把 timeout 傳給 SDK 的 HTTP client（`genai.Client(http_options=...)`、
`OpenAI(timeout=...)`），那是真的中止請求。

`provider_timeout_seconds` 必須明顯小於 `guardrails.timeout_seconds`（30 秒），
否則 loop 還沒判逾時就先被單次呼叫吃光時間。目前是 12 秒。

順帶把 `OpenAI(max_retries=0)` 關掉——重試由 `ops/resilience.py` 統一負責，
否則 SDK 內建的重試會和外層的退避疊在一起，實際重試次數與間隔都變成算不出來的值。

### 2. 只重試「可能是暫時性」的失敗

把所有例外都重試會做兩件壞事：把「輸入 schema 有問題」這種必然再失敗的錯誤重打三次
（白花錢），以及**把程式 bug 藏在重試後面看不見**。

判斷方式刻意用「例外類別名稱 + 訊息關鍵字」而不是 import 各家 SDK 的例外型別：
provider adapter 是可插拔的，韌性層不該為了判斷錯誤而依賴特定 SDK。代價是判斷比較粗；
誤判的後果是多打一次或少打一次，兩者都不嚴重。

### 3. 熔斷的目的是快速失敗，不是省錢

連續失敗達閾值後直接拒絕，不再打 provider。省下來的不只是 API 費用，更重要的是
**threadpool slot**——那才是會讓整個服務死掉的資源。

半開狀態**只放一個請求出去探路**。放一整批出去會在 provider 還沒好的時候再把它打垮
一次，這是熔斷器最常見的實作錯誤，所以 `try_acquire` 用同一把鎖保證只有一個 probe。

`try_acquire` 回傳「這次呼叫是在哪個狀態下發出的」，呼叫端要把它原封不動傳回
`record_success` / `record_failure`。不能在事後重讀 `self._state`——那時候狀態可能
已經被別的執行緒改掉了。

### 4. provider 不可用是結構化拒答，不是 500

provider 暫時壞掉是「已知的、預期內的」狀況。回 500 會讓監控誤判成伺服器出錯，
也讓呼叫端無從分辨「該等一等」與「該回報 bug」。

**這是唯一一處為了 Phase 3 而改 `agent/loop.py` 的地方**：新增一個拒答原因
`_REFUSAL_LIMITATION_PROVIDER_UNAVAILABLE`，把 `ProviderUnavailableError` 轉成
既有的 `_refuse(...)` 格式。既有的四個護欄（輸入長度、tool rounds、loop 逾時、
查無病患）**一個都沒動**。

放在 loop 而不是路由層，是因為 eval harness 直接呼叫 `answer_question`——放在路由層
的話，評估過程中 provider 掛掉會噴例外而不是拒答，那會讓 220 題的結果變成無法解讀。

### 5. 重試的成本要算進預算

失敗的嘗試在 provider 端可能已經產生 token（例如生成到一半才逾時），**我們觀測不到**。
所以每次重試都用 `configs/ops.yaml` 的假設值向預算計數補記一筆——寧可高估，
也不要讓一次請求偷偷花三倍錢。

### 6. 包裝順序：韌性在外、觀測在內

```
ResilientProvider(InstrumentedProvider(真正的 provider))
```

反過來包的話，trace 上只看得到最後一次嘗試，**重試就變成看不見的成本**。
現在每一次重試都會產生自己的 `provider.start` span。

熔斷狀態變化也會產生 `circuit.state_change` span 與 metrics counter——否則事後
只會看到一片拒答，查不出是什麼時候開始壞的。

## 已知限制（誠實記錄）

- **熔斷器是單一 process 的記憶體狀態**。多實例部署時每個實例各自判斷，
  provider 掛掉時每個實例都要先各自失敗 N 次才會熔斷。與限流是同一類限制。
- `is_retryable` 用關鍵字比對，會誤判。目前沒有 provider 專屬的錯誤分類。
- **沒有量測熔斷在真實負載下的行為**。故障注入的驗證是單元與整合測試層級的；
  「provider 掛掉時 threadpool 不會被佔滿」這個命題還沒有負載測試數字支持，
  留給 Phase 5 的故障注入場景表。
- 逾時只在 SDK 層。如果 SDK 本身有 bug 導致不遵守 timeout，這一層擋不住。

## 後果

- 之後新增 provider adapter 時，`timeout_seconds` 必須傳給它的 HTTP client，
  否則這個 adapter 就是韌性層的破口。
- 調整 `failure_threshold` / `recovery_seconds` 時要記得：閾值太低會讓偶發失敗
  觸發熔斷，太高則失去保護 threadpool 的意義。
