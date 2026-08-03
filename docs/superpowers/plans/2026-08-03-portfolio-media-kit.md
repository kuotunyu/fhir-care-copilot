# FHIR Care Copilot Media and Private Kit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a safe 75-second product demo and a bilingual recruiter/interview kit outside Git history using only the frozen mock/synthetic application.

**Architecture:** Use one Markdown source of truth for recruiter copy, render a visually checked PDF from it, and record the existing UI against a local mock-provider backend. Compose exact-text title/architecture/end cards with the real screen recording, then burn captions and verify representative frames before publication.

**Tech Stack:** Markdown, bundled document/PDF runtime, Playwright/Chromium, FastAPI/React, FFmpeg/libx264, PNG

## Global Constraints

- Private artifact root is exactly `C:/Users/3Hml/.codex/visualizations/2026/08/03/019fc611-3a18-76c0-a9fb-36ba3a46fa23/fhir-care-copilot-v0.2.0-portfolio/` and must remain outside the repository.
- The final video filename is exactly `FHIR_Care_Copilot_Demo_v0.2.0.mp4`; the kit filenames are `FHIR_Care_Copilot_Portfolio_Kit.md` and `.pdf`.
- All displayed records are Synthea synthetic data and must be visibly described as synthetic/non-clinical.
- Use only `FHIR_COPILOT_PROVIDER=mock`; make no paid API call and do not read/display `.env`.
- Do not modify application code, UI, architecture, evaluation artifacts, screenshots, or model configuration.
- Do not show secrets, account pages, local usernames/paths, notifications, real medical data, or clinical recommendations.
- Reference integrity is not natural-language claim grounding; authentication is not tenant isolation; tests are not clinical validation.
- Do not commit the PDF, MP4, raw recording, capture source, storyboard, release notes source, or contact-sheet frames.

---

## File map

- Create private `FHIR_Care_Copilot_Portfolio_Kit.md`: bilingual resume and interview source of truth.
- Create private `FHIR_Care_Copilot_Portfolio_Kit.pdf`: recruiter-friendly rendered kit.
- Create private `demo/storyboard.md`: timed scene, caption, and safety checklist.
- Create private `demo/capture_demo.py`: deterministic local mock UI capture helper.
- Create private `demo/raw-ui.webm`: Playwright recording of the unchanged UI.
- Create private `demo/title-card.png`, `architecture-card.png`, `end-card.png`: exact-text video cards.
- Create private `demo/demo-captions.srt`: Traditional Chinese captions with technical English terms.
- Create private `FHIR_Care_Copilot_Demo_v0.2.0.mp4`: final H.264 release asset.
- Create private `release-notes-v0.2.0.md`: exact GitHub Release body used by the publication plan.

### Task 1: Write the bilingual recruiter and interview source

**Files:**
- Create: private `FHIR_Care_Copilot_Portfolio_Kit.md`

**Interfaces:**
- Consumes: approved design, `docs/CASE_STUDY.md`, `README.md`, `MODEL_CARD.md`, and committed reports.
- Produces: the single copy source used by the PDF and interview preparation.

- [ ] **Step 1: Create the private artifact directories**

Create the fixed artifact root plus `demo/`, `social-preview-source/`, and `qa-frames/`. Confirm the resolved artifact root does not start with the repository path.

- [ ] **Step 2: Write the kit with this exact section order**

```markdown
# FHIR Care Copilot — Portfolio Kit

## Project boundary
## English resume bullets
## 中文履歷重點
## 30-second introduction / 30 秒版本
## 2-minute interview narrative / 2 分鐘版本
## 5-minute technical deep dive / 5 分鐘版本
## Architecture and security trade-offs
## Interview question bank
## Claims I will not make
## LinkedIn / CakeResume project post
## Evidence links
```

Use these three English bullets as the factual baseline:

- `Engineered a security-focused FHIR R4 AI application with FastAPI and React, using server-injected patient scope and strict tool schemas so the model cannot choose or rewrite the patient identifier passed to retrieval tools.`
- `Built an evidence pipeline that returns verifiable FHIR resourceType/id references, while explicitly separating reference integrity from natural-language claim grounding; published committed model-comparison and prompt-injection evaluation artifacts.`
- `Implemented operational controls including authentication hooks, rate and budget limits, PII-safe logs/traces, retry and circuit-breaker failure paths, append-only audit evidence, cross-platform CI, and Docker health/runtime smoke tests.`

Use these Chinese equivalents:

- `以 FastAPI、React 與 FHIR R4 建立安全導向 AI Application；透過 server-injected patient scope 與嚴格 tool schema，使模型無法選擇或改寫實際傳入資料工具的 patient identifier。`
- `建立附 FHIR resourceType/id 的可驗證 evidence pipeline，並明確區分 reference integrity 與自然語言 claim grounding；公開可追溯的模型比較與 prompt-injection evaluation artifacts。`
- `完成 authentication hooks、rate/budget limit、PII-safe logs/traces、retry/circuit breaker、append-only audit evidence、跨平台 CI 與 Docker health/runtime smoke 等營運控制。`

The narratives must tell one consistent story: the main design problem was model-controlled scope, the solution was server-side scope injection plus tool-controlled retrieval, the evidence is committed tests/reports/CI/Docker, and the limitations include no tenant isolation, no clinical validation, no complete claim-level grounding, and no FHIR write-back.

- [ ] **Step 3: Add the interview trade-off matrix**

Cover these pairs with “chosen approach / why / cost / what would trigger a change” fields:

- server-injected patient scope vs authorization/tenant isolation;
- modular monolith vs microservices;
- mock public demo vs paid live model;
- reference integrity vs claim-level grounding;
- JSONL fallback vs Postgres audit sink;
- deterministic screenshots/video vs live-model variability;
- historical model evaluation vs rerunning for release cosmetics.

- [ ] **Step 4: Add the exact prohibited-claim checklist**

Include and negate each statement:

- clinically ready / 臨床可用;
- production-ready healthcare system;
- every generated sentence is grounded;
- patient scope equals authorization;
- synthetic patients are real records;
- passing tests proves safety or medical efficacy;
- the public mock demo measures Gemini/OpenAI quality.

- [ ] **Step 5: Validate copy against committed evidence**

Search every number and named control in the kit back to README, MODEL_CARD, reports, tests, or CI. Remove any number without a committed source. Verify the repository worktree remains unchanged.

### Task 2: Render and inspect the private PDF

**Files:**
- Create: private `FHIR_Care_Copilot_Portfolio_Kit.pdf`
- Consume: private `FHIR_Care_Copilot_Portfolio_Kit.md`

**Interfaces:**
- Consumes: the completed Markdown kit from Task 1.
- Produces: a readable, selectable-text PDF suitable for recruiter sharing, but not public release attachment.

- [ ] **Step 1: Load the bundled document/PDF runtime and instructions**

Use the workspace dependency loader, then read and follow the `documents` and `pdf` skills completely. Do not install project dependencies for document generation.

- [ ] **Step 2: Render a restrained bilingual layout**

Use A4 portrait pages, cream background accents, deep teal headings, terracotta rules, page numbers, and a compact footer `Synthea synthetic data · Non-clinical portfolio project`. Keep body text selectable; do not rasterize entire pages.

- [ ] **Step 3: Render every PDF page to images**

Use the PDF skill's render workflow. Inspect all pages for clipped Chinese glyphs, missing symbols, orphan headings, overlapping content, unreadable links, and unexpected blank pages.

- [ ] **Step 4: Verify the PDF boundary**

Confirm the PDF contains no `.env` value, token, real patient record, local filesystem path, private account detail, clinical recommendation, or unsupported metric. Confirm it is absent from `git ls-files` and `git status` in the repository.

### Task 3: Capture the frozen UI with the mock provider

**Files:**
- Create: private `demo/storyboard.md`
- Create: private `demo/capture_demo.py`
- Create: private `demo/raw-ui.webm`

**Interfaces:**
- Consumes: built `app/dist`, installed Playwright Chromium, and the frozen FastAPI application.
- Produces: a 1920×1080 raw recording showing synthetic patient timeline, deterministic question, answer, and evidence drawer.

- [ ] **Step 1: Prepare the existing screenshot/browser dependency without changing locks**

```powershell
uv sync --locked --extra screenshots
uv run playwright install chromium
npm ci --prefix app
npm run --prefix app build
```

Expected: all commands exit 0; no dependency file changes.

- [ ] **Step 2: Write the timed storyboard**

The storyboard must allocate: title/boundary 8s, UI timeline/question/evidence 44s, architecture boundary 13s, CI/Docker/limitations 10s. Each scene lists visible content, caption, source artifact, and a safety check.

- [ ] **Step 3: Create the deterministic capture helper outside Git**

Use this behavior in `demo/capture_demo.py`:

```python
from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

REPO_ROOT = Path(r"C:\Users\3Hml\.codex\visualizations\2026\08\03\019fc611-3a18-76c0-a9fb-36ba3a46fa23\fhir-portfolio-v020-closeout")
OUT_DIR = Path(__file__).resolve().parent
BASE_URL = "http://127.0.0.1:8126"


def wait_for_health() -> None:
    for _ in range(60):
        try:
            with urllib.request.urlopen(f"{BASE_URL}/api/health", timeout=2):
                return
        except OSError:
            time.sleep(0.5)
    raise RuntimeError("local mock backend did not become healthy")


def main() -> None:
    env = dict(os.environ)
    env["FHIR_COPILOT_PROVIDER"] = "mock"
    env.pop("FHIR_COPILOT_REQUIRE_AUTH", None)
    env.pop("FHIR_COPILOT_API_KEYS", None)
    backend = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "fhir_copilot.api.app:app", "--host", "127.0.0.1", "--port", "8126", "--log-level", "warning"],
        cwd=REPO_ROOT,
        env=env,
    )
    try:
        wait_for_health()
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            context = browser.new_context(
                viewport={"width": 1920, "height": 1080},
                locale="zh-TW",
                record_video_dir=OUT_DIR,
                record_video_size={"width": 1920, "height": 1080},
            )
            page = context.new_page()
            video = page.video
            page.goto(BASE_URL, wait_until="networkidle")
            page.wait_for_selector(".patient-card.is-selected", timeout=15_000)
            page.wait_for_timeout(8_000)
            page.get_by_role("button", name="目前有哪些生效中的診斷?").click()
            page.wait_for_selector("details", timeout=30_000)
            page.wait_for_timeout(10_000)
            page.evaluate("() => document.querySelectorAll('details').forEach(d => d.open = true)")
            page.wait_for_timeout(10_000)
            page.evaluate("() => { const d = document.querySelector('details'); d?.scrollIntoView({block: 'center'}); }")
            page.wait_for_timeout(10_000)
            context.close()
            if video is None:
                raise RuntimeError("Playwright did not create a video")
            video.save_as(OUT_DIR / "raw-ui.webm")
            browser.close()
    finally:
        backend.terminate()
        backend.wait(timeout=15)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the capture and inspect the raw recording**

Run the helper with the worktree virtual environment. Confirm `/api/health` reports mock mode before opening the browser, and use `ffprobe` to confirm 1920×1080 video. Reject and recapture if the UI shows an error, a local browser chrome/account element, or anything not clearly covered by the synthetic-data captions.

- [ ] **Step 5: Confirm no repository mutation**

Run `git status --short` in the worktree. Expected: clean; raw media and helper exist only under the private artifact root.

### Task 4: Compose and caption the 75-second demo

**Files:**
- Create: private `demo/title-card.png`
- Create: private `demo/architecture-card.png`
- Create: private `demo/end-card.png`
- Create: private `demo/demo-captions.srt`
- Create: private `FHIR_Care_Copilot_Demo_v0.2.0.mp4`

**Interfaces:**
- Consumes: `raw-ui.webm`, the social-preview visual language, committed architecture/CI evidence.
- Produces: a 1920×1080, H.264, 60–90 second captioned release asset with no audio requirement.

- [ ] **Step 1: Create three exact-text cards using canvas-design**

- Title card: `FHIR Care Copilot`, `Security-focused FHIR AI application`, `Synthea synthetic data · Non-clinical demo`.
- Architecture card: `Frontend → FastAPI → Agent loop → Read-only tools → FHIR store`, plus `patient_id is injected by the server, not selected by the model` and `reference integrity ≠ claim grounding`.
- End card: `Windows/Linux CI · PostgreSQL integration · Docker health smoke`, plus `Mock public demo · No clinical validation · No tenant isolation`.

All cards are 1920×1080 PNG, exact text, warm cream/deep teal/terracotta, and contain no medical branding.

- [ ] **Step 2: Create the exact caption file**

```srt
1
00:00:00,000 --> 00:00:08,000
技術展示｜Synthea 合成資料｜非臨床用途

2
00:00:08,000 --> 00:00:20,000
從合成病患時間軸開始；畫面不是任何人的真實病歷。

3
00:00:20,000 --> 00:00:38,000
公開展示固定使用 deterministic mock provider，不呼叫付費模型 API。

4
00:00:38,000 --> 00:00:52,000
回答附 FHIR resourceType/id；reference integrity 驗證引用存在，不等於逐句 grounded。

5
00:00:52,000 --> 00:01:05,000
模型看不到 patient_id 工具參數；server 在 tool execution 前注入 session scope。

6
00:01:05,000 --> 00:01:15,000
CI、Docker 與 failure-path 測試是工程證據，不是臨床驗證。
```

- [ ] **Step 3: Assemble a deterministic 75-second silent master**

From the private `demo/` directory, use FFmpeg to normalize each input to 1920×1080/30fps, trim or clone-pad the UI recording to 44 seconds, concatenate 8s title + 44s UI + 13s architecture + 10s end, and encode H.264/yuv420p. The filter must use `tpad=stop_mode=clone` before each fixed-duration trim so a short raw recording cannot produce a short final asset.

- [ ] **Step 4: Burn captions and create the final MP4**

Use FFmpeg's subtitles/libass filter with a Traditional-Chinese-capable installed font, white text, dark translucent outline/box, bottom-center safe margin, `libx264`, `-crf 20`, `-preset medium`, `-pix_fmt yuv420p`, and `-movflags +faststart`. Do not add synthetic voice or music.

- [ ] **Step 5: Verify duration, codec, resolution, and representative frames**

Use `ffprobe` and require: duration between 74.0 and 76.0 seconds, codec `h264`, width 1920, height 1080, pixel format `yuv420p`. Extract frames at 5, 15, 35, 55, and 70 seconds into `qa-frames/` and inspect all five at original resolution.

### Task 5: Write release notes and run the private-artifact boundary audit

**Files:**
- Create: private `release-notes-v0.2.0.md`
- Verify: private Markdown/PDF/MP4 and repository worktree

**Interfaces:**
- Consumes: public-artifact commits, validated MP4, and the final package version.
- Produces: exact release copy and a clean publication handoff.

- [ ] **Step 1: Write release notes with these sections**

```markdown
## What changed
## Security and evidence hardening
## Release verification
## Public demo boundary
## Known limitations
```

State that `v0.2.0` closes patient-scope, PII-safe observability, reference-integrity semantics, failure paths, clean install, and Docker evidence. Link the case study and CI run. Explicitly state Synthea-only, non-clinical, mock public demo, no claim-level grounding, no tenant isolation, and no clinical validation. Do not call the project production-ready.

- [ ] **Step 2: Scan all private/public copy for unsafe claims**

Search the Markdown source, release notes, README, case study, and subtitle file for `真實病歷`, `臨床可用`, `production-ready`, `every claim`, and `100% grounded`. Every occurrence must be absent or a clear negation/limitation.

- [ ] **Step 3: Prove private artifacts are outside Git**

Run `git ls-files` and `git status --short` from the repository. None of the PDF, MP4, raw video, storyboard, capture helper, caption file, release-notes source, or QA frames may appear.

- [ ] **Step 4: Record the publication handoff values**

Record SHA-256 and byte size for the final MP4 and PDF in a private handoff note. Record the expected Release asset name exactly as `FHIR_Care_Copilot_Demo_v0.2.0.mp4`; do not put checksums into the repository unless the approved public plan explicitly adds them.
