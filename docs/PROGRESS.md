# 進度日誌（PROGRESS）

> 目的：讓隔一段時間回來的人（包括未來的我們）在 2 分鐘內接上進度。
> 規則：**新的紀錄放最上面**（reverse chronological）。每個 session / milestone 結束時新增一節。
> 每節固定格式：日期、做了什麼、真實測試輸出摘要（照實貼、失敗也記）、決策/發現、下一步。

---

## 2026-07-24 — M1 收尾 + M2 + M3 完成 ✅（含真實 Gemini/OpenAI 端到端測試）

**背景**：使用者授權整晚自主開工（只交代不 push、GitHub Contributors 保持乾淨）。session 中途從 Fable 5 切到 Sonnet 5（額度問題），不影響進度。M1/M2 分別跑了 21-agent 與 16-agent 多視角審查（含直接對真實下載的 100 位病患資料寫探針驗證），M3 做了 agent loop + 三個 provider + 兩次真實 API 端到端測試。

**做了什麼**

*M1 收尾（store 層 21-agent 審查修正）*
- 🔴 **HIGH**：`_build_index` 原本只接 `(OSError, json.JSONDecodeError)`，非 UTF-8 的壞檔會丟出 `UnicodeDecodeError`（`ValueError` 子類別、不在原本的 except 裡），讓整個 store 初始化直接炸掉，而不是照設計跳過該檔 → 改成 `except (OSError, ValueError)`，補迴歸測試
- ⚠️ **PLAN.md §7 的「查證事實」被真實資料推翻**：原始 spec 依二手文件寫「transaction 模式下 Practitioner/Organization/Location 不在病患 bundle 內、用 conditional search URL 參照」——3 個獨立審查視角交叉掃描全部 1,280 個真實 patient bundle、190 萬筆 reference 欄位，**0 筆是 conditional search URL**：Practitioner/Organization 其實都內嵌在 bundle 內、用 `urn:uuid` 正常解析，只有 Location 真的沒出現。真正無法解析的參照是 `#` 開頭的 contained resource 參照（只在 `ExplanationOfBenefit`，1K 樣本裡 93,736 筆，之前完全沒被記錄）→ 修正 PLAN.md §7、`store/local.py`、`store/base.py` 的文件；fixture 改成用真實資料的 urn:uuid 模式，conditional-search-URL 與 `#` 參照都保留為防禦性測試案例
- 下載腳本 4 個穩健性 bug（都是真實會發生的情境，非假設）：`download()` 中斷後留下看似完整的半成品檔案 → 改成下載到 `.part` 暫存檔、成功才原子性 rename；`extract()` 只看「有沒有任一檔案」判斷已完成 → 改成比對 zip 內實際 `.json` 數；`make_subset()` 只比數量、不比檔名 → 換來源（下載↔生成）但數量剛好一樣時會誤判成最新 → 改成比對實際檔名集合；`java_major_version()` 誤判 Java 8 舊制版號 `"1.8.0_281"` 為主版號 1（不影響拒絕判斷，但診斷訊息誤導）→ 修正
- 新增 `tests/test_download_script.py`（12 個測試，純邏輯、不碰真實網路）

*M2 收尾（工具層 16-agent 審查修正，含對真實 100 位病患跑全部 5 個工具）*
- `_value_display()` 沒處理 `valueString`（social-history 類別常見，如居住/受虐狀況）→ 靜默回傳 `None`，跟「真的沒資料」無法區分——對長照個案是會漏掉「居無定所」這種事實的安全性問題（4 個審查視角獨立發現，1 個評 HIGH）→ 補上 `valueString` 分支
- `effectiveDateTime`/`period.start` 直接比字串排序，真實資料混用 `-04:00`/`-05:00`（跨年份的日光節約時間）時字串排序會跟實際時間相反（目前樣本剛好沒觸發過，但邏輯上證實是錯的）→ 改用 `fhir_utils.datetime_sort_key()` 比較真正的 datetime
- `list_active_medications` 透過 `medicationReference` 解析出的藥名，evidence 只引用了 `MedicationRequest`（只證明 status=active，證不到藥名本身）→ 補一筆指向實際 `Medication` resource 的 evidence
- 新增 `tests/test_fhir_utils.py`、fixture 補 `valueString` 觀察值與第二個 `medicationReference` 案例

*M3（agent loop + providers，全新實作）*
- `AgentResponse` 回應契約（`answer/evidence/limitations/refused/model/latency_ms/input_tokens/output_tokens/estimated_cost_usd`）
- `configs/{models,pricing,guardrails}.yaml` 真的接進程式（`src/fhir_copilot/config.py`）——修正了一個中途發現的架構漏洞：一開始 provider 的 `model_id` 是寫死在 class attribute，`configs/models.yaml` 只是裝飾用；改成 provider 建構子吃 `model_id` 參數，`providers/factory.py` 從設定檔讀入再傳進去
- `agent/loop.py`：max tool rounds / timeout / 輸入長度上限護欄；任一工具 `ok=False`（病患不存在)立刻結構化拒答，不再問 LLM；**病患範圍由 loop 直接注入每個工具呼叫**，LLM 連 schema 裡都看不到 `patient_id`（`tools/registry.py:llm_facing_schema`），就算 LLM 硬塞別的 patient_id 進參數也會被覆蓋——寫了 ADR 0003 記錄這個 prompt injection 防線，並有專門測試鎖定
- 三個 provider：`MockProvider`（deterministic 關鍵字選工具，CI 用）、`GeminiProvider`（google-genai，手動 function calling，關閉 automatic calling）、`OpenAIProvider`（Responses API，用 `previous_response_id` 串多輪）
- `propose_care_note` + `confirm_and_log`（`src/fhir_copilot/care_notes.py`）：只組草稿、不寫任何東西；**刻意不進入**唯讀 agent loop 的工具清單（測試鎖定這件事）；UI 確認後才呼叫 `confirm_and_log` 附加寫入本地 audit log JSONL，FHIRStore 介面本身沒有 write 方法，結構上不可能寫回 FHIR

**真實測試輸出**
```
uv run pytest         → 80 passed in 1.42s
uv run mypy            → Success: no issues found in 43 source files
uv run ruff check .    → All checks passed!

# 真實下載腳本重跑(驗證 M1 修正後仍 idempotent)
INFO 已存在且大小正確,略過下載:synthea_sample_data_fhir_r4_sep2019.zip(85042887 bytes)
INFO 已解壓,略過:...\fhir_r4_sep2019(1180 個 .json)
INFO 子集已存在且內容相符,略過:...\subset_100(100 檔)
INFO 驗證:成功載入 100 位病患

# 真實 Gemini(gemini-3.1-flash-lite)端到端(問「生效中的診斷」,病患 Aaron697 Brekke496)
answer: 這位病患目前有以下生效中的診斷:1. Cardiac Arrest ... 2. History of cardiac arrest ...
        3. Body mass index 30+ - obesity ... 4. Prediabetes ... 5. Anemia (disorder) ...
refused: False | evidence count: 5(全部是 Condition resourceType/id/clinicalStatus=active)
model: gemini-3.1-flash-lite | latency_ms: 1580 | input_tokens: 1456 | output_tokens: 174
estimated_cost_usd: 0.000625

# 真實 OpenAI(gpt-5.4-mini)同一題
answer: 這位病患目前生效中的診斷有 5 項:1. Cardiac Arrest 2. History of cardiac arrest ...
refused: False | evidence count: 5(與 Gemini 一致)
model: gpt-5.4-mini | latency_ms: 3088 | input_tokens: 1178 | output_tokens: 122
estimated_cost_usd: 0.0014325
```

**決策 / 發現**
- 🔥 **模型現況會漂移，即使查證日期只差 5 天**：7/19 查證 `gemini-2.5-flash-lite` 是 GA 現行模型；7/24 實測發現這把金鑰打它回 404「對新使用者已下架」（`client.models.list()` 卻仍列得出來——列表≠可呼叫）。改用 `gemini-3.1-flash-lite`（已實測成功），定價從 $0.10/$0.40 變成 $0.25/$1.50 per 1M tokens（仍便宜，200 題 eval 預算影響可忽略）。教訓：**model_id 一定要走 config 才扛得住這種漂移**——這也是這次順手修掉「model_id 寫死在 provider class」架構漏洞的直接動機
- Workflow 背景審查偶爾會卡住不動（M1 第一次跑 21 個 agent 卡在 1/5 完成十幾分鐘無進度，疑似跟同時跑 M2 審查搶併發額度有關）→ 直接 `TaskStop` 重跑一次就正常跑完，沒有更深入排查，記錄下來供之後參考
- `propose_care_note` 的設計關鍵：**不放進唯讀 agent loop 的工具清單**，是獨立於問答對話的動作路徑，避免被使用者的一般提問意外觸發草稿生成——這個邊界用測試鎖住了

**下一步**
- M4：FastAPI endpoints + React/Vite 工作台（病患選擇器、時間軸、對話區、證據抽屜、cost badge、拒答狀態）；vite build 由 FastAPI serve
- M4 開工時記得先驗證 node/vite 在這個含中文與空格的路徑上能不能跑(PLAN.md §10 風險表還沒驗證這塊)
- commit 這次的 M1 修正 + M2 修正 + M3 全部(目前都還是 working tree 裡未 commit 的變更)

---

## 2026-07-19 — M0 工程骨架完成 ✅

**做了什麼**
- 本機 `git init -b main`（無 remote）；uv + pyproject（**Python 3.13**，非原定 3.11，見下）；目錄與 22 個骨架檔案
- README 骨架（Synthea 來源/Apache-2.0/引用）、ADR 0001（scope/threat model）、ADR 0002（Python 3.13）
- ruff + mypy(strict) + pytest + pre-commit（hooks autoupdate 至 v6.0.0 / ruff v0.15.22）+ GitHub Actions + justfile
- `just`（1.56.0）已由 winget 安裝（新開 shell 才吃得到 PATH）
- 12-agent 多視角審查（設定/CI/文件/secret 四鏡頭 + 逐 finding 反駁式驗證）：確認並修正 4 項

**真實測試輸出**
```
uv run pytest        → 1 passed in 0.01s
uv run ruff check .  → All checks passed!
uv run ruff format --check . → 2 files already formatted
uv run mypy          → Success: no issues found in 2 source files
uv run pre-commit run --all-files → 9 hooks 全部 Passed
just check           → 全綠(just 1.56.0)
uv run python -V     → Python 3.13.13
```

**決策 / 發現**
- 🔥 **中文路徑地雷（已解）**：Python 3.11/3.12 的 `site` 讀 `.pth` 固定用 cp950（`PYTHONUTF8=1` 實測無效），editable install 的 UTF-8 路徑直接讓 venv 啟動即炸 → **改用 Python 3.13**（`.pth` 改 UTF-8 解碼），全部恢復正常。詳見 ADR 0002
- pre-commit 用系統 locale 讀自己的設定檔 → `.pre-commit-config.yaml` 必須 **ASCII-only**（中文註解會炸，實測）
- cp950 第三例：`pre-commit install` 的 hook 以 Big5 嵌 venv 路徑 → 改用 repo 內建 hook（`core.hooksPath scripts/git-hooks`、`uv run` 不嵌路徑），commit 時 9 個 hooks 實測通過
- 審查修正：`.gitignore` 的 `data/` 錨定為 `/data/`（否則 M1 的 `tests/data/` fixture 會被默默忽略）；CI 改 `uv sync --locked`；setup-uv 釘 `v8.3.2`（**v8 起廢除 major tag，`@v8` 不存在**）；README 殘留 3.11 字樣清除
- `.env` 確認未被追蹤；`git check-ignore` 驗證 `.env`、`data/` 生效

**下一步**
- M1 資料層：下載腳本（1K 樣本 + `--subset 100`）、`FHIRStore` protocol + `LocalBundleFHIRStore`、手工裁剪 fixture（含 `stopped`/`completed` 兩種藥物狀態）
- Java 17 已確認在機器上（openjdk 17.0.16）→ 固定 seed 生成路徑可做

---

## 2026-07-19 — 規劃階段完成（尚未動工 M0）

**做了什麼**
- 完成專案規劃：`PLAN.md`（權威版本）、本檔、`CLAUDE.md` 建立
- 以 10 個研究/驗證 agents 查證外部事實（51 個來源 URL 逐一 fetch 驗證，全數通過），結果寫入 PLAN.md §7

**真實測試輸出**
- 無（本階段不寫程式）

**決策 / 發現**
- 官方無 100 位病患 R4 樣本包 → 改抓已驗證的 1K 樣本（85MB）+ `--subset 100`
- `gpt-5.4-mini` 存在（$0.75/$4.50 per 1M）；Gemini 2.5 Flash-Lite（$0.10/$0.40）→ 雙模型全量 eval 估 ~$0.6
- sep2019 樣本停用藥 status 是 `stopped`（新版 `completed`）；藥品編碼兩種形式都要支援
- 已確認：文件與 UI 正體中文、React + Vite、Apache-2.0、不整合 W&B（完整決策表見 PLAN.md §8）

**下一步**
- M0：git init、uv 骨架、目錄結構、README 骨架（Synthea 來源/授權/引用）、`docs/decisions/0001-scope.md`、lint/test/CI 骨架、justfile
- M0 第一件事：在目前路徑（含中文與空格）驗證 uv / node / docker 工具鏈是否正常

---

<!-- 新紀錄往上加，格式範本：

## YYYY-MM-DD — <milestone 或 session 主題>

**做了什麼**
-

**真實測試輸出**
```
（貼上 pytest / eval 等關鍵輸出，失敗也照實記）
```

**決策 / 發現**
-

**下一步**
-

-->
