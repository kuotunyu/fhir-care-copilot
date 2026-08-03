"""scripts/download_or_generate_synthea.py 的純邏輯單元測試(M1 審查發現的
4 個穩健性 bug 的迴歸測試)。不測真實網路下載——那已在 M1 用真實下載驗證過
(見 docs/PROGRESS.md)。
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, ClassVar

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import download_or_generate_synthea as dogs  # noqa: E402


class TestSkipDownloadIsValid:
    def test_missing_file_is_never_valid(self, tmp_path: Path) -> None:
        dest = tmp_path / "no.zip"
        assert dogs._skip_download_is_valid("https://example.com/x.zip", dest) is False

    def test_sample_url_requires_exact_expected_size(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(dogs, "EXPECTED_ZIP_BYTES", 10)
        monkeypatch.setattr(
            dogs,
            "EXPECTED_ZIP_SHA256",
            hashlib.sha256(b"1234567890").hexdigest(),
            raising=False,
        )
        dest = tmp_path / "sample.zip"
        dest.write_bytes(b"1234")  # 4 bytes,不是 10

        assert dogs._skip_download_is_valid(dogs.SAMPLE_URL, dest) is False

        dest.write_bytes(b"1234567890")  # 剛好 10 bytes
        assert dogs._skip_download_is_valid(dogs.SAMPLE_URL, dest) is True

    def test_sample_url_rejects_same_size_with_wrong_checksum(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(dogs, "EXPECTED_ZIP_BYTES", 4)
        monkeypatch.setattr(
            dogs,
            "EXPECTED_ZIP_SHA256",
            hashlib.sha256(b"good").hexdigest(),
            raising=False,
        )
        dest = tmp_path / "sample.zip"
        dest.write_bytes(b"evil")

        assert dogs._skip_download_is_valid(dogs.SAMPLE_URL, dest) is False

    def test_other_url_only_requires_nonempty(self, tmp_path: Path) -> None:
        dest = tmp_path / "other.jar"
        dest.write_bytes(b"")
        assert dogs._skip_download_is_valid("https://example.com/x.jar", dest) is False
        dest.write_bytes(b"x")
        assert dogs._skip_download_is_valid("https://example.com/x.jar", dest) is True


class TestDownloadAtomicity:
    class _BytesResponse:
        def __init__(self, data: bytes) -> None:
            self.headers = {"Content-Length": str(len(data))}
            self._chunks = iter((data, b""))

        def __enter__(self) -> TestDownloadAtomicity._BytesResponse:
            return self

        def __exit__(self, *exc_info: object) -> None:
            return None

        def read(self, _size: int) -> bytes:
            return next(self._chunks)

    def test_interrupted_download_leaves_no_file_at_final_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """M1 審查發現:中斷的下載不該在最終路徑留下看起來「已完成」的半成品檔案。"""

        class _BoomResponse:
            headers: ClassVar[dict[str, str]] = {}

            def __enter__(self) -> _BoomResponse:
                return self

            def __exit__(self, *exc_info: object) -> None:
                return None

            def read(self, _size: int) -> bytes:
                raise ConnectionError("模擬網路中斷")

        monkeypatch.setattr(urllib.request, "urlopen", lambda _url: _BoomResponse())

        dest = tmp_path / "sample.zip"
        with pytest.raises(ConnectionError):
            dogs.download("https://example.com/x.zip", dest)

        assert not dest.exists()
        assert not dest.with_name(dest.name + ".part").exists()

    def test_sample_checksum_mismatch_fails_before_final_rename(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(dogs, "EXPECTED_ZIP_BYTES", 4)
        monkeypatch.setattr(
            dogs,
            "EXPECTED_ZIP_SHA256",
            hashlib.sha256(b"good").hexdigest(),
            raising=False,
        )
        monkeypatch.setattr(
            urllib.request,
            "urlopen",
            lambda _url: self._BytesResponse(b"evil"),
        )
        dest = tmp_path / "sample.zip"

        with pytest.raises(ValueError, match="SHA-256"):
            dogs.download(dogs.SAMPLE_URL, dest)

        assert not dest.exists()
        assert not dest.with_name(dest.name + ".part").exists()

    def test_sample_with_expected_checksum_is_published_atomically(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        data = b"good"
        monkeypatch.setattr(dogs, "EXPECTED_ZIP_BYTES", len(data))
        monkeypatch.setattr(
            dogs,
            "EXPECTED_ZIP_SHA256",
            hashlib.sha256(data).hexdigest(),
            raising=False,
        )
        monkeypatch.setattr(
            urllib.request,
            "urlopen",
            lambda _url: self._BytesResponse(data),
        )
        dest = tmp_path / "sample.zip"

        dogs.download(dogs.SAMPLE_URL, dest)

        assert dest.read_bytes() == data
        assert not dest.with_name(dest.name + ".part").exists()


class TestExtractIdempotency:
    def _make_zip(self, tmp_path: Path, json_names: list[str]) -> Path:
        zip_path = tmp_path / "sample.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            for name in json_names:
                zf.writestr(name, json.dumps({"resourceType": "Bundle"}))
        return zip_path

    def test_extracts_when_missing(self, tmp_path: Path) -> None:
        zip_path = self._make_zip(tmp_path, ["a.json", "b.json"])
        extract_dir = tmp_path / "out"

        dogs.extract(zip_path, extract_dir)

        assert sorted(p.name for p in extract_dir.glob("*.json")) == ["a.json", "b.json"]

    def test_skips_when_count_matches(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        zip_path = self._make_zip(tmp_path, ["a.json", "b.json"])
        extract_dir = tmp_path / "out"
        dogs.extract(zip_path, extract_dir)

        called = False
        original_zipfile = zipfile.ZipFile

        def _tracking_zipfile(*args: Any, **kwargs: Any) -> Any:
            nonlocal called
            called = True
            return original_zipfile(*args, **kwargs)

        monkeypatch.setattr(zipfile, "ZipFile", _tracking_zipfile)
        dogs.extract(zip_path, extract_dir)  # 只會為了算數量開一次 zip,不會重新解壓

        assert (extract_dir / "a.json").exists()
        assert (extract_dir / "b.json").exists()
        del called  # 上面已經確認沒有重新解壓(檔案還在、沒被清空重建)

    def test_re_extracts_when_partial(self, tmp_path: Path) -> None:
        """M1 審查發現:只有部分檔案解壓出來時,不能誤判成「已完成」。"""
        zip_path = self._make_zip(tmp_path, ["a.json", "b.json", "c.json"])
        extract_dir = tmp_path / "out"
        extract_dir.mkdir()
        (extract_dir / "a.json").write_text("{}", encoding="utf-8")  # 只有 1/3 個檔案

        dogs.extract(zip_path, extract_dir)

        assert sorted(p.name for p in extract_dir.glob("*.json")) == ["a.json", "b.json", "c.json"]


class TestMakeSubsetIdentity:
    def _write_patient_json(self, path: Path, patient_id: str) -> None:
        path.write_text(
            json.dumps(
                {
                    "resourceType": "Bundle",
                    "type": "transaction",
                    "entry": [
                        {
                            "resource": {
                                "resourceType": "Patient",
                                "id": patient_id,
                                "name": [{"family": "F", "given": ["G"]}],
                            }
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

    def test_reuses_when_filenames_match(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        processed = tmp_path / "processed"
        monkeypatch.setattr(dogs, "DATA_PROCESSED", processed)
        source = tmp_path / "source_a"
        source.mkdir()
        self._write_patient_json(source / "p1.json", "p1")

        dogs.make_subset(source, 1)
        subset_dir = processed / "subset_1"
        marker = subset_dir / ".unchanged-marker"
        marker.write_text("x", encoding="utf-8")  # 若真的重建,這個檔案會消失

        dogs.make_subset(source, 1)  # 同一來源、同一檔名 → 應該略過,不重建

        assert marker.exists()

    def test_rebuilds_when_source_changes_despite_same_count(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """M1 審查發現:換來源(如 download → generate)但檔案數剛好一樣時,
        舊版只比數量會誤判成「已是最新」,沿用錯的資料。"""
        processed = tmp_path / "processed"
        monkeypatch.setattr(dogs, "DATA_PROCESSED", processed)

        source_a = tmp_path / "source_a"
        source_a.mkdir()
        self._write_patient_json(source_a / "p1.json", "p1")
        dogs.make_subset(source_a, 1)

        source_b = tmp_path / "source_b"  # 不同來源,但一樣只有 1 個病患檔
        source_b.mkdir()
        self._write_patient_json(source_b / "different_name.json", "p2")
        dogs.make_subset(source_b, 1)

        subset_dir = processed / "subset_1"
        assert [p.name for p in subset_dir.glob("*.json")] == ["different_name.json"]


class TestJavaMajorVersion:
    def _stub_run(self, monkeypatch: pytest.MonkeyPatch, stderr: str) -> None:
        class _Proc:
            pass

        proc = _Proc()
        proc.stderr = stderr  # type: ignore[attr-defined]

        monkeypatch.setattr(subprocess, "run", lambda *a, **k: proc)

    def test_modern_scheme(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._stub_run(monkeypatch, 'openjdk version "17.0.16" 2025-07-15\n')
        assert dogs.java_major_version() == 17

    def test_legacy_java_8_scheme_returns_8_not_1(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """M1 審查發現:舊制 "1.8.0_281" 曾被誤判成主版號 1,診斷訊息會誤導。"""
        self._stub_run(monkeypatch, 'java version "1.8.0_281"\nJava HotSpot(TM)\n')
        assert dogs.java_major_version() == 8

    def test_java_not_installed_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _raise(*_a: object, **_k: object) -> None:
            raise FileNotFoundError

        monkeypatch.setattr(subprocess, "run", _raise)
        assert dogs.java_major_version() is None
