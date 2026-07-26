"""產生 README 用的介面截圖——**由程式產生,不手動截**。

    uv sync --extra screenshots
    uv run playwright install chromium
    uv run python scripts/capture_screenshots.py

## 為什麼要腳本化

手動截圖有兩個問題:UI 一改就過期,而且沒人知道那張圖是哪個版本、什麼狀態下截的。
這支腳本自己起後端、走完一段固定的操作流程、把結果存進 `docs/screenshots/`,
所以截圖跟 `reports/` 底下那些數字一樣是**可重跑的產物**。

用 `mock` provider:deterministic、不打外部 API、不花錢,而且每次跑出來的回答一樣,
截圖之間才有可比性。

## 這裡刻意截的是「有證據」的畫面

這個專案的賣點是「每個病患事實都附 FHIR resourceType/id」,所以截圖要拍到
**證據抽屜是打開的**——只拍一個聊天泡泡看不出跟一般 chatbot 有什麼不同。
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from playwright.sync_api import ViewportSize

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT_DIR = REPO_ROOT / "docs" / "screenshots"
logger = logging.getLogger("capture_screenshots")

# ViewportSize 是 playwright 的 TypedDict;用 Final 標起來 mypy 才不會退化成 dict[str, int]
DESKTOP: Final[ViewportSize] = {"width": 1440, "height": 960}
MOBILE: Final[ViewportSize] = {"width": 375, "height": 812}

# 全頁圖用 1 倍像素密度。第一版用 2 倍,單張 525 KB,被 pre-commit 的
# check-added-large-files(上限 500 KB)擋下——**而它擋得有道理**:截圖是會隨 UI
# 反覆重新產生的檔案,每次都塞半 MB 進 git 歷史,repo 只會越長越肥。
# README 的顯示寬度約 900px,1440 的原圖已經夠銳利。
FULL_PAGE_SCALE = 1
# 小範圍特寫才用 2 倍:檔案本來就小,細節值得。
CLOSEUP_SCALE = 2
MAX_BYTES = 500 * 1024


def wait_for_health(base_url: str, attempts: int = 60) -> None:
    for _ in range(attempts):
        try:
            with urllib.request.urlopen(f"{base_url}/api/health", timeout=5):
                return
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            time.sleep(0.5)
    raise SystemExit("後端沒有在時限內起來")


def start_backend(port: int) -> subprocess.Popen[bytes]:
    env = dict(os.environ)
    # mock provider:deterministic、不花錢、每次回答一樣,截圖之間才可比
    env["FHIR_COPILOT_PROVIDER"] = "mock"
    env.pop("FHIR_COPILOT_API_KEYS", None)
    env.pop("FHIR_COPILOT_REQUIRE_AUTH", None)
    command = [
        sys.executable,
        "-m",
        "uvicorn",
        "fhir_copilot.api.app:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--log-level",
        "warning",
    ]
    logger.info("啟動後端(mock provider, port %d)", port)
    return subprocess.Popen(command, env=env, cwd=REPO_ROOT)


def capture(base_url: str, out_dir: Path) -> list[Path]:
    from playwright.sync_api import sync_playwright

    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(
            viewport=DESKTOP, device_scale_factor=FULL_PAGE_SCALE, locale="zh-TW"
        )
        page.goto(base_url, wait_until="networkidle")

        # 1) 病患清單 + 時間軸。第一位病患預設就是選中的,不必再點
        page.wait_for_selector(".patient-card.is-selected", timeout=15_000)
        path = out_dir / "01-patient-timeline.png"
        page.screenshot(path=path)
        written.append(path)

        # 2) 問答 + 證據抽屜(**要打開**——只拍聊天泡泡看不出跟一般 chatbot 的差別)
        # 建議問題那顆按鈕**本身就會送出**,不要再點「送出」——那時它是 disabled 的
        page.get_by_role("button", name="目前有哪些生效中的診斷?").click()
        page.wait_for_selector("details", timeout=30_000)
        # 直接設 open 屬性,不用點 summary:點擊會受動畫與捲動位置影響,設屬性不會
        page.evaluate("() => document.querySelectorAll('details').forEach(d => d.open = true)")
        # 對話面板有自己的捲動容器,`full_page` 救不到——不捲的話證據清單會被下方
        # 輸入框切掉,而**證據正是這張圖要拍的東西**。
        #
        # 只捲**證據所在的那個容器**,不要全頁捲到底:第一版把每個可捲元素都捲到底,
        # 結果左側病患清單也跟著捲走,選中的那位病患不見了,整張圖看起來像清單和
        # 時間軸各講各的。
        page.evaluate(
            "() => {"
            "  const d = document.querySelector('details');"
            "  if (!d) return;"
            "  let el = d.parentElement;"
            "  while (el && el.scrollHeight <= el.clientHeight + 4) el = el.parentElement;"
            "  if (el) el.scrollTop = el.scrollHeight;"
            "}"
        )
        page.wait_for_timeout(600)
        path = out_dir / "02-answer-with-evidence.png"
        page.screenshot(path=path, full_page=True)
        written.append(path)

        # 3) 回答卡片特寫:成本/延遲 badge + 證據清單
        #
        # **原本這裡拍的是頁首,但頁首裡沒有 cost badge**——那個 badge 在回答泡泡
        # 裡面,檔名叫 status-and-cost 等於標錯。這個專案的賣點就是「每個回答都附
        # 成本、延遲與可追溯證據」,要拍就拍那張卡片。
        #
        # **另一件原本想拍卻拍不出來的:結構化拒答。** 這個系統唯一的拒答觸發點是
        # 「病患不存在」(工具回 ok=False),而 UI 的選擇器只列得出真實存在的病患
        # ——從介面上走不到那條路徑。硬拍會變成一張標錯標題的假圖。
        # 這件事本身是產品缺口,已記在 README 的已知限制。
        # 這張是小範圍特寫,檔案本來就小,用高解析度讓 resourceType/id 看得清楚
        closeup = browser.new_page(
            viewport=DESKTOP, device_scale_factor=CLOSEUP_SCALE, locale="zh-TW"
        )
        closeup.goto(base_url, wait_until="networkidle")
        closeup.get_by_role("button", name="目前有哪些生效中的診斷?").click()
        closeup.wait_for_selector("details", timeout=30_000)
        closeup.evaluate("() => document.querySelectorAll('details').forEach(d => d.open = true)")
        closeup.wait_for_timeout(400)
        path = out_dir / "03-cost-and-evidence.png"
        closeup.locator("div:has(> details)").last.screenshot(path=path)
        written.append(path)

        # 4) 手機寬度(375px 無橫向溢位是 M4 的驗收條件之一)
        mobile = browser.new_page(
            viewport=MOBILE, device_scale_factor=FULL_PAGE_SCALE, locale="zh-TW"
        )
        mobile.goto(base_url, wait_until="networkidle")
        path = out_dir / "04-mobile.png"
        mobile.screenshot(path=path)
        written.append(path)

        overflow = mobile.evaluate(
            "() => document.documentElement.scrollWidth > document.documentElement.clientWidth"
        )
        if overflow:
            logger.warning("375px 下有橫向溢位——那是 M4 驗收條件的回歸,截圖照留但要修")
        else:
            logger.info("375px 下無橫向溢位")

        browser.close()
    return written


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8124)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args()

    dist = REPO_ROOT / "app" / "dist" / "index.html"
    if not dist.is_file():
        raise SystemExit("找不到 app/dist——先跑 `just frontend-build`,否則截到的是空白頁")

    base_url = f"http://127.0.0.1:{args.port}"
    backend = start_backend(args.port)
    try:
        wait_for_health(base_url)
        written = capture(base_url, args.out_dir)
        oversized = []
        for path in written:
            size = path.stat().st_size
            logger.info("已輸出 %s(%.0f KB)", path, size / 1024)
            if size > MAX_BYTES:
                oversized.append(f"{path.name} {size / 1024:.0f} KB")
        if oversized:
            # 在這裡失敗,不要等到 git commit 被 hook 擋——那時候檔案已經 staged,
            # 要重新 add 一次。**產生器該為自己的產物負責。**
            raise SystemExit(f"截圖超過 {MAX_BYTES // 1024} KB(pre-commit 的上限):{oversized}")
        return 0
    finally:
        backend.terminate()
        try:
            backend.wait(timeout=15)
        except subprocess.TimeoutExpired:
            backend.kill()


if __name__ == "__main__":
    raise SystemExit(main())
