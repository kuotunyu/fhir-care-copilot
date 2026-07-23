---
name: synthea-data
description: Synthea FHIR R4 資料管線——下載官方 1K 樣本、子集化、固定 seed 本地生成、驗證載入,以及 bundle 結構的實作要點。處理 data/ 目錄、重建資料、或寫讀取 FHIR 資料的程式時使用。
---

# synthea-data

## 指令

```bash
# 預設:下載 1K 樣本(85MB)→ 解壓 → 子集 100 位 → store 載入驗證(idempotent)
uv run python scripts/download_or_generate_synthea.py

# 不同子集大小 / 強制重建 / 只驗證
uv run python scripts/download_or_generate_synthea.py --subset 30
uv run python scripts/download_or_generate_synthea.py --force
uv run python scripts/download_or_generate_synthea.py --verify-only

# 本地生成(Java 17+,固定 seed → 同版本 Synthea 輸出一致)
uv run python scripts/download_or_generate_synthea.py --generate --seed 20260719 --population 500
```

## 事實(2026-07-19 實測)

- 樣本 zip:`synthea_sample_data_fhir_r4_sep2019.zip`,85,042,887 bytes,
  sha256 `a6fc595d9c0f4c646746af42f861b5a12d03c856af158dd837c764dfb81b66f8`
- 位置:zip 在 `data/raw/`、解壓在 `data/raw/fhir_r4_sep2019/`、子集在 `data/processed/subset_<N>/`
- 子集選取 deterministic:檔名排序取前 N
- `data/` 整目錄 gitignore;測試 fixture 在 `tests/data/fixtures/`(手工打造,會進 git)

## 讀資料的實作要點(踩雷防護,詳見 PLAN.md §7)

- 病患檔 = transaction Bundle;`hospitalInformation*`/`practitionerInformation*` 是 batch bundle → 跳過
- MedicationRequest 已結束的 status:sep2019 樣本用 `stopped`,v3.4.0+ 用 `completed` → 兩者都要接受
- 藥品編碼:`medicationCodeableConcept`(RxNorm)或 `medicationReference` → bundle 內 Medication → 兩種都要處理
- 參照:`urn:uuid:` 可在 bundle 內解析;`Type?query`(conditional search URL)不可解析 → 回 None 容忍
- 讀 JSON 一律 `encoding="utf-8"`(Windows 預設 cp950,ADR 0002 同族問題)
- 入口:`from fhir_copilot.store import LocalBundleFHIRStore`(唯讀;write 方法依 ADR 0001 不存在)
