"""下載或生成 Synthea FHIR R4 合成病患資料,並子集化供開發使用。

預設流程(不需任何金鑰):
    uv run python scripts/download_or_generate_synthea.py
    1. 下載官方 1K 樣本 zip 到 data/raw/(已驗證 URL)
    2. 解壓到 data/raw/fhir_r4_sep2019/
    3. 取前 N 位(檔名排序,deterministic)複製到 data/processed/subset_<N>/
    4. 以 LocalBundleFHIRStore 載入驗證並列出病患

本地生成(需 Java 17+;相同 seed + 相同 Synthea 版本輸出一致):
    uv run python scripts/download_or_generate_synthea.py --generate \
        --seed 20260719 --population 500

data/ 整個目錄已 gitignore——任何輸出都不會進 git。
"""

from __future__ import annotations

import argparse
import hashlib
import io
import logging
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_RAW = REPO_ROOT / "data" / "raw"
DATA_PROCESSED = REPO_ROOT / "data" / "processed"

# 已驗證(2026-07-19,HTTP 200):1K Sample Synthetic Patient Records, FHIR R4
SAMPLE_URL = (
    "https://synthetichealth.github.io/synthea-sample-data/downloads/"
    "synthea_sample_data_fhir_r4_sep2019.zip"
)
SAMPLE_ZIP = DATA_RAW / "synthea_sample_data_fhir_r4_sep2019.zip"
SAMPLE_EXTRACT_DIR = DATA_RAW / "fhir_r4_sep2019"
EXPECTED_ZIP_BYTES = 85_042_887  # 查證時的大小;不同時警告但不中止(上游可能更新)

JAR_URL = (
    "https://github.com/synthetichealth/synthea/releases/latest/download/"
    "synthea-with-dependencies.jar"
)
JAR_PATH = DATA_RAW / "synthea-with-dependencies.jar"
GENERATED_DIR = DATA_RAW / "generated"

# 與 LocalBundleFHIRStore 的跳過規則一致
SKIP_PREFIXES = ("hospitalInformation", "practitionerInformation")

logger = logging.getLogger("synthea-data")


def _skip_download_is_valid(url: str, dest: Path) -> bool:
    """略過下載前先驗證既有檔案大小,不要盲信「檔案存在=下載完整」。

    M1 審查發現:中斷的下載(Ctrl+C、斷線、睡眠)會在 dest 留下不完整檔案,
    下次執行只檢查 dest.exists() 就當作已完成,之後才在 extract() 炸出
    難懂的 BadZipFile。
    """
    if not dest.exists():
        return False
    size = dest.stat().st_size
    if url == SAMPLE_URL:
        return size == EXPECTED_ZIP_BYTES
    return size > 0


def download(url: str, dest: Path, force: bool = False) -> None:
    if not force and _skip_download_is_valid(url, dest):
        logger.info("已存在且大小正確,略過下載:%s(%d bytes)", dest.name, dest.stat().st_size)
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    logger.info("下載 %s", url)
    sha256 = hashlib.sha256()
    downloaded = 0
    # 下載到 .part 暫存檔,成功後才原子性 rename 到 dest——中斷(Ctrl+C/斷線/
    # 睡眠)絕不會在 dest 留下看起來「已完成」的半成品檔案(M1 審查發現)
    tmp_dest = dest.with_name(dest.name + ".part")
    try:
        with urllib.request.urlopen(url) as resp, tmp_dest.open("wb") as out:
            total = int(resp.headers.get("Content-Length") or 0)
            next_report = 0
            while chunk := resp.read(1024 * 1024):
                out.write(chunk)
                sha256.update(chunk)
                downloaded += len(chunk)
                if total and downloaded >= next_report:
                    logger.info(
                        "  %d%%(%d / %d bytes)", downloaded * 100 // total, downloaded, total
                    )
                    next_report += total // 10
        os.replace(tmp_dest, dest)
    except BaseException:
        tmp_dest.unlink(missing_ok=True)
        raise
    logger.info("下載完成:%d bytes,sha256=%s", downloaded, sha256.hexdigest())
    if url == SAMPLE_URL and downloaded != EXPECTED_ZIP_BYTES:
        logger.warning(
            "大小與查證時(%d bytes)不同——上游可能已更新,請人工確認內容",
            EXPECTED_ZIP_BYTES,
        )


def _zip_json_member_count(zip_path: Path) -> int:
    with zipfile.ZipFile(zip_path) as zf:
        return sum(1 for name in zf.namelist() if name.endswith(".json"))


def extract(zip_path: Path, extract_dir: Path, force: bool = False) -> None:
    # 比對「解壓出的 .json 數」與「zip 內實際的 .json 數」,而不是「有沒有任一個檔案」——
    # 中斷的解壓(硬碟滿、Ctrl+C、防毒軟體鎖檔)會留下部分檔案,只看「存在」會誤判成
    # 「已完成」(M1 審查發現)
    if extract_dir.is_dir() and not force:
        extracted = sum(1 for _ in extract_dir.rglob("*.json"))
        expected = _zip_json_member_count(zip_path)
        if extracted == expected and expected > 0:
            logger.info("已解壓,略過:%s(%d 個 .json)", extract_dir, extracted)
            return
        if extracted:
            logger.warning(
                "偵測到不完整的解壓結果(%d/%d 個 .json),重新解壓:%s",
                extracted,
                expected,
                extract_dir,
            )
    logger.info("解壓 %s → %s", zip_path.name, extract_dir)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(extract_dir)
    logger.info("解壓完成")


def list_patient_files(source_dir: Path) -> list[Path]:
    """遞迴列出病患 bundle 檔(排除 hospital/practitioner 資訊檔),依檔名排序。"""
    return sorted(
        (p for p in source_dir.rglob("*.json") if not p.name.startswith(SKIP_PREFIXES)),
        key=lambda p: p.name,
    )


def make_subset(source_dir: Path, n: int, force: bool = False) -> Path:
    subset_dir = DATA_PROCESSED / f"subset_{n}"
    patient_files = list_patient_files(source_dir)
    if not patient_files:
        raise SystemExit(f"{source_dir} 內找不到任何病患 JSON——請先下載或生成")
    chosen = patient_files[:n]
    if len(chosen) < n:
        logger.warning("來源只有 %d 位病患,少於要求的 %d 位", len(chosen), n)
    chosen_names = {p.name for p in chosen}
    # 比對實際檔名集合,不能只比數量——來源換了(下載↔生成、換 seed)但選出的
    # 檔案數剛好一樣時,只看數量會誤判成「已是最新」而沿用舊資料(M1 審查發現)
    existing_names = {p.name for p in subset_dir.glob("*.json")} if subset_dir.is_dir() else set()
    if existing_names == chosen_names and not force:
        logger.info("子集已存在且內容相符,略過:%s(%d 檔)", subset_dir, len(existing_names))
        return subset_dir
    if subset_dir.is_dir():
        # 防呆:只允許刪除我們自己建立的 data/processed/subset_* 目錄
        assert subset_dir.parent == DATA_PROCESSED
        assert subset_dir.name.startswith("subset_")
        shutil.rmtree(subset_dir)
    subset_dir.mkdir(parents=True)
    for src in chosen:
        shutil.copy2(src, subset_dir / src.name)
    logger.info("子集完成:%s(%d 位病患)", subset_dir, len(chosen))
    return subset_dir


def verify(subset_dir: Path) -> None:
    """以 LocalBundleFHIRStore 實際載入子集,列出病患(M1 驗收)。"""
    from fhir_copilot.store import LocalBundleFHIRStore

    store = LocalBundleFHIRStore(subset_dir)
    patients = store.list_patients()
    logger.info("驗證:成功載入 %d 位病患(%s)", len(patients), subset_dir)
    for s in patients[:5]:
        logger.info("  - %s | %s | %s | %s", s.patient_id[:8], s.name, s.gender, s.birth_date)
    if len(patients) > 5:
        logger.info("  …(其餘 %d 位省略)", len(patients) - 5)


def java_major_version() -> int | None:
    try:
        proc = subprocess.run(
            ["java", "-version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except FileNotFoundError:
        return None
    # 版本字串在 stderr,如:openjdk version "17.0.16" 2025-07-15
    for token in proc.stderr.replace('"', " ").split():
        segments = token.split(".")
        head = segments[0]
        if not head.isdigit():
            continue
        # 舊制版本號(Java 8 及更早)長這樣:"1.8.0_281" → 真正的主版號是第二段
        # 的 "8",不是開頭的 "1"(M1 審查發現,原本一律回傳 1,診斷訊息會誤導)
        if head == "1" and len(segments) > 1 and segments[1].isdigit():
            return int(segments[1])
        return int(head)
    return None


def generate(seed: int, population: int, state: str, force: bool = False) -> Path:
    version = java_major_version()
    if version is None or version < 17:
        raise SystemExit(f"本地生成需要 Java 17+(偵測到:{version});或改用預設的下載模式")
    download(JAR_URL, JAR_PATH, force=False)
    out_dir = GENERATED_DIR / f"seed_{seed}_p{population}"
    fhir_dir = out_dir / "fhir"
    if fhir_dir.is_dir() and any(fhir_dir.glob("*.json")) and not force:
        logger.info("已有生成結果,略過:%s", fhir_dir)
        return out_dir
    cmd = [
        "java",
        "-jar",
        str(JAR_PATH),
        "-s",
        str(seed),
        "-p",
        str(population),
        f"--exporter.baseDirectory={out_dir}",
        state,
    ]
    logger.info("執行:%s(population=%d 可能需要數分鐘)", " ".join(cmd[:3]), population)
    subprocess.run(cmd, check=True)
    if not fhir_dir.is_dir():
        raise SystemExit(f"生成結束但找不到輸出目錄 {fhir_dir}——請檢查 Synthea 輸出")
    return out_dir


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subset", type=int, default=100, metavar="N", help="子集病患數(預設 100)")
    parser.add_argument("--force", action="store_true", help="強制重新下載/解壓/子集化")
    parser.add_argument(
        "--generate", action="store_true", help="改用本地 Synthea 生成(需 Java 17+)"
    )
    parser.add_argument("--seed", type=int, default=20260719, help="生成用固定 seed")
    parser.add_argument("--population", type=int, default=500, help="生成病患數(預設 500)")
    parser.add_argument("--state", default="Massachusetts", help="生成用州別")
    parser.add_argument("--verify-only", action="store_true", help="只驗證現有子集,不下載")
    args = parser.parse_args()

    # Windows 下管線/重導向預設 cp950,中文 log 會變亂碼 → 強制 UTF-8
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if args.verify_only:
        verify(DATA_PROCESSED / f"subset_{args.subset}")
        return

    if args.generate:
        out_dir = generate(args.seed, args.population, args.state, force=args.force)
        source_dir = out_dir / "fhir"
    else:
        download(SAMPLE_URL, SAMPLE_ZIP, force=args.force)
        extract(SAMPLE_ZIP, SAMPLE_EXTRACT_DIR, force=args.force)
        source_dir = SAMPLE_EXTRACT_DIR

    subset_dir = make_subset(source_dir, args.subset, force=args.force)
    verify(subset_dir)


if __name__ == "__main__":
    sys.path.insert(0, str(REPO_ROOT / "src"))  # 未安裝專案時也可直跑
    main()
