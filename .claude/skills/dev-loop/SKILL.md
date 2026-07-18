---
name: dev-loop
description: FHIR Care Copilot 開發迴圈——環境同步、測試、lint、typecheck、pre-commit 指令,以及每個 session/milestone 的收尾 checklist。開始實作、跑測試、或收尾 milestone 時使用。
---

# dev-loop

## 日常指令

| 動作 | just | 直接指令 |
|---|---|---|
| 同步環境 | `just sync` | `uv sync` |
| 測試 | `just test` | `uv run pytest` |
| lint | `just lint` | `uv run ruff check .` + `uv run ruff format --check .` |
| 自動修排版 | `just fmt` | `uv run ruff check --fix .` + `uv run ruff format .` |
| 型別 | `just typecheck` | `uv run mypy` |
| 全套 | `just check` | 上面三項依序 |
| pre-commit | `just precommit` | `uv run pre-commit run --all-files` |

注意:Windows 上 `just` 由 winget 安裝(`Casey.Just`),新開的 shell 才吃得到 PATH。

## session 開始

1. 讀 `PLAN.md` §3 checkbox 進度
2. 讀 `docs/PROGRESS.md` 最上面一節(最新)
3. 依 milestone 順序做,不跳關

## session / milestone 收尾 checklist

1. `just check`(或 `uv run pytest` 等)全綠——失敗就修,修不完照實記錄
2. `docs/PROGRESS.md` **最上方**新增一節:日期、做了什麼、**真實測試輸出**、決策/發現、下一步
3. milestone 全部驗收達成才勾 `PLAN.md` §3 checkbox
4. git commit(訊息格式:`M<N>: <摘要>`)
5. 有穩定下來的新流程 → 固化成 `.claude/skills/` 專案 skill
