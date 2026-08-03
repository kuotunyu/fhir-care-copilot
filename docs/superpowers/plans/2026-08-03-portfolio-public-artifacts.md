# FHIR Care Copilot Public Artifacts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a claims-safe, internally consistent `v0.2.0` repository surface without changing application behavior or UI.

**Architecture:** Treat release metadata, recruiter-facing documentation, the social image, and the Hugging Face upload boundary as one public-artifact contract. Pin that contract with narrow tests, then validate the unchanged backend, frontend, and Docker runtime on CPU with the mock provider.

**Tech Stack:** Markdown, TOML, YAML/CFF, Python 3.13/pytest, PNG, uv, FastAPI, React/Vite, Docker

## Global Constraints

- Target release is exactly `v0.2.0`, with packaging/runtime/CITATION version `0.2.0` and release date `2026-08-03`.
- No product feature, application behavior, UI, architecture, dependency, model configuration, or evaluation result changes.
- All patient examples are Synthea synthetic data and must never be described as real medical records.
- This is a non-clinical technical demonstration; passing tests must never be described as clinical readiness.
- Reference integrity means returned FHIR `resourceType/id` references exist in the evaluated store; it is not natural-language claim grounding.
- No paid API call, GPU, real medical data, `.env` read/display, force push, history rewrite, or co-author trailer.
- Every commit author and committer must be `kuotunyu <61350295+kuotunyu@users.noreply.github.com>`.
- Preserve the feature freeze and keep GitHub Contributors limited to `kuotunyu`.

---

## File map

- Modify `pyproject.toml`: canonical Python package version.
- Modify `uv.lock`: root editable-package version only; dependencies remain unchanged.
- Modify `CITATION.cff`: release version and date.
- Modify `src/fhir_copilot/__init__.py`: exported runtime version.
- Modify `tests/test_smoke.py`: runtime version smoke assertion.
- Create `tests/test_release_metadata.py`: canonical packaging/runtime/CITATION contract plus README and PNG assertions.
- Modify `scripts/publish_to_hf.py`: exclude internal closeout provenance from the public Space.
- Modify `tests/test_publish_to_hf.py`: prove the excluded provenance is absent from the upload set.
- Modify `tests/test_public_claims.py`: include the new public case study in claim-semantic checks.
- Create `docs/CASE_STUDY.md`: concise recruiter review path backed by committed evidence.
- Create `docs/portfolio/social-preview.png`: exact-text 1280×640 GitHub social image.
- Modify `README.md`: badges, case-study/video entry points, and honest public mock-demo wording.

### Task 1: Align release metadata

**Files:**
- Create: `tests/test_release_metadata.py`
- Modify: `pyproject.toml:1-8`
- Modify: `uv.lock` root `fhir-copilot` package entry
- Modify: `CITATION.cff:1-12`
- Modify: `src/fhir_copilot/__init__.py`
- Modify: `tests/test_smoke.py`

**Interfaces:**
- Consumes: approved target version `0.2.0` and release date `2026-08-03`.
- Produces: one canonical version/date contract used by packaging, the exported runtime version,
  citation, CI, and release creation.

- [ ] **Step 1: Write the failing metadata test**

Create `tests/test_release_metadata.py` with:

```python
from __future__ import annotations

import tomllib
from pathlib import Path

import yaml

from fhir_copilot import __version__ as runtime_version

REPO_ROOT = Path(__file__).resolve().parent.parent
RELEASE_VERSION = "0.2.0"
RELEASE_DATE = "2026-08-03"


def test_package_and_citation_release_metadata_match() -> None:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    citation = yaml.safe_load((REPO_ROOT / "CITATION.cff").read_text(encoding="utf-8"))

    assert pyproject["project"]["version"] == RELEASE_VERSION
    assert runtime_version == RELEASE_VERSION
    assert citation["version"] == RELEASE_VERSION
    assert str(citation["date-released"]) == RELEASE_DATE
```

- [ ] **Step 2: Verify the test fails for the old metadata**

Run:

```powershell
uv run pytest tests/test_release_metadata.py -q
```

Expected: FAIL because `pyproject.toml` is `0.1.0` and `CITATION.cff` has no `version: 0.2.0`.

- [ ] **Step 3: Apply the minimal version/date changes**

Change only these values:

```toml
# pyproject.toml
version = "0.2.0"
```

```python
# src/fhir_copilot/__init__.py
__version__ = "0.2.0"
```

Update `tests/test_smoke.py` to assert the exported runtime version is `0.2.0`.

```yaml
# CITATION.cff, after `type: software`
version: "0.2.0"
date-released: "2026-08-03"
```

Remove the old `date-released` line rather than leaving two keys.

- [ ] **Step 4: Refresh and inspect the lockfile**

Run:

```powershell
uv lock
git diff -- pyproject.toml uv.lock CITATION.cff
```

Expected: `uv.lock` changes only the editable `fhir-copilot` package version from `0.1.0` to `0.2.0`. Stop if any third-party dependency, hash, or resolution marker changes.

- [ ] **Step 5: Verify metadata and locked installation**

Run:

```powershell
uv lock --check
uv sync --locked
uv run pytest tests/test_release_metadata.py tests/test_smoke.py -q
```

Expected: all commands exit 0.

- [ ] **Step 6: Commit the metadata contract**

```powershell
git add -- pyproject.toml uv.lock CITATION.cff src/fhir_copilot/__init__.py tests/test_release_metadata.py tests/test_smoke.py
git -c user.name=kuotunyu -c user.email=61350295+kuotunyu@users.noreply.github.com commit -m "chore(release): align v0.2.0 metadata"
```

### Task 2: Pin the Hugging Face artifact boundary

**Files:**
- Modify: `tests/test_publish_to_hf.py` in `TestUploadSet`
- Modify: `scripts/publish_to_hf.py:58-88`

**Interfaces:**
- Consumes: `pub._simulate_upload() -> tuple[list[tuple[str, int]], int]`.
- Produces: a Space upload set that excludes `docs/superpowers/` while retaining recruiter-facing docs such as `docs/CASE_STUDY.md`.

- [ ] **Step 1: Add the failing boundary test**

Append this method to `TestUploadSet`:

```python
    def test_internal_closeout_provenance_is_not_uploaded(self) -> None:
        kept, _total = pub._simulate_upload()
        uploaded = {rel.replace("\\", "/") for rel, _size in kept}

        assert not [path for path in uploaded if path.startswith("docs/superpowers/")]
        assert "README.md" in uploaded
```

- [ ] **Step 2: Verify it fails against the current ignore list**

Run:

```powershell
uv run pytest tests/test_publish_to_hf.py::TestUploadSet::test_internal_closeout_provenance_is_not_uploaded -q
```

Expected: FAIL and report the committed design/plan paths.

- [ ] **Step 3: Add one upload-ignore pattern**

Add this documented entry to `UPLOAD_IGNORE_PATTERNS` immediately after the internal-work-file entries:

```python
    # Release-process provenance belongs in GitHub source history, not in the public demo image.
    "docs/superpowers/*",
```

Do not change application code or any other upload rule.

- [ ] **Step 4: Verify the upload boundary and README links**

Run:

```powershell
uv run pytest tests/test_publish_to_hf.py -q
uv run python scripts/publish_to_hf.py --repo-id steven0226/fhir-care-copilot
```

Expected: tests pass; dry-run reports no API call and no broken README link.

- [ ] **Step 5: Commit the release-boundary change**

```powershell
git add -- scripts/publish_to_hf.py tests/test_publish_to_hf.py
git -c user.name=kuotunyu -c user.email=61350295+kuotunyu@users.noreply.github.com commit -m "test(release): pin the Space artifact boundary"
```

### Task 3: Add the evidence-backed public case study

**Files:**
- Create: `docs/CASE_STUDY.md`
- Modify: `tests/test_public_claims.py:8-16`

**Interfaces:**
- Consumes: `README.md`, `MODEL_CARD.md`, `DATA_CARD.md`, ADR 0003, committed evaluation/load/failure reports, and GitHub Actions run `30792959630` attempt 2.
- Produces: a 4–6 minute recruiter path with no new metrics or clinical claims.

- [ ] **Step 1: Extend the public-claim contract before creating the file**

Add `"docs/CASE_STUDY.md"` to `PUBLIC_CLAIM_FILES`, then append:

```python
def test_case_study_has_required_boundaries_and_evidence_links() -> None:
    text = (REPO_ROOT / "docs/CASE_STUDY.md").read_text(encoding="utf-8")
    required = (
        "Synthea",
        "合成資料",
        "非臨床",
        "server-injected patient scope",
        "reference integrity",
        "不代表自然語言回答已逐句 grounded",
        "MODEL_CARD.md",
        "model_comparison_full.md",
        "0003-patient-scope-injection.md",
    )
    assert all(value in text for value in required)
```

- [ ] **Step 2: Verify the contract fails because the case study is absent**

Run:

```powershell
uv run pytest tests/test_public_claims.py -q
```

Expected: FAIL with `FileNotFoundError` for `docs/CASE_STUDY.md`.

- [ ] **Step 3: Create the case study with this exact information architecture**

Create `docs/CASE_STUDY.md` using these headings and evidence rules:

```markdown
# FHIR Care Copilot：安全型 AI Application Case Study

> 非臨床技術展示。所有畫面與測試資料皆來自 Synthea 合成病患，不是真實病歷。

## 一分鐘摘要
## 問題不是「讓模型看資料」，而是限制它只能看哪一位病患
## 真實資料流與信任邊界
## 三個最重要的工程決策
### 1. server-injected patient scope
### 2. tool-controlled retrieval 與嚴格 schema
### 3. reference integrity 不等於 claim grounding
## 證據：我量了什麼，也誠實標出沒量到什麼
## Failure paths 與可觀測性
## 為什麼保持 modular monolith
## 刻意不做的事
## 五分鐘審查路徑
```

The body must make these concrete points:

- Frontend sends the selected patient and question to FastAPI; authorization is not claimed from patient scope alone.
- FastAPI creates the session scope; the LLM-facing tool schemas do not expose `patient_id`; the loop injects the server-held id immediately before tool execution.
- The model can choose only an allowlisted read tool and its non-patient arguments; it cannot rewrite the injected patient scope.
- FHIR store results are structured and include evidence references; reference integrity checks existence only and **不代表自然語言回答已逐句 grounded**.
- Historical paid-provider results remain historical: three 220-case runs and repeated prompt-injection artifacts are linked, not rerun or relabelled.
- Link `../MODEL_CARD.md`, `../DATA_CARD.md`, `decisions/0003-patient-scope-injection.md`, `../reports/model_comparison_full.md`, `../reports/injection_variance.md`, and `../reports/loadtest/comparison.md` using correct relative paths from `docs/`.
- Describe auth, rate limit, budget, PII-safe logs/traces, retry/circuit breaker, JSONL/Postgres audit degradation, and Docker health as engineering controls—not proof of clinical readiness.
- State that tenant isolation, complete claim-level grounding, clinical validation, and write-back to FHIR are not delivered.
- End with a review path linking README architecture/security sections, MODEL_CARD, ADR 0003, SECURITY, CI run `https://github.com/kuotunyu/fhir-care-copilot/actions/runs/30792959630/attempts/2`, and the live mock demo.

- [ ] **Step 4: Check links and public wording**

Run:

```powershell
uv run pytest tests/test_public_claims.py tests/test_publish_to_hf.py -q
rg -n "真實病歷|臨床可用|production-ready|逐句 grounded|reference integrity" docs/CASE_STUDY.md
```

Expected: tests pass; any occurrence of “真實病歷” is only in an explicit negation, and the grounding limitation is present.

- [ ] **Step 5: Commit the case study**

```powershell
git add -- docs/CASE_STUDY.md tests/test_public_claims.py
git -c user.name=kuotunyu -c user.email=61350295+kuotunyu@users.noreply.github.com commit -m "docs: add the security case study"
```

### Task 4: Create the GitHub social preview

**Files:**
- Create: `docs/portfolio/social-preview.png`
- Modify: `tests/test_release_metadata.py`
- Private source only: `C:/Users/3Hml/.codex/visualizations/2026/08/03/019fc611-3a18-76c0-a9fb-36ba3a46fa23/fhir-care-copilot-v0.2.0-portfolio/social-preview-source/`

**Interfaces:**
- Consumes: existing `docs/screenshots/02-answer-with-evidence.png` and the approved warm cream/deep teal/terracotta visual direction.
- Produces: a 1280×640 PNG under 1 MiB for GitHub social preview and video title-card reuse.

- [ ] **Step 1: Add the failing binary-contract test**

Add `import struct` beside the existing standard-library imports, then append this test:

```python
def test_social_preview_is_the_required_png_size() -> None:
    path = REPO_ROOT / "docs/portfolio/social-preview.png"
    data = path.read_bytes()

    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert struct.unpack(">II", data[16:24]) == (1280, 640)
    assert len(data) < 1024 * 1024
```

- [ ] **Step 2: Verify the test fails because the image is absent**

Run:

```powershell
uv run pytest tests/test_release_metadata.py::test_social_preview_is_the_required_png_size -q
```

Expected: FAIL with `FileNotFoundError`.

- [ ] **Step 3: Generate the preview through the canvas-design workflow**

Use the `canvas-design` skill. Build an exact-text composition, not AI-rendered lettering:

- 60% left: cream field with title `FHIR Care Copilot`.
- Subtitle: `Security-focused FHIR AI application`.
- Boundary line: `Synthea synthetic data · Non-clinical demo`.
- Three compact labels: `Server-injected patient scope`, `Verifiable FHIR references`, `PII-safe observability`.
- Footer identifiers: `FastAPI · React · FHIR R4 · Docker`.
- 40% right: cropped current evidence-drawer screenshot with a subtle deep-teal frame.
- Do not show a real person, medical logo, hospital branding, unsupported metric, or clinical recommendation.

Store editable/source outputs outside Git at the private source path; copy only the final PNG to `docs/portfolio/social-preview.png`.

- [ ] **Step 4: Inspect and validate the final image**

Run the targeted test, then inspect the PNG at original resolution with the image viewer. Confirm the text is readable at approximately 320×160 card size and the screenshot is visibly labelled synthetic/non-clinical.

- [ ] **Step 5: Commit only the final PNG and its contract test**

```powershell
git add -- docs/portfolio/social-preview.png tests/test_release_metadata.py
git -c user.name=kuotunyu -c user.email=61350295+kuotunyu@users.noreply.github.com commit -m "docs: add the portfolio social preview"
```

### Task 5: Refresh the README entry point

**Files:**
- Modify: `README.md:1-24`
- Modify: `tests/test_release_metadata.py`

**Interfaces:**
- Consumes: `docs/CASE_STUDY.md`, planned `v0.2.0` release asset name, and the public mock Space contract.
- Produces: a truthful first-screen reviewer path with stable badge and artifact URLs.

- [ ] **Step 1: Add failing README assertions**

Append:

```python
def test_readme_exposes_release_evidence_and_mock_demo_boundary() -> None:
    text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

    required = (
        "actions/workflows/ci.yml/badge.svg?branch=main",
        "img.shields.io/github/v/release/kuotunyu/fhir-care-copilot",
        "docs/CASE_STUDY.md",
        "releases/download/v0.2.0/FHIR_Care_Copilot_Demo_v0.2.0.mp4",
        "公開 demo 固定使用 `mock` provider",
        "Synthea 合成資料",
    )
    assert all(value in text for value in required)
    assert "`provider` 是 `gemini` 才是真的在跑模型" not in text
```

- [ ] **Step 2: Verify the assertions fail against the current README**

Run:

```powershell
uv run pytest tests/test_release_metadata.py::test_readme_exposes_release_evidence_and_mock_demo_boundary -q
```

Expected: FAIL on badges, links, and the old paid-provider demo wording.

- [ ] **Step 3: Replace only the README first-screen release block**

Immediately below the H1, add badges linked to CI and the latest release. Preserve the existing non-clinical/Synthea warning. Replace the current online-demo note with wording that states:

```markdown
**線上 demo**：https://huggingface.co/spaces/steven0226/fhir-care-copilot

公開 demo 固定使用 `mock` provider 與 Synthea 合成資料：deterministic、CPU-safe、
不呼叫付費模型 API。它展示的是完整的 patient scope、tool、FHIR reference 與
failure-path 接線，不代表外部模型品質或臨床可用性。免費 Space 睡眠後首次開啟可能需要等待喚醒。

**快速審查**：[Case Study](docs/CASE_STUDY.md) ·
[75 秒展示影片](https://github.com/kuotunyu/fhir-care-copilot/releases/download/v0.2.0/FHIR_Care_Copilot_Demo_v0.2.0.mp4)
```

Do not rewrite the architecture, metrics, or limitations sections.

- [ ] **Step 4: Verify README claims and Space link closure**

Run:

```powershell
uv run pytest tests/test_release_metadata.py tests/test_public_claims.py tests/test_publish_to_hf.py -q
```

Expected: all pass and the HF dry-run reports no broken README links.

- [ ] **Step 5: Commit the reviewer entry point**

```powershell
git add -- README.md tests/test_release_metadata.py
git -c user.name=kuotunyu -c user.email=61350295+kuotunyu@users.noreply.github.com commit -m "docs: prepare the v0.2.0 reviewer entry point"
```

### Task 6: Verify the frozen application and artifact contract

**Files:**
- Verify only; no file changes expected.

**Interfaces:**
- Consumes: all public-artifact commits from Tasks 1–5.
- Produces: a clean release-candidate branch suitable for media production and publication.

- [ ] **Step 1: Verify formatting, types, backend tests, and publication dry-run**

```powershell
uv lock --check
uv sync --locked --extra postgres --extra screenshots
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
uv run python scripts/publish_to_hf.py --repo-id steven0226/fhir-care-copilot
```

Expected: every command exits 0 without a paid API call.

- [ ] **Step 2: Verify the frontend**

```powershell
npm ci --prefix app
npm run --prefix app lint
npm run --prefix app test
npm run --prefix app build
```

Expected: lint, all Vitest tests, and the production build pass.

- [ ] **Step 3: Build and smoke the exact Docker candidate**

```powershell
docker build -t fhir-care-copilot:v0.2.0-rc .
$containerId = docker run -d --name fhir-copilot-v020-verify -p 7862:7860 -e FHIR_COPILOT_PROVIDER=mock fhir-care-copilot:v0.2.0-rc
```

Poll `docker inspect --format '{{.State.Health.Status}}' fhir-copilot-v020-verify` for at most 120 seconds inside a PowerShell `try` block. From the host, call `http://127.0.0.1:7862/api/health` and require `status=ok`, `provider=mock`, `model_id=mock-deterministic`, `demo_mode=true`, and `patient_count=100`. Put container removal in the matching `finally` block so a failed assertion cannot leave it running.

- [ ] **Step 4: Clean the verification container even on failure**

```powershell
docker rm -f fhir-copilot-v020-verify
docker ps -a --filter name=fhir-copilot-v020-verify --format '{{.Names}}'
```

Expected: the second command prints nothing. The image may remain.

- [ ] **Step 5: Verify authorship and worktree state**

```powershell
git log 03ebaa75fb20ba8e4b38f0735af64cacd27796cc..HEAD --format='%H %an <%ae> %cn <%ce> %s'
git diff --check 03ebaa75fb20ba8e4b38f0735af64cacd27796cc..HEAD
git status --short --branch
```

Expected: every author/committer is `kuotunyu`, diff check is empty, and the worktree is clean.
