# 進度日誌（PROGRESS）

> 目的：讓隔一段時間回來的人（包括未來的我們）在 2 分鐘內接上進度。
> 規則：**新的紀錄放最上面**（reverse chronological）。每個 session / milestone 結束時新增一節。
> 每節固定格式：日期、做了什麼、真實測試輸出摘要（照實貼、失敗也記）、決策/發現、下一步。

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
