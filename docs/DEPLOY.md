# 發布到 Hugging Face Docker Space

> 只允許 Synthea 合成資料。這是非臨床作品集展示，不應接收真實病歷。

發布腳本預設是 dry-run；只有明確加入 `--execute` 才會呼叫 Hugging Face API。

```bash
# 預覽會上傳的內容，不需 token、不會發布
uv run python scripts/publish_to_hf.py --repo-id <username>/fhir-care-copilot

# 產生可在本機 Docker build 驗證的 staging directory，不碰 Hugging Face
uv run python scripts/publish_to_hf.py --repo-id <username>/x --stage-dir /tmp/hf-stage
```

## 建議的公開作品集模式：mock

公開 demo 應維持 repository 的安全預設 `FHIR_COPILOT_PROVIDER=mock`。它不需要外部
provider API key，也不會呼叫付費模型；仍可展示 request、tool、FHIR reference、拒答與
audit flow。

```bash
# 真的發布會需要環境中的 HF_TOKEN；同時覆蓋舊 provider 並清除已知 external API keys
uv run python scripts/publish_to_hf.py \
  --repo-id <username>/fhir-care-copilot \
  --execute \
  --set-secret FHIR_COPILOT_PROVIDER=mock \
  --unset-secret GEMINI_API_KEY \
  --unset-secret GEMINI_API_KEY_BACKUP \
  --unset-secret GEMINI_API_KEY_BACKUP2 \
  --unset-secret GEMINI_API_KEY_BACKUP3 \
  --unset-secret OPENAI_API_KEY
```

這些 `--unset-secret` 讓既有 external-provider Space 重新發布時也會收斂到 mock；只改
source code 或省略 provider 設定，不能保證遠端既有 secrets 已被移除。

發布後檢查 `/api/health`，公開 mock demo 的預期值是：

- `provider=mock`
- `model_id=mock-deterministic`
- `demo_mode=true`

## 選配的私人 external-provider 模式

這不是公開作品集的必要條件。只有在私人、受控且能承擔費用的部署中，才設定 external
provider 與專屬 API key；不可與開發或 evaluation 共用 credentials。

```bash
uv run python scripts/publish_to_hf.py \
  --repo-id <username>/fhir-care-copilot-private \
  --private --load-env --execute \
  --set-secret FHIR_COPILOT_PROVIDER=gemini \
  --set-secret-from-env-as GEMINI_API_KEY_SPACE:GEMINI_API_KEY
```

這條路徑發布後，才應確認 `/api/health` 的 `provider` 不是 `mock`。API key 值不得放在
命令列、文件、git history 或公開 log；`--set-secret-from-env-as` 只在命令列顯示變數名稱。

## 五個部署陷阱

1. **Provider 必須明確**：只有 API key 而未設定 provider 時，服務會依安全預設使用
   `mock`；以 `/api/health` 判定實際模式。
2. **Secret 要先於 upload**：腳本依 create → unset → secrets → upload → restart 的順序
   執行，避免第一個 container 在 secret 尚未設定時啟動。
3. **API key 不進命令列**：使用 `--set-secret-from-env` 或
   `--set-secret-from-env-as`；`NAME=VALUE` 可能留在 shell history 或 process listing。
4. **排除不等於刪除**：腳本會比較遠端檔案並透過 `delete_patterns` 清掉已停止上傳的舊檔，
   避免內部文件仍留在公開 Space。
5. **Front matter 有固定值域**：`colorFrom`／`colorTo` 只接受 Hugging Face 支援的顏色；
   腳本會在 upload 前驗證。

## 發布後驗收

- `/api/health` 與預期 provider/demo mode 一致。
- 公開檔案不含 `.env`、內部工作文件、真實資料或 API key。
- Container healthcheck 變成 healthy，host 端 health request 成功。
- 畫面與文件持續標示 Synthea synthetic data 與 non-clinical demo。
- External-provider 部署另行驗證 budget、rate limit、authentication 與 secret rotation；
  mock demo 通過不能替代這些驗證。
