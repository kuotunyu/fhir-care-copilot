from __future__ import annotations

import tomllib
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
RELEASE_VERSION = "0.2.0"
RELEASE_DATE = "2026-08-03"


def test_package_and_citation_release_metadata_match() -> None:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    citation = yaml.safe_load((REPO_ROOT / "CITATION.cff").read_text(encoding="utf-8"))

    assert pyproject["project"]["version"] == RELEASE_VERSION
    assert citation["version"] == RELEASE_VERSION
    assert str(citation["date-released"]) == RELEASE_DATE
