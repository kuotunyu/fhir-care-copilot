"""committed 進 repo 的報告檔必須是 pre-commit 乾淨的。

這個檔案存在的理由是**同一個錯誤犯了三次**:

1. `reports/loadtest/*.json` —— `json.dumps()` 沒有結尾換行
2. `reports/injection_ab.md` —— `"\\n".join(...)` 之後又多加一個 `"\\n"`,變成兩個
3. `reports/e2e_sample_*.json` —— 又是 `json.dumps()` 沒有結尾換行;
   同一次還有 `model_comparison_full.md` 行尾帶空白(逐字稿是模型原文,
   模型很常在句末留兩個空格當 markdown 換行)

每次的症狀都一樣:`git commit` 被 `trailing-whitespace` / `end-of-file-fixer`
擋下,檔案被 hook 改掉,commit 中止,要重新 `git add`。而每次都是**產出檔案的
那支程式**寫錯,不是檔案本身的問題。

**修在源頭之後還需要這個測試**,因為源頭有好幾個(至少四支產生器),而下一支
新寫的產生器不會知道前面踩過什麼。這裡直接對產物斷言,新產生器一寫錯就會被抓到。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
REPORTS = REPO_ROOT / "reports"

# 只檢查文字檔;reports/ 底下目前沒有二進位檔,但之後可能會有截圖之類的
_TEXT_SUFFIXES = {".md", ".json", ".jsonl", ".txt", ".csv"}


def _report_files() -> list[Path]:
    if not REPORTS.is_dir():
        return []
    return sorted(p for p in REPORTS.rglob("*") if p.is_file() and p.suffix in _TEXT_SUFFIXES)


def _relative(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


@pytest.mark.parametrize("path", _report_files(), ids=_relative)
def test_report_ends_with_exactly_one_newline(path: Path) -> None:
    """``end-of-file-fixer`` 要求結尾恰好一個換行。

    用位元組比對而不是 ``text.endswith("\\n")``:CRLF 的最後兩個位元組是 ``\\r\\n``,
    所以 ``endswith(b"\\n\\n")`` 對 ``\\r\\n\\r\\n`` 會回 False——**檢查本身被 CRLF 騙過一次**。
    """
    raw = path.read_bytes()
    assert raw, f"{_relative(path)} 是空檔"
    text = raw.decode("utf-8")
    trailing = re.search(r"((?:\r?\n)*)$", text)
    assert trailing is not None
    count = len(trailing.group(1).replace("\r", ""))
    assert count == 1, f"{_relative(path)} 結尾有 {count} 個換行,應該恰好 1 個"


@pytest.mark.parametrize("path", _report_files(), ids=_relative)
def test_report_has_no_trailing_whitespace(path: Path) -> None:
    """``trailing-whitespace`` 要求每行結尾沒有空白。

    最常見的來源是**嵌進報告的模型原始回答**——模型很愛在句末留兩個空格。
    產生器要負責 rstrip,不能指望模型輸出乾淨。
    """
    text = path.read_bytes().decode("utf-8")
    offenders = [i + 1 for i, line in enumerate(text.splitlines()) if line != line.rstrip()]
    assert not offenders, f"{_relative(path)} 第 {offenders[:10]} 行的行尾有空白"


def test_there_are_reports_to_check() -> None:
    """對照組:如果 glob 寫錯導致一個檔案都沒掃到,上面兩個測試會空跑通過。"""
    assert len(_report_files()) >= 5
