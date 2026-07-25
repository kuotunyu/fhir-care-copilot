"""呼叫者身分:API key 的來源、比對與降級行為。

金鑰**只從環境變數來**(專案硬規則),格式是逗號分隔的 ``label:key``:

    FHIR_COPILOT_API_KEYS="demo:sk-aaa,ops:sk-bbb"

label 存在的理由:限流要能區分呼叫者,而日誌與 metrics 只能記 label、
**永遠不記金鑰本身**。沒有 label 的話,要嘛不能分辨呼叫者,要嘛得把金鑰
(或它的雜湊)寫進日誌——兩者都不可接受。

降級行為(與 provider 缺金鑰自動退回 mock 同一個哲學):
``FHIR_COPILOT_REQUIRE_AUTH`` 預設 ``false`` → 放行,呼叫者記為 ``anonymous``。
服務不會因為少設一個環境變數就起不來,但 ``/api/health`` 會誠實標明現在沒開認證。
"""

from __future__ import annotations

import hmac
import logging
import os

logger = logging.getLogger(__name__)

API_KEYS_ENV = "FHIR_COPILOT_API_KEYS"
REQUIRE_AUTH_ENV = "FHIR_COPILOT_REQUIRE_AUTH"

ANONYMOUS = "anonymous"

_TRUTHY = frozenset({"1", "true", "yes", "on"})


def anonymous_bucket_key(client_host: str | None, forwarded_for: str | None) -> str:
    """匿名呼叫者的限流分桶依據:來源 IP。

    **為什麼不能所有匿名請求共用一個桶**:公開 demo(例如 HF Space)上沒有設定
    任何金鑰,於是每一位訪客都是 ``anonymous``。共用一個桶等於「全世界的訪客
    一起分 20 次/分鐘」,兩三個人同時玩就互相卡死——限流的職責是公平性,
    結果卻變成訪客互相餓死彼此。

    **誠實揭露的弱點**:反向代理後面拿不到真實 remote address,只能看
    ``X-Forwarded-For`` 的第一段,而那個 header **可以偽造**,有心人繞得過。
    這是可接受的,因為擋錢的主防線是全域每日預算上限(不分身分,偽造不了);
    限流管的是公平性,不是防惡意。

    回傳值只當作記憶體內的桶 key,**永遠不進日誌**(IP 是個人資料)。
    對外的身分標籤一律是 ``anonymous``。
    """
    if forwarded_for:
        first = forwarded_for.split(",")[0].strip()
        if first:
            return f"{ANONYMOUS}:{first}"
    if client_host:
        return f"{ANONYMOUS}:{client_host}"
    return ANONYMOUS


def require_auth() -> bool:
    return os.environ.get(REQUIRE_AUTH_ENV, "").strip().lower() in _TRUTHY


def load_api_keys() -> dict[str, str]:
    """回傳 ``{label: key}``。格式錯誤的項目跳過並警告,不讓服務起不來。"""
    raw = os.environ.get(API_KEYS_ENV, "").strip()
    if not raw:
        return {}
    keys: dict[str, str] = {}
    for item in raw.split(","):
        entry = item.strip()
        if not entry:
            continue
        label, separator, secret = entry.partition(":")
        if not separator or not label.strip() or not secret.strip():
            # 不印 entry 本身——它含金鑰
            logger.warning("%s 有一筆格式不符 'label:key' 的項目,已跳過", API_KEYS_ENV)
            continue
        keys[label.strip()] = secret.strip()
    return keys


def resolve_label(presented: str | None, keys: dict[str, str]) -> str | None:
    """比對出 label;比不到回 None。

    一律走完所有金鑰、用 ``hmac.compare_digest`` 比對,不提早 return——
    避免比對耗時洩漏「猜對了幾個字元」或「有幾把金鑰」。
    """
    if not presented:
        return None
    matched: str | None = None
    for label, secret in keys.items():
        if hmac.compare_digest(presented, secret):
            matched = label
    return matched
