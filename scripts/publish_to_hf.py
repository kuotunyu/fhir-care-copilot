"""把本專案發布成 Hugging Face Docker Space。

**預設是 dry-run**:只印出「會做什麼」,不呼叫任何 HF API、不上傳任何檔案。
要真的發布必須明確加 ``--execute``,而且需要 ``HF_TOKEN`` 環境變數(.env 已有)。

用法:
    # dry-run(預設,安全,不需要 token 也能跑)
    uv run python scripts/publish_to_hf.py --repo-id <username>/fhir-care-copilot

    # 真的發布(需要 HF_TOKEN,且需要明確 --execute)
    uv run python scripts/publish_to_hf.py --repo-id <username>/fhir-care-copilot --execute

依 PLAN.md §7 已查證的事實:
    - Space README 需要 front-matter(sdk: docker、app_port);見 assemble_readme()
    - Space Secrets 在 Settings 設定,runtime 是普通 env var,buildtime 拿不到
      → 本專案的「無金鑰自動退回 mock demo mode」設計(見 api/dependencies.py)
        正是為了讓沒設 Secrets 的訪客也能看到完整功能
    - 免費 cpu-basic 方案:2 vCPU / 16GB RAM / 50GB 非持久碟,48 小時不活動會 sleep
    - 上傳排除規則刻意與 .dockerignore/.gitignore 對齊:不上傳 data/、.env、.git 等
"""

from __future__ import annotations

import argparse
import fnmatch
import logging
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# 與 .gitignore / .dockerignore 對齊:不上傳原始資料、密鑰、開發用檔案。
UPLOAD_IGNORE_PATTERNS = [
    ".git*",
    ".env*",
    "data/*",
    "app/node_modules/*",
    "app/dist/*",
    ".venv/*",
    "__pycache__/*",
    "*.pyc",
    ".mypy_cache/*",
    ".ruff_cache/*",
    ".pytest_cache/*",
    # `.claude/` 底下只有兩類東西:開發機的編輯器設定(launch.json、settings.local.json)
    # 與**專案 skill 文件**。前者對讀者沒有意義,後者有——README 直接連到
    # `.claude/skills/run-eval/SKILL.md`(eval 的指標定義與已知限制寫在那裡)。
    # 所以只排除設定檔,skills 照上傳。
    ".claude/launch.json",
    ".claude/settings*",
    # **只排除 reports 底下的原始 JSON,保留 .md**(12 個檔、69 KB)。
    #
    # README 直接連到 reports/model_comparison_full.md、injection_ab.md、
    # loadtest/comparison.md 等——整個 reports/ 排掉的話,Space 首頁上那些連結
    # 全部 404,而它們正是「每個數字都指得回原始輸出」這個賣點的落點。
    # JSON 有 0.9 MB 且沒有人會在網頁上讀,排掉。
    "reports/*.json",
    "audit_log/*",
]

SPACE_README_FRONT_MATTER = """\
---
title: FHIR Care Copilot
emoji: \U0001fa7a
colorFrom: teal
colorTo: orange
sdk: docker
app_port: 7860
pinned: false
license: apache-2.0
---

"""

logger = logging.getLogger("publish-to-hf")


def assemble_space_readme(project_readme: Path) -> str:
    """把專案 README 內容接在 HF Space 要求的 front-matter 後面。

    Space 用的 README 需要 YAML front-matter 告訴 HF 這是 docker sdk、對外
    埠是多少(PLAN.md §7 查證);本專案根目錄的 README.md 本身不放這段
    front-matter(那是給 GitHub 讀者看的,front-matter 只對 HF 有意義),
    發布時才組合起來,避免兩份 README 分岔維護。
    """
    body = project_readme.read_text(encoding="utf-8")
    return SPACE_README_FRONT_MATTER + body


def _simulate_upload() -> tuple[list[tuple[str, int]], int]:
    """實際套用 ignore 規則,回傳會上傳的檔案清單與總大小。

    ``upload_folder`` 的 ``ignore_patterns`` 用的是 fnmatch,而 fnmatch 的 ``*``
    會跨過 ``/``——所以 ``reports/*.json`` 也會命中 ``reports/loadtest/x.json``。
    這裡用同一套語意模擬,免得 dry-run 講的跟真的做的不一樣。
    """
    kept: list[tuple[str, int]] = []
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(REPO_ROOT).as_posix()
        if any(fnmatch.fnmatch(rel, pattern) for pattern in UPLOAD_IGNORE_PATTERNS):
            continue
        kept.append((rel, path.stat().st_size))
    return kept, sum(size for _, size in kept)


def _broken_readme_links(uploaded: set[str], project_readme: Path) -> list[str]:
    """README 裡連到 repo 內檔案、但那些檔案不會被上傳的連結。"""
    text = project_readme.read_text(encoding="utf-8")
    links = sorted({m for m in re.findall(r"\]\(([^)#:]+\.(?:md|png|json|ya?ml|py))\)", text)})
    return [link for link in links if link not in uploaded and (REPO_ROOT / link).exists()]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--repo-id",
        required=True,
        help="HF Space repo id,格式 <username>/<space-name>",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="真的呼叫 HF API 發布。不加這個旗標一律只做 dry-run。",
    )
    parser.add_argument(
        "--private",
        action="store_true",
        help="建立為 private space(預設 public)。",
    )
    parser.add_argument(
        "--set-secret",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="發布後同時設定一個 Space Secret(可重複使用此旗標)。"
        "只在 --execute 時生效;dry-run 只會印出會設定哪些 secret 名稱(不印值)。",
    )
    return parser.parse_args(argv)


def _parse_secret_arg(raw: str) -> tuple[str, str]:
    if "=" not in raw:
        raise ValueError(f"--set-secret 格式錯誤(需要 NAME=VALUE):{raw!r}")
    name, _, value = raw.partition("=")
    if not name:
        raise ValueError(f"--set-secret 缺少 secret 名稱:{raw!r}")
    return name, value


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = parse_args(argv)

    project_readme = REPO_ROOT / "README.md"
    if not project_readme.exists():
        logger.error("找不到 %s,無法組合 Space README", project_readme)
        return 1

    secrets: dict[str, str] = {}
    for raw in args.set_secret:
        try:
            name, value = _parse_secret_arg(raw)
        except ValueError as exc:
            logger.error("%s", exc)
            return 1
        secrets[name] = value

    logger.info("repo_id:       %s", args.repo_id)
    logger.info("visibility:    %s", "private" if args.private else "public")
    logger.info("upload root:   %s", REPO_ROOT)
    logger.info("ignore patterns:")
    for pattern in UPLOAD_IGNORE_PATTERNS:
        logger.info("  - %s", pattern)

    kept, total = _simulate_upload()
    logger.info("實際會上傳:%d 個檔案,合計 %.1f MB", len(kept), total / 1024 / 1024)
    logger.info("最大的幾個:")
    for rel, size in sorted(kept, key=lambda x: -x[1])[:5]:
        logger.info("  %7.0f KB  %s", size / 1024, rel)

    broken = _broken_readme_links({rel for rel, _ in kept}, project_readme)
    if broken:
        # dry-run 原本只印出排除樣式,看不出「README 連到的檔案被排除了」——
        # 那要等真的發布、點開 Space 首頁才會發現連結 404。
        logger.warning("README 連到但**不會上傳**的檔案(Space 上會 404):")
        for link in broken:
            logger.warning("  - %s", link)
    if secrets:
        logger.info("secrets to set(僅列名稱,不印值): %s", ", ".join(sorted(secrets)))

    if not args.execute:
        logger.info("=== DRY RUN(預設模式,未呼叫任何 HF API、未上傳任何檔案)===")
        logger.info("加 --execute 才會真的發布;真的發布需要 HF_TOKEN 環境變數。")
        return 0

    return _execute_publish(args.repo_id, args.private, secrets, project_readme)


def _execute_publish(
    repo_id: str, private: bool, secrets: dict[str, str], project_readme: Path
) -> int:
    import os
    import tempfile

    token = os.environ.get("HF_TOKEN")
    if not token:
        logger.error("--execute 需要 HF_TOKEN 環境變數(.env 應已提供),但目前未設定")
        return 1

    from huggingface_hub import HfApi

    api = HfApi(token=token)

    logger.info("建立/確認 Space repo:%s", repo_id)
    api.create_repo(
        repo_id,
        repo_type="space",
        space_sdk="docker",
        private=private,
        exist_ok=True,
    )

    with tempfile.TemporaryDirectory() as tmp:
        space_readme = Path(tmp) / "README.md"
        space_readme.write_text(assemble_space_readme(project_readme), encoding="utf-8")

        logger.info("上傳專案內容(README 另用組好 front-matter 的版本覆蓋)...")
        api.upload_folder(
            repo_id=repo_id,
            repo_type="space",
            folder_path=str(REPO_ROOT),
            ignore_patterns=[*UPLOAD_IGNORE_PATTERNS, "README.md"],
        )
        api.upload_file(
            repo_id=repo_id,
            repo_type="space",
            path_or_fileobj=str(space_readme),
            path_in_repo="README.md",
        )

    for name, value in secrets.items():
        logger.info("設定 Space secret:%s", name)
        api.add_space_secret(repo_id, name, value)

    logger.info("完成。Space 網址:https://huggingface.co/spaces/%s", repo_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
