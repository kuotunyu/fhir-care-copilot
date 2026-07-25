"""草稿簽章:證明這份草稿是這個系統產生的。

**為什麼認證擋不住這件事**:Phase 1 的 API key 回答的是「是誰打進來的」。
但 ``POST /api/care-notes/confirm`` 收的是一份完整的 ``CareNoteDraft``——
一個通過認證的呼叫者仍然可以送出從來沒有經過 ``propose`` 的內容,包括自己編的
``proposed_at``。那寫進稽核軌跡之後,防竄改鏈會忠實地保護一筆**一開始就是假的**紀錄。

作法:``propose`` 回傳草稿時附一個 HMAC 簽章,``confirm`` 驗簽後才寫。
無狀態——不需要伺服器端暫存草稿,也就沒有暫存過期、清理、多實例共享的問題。

**沒設定金鑰時**:用 process 啟動時產生的隨機金鑰。仍然擋得住偽造(攻擊者算不出
簽章),只是重啟後先前發出的草稿會失效——草稿本來就是短命的(使用者按下確認
之前的那幾秒),這個代價可以接受,而且維持了「少一個環境變數也能跑」。

多實例部署時**必須**設定共用金鑰,否則 A 實例發的草稿到 B 實例會驗不過。
這一點寫在 ``.env.example`` 與 README。
"""

from __future__ import annotations

import hmac
import os
import secrets
from hashlib import sha256

from fhir_copilot.ops.audit.chain import canonical_json

SIGNING_KEY_ENV = "FHIR_COPILOT_DRAFT_SIGNING_KEY"

# process 啟動時產生的臨時金鑰(沒設環境變數時用)。
# 模組層常數而不是每次呼叫都產生——後者會讓每一份草稿都用不同金鑰,
# 等於沒有簽章。
_EPHEMERAL_KEY = secrets.token_hex(32)


def signing_key() -> str:
    return os.environ.get(SIGNING_KEY_ENV, "").strip() or _EPHEMERAL_KEY


def key_is_configured() -> bool:
    """``/api/health`` 用來回報現在是設定的金鑰還是臨時金鑰。"""
    return bool(os.environ.get(SIGNING_KEY_ENV, "").strip())


def sign_draft(*, patient_id: str, note_text: str, proposed_at: str) -> str:
    """簽章涵蓋草稿的**全部**欄位。

    漏簽任何一個欄位,那個欄位就可以被竄改——例如只簽 ``patient_id`` 的話,
    攻擊者可以把 ``note_text`` 換成任意內容再拿原簽章送出。
    """
    payload = canonical_json(
        {"patient_id": patient_id, "note_text": note_text, "proposed_at": proposed_at}
    )
    return hmac.new(signing_key().encode("utf-8"), payload.encode("utf-8"), sha256).hexdigest()


def verify_draft(*, patient_id: str, note_text: str, proposed_at: str, signature: str) -> bool:
    expected = sign_draft(patient_id=patient_id, note_text=note_text, proposed_at=proposed_at)
    return hmac.compare_digest(expected, signature)
