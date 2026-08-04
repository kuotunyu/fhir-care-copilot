# Product

> 使用 Synthea 合成病患的非臨床技術展示；不是診斷、治療或臨床決策工具。

## Purpose

FHIR Care Copilot 是可追溯、工具受控、預設唯讀的 FHIR 查詢工作台。審查者可選擇
synthetic patient、查看時間軸、以自然語言提問，並回查工具提供的 FHIR references。
Reference 可驗證不代表回答已逐句 grounded，也不代表臨床正確。

## Review scenario

介面以忙碌的長照資訊查詢情境作為設計假設：病患清單、時間軸與問答區各自清楚，
輸入位置容易找到，回答、拒答與證據狀態容易辨識。這是作品集中的工程原型；沒有使用
真實病歷、沒有臨床使用者研究，也沒有部署到實際照護流程。

## Product principles

1. 可用性優先於裝飾：字級、對比、焦點與輸入可見度必須清楚。
2. 可追溯與拒答是信任核心：FHIR references 與限制要能被審查。
3. Read-only 是架構邊界：agent allowlist 不包含 FHIR write tools。
4. 失敗狀態要誠實：demo、provider、authentication 與 audit 狀態不可混淆。
5. 不以測試、evaluation 或合成資料展示宣稱臨床可用。

## Visual language

「溫暖病歷夾」結合奶油紙色、深松石綠、赤陶橘與清楚的資訊層級。避免通用聊天玩具
或卡片堆疊式 SaaS 樣板；視覺不得暗示自動診斷、處方或醫療建議。

## Accessibility

介面提供 `:focus-visible` 焦點樣式、原生語意元素與 375px 響應式版面。這些是已實作的
前端工程控制，不等同完整 WCAG conformance audit 或臨床環境 usability validation。
