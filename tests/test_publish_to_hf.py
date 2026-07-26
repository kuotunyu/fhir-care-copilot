"""publish_to_hf.py 的單元測試:只測 dry-run 路徑與純函式,不呼叫真實 HF API。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import publish_to_hf as pub  # noqa: E402


def test_main_defaults_to_dry_run(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("INFO")
    exit_code = pub.main(["--repo-id", "someone/fhir-care-copilot"])

    assert exit_code == 0
    assert "DRY RUN" in caplog.text


def test_main_dry_run_logs_expected_fields(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("INFO")
    exit_code = pub.main(["--repo-id", "someone/fhir-care-copilot", "--set-secret", "FOO=bar"])

    assert exit_code == 0
    text = caplog.text
    assert "someone/fhir-care-copilot" in text
    assert "DRY RUN" in text
    assert "FOO" in text
    assert "bar" not in text  # secret 的值不應該被印出來


def test_parse_secret_arg_splits_name_and_value() -> None:
    name, value = pub._parse_secret_arg("GEMINI_API_KEY=abc123")
    assert name == "GEMINI_API_KEY"
    assert value == "abc123"


def test_parse_secret_arg_rejects_missing_equals() -> None:
    with pytest.raises(ValueError, match="格式錯誤"):
        pub._parse_secret_arg("NOEQUALSSIGN")


def test_parse_secret_arg_rejects_empty_name() -> None:
    with pytest.raises(ValueError, match="缺少 secret 名稱"):
        pub._parse_secret_arg("=value")


def test_main_rejects_malformed_secret_without_executing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    exit_code = pub.main(["--repo-id", "someone/space", "--set-secret", "BROKEN"])
    assert exit_code == 1


def test_assemble_space_readme_prepends_front_matter(tmp_path: Path) -> None:
    project_readme = tmp_path / "README.md"
    project_readme.write_text("# 測試專案\n\n內容。\n", encoding="utf-8")

    combined = pub.assemble_space_readme(project_readme)

    assert combined.startswith("---\n")
    assert "sdk: docker" in combined
    assert "app_port: 7860" in combined
    assert "# 測試專案" in combined


def test_main_missing_readme_fails_before_any_network_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pub, "REPO_ROOT", tmp_path)
    exit_code = pub.main(["--repo-id", "someone/space"])
    assert exit_code == 1


class TestUploadSet:
    """發布時**實際會上傳哪些檔案**——ignore 樣式看起來對不代表結果對。

    原本的 dry-run 只印出排除樣式,不模擬檔案集合,所以看不出「README 連到的檔案
    被排除了」——那要等真的發布、點開 Space 首頁才會發現連結 404。實測就抓到兩個:
    整個 `reports/` 被排掉(README 連到 5 個 .md),以及 `.claude/*` 連 skills 一起
    排掉(README 連到 run-eval 的 SKILL.md)。
    """

    def test_secrets_are_never_uploaded(self) -> None:
        """**這是最不能錯的一條。** `.env` 上傳等於把金鑰公開。"""
        kept, _total = pub._simulate_upload()
        uploaded = {rel for rel, _size in kept}
        for path in (".env", ".claude/settings.local.json"):
            assert path not in uploaded, f"{path} 不該被上傳"
        assert not [p for p in uploaded if p.startswith(".env")], "任何 .env* 都不該上傳"

    def test_synthea_data_is_not_uploaded(self) -> None:
        """病患資料在 image build 時才下載,不進 repo 也不進 Space。"""
        kept, _total = pub._simulate_upload()
        uploaded = {rel for rel, _size in kept}
        assert not [p for p in uploaded if p.startswith("data/")]

    def test_readme_links_all_resolve_after_upload(self) -> None:
        """README 連到的 repo 內檔案都必須會被上傳,否則 Space 首頁上是死連結。

        這條擋的是**未來改 README 時再犯**:加一個連到被排除目錄的連結,
        測試就會紅,不必等發布之後才發現。
        """
        kept, _total = pub._simulate_upload()
        uploaded = {rel for rel, _size in kept}
        broken = pub._broken_readme_links(uploaded, pub.REPO_ROOT / "README.md")
        assert broken == [], f"README 連到但不會上傳的檔案:{broken}"

    def test_evidence_reports_are_uploaded(self) -> None:
        """`reports/*.md` 是「每個數字都指得回原始輸出」的落點,必須上傳;
        原始 JSON 有近 1 MB 且沒人會在網頁上讀,排掉。"""
        kept, _total = pub._simulate_upload()
        uploaded = {rel for rel, _size in kept}
        assert "reports/model_comparison_full.md" in uploaded
        assert not [p for p in uploaded if p.startswith("reports/") and p.endswith(".json")]
