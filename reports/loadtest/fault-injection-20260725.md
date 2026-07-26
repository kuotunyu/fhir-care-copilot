# 故障注入場景表

產生時間:2026-07-25T21:32:04+00:00

每個場景都**一邊用固定併發打 `/api/chat`,一邊以固定速率打 `/api/health`**,
兩者的延遲分開記錄。故障一律用 mock provider 的注入旋鈕,不打真的 provider。

參數:chat 併發 48、每個場景 40 秒、
health 固定 5 req/s。uvicorn 單一 worker(與 Dockerfile 的 CMD 一致)。

## 為什麼要這樣量

熔斷的目的不是省錢,是**不要讓一個壞掉的下游把 threadpool 佔滿**。
七個端點全是同步 `def`,跑在 anyio threadpool 的 40 個 slot 上——provider 掛掉時
每個請求都佔住一個 slot 直到逾時,佔滿之後連 `/api/health` 都排不進去,
而**監控會在服務其實還活著的時候誤判成整台死亡**。

所以這張表真正要看的欄位是「health p95/p99」:如果它在 provider 掛掉時仍然很小,
那句宣稱才算有證據。

## 結果

| 場景 | chat p50 | chat p95 | chat 拒答率 | chat HTTP 錯誤 | **health p95** | **health p99** | health max |
|---|---:|---:|---:|---:|---:|---:|---:|
| 一切正常(對照組) | 654 ms | 1291 ms | 0% | 0% | **606.9 ms** | **632.2 ms** | 685 ms |
| provider 持續失敗(100%) | 54 ms | 68 ms | 100% | 0% | **126.3 ms** | **1885.6 ms** | 2282 ms |
| provider 間歇失敗(50%) | 2454 ms | 4025 ms | 26% | 0% | **527.3 ms** | **666.6 ms** | 753 ms |
| provider 極慢(3 秒),熔斷閾值調到極高 | 6069 ms | 12121 ms | 0% | 0% | **5775.4 ms** | **5978.1 ms** | 6055 ms |
| 稽核資料庫連不上 | 43 ms | 60 ms | 0% | 100% | **1313.1 ms** | **1843.6 ms** | 1928 ms |

## 各場景的預期行為

- **一切正常(對照組)**:chat 正常回答;health 快速。這一列是其餘場景的比較基準
- **provider 持續失敗(100%)**:chat 回結構化拒答(HTTP 200 + refused)、熔斷開啟後快速失敗;**health 不該被拖慢**
- **provider 間歇失敗(50%)**:重試吸收掉一部分失敗;成功率高於 50%,但延遲因退避而上升
- **provider 極慢(3 秒),熔斷閾值調到極高**:**這是沒有熔斷的對照組**:provider 沒有失敗、只是很慢,所以熔斷不會開;請求全部卡在 provider 上把 threadpool 佔滿
- **稽核資料庫連不上**:health 回 degraded 而不是死掉;chat fail closed 回 503;唯讀端點不受影響
