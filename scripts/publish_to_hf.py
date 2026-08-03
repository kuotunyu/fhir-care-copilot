"""把本專案發布成 Hugging Face Docker Space。

**預設是 dry-run**:只印出「會做什麼」,不呼叫任何 HF API、不上傳任何檔案。
要真的發布必須明確加 ``--execute``,而且需要 ``HF_TOKEN`` 環境變數(.env 已有)。

用法:
    # dry-run(預設,安全,不需要 token 也能跑)
    uv run python scripts/publish_to_hf.py --repo-id <username>/fhir-care-copilot

    # 把「會上傳的那一份」實體攤到一個目錄,拿去 docker build 驗證(不碰 HF)
    uv run python scripts/publish_to_hf.py --repo-id <username>/x --stage-dir /tmp/hf-stage

    # 真的發布(需要 HF_TOKEN,且需要明確 --execute)
    uv run python scripts/publish_to_hf.py --repo-id <username>/fhir-care-copilot --execute

## 為什麼有 --stage-dir

dry-run 回答的是「**會上傳哪些檔案**」,不是「**那些檔案 build 得起來**」。這是兩個
不同的宣稱,而本機 ``docker build`` 一直是在完整 repo 上跑的——那裡有 ``.git/``、
``data/``、``app/node_modules/``,Space 上一個都沒有。用完整 repo 驗證 Space 的
build,驗到的是另一條路徑。

``--stage-dir`` 把 ``_simulate_upload()`` 算出來的那一份**實體複製**出來(README 也
換成組好 front-matter 的版本),於是可以:

    docker build -t fhir-care-copilot:hf <stage-dir>

在花掉 HF 的 build 之前,先在本機證明它建得起來。

依已查證的事實:
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
import os
import re
import shutil
import sys
from collections.abc import Iterable
from pathlib import Path

import yaml

from _env import load_env_file

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
    # `.claude/` 整個排除。原本只排除設定檔、保留 skills,因為 README 連到
    # `.claude/skills/run-eval/SKILL.md`(eval 的指標定義與已知限制寫在那裡)。
    # 2026-07-28 起那份內容搬到 `docs/EVAL.md`,`.claude/` 也不再進 git
    # ——它底下剩下的都是開發機的工具設定,對讀者沒有意義。
    ".claude/*",
    # 同一批:內部的規劃文件與 AI 助理工作約定,2026-07-28 起不進 git 也不進 Space。
    # 它們仍在開發者本機,只是不對外——Space 是公開的,標準與 repo 一致。
    "PLAN.md",
    "CLAUDE.md",
    ".superpowers/*",
    # Release-process provenance belongs in GitHub source history, not in the public demo image.
    "docs/superpowers/*",
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
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
pinned: false
license: apache-2.0
---

"""

# **這組值不是查文件抄來的,是 HF 的 400 錯誤訊息逐字告訴我們的**(2026-07-26 實測):
#   "colorFrom" must be one of [red, yellow, green, blue, indigo, purple, pink, gray]
# 原本寫的是 teal/orange——兩個都不在清單上。事前查證只記了「front-matter 需要
# colorFrom/colorTo」,但沒記**值域**,於是這個錯一路活到真的發布那一刻。
HF_SPACE_COLORS = frozenset({"red", "yellow", "green", "blue", "indigo", "purple", "pink", "gray"})
_REQUIRED_FRONT_MATTER_KEYS = ("title", "sdk", "app_port", "colorFrom", "colorTo")


def front_matter_problems(front_matter: str) -> list[str]:
    """在**碰 HF 之前**檢查 front-matter,回傳問題清單(空的代表沒問題)。

    為什麼這件事非做不可:實測時 dry-run 一切正常,``--execute`` 卻在
    ``upload_folder`` 把 **184 個檔案都傳完之後**才因為 README 的 metadata 被
    ``/api/validate-yaml`` 打回 400。錯誤本身無害,但它暴露的是 dry-run 的職責
    ——它宣稱「先讓你看會發生什麼」,卻漏檢了一個純本地、零成本就能檢的東西。

    這裡刻意**只檢查本地檢查得到的**:值域、必要欄位、型別。HF 端還有什麼規則
    我們不知道,不假裝知道。
    """
    problems: list[str] = []
    body = front_matter.strip()
    if not body.startswith("---"):
        return ["front-matter 必須以 --- 開頭"]

    _, _, rest = body.partition("---")
    yaml_text, sep, _ = rest.partition("---")
    if not sep:
        return ["front-matter 缺少結尾的 ---"]

    parsed = yaml.safe_load(yaml_text)
    if not isinstance(parsed, dict):
        return [f"front-matter 不是 YAML mapping:{type(parsed).__name__}"]

    for key in _REQUIRED_FRONT_MATTER_KEYS:
        if key not in parsed:
            problems.append(f"缺少必要欄位 {key}")

    for key in ("colorFrom", "colorTo"):
        value = parsed.get(key)
        if value is not None and value not in HF_SPACE_COLORS:
            allowed = ", ".join(sorted(HF_SPACE_COLORS))
            problems.append(f"{key}={value!r} 不在 HF 允許的顏色裡({allowed})")

    if parsed.get("sdk") != "docker":
        problems.append(f"sdk 必須是 docker,目前是 {parsed.get('sdk')!r}")
    if not isinstance(parsed.get("app_port"), int):
        problems.append(f"app_port 必須是整數,目前是 {parsed.get('app_port')!r}")

    return problems


logger = logging.getLogger("publish-to-hf")


def assemble_space_readme(project_readme: Path) -> str:
    """把專案 README 內容接在 HF Space 要求的 front-matter 後面。

    Space 用的 README 需要 YAML front-matter 告訴 HF 這是 docker sdk、對外
    埠是多少(已查證);本專案根目錄的 README.md 本身不放這段
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


def stale_remote_files(remote: Iterable[str], uploaded: set[str]) -> list[str]:
    """Space 上有、但這次不會上傳的檔案——**必須明確刪掉,否則會一直留著**。

    ``upload_folder`` 的 ``ignore_patterns`` 只決定「這次傳什麼」,不會移除
    遠端已經存在的東西。所以把某個檔案加進排除清單,只是讓它**停止被更新**,
    它仍然公開躺在 Space 上。

    2026-07-28 實測踩到:把內部規劃文件從 git 移除、也加進了排除清單之後,
    它們在 Space 上仍然是 HTTP 200。**從 git 移除但留在公開 Space 上,
    等於沒移除。**

    `.gitattributes` 由 HF 在建 repo 時自己產生,不在我們的上傳集裡,
    刪掉它會動到 repo 的 LFS 設定——排除。
    """
    hf_managed = {".gitattributes"}
    return sorted(p for p in remote if p not in uploaded and p not in hf_managed)


def _broken_readme_links(uploaded: set[str], project_readme: Path) -> list[str]:
    """README 裡連到 repo 內檔案、但那些檔案不會被上傳的連結。"""
    text = project_readme.read_text(encoding="utf-8")
    links = sorted({m for m in re.findall(r"\]\(([^)#:]+\.(?:md|png|json|ya?ml|py))\)", text)})
    return [link for link in links if link not in uploaded and (REPO_ROOT / link).exists()]


def stage_upload(dest: Path, project_readme: Path) -> tuple[int, int]:
    """把會上傳的檔案實體複製到 ``dest``,回傳 (檔案數, 總位元組)。

    刻意**共用 ``_simulate_upload()``**,而不是另外寫一份複製規則——兩份規則遲早
    分岔,到時候「驗過的那一份」就不是「上傳的那一份」了。

    ``dest`` 必須不存在或為空目錄:這支腳本不該有機會覆寫使用者既有的東西。
    """
    if dest.exists() and any(dest.iterdir()):
        raise ValueError(f"--stage-dir 指向的目錄不是空的,拒絕覆寫:{dest}")

    kept, total = _simulate_upload()
    for rel, _size in kept:
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / rel, target)

    # 與 _execute_publish 一致:README 換成組好 front-matter 的那一份。
    (dest / "README.md").write_text(assemble_space_readme(project_readme), encoding="utf-8")
    return len(kept), total


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
        "只在 --execute 時生效;dry-run 只會印出會設定哪些 secret 名稱(不印值)。"
        "**金鑰請改用 --set-secret-from-env**,值寫在命令列會留在 shell 歷史裡。",
    )
    parser.add_argument(
        "--set-secret-from-env",
        action="append",
        default=[],
        metavar="NAME",
        help="從環境變數讀值來設定同名的 Space Secret(可重複)。"
        "與 --set-secret 的差別只有一個,但很重要:**值不會出現在命令列**"
        "——不進 shell 歷史、不進 ps 的輸出。設定真的 API 金鑰時用這個。",
    )
    parser.add_argument(
        "--set-secret-from-env-as",
        action="append",
        default=[],
        metavar="LOCAL_NAME:SPACE_NAME",
        help="從本機的 LOCAL_NAME 環境變數讀值,設成 Space 上叫 SPACE_NAME 的 secret。"
        "用途是「本機與雲端用不同的金鑰,但程式讀的名字必須一樣」——例如給 Space "
        "一把專屬的 Gemini 金鑰時,本機叫 GEMINI_API_KEY_SPACE、Space 上必須叫 "
        "GEMINI_API_KEY(models.yaml 的 api_key_env)。名字對不上的話 Space 會"
        "**安靜退回 mock**,而不是報錯。",
    )
    parser.add_argument(
        "--unset-secret",
        action="append",
        default=[],
        metavar="NAME",
        help="**移除**一個 Space Secret(可重複)。設定得了卻移除不了的話,"
        "換金鑰時舊的會永遠留在雲端服務的設定裡——例如把 Space 換成專屬金鑰時,"
        "原本那幾把開發用的備援金鑰。只在 --execute 時生效。",
    )
    parser.add_argument(
        "--stage-dir",
        type=Path,
        default=None,
        metavar="PATH",
        help="把會上傳的檔案實體複製到這個目錄後結束(不呼叫任何 HF API)。"
        "用途是拿去 `docker build` 驗證 Space 的 build——完整 repo 建得起來"
        "不代表少了 .git/、data/ 的那一份建得起來。目錄必須不存在或為空。",
    )
    parser.add_argument(
        "--load-env",
        action="store_true",
        help="先把專案根目錄的 .env 讀進環境變數(HF_TOKEN 與各 provider 金鑰都在那裡)。"
        "已經在環境裡的值優先,不會被檔案蓋掉。",
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
    if args.load_env:
        load_env_file(REPO_ROOT / ".env")

    project_readme = REPO_ROOT / "README.md"
    if not project_readme.exists():
        logger.error("找不到 %s,無法組合 Space README", project_readme)
        return 1

    # **在任何上傳之前。** 實測的教訓:metadata 錯誤是在 184 個檔案上傳完之後
    # 才由 HF 端擋下來的,結果是一個半完成的 Space。純本地檢查就先擋掉。
    problems = front_matter_problems(SPACE_README_FRONT_MATTER)
    if problems:
        logger.error("Space README front-matter 有問題,發布前先修掉:")
        for problem in problems:
            logger.error("  - %s", problem)
        return 1

    secrets: dict[str, str] = {}
    for raw in args.set_secret:
        try:
            name, value = _parse_secret_arg(raw)
        except ValueError as exc:
            logger.error("%s", exc)
            return 1
        secrets[name] = value
    pairs: list[tuple[str, str]] = [(n, n) for n in args.set_secret_from_env]
    for raw in args.set_secret_from_env_as:
        local, sep, remote = raw.partition(":")
        if not sep or not local or not remote:
            logger.error("--set-secret-from-env-as 格式錯誤(需要 LOCAL:SPACE):%s", raw)
            return 1
        pairs.append((local, remote))

    for name, space_name in pairs:
        value = os.environ.get(name, "")
        if not value:
            # 只在真的要發布時才是致命的——dry-run 應該在沒有任何金鑰的機器上跑得完。
            level = logger.error if args.execute else logger.warning
            level("環境變數 %s 未設定或為空(要設成 Space 的 %s)", name, space_name)
            if args.execute:
                return 1
            continue
        secrets[space_name] = value

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
    if args.unset_secret:
        logger.info("secrets to REMOVE: %s", ", ".join(sorted(args.unset_secret)))

    if args.stage_dir is not None:
        try:
            count, staged_total = stage_upload(args.stage_dir, project_readme)
        except ValueError as exc:
            logger.error("%s", exc)
            return 1
        logger.info(
            "已攤開 %d 個檔案(%.1f MB)到 %s", count, staged_total / 1024 / 1024, args.stage_dir
        )
        logger.info("下一步:docker build -t fhir-care-copilot:hf %s", args.stage_dir)
        logger.info("=== 只攤開檔案,未呼叫任何 HF API ===")
        return 0

    if not args.execute:
        logger.info("=== DRY RUN(預設模式,未呼叫任何 HF API、未上傳任何檔案)===")
        logger.info("加 --execute 才會真的發布;真的發布需要 HF_TOKEN 環境變數。")
        return 0

    return _execute_publish(
        args.repo_id, args.private, secrets, list(args.unset_secret), project_readme
    )


def _execute_publish(
    repo_id: str,
    private: bool,
    secrets: dict[str, str],
    unset: list[str],
    project_readme: Path,
) -> int:
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

    # **secret 必須在上傳之前設好,順序不能顛倒。**
    #
    # 上傳內容會讓 HF 立刻開始 build,build 完成的容器帶著的是「當下存在的」
    # 環境變數。原本的順序是先上傳、後設 secret,於是第一個跑起來的容器永遠
    # 拿不到金鑰——而 resolve_provider_name() 沒金鑰就退回 mock,get_provider_name()
    # 又是 @lru_cache,一旦解析成 mock 就固定到 process 結束。
    #
    # 結果是:全新部署**必然**跑成 mock demo mode,而且網頁看起來完全正常。
    # 2026-07-26 首次部署實測就是這樣,/api/health 回 provider=mock,
    # budget_counting_since 顯示容器早於 secret 設定時間。
    # **先移除再設定。** 換金鑰的情境裡,兩者是同一個動作的兩半:
    # 把 Space 從「跟開發共用的一堆備援金鑰」換成「一把專屬金鑰」時,
    # 只設定不移除的話,舊的那幾把會繼續留在雲端服務的設定裡。
    for name in unset:
        logger.info("移除 Space secret:%s", name)
        api.delete_space_secret(repo_id, name)

    for name, value in secrets.items():
        logger.info("設定 Space secret:%s", name)
        api.add_space_secret(repo_id, name, value)

    with tempfile.TemporaryDirectory() as tmp:
        space_readme = Path(tmp) / "README.md"
        space_readme.write_text(assemble_space_readme(project_readme), encoding="utf-8")

        # 排除清單只決定「這次傳什麼」,不會移除遠端已經存在的檔案。
        # 所以要先算出 Space 上有、但不該再有的那些,明確刪掉。
        kept, _total = _simulate_upload()
        stale = stale_remote_files(
            api.list_repo_files(repo_id, repo_type="space"),
            {rel.replace("\\", "/") for rel, _size in kept},
        )
        if stale:
            logger.warning("Space 上有 %d 個檔案不該再存在,將一併刪除:", len(stale))
            for path in stale:
                logger.warning("  - %s", path)

        logger.info("上傳專案內容(README 另用組好 front-matter 的版本覆蓋)...")
        api.upload_folder(
            repo_id=repo_id,
            repo_type="space",
            folder_path=str(REPO_ROOT),
            ignore_patterns=[*UPLOAD_IGNORE_PATTERNS, "README.md"],
            delete_patterns=stale or None,
        )
        api.upload_file(
            repo_id=repo_id,
            repo_type="space",
            path_or_fileobj=str(space_readme),
            path_in_repo="README.md",
        )

    if secrets or unset:
        # 上面的順序修好了「全新部署」。但**重跑**時 Space 可能正跑著一個舊容器,
        # 而內容沒變就不會觸發 build——那它會繼續用舊環境。明確重啟一次,
        # 讓「指令跑完 = 新設定生效」成立,不必人工去點。
        logger.info("重啟 Space,讓新的 secret 生效...")
        api.restart_space(repo_id)

    logger.info("完成。Space 網址:https://huggingface.co/spaces/%s", repo_id)
    logger.info("健康檢查:https://%s.hf.space/api/health", repo_id.replace("/", "-"))
    logger.info(
        "公開 demo 驗證:等待 Space running 後檢查 /api/health,必須回傳 "
        "provider=mock、model_id=mock-deterministic、demo_mode=true。"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
