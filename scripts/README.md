# scripts/

預計腳本（隨 milestone 建立）：

- `download_or_generate_synthea.py`（M1）— 下載官方 1K FHIR R4 樣本 + `--subset N` 子集化；
  偵測到 Java 17+ 時可固定 seed 本地生成
- eval CLI（M5–M6）— case 生成、執行、預算守門、報告產出
- `publish_to_hf.py`（M7）— 發布到 Hugging Face Docker Space,**預設 dry-run**
