"""publish_to_hf.py 的單元測試:只測 dry-run 路徑與純函式,不呼叫真實 HF API。"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import ClassVar

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


class _RecordingHfApi:
    """記下呼叫順序的假 HfApi。不連網,只證明**我們用什麼順序呼叫**。"""

    # 類別屬性:`_execute_publish` 自己 new 一個 HfApi,測試拿不到那個實例。
    calls: ClassVar[list[str]] = []

    def __init__(self, token: str | None = None) -> None:
        _RecordingHfApi.calls = []

    def create_repo(self, repo_id: str, **kwargs: object) -> None:
        self.calls.append("create_repo")

    def add_space_secret(self, repo_id: str, name: str, value: str) -> None:
        self.calls.append(f"secret:{name}")

    def upload_folder(self, **kwargs: object) -> None:
        self.calls.append("upload_folder")

    def upload_file(self, **kwargs: object) -> None:
        self.calls.append("upload_file")

    def delete_space_secret(self, repo_id: str, key: str) -> None:
        self.calls.append(f"unset:{key}")

    def restart_space(self, repo_id: str) -> None:
        self.calls.append("restart_space")


class TestPublishOrdering:
    """**順序就是正確性。** 2026-07-26 首次部署實測:Space 建起來、資料進去了、
    網頁完全正常,但 `/api/health` 回 `provider: mock`——因為腳本先上傳內容
    (觸發 HF 開始 build)、後設 secret,build 完成的容器裡根本沒有金鑰。

    而 `get_provider_name()` 是 `@lru_cache`,解析成 mock 就固定到 process 結束。
    也就是說:**全新部署必然跑成假 agent,而且外觀上看不出來。**
    """

    @pytest.fixture(autouse=True)
    def _fake_api(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HF_TOKEN", "fake-token-for-test")
        monkeypatch.setattr("huggingface_hub.HfApi", _RecordingHfApi)

    def test_secrets_are_set_before_any_content_upload(self) -> None:
        """這條就是那個 bug。把 secret 搬回上傳之後,這裡會紅。"""
        exit_code = pub.main(
            ["--repo-id", "someone/space", "--execute", "--set-secret", "GEMINI_API_KEY=k"]
        )

        assert exit_code == 0
        calls = _RecordingHfApi.calls
        assert calls.index("secret:GEMINI_API_KEY") < calls.index("upload_folder"), (
            f"secret 必須在上傳之前設定,實際順序:{calls}"
        )

    def test_space_is_restarted_after_secrets_change(self) -> None:
        """重跑時內容沒變就不會觸發 build,舊容器會繼續用舊環境——要明確重啟。"""
        pub.main(["--repo-id", "someone/space", "--execute", "--set-secret", "A=b"])

        calls = _RecordingHfApi.calls
        assert calls[-1] == "restart_space", f"重啟必須在最後,實際順序:{calls}"

    def test_secrets_are_removed_before_being_set(self) -> None:
        """換金鑰時「移除舊的」與「設定新的」是同一個動作的兩半。

        把 Space 從「跟開發共用的一堆備援金鑰」換成「一把專屬金鑰」時,
        只設定不移除的話,舊的那幾把會繼續留在雲端服務的設定裡
        ——**設定得了卻移除不了,等於金鑰只進不出**。
        """
        pub.main(
            [
                "--repo-id",
                "someone/space",
                "--execute",
                "--unset-secret",
                "GEMINI_API_KEY_BACKUP",
                "--set-secret",
                "GEMINI_API_KEY=new",
            ]
        )

        calls = _RecordingHfApi.calls
        assert "unset:GEMINI_API_KEY_BACKUP" in calls
        assert calls.index("unset:GEMINI_API_KEY_BACKUP") < calls.index("secret:GEMINI_API_KEY")
        assert calls.index("unset:GEMINI_API_KEY_BACKUP") < calls.index("upload_folder")

    def test_unsetting_alone_still_restarts(self) -> None:
        """只移除、不新增,也必須重啟——否則舊容器會繼續拿著那把金鑰跑。"""
        pub.main(["--repo-id", "someone/space", "--execute", "--unset-secret", "OLD_KEY"])

        assert _RecordingHfApi.calls[-1] == "restart_space"

    def test_no_restart_when_there_are_no_secrets(self) -> None:
        """沒有 secret 要生效就不必重啟——無謂的重啟會讓訪客斷線。"""
        pub.main(["--repo-id", "someone/space", "--execute"])

        assert "restart_space" not in _RecordingHfApi.calls


class TestFrontMatterValidation:
    """2026-07-26 真實發布時踩到的:``colorFrom: teal`` / ``colorTo: orange``
    兩個值都不在 HF 允許的顏色清單裡,``/api/validate-yaml`` 回 400。

    **痛點不在顏色,在時機。** dry-run 全過,``--execute`` 卻是在 ``upload_folder``
    把 184 個檔案傳完之後才炸——留下一個半完成的 Space。這是純本地、零成本就能
    檢出來的東西,dry-run 漏檢它等於沒有履行「先讓你看會發生什麼」的承諾。
    """

    def test_the_real_front_matter_is_valid(self) -> None:
        """**這條就是那個 400。** 顏色改回不合法的值,這裡會紅。"""
        assert pub.front_matter_problems(pub.SPACE_README_FRONT_MATTER) == []

    def test_rejects_colors_outside_the_allowed_set(self) -> None:
        bad = pub.SPACE_README_FRONT_MATTER.replace("colorFrom: blue", "colorFrom: teal")
        problems = pub.front_matter_problems(bad)
        assert any("colorFrom" in p and "teal" in p for p in problems)

    def test_rejects_non_integer_app_port(self) -> None:
        bad = pub.SPACE_README_FRONT_MATTER.replace("app_port: 7860", "app_port: '7860'")
        assert any("app_port" in p for p in pub.front_matter_problems(bad))

    def test_rejects_missing_required_key(self) -> None:
        bad = pub.SPACE_README_FRONT_MATTER.replace("title: FHIR Care Copilot\n", "")
        assert any("title" in p for p in pub.front_matter_problems(bad))

    def test_main_aborts_before_upload_when_front_matter_is_invalid(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """關鍵的一條:**擋在上傳之前**,不是上傳之後。"""
        monkeypatch.setattr(
            pub,
            "SPACE_README_FRONT_MATTER",
            pub.SPACE_README_FRONT_MATTER.replace("colorTo: green", "colorTo: orange"),
        )
        monkeypatch.setattr(
            pub, "_execute_publish", lambda *a, **k: pytest.fail("front-matter 壞掉不該走到上傳")
        )

        exit_code = pub.main(["--repo-id", "someone/space", "--execute"])
        assert exit_code == 1


class TestSecretFromEnv:
    """``--set-secret NAME=VALUE`` 會把金鑰留在 shell 歷史與 ps 的輸出裡。

    一個以「secret 只從環境變數來、永不進 git」為紀律的專案,發布指令本身卻要求
    把金鑰打在命令列上,是自相矛盾的。``--set-secret-from-env`` 只傳名稱。
    """

    def test_value_is_read_from_the_environment(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level("INFO")
        monkeypatch.setenv("FAKE_KEY_FOR_TEST", "s3cr3t-value")

        exit_code = pub.main(
            ["--repo-id", "someone/space", "--set-secret-from-env", "FAKE_KEY_FOR_TEST"]
        )

        assert exit_code == 0
        assert "FAKE_KEY_FOR_TEST" in caplog.text
        assert "s3cr3t-value" not in caplog.text  # 名稱印出來,值永遠不印

    def test_missing_variable_only_warns_during_dry_run(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """dry-run 要能在一台完全沒有金鑰的機器上跑完(例如 CI)。"""
        monkeypatch.delenv("FAKE_KEY_FOR_TEST", raising=False)
        exit_code = pub.main(
            ["--repo-id", "someone/space", "--set-secret-from-env", "FAKE_KEY_FOR_TEST"]
        )
        assert exit_code == 0

    def test_local_name_can_differ_from_the_space_name(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """本機與 Space 用不同的環境變數名稱。

        給 Space 一把專屬金鑰時,本機叫 GEMINI_API_KEY_SPACE(才不會蓋掉開發用的),
        但 Space 上必須叫 GEMINI_API_KEY——那是 models.yaml 的 api_key_env。
        **名字對不上的話 Space 會安靜退回 mock,不會報錯**,那正是這個專案
        2026-07-26 已經踩過一次的坑。
        """
        caplog.set_level("INFO")
        monkeypatch.setenv("GEMINI_API_KEY_SPACE", "space-only-key")

        exit_code = pub.main(
            [
                "--repo-id",
                "someone/space",
                "--set-secret-from-env-as",
                "GEMINI_API_KEY_SPACE:GEMINI_API_KEY",
            ]
        )

        assert exit_code == 0
        # 印出來的是 **Space 上的名字**,不是本機的
        assert "GEMINI_API_KEY" in caplog.text
        assert "space-only-key" not in caplog.text

    def test_malformed_rename_is_rejected(self) -> None:
        assert pub.main(["--repo-id", "someone/space", "--set-secret-from-env-as", "NOCOLON"]) == 1

    def test_missing_variable_aborts_before_publishing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """真的要發布時就不能含糊:少了值就中止,而且**在呼叫任何 HF API 之前**。

        否則 Space 會建起來、跑起來、然後因為沒有金鑰靜靜退回 mock demo mode
        ——看起來一切正常,實際上不是你要的東西。
        """
        monkeypatch.delenv("FAKE_KEY_FOR_TEST", raising=False)
        monkeypatch.setattr(
            pub, "_execute_publish", lambda *a, **k: pytest.fail("不該走到真的發布")
        )

        exit_code = pub.main(
            [
                "--repo-id",
                "someone/space",
                "--execute",
                "--set-secret-from-env",
                "FAKE_KEY_FOR_TEST",
            ]
        )
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
    排掉(當時 README 連到 run-eval 的 SKILL.md)。

    後者現在**刻意**整個排除:那份內容已搬到 `docs/EVAL.md`,`.claude/` 不再進 git。
    這條測試的價值不變——它擋的是「未來改 README 時連到不會上傳的東西」。
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

    def test_staged_copy_matches_the_simulated_upload_set(self, tmp_path: Path) -> None:
        """``--stage-dir`` 攤出來的必須**逐檔等於** dry-run 說會上傳的那一組。

        這條的意義在於:攤開的目錄就是拿去 `docker build` 驗證用的。如果它跟真的
        會上傳的檔案集合有落差,那 build 過了也只證明了另一份東西建得起來——
        這個專案已經因為「只驗到等效路徑」吃過好幾次虧。
        """
        dest = tmp_path / "stage"
        count, total = pub.stage_upload(dest, pub.REPO_ROOT / "README.md")

        kept, expected_total = pub._simulate_upload()
        expected = {rel for rel, _size in kept}
        actual = {p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file()}

        assert actual == expected
        assert count == len(kept)
        assert total == expected_total

    def test_staged_readme_carries_the_space_front_matter(self, tmp_path: Path) -> None:
        """攤開的 README 是組好 front-matter 的那一份,不是專案原本的 README。"""
        dest = tmp_path / "stage"
        pub.stage_upload(dest, pub.REPO_ROOT / "README.md")

        staged = (dest / "README.md").read_text(encoding="utf-8")
        assert staged.startswith("---\n")
        assert "app_port: 7860" in staged

    def test_stage_dir_refuses_to_overwrite_a_non_empty_directory(self, tmp_path: Path) -> None:
        dest = tmp_path / "stage"
        dest.mkdir()
        (dest / "既有檔案.txt").write_text("別動我", encoding="utf-8")

        with pytest.raises(ValueError, match="不是空的"):
            pub.stage_upload(dest, pub.REPO_ROOT / "README.md")

    def test_evidence_reports_are_uploaded(self) -> None:
        """`reports/*.md` 是「每個數字都指得回原始輸出」的落點,必須上傳;
        原始 JSON 有近 1 MB 且沒人會在網頁上讀,排掉。"""
        kept, _total = pub._simulate_upload()
        uploaded = {rel for rel, _size in kept}
        assert "reports/model_comparison_full.md" in uploaded
        assert not [p for p in uploaded if p.startswith("reports/") and p.endswith(".json")]
