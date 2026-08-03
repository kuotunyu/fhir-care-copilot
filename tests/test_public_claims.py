"""公開作品集文件不得把 reference existence 說成逐 claim grounding。"""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PUBLIC_CLAIM_FILES = (
    "README.md",
    "MODEL_CARD.md",
    "DATA_CARD.md",
    "docs/EVAL.md",
    "reports/model_comparison.md",
    "reports/model_comparison_full.md",
)


@pytest.mark.parametrize("relative_path", PUBLIC_CLAIM_FILES)
def test_public_evidence_claims_stay_within_measured_semantics(relative_path: str) -> None:
    text = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
    overclaims = (
        "每個事實都要有出處",
        "病患事實一律出自 deterministic tool",
        "Citation validity 100% 是最重要的信任指標",
        "直接對照真實 store",
        "直接對照真實 FHIR store",
        "掃描真實病患資料",
        "搭配真實病患",
        "對真實 100 位病患資料",
        "對真實 1,000 位病患樣本",
        "這是架構層的保證",
    )
    found = [claim for claim in overclaims if claim in text]
    assert not found, f"{relative_path} 含過強或易誤解的公開 claim: {found}"


def test_readme_defines_reference_integrity_without_claim_grounding() -> None:
    text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "reference integrity" in text.lower()
    assert "不代表" in text
    assert "逐句" in text
