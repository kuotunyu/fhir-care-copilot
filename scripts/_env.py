"""互動式腳本共用的 `.env` 載入。

**專案的程式碼(``src/``)刻意不讀 `.env`**——secret 只從環境變數來,那是硬規則。
但手動跑的腳本(eval、取樣、發布)需要金鑰,總不能每次都叫使用者自己 export,
所以由腳本這一層顯式載入。這條界線要守住:載入發生在 ``scripts/``,不在 ``src/``。

原本這段在 ``run_injection_repeats.py`` 與 ``run_e2e_sample.py`` 各有一份逐字相同的
複製;第三支要用時抽出來,免得「哪一份才算數」變成新的問題。
"""

from __future__ import annotations

import os
from pathlib import Path


def load_env_file(path: Path) -> None:
    """把 ``.env`` 的內容注入 ``os.environ``。

    用 ``setdefault``:**真實環境變數優先**。已經在環境裡設好的值不會被檔案蓋掉,
    所以 CI 或臨時覆寫都還是說了算。檔案不存在就安靜跳過。
    """
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
