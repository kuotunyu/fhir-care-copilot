# FHIR Care Copilot Portfolio Closeout Design

Date: 2026-08-03
Status: proposed for user review
Target release: `v0.2.0`

## 1. Objective

Turn the already frozen, tested, and Docker-verified application into one coherent public
portfolio release and a separate private job-search kit. The closeout must improve reviewer
comprehension and public-artifact consistency without adding product features, changing the UI,
rerunning paid-model evaluations, or weakening the project's non-clinical boundary.

The primary audience is Taiwan-based AI Engineer and Backend Engineer hiring teams. Public copy
will remain concise Traditional Chinese with enough English technical terminology for
international reviewers. Resume bullets will be supplied in both English and Traditional Chinese.

## 2. Current evidence and gaps

The release candidate at `03ebaa75fb20ba8e4b38f0735af64cacd27796cc` has passed the full local
suite, clean-install verification, local Docker build/runtime smoke, and GitHub Actions run
`30792959630` attempt 2. No product-code blocker remains.

The closeout addresses these public-surface gaps:

- GitHub Latest Release `v0.1.0` is 80 commits behind `main` and contains the obsolete claim that
  every clinical fact is evidenced.
- `pyproject.toml` still reports `0.1.0`; `CITATION.cff` has the old release date and no current
  release version.
- GitHub repository topics and homepage are empty; the repository description is stronger than
  the hardened README/MODEL_CARD semantics.
- The Hugging Face Space was last updated on 2026-07-28, before final hardening. It currently uses
  unauthenticated paid Gemini with a USD 1 daily budget rather than the intended public mock
  deployment.
- README has screenshots but no immediately visible CI/release status badge or short case-study
  entry point.

## 3. Scope and non-goals

### In scope

- Release metadata and public documentation only.
- GitHub repository metadata, social preview, tag, and release.
- A current Hugging Face Docker Space deployment using the mock provider and synthetic data.
- A concise public case study.
- A captioned 60–90 second demo video using only the current UI and Synthea synthetic patients.
- A private bilingual resume/interview kit stored outside Git history.

### Explicitly out of scope

- Product features, application behavior, UI redesign, architecture refactoring, or additional
  production integrations.
- New clinical, diagnostic, treatment, medication, or decision-support capabilities.
- Real medical data, PHI, or wording that presents Synthea records as real patient records.
- New paid-model calls or evaluation reruns.
- Kubernetes, Kafka, microservices, multi-agent application architecture, or additional test
  breadth.
- Rewriting the existing 80-commit history, moving `v0.1.0`, force-pushing, or adding non-kuotunyu
  commit authors/co-authors.

## 4. Artifact boundary

### Public Git repository artifacts

1. `pyproject.toml`
   - Change application version from `0.1.0` to `0.2.0`.
   - Refresh only the root-package version recorded in `uv.lock`; do not change dependencies.

2. `CITATION.cff`
   - Add/update `version: 0.2.0` and `date-released: 2026-08-03`.
   - Preserve the Synthea preferred citation and Apache-2.0 license.

3. `README.md`
   - Add a CI badge linked to the current GitHub Actions workflow.
   - Add the release badge/link and a compact link to the case study and demo video.
   - Keep the existing architecture, limitations, screenshots, and evidence language intact.
   - Do not add new production or clinical claims.

4. `docs/CASE_STUDY.md`
   - One concise reviewer path: problem, threat model, architecture decision, evidence, measured
     results, failure handling, and explicit limitations.
   - Target reading time: 4–6 minutes.
   - Link to committed reports rather than copying or reinterpreting measured values.

5. `docs/portfolio/social-preview.png`
   - 1280×640, under GitHub's upload limit and preferably under 1 MB.
   - Use existing UI screenshots and an exact-text layout rather than AI-rendered text.
   - Include: project name, “Security-focused FHIR AI application”, synthetic-data boundary, and
     FastAPI / React / FHIR / Docker identifiers.

6. `docs/superpowers/specs/2026-08-03-portfolio-closeout-design.md` and
   `docs/superpowers/plans/2026-08-03-*.md`
   - Retain the approved closeout specification and execution plans as release-process provenance.
   - Exclude them from the Hugging Face publish set and recruiter-facing top-level navigation.

7. `scripts/publish_to_hf.py` and release-boundary tests
   - Exclude `docs/superpowers/` from the Space upload set without changing application behavior.
   - Add the minimum tests needed to pin version, public-claim, image, README-link, and Space-upload
     consistency for the closeout artifacts.

No MP4, private interview material, generated patient data, raw screen recording, or editor source
will be committed to Git.

### GitHub-hosted artifacts and metadata

- Repository description will be replaced with an accurate security-focused summary that does not
  equate reference integrity with claim grounding.
- Homepage will point to the Hugging Face Space.
- Topics will cover FHIR, AI application security, FastAPI, React, synthetic data, observability,
  prompt injection, and portfolio discovery.
- The generated PNG will be uploaded as the repository social preview.
- An annotated `v0.2.0` tag will point to the final release commit.
- A GitHub Release will explain the three hardening areas, link CI/Docker evidence, disclose
  synthetic-only/non-clinical use, and preserve `v0.1.0` as historical context.
- The demo MP4 will be attached to the GitHub Release rather than stored in Git history.

### Hugging Face public deployment

- Publish the exact final GitHub release snapshot using the existing allowlisted publishing path.
- Set `FHIR_COPILOT_PROVIDER=mock` as a Space variable before public verification.
- Do not expose, print, rotate, or read any provider secret.
- Keep the existing CPU-basic hardware and Synthea-only dataset.
- Verify Space build state, `/api/health`, patient count, mock model id, demo mode, patient list,
  summary, and one no-cost chat request.

### Private job-search artifacts

Private artifacts will be created under the Codex artifact workspace, outside the repository:

- `FHIR_Care_Copilot_Portfolio_Kit.pdf`
- `FHIR_Care_Copilot_Portfolio_Kit.md`
- `FHIR_Care_Copilot_Demo_v0.2.0.mp4`
- Optional editable video storyboard/source files

The kit will contain:

- English and Traditional Chinese resume bullets.
- 30-second, 2-minute, and 5-minute interview narratives.
- Architecture/security trade-off explanations.
- A question bank covering patient scope versus authorization, reference integrity versus
  grounding, Synthea, modular monolith choice, failure paths, and production limitations.
- A concise LinkedIn/CakeResume project post.

## 5. Visual and video direction

Visual language will reuse the existing “warm clinical folder” product identity: cream background,
deep teal, terracotta accent, and restrained red only for safety boundaries. The social image and
video must look like the current product rather than a separate marketing brand.

The captioned demo will be 1920×1080, approximately 75 seconds, with no synthetic voice required:

1. 0–8s — problem and non-clinical/synthetic boundary.
2. 8–20s — select a clearly labelled Synthea synthetic patient and show the timeline.
3. 20–38s — ask a supported question using the mock provider.
4. 38–52s — open evidence and show FHIR `resourceType/id` references.
5. 52–65s — explain server-injected patient scope and PII-safe observability with a compact
   architecture visual.
6. 65–75s — show CI/Docker evidence and explicit non-clinical limitations.

The recording must not show `.env`, tokens, local usernames/paths, browser account details, or real
medical information. Every displayed patient record must be labelled synthetic.

## 6. Public copy direction

Recommended repository description:

> Security-focused FHIR AI application using Synthea: server-injected patient scope,
> tool-controlled retrieval, verifiable FHIR references, PII-safe observability, FastAPI, React,
> and Docker.

Recommended topics:

`fhir`, `healthcare`, `ai-agent`, `llm-security`, `fastapi`, `react`, `synthetic-data`,
`observability`, `prompt-injection`, `docker`, `portfolio`

Release and case-study copy must use “reference integrity” only for existence checks on returned
FHIR references and explicitly state that this is not natural-language claim grounding.

## 7. Implementation and publication sequence

1. Create public text and visual artifacts on `codex/portfolio-v0.2.0-closeout`.
2. Generate the private kit and demo video outside the repository.
3. Run public-claim/link checks, formatting/static checks, full CPU/mock backend and frontend suites,
   clean-install verification, and local Docker smoke where relevant.
4. Commit the release closeout as `kuotunyu` with no co-author trailer.
5. Fast-forward `main` only after confirming `origin/main` has not diverged.
6. Push normally and wait for all GitHub Actions jobs to pass.
7. Create annotated tag `v0.2.0` and GitHub Release; upload the MP4 release asset.
8. Update GitHub description, topics, homepage, and social preview.
9. Publish the final release snapshot to Hugging Face, switch the public provider to mock, and wait
   for the Space to become running/healthy.
10. Run public health/API smoke without paid calls and verify all public links.

Any divergence, CI failure, failed checksum, failed HF build, authentication uncertainty, or
unexpected public artifact stops publication. No force push or opportunistic product fix is
allowed.

## 8. Verification and acceptance criteria

The closeout is complete only when all of the following are true:

- GitHub default branch, `v0.2.0` tag, Release target, and local `main` resolve to the same commit.
- The final commit author and committer are `kuotunyu
  <61350295+kuotunyu@users.noreply.github.com>` with no co-author trailer.
- GitHub Contributors still contains only `kuotunyu`.
- GitHub Actions is green, including Windows/Linux tests, frontend, Postgres, Docker build, and
  container smoke.
- README, case study, release notes, repository description, MODEL_CARD, and DATA_CARD make
  mutually consistent claims.
- Social preview renders legibly at desktop and small-card sizes.
- Demo video contains no real patient data, secret, local path, clinical recommendation, or claim
  that tests prove clinical readiness.
- The MP4 is a Release asset and is not in Git history.
- Hugging Face reports `provider=mock`, `model_id=mock-deterministic`, `demo_mode=true`,
  `patient_count=100`, CPU hardware, and successful health/API smoke.
- No paid API call is made during closeout verification.
- The private kit is usable but absent from `git ls-files` and the GitHub Release.
- Worktrees are clean and no release container remains running after verification.

## 9. Rollback and preservation

- Preserve `v0.1.0`; do not retag or edit its source history.
- If GitHub metadata is wrong, restore the previous text without changing commits.
- If the HF deployment fails, keep the prior Space revision available and do not expose paid API
  access as a fallback.
- If `v0.2.0` publication has not occurred, fix only closeout artifacts on the branch. If the tag or
  Release already exists, stop and request explicit approval before replacing or deleting any
  public artifact.

## 10. Definition of done

The outcome is a frozen `v0.2.0` portfolio release with one trustworthy public story, one safe
mock/synthetic live demo, one short video, one recruiter-friendly case study, and one private
bilingual interview kit. No application feature or architecture behavior changes as part of this
work.
