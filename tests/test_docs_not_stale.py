"""目錄裡的東西有沒有被對應的 README 記到。

## 為什麼需要這個

這個專案反覆撞到同一個形狀的錯誤:**加了東西,某個手列的清單沒跟上**。
2026-07-27 一天之內就撞到四次:

1. 加第 6 個工具 → ``out_of_scope_questions_with_answers`` 寫死五個工具呼叫
2. 加第 5 個資料題型 → ``evaluate_case`` 寫死四個題型名稱
3. 題庫從 220 擴充到 254 → README 還寫著 220
4. 改名 + 新增兩支腳本 → ``scripts/README.md`` 一個都沒提

前三個已經改成從單一來源推導(registry / ``expected_resource_types``)。
第四個沒辦法「推導」——README 的內容本來就是人寫的。**推導不了的就用測試釘住。**

## 為什麼只釘 scripts/ 與 configs/

這兩個目錄的內容是**人工策展**的:每個檔案都該有存在的理由,而理由寫在 README。
``reports/`` 不釘,因為那裡是產物落地的地方,每跑一次量測就多幾個檔案,
要求逐檔記錄會變成噪音(那裡是用 ``eval_allergy_<model>.json`` 這種樣式描述的)。
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _readme_text(directory: str) -> str:
    return (REPO_ROOT / directory / "README.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("path", sorted((REPO_ROOT / "scripts").glob("*.py")), ids=lambda p: p.name)
def test_every_script_is_documented(path: Path) -> None:
    """``scripts/`` 底下每一支都要在 ``scripts/README.md`` 裡有一行。

    加腳本不寫一行說明,下一個人(包括三個月後的自己)就得靠讀程式碼才知道
    它為什麼存在。這條測試讓「忘了寫」在 commit 之前就紅。
    """
    assert path.name in _readme_text("scripts"), (
        f"scripts/{path.name} 沒有出現在 scripts/README.md 裡——加腳本要順手寫一行它為什麼存在"
    )


@pytest.mark.parametrize(
    "path", sorted((REPO_ROOT / "configs").glob("*.yaml")), ids=lambda p: p.name
)
def test_every_config_is_documented(path: Path) -> None:
    """``configs/`` 底下每一份設定都要在 ``configs/README.md`` 裡有一行。"""
    assert path.name in _readme_text("configs"), (
        f"configs/{path.name} 沒有出現在 configs/README.md 裡"
    )


def test_the_check_scans_something() -> None:
    """對照組:確認上面兩條真的有掃到檔案。

    參數化測試在「一個檔案都沒掃到」時會靜靜地零通過——那看起來跟全部通過
    一模一樣。這個專案已經因為「跑得動但沒量到」吃過虧,不再讓它發生。
    """
    assert len(list((REPO_ROOT / "scripts").glob("*.py"))) >= 10
    assert len(list((REPO_ROOT / "configs").glob("*.yaml"))) >= 3


def test_public_mock_deploy_instructions_remove_external_provider_state() -> None:
    """公開 mock 重發必須能覆蓋舊 provider,並移除已知 external API keys。"""
    deploy = (REPO_ROOT / "docs" / "DEPLOY.md").read_text(encoding="utf-8")
    public_mock = deploy.split("## 建議的公開作品集模式", 1)[1].split(
        "## 選配的私人 external-provider 模式", 1
    )[0]

    assert "--set-secret FHIR_COPILOT_PROVIDER=mock" in public_mock
    for name in (
        "GEMINI_API_KEY",
        "GEMINI_API_KEY_BACKUP",
        "GEMINI_API_KEY_BACKUP2",
        "GEMINI_API_KEY_BACKUP3",
        "OPENAI_API_KEY",
    ):
        assert f"--unset-secret {name}" in public_mock
