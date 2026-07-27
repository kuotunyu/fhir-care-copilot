# 發布到 Hugging Face Docker Space

```bash
# dry-run(預設,不需金鑰,不會真的發布)
uv run python scripts/publish_to_hf.py --repo-id <username>/fhir-care-copilot

# 把「會上傳的那一份」攤出來,拿去 docker build 驗證(不碰 HF)
uv run python scripts/publish_to_hf.py --repo-id <username>/x --stage-dir /tmp/hf-stage

# 真的發布(需要 HF_TOKEN,且要明確加 --execute)
uv run python scripts/publish_to_hf.py --repo-id <username>/fhir-care-copilot --load-env --execute \
  --set-secret FHIR_COPILOT_PROVIDER=gemini --set-secret-from-env GEMINI_API_KEY
```

腳本預設 **dry-run**；只有明確加上 `--execute` 才會真的呼叫 HF API。

---

## 四個實際部署才會踩到的坑

全部已修掉並用測試釘住。**它們的共同點是「會安靜地失敗」**——發布流程從頭到尾
印的都是成功，錯誤只在點開網頁時才看得到。

### 1. `FHIR_COPILOT_PROVIDER` 不能省

`models.yaml` 的 `default_provider` 是 `mock`。只設金鑰而不指定 provider，
Space 會退回 mock demo mode。

### 2. Secret 必須在上傳內容之前設定

上傳會觸發 HF 開始 build，build 出來的容器帶的是**當下存在的**環境變數；
先上傳後設 secret 等於保證第一個容器拿不到金鑰。

腳本現在的順序是 create → unset → secrets → upload → `restart_space()`，
由 [`TestPublishOrdering`](../tests/test_publish_to_hf.py) 釘住。

### 3. `--set-secret-from-env` 優於 `--set-secret NAME=VALUE`

後者會把金鑰留在 shell 歷史與 `ps` 的輸出裡。設定真的 API 金鑰時用前者，
命令列上只出現名稱。

### 4. front-matter 的 `colorFrom`/`colorTo` 有值域

只接受 `red / yellow / green / blue / indigo / purple / pink / gray`。
其他值會讓 HF 回 400——而那是**上傳了 184 個檔案之後**才發生的。
腳本現在在任何上傳之前先驗 front-matter。

---

## 給 Space 一把專屬金鑰（不要跟開發共用）

公開 demo 與本機開發、eval 共用同一份免費層額度時，跑一次全量 eval
就可能讓 demo 當天只剩拒答。

```bash
uv run python scripts/publish_to_hf.py --repo-id <username>/fhir-care-copilot --load-env --execute \
  --set-secret FHIR_COPILOT_PROVIDER=gemini \
  --set-secret-from-env-as GEMINI_API_KEY_SPACE:GEMINI_API_KEY \
  --unset-secret GEMINI_API_KEY_BACKUP --unset-secret GEMINI_API_KEY_BACKUP2
```

### 新專案不等於有額度

免費層配額是 **per project**（429 訊息直接寫著
`GenerateRequestsPerDayPerProjectPerModel-FreeTier`）。但如果 AI Studio 把新專案
綁到一個**預付額度已耗盡**的帳單帳戶，那個專案會變成 Tier 1 而**沒有免費額度**
——`Your prepayment credits are depleted`，隔天也不會重置。

**綁到耗盡的付費帳戶比留在免費層更糟。** 兩種 429 的狀態碼一樣，意思相反：

| 錯誤內容 | 意思 | 會不會好 |
|---|---|---|
| `…FreeTier`，limit 500 | 免費層當日配額用完 | 隔天重置 |
| `Your prepayment credits are depleted` | 付費層額度歸零 | **永遠不會好** |

### 推上去之前先單獨驗那把金鑰

**不要帶 failover**——否則新金鑰壞掉也會被備援救起來，等於沒驗。
實測就靠這一步攔下一把不能用的新金鑰，也才發現設定裡有兩把備援**從設定進去
那天就是死的**（failover 每次都老實去試它們，日誌看起來像正常切換）。

### `--set-secret-from-env-as LOCAL:SPACE` 的名字必須對上

本機叫 `GEMINI_API_KEY_SPACE`（才不會蓋掉開發用的），Space 上必須叫
`GEMINI_API_KEY`（`models.yaml` 的 `api_key_env`）。
**名字對不上時 Space 會安靜退回 mock，不會報錯。**

### `--unset-secret`：設定得了也要移除得了

舊的備援金鑰要移除。只設定不移除的話，開發金鑰會永遠留在雲端服務的設定裡。

---

## 部署後一定要做的一件事

**確認 `/api/health` 的 `provider` 欄位不是 `mock`。**

服務本身會誠實揭露降級狀態——前端狀態列在 demo mode 下顯示「示範模式／尚未連接
真實 AI」而非「已連線真實 AI 模型」——但**發布流程不會告訴你**，所以那一步要自己做。
