# FHIR Care Copilot

> ⚠️ **這不是醫療診斷工具。** 本專案僅用於展示 healthcare interoperability 與 LLM agent 工程，
> 所有病患資料皆為 [Synthea](https://github.com/synthetichealth/synthea) 產生的**合成資料**，不含任何真實個資。

以 Synthea 公開合成病患 FHIR R4 資料為基礎的**長照個案查詢 copilot**：可追溯、工具受控、預設唯讀。
LLM 不直接接觸資料庫、不憑記憶回答病患事實——每個病患事實都由 deterministic tool 回傳並附
FHIR `resourceType/id` 證據；資料不足時明確拒答。

**專案狀態**：🚧 M0 工程骨架（完整 milestones 見 [PLAN.md](PLAN.md)）

## 90 秒 demo

（M4 完成後補上：一行指令啟動 → 選病患 → 問一題 → 看證據抽屜與 cost badge → 看拒答行為）

## 架構

（M7 完成完整版；目前見 [PLAN.md](PLAN.md) §4 的 Mermaid 圖與資料流說明）

## 開發

```bash
uv sync          # 建環境(Python 3.13,由 uv 管理;版本選擇原因見 ADR 0002)
uv run pytest    # 跑測試
uv run ruff check .
uv run mypy
```

或安裝 [just](https://github.com/casey/just) 後直接 `just check`。

## 資料來源與授權

- 病患資料：[Synthea](https://github.com/synthetichealth/synthea)（MITRE）產生之合成資料，授權 **Apache-2.0**
- 樣本資料集：[synthea-sample-data](https://github.com/synthetichealth/synthea-sample-data)（1K Sample Synthetic Patient Records, FHIR R4）
- 引用：

> Walonoski J, Kramer M, Nichols J, Quina A, Moesel C, Hall D, Duffett C, Dube K, Gallagher T, McLachlan S.
> *Synthea: An approach, method, and software mechanism for generating synthetic patients and the synthetic electronic health care record.*
> Journal of the American Medical Informatics Association. 2018;25(3):230-238. https://doi.org/10.1093/jamia/ocx079

## 安全邊界

見 [docs/decisions/0001-scope.md](docs/decisions/0001-scope.md)：synthetic-only、read-only default、
prompt injection 邊界、人工確認點。

## 授權

程式碼以 Apache-2.0 釋出（LICENSE 檔於 M7 加入）。

## 截圖

（M7 補上 screenshots placeholder）
